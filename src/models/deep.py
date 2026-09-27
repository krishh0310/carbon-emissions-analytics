"""Deep panel forecasters. ONE global model for all 36 states/UTs with a learned STATE EMBEDDING.

Every network maps (x[B,W,F], state[B], static[B,S], fut[B,H,K]) -> (B, H, 3) quantiles of the log-growth target,
except DeepAR which emits a Gaussian (mu, sigma) per horizon (converted to quantiles).
"""
from __future__ import annotations

import math
import time

import lightning as L
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from src.data.features import Windows

QS = torch.tensor([0.1, 0.5, 0.9])
Z90 = 1.2815515655446004  # N(0,1) 90th percentile


class JointEmb(nn.Module):
    """Factorised (state, sector) embedding: e = E_state[s] + E_sector[k]. Input is the packed unit index
    s * n_sectors + k, so every architecture keeps its (x, state, ...) signature. n_sectors=1 -> plain state embedding."""

    def __init__(self, n_states, n_sectors, dim):
        super().__init__()
        self.n_sectors, self.embedding_dim = n_sectors, dim
        self.state = nn.Embedding(n_states, dim)
        self.sector = nn.Embedding(n_sectors, dim)
        if n_sectors == 1:
            nn.init.zeros_(self.sector.weight)
            self.sector.weight.requires_grad_(False)

    def forward(self, unit):
        return self.state(unit // self.n_sectors) + self.sector(unit % self.n_sectors)


class _Base(nn.Module):
    def __init__(self, n_feat, n_states, n_static, n_fut, horizon, hidden=64, emb=8, dropout=0.3, n_sectors=1, **_):
        super().__init__()
        self.H, self.hidden = horizon, hidden
        self.emb = JointEmb(n_states, n_sectors, emb)
        self.n_in = n_feat + emb
        self.drop = nn.Dropout(dropout)
        self.n_static, self.n_fut = n_static, n_fut

    def _seq(self, x, state):
        e = self.emb(state)[:, None, :].expand(-1, x.shape[1], -1)
        return torch.cat([x, e], -1)


class RNN(_Base):
    def __init__(self, cell="lstm", n_layers=2, **kw):
        super().__init__(**kw)
        rnn = nn.LSTM if cell == "lstm" else nn.GRU
        self.rnn = rnn(self.n_in, self.hidden, n_layers, batch_first=True, dropout=kw.get("dropout", 0.3) if n_layers > 1 else 0)
        self.head = nn.Sequential(nn.Linear(self.hidden + self.n_static, self.hidden), nn.ReLU(), self.drop,
                                  nn.Linear(self.hidden, self.H * 3))

    def forward(self, x, state, static, fut):
        o, _ = self.rnn(self._seq(x, state))
        return self.head(torch.cat([o[:, -1], static], -1)).view(-1, self.H, 3), {}


class TCN(_Base):
    """Causal dilated residual convolutions (dilations 1,2,4,...)."""

    def __init__(self, n_layers=3, kernel=3, **kw):
        super().__init__(**kw)
        self.inp = nn.Conv1d(self.n_in, self.hidden, 1)
        self.blocks = nn.ModuleList()
        self.pads = []
        for i in range(n_layers):
            d = 2 ** i
            self.pads.append((kernel - 1) * d)
            self.blocks.append(nn.Conv1d(self.hidden, self.hidden, kernel, dilation=d))
        self.head = nn.Sequential(nn.Linear(self.hidden + self.n_static, self.hidden), nn.ReLU(), self.drop,
                                  nn.Linear(self.hidden, self.H * 3))

    def forward(self, x, state, static, fut):
        h = self.inp(self._seq(x, state).transpose(1, 2))
        for pad, conv in zip(self.pads, self.blocks, strict=True):
            h = h + self.drop(F.relu(conv(F.pad(h, (pad, 0)))))
        return self.head(torch.cat([h[:, :, -1], static], -1)).view(-1, self.H, 3), {}


class Seq2SeqAttn(_Base):
    """GRU encoder -> GRU decoder over horizons (inputs: known-future covariates) with Bahdanau attention."""

    def __init__(self, n_layers=1, **kw):
        super().__init__(**kw)
        hd = self.hidden
        self.enc = nn.GRU(self.n_in, hd, n_layers, batch_first=True)
        self.dec = nn.GRUCell(self.n_fut + hd + self.emb.embedding_dim, hd)
        self.Wq, self.Wk, self.v = nn.Linear(hd, hd, bias=False), nn.Linear(hd, hd), nn.Linear(hd, 1, bias=False)
        self.out = nn.Sequential(nn.Linear(2 * hd + self.n_static, hd), nn.ReLU(), self.drop, nn.Linear(hd, 3))

    def forward(self, x, state, static, fut):
        enc, h = self.enc(self._seq(x, state))
        h, keys, e = h[-1], self.Wk(enc), self.emb(state)
        ctx = enc[:, -1]
        outs, atts = [], []
        for t in range(self.H):
            h = self.dec(torch.cat([fut[:, t], ctx, e], -1), h)
            a = torch.softmax(self.v(torch.tanh(keys + self.Wq(h)[:, None])).squeeze(-1), -1)  # (B, W)
            ctx = (a[:, :, None] * enc).sum(1)
            outs.append(self.out(torch.cat([h, ctx, static], -1)))
            atts.append(a)
        return torch.stack(outs, 1), {"attention": torch.stack(atts, 1)}  # (B,H,W)


class GRN(nn.Module):
    """Gated residual network (TFT)."""

    def __init__(self, d_in, d, d_out=None, d_ctx=0, dropout=0.1):
        super().__init__()
        d_out = d_out or d
        self.l1, self.l2 = nn.Linear(d_in + d_ctx, d), nn.Linear(d, 2 * d_out)
        self.skip = nn.Linear(d_in, d_out) if d_in != d_out else nn.Identity()
        self.norm, self.drop = nn.LayerNorm(d_out), nn.Dropout(dropout)

    def forward(self, x, ctx=None):
        h = x if ctx is None else torch.cat([x, ctx], -1)
        h = self.drop(F.elu(self.l1(h)))
        return self.norm(self.skip(x) + F.glu(self.l2(h), -1))


class TFTLite(_Base):
    """Static enrichment + variable selection + GRU enc/dec + multi-head attention + quantile head."""

    def __init__(self, n_heads=4, **kw):
        super().__init__(**kw)
        d, nf = self.hidden, kw["n_feat"]
        self.nf = nf
        self.static_enc = GRN(self.n_static + self.emb.embedding_dim, d, dropout=kw.get("dropout", 0.1))
        self.var_proj = nn.Parameter(torch.randn(nf, d) * 0.1)  # per-variable embedding of scalar input
        self.var_sel = GRN(nf, d, nf, d_ctx=d)                   # -> softmax weights over variables
        self.fut_proj = nn.Linear(self.n_fut, d)
        self.enc, self.dec = nn.GRU(d, d, batch_first=True), nn.GRU(d, d, batch_first=True)
        self.attn = nn.MultiheadAttention(d, n_heads, dropout=kw.get("dropout", 0.1), batch_first=True)
        self.post = GRN(d, d)
        self.head = nn.Linear(d, 3)

    def forward(self, x, state, static, fut):
        B, W, _ = x.shape
        s = self.static_enc(torch.cat([static, self.emb(state)], -1))           # (B,d)
        wts = torch.softmax(self.var_sel(x, s[:, None].expand(-1, W, -1)), -1)  # (B,W,F)
        emb = (wts[..., None] * (x[..., None] * self.var_proj)).sum(2)          # (B,W,d)
        enc, h = self.enc(emb, s[None].contiguous())
        dec, _ = self.dec(self.fut_proj(fut) + s[:, None], h)
        seq = torch.cat([enc, dec], 1)
        causal = torch.triu(torch.ones(W + self.H, W + self.H, dtype=torch.bool, device=x.device), 1)
        att, a = self.attn(seq, seq, seq, attn_mask=causal, need_weights=True, average_attn_weights=True)
        out = self.post(self.drop(att[:, W:]) + dec)
        return self.head(out), {"attention": a[:, W:, :W], "variable_weights": wts.mean(1)}


class DeepAR(_Base):
    """DeepAR-style Gaussian likelihood head on a GRU encoder (direct multi-horizon, no ancestral sampling)."""
    gaussian = True

    def __init__(self, n_layers=2, **kw):
        super().__init__(**kw)
        self.rnn = nn.GRU(self.n_in, self.hidden, n_layers, batch_first=True, dropout=kw.get("dropout", 0.3))
        self.head = nn.Linear(self.hidden + self.n_static, self.H * 2)

    def forward(self, x, state, static, fut):
        o, _ = self.rnn(self._seq(x, state))
        p = self.head(self.drop(torch.cat([o[:, -1], static], -1))).view(-1, self.H, 2)
        mu, sigma = p[..., 0], F.softplus(p[..., 1]) + 1e-3
        return torch.stack([mu - Z90 * sigma, mu, mu + Z90 * sigma], -1), {"mu": mu, "sigma": sigma}


class MultiTask(nn.Module):
    """Cross-learning multi-task model over ALL 7 sectors of a state in one forward pass.

    x (B, K, W, F) -> shared per-sector temporal encoder (weights shared across sectors, sector identity via the joint
    (state, sector) embedding) -> K sector tokens -> cross-sector Transformer layer (sectors attend to each other: a
    state's transport and power co-move) -> per-token quantile head -> (B, K, H, 3).
    tft=True swaps the GRU encoder for TFT-style variable selection + GRU + temporal self-attention."""

    def __init__(self, n_feat, n_states, n_sectors, n_static, n_fut, horizon, hidden=64, emb=8, dropout=0.2,
                 n_heads=4, tft=False, **_):
        super().__init__()
        d, self.H, self.K, self.tft = hidden, horizon, n_sectors, tft
        self.emb = JointEmb(n_states, n_sectors, emb)
        self.static_proj = nn.Linear(n_static + emb, d)
        if tft:
            self.var_proj = nn.Parameter(torch.randn(n_feat, d) * 0.1)
            self.var_sel = GRN(n_feat, d, n_feat, d_ctx=d, dropout=dropout)
            self.enc = nn.GRU(d, d, batch_first=True)
            self.tattn = nn.MultiheadAttention(d, n_heads, dropout=dropout, batch_first=True)
        else:
            self.enc = nn.GRU(n_feat + emb, d, 2, batch_first=True, dropout=dropout)
        self.fut_proj = nn.Linear(n_fut * horizon, d)
        self.cross = nn.TransformerEncoderLayer(d, n_heads, 2 * d, dropout, batch_first=True, norm_first=True)
        self.head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Dropout(dropout), nn.Linear(d, horizon * 3))

    def forward(self, x, state, static, fut):
        B, K, W, F_ = x.shape
        units = state[:, None] * K + torch.arange(K, device=x.device)[None]           # (B,K)
        e = self.emb(units)                                                            # (B,K,E)
        ctx = self.static_proj(torch.cat([static[:, None].expand(-1, K, -1), e], -1))  # (B,K,d)
        xs = x.reshape(B * K, W, F_)
        if self.tft:
            c = ctx.reshape(B * K, 1, -1).expand(-1, W, -1)
            wts = torch.softmax(self.var_sel(xs, c), -1)
            h, _ = self.enc((wts[..., None] * (xs[..., None] * self.var_proj)).sum(2), ctx.reshape(1, B * K, -1).contiguous())
            a, att = self.tattn(h[:, -1:], h, h, need_weights=True)
            tok = (a[:, 0] + h[:, -1]).view(B, K, -1)
            aux = {"attention": att[:, 0].view(B, K, W).mean(1), "variable_weights": wts.mean(1).view(B, K, F_).mean(1)}
        else:
            h, _ = self.enc(torch.cat([xs, e.reshape(B * K, 1, -1).expand(-1, W, -1)], -1))
            tok, aux = h[:, -1].view(B, K, -1), {}
        tok = tok + ctx + self.fut_proj(fut.reshape(B, -1))[:, None]
        tok = self.cross(tok)
        return self.head(tok).view(B, K, self.H, 3), aux


