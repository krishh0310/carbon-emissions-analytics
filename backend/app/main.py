"""CarbonScope India API — OpenAPI at /docs. All routes under /api/v1."""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app import registry
from backend.app.config import settings
from backend.app.db import (
    Artifact,
    City,
    EmissionCity,
    EmissionState,
    FeatureState,
    Forecast,
    Job,
    State,
    User,
    get_db,
)
from backend.app.security import current_user, hash_password, issue_tokens, require_admin, rotate, verify_password

S = settings()
from backend.app.ratelimit import limiter  # noqa: E402  (shared with the v2 router)

app = FastAPI(title="CarbonScope India API", version="1.0.0",
              description="State/UT & city CO₂ forecasting for India. Emissions are EDGAR-downscaled estimates; "
                          "city values are proxy estimates with confidence tiers — never measured inventories.")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in S.cors_origins.split(",") if o.strip()],
                   allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    r: Response = await call_next(request)
    r.headers.update({
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
                                   "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                                   "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'",
    })
    return r


api = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]
Viewer = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(require_admin)]
CODE_RE = re.compile(r"^IN-[A-Z]{2}$")


def state_code(code: str) -> str:
    code = code.upper()
    if not CODE_RE.match(code):
        raise HTTPException(422, "state code must look like IN-XX")
    return code


class Page(BaseModel):
    limit: int = Field(50, ge=1)
    offset: int = Field(0, ge=0)

    @field_validator("limit")
    @classmethod
    def cap(cls, v):
        return min(v, S.max_page_size)


def page(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100_000)) -> Page:
    return Page(limit=limit, offset=offset)


# ---- auth -------------------------------------------------------------------------------------------
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=2048)


@api.post("/auth/register", status_code=201, tags=["auth"])
@limiter.limit(S.rate_limit_auth)
def register(request: Request, body: Credentials, db: DB):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "email already registered")
    u = User(email=body.email.lower(), hash=hash_password(body.password), role="viewer")  # admins only via seed/DB
    db.add(u)
    db.commit()
    return {"id": u.id, "email": u.email, "role": u.role}


@api.post("/auth/login", tags=["auth"])
@limiter.limit(S.rate_limit_auth)
def login(request: Request, body: Credentials, db: DB):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(u.hash if u else None, body.password) or u is None:
        raise HTTPException(401, "invalid credentials")
    return issue_tokens(db, u)


@api.post("/auth/refresh", tags=["auth"])
@limiter.limit(S.rate_limit_auth)
def refresh(request: Request, body: RefreshIn, db: DB):
    return rotate(db, body.refresh_token)


@api.get("/auth/me", tags=["auth"])
def me(u: Viewer):
    return {"id": u.id, "email": u.email, "role": u.role}


# ---- states -----------------------------------------------------------------------------------------
def _geojson(db: Session, codes: list[str] | None = None) -> dict[str, dict | None]:
    if db.get_bind().dialect.name == "postgresql":
        q = select(State.code, func.ST_AsGeoJSON(State.geometry, 4))
    else:
        q = select(State.code, State.geometry)
    if codes:
        q = q.where(State.code.in_(codes))
    return {c: json.loads(g) if g else None for c, g in db.execute(q)}


@api.get("/states", tags=["states"])
@limiter.limit(S.rate_limit_default)
def states(request: Request, db: DB, _: Viewer, year: int | None = Query(None, ge=1990, le=2100),
           geometry: bool = True, p: Page = Depends(page)):
    """All 28 states + 8 UTs with region, geometry and emissions for `year` (default: latest)."""
    y = year or db.scalar(select(func.max(EmissionState.year)))
    rows = db.execute(select(State, EmissionState).join(EmissionState, (EmissionState.state_code == State.code)
                                                        & (EmissionState.year == y), isouter=True)
                      .order_by(State.code).limit(p.limit).offset(p.offset)).all()
    geo = _geojson(db, [s.code for s, _ in rows]) if geometry else {}
    total = db.scalar(select(func.count()).select_from(State))
    return {"year": y, "total": total, "items": [{
        "code": s.code, "name": s.name, "name_hi": s.name_hi, "region": s.region, "income_group": s.income_group,
        "is_ut": s.is_ut, "coastal": s.coastal, "boundary_source": s.boundary_source,
        "co2_mt": e.co2_mt if e else None, "co2_per_capita": e.co2_per_capita if e else None,
        "carbon_intensity": e.carbon_intensity if e else None, "source": e.source if e else None,
        "geometry": geo.get(s.code)} for s, e in rows]}


