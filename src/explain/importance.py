"""Explainability: `python -m src.explain.importance [--models lightgbm,tft,seq2seq_attn]`.

  results/tables/importance_<model>.csv   permutation importance of feature GROUPS (Δ val MASE)
  results/tables/shap_lightgbm.csv         mean |SHAP| per feature (h=1 P50 booster)
  results/tables/attention_<model>.csv     mean attention over input years per horizon (Seq2Seq / TFT)
  results/tables/pdp_renewable_share.csv   partial dependence of predicted 1-yr growth on renewable share (LightGBM)
Models are refit with the config in configs/models.yaml (same seed) — deterministic.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from src.data.cache import ROOT
from src.data.features import FEATURE_GROUPS, build
from src.train.run import load_config, make_model

TAB = ROOT / "results" / "tables"


def val_mase(w, q) -> float:
    m = w.mask("val")
    lvl = np.expm1(w.base[:, None] + q[..., 1])
    true = np.expm1(w.base[:, None] + w.y)
    sc = np.array([np.nanmean(np.abs(np.diff(np.expm1(w.hist[i])))) or 1 for i in range(len(w.y))])
    return float(np.nanmean((np.abs(lvl - true) / sc[:, None])[m]))


def group_permutation(model, w, repeats: int = 5, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = val_mase(w, model.predict(w))
    rows = []
    for g, cols in FEATURE_GROUPS.items():
        idx = [w.features.index(c) for c in cols if c in w.features]
        idx += [w.features.index(c) for c in w.features if c.endswith("_missing") and c[:-8] in cols]
        if not idx:
            continue
        deltas = []
        for _ in range(repeats):
            X = w.X.copy()
            perm = rng.permutation(len(X))
            X[:, :, idx] = X[perm][:, :, idx]  # shuffle whole group jointly across samples (keeps within-group structure)
            deltas.append(val_mase(w.__class__(**{**w.__dict__, "X": X}), model.predict(w.__class__(**{**w.__dict__, "X": X}))) - base)
        rows.append({"group": g, "importance": float(np.mean(deltas)), "std": float(np.std(deltas)), "n_features": len(idx)})
    return pd.DataFrame(rows).sort_values("importance", ascending=False)


def run(models: list[str]) -> None:
    cfg = load_config()
    df, w, _ = build(cfg["window"])
    TAB.mkdir(parents=True, exist_ok=True)
    for name in models:
        print(f"== {name}")
        m = make_model(name, cfg["models"][name], df, cfg["seed"]).fit(w)
        imp = group_permutation(m, w)
        imp.insert(0, "model", name)
        imp.to_csv(TAB / f"importance_{name}.csv", index=False)
        print(imp.to_string(index=False))

        if name == "lightgbm":
            import shap

            X = m._X(w)
            sv = shap.TreeExplainer(m.models[0, 0.5]).shap_values(X)
            pd.DataFrame({"feature": m.feature_names(w), "mean_abs_shap": np.abs(sv).mean(0)}).sort_values(
                "mean_abs_shap", ascending=False).to_csv(TAB / "shap_lightgbm.csv", index=False)
            if "renewable_share_pct" in w.features:
                j = w.features.index("renewable_share_pct")
                grid = np.quantile(w.X[:, -1, j], np.linspace(0.05, 0.95, 15))
                pdp = []
                for v in grid:
                    Xv = X.copy()
                    Xv[:, j] = v
                    pdp.append({"renewable_share_scaled": float(v),
                                "pred_growth_h1_pct": float(100 * np.expm1(m.models[0, 0.5].predict(Xv)).mean())})
                pd.DataFrame(pdp).to_csv(TAB / "pdp_renewable_share.csv", index=False)

        if name in ("tft", "seq2seq_attn"):
            _, aux = m.predict(w, return_aux=True)
            att = aux["attention"].mean(0)  # (H, W) — weight of each input year (t-W+1 .. t)
            W = att.shape[1]
            pd.DataFrame(att, columns=[f"t-{W - 1 - i}" for i in range(W)],
                         index=pd.Index(range(1, att.shape[0] + 1), name="horizon")).to_csv(TAB / f"attention_{name}.csv")
            if "variable_weights" in aux:
                pd.DataFrame({"feature": w.features, "weight": aux["variable_weights"].mean(0)}).sort_values(
                    "weight", ascending=False).to_csv(TAB / "tft_variable_selection.csv", index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="lightgbm,ridge,tft,seq2seq_attn,gru")
    run(ap.parse_args().models.split(","))
