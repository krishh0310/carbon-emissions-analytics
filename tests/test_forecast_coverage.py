"""Five-year coverage and city/state reconciliation for production forecast artifacts."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.sectors import SECTORS
from src.train.city_share import allocate
from src.train.coverage import require_city_coverage, require_sector_coverage

ROOT = Path(__file__).resolve().parents[1]
FC = ROOT / "results/forecasts_sector.parquet"


def test_coverage_contract_catches_missing_horizons():
    codes = [f"IN-{i:02d}" for i in range(36)]
    rows = [{"state_code": c, "sector": s, "year": y, "p10": 1, "p50": 2, "p90": 3, "p50_reconciled": 2}
            for c in codes for s in SECTORS for y in range(2025, 2030)]
    frame = pd.DataFrame(rows)
    require_sector_coverage(frame, codes, 2024)
    with pytest.raises(ValueError, match="coverage incomplete"):
        require_sector_coverage(frame.iloc[:-1], codes, 2024)
    cities = pd.DataFrame([{"city_id": cid, "year": y, "p10": 1, "p50": 2, "p90": 3}
                           for cid in range(64) for y in range(2025, 2030)])
    require_city_coverage(cities, list(range(64)), 2024)
    with pytest.raises(ValueError, match="coverage incomplete"):
        require_city_coverage(cities.iloc[:-1], list(range(64)), 2024)


def test_served_sector_fan_encloses_reconciled_median():
    from types import SimpleNamespace

    from backend.app.v2 import _sector_point

    point = _sector_point(SimpleNamespace(year=2025, p10=-0.1, p50=0.1, p90=0.2, p50_reconciled=0.3))
    assert point == {"year": 2025, "p10": 0, "p50": 0.3, "p90": 0.3}


@pytest.mark.skipif(not FC.exists(), reason="train sector forecasts first")
def test_all_state_sector_horizons_and_city_reconciliation():
    from src.data.reference import cities_df

    fc = pd.read_parquet(FC)
    registry = json.loads((ROOT / "results/sector_registry.json").read_text())
    champion = min(registry, key=lambda k: registry[k]["metrics"]["val_reconciled_mase_h5"])
    fc = fc[fc.model == champion].copy()
    state = pd.read_parquet(ROOT / "data/processed/india_states_sector_panel.parquet")
    city = pd.read_parquet(ROOT / "data/processed/india_cities_sector_panel.parquet")
    meta = cities_df().set_index("id")
    codes = set(state.state_code.unique())
    years = set(range(int(state.year.max()) + 1, int(state.year.max()) + 6))
    expected = pd.MultiIndex.from_product([codes, SECTORS, years], names=["state_code", "sector", "year"])
    actual = pd.MultiIndex.from_frame(fc[["state_code", "sector", "year"]])
    assert len(codes) == 36
    require_sector_coverage(fc, sorted(codes), 2024)
    assert len(fc) == 36 * 7 * 5 and actual.is_unique and actual.symmetric_difference(expected).empty
    assert fc[["p10", "p50", "p90", "p50_reconciled"]].notna().all().all()
    assert (fc.p50_reconciled >= 0).all()

    cities, residual = allocate(city, state, fc, meta.state_code)
    city_expected = pd.MultiIndex.from_product([meta.index, years], names=["city_id", "year"])
    city_actual = pd.MultiIndex.from_frame(cities[["city_id", "year"]])
    require_city_coverage(cities, meta.index.tolist(), 2024)
    assert city_actual.is_unique and city_actual.symmetric_difference(city_expected).empty
    assert (cities[["p10", "p50", "p90"]] >= 0).all().all()
    grouped = cities.assign(state_code=cities.city_id.map(meta.state_code)).groupby(["state_code", "year"])[["p10", "p50", "p90"]].sum()
    fc["p50"] = fc.p50_reconciled
    fc["p10"] = fc.p10.clip(lower=0).clip(upper=fc.p50)
    fc["p90"] = fc.p90.clip(lower=fc.p50)
    total = fc.groupby(["state_code", "year"])[["p10", "p50", "p90"]].sum()
    both = grouped.add(residual.set_index(["state_code", "year"])[["p10", "p50", "p90"]], fill_value=0).reindex(total.index)
    np.testing.assert_allclose(both.to_numpy(), total.to_numpy(), rtol=0, atol=1e-6)
