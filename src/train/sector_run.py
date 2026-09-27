"""v2 state x sector training: `python -m src.train.sector_run [--models ...] [--fast]`.

Panel: 36 states x 7 sectors = 252 series, target co2e_mt (AR6 GWP-100), same time splits as v1.
Writes (sector rows are appended to results/tables/metrics.csv with level=state_sector and a `sector` column):
  results/forecasts_sector.parquet     production forecasts 2025-2029 (P10/P50/P90 + two-level-MinT P50)
  results/backtest_sector.parquet
  results/tables/experiments.csv       E10 disaggregation, E11 multi-task vs per-sector, E12 reconciliation, E14 transfer
  results/tables/importance_sector_<model>.csv   group permutation importance per sector
  results/sector_registry.json
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from src.data.cache import PROCESSED, ROOT
from src.data.features import REPORT_HORIZONS, make_windows
from src.data.sector_features import LOG1P, SECTOR_DRIVERS, SHARED, build, feature_columns, state_total_frame
from src.data.sectors import SECTORS
from src.models import baselines as B
from src.models.deep import DeepForecaster
from src.train import evaluate as E
from src.train.run import load_config

RES = ROOT / "results"
DEEP = ("gru", "tcn", "seq2seq_attn", "tft", "mt_gru", "mt_tft")
ALL = ("naive", "drift", "lightgbm", "lightgbm_sector", *DEEP)
MAIN = "mt_tft"
GROUPS = {"sector_history": ["sec_log", "sec_lag1", "sec_lag3", "sec_lag5", "sec_roll5", "sec_growth_yoy", "sec_share_lag1"],
          "state_total_history": ["tot_lag1", "tot_growth_lag1"],
          "economy": ["gsdp_const_cr", "gsdp_growth_pct", "gsdp_imputed"],
          "demography": ["population_mn", "urban_population_pct", "population_density"],
          "climate": ["avg_temp_c", "cooling_degree_days", "heating_degree_days", "monsoon_rainfall_mm", "drought_year"],
          "policy": [c for c in SHARED if c.endswith(("_dummy", "_phase", "stringency"))],
          "sector_drivers": [c for cols in SECTOR_DRIVERS.values() for c in cols]}


def make(name: str, params: dict, seed: int, fast: bool, **extra):
    if name in DEEP:
        p = {**params, **({"max_epochs": 4, "patience": 2, "hidden": 16} if fast else {})}
        return DeepForecaster(name, seed=seed, **p, **extra)
    return {"naive": B.Naive, "drift": B.Drift, "lightgbm": lambda: B.LightGBMPanel(seed=seed, **params),
            "lightgbm_sector": lambda: B.LightGBMPerSector(seed=seed, **params)}[name]()


def params_for(cfg: dict, name: str) -> dict:
    base = name.removeprefix("mt_")
    p = dict(cfg["models"].get(name) or cfg["models"].get(base) or {})
    if name == "mt_tft":
        p.pop("n_layers", None)
    return p


def windows(window: int):
    df = build(pd.read_parquet(PROCESSED / "india_states_panel.parquet"),
               pd.read_parquet(PROCESSED / "india_states_sector_panel.parquet"))
    feats = feature_columns(df)
    w, prep = make_windows(df, window, target="co2e_mt", features=feats, sectors=tuple(SECTORS), log_cols=LOG1P)
    tdf = state_total_frame(df)
    wt, _ = make_windows(tdf, window, target="co2e_mt", features=feats, log_cols=LOG1P)
    return df, w, wt


def state_base(wt: E.Windows, q_total: np.ndarray) -> dict:
    lvl = E.to_level(wt, q_total)[..., 1]
    return {(int(s), int(o), hi): float(lvl[i, hi]) for i, (s, o) in enumerate(zip(wt.state, wt.origin, strict=True))
            for hi in range(lvl.shape[1])}


def bottom_up_vs_direct(name: str, w, wt, lvl_cells, rec_cells, lvl_total) -> list[dict]:
    """E10: state-total accuracy from Σ sector forecasts (raw and reconciled) vs a direct state-total model."""
    true_t = np.expm1(wt.base[:, None] + wt.y)
    sc = E._level_scale(wt)[wt.unit]
    pos = {(int(s), int(o)): i for i, (s, o) in enumerate(zip(wt.state, wt.origin, strict=True))}
    bu = np.full_like(lvl_total, np.nan)
    bur = np.full_like(lvl_total, np.nan)
    for (s, o), i in pos.items():
        sel = (w.state == s) & (w.origin == o)
        if sel.sum() == len(w.sectors):
            bu[i] = lvl_cells[sel].sum(0)
            bur[i] = rec_cells[sel].sum(0)
    rows = []
    m = wt.mask("test")
    for hi, h in enumerate(E.HORIZONS):
        k = m[:, hi] & np.isfinite(bu[:, hi])
        if not k.any():
            continue
        for variant, pred in (("direct_state_total", lvl_total), ("bottom_up_sectors", bu), ("bottom_up_reconciled", bur)):
            rows.append({"experiment": "E10", "model": name, "variant": variant, "horizon": h, "split": "test",
                         "mase": float(np.nanmean(np.abs(pred[k, hi] - true_t[k, hi]) / sc[k]))})
    return rows


def group_importance(model, w, repeats=3, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    m = w.mask("val")
    true = np.expm1(w.base[:, None] + w.y)
    scale = E._level_scale(w)[w.unit][:, None]

    def per_sector(q):
        err = np.abs(np.expm1(w.base[:, None] + q[..., 1]) - true) / scale
        return {sec: float(np.nanmean(err[(w.sector == k)[:, None] & m])) for k, sec in enumerate(w.sectors)}
    base = per_sector(model.predict(w))
    rows = []
    for g, cols in GROUPS.items():
        idx = [w.features.index(c) for c in w.features if c in cols or c.removesuffix("_missing") in cols]
        if not idx:
            continue
        acc = {s: [] for s in w.sectors}
        for _ in range(repeats):
            X = w.X.copy()
            X[:, :, idx] = X[rng.permutation(len(X))][:, :, idx]
            got = per_sector(model.predict(replace(w, X=X)))
            for s in w.sectors:
                acc[s].append(got[s] - base[s])
        rows += [{"sector": s, "group": g, "importance": float(np.mean(v))} for s, v in acc.items()]
    return pd.DataFrame(rows)


def run(models: list[str], fast: bool = False, final: bool = True, transfer: bool = True) -> None:
    cfg = load_config()
    seed = cfg["seed"]
    df, w, wt = windows(cfg["window"])
    (RES / "tables").mkdir(parents=True, exist_ok=True)
    rows, exp_rows, back, fcs, registry = [], [], [], [], {}
    latest = w.origin.max()

    # direct state-total model: aggregate base forecasts for reconciliation + E10 comparator
    t0 = time.time()
    tot_model = make("tft", params_for(cfg, "tft"), seed, fast).fit(wt)
    q_tot = tot_model.predict(wt)
    sbase = state_base(wt, q_tot)
    print(f"direct state-total TFT fitted ({time.time() - t0:.0f}s)")
    tot_final = make("tft", params_for(cfg, "tft"), seed, fast).fit(replace(wt, final=True)) if final else tot_model
    wtl = wt.subset(wt.origin == latest)
    sbase_latest = state_base(wtl, tot_final.predict(wtl))

    for name in models:
        t0 = time.time()
        m = make(name, params_for(cfg, name), seed, fast).fit(w)
        tt = getattr(m, "train_time", time.time() - t0)
        q = m.predict(w)
        lvl = E.to_level(w, q)[..., 1]
        rec, wd = E.reconcile_two_level(w, lvl, sbase)
        r = E.metric_rows(name, w, q, tt, rec, target="co2e_mt")
        rows += r
        exp_rows += bottom_up_vs_direct(name, w, wt, lvl, rec, E.to_level(wt, q_tot)[..., 1])
        bt = E.to_frame(w, q, name, rec)
        bt["sector"] = np.tile(np.array(w.sectors)[w.sector], len(E.HORIZONS))
        back.append(bt[bt.year >= 2015])

        fm = make(name, params_for(cfg, name), seed, fast).fit(replace(w, final=True)) if final else m
        sel = np.flatnonzero(w.origin == latest)
        wl = w.subset(sel)
        ql = fm.predict(wl)
        recl, _ = E.reconcile_two_level(wl, E.to_level(wl, ql)[..., 1], sbase_latest, wd)
        f = E.to_frame(wl, ql, name, recl)
        f["sector"] = np.tile(np.array(w.sectors)[wl.sector], len(E.HORIZONS))
        fcs.append(f)
        allr = {(x["split"], x["horizon"]): x for x in r if x["state_code"] == "ALL" and x["sector"] == "ALL"}
        summ = {f"{s}_mase_h{h}": allr[(s, h)]["mase"] for s in ("val", "test") for h in REPORT_HORIZONS if (s, h) in allr}
        summ |= {f"{s}_reconciled_mase_h{h}": allr[(s, h)]["reconciled_mase"] for s in ("val", "test") for h in REPORT_HORIZONS if (s, h) in allr}
        registry[name] = {"name": name, "version": time.strftime("%Y%m%d"), "target": "co2e_mt", "level": "state_sector",
                          "metrics": summ, "train_time_s": round(tt, 1), "checkpoint_path": getattr(fm, "checkpoint_path", None)}
        print(f"== {name:16s} test MASE h1/h3/h5 raw " + " ".join(f"{summ.get(f'test_mase_h{h}', np.nan):.2f}" for h in REPORT_HORIZONS)
              + " | MinT " + " ".join(f"{summ.get(f'test_reconciled_mase_h{h}', np.nan):.2f}" for h in REPORT_HORIZONS)
              + f"  ({tt:.0f}s)")
        if name not in ("naive", "drift"):  # every learned model (the serving champion is picked later on val)
            imp = group_importance(m, w)
            imp.insert(0, "model", name)
            imp.to_csv(RES / "tables" / f"importance_sector_{name}.csv", index=False)

    # E14: cross-state transfer — hold out 6 states (seeded), predict them zero-shot with the mean state embedding
    if transfer:
        rng = np.random.default_rng(seed)
        held = sorted(rng.choice(len(w.codes), 6, replace=False).tolist())
        for name in [n for n in ("gru", MAIN) if n in models]:
            m = make(name, params_for(cfg, name), seed, fast, exclude_states=held).fit(w)
            q = m.predict(w)
            ms = [x for x in E.metric_rows(name, w, q) if x["split"] == "test" and x["sector"] != "ALL"
                  and x["state_code"] in {w.codes[i] for i in held}]
            full = [x for x in rows if x["model"] == name and x["split"] == "test" and x["state_code"] in {w.codes[i] for i in held}]
            for h in REPORT_HORIZONS:
                exp_rows.append({"experiment": "E14", "model": name, "variant": "held_out_zero_shot", "horizon": h, "split": "test",
                                 "mase": float(np.mean([x["mase"] for x in ms if x["horizon"] == h])),
                                 "note": "held-out: " + ",".join(w.codes[i] for i in held)})
                exp_rows.append({"experiment": "E14", "model": name, "variant": "trained_on_all", "horizon": h, "split": "test",
                                 "mase": float(np.mean([x["mase"] for x in full if x["horizon"] == h]))})

    met = pd.DataFrame(rows)
    for (a, b_) in (("gru", "mt_gru"), ("tft", "mt_tft")):  # E11
        for h in REPORT_HORIZONS:
            for mdl in (a, b_):
                x = met[(met.model == mdl) & (met.state_code == "ALL") & (met.sector == "ALL") & (met.split == "test") & (met.horizon == h)]
                if len(x):
                    exp_rows.append({"experiment": "E11", "model": mdl, "variant": "multi_task" if mdl.startswith("mt_") else "per_sector_head",
                                     "horizon": h, "split": "test", "mase": float(x.mase.iloc[0]), "reconciled_mase": float(x.reconciled_mase.iloc[0])})
    for mdl, g in met[(met.state_code == "ALL") & (met.sector == "ALL") & (met.split == "test")].groupby("model"):  # E12
        for _, x in g[g.horizon.isin(REPORT_HORIZONS)].iterrows():
            exp_rows.append({"experiment": "E12", "model": mdl, "variant": "unreconciled", "horizon": x.horizon, "split": "test", "mase": x.mase})
            exp_rows.append({"experiment": "E12", "model": mdl, "variant": "two_level_MinT", "horizon": x.horizon, "split": "test", "mase": x.reconciled_mase})

    _merge_csv(RES / "tables" / "metrics.csv", met, lambda d: (d.get("level", "state") == "state_sector") & d.model.isin(models))
    _merge_csv(RES / "tables" / "experiments.csv", pd.DataFrame(exp_rows), lambda d: d.model.isin(models))
    for fname, frames in (("backtest_sector.parquet", back), ("forecasts_sector.parquet", fcs)):
        new = pd.concat(frames, ignore_index=True)
        p = RES / fname
        if p.exists():
            prev = pd.read_parquet(p)
            new = pd.concat([prev[~prev.model.isin(models)], new], ignore_index=True)
        new.to_parquet(p, index=False)
    reg_p = RES / "sector_registry.json"
    reg = json.loads(reg_p.read_text()) if reg_p.exists() else {}
    reg.update(registry)
    reg_p.write_text(json.dumps(reg, indent=1, default=float))


def _merge_csv(path, new: pd.DataFrame, drop) -> None:
    if path.exists():
        prev = pd.read_csv(path)
        if "sector" not in prev:
            prev["sector"] = "TOTAL"
        prev = prev[~drop(prev)]
        new = pd.concat([prev, new], ignore_index=True)
    new.to_csv(path, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(ALL))
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--no-final", action="store_true")
    ap.add_argument("--no-transfer", action="store_true")
    a = ap.parse_args()
    run(a.models.split(","), a.fast, not a.no_final, not a.no_transfer)
    ex = pd.read_csv(RES / "tables" / "experiments.csv")
    print(ex.pivot_table(index=["experiment", "model", "variant"], columns="horizon", values="mase").round(3).to_string())


if __name__ == "__main__":
    main()