@api.get("/states/{code}/history", tags=["states"])
def history(code: str, db: DB, _: Viewer, target: Literal["co2", "co2_per_capita", "carbon_intensity"] = "co2",
            level: Literal["state"] = "state"):
    code = state_code(code)
    st = db.get(State, code) or _404("state")
    col = {"co2": EmissionState.co2_mt, "co2_per_capita": EmissionState.co2_per_capita,
           "carbon_intensity": EmissionState.carbon_intensity}[target]
    rows = db.execute(select(EmissionState.year, col, EmissionState.cea_power_co2_mt, EmissionState.is_imputed)
                      .where(EmissionState.state_code == code).order_by(EmissionState.year)).all()
    feats = db.execute(select(FeatureState.year, FeatureState.features).where(FeatureState.state_code == code)
                       .order_by(FeatureState.year)).all()
    return {"code": code, "name": st.name, "target": target, "level": level, "source": "EDGAR-downscaled",
            "points": [{"year": y, "value": v, "cea_power_co2_mt": c, "is_imputed": i} for y, v, c, i in rows],
            "features": [{"year": y, **(f or {})} for y, f in feats]}


def _404(what):
    raise HTTPException(404, f"{what} not found")


@api.get("/states/{code}/forecast", tags=["states"])
def state_forecast(code: str, db: DB, user: Viewer, horizon: int = Query(5, ge=1, le=5),
                   model: str | None = Query(None, pattern=r"^[a-z0-9_]{2,20}$", description="admin only: serve a specific registered model")):
    code = state_code(code)
    db.get(State, code) or _404("state")
    m = registry.serve(db, user, "state", "state_forecast", model)
    rows = db.scalars(select(Forecast).where(Forecast.model_id == m.id, Forecast.state_code == code)
                      .order_by(Forecast.year).limit(horizon)).all()
    return {"code": code, **registry.describe(m, user), "unit": "MtCO2",
            "points": [{"year": f.year, "p10": f.p10, "p50": f.p50, "p90": f.p90, "p50_reconciled": f.p50_reconciled}
                       for f in rows]}


# ---- cities -----------------------------------------------------------------------------------------
@api.get("/cities", tags=["cities"])
def cities(db: DB, _: Viewer, state: str | None = Query(None, pattern=r"^(IN-)?[A-Za-z]{2}$"), p: Page = Depends(page)):
    y = db.scalar(select(func.max(EmissionCity.year)))
    q = select(City, EmissionCity.co2_mt).join(EmissionCity, (EmissionCity.city_id == City.id) & (EmissionCity.year == y),
                                               isouter=True)
    if state:
        q = q.where(City.state_code == state_code(state if state.upper().startswith("IN-") else f"IN-{state}"))
    rows = db.execute(q.order_by(EmissionCity.co2_mt.desc().nullslast()).limit(p.limit).offset(p.offset)).all()
    return {"year": y, "note": "Estimates from EDGAR grid within a city buffer — not measured inventories.",
            "items": [{"id": c.id, "name": c.name, "state_code": c.state_code, "lat": c.lat, "lon": c.lon,
                       "estimation_method": c.estimation_method, "confidence_tier": c.confidence_tier, "co2_mt": v}
                      for c, v in rows]}


@api.get("/cities/{city_id}/forecast", tags=["cities"])
def city_forecast(city_id: int, db: DB, user: Viewer, model: str | None = Query(None, pattern=r"^[a-z0-9_]{2,20}$", description="admin only: serve a specific registered model")):
    c = db.get(City, city_id) or _404("city")
    m = registry.serve(db, user, "state", "city_forecast", model)
    hist = db.execute(select(EmissionCity.year, EmissionCity.co2_mt).where(EmissionCity.city_id == city_id)
                      .order_by(EmissionCity.year)).all()
    fc = db.scalars(select(Forecast).where(Forecast.model_id == m.id, Forecast.city_id == city_id).order_by(Forecast.year)).all()
    return {"id": c.id, "name": c.name, "state_code": c.state_code, "confidence_tier": c.confidence_tier,
            "estimation_method": c.estimation_method, **registry.describe(m, user),
            "method_note": "City forecast = state forecast × mean city share of state over the last 3 years.",
            "history": [{"year": y, "co2_mt": v} for y, v in hist],
            "points": [{"year": f.year, "p10": f.p10, "p50": f.p50, "p90": f.p90} for f in fc]}


# ---- insights / models / data quality (precomputed artifacts) ---------------------------------------
def _artifact(db: Session, key: str):
    a = db.get(Artifact, key)
    return a.data if a else _404(key)


@api.get("/insights/{kind}", tags=["insights"])
def insights(kind: Literal["decoupling", "carbon-intensity", "watchlist", "cities"], db: DB, user: Viewer,
             p: Page = Depends(page)):
    data = _artifact(db, "insights")
    items = data[kind.replace("-", "_")]
    extra = {"best_model": data.get("best_model")} if user.role == "admin" else {}
    return {"year": data["year"], **extra, "notes": data["notes"],
            "total": len(items), "items": items[p.offset: p.offset + p.limit]}


@api.get("/models", tags=["admin"])
def models(db: DB, _: Admin):
    """Leaderboard: ALL-state MASE per horizon & split (+ MinT-reconciled MASE)."""
    return _artifact(db, "leaderboard")


