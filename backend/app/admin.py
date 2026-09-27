"""Admin console API (/api/v1/admin/*) — every route requires the admin role.

Registry (promote / archive / pin), continuous-learning cycles, drift, schedule, feature-store status,
source reconciliation, metrics download, and ATAR insight moderation.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import mlops
from backend.app.db import Artifact, DriftReport, FeatureState, Insight, Model, ServingLog, User, get_db
from backend.app.security import require_admin

ROOT = Path(__file__).resolve().parents[2]
DB = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_admin)]
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _model(db: Session, mid: int) -> Model:
    m = db.get(Model, mid)
    if m is None:
        raise HTTPException(404, "model not found")
    return m


@router.get("/registry")
def registry(db: DB, _: Admin, level: Literal["state", "state_sector"] | None = None, include_archived: bool = False):
    since = date.today() - timedelta(days=14)
    served = {mid: n for mid, n in db.execute(select(ServingLog.model_id, func.sum(ServingLog.n)).where(ServingLog.day >= since)
                                                .group_by(ServingLog.model_id))}
    q = select(Model).order_by(Model.level, Model.status, Model.val_score)
    if level:
        q = q.where(Model.level == level)
    if not include_archived:
        q = q.where(Model.status != "archived")
    rows = db.scalars(q).all()
    return {"policy": {"promotion": f"challenger needs ≥ {mlops.IMPROVE:.0%} better backtest (mean test MASE h1/h3/h5) + consistency tests; "
                                    f"shadow {mlops.SHADOW_DAYS} days at 20 % traffic", "selection": "lowest validation MASE @ h=5"},
            "items": [{"id": m.id, "name": m.name.removeprefix("s_"), "level": m.level, "version": m.version, "status": m.status,
                       "pinned": m.pinned, "shadow_until": m.shadow_until, "val_score": m.val_score,
                       "backtest_score": mlops.backtest_score(m.metrics or {}, m.level), "served_14d": int(served.get(m.id, 0)),
                       "metrics": m.metrics, "checkpoint_path": m.checkpoint_path, "created_at": m.created_at} for m in rows]}


@router.post("/models/{mid}/promote")
def promote(mid: int, db: DB, _: Admin):
    m = _model(db, mid)
    ok, why = mlops.consistency_ok(db, m)
    if not ok:
        raise HTTPException(409, f"consistency tests failed: {why}")
    for old in db.scalars(select(Model).where(Model.level == m.level, Model.status.in_(["champion", "challenger"]), Model.id != m.id)):
        old.status, old.pinned, old.shadow_until = "archived", False, None
    m.status, m.shadow_until = "champion", None
    db.commit()
    _invalidate()
    return {"ok": True, "champion": m.id}


@router.post("/models/{mid}/archive")
def archive(mid: int, db: DB, _: Admin):
    m = _model(db, mid)
    if m.status == "champion":
        raise HTTPException(409, "promote another model first; a level must always have a champion")
    m.status, m.shadow_until = "archived", None
    db.commit()
    return {"ok": True}


@router.post("/models/{mid}/challenge")
def challenge(mid: int, db: DB, _: Admin, days: int = 14):
    """Start shadow mode for a candidate manually (20 % of traffic)."""
    m = _model(db, mid)
    ok, why = mlops.consistency_ok(db, m)
    if not ok:
        raise HTTPException(409, f"consistency tests failed: {why}")
    for old in db.scalars(select(Model).where(Model.level == m.level, Model.status == "challenger")):
        old.status, old.shadow_until = "archived", None
    m.status, m.shadow_until = "challenger", datetime.now(UTC) + timedelta(days=max(1, min(days, 60)))
    db.commit()
    return {"ok": True, "shadow_until": m.shadow_until}


@router.post("/models/{mid}/pin")
def pin(mid: int, db: DB, _: Admin, pinned: bool = True):
    m = _model(db, mid)
    if m.status != "champion":
        raise HTTPException(409, "only the champion can be pinned")
    m.pinned = pinned
    db.commit()
    return {"ok": True, "pinned": pinned}


class CycleIn(BaseModel):
    kind: Literal["full", "incremental"] = "full"
    models: list[Literal["naive", "drift", "ridge", "lightgbm", "arima", "lstm", "gru", "tcn", "seq2seq_attn", "tft", "deepar"]] | None = Field(None, max_length=11)


@router.post("/cycle", status_code=202)
def cycle(body: CycleIn, _: Admin):
    try:
        jid = mlops.enqueue_cycle(body.kind, reason="admin", models=list(body.models) if body.models else None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"job queue unavailable: {e}") from e
    return {"job_id": jid}


@router.post("/drift/check", status_code=202)
def drift_now(_: Admin):
    try:
        from redis import Redis
        from rq import Queue

        from backend.app.config import settings

        Queue("carbonscope", connection=Redis.from_url(settings().redis_url)).enqueue("backend.app.mlops.drift_check", None, False)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"job queue unavailable: {e}") from e
    return {"queued": True}


@router.get("/drift")
def drift(db: DB, _: Admin, limit: int = 30):
    rows = db.scalars(select(DriftReport).order_by(DriftReport.id.desc()).limit(min(limit, 200))).all()
    return {"thresholds": {"psi": mlops.PSI_T, "psi_inputs": mlops.PSI_N, "error_ratio": mlops.ERR_T},
            "items": [{"id": r.id, "created_at": r.created_at, "psi_max": r.psi_max, "error_ratio": r.mase_drift, "triggered": r.triggered,
                       "details": r.details} for r in rows]}


@router.get("/schedule")
def schedule(_: Admin):
    from backend.app.scheduler import next_runs

    return {"timezone": "Asia/Kolkata", "jobs": next_runs(),
            "note": "Deep models retrain from scratch on the updated windowed panel; true online learning for TFT-style models is out of scope."}


@router.get("/metrics.csv")
def metrics_csv(_: Admin):
    p = ROOT / "results" / "tables" / "metrics.csv"
    if not p.exists():
        raise HTTPException(404, "no metrics yet")
    return FileResponse(p, media_type="text/csv", filename="carbonscope_metrics.csv")


@router.get("/features")
def features(db: DB, _: Admin):
    """Feature-store status: coverage and year span of every stored driver."""
    rows = db.execute(select(FeatureState.year, FeatureState.features)).all()
    stats: dict[str, dict] = {}
    for y, f in rows:
        for k, v in (f or {}).items():
            s = stats.setdefault(k, {"n": 0, "present": 0, "first": None, "last": None})
            s["n"] += 1
            if v is not None:
                s["present"] += 1
                s["first"] = y if s["first"] is None else min(s["first"], y)
                s["last"] = y if s["last"] is None else max(s["last"], y)
    src = {"edgar": "EDGAR 2025", "generation": "CEA", "grid_emission": "CEA", "gsdp": "MoSPI/World Bank", "population": "Census",
           "urban": "Census", "temp": "IMD / NASA POWER", "degree": "IMD / NASA POWER", "rainfall": "IMD / NASA POWER", "drought": "IMD / NASA POWER",
           "sales": "PPAC", "lockdown": "OxCGRT", "dummy": "policy calendar", "phase": "policy calendar", "coal_dep": "EDGAR", "road": "EDGAR",
           "renewable": "CEA", "climate_source": "ingest"}
    return {"items": sorted([{"feature": k, "coverage": round(v["present"] / max(v["n"], 1), 3), "first_year": v["first"], "last_year": v["last"],
                              "source": next((s for key, s in src.items() if key in k), "derived")} for k, v in stats.items()], key=lambda r: r["coverage"])}


@router.get("/sources")
def sources(db: DB, _: Admin):
    a = db.get(Artifact, "layer:triangulation")
    if a is None:
        raise HTTPException(404, "triangulation not computed")
    d = a.data
    last = max(int(y) for v in d["values"].values() for y in v)
    rows = []
    for c, v in d["values"].items():
        r = v.get(str(last)) or v.get(last) or {}
        rows.append({"state_code": c, "edgar_power_mt": r.get("edgar_power_mt"), "cea_power_mt": r.get("cea_power_mt"),
                     "agreement": r.get("agreement"), "divergent": r.get("divergent"), "calibrated_co2e_mt": r.get("calibrated_co2e_mt"),
                     "total_co2e_mt": r.get("total_co2e_mt"), "cea_over_edgar_factor": d["cea_over_edgar_factor"].get(c)})
    return {"year": last, "method": d["method"], "ghgpi": d["ghgpi"], "items": sorted(rows, key=lambda r: -(r["total_co2e_mt"] or 0))}


class InsightEdit(BaseModel):
    approved: bool | None = None
    body: str | None = Field(None, min_length=5, max_length=2000)
    admin_note: str | None = Field(None, max_length=1000)


@router.patch("/insights/{iid}")
def edit_insight(iid: int, body: InsightEdit, db: DB, user: Admin):
    i = db.get(Insight, iid)
    if i is None:
        raise HTTPException(404, "insight not found")
    if body.approved is not None:
        i.approved = body.approved
    if body.body is not None:
        i.body, i.edited_by = body.body, user.id
    if body.admin_note is not None:
        i.admin_note = body.admin_note
    db.commit()
    return {"ok": True, "id": i.id, "approved": i.approved, "edited": i.edited_by is not None}


def _invalidate():
    try:
        from backend.app.v2 import invalidate_cache

        invalidate_cache()
    except Exception:  # noqa: BLE001
        pass
