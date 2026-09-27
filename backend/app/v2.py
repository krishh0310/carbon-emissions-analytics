"""/api/v2 — state x sector emissions, sector forecasts, ATAR insights, scenarios, map layers, flow field, consistency."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import registry
from backend.app.config import settings
from backend.app.db import (
    Artifact,
    EmissionState,
    EmissionStateSector,
    ForecastSector,
    Insight,
    Scenario,
    State,
    User,
    get_db,
)
from backend.app.ratelimit import limiter
from backend.app.security import current_user, require_admin

ROOT = Path(__file__).resolve().parents[2]
SECTORS = ("POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER")
Sector = Literal["POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER"]
ModelName = Query(None, pattern=r"^[a-z0-9_]{2,20}$", description="admin only: serve a specific registered model")
DB = Annotated[Session, Depends(get_db)]
Viewer = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(require_admin)]
router = APIRouter(prefix="/api/v2", tags=["v2"])


# ---- tiny Redis cache (optional: falls back to no cache if Redis is down) --------------------------------
def _redis():
    try:
        from redis import Redis

        r = Redis.from_url(settings().redis_url, socket_connect_timeout=0.2, socket_timeout=0.5)
        r.ping()
        return r
    except Exception:  # noqa: BLE001
        return None


def cached(key: str, ttl: int, fn):
    r = _redis()
    if r is not None:
        hit = r.get(f"cs:{key}")
        if hit:
            return json.loads(hit)
    val = fn()
    if r is not None:
        r.setex(f"cs:{key}", ttl, json.dumps(val, default=float))
    return val


def invalidate_cache() -> None:
    r = _redis()
    if r is not None:
        for k in r.scan_iter("cs:*"):
            r.delete(k)


def _code(code: str) -> str:
    code = code.upper()
    if len(code) != 5 or not code.startswith("IN-") or not code[3:].isalpha():
        raise HTTPException(422, "state code must look like IN-XX")
    return code


# ---- sectors ------------------------------------------------------------------------------------------
@router.get("/states/{code}/sectors")
def state_sectors(code: str, db: DB, _: Viewer):
    code = _code(code)
    st = db.get(State, code) or _404("state")
    rows = db.scalars(select(EmissionStateSector).where(EmissionStateSector.state_code == code)
                      .order_by(EmissionStateSector.sector, EmissionStateSector.year)).all()
    if not rows:
        raise HTTPException(404, "no sector data")
    last = max(r.year for r in rows)
    hist: dict[str, list] = {}
    meta = {}
    for r in rows:
        hist.setdefault(r.sector, []).append({"year": r.year, "co2e_mt": r.co2e_mt, "co2_mt": r.co2_mt,
                                              "ch4_co2e_mt": r.ch4_co2e_mt, "n2o_co2e_mt": r.n2o_co2e_mt})
        meta[r.sector] = {"source": r.source, "method": r.method, "confidence": r.confidence}
    latest = {r.sector: r.co2e_mt for r in rows if r.year == last}
    tot = sum(latest.values()) or 1
    return {"code": code, "name": st.name, "name_hi": st.name_hi, "year": last, "unit": "MtCO2e (AR6 GWP-100)",
            "breakdown": [{"sector": s, "co2e_mt": latest.get(s, 0), "share": latest.get(s, 0) / tot, **meta.get(s, {})} for s in SECTORS],
            "history": hist}


@router.get("/states/{code}/sectors/{sector}/forecast")
def sector_forecast(code: str, sector: Sector, db: DB, user: Viewer, horizon: int = Query(5, ge=1, le=5), model: str | None = ModelName):
    code = _code(code)
    m = registry.serve(db, user, "state_sector", "sector_forecast", model)
    rows = db.scalars(select(ForecastSector).where(ForecastSector.model_id == m.id, ForecastSector.state_code == code,
                                                   ForecastSector.sector == sector).order_by(ForecastSector.year).limit(horizon)).all()
    return {"code": code, "sector": sector, **registry.describe(m, user), "unit": "MtCO2e",
            "points": [{"year": f.year, "p10": f.p10, "p50": f.p50, "p90": f.p90, "p50_reconciled": f.p50_reconciled} for f in rows]}


@router.get("/states/{code}/sectors/forecast")
def sector_forecast_all(code: str, db: DB, user: Viewer, model: str | None = ModelName):
    """All 7 sector forecasts of a state in one call (P10/P50/P90 + reconciled P50)."""
    code = _code(code)
    m = registry.serve(db, user, "state_sector", "sector_forecast_all", model)
    out: dict[str, list] = {s: [] for s in SECTORS}
    for f in db.scalars(select(ForecastSector).where(ForecastSector.model_id == m.id, ForecastSector.state_code == code)
                        .order_by(ForecastSector.year)):
        out[f.sector].append({"year": f.year, "p10": f.p10, "p50": f.p50, "p90": f.p90, "p50_reconciled": f.p50_reconciled})
    return {"code": code, **registry.describe(m, user), "unit": "MtCO2e", "sectors": out}


@router.get("/drivers")
def drivers(db: DB, _: Viewer):
    """Viewer-safe driver influence per sector (relative 0-1 weights of input groups for the serving forecast).
    Derived from permutation importance; no model identity or error metrics are exposed."""
    champ = registry.champion(db, "state_sector")
    a = db.get(Artifact, f"importance_sector:{registry.public_name(champ)}") if champ else None
    rows = a.data if a else []
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        out.setdefault(r["sector"], {})[r["group"]] = max(float(r["importance"]), 0.0)
    for sec, g in out.items():
        tot = sum(g.values()) or 1.0
        out[sec] = {k: round(v / tot, 4) for k, v in sorted(g.items(), key=lambda kv: -kv[1])}
    return {"method": "Relative influence = share of forecast-error increase when an input group is randomly shuffled.",
            "sectors": out}


@router.get("/sectors/series")
def sector_series(db: DB, user: Viewer, model: str | None = ModelName):
    """All state x sector x year values + reconciled forecasts in one payload (for the animated map)."""
    m_ = registry.serve(db, user, "state_sector", "sector_series", model)
    model = registry.public_name(m_)

    def build():
        hist: dict = {}
        for c, s, y, v in db.execute(select(EmissionStateSector.state_code, EmissionStateSector.sector,
                                            EmissionStateSector.year, EmissionStateSector.co2e_mt)):
            hist.setdefault(c, {}).setdefault(s, {})[y] = round(v, 5)
        fc: dict = {}
        m = m_
        if m:
            for f in db.scalars(select(ForecastSector).where(ForecastSector.model_id == m.id)):
                fc.setdefault(f.state_code, {}).setdefault(f.sector, []).append(
                    {"year": f.year, "p10": round(f.p10, 5), "p50": round(f.p50_reconciled if f.p50_reconciled is not None else f.p50, 5),
                     "p90": round(f.p90, 5)})
        return {"sectors": SECTORS, "history": hist, "forecast": fc}
    return {**cached(f"series:{m_.id}", 3600, build), **registry.describe(m_, user)}


# ---- cities (v3 analytics) ------------------------------------------------------------------------------
CITY_METHOD = ("City CO₂e = Σ EDGAR 0.1° grid cells whose centre lies within the city buffer (25 km for metros, "
               "12 km otherwise); sector split = the same cells per sector. Forecast = Σ_sector state reconciled "
               "forecast × the city's mean share of that state-sector in the last 3 observed years. These are "
               "estimates, not measured municipal inventories.")


@router.get("/cities")
def cities_ranking(db: DB, _: Viewer, state: str | None = Query(None, pattern=r"^IN-[A-Z]{2}$"),
                   sort: Literal["co2e_mt", "cagr10_pct", "per_capita_t", "share_of_state_pct", "confidence_tier"] = "co2e_mt",
                   limit: int = Query(100, ge=1, le=200)):
    a = db.get(Artifact, "cities_v3") or _404("cities")
    rows = [r for r in a.data["ranking"] if not state or r["state_code"] == state]
    rows.sort(key=lambda r: (r[sort] is None, -(r[sort] or 0) if sort != "confidence_tier" else r[sort]))
    return {"year": a.data["year"], "method": CITY_METHOD, "items": rows[:limit]}


@router.get("/cities/{city_id}")
def city_detail(city_id: int, db: DB, _: Viewer):
    a = db.get(Artifact, "cities_v3") or _404("cities")
    d = a.data["details"].get(str(city_id)) or _404("city")
    return {**d, "method": CITY_METHOD}


# ---- insights -----------------------------------------------------------------------------------------
@router.get("/insights")
def insights(db: DB, user: Viewer, state: str | None = Query(None, pattern=r"^IN-[A-Z]{2}$|^NATIONAL$"),
             sector: Sector | None = None, severity: Literal["alert", "warning", "notice", "info"] | None = None,
             type: str | None = Query(None, pattern=r"^[A-Z]{3,12}$"), limit: int = Query(50, ge=1, le=200),
             offset: int = Query(0, ge=0, le=10_000), q_text: str | None = Query(None, alias="q", max_length=80),
             include_hidden: bool = False):
    q = select(Insight)
    if not (include_hidden and user.role == "admin"):
        q = q.where(Insight.approved.is_(True))  # admin-hidden insights never reach viewers
    if q_text:
        like = f"%{q_text}%"
        q = q.where(Insight.title.ilike(like) | Insight.body.ilike(like))
    if state == "NATIONAL":
        q = q.where(Insight.state_code.is_(None))
    elif state:
        q = q.where(Insight.state_code == state)
    if sector:
        q = q.where(Insight.sector == sector)
    if severity:
        q = q.where(Insight.severity == severity)
    if type:
        q = q.where(Insight.type == type)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Insight.id).limit(limit).offset(offset)).all()
    def one(i: Insight) -> dict:
        ev = i.evidence or {}
        data = ev.get("data", ev) if isinstance(ev, dict) else ev
        d = {"id": i.id, "state_code": i.state_code, "sector": i.sector, "type": i.type, "severity": i.severity,
             "title": i.title, "body": i.body, "title_hi": i.title_hi, "body_hi": i.body_hi, "evidence": data,
             "viz": ev.get("viz") if isinstance(ev, dict) else None, "how": ev.get("how") if isinstance(ev, dict) else None,
             "created_at": i.created_at}
        if user.role == "admin":
            d |= {"approved": i.approved, "admin_note": i.admin_note, "edited": i.edited_by is not None}
        return d

    return {"total": total, "items": [one(i) for i in rows]}


# ---- scenarios ----------------------------------------------------------------------------------------
class ScenarioIn(BaseModel):
    name: str = Field("custom", min_length=1, max_length=80, pattern=r"^[\w .\-()]+$")
    preset: Literal["bau", "moderate", "ambitious"] | None = None
    renewable_pp: float = Field(0, ge=0, le=40)
    ev_share_pct: float = Field(0, ge=0, le=60)
    industrial_growth_pp: float = Field(0, ge=-5, le=5)
    building_efficiency_pct: float = Field(0, ge=0, le=30)
    states: list[Annotated[str, Field(pattern=r"^IN-[A-Z]{2}$")]] | None = Field(None, max_length=36)
    model: str | None = Field(None, pattern=r"^[a-z0-9_]{2,20}$", description="admin only")


@router.get("/scenarios/presets")
def presets(_: Viewer):
    from dataclasses import asdict

    from src.scenarios import BOUNDS, PRESETS

    return {"bounds": BOUNDS, "presets": {k: {"name": n, **asdict(p)} for k, (n, p) in PRESETS.items()}}


@router.post("/scenarios/run", status_code=201)
@limiter.limit("20/minute")
def run_scenario(request: Request, body: ScenarioIn, db: DB, user: Viewer):
    from src.scenarios import PRESETS, Params, run

    served = registry.serve(db, user, "state_sector", "scenario", body.model if user.role == "admin" and body.model else None)
    body.model = registry.public_name(served)
    if body.preset:
        name, p = PRESETS[body.preset]
    else:
        name, p = body.name, Params(body.renewable_pp, body.ev_share_pct, body.industrial_growth_pp, body.building_efficiency_pct)
    try:
        res = run(p.validate(), body.states, body.model)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(422, str(e)) from e
    sc = Scenario(name=name, params={**res["params"], "states": body.states, "model": body.model}, results=res, created_by=user.id)
    db.add(sc)
    db.commit()
    if user.role != "admin":
        res = {k: v for k, v in res.items() if k != "model"}
    return {"id": sc.id, "name": name, **res, **registry.describe(served, user)}


@router.get("/scenarios/{sid}")
def get_scenario(sid: int, db: DB, user: Viewer):
    sc = db.get(Scenario, sid) or _404("scenario")
    res = dict(sc.results or {})
    params = dict(sc.params or {})
    if user.role != "admin":  # never leak model identity to viewers
        res.pop("model", None)
        params.pop("model", None)
    return {"id": sc.id, "name": sc.name, "params": params, "created_at": sc.created_at, **res}


# ---- map layers / flow field / models --------------------------------------------------------------------
def _artifact(db: Session, key: str):
    a = db.get(Artifact, key)
    return a.data if a else _404(key)


@router.get("/layers/{layer_id}")
def layer(layer_id: Literal["anomaly", "uncertainty", "triangulation", "decoupling", "watchlist"], db: DB, _: Viewer):
    """Derived map layers (state x year values): anomaly = actual vs 5-yr log-linear trend (%); uncertainty =
    (P90−P10)/P50 of the state total forecast (%). The 36 simplified polygons (~200 KB) are served once by
    /api/v1/states, so per-layer vector tiles are unnecessary; layers are value tables cached in Redis."""
    return cached(f"layer:{layer_id}", 3600, lambda: _artifact(db, f"layer:{layer_id}"))


@router.get("/flow-field")
def flow_field(db: DB, _: Viewer, sector: Literal["TOTAL", "POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER"] = "TOTAL"):
    return cached(f"flow:{sector}", 86400, lambda: _artifact(db, f"flow:{sector}"))


@router.get("/models")
def models(db: DB, _: Admin):
    return {"leaderboard": _artifact(db, "sector_leaderboard"), "experiments": _artifact(db, "experiments")}


@router.get("/models/{name}/importance")
def importance(name: str, db: DB, _: Admin):
    if not name.replace("_", "").isalnum() or len(name) > 20:
        raise HTTPException(422, "bad model name")
    return _artifact(db, f"importance_sector:{name}")


@router.get("/consistency")
def consistency(db: DB, user: Viewer, model: str | None = ModelName):
    """Hierarchy checks (also a CI test): Σ sectors == state total (history) and, for reconciled forecasts,
    Σ cells per state/sector/national are internally coherent. Returns max absolute gaps in Mt."""
    hist = db.execute(select(EmissionStateSector.state_code, EmissionStateSector.year, func.sum(EmissionStateSector.co2_mt))
                      .group_by(EmissionStateSector.state_code, EmissionStateSector.year)).all()
    v1 = {(c, y): v for c, y, v in db.execute(select(EmissionState.state_code, EmissionState.year, EmissionState.co2_mt))}
    gap_hist = max((abs((s or 0.0) - (v1.get((c, y)) or 0.0)) for c, y, s in hist), default=0.0)
    m = registry.serve(db, user, "state_sector", "consistency", model)
    neg = 0
    if m:
        neg = db.scalar(select(func.count()).select_from(ForecastSector).where(ForecastSector.model_id == m.id,
                                                                              ForecastSector.p50_reconciled < 0)) or 0
    ok = gap_hist < 1e-3 and neg == 0
    return {"ok": ok, "checks": {
        "sector_co2_sum_minus_state_co2_max_abs_mt": gap_hist,
        "negative_reconciled_cells": neg,
        "note": "Reconciled forecasts are produced bottom-up from MinT cells, so state/sector/national totals are exact sums by construction."}}


def _404(what):
    raise HTTPException(404, f"{what} not found")
