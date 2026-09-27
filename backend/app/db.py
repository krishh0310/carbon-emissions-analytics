"""SQLAlchemy 2.x ORM. Geometry is PostGIS on PostgreSQL and GeoJSON text elsewhere (SQLite tests)."""
from __future__ import annotations

from datetime import UTC, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.app.config import settings

# PostGIS geometry on PostgreSQL; GeoJSON text elsewhere (GeoAlchemy2 hooks SQLite tables even via with_variant)
GEOM = (Geometry("MULTIPOLYGON", srid=4326, spatial_index=True)
        if settings().database_url.startswith("postgresql") else Text())
JSONB = JSON().with_variant(__import__("sqlalchemy.dialects.postgresql", fromlist=["JSONB"]).JSONB(), "postgresql")


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RefreshToken(Base):
    """Rotation: each refresh revokes the presented jti; re-use of a revoked jti revokes the whole family."""
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class State(Base):
    __tablename__ = "states"
    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_hi: Mapped[str | None] = mapped_column(String(80))
    region: Mapped[str] = mapped_column(String(16))
    income_group: Mapped[str | None] = mapped_column(String(8))
    is_ut: Mapped[bool] = mapped_column(Boolean)
    coastal: Mapped[bool] = mapped_column(Boolean, default=False)
    geometry = mapped_column(GEOM)
    boundary_source: Mapped[str] = mapped_column(String(80))


class City(Base):
    __tablename__ = "cities"
    id: Mapped[int] = mapped_column(primary_key=True)
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    estimation_method: Mapped[str] = mapped_column(String(40))
    confidence_tier: Mapped[str] = mapped_column(String(2))


class EmissionState(Base):
    __tablename__ = "emissions_state"
    __table_args__ = (UniqueConstraint("state_code", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    co2_mt: Mapped[float | None] = mapped_column(Float)
    co2_per_capita: Mapped[float | None] = mapped_column(Float)
    carbon_intensity: Mapped[float | None] = mapped_column(Float)
    cea_power_co2_mt: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40))
    is_imputed: Mapped[bool] = mapped_column(Boolean, default=False)


class EmissionCity(Base):
    __tablename__ = "emissions_city"
    __table_args__ = (UniqueConstraint("city_id", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    co2_mt: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[str] = mapped_column(String(2))


class FeatureState(Base):
    """Wide Section-4 features stored as JSONB (schema evolves with sources; columns documented in README)."""
    __tablename__ = "features_state"
    __table_args__ = (UniqueConstraint("state_code", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    features = mapped_column(JSONB)


class Model(Base):
    __tablename__ = "models"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(20))
    horizon: Mapped[int] = mapped_column(Integer)
    metrics = mapped_column(JSONB)
    checkpoint_path: Mapped[str | None] = mapped_column(String(255))
    # registry (v3): level = state | state_sector; status = champion | challenger | candidate | archived
    level: Mapped[str] = mapped_column(String(16), default="state", index=True)
    status: Mapped[str] = mapped_column(String(12), default="candidate", index=True)
    val_score: Mapped[float | None] = mapped_column(Float)      # reconciled val MASE @ h=5 (lower is better)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)  # admin-pinned champion (auto-promotion skipped)
    shadow_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now)


class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    state_code: Mapped[str | None] = mapped_column(ForeignKey("states.code"), index=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), index=True)
    target: Mapped[str] = mapped_column(String(20))
    year: Mapped[int] = mapped_column(Integer)
    p10: Mapped[float] = mapped_column(Float)
    p50: Mapped[float] = mapped_column(Float)
    p90: Mapped[float] = mapped_column(Float)
    p50_reconciled: Mapped[float | None] = mapped_column(Float)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default="queued")
    logs: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Artifact(Base):
    """Small JSON documents computed offline (insights, leaderboard tables, importance, data-quality)."""
    __tablename__ = "artifacts"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    data = mapped_column(JSONB)


# ---- v2: state × sector ----------------------------------------------------------------------------
SECTOR_CHECK = "sector IN ('POWER','TRANSPORT','INDUSTRY','BUILDINGS','AGRICULTURE','WASTE','OTHER')"


class EmissionStateSector(Base):
    __tablename__ = "emissions_state_sector"
    __table_args__ = (UniqueConstraint("state_code", "sector", "year"), CheckConstraint(SECTOR_CHECK, name="ck_ess_sector"))
    id: Mapped[int] = mapped_column(primary_key=True)
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), index=True)
    sector: Mapped[str] = mapped_column(String(12), index=True)
    year: Mapped[int] = mapped_column(Integer)
    co2e_mt: Mapped[float] = mapped_column(Float)
    co2_mt: Mapped[float | None] = mapped_column(Float)
    ch4_co2e_mt: Mapped[float | None] = mapped_column(Float)
    n2o_co2e_mt: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(160))
    confidence: Mapped[str] = mapped_column(String(2))


class ForecastSector(Base):
    __tablename__ = "forecasts_sector"
    __table_args__ = (CheckConstraint(SECTOR_CHECK, name="ck_fs_sector"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), index=True)
    sector: Mapped[str] = mapped_column(String(12), index=True)
    target: Mapped[str] = mapped_column(String(20), default="co2e_mt")
    year: Mapped[int] = mapped_column(Integer)
    p10: Mapped[float] = mapped_column(Float)
    p50: Mapped[float] = mapped_column(Float)
    p90: Mapped[float] = mapped_column(Float)
    p50_reconciled: Mapped[float | None] = mapped_column(Float)


class Insight(Base):
    __tablename__ = "insights"
    id: Mapped[int] = mapped_column(primary_key=True)
    state_code: Mapped[str | None] = mapped_column(ForeignKey("states.code"), index=True)  # NULL = national
    sector: Mapped[str | None] = mapped_column(String(12), index=True)
    type: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(8), index=True)  # info | notice | warning | alert
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    evidence = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    title_hi: Mapped[str | None] = mapped_column(String(240))
    body_hi: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)       # admin moderation: hidden when False
    admin_note: Mapped[str | None] = mapped_column(Text)
    edited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ServingLog(Base):
    """Daily request counts per served model (champion vs shadow challenger)."""
    __tablename__ = "serving_log"
    __table_args__ = (UniqueConstraint("model_id", "endpoint", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))
    endpoint: Mapped[str] = mapped_column(String(60))
    day = mapped_column(Date, index=True)
    n: Mapped[int] = mapped_column(Integer, default=0)


class DriftReport(Base):
    __tablename__ = "drift_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    level: Mapped[str] = mapped_column(String(16))
    psi_max: Mapped[float | None] = mapped_column(Float)
    mase_drift: Mapped[float | None] = mapped_column(Float)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    details = mapped_column(JSON)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    params = mapped_column(JSONB)
    results = mapped_column(JSONB)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = settings().database_url
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engine = create_engine(url, **kw)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_db():
    engine()
    with _Session() as s:
        yield s


def session():
    engine()
    return _Session()
