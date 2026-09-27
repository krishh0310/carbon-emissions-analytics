"""Leakage, boundary and reconciliation tests. Panel-dependent tests skip if ingestion hasn't run."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.features import TRAIN_END, VAL_END, Prep, engineer, make_windows, split_of
from src.data.reference import STATE_CODES, cities_df, name_to_code, validate_codes
from src.train.evaluate import mint, mint_shrink_cov, summing_matrix

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "processed" / "india_states_panel.parquet"
GEO = ROOT / "data" / "processed" / "india_states.geojson"


def synthetic_panel(start=1995, end=2024, n_states=6, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i, code in enumerate(STATE_CODES[:n_states]):
        lvl = 10 + 20 * i
        for y in range(start, end + 1):
            lvl *= 1 + 0.04 + 0.02 * rng.standard_normal()
            rows.append({"state_code": code, "year": y, "co2_mt": lvl, "population_mn": 10 + i, "gsdp_const_cr": 1e5 * (1 + i) * 1.06 ** (y - start),
                         "gsdp_cr": 1e5, "edgar_power_mt": lvl * 0.5, "edgar_road_mt": lvl * 0.1, "avg_temp_c": 25 + rng.standard_normal(),
                         "region": ["North", "South", "East"][i % 3], "is_ut": False, "coastal": bool(i % 2), "covid_dummy": int(y in (2020, 2021))})
    return pd.DataFrame(rows)


# ---- reference / boundaries ---------------------------------------------------------------------
def test_reference_has_36_units():
    assert len(STATE_CODES) == 36 and len(set(STATE_CODES)) == 36
    assert {"IN-JK", "IN-LA", "IN-DH"} <= set(STATE_CODES)
    validate_codes(STATE_CODES)
    with pytest.raises(ValueError):
        validate_codes(STATE_CODES[:-1])


def test_name_aliases():
    assert name_to_code("Orissa") == "IN-OD"
    assert name_to_code("NCT of Delhi") == "IN-DL"
    assert name_to_code("Dadra & Nagar Haveli") == "IN-DH"
    assert name_to_code("Jammu & Kashmir") == "IN-JK"


def test_cities_have_method_and_tier():
    c = cities_df()
    assert len(c) >= 50 and set(c.state_code) <= set(STATE_CODES)
    assert c.estimation_method.notna().all() and c.confidence_tier.isin(["A", "B", "C"]).all()
    assert set(STATE_CODES) <= set(c.state_code)  # every state/UT has at least its capital


@pytest.mark.skipif(not GEO.exists(), reason="run ingestion first")
def test_geojson_exactly_36_states():
    d = json.loads(GEO.read_text())
    codes = [f["properties"]["code"] for f in d["features"]]
    validate_codes(codes)


# ---- leakage ------------------------------------------------------------------------------------
def test_split_boundaries():
    assert list(split_of([TRAIN_END, TRAIN_END + 1, VAL_END, VAL_END + 1])) == ["train", "val", "val", "test"]


def test_window_masks_are_disjoint_and_time_ordered():
    df = engineer(synthetic_panel())
    w, _ = make_windows(df, 8)
    tr, va, te = w.mask("train"), w.mask("val"), w.mask("test")
    assert not (tr & va).any() and not (tr & te).any() and not (va & te).any()
    ty = w.target_years()
    assert ty[tr].max() <= TRAIN_END < ty[va].min() and ty[va].max() <= VAL_END < ty[te].min()
    # targets are strictly after the input window
    assert (ty > w.origin[:, None]).all()


def test_scaler_fit_on_train_only():
    df = engineer(synthetic_panel())
    prep = Prep(["avg_temp_c", "co2_log"]).fit(df)
    df2 = df.copy()
    df2.loc[df2.year > TRAIN_END, ["avg_temp_c", "co2_log"]] = 1e6  # poison val/test rows
    prep2 = Prep(["avg_temp_c", "co2_log"]).fit(df2)
    pd.testing.assert_series_equal(prep.mu, prep2.mu)
    pd.testing.assert_series_equal(prep.sd, prep2.sd)


def test_future_values_do_not_change_past_features():
    """Perturbing years > t must not change any input window ending at t."""
    df = engineer(synthetic_panel())
    w1, prep = make_windows(df, 8)
    raw = synthetic_panel()
    raw.loc[raw.year > 2010, "co2_mt"] *= 3
    w2, _ = make_windows(engineer(raw), 8, prep)
    early = w1.origin <= 2010
    np.testing.assert_allclose(w1.X[early], w2.X[early], atol=1e-6)


def test_lag_features_are_strictly_past():
    df = engineer(synthetic_panel())
    g = df[df.state_code == STATE_CODES[0]].set_index("year")
    assert g.loc[2005, "co2_lag1"] == pytest.approx(g.loc[2004, "co2_mt"])
    assert g.loc[2005, "co2_rolling_mean_5y"] == pytest.approx(g.loc[2000:2004, "co2_mt"].mean())


# ---- reconciliation -----------------------------------------------------------------------------
def test_mint_is_coherent_and_keeps_coherent_forecasts():
    rng = np.random.default_rng(1)
    n = 36
    W = mint_shrink_cov(rng.standard_normal((60, n + 1)))
    states = rng.uniform(1, 300, n)
    base = np.r_[states.sum() * 1.1, states]  # incoherent national
    rec = mint(base[None], W)[0]
    assert rec[0] == pytest.approx(rec[1:].sum(), rel=1e-9)
    coherent = np.r_[states.sum(), states]
    np.testing.assert_allclose(mint(coherent[None], W)[0], coherent, rtol=1e-8)
    assert summing_matrix(n).shape == (n + 1, n)


def test_wls_adjusts_small_series_less():
    W = np.diag([1.0, 100.0, 1.0, 0.0001])  # last state: tiny error variance
    rec = mint(np.array([[120.0, 50, 40, 10]]), W)[0]
    assert rec[0] == pytest.approx(rec[1:].sum())
    assert abs(rec[3] - 10) < 1e-3 < abs(rec[1] - 50)


@pytest.mark.skipif(not (ROOT / "results" / "forecasts.parquet").exists(), reason="run training first")
def test_reconciled_forecasts_sum_to_national_and_stay_sane():
    f = pd.read_parquet(ROOT / "results" / "forecasts.parquet").dropna(subset=["p50_reconciled"])
    for (m, y), g in f.groupby(["model", "year"]):
        assert len(g) == 36, (m, y)
        # reconciled should never be wildly outside the model's own band
        assert (g.p50_reconciled <= 3 * g.p90 + 1).all(), (m, y)


@pytest.mark.skipif(not PANEL.exists(), reason="run ingestion first")
def test_real_panel_integrity():
    df = pd.read_parquet(PANEL)
    assert df.state_code.nunique() == 36
    assert not df.duplicated(["state_code", "year"]).any()
    assert (df.co2_mt.dropna() >= 0).all() and df.emissions_source.eq("EDGAR-downscaled").all()
    nat = df.groupby("year").co2_mt.sum()
    assert 400 < nat.loc[1990] < 900 and 2000 < nat.iloc[-1] < 4500  # plausible India fossil CO2 (Mt)


def test_climatetrace_subsector_mapping():
    from src.data.external import ct_sector
    assert ct_sector("electricity-generation") == "POWER"
    assert ct_sector("net-forest-land") is None and ct_sector("international-aviation") is None
    assert ct_sector("iron-and-steel") == "INDUSTRY" and ct_sector("coal-mining") == "OTHER"
    assert ct_sector("road-transportation") == "TRANSPORT" and ct_sector("rice-cultivation") == "AGRICULTURE"


def test_recent_population_anchors_drop_contradiction():
    from src.data.drivers import recent_anchors
    assert set(recent_anchors(585764, 0.551, 1263000, 657587)) == {2023}  # DNH&DD source contradiction
    assert recent_anchors(1e8, 0.2, 1.2e8, 1.21e8) == {2023: 1.2e8, 2024: 1.21e8}
