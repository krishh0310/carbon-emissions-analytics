"""Continuous-learning loop (runs inside the RQ worker; the API keeps serving the current champion throughout).

Cycle:  (incremental: refresh CEA/PPAC/IMD/EDGAR downloads; skip training if no checksum changed)
        → train fossil-CO2 models + state×sector models from scratch on the updated windowed panel
          (true online/incremental learning for TFT-style networks is out of scope — documented)
        → explain → ATAR insights → register every trained model as a new *candidate* version
        → promotion check: best candidate becomes CHALLENGER (shadow: 20 % of traffic for 14 days) only if
          (a) backtest score ≥ 2 % better than the champion, (b) consistency tests pass
          (Σ cells = state = national; no negative/NaN forecasts; renewables↑ ⇒ power CO2 not↑)
        → after the shadow window a challenger that still qualifies is promoted; the old champion is archived.
Drift:  PSI of every model input (latest 3 years vs the preceding 5) and error drift (champion's newest 1-year-ahead
        error vs its validation MASE). PSI > 0.25 on ≥ 3 inputs or error ratio > 1.5 → report + auto-retrain + admin alert.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select

from backend.app.db import DriftReport, Forecast, ForecastSector, Job, Model, now, session

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results"
IMPROVE = 0.02          # challenger must beat champion's backtest score by ≥ 2 %
SHADOW_DAYS = 14
PSI_T, PSI_N, ERR_T = 0.25, 3, 1.5
LEVEL_REG = {"state": ("model_registry.json", "val_mase_h5", "test_mase_h"), "state_sector": ("sector_registry.json", "val_reconciled_mase_h5", "test_reconciled_mase_h")}
PARTIAL = {"arima"}


def backtest_score(metrics: dict, level: str) -> float | None:
    """Mean test (2020-2024) MASE over horizons 1, 3, 5 — reconciled for the state×sector level."""
    key = LEVEL_REG[level][2]
    v = [float(x) for x in (metrics.get(f"{key}{h}") for h in (1, 3, 5)) if x is not None and np.isfinite(x)]
    return float(np.mean(v)) if v else None


def _log(job_id: int | None, msg: str, status: str | None = None) -> None:
    print(msg, flush=True)
    if job_id is None:
        return
    with session() as db:
        j = db.get(Job, job_id)
        if j is None:
            return
        j.logs = (j.logs + msg + "\n")[-200_000:]
        if status:
            j.status = status
            if status in ("succeeded", "failed"):
                j.finished_at = now()
        db.commit()


def _run(job_id, cmd: list[str], env: dict | None = None) -> bool:
    _log(job_id, "$ " + " ".join(cmd[1:]))
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env={**os.environ, **(env or {})})
    _log(job_id, p.stdout[-6000:] + (p.stderr[-3000:] if p.returncode else ""))
    return p.returncode == 0


def _raw_digest() -> dict:
    m = ROOT / "data" / "raw" / "manifest.json"
    return json.loads(m.read_text()) if m.exists() else {}


# ---- registry ------------------------------------------------------------------------------------------
def register_candidates(db, version: str) -> list[Model]:
    """Insert every model in the results registries as a candidate version (with its forecasts)."""
    out = []
    for level, (fname, vkey, _) in LEVEL_REG.items():
        p = RES / fname
        if not p.exists():
            continue
        reg = json.loads(p.read_text())
        fc = pd.read_parquet(RES / ("forecasts.parquet" if level == "state" else "forecasts_sector.parquet"))
        for name, r in reg.items():
            dbn = name if level == "state" else f"s_{name}"
            if db.scalar(select(Model).where(Model.name == dbn, Model.level == level, Model.version == version)):
                continue
            m = Model(name=dbn, version=version, target=r["target"], horizon=5, metrics=r["metrics"], level=level,
                      checkpoint_path=r.get("checkpoint_path"), status="candidate", val_score=r["metrics"].get(vkey))
            db.add(m)
            db.flush()
            f = fc[fc.model == name]
            if level == "state":
                cp = ROOT / "data" / "processed" / "india_cities_panel.parquet"
                if cp.exists():  # city fossil-CO2 forecasts = state forecast × city's mean share of state (last 3 yrs)
                    cities = pd.read_parquet(cp)
                    share = cities[cities.year > cities.year.max() - 3].groupby(["city_id", "state_code"]).share_of_state.mean().reset_index()
                    db.bulk_insert_mappings(Forecast, [{"model_id": m.id, "city_id": int(x.city_id), "target": "co2_mt", "year": int(x.year),
                                                        "p10": float(x.p10 * x.share_of_state), "p50": float(x.p50 * x.share_of_state),
                                                        "p90": float(x.p90 * x.share_of_state)} for x in share.merge(f, on="state_code").itertuples()])
                db.bulk_insert_mappings(Forecast, [{"model_id": m.id, "state_code": x.state_code, "target": "co2_mt", "year": int(x.year),
                                                    "p10": float(x.p10), "p50": float(x.p50), "p90": float(x.p90),
                                                    "p50_reconciled": None if pd.isna(x.p50_reconciled) else float(x.p50_reconciled)}
                                                   for x in f.itertuples()])
            else:
                db.bulk_insert_mappings(ForecastSector, [{"model_id": m.id, "state_code": x.state_code, "sector": x.sector, "target": "co2e_mt",
                                                          "year": int(x.year), "p10": float(x.p10), "p50": float(x.p50), "p90": float(x.p90),
                                                          "p50_reconciled": None if pd.isna(x.p50_reconciled) else float(x.p50_reconciled)}
                                                         for x in f.itertuples()])
            out.append(m)
    db.commit()
    return out


def consistency_ok(db, m: Model) -> tuple[bool, str]:
    """Pre-promotion checks on a model's stored forecasts."""
    if m.level == "state":
        rows = db.scalars(select(Forecast).where(Forecast.model_id == m.id, Forecast.state_code.is_not(None))).all()
        vals = [r.p50 for r in rows]
        if not rows or any(v is None or not np.isfinite(v) or v < 0 for v in vals):
            return False, "missing/negative/NaN forecasts"
        if any(r.p10 > r.p50 + 1e-9 or r.p50 > r.p90 + 1e-9 for r in rows):
            return False, "quantiles cross"
        return True, "ok"
    rows = db.scalars(select(ForecastSector).where(ForecastSector.model_id == m.id)).all()
    if not rows:
        return False, "no forecasts"
    df = pd.DataFrame([{"s": r.state_code, "k": r.sector, "y": r.year, "p10": r.p10, "p50": r.p50, "p90": r.p90,
                        "rec": r.p50_reconciled} for r in rows])
    if df[["p10", "p50", "p90"]].isna().any().any() or (df.rec.fillna(0) < -1e-9).any():
        return False, "NaN or negative reconciled cells"
    if len(df) != 36 * 7 * df.y.nunique():
        return False, "incomplete state×sector grid"
    # E13: renewables up must never raise power emissions (scenario identities on this model's forecast)
    from src.scenarios import Params, apply, state_structure

    base = df.rename(columns={"s": "state_code", "k": "sector", "y": "year"})[["state_code", "sector", "year", "p10", "p50", "p90"]]
    st = state_structure()
    prev = None
    for pp in (0, 10, 25, 40):
        power = apply(base, Params(renewable_pp=pp), st).query("sector == 'POWER'").scenario_p50.sum()
        if prev is not None and power > prev + 1e-6:
            return False, "renewables↑ increased power CO2"
        prev = power
    return True, "ok"