ARCH = {
    "lstm": lambda **kw: RNN(cell="lstm", **kw), "gru": lambda **kw: RNN(cell="gru", **kw), "tcn": TCN,
    "seq2seq_attn": Seq2SeqAttn, "tft": TFTLite, "deepar": DeepAR,
    "mt_gru": lambda **kw: MultiTask(tft=False, **kw), "mt_tft": lambda **kw: MultiTask(tft=True, **kw),
}


class Lit(L.LightningModule):
    def __init__(self, arch: str, lr: float = 1e-3, weight_decay: float = 1e-4, **net_kw):
        super().__init__()
        self.save_hyperparameters()
        self.net = ARCH[arch](**net_kw)
        self.lr, self.wd = lr, weight_decay
        self.gaussian = getattr(self.net, "gaussian", False)

    def forward(self, b):
        return self.net(b["x"], b["state"], b["static"], b["fut"])

    def _loss(self, b, mask):
        q, aux = self(b)
        y = torch.nan_to_num(b["y"])
        m = mask.float() / b["scale"].unsqueeze(-1)  # MASE-style weighting: each series contributes equally
        if self.gaussian:
            nll = 0.5 * ((y - aux["mu"]) / aux["sigma"]) ** 2 + torch.log(aux["sigma"])
            loss = (nll * m).sum() / mask.sum().clamp(min=1)
        else:
            e = y[..., None] - q
            qs = QS.to(q.device)
            loss = ((torch.maximum(qs * e, (qs - 1) * e)).sum(-1) * m).sum() / mask.sum().clamp(min=1)
        mase = ((q[..., 1] - y).abs() * m).sum() / mask.sum().clamp(min=1)
        return loss, mase

    def training_step(self, b, _):
        loss, _ = self._loss(b, b["m_train"])
        self.log("train_loss", loss, prog_bar=False, batch_size=len(b["y"]))
        return loss

    def validation_step(self, b, _):
        loss, mase = self._loss(b, b["m_val"])
        self.log("val_loss", loss, batch_size=len(b["y"]))
        self.log("val_mase", mase, prog_bar=True, batch_size=len(b["y"]))

    def configure_optimizers(self):
        return torch.optim.AdamW(self.parameters(), lr=self.lr, weight_decay=self.wd)


