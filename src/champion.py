"""Offline champion lookup (same rule as the serving registry): lowest validation MASE at h=5 among models with
full coverage. Level 'state' uses val_mase_h5; 'state_sector' uses the two-level-reconciled val MASE."""
from __future__ import annotations

import json

from src.data.cache import ROOT

PARTIAL = {"arima"}  # fitted on a subset of states -> never eligible


def best(level: str = "state_sector") -> str:
    """Serving champion from the database registry (so offline insights/scenarios match what the API serves);
    falls back to the lowest-validation-MASE rule on the results registry when no database is reachable."""
    try:
        from sqlalchemy import select

        from backend.app.db import Model, session

        with session() as db:
            m = db.scalar(select(Model).where(Model.level == level, Model.status == "champion").order_by(Model.id.desc()))
            if m is not None:
                return m.name.removeprefix("s_")
    except Exception:  # noqa: BLE001 — no DB configured (CI, offline runs)
        pass
    path, key = (("sector_registry.json", "val_reconciled_mase_h5") if level == "state_sector"
                 else ("model_registry.json", "val_mase_h5"))
    reg = json.loads((ROOT / "results" / path).read_text())
    ok = {k: v["metrics"].get(key) for k, v in reg.items() if k not in PARTIAL and v["metrics"].get(key) is not None}
    return min(ok, key=lambda k: ok[k])
