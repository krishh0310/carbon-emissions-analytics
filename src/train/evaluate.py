"""Metrics (on CO2 level, MtCO2) and MinT hierarchical reconciliation (national = sum of 36 states)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.features import HORIZONS, Windows, split_of


def to_level(w: Windows, q: np.ndarray) -> np.ndarray:
    """(N,H,3) log-growth quantiles -> MtCO2 levels."""
    return np.expm1(w.base[:, None, None] + q)


def metric_rows(model: str, w: Windows, q: np.ndarray, train_time: float = np.nan,
                reconciled_p50: np.ndarray | None = None, target: str = "co2_mt") -> list[dict]:
    """Per (unit, horizon, split) + aggregate rows. Unit = state (v1) or state x sector (v2; aggregate rows per sector
    and 'ALL'). MASE scale = unit's train in-sample naive-1 MAE on level."""
    lvl = to_level(w, q)[..., 1]
    true = np.expm1(w.base[:, None] + w.y)
    naive_scale = _level_scale(w)
    multi = len(w.sectors) > 1
    groups: list[tuple[str, str, np.ndarray]] = []
    for u in np.unique(w.unit):
        s, k = divmod(int(u), len(w.sectors))
        groups.append((w.codes[s], w.sectors[k], w.unit == u))
    material = np.ones(len(w.y), bool)
    if multi:
        # aggregates exclude near-zero cells (train mean < 10 kt, e.g. power in UTs without plants): their MASE
        # denominators are ~0 and would dominate the mean. Per-cell rows are still reported for every cell.
        material = _train_mean_level(w)[w.unit] >= 0.01
        groups += [("ALL", sec, (w.sector == k) & material) for k, sec in enumerate(w.sectors)]
    groups.append(("ALL", "ALL" if multi else "TOTAL", material))
    rows = []
    for split in ("train", "val", "test"):
        m = w.mask(split) & ~np.isnan(lvl)
        for hi, h in enumerate(HORIZONS):
            for code, sec, g in groups:
                sel = m[:, hi] & g
                if not sel.any():
                    continue
                yt, yp = true[sel, hi], lvl[sel, hi]
                sc = naive_scale[w.unit[sel]]
                e = yp - yt
                r = {"model": model, "level": "state_sector" if multi else "state", "state_code": code, "sector": sec,
                     "target": target, "horizon": h, "split": split, "n": int(sel.sum()),
                     "mae": np.mean(np.abs(e)), "rmse": np.sqrt(np.mean(e ** 2)),
                     "mape": 100 * np.mean(np.abs(e) / np.maximum(np.abs(yt), 1e-6)),
                     "smape": 100 * np.mean(2 * np.abs(e) / np.maximum(np.abs(yt) + np.abs(yp), 1e-6)),
                     "mase": np.mean(np.abs(e) / sc),
                     "r2": 1 - np.sum(e ** 2) / max(np.sum((yt - yt.mean()) ** 2), 1e-12) if sel.sum() > 1 else np.nan,
                     "reconciled_mase": np.nan, "training_time": train_time}
                if reconciled_p50 is not None:
                    r["reconciled_mase"] = np.nanmean(np.abs(reconciled_p50[sel, hi] - yt) / sc)
                rows.append(r)
    return rows


def _train_mean_level(w: Windows) -> np.ndarray:
    n = len(w.codes) * len(w.sectors)
    out = np.zeros(n)
    for u in np.unique(w.unit):
        tr = (w.unit == u) & (w.origin <= 2014)
        out[u] = float(np.mean(np.expm1(w.hist[tr][:, -1]))) if tr.any() else 0.0
    return out


def _level_scale(w: Windows) -> np.ndarray:
    """Per-unit mean |Δ level| over train years (level scale for MASE), indexed by w.unit."""
    n = len(w.codes) * len(w.sectors)
    sc = np.full(n, np.nan)
    for u in np.unique(w.unit):
        tr = (w.unit == u) & (w.origin <= 2014)
        lv = np.expm1(w.hist[tr][:, -1]) if tr.any() else np.array([])
        sc[u] = np.mean(np.abs(np.diff(lv))) if len(lv) > 2 else np.nan
    med = np.nanmedian(sc)
    # series that never move in train (e.g. zero-emission sector in a small UT) get a small floor, not the median
    sc = np.where(np.isfinite(sc) & (sc > 0), sc, max(1e-4, 0.01 * med))
    return np.maximum(sc, 1e-3) if len(w.sectors) > 1 else sc  # 1 kt floor for state x sector cells


