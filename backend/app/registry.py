"""Model registry + serving policy.

- Every forecast endpoint serves the CHAMPION of its level ("state" = v1 fossil CO2, "state_sector" = v2 CO2e).
- Viewers cannot pick a model and never see model identity; admins may request any registered model by name.
- Shadow mode: while a challenger has `shadow_until` in the future, ~20 % of requests (stable hash of the caller)
  are served by the challenger; every served request is counted in serving_log for the admin dashboard.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.app.db import Model, ServingLog, User

SHADOW_SHARE = 0.20
PUBLIC_NAME = "CarbonScope Forecast"


def db_name(name: str, level: str) -> str:
    return f"s_{name}" if level == "state_sector" else name


def public_name(m: Model) -> str:
    return m.name.removeprefix("s_")


def champion(db: Session, level: str) -> Model | None:
    m = db.scalar(select(Model).where(Model.level == level, Model.status == "champion").order_by(Model.id.desc()))
    if m is None:  # no explicit champion yet: best validation score
        m = db.scalar(select(Model).where(Model.level == level, Model.val_score.is_not(None)).order_by(Model.val_score))
    return m


def challenger(db: Session, level: str) -> Model | None:
    now = datetime.now(UTC)
    m = db.scalar(select(Model).where(Model.level == level, Model.status == "challenger").order_by(Model.id.desc()))
    if m and m.shadow_until and (m.shadow_until.replace(tzinfo=UTC) if m.shadow_until.tzinfo is None else m.shadow_until) > now:
        return m
    return None


def _bucket(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _log(db: Session, m: Model, role: str, endpoint: str) -> None:
    try:
        if db.get_bind().dialect.name == "postgresql":
            stmt = pg_insert(ServingLog).values(model_id=m.id, role=role, endpoint=endpoint, day=date.today(), n=1)
            db.execute(stmt.on_conflict_do_update(index_elements=["model_id", "endpoint", "day"],
                                                  set_={"n": ServingLog.n + 1}))
        else:
            row = db.scalar(select(ServingLog).where(ServingLog.model_id == m.id, ServingLog.endpoint == endpoint,
                                                     ServingLog.day == date.today()))
            if row:
                row.n += 1
            else:
                db.add(ServingLog(model_id=m.id, role=role, endpoint=endpoint, day=date.today(), n=1))
        db.commit()
    except Exception:  # noqa: BLE001 — logging must never break serving
        db.rollback()


def serve(db: Session, user: User, level: str, endpoint: str, requested: str | None = None) -> Model:
    """Resolve which model answers this request (see module docstring)."""
    if requested:
        if user.role != "admin":
            raise HTTPException(403, "model selection is restricted to administrators")
        m = db.scalar(select(Model).where(Model.name == db_name(requested, level), Model.level == level).order_by(Model.id.desc()))
        if m is None:
            raise HTTPException(404, "model not found")
        return m
    champ = champion(db, level)
    if champ is None:
        raise HTTPException(503, "no forecast model available yet")
    chal = challenger(db, level)
    if chal is not None and _bucket(f"{user.id}:{endpoint}") < SHADOW_SHARE:
        _log(db, chal, "challenger", endpoint)
        return chal
    _log(db, champ, "champion", endpoint)
    return champ


def describe(m: Model, user: User) -> dict:
    """Model identity only for admins; viewers get the product name."""
    if user.role == "admin":
        return {"forecast": PUBLIC_NAME, "model": public_name(m), "version": m.version, "status": m.status}
    return {"forecast": PUBLIC_NAME}