def promotion_check(job_id: int | None = None) -> list[str]:
    """Candidate → challenger (shadow) → champion lifecycle. Returns human-readable decisions."""
    notes = []
    with session() as db:
        for level in LEVEL_REG:
            champ = db.scalar(select(Model).where(Model.level == level, Model.status == "champion").order_by(Model.id.desc()))
            chal = db.scalar(select(Model).where(Model.level == level, Model.status == "challenger").order_by(Model.id.desc()))
            n = datetime.now(UTC)
            if chal and chal.shadow_until:
                su = chal.shadow_until if chal.shadow_until.tzinfo else chal.shadow_until.replace(tzinfo=UTC)
                if su <= n:
                    ok, why = consistency_ok(db, chal)
                    cs, hs = backtest_score(chal.metrics, level), backtest_score(champ.metrics, level) if champ else None
                    if ok and (hs is None or (cs is not None and cs <= hs * (1 - IMPROVE))) and not (champ and champ.pinned):
                        if champ:
                            champ.status = "archived"
                        chal.status, chal.shadow_until = "champion", None
                        notes.append(f"[{level}] promoted {chal.name}@{chal.version} (backtest {cs:.3f} vs {hs if hs is None else round(hs, 3)})")
                    else:
                        chal.status, chal.shadow_until = "archived", None
                        notes.append(f"[{level}] challenger {chal.name}@{chal.version} archived after shadow ({why}; pinned={bool(champ and champ.pinned)})")
                    chal = None
            if champ is None:  # bootstrap: best validation score becomes champion directly
                best = db.scalar(select(Model).where(Model.level == level, Model.status == "candidate", Model.val_score.is_not(None),
                                                     Model.name.not_in(["arima", "s_arima"])).order_by(Model.val_score))
                if best:
                    best.status = "champion"
                    notes.append(f"[{level}] bootstrap champion {best.name}@{best.version}")
                db.commit()
                continue
            if chal is None:
                cands = db.scalars(select(Model).where(Model.level == level, Model.status == "candidate", Model.val_score.is_not(None),
                                                       Model.name.not_in(["arima", "s_arima"])).order_by(Model.val_score)).all()
                hs = backtest_score(champ.metrics, level)
                for c in cands[:3]:  # best by validation first (selection never looks at test)
                    cs = backtest_score(c.metrics, level)
                    if cs is None or hs is None or cs > hs * (1 - IMPROVE):
                        continue
                    ok, why = consistency_ok(db, c)
                    if not ok:
                        notes.append(f"[{level}] {c.name}@{c.version} failed consistency: {why}")
                        continue
                    c.status, c.shadow_until = "challenger", n + timedelta(days=SHADOW_DAYS)
                    notes.append(f"[{level}] {c.name}@{c.version} → challenger (backtest {cs:.3f} vs champion {hs:.3f}); shadow 20 % until {c.shadow_until:%Y-%m-%d}")
                    break
                else:
                    notes.append(f"[{level}] champion {champ.name}@{champ.version} retained (no candidate ≥ {IMPROVE:.0%} better on backtest)")
            # keep the registry small: archive old candidates beyond the 3 most recent versions
            for old in db.scalars(select(Model).where(Model.level == level, Model.status == "candidate").order_by(Model.id.desc())).all()[len(LEVEL_REG) * 40:]:
                old.status = "archived"
            db.commit()
    for x in notes:
        _log(job_id, x)
    return notes