def _tensors(w: Windows) -> dict[str, torch.Tensor]:
    return {"x": torch.from_numpy(w.X), "state": torch.from_numpy(w.unit).long(), "static": torch.from_numpy(w.static),
            "fut": torch.from_numpy(w.fut), "y": torch.from_numpy(w.y), "scale": torch.from_numpy(w.scale).float(),
            "m_train": torch.from_numpy(w.mask("train")), "m_val": torch.from_numpy(w.mask("val"))}


def state_origin_groups(w: Windows) -> np.ndarray:
    """(M, K) sample indices: all K sector samples of one (state, origin), ordered by sector. Drops incomplete groups."""
    K = len(w.sectors)
    key = w.state.astype(np.int64) * 10_000 + w.origin.astype(np.int64)
    out = []
    for k in np.unique(key):
        idx = np.flatnonzero(key == k)
        if len(idx) == K:
            out.append(idx[np.argsort(w.sector[idx])])
    return np.array(out, dtype=np.int64).reshape(-1, K)


def _tensors_mt(w: Windows, G: np.ndarray) -> dict[str, torch.Tensor]:
    t = _tensors(w)
    return {"x": t["x"][G], "state": torch.from_numpy(w.state[G[:, 0]]).long(), "static": t["static"][G[:, 0]],
            "fut": t["fut"][G[:, 0]], "y": t["y"][G], "scale": t["scale"][G], "m_train": t["m_train"][G], "m_val": t["m_val"][G]}


