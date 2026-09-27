"""End-to-end tiny training run on a synthetic panel (CI-friendly: no downloads)."""
import numpy as np

from src.data.features import engineer, make_windows
from src.models.baselines import LightGBMPanel, Naive, RidgePanel
from src.models.deep import DeepForecaster
from src.train import evaluate as E
from tests.test_data import synthetic_panel


def test_tiny_end_to_end():
    df = engineer(synthetic_panel(n_states=5))
    w, _ = make_windows(df, 6)
    nat = E.national_drift_base(w)
    for m in (Naive(), RidgePanel(), LightGBMPanel(n_estimators=20),
              DeepForecaster("gru", hidden=8, max_epochs=3, patience=2), DeepForecaster("tft", hidden=8, max_epochs=3, patience=2)):
        m.fit(w)
        q = m.predict(w)
        assert q.shape == (len(w.y), 5, 3) and np.isfinite(q).all()
        assert (np.diff(q, axis=-1) >= -1e-9).all()  # P10 <= P50 <= P90
        rows = E.metric_rows(m.__class__.__name__, w, q)
        assert any(r["split"] == "test" and r["state_code"] == "ALL" for r in rows)
        rec, _ = E.reconcile_panel(w, E.to_level(w, q)[..., 1], nat)
        assert np.isfinite(rec).all()


def test_deep_is_deterministic():
    df = engineer(synthetic_panel(n_states=4))
    w, _ = make_windows(df, 6)
    a = DeepForecaster("lstm", hidden=8, max_epochs=2, patience=1, seed=7).fit(w).predict(w)
    b = DeepForecaster("lstm", hidden=8, max_epochs=2, patience=1, seed=7).fit(w).predict(w)
    np.testing.assert_allclose(a, b, atol=1e-6)