# ---- drift ---------------------------------------------------------------------------------------------
def psi(ref: np.ndarray, cur: np.ndarray, bins: int = 10) -> float:
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 20 or len(cur) < 10 or np.nanstd(ref) == 0:
        return 0.0
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    r = np.histogram(np.clip(ref, edges[0], edges[-1]), edges)[0] / len(ref)
    c = np.histogram(np.clip(cur, edges[0], edges[-1]), edges)[0] / len(cur)
    r, c = np.clip(r, 1e-4, None), np.clip(c, 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


def drift_check(job_id: int | None = None, auto_retrain: bool = True) -> dict:
    from src.data.features import engineer, feature_list, load_panel

    df = engineer(load_panel())
    last = int(df.year.max())
    feats = [f for f in feature_list(df) if not f.endswith("_missing")]
    # growth-type comparison: level features trend upward by design, so compare year-on-year changes
    g = df.sort_values(["state_code", "year"]).groupby("state_code")[feats].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    g["year"] = df.sort_values(["state_code", "year"]).year.values
    ref, cur = g[(g.year > last - 8) & (g.year <= last - 3)], g[g.year > last - 3]
    scores = {f: round(psi(ref[f].to_numpy(float), cur[f].to_numpy(float)), 4) for f in feats}
    top = dict(sorted(scores.items(), key=lambda kv: -kv[1])[:8])
    n_drift = sum(v > PSI_T for v in scores.values())
    # error drift: champion's newest 1-year-ahead error vs its validation MASE at h=1
    err_ratio = None
    with session() as db:
        champ = db.scalar(select(Model).where(Model.level == "state", Model.status == "champion").order_by(Model.id.desc()))
    bt_p = RES / "backtest.parquet"
    if champ and bt_p.exists():
        bt = pd.read_parquet(bt_p)
        b = bt[(bt.model == champ.name) & (bt.horizon == 1) & (bt.year == bt.year.max())].dropna(subset=["actual"])
        if len(b):
            hist = df[df.year <= 2014].sort_values("year").groupby("state_code").co2_mt.apply(lambda s: np.mean(np.abs(np.diff(s.to_numpy()))))
            mase_new = float(np.mean(np.abs(b.p50 - b.actual) / b.state_code.map(hist).clip(lower=1e-3)))
            v1 = (champ.metrics or {}).get("val_mase_h1")
            err_ratio = mase_new / v1 if v1 else None
    triggered = n_drift >= PSI_N or (err_ratio is not None and err_ratio > ERR_T)
    rep = {"psi_top": top, "n_inputs_over_threshold": n_drift, "psi_threshold": PSI_T, "error_ratio": err_ratio,
           "error_threshold": ERR_T, "window": f"{last - 7}-{last - 3} vs {last - 2}-{last}", "triggered": triggered}
    with session() as db:
        db.add(DriftReport(level="state", psi_max=max(scores.values() or [0]), mase_drift=err_ratio, triggered=triggered, details=rep))
        if triggered:
            db.add(Job(type="drift_alert", status="succeeded", finished_at=now(),
                       logs=f"DRIFT ALERT: {n_drift} inputs with PSI>{PSI_T}; error ratio {err_ratio}. Auto-retrain {'queued' if auto_retrain else 'disabled'}.\n"))
        db.commit()
    _log(job_id, f"drift: {n_drift} inputs over PSI {PSI_T}; error ratio {err_ratio}; triggered={triggered}")
    if triggered and auto_retrain:
        enqueue_cycle("full", reason="drift")
    return rep


# ---- cycles --------------------------------------------------------------------------------------------
def enqueue_cycle(kind: str, reason: str = "schedule", models: list[str] | None = None) -> int:
    from redis import Redis
    from rq import Queue

    from backend.app.config import settings

    with session() as db:
        j = Job(type=f"retrain_{kind}", status="queued", logs=f"reason={reason} models={models or 'all'}\n")
        db.add(j)
        db.commit()
        jid = j.id
    Queue("carbonscope", connection=Redis.from_url(settings().redis_url)).enqueue(
        "backend.app.mlops.run_cycle", jid, kind, models, job_timeout=8 * 3600)
    return jid


def run_cycle(job_id: int, kind: str = "full", models: list[str] | None = None, fast: bool = False) -> None:
    py = sys.executable
    _log(job_id, f"cycle={kind} started {datetime.now(UTC):%Y-%m-%d %H:%M} UTC", "running")
    try:
        if kind == "incremental":
            before = {k: v.get("sha256") for k, v in _raw_digest().items()}
            # live external APIs (OWID, World Bank, Climate TRACE) feed Analytics only — never block the cycle
            _run(job_id, [py, "-m", "src.data.external"], env={"CARBONSCOPE_REFRESH": "1"})
            if not _run(job_id, [py, "-m", "src.data.ingest", "--refresh"]):
                raise RuntimeError("ingest failed")
            after = {k: v.get("sha256") for k, v in _raw_digest().items()}
            changed = [k for k in after if before.get(k) != after[k]]
            _log(job_id, f"sources changed: {len(changed)} {changed[:8]}")
            if not changed:
                _log(job_id, "no new data — training skipped; running promotion check only")
                promotion_check(job_id)
                _log(job_id, "done", "succeeded")
                return
        fast_flag = ["--fast"] if fast else []
        v1 = [m for m in (models or []) if m in ("naive", "drift", "ridge", "lightgbm", "arima", "lstm", "gru", "tcn", "seq2seq_attn", "tft", "deepar")]
        steps = [[py, "-m", "src.train.run", *(["--models", ",".join(v1)] if v1 else []), *fast_flag],
                 [py, "-m", "src.train.sector_run", "--no-transfer", *fast_flag],
                 [py, "-m", "src.explain.importance"], [py, "-m", "src.flowfield"], [py, "-m", "src.insights"],
                 [py, "-m", "backend.app.seed", "--keep-registry"]]
        for cmd in steps:
            if not _run(job_id, cmd):
                raise RuntimeError(f"step failed: {' '.join(cmd[2:3])}")
        version = datetime.now(UTC).strftime("%Y%m%d-%H%M")
        with session() as db:
            new = register_candidates(db, version)
        _log(job_id, f"registered {len(new)} candidate versions @ {version}")
        promotion_check(job_id)
        from backend.app.v2 import invalidate_cache

        invalidate_cache()
        _log(job_id, "done", "succeeded")
    except Exception as e:  # noqa: BLE001
        _log(job_id, f"FAILED: {e}", "failed")