class _DS(torch.utils.data.Dataset):
    def __init__(self, t, idx):
        self.t, self.idx = t, idx

    def __len__(self):
        return len(self.idx)

    def __getitem__(self, i):
        j = self.idx[i]
        return {k: v[j] for k, v in self.t.items()}


class DeepForecaster:
    """Adapter giving deep models the same fit/predict interface as baselines."""

    def __init__(self, arch: str, hidden=64, n_layers=2, dropout=0.3, lr=1e-3, weight_decay=1e-4, emb=8,
                 batch_size=64, max_epochs=300, patience=25, seed=42, ckpt_dir=None, exclude_states=(), **_):
        self.name, self.arch = arch, arch
        self.multitask = arch.startswith("mt_")
        self.exclude_states = np.array(sorted(exclude_states), dtype=int)  # E14: held-out states (never trained on)
        self.kw = dict(hidden=hidden, n_layers=n_layers, dropout=dropout, emb=emb)
        self.lr, self.wd, self.bs, self.max_epochs, self.patience, self.seed = lr, weight_decay, batch_size, max_epochs, patience, seed
        self.ckpt_dir = ckpt_dir

    def fit(self, w: Windows):
        L.seed_everything(self.seed, workers=True)
        if self.multitask:
            self.G = state_origin_groups(w)
            t = _tensors_mt(w, self.G)
            unit_state = t["state"].numpy()
        else:
            t = _tensors(w)
            unit_state = w.state
        if len(self.exclude_states):
            held = torch.from_numpy(np.isin(unit_state, self.exclude_states))
            shape = (-1,) + (1,) * (t["m_train"].dim() - 1)
            t["m_train"] = t["m_train"] & ~held.view(shape)
            t["m_val"] = t["m_val"] & ~held.view(shape)
        flat = lambda m: m.reshape(len(m), -1).any(1).numpy()  # noqa: E731
        tr, va = np.flatnonzero(flat(t["m_train"])), np.flatnonzero(flat(t["m_val"]))
        kw = dict(n_feat=w.X.shape[2], n_states=len(w.codes), n_sectors=len(w.sectors), n_static=w.static.shape[1], n_fut=w.fut.shape[2],
                  horizon=w.y.shape[1], **self.kw)
        self.model = Lit(self.arch, lr=self.lr, weight_decay=self.wd, **kw)
        g = torch.Generator().manual_seed(self.seed)
        dl_tr = torch.utils.data.DataLoader(_DS(t, tr), batch_size=self.bs, shuffle=True, generator=g)  # shuffles SAMPLES, never time order
        dl_va = torch.utils.data.DataLoader(_DS(t, va), batch_size=1024)
        cbs = [L.pytorch.callbacks.EarlyStopping("val_mase", patience=self.patience, mode="min")]
        ck = None
        if self.ckpt_dir:
            ck = L.pytorch.callbacks.ModelCheckpoint(self.ckpt_dir, filename=self.arch, monitor="val_mase", mode="min",
                                                     save_top_k=1, enable_version_counter=False)
            cbs.append(ck)
        t0 = time.time()
        self.trainer = L.Trainer(max_epochs=self.max_epochs, callbacks=cbs, gradient_clip_val=1.0, deterministic=True,
                                 logger=False, enable_progress_bar=False, enable_model_summary=False,
                                 accelerator="cpu", enable_checkpointing=ck is not None)
        self.trainer.fit(self.model, dl_tr, dl_va)
        if ck and ck.best_model_path:
            self.model = Lit.load_from_checkpoint(ck.best_model_path)
            self.checkpoint_path = ck.best_model_path
        self.train_time = time.time() - t0
        self.best_val_mase = float(self.trainer.callback_metrics.get("val_mase", math.nan))
        if len(self.exclude_states):  # unseen states get the mean learned state embedding (zero-shot transfer)
            with torch.no_grad():
                E = self.model.net.emb.state.weight
                keep = torch.ones(len(E), dtype=torch.bool)
                keep[torch.from_numpy(self.exclude_states)] = False
                E[~keep] = E[keep].mean(0)
        return self

    @torch.no_grad()
    def predict(self, w: Windows, return_aux: bool = False):
        self.model.eval()
        if self.multitask:
            G = state_origin_groups(w)
            qg, aux = self.model(_tensors_mt(w, G))
            qg = torch.sort(qg, -1).values.numpy()
            q = np.full((len(w.y), w.y.shape[1], 3), np.nan)
            q[G.reshape(-1)] = qg.reshape(-1, qg.shape[2], 3)
        else:
            q, aux = self.model(_tensors(w))
            q = torch.sort(q, -1).values.numpy()
        return (q, {k: v.numpy() for k, v in aux.items()}) if return_aux else q