# ---- MinT -------------------------------------------------------------------------------------------
def summing_matrix(n: int) -> np.ndarray:
    return np.vstack([np.ones((1, n)), np.eye(n)])  # rows: [national, state_1..state_n]


def mint_shrink_cov(res: np.ndarray) -> np.ndarray:
    """Schäfer-Strimmer shrinkage of residual covariance towards its diagonal (MinT-shrink, Wickramasuriya 2019)."""
    res = res[~np.isnan(res).any(1)]
    T, n = res.shape
    if T < 3:
        return np.diag(np.nanvar(res, 0) + 1e-9)
    cov = np.cov(res, rowvar=False, bias=True)
    sd = np.sqrt(np.diag(cov)) + 1e-12
    xs = (res - res.mean(0)) / sd
    corr = cov / np.outer(sd, sd)
    v = np.zeros_like(corr)
    for t in range(T):
        v += (np.outer(xs[t], xs[t]) - corr) ** 2
    v *= T / (T - 1) ** 3
    off = ~np.eye(n, dtype=bool)
    lam = float(np.clip(v[off].sum() / max((corr[off] ** 2).sum(), 1e-12), 0, 1))
    shrunk = lam * np.diag(np.diag(cov)) + (1 - lam) * cov
    return shrunk + 1e-9 * np.eye(n)


def mint(base: np.ndarray, W: np.ndarray) -> np.ndarray:
    """base: (..., n+1) [national, states]. Returns reconciled (..., n+1), coherent: national == sum(states)."""
    n = base.shape[-1] - 1
    S = summing_matrix(n)
    Wi = np.linalg.pinv(W)
    G = np.linalg.solve(S.T @ Wi @ S, S.T @ Wi)
    return base @ (S @ G).T


def reconcile_panel(w: Windows, lvl_p50: np.ndarray, national_base: dict[tuple[int, int], float],
                    Ws: dict[int, np.ndarray] | None = None) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """Reconcile state P50 levels per (origin year, horizon). national_base[(origin, h_idx)] = national base forecast.
    Residual covariance per horizon is estimated from TRAIN-split errors only, or passed in via `Ws` (e.g. when
    reconciling production forecasts whose origin has no residuals). With fewer residual rows than series the
    full covariance is unreliable, so MinT falls back to its variance-scaled diagonal form (WLS_var).
    Returns (reconciled state P50 (N,H), {h_idx: W})."""
    n = len(w.codes)
    true = np.expm1(w.base[:, None] + w.y)
    out = lvl_p50.copy()
    used: dict[int, np.ndarray] = {}
    for hi in range(lvl_p50.shape[1]):
        # build residual matrix (origins x [national, states]) on train targets
        res_rows, frames = [], {}
        for o in np.unique(w.origin):
            sel = w.origin == o
            if sel.sum() != n:
                continue
            idx = np.flatnonzero(sel)[np.argsort(w.state[sel])]
            frames[o] = idx
            ty = o + HORIZONS[hi]
            if split_of(ty) == "train" and not np.isnan(true[idx, hi]).any():
                nat_true = true[idx, hi].sum()
                res_rows.append(np.r_[national_base[(o, hi)] - nat_true, lvl_p50[idx, hi] - true[idx, hi]])
        if Ws is not None and hi in Ws:
            W = Ws[hi]
        elif len(res_rows) > n + 1:
            W = mint_shrink_cov(np.array(res_rows))
        elif len(res_rows) >= 3:
            W = np.diag(np.nanvar(np.array(res_rows), 0) + 1e-9)
        else:
            W = np.eye(n + 1)
        used[hi] = W
        for o, idx in frames.items():
            b = np.r_[national_base[(o, hi)], lvl_p50[idx, hi]]
            if np.isnan(b).any():
                continue
            out[idx, hi] = mint(b[None], W)[0, 1:]
    return out, used


def national_drift_base(w: Windows) -> dict[tuple[int, int], float]:
    """National base forecast: random walk with drift on log national total (drift from the 10-year input window)."""
    out = {}
    for o in np.unique(w.origin):
        sel = w.origin == o
        nat = np.log(np.expm1(w.hist[sel]).sum(0))
        slope = np.mean(np.diff(nat))
        for hi, h in enumerate(HORIZONS):
            out[(o, hi)] = float(np.exp(nat[-1] + slope * h))
    return out


