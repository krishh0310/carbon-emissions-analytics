"""Continuous-learning rules: PSI, backtest score, promotion gate and consistency checks (SQLite, no training)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_api.db")
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.app import db as dbm  # noqa: E402
from backend.app import mlops  # noqa: E402


def test_psi_detects_shift_and_not_noise():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 2000)
    assert mlops.psi(a, rng.normal(0, 1, 500)) < 0.1          # same distribution
    assert mlops.psi(a, rng.normal(1.5, 1, 500)) > mlops.PSI_T  # shifted


def test_backtest_score_uses_reconciled_for_sector_level():
    m = {"test_mase_h1": 1.0, "test_mase_h3": 2.0, "test_mase_h5": 3.0,
         "test_reconciled_mase_h1": 2.0, "test_reconciled_mase_h3": 2.0, "test_reconciled_mase_h5": 2.0}
    assert mlops.backtest_score(m, "state") == pytest.approx(2.0)
    assert mlops.backtest_score(m, "state_sector") == pytest.approx(2.0)
    assert mlops.backtest_score({}, "state") is None


@pytest.fixture()
def registry_db():
    dbm.Base.metadata.create_all(dbm.engine())
    with dbm.session() as s:
        for T in (dbm.Forecast, dbm.Model):
            s.query(T).delete()
        s.commit()
    yield
    with dbm.session() as s:
        for T in (dbm.Forecast, dbm.Model):
            s.query(T).delete()
        s.commit()


def _model(s, name, status, val, bt, rows_ok=True):
    m = dbm.Model(name=name, version="t", target="co2_mt", horizon=5, level="state", status=status, val_score=val,
                  metrics={"test_mase_h1": bt, "test_mase_h3": bt, "test_mase_h5": bt})
    s.add(m)
    s.flush()
    for y in range(2025, 2030):
        s.add(dbm.Forecast(model_id=m.id, state_code="IN-MH", target="co2_mt", year=y, p10=1.0, p50=2.0 if rows_ok else -1.0, p90=3.0))
    return m


def test_challenger_needs_2pct_and_consistency(registry_db):
    with dbm.session() as s:
        _model(s, "gru", "champion", 2.0, 3.00)
        _model(s, "tft", "candidate", 1.9, 2.99)     # only 0.3 % better -> not promoted
        _model(s, "tcn", "candidate", 1.95, 2.50, rows_ok=False)  # much better but negative forecasts -> rejected
        s.commit()
    notes = mlops.promotion_check()
    with dbm.session() as s:
        st = {m.name: m.status for m in s.query(dbm.Model)}
    assert st == {"gru": "champion", "tft": "candidate", "tcn": "candidate"}, notes
    assert any("failed consistency" in n for n in notes)
    with dbm.session() as s:
        _model(s, "lstm", "candidate", 1.99, 2.80)   # 6.7 % better and consistent -> challenger in shadow
        s.commit()
    mlops.promotion_check()
    with dbm.session() as s:
        ch = s.query(dbm.Model).filter_by(name="lstm").one()
        assert ch.status == "challenger" and ch.shadow_until is not None