@api.get("/models/{name}/importance", tags=["admin"])
def importance(name: str, db: DB, _: Admin):
    if not re.match(r"^[a-z0-9_]{2,20}$", name):
        raise HTTPException(422, "bad model name")
    return _artifact(db, f"importance:{name}")


@api.get("/models/{name}/backtest", tags=["admin"])
def backtest(name: str, db: DB, _: Admin, state: str = Query("IN-MH")):
    if not re.match(r"^[a-z0-9_]{2,20}$", name):
        raise HTTPException(422, "bad model name")
    data = _artifact(db, f"backtest:{name}")
    return {"model": name, "state": state_code(state), "points": [r for r in data if r["state_code"] == state_code(state)]}


@api.get("/data-quality", tags=["admin"])
def data_quality(db: DB, _: Admin):
    return _artifact(db, "data_quality")


MAP_FEATURES = ("edgar_power_mt", "edgar_industry_mt", "edgar_road_mt", "edgar_cement_mt", "edgar_buildings_mt",
                "avg_temp_c", "monsoon_rainfall_mm", "population_mn", "cooling_degree_days", "coal_dependence", "gsdp_const_cr")


@api.get("/map/series", tags=["map"])
def map_series(db: DB, user: Viewer, model: str | None = Query(None, pattern=r"^[a-z0-9_]{2,20}$", description="admin only: serve a specific registered model")):
    """Every state x year value for the animated map in one payload (≈40 KB gzipped).
    Layers: co2, co2_per_capita, carbon_intensity + sector/climate/population features; forecasts (P10/P50/P90,
    MinT-reconciled P50 where available) for the CO2 layer from `model`."""
    em = db.execute(select(EmissionState.state_code, EmissionState.year, EmissionState.co2_mt,
                           EmissionState.co2_per_capita, EmissionState.carbon_intensity)).all()
    fs = {(c, y): f or {} for c, y, f in db.execute(select(FeatureState.state_code, FeatureState.year, FeatureState.features))}
    series: dict[str, dict[str, dict[int, float | None]]] = {}
    for c, y, co2, pc, ci in em:
        s = series.setdefault(c, {})
        f = fs.get((c, y), {})
        for k, v in (("co2", co2), ("co2_per_capita", pc), ("carbon_intensity", ci), *((k, f.get(k)) for k in MAP_FEATURES)):
            s.setdefault(k, {})[y] = v
    m = registry.serve(db, user, "state", "map_series", model)
    fc: dict[str, list[dict]] = {}
    if m:
        for f in db.scalars(select(Forecast).where(Forecast.model_id == m.id, Forecast.state_code.is_not(None))
                            .order_by(Forecast.year)):
            fc.setdefault(f.state_code or "", []).append(
                {"year": f.year, "p10": f.p10, "p50": f.p50_reconciled if f.p50_reconciled is not None else f.p50, "p90": f.p90})
    years = sorted({y for _, y, *__ in em})
    return {"years": years, "forecast_years": sorted({p["year"] for v in fc.values() for p in v}), **registry.describe(m, user),
            "series": series, "forecast": fc}


# ---- admin ------------------------------------------------------------------------------------------
class RetrainIn(BaseModel):
    models: list[Literal["naive", "drift", "ridge", "lightgbm", "arima", "lstm", "gru", "tcn", "seq2seq_attn", "tft",
                         "deepar"]] = Field(default=["lightgbm", "tft"], max_length=11)
    fast: bool = False


@api.post("/admin/retrain", status_code=202, tags=["admin"])
@limiter.limit("5/hour")
def retrain(request: Request, body: RetrainIn, _: Annotated[User, Depends(require_admin)]):
    """Legacy endpoint: enqueues a full continuous-learning cycle for the selected fossil-CO2 models (+ all sector models)."""
    from backend.app import mlops

    try:
        jid = mlops.enqueue_cycle("full", reason="admin retrain", models=list(body.models))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "job queue unavailable") from e
    return {"job_id": jid, "status": "queued"}


@api.get("/admin/jobs", tags=["admin"])
def jobs(db: DB, _: Annotated[User, Depends(require_admin)], p: Page = Depends(page)):
    rows = db.scalars(select(Job).order_by(Job.id.desc()).limit(p.limit).offset(p.offset)).all()
    return {"items": [{"id": j.id, "type": j.type, "status": j.status, "created_at": j.created_at,
                       "finished_at": j.finished_at} for j in rows]}


@api.get("/admin/jobs/{job_id}", tags=["admin"])
def job(job_id: int, db: DB, _: Annotated[User, Depends(require_admin)]):
    j = db.get(Job, job_id) or _404("job")
    return {"id": j.id, "type": j.type, "status": j.status, "logs": j.logs[-20000:], "created_at": j.created_at,
            "finished_at": j.finished_at}


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


app.include_router(api)

from backend.app.admin import router as admin_router  # noqa: E402
from backend.app.v2 import router as v2_router  # noqa: E402

app.include_router(v2_router)
app.include_router(admin_router)