def to_frame(w: Windows, q: np.ndarray, model: str, reconciled: np.ndarray | None = None) -> pd.DataFrame:
    lvl = to_level(w, q)
    rows = []
    for hi, h in enumerate(HORIZONS):
        rows.append(pd.DataFrame({
            "model": model, "state_code": np.array(w.codes)[w.state], "origin": w.origin, "horizon": h,
            "year": w.origin + h, "p10": lvl[:, hi, 0], "p50": lvl[:, hi, 1], "p90": lvl[:, hi, 2],
            "p50_reconciled": reconciled[:, hi] if reconciled is not None else np.nan,
            "actual": np.expm1(w.base + w.y[:, hi])}))
    return pd.concat(rows, ignore_index=True)


# ---- v2: two-level hierarchy (national -> states / sectors -> state x sector) ------------------------
def summing_matrix_2level(n_states: int, n_sectors: int) -> np.ndarray:
    """Rows: [national, state_1..state_S, sector_1..sector_K, cell_(s,k) ...]; bottom ordered state-major."""
    n = n_states * n_sectors
    nat = np.ones((1, n))
    st = np.kron(np.eye(n_states), np.ones((1, n_sectors)))
    sec = np.kron(np.ones((1, n_states)), np.eye(n_sectors))
    return np.vstack([nat, st, sec, np.eye(n)])


def mint_bottom(base: np.ndarray, S: np.ndarray, w_diag: np.ndarray) -> np.ndarray:
    """MinT with diagonal W (WLS-var): reconciled bottom = (S'W⁻¹S)⁻¹ S'W⁻¹ ŷ. base (..., m)."""
    Wi = 1.0 / np.maximum(w_diag, 1e-12)
    A = S.T * Wi
    G = np.linalg.solve(A @ S, A)
    return base @ G.T


def reconcile_two_level(w: Windows, lvl_p50: np.ndarray, state_base: dict | None = None,
                        wdiag: dict[int, np.ndarray] | None = None) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """Coherent state x sector forecasts: Σ cells == state totals, Σ cells == sector totals, Σ == national.

    Base forecasts: cells = model P50; state totals = `state_base[(state_idx, origin, h_idx)]` (direct state-total
    model; drift if missing); sector-national and national = random walk with drift on the aggregated window.
    W = diag(train residual variances) per level (T << number of series, so full-covariance MinT is ill-posed).
    Returns (reconciled cell P50 aligned to w rows (N,H), {h_idx: w_diag})."""
    S_, K = len(w.codes), len(w.sectors)
    S = summing_matrix_2level(S_, K)
    true = np.expm1(w.base[:, None] + w.y)
    out = np.full_like(lvl_p50, np.nan)
    used: dict[int, np.ndarray] = {}
    frames = {}
    for o in np.unique(w.origin):
        idx = np.flatnonzero(w.origin == o)
        if len(idx) != S_ * K:
            continue
        frames[o] = idx[np.argsort(w.unit[idx])]
    for hi, h in enumerate(HORIZONS):
        bases, resid = {}, []
        for o, idx in frames.items():
            cells = lvl_p50[idx, hi]
            hist = np.expm1(w.hist[idx])                       # (n, W)
            st_hist = hist.reshape(S_, K, -1).sum(1)            # (S, W)
            sec_hist = hist.reshape(S_, K, -1).sum(0)           # (K, W)
            nat_hist = hist.sum(0)

            def drift(x, h=h):
                lx = np.log(np.maximum(x, 1e-9))
                return np.exp(lx[..., -1] + np.mean(np.diff(lx, axis=-1), -1) * h)
            st_b = np.array([state_base.get((s, o, hi), np.nan) if state_base else np.nan for s in range(S_)])
            st_b = np.where(np.isfinite(st_b), st_b, drift(st_hist))
            b = np.r_[drift(nat_hist), st_b, drift(sec_hist), cells]
            bases[o] = b
            t = true[idx, hi]
            if split_of(o + h) == "train" and np.isfinite(t).all() and np.isfinite(b).all():
                resid.append(b - S @ t)
        if wdiag is not None and hi in wdiag:
            wd = wdiag[hi]
        elif len(resid) >= 3:
            wd = np.nanvar(np.array(resid), 0) + 1e-9
        else:
            wd = np.ones(S.shape[0])
        used[hi] = wd
        for o, idx in frames.items():
            if np.isfinite(bases[o]).all():
                out[idx, hi] = np.maximum(mint_bottom(bases[o][None], S, wd)[0], 0)
    return out, used
