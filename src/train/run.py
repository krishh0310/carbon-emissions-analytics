"""Train/evaluate all models: `python -m src.train.run [--models lstm,tft] [--fast] [--no-final]`.

Outputs
  results/tables/metrics.csv         model, level, state_code, target, horizon, split, mae, rmse, mape, smape, mase,
                                     r2, reconciled_mase, training_time
  results/backtest.parquet           per-sample val/test predictions (P10/P50/P90 + MinT-reconciled P50)
  results/forecasts.parquet          production forecasts from the latest origin (refit on all years), reconciled
  results/model_registry.json        name, version, metrics, checkpoint path
  models/checkpoints/<model>.{ckpt,joblib}
  mlruns/                            MLflow file store (params, per-horizon metrics, artifacts)
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

from src.data.cache import ROOT
from src.data.features import REPORT_HORIZONS, build
from src.models import baselines as B
from src.models.deep import DeepForecaster
from src.train import evaluate as E

DEEP = ("lstm", "gru", "tcn", "seq2seq_attn", "tft", "deepar")
RES, CKPT = ROOT / "results", ROOT / "models" / "checkpoints"


def load_config() -> dict:
    cfg = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text())
    for name in cfg["models"]:
        tuned = ROOT / "configs" / "tuned" / f"{name}.yaml"
        if tuned.exists():
            cfg["models"][name].update(yaml.safe_load(tuned.read_text()))
    return cfg


def make_model(name: str, params: dict, df: pd.DataFrame, seed: int, ckpt_dir: Path | None = None):
    if name in DEEP:
        return DeepForecaster(name, seed=seed, ckpt_dir=str(ckpt_dir) if ckpt_dir else None, **params)
    return {"naive": B.Naive, "drift": B.Drift, "ridge": lambda: B.RidgePanel(**params),
            "lightgbm": lambda: B.LightGBMPanel(seed=seed, **params),
            "arima": lambda: B.ARIMAPerState(df, **params)}[name]()


def _mlflow():
    try:
        import mlflow

        mlflow.set_tracking_uri(f"file://{ROOT / 'mlruns'}")
        mlflow.set_experiment("carbonscope-india")
        return mlflow
    except Exception:  # noqa: BLE001 — tracking is optional
        return None


def run(models: list[str], fast: bool = False, final: bool = True) -> pd.DataFrame:
    cfg = load_config()
    df, w, _ = build(cfg["window"])
    RES.mkdir(exist_ok=True)
    (RES / "tables").mkdir(exist_ok=True)
    CKPT.mkdir(parents=True, exist_ok=True)
    mlf = _mlflow()
    nat_base = E.national_drift_base(w)
    all_rows, backtests, forecasts, registry = [], [], [], {}
    latest = w.origin.max()
    for name in models:
        params = dict(cfg["models"].get(name, {}))
        if fast and name in DEEP:
            params.update(max_epochs=5, patience=2, hidden=16)
        print(f"== {name} {params}")
        t0 = time.time()
        m = make_model(name, params, df, cfg["seed"], CKPT).fit(w)
        tt = getattr(m, "train_time", time.time() - t0)
        q = m.predict(w)
        lvl = E.to_level(w, q)[..., 1]
        rec, Ws = E.reconcile_panel(w, lvl, nat_base)
        rows = E.metric_rows(name, w, q, tt, rec)
        all_rows += rows
        bt = E.to_frame(w, q, name, rec)
        backtests.append(bt[bt.year.between(2015, latest)])

        # production forecast: refit on all observed targets (same hyper-params), forecast from latest origin
        fm = m
        if final:
            wf = replace(w, final=True)
            fm = make_model(name, params, df, cfg["seed"], CKPT / "final").fit(wf)
        sel = w.origin == latest
        wl = w.subset(sel)
        ql = fm.predict(wl)
        lvl_l = E.to_level(wl, ql)[..., 1]
        rec_l = E.reconcile_panel(wl, lvl_l, {k: v for k, v in nat_base.items() if k[0] == latest}, Ws)[0] \
            if not np.isnan(lvl_l).any() else np.full_like(lvl_l, np.nan)  # partial coverage (ARIMA): not reconcilable
        forecasts.append(E.to_frame(wl, ql, name, rec_l))

        ck = getattr(fm, "checkpoint_path", None)
        if name not in DEEP:
            ck = str(CKPT / f"{name}.joblib")
            joblib.dump(fm if name != "arima" else {"order": (1, 1, 0), "states": sorted(m.states)}, ck)
        summ = {f"{s}_mase_h{h}": r["mase"] for r in rows if r["state_code"] == "ALL"
                for s, h in [(r["split"], r["horizon"])] if h in REPORT_HORIZONS}
        registry[name] = {"name": name, "version": time.strftime("%Y%m%d"), "target": "co2_mt",
                          "horizons": list(REPORT_HORIZONS), "params": params, "metrics": summ,
                          "checkpoint_path": str(Path(ck).relative_to(ROOT)) if ck else None, "train_time_s": round(tt, 2)}
        if mlf:
            with mlf.start_run(run_name=name):
                mlf.log_params({k: v for k, v in params.items()})
                mlf.log_metrics({k: float(v) for k, v in summ.items() if np.isfinite(v)})
        print("   test MASE h1/h3/h5: " + ", ".join(f"{summ.get(f'test_mase_h{h}', np.nan):.3f}" for h in REPORT_HORIZONS))

    metrics = pd.DataFrame(all_rows)
    old = RES / "tables" / "metrics.csv"
    if old.exists():  # keep other models' rows when training a subset
        prev = pd.read_csv(old)
        lvl = prev.level if "level" in prev else "state"
        metrics = pd.concat([prev[~((lvl == "state") & prev.model.isin(models))], metrics])  # keep v2 sector rows
    metrics.to_csv(old, index=False)
    for fname, frames in (("backtest.parquet", backtests), ("forecasts.parquet", forecasts)):
        new = pd.concat(frames, ignore_index=True)
        p = RES / fname
        if p.exists():
            prev = pd.read_parquet(p)
            new = pd.concat([prev[~prev.model.isin(models)], new], ignore_index=True)
        new.to_parquet(p, index=False)
    reg_p = RES / "model_registry.json"
    reg = json.loads(reg_p.read_text()) if reg_p.exists() else {}
    reg.update(registry)
    reg_p.write_text(json.dumps(reg, indent=1, default=float))
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="naive,drift,ridge,lightgbm,arima," + ",".join(DEEP))
    ap.add_argument("--fast", action="store_true", help="tiny deep runs (CI smoke test)")
    ap.add_argument("--no-final", action="store_true", help="skip production refit")
    a = ap.parse_args()
    m = run(a.models.split(","), a.fast, not a.no_final)
    lb = m[(m.state_code == "ALL") & (m.split == "test") & m.horizon.isin(REPORT_HORIZONS) & ((m.level == "state") if "level" in m else True)]
    print(lb.pivot_table(index="model", columns="horizon", values="mase").sort_values(5).round(3).to_string())


if __name__ == "__main__":
    main()
