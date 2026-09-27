"""v2 state x sector: taxonomy, leakage, and reconciliation consistency (synthetic data; no downloads)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.features import TRAIN_END, VAL_END, make_windows
from src.data.sector_features import LOG1P, build, feature_columns
from src.data.sectors import GWP, MAP, SECTORS
from tests.test_data import synthetic_panel

ROOT = Path(__file__).resolve().parents[1]
SEC_PANEL = ROOT / "data" / "processed" / "india_states_sector_panel.parquet"


def synthetic_sector_panel(n_states=4, start=1995, end=2024, seed=0) -> tuple[pd.DataFrame, pd.DataFrame]:
    st = synthetic_panel(start, end, n_states, seed)
    rng = np.random.default_rng(seed)
    rows = []
    for code in st.state_code.unique():
        for k, sec in enumerate(SECTORS):
            v = 1 + 3 * k
            for y in range(start, end + 1):
                v *= 1 + 0.03 + 0.03 * rng.standard_normal()
                rows.append({"state_code": code, "sector": sec, "year": y, "co2e_mt": max(v, 0), "source": "synthetic",
                             "method": "synthetic", "confidence": "C"})
    return st, pd.DataFrame(rows)


def test_taxonomy_and_gwp():
    assert SECTORS == ["POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER"]
    assert set(MAP) == set(SECTORS)
    assert GWP == {"CO2": 1.0, "CH4_fossil": 29.8, "CH4_bio": 27.0, "N2O": 273.0}  # AR6 WG1 Table 7.15
    # every EDGAR sub-sector is assigned to exactly one sector per gas (no double counting)
    for gas in ("CO2", "CH4", "N2O"):
        subs = [s for spec in MAP.values() for s in spec.get(gas, [])]
        assert len(subs) == len(set(subs)), gas


def test_sector_features_strictly_past():
    st, sec = synthetic_sector_panel()
    df = build(st, sec)
    g = df[(df.state_code == df.state_code.iloc[0]) & (df.sector == "POWER")].set_index("year")
    assert g.loc[2005, "sec_lag1"] == pytest.approx(g.loc[2004, "co2e_mt"])
    assert g.loc[2005, "sec_roll5"] == pytest.approx(g.loc[2000:2004, "co2e_mt"].mean())
    tot = df[(df.state_code == df.state_code.iloc[0])].groupby("year").co2e_mt.sum()
    assert g.loc[2005, "tot_lag1"] == pytest.approx(tot.loc[2004])
    share = df[(df.state_code == df.state_code.iloc[0]) & (df.year == 2004) & (df.sector == "POWER")].co2e_mt.iloc[0] / tot.loc[2004]
    assert g.loc[2005, "sec_share_lag1"] == pytest.approx(share)
    assert "state_total_co2e_mt" not in feature_columns(df)  # contemporaneous total must never be an input


def test_sector_windows_split_and_no_future_leak():
    st, sec = synthetic_sector_panel()
    df = build(st, sec)
    feats = feature_columns(df)
    w, prep = make_windows(df, 6, target="co2e_mt", features=feats, sectors=tuple(SECTORS), log_cols=LOG1P)
    assert len(w.sectors) == 7 and set(np.unique(w.sector)) == set(range(7))
    ty = w.target_years()
    tr, va, te = w.mask("train"), w.mask("val"), w.mask("test")
    assert ty[tr].max() <= TRAIN_END < ty[va].min() and ty[va].max() <= VAL_END < ty[te].min()
    # perturbing the future must not change inputs of earlier origins
    sec2 = sec.copy()
    sec2.loc[sec2.year > 2010, "co2e_mt"] *= 5
    w2, _ = make_windows(build(st, sec2), 6, prep, target="co2e_mt", features=feats, sectors=tuple(SECTORS), log_cols=LOG1P)
    early = w.origin <= 2010
    np.testing.assert_allclose(w.X[early], w2.X[early], atol=1e-6)


@pytest.mark.skipif(not SEC_PANEL.exists(), reason="run sector ingestion first")
def test_real_sector_panel_reconciles_to_state_total():
    d = pd.read_parquet(SEC_PANEL)
    assert set(d.sector) == set(SECTORS) and d.state_code.nunique() == 36
    assert not d.duplicated(["state_code", "sector", "year"]).any()
    assert (d.co2e_mt >= -1e-9).all() and d.source.notna().all() and d.confidence.notna().all()
    st = pd.read_parquet(ROOT / "data" / "processed" / "india_states_panel.parquet")
    co2 = d.groupby(["state_code", "year"]).co2_mt.sum()
    ref = st.set_index(["state_code", "year"]).co2_mt.reindex(co2.index)
    np.testing.assert_allclose(co2.to_numpy(), ref.to_numpy(), rtol=1e-6, atol=1e-6)  # CO2 part == v1 fossil CO2


def test_two_level_mint_is_coherent():
    from src.train.evaluate import mint_bottom, summing_matrix_2level

    rng = np.random.default_rng(3)
    S_, K = 5, 7
    S = summing_matrix_2level(S_, K)
    cells = rng.uniform(0.1, 50, S_ * K)
    base = S @ cells * rng.uniform(0.9, 1.1, S.shape[0])  # incoherent at every level
    rec = mint_bottom(base[None], S, rng.uniform(0.5, 2, S.shape[0]))[0]
    full = S @ rec
    assert full[0] == pytest.approx(rec.sum())
    np.testing.assert_allclose(full[1:1 + S_], rec.reshape(S_, K).sum(1))
    np.testing.assert_allclose(full[1 + S_:1 + S_ + K], rec.reshape(S_, K).sum(0))
    np.testing.assert_allclose(mint_bottom((S @ cells)[None], S, np.ones(S.shape[0]))[0], cells, rtol=1e-8)  # coherent in -> unchanged


# ---- E13: counterfactual sanity (runs in CI) ---------------------------------------------------------
def _toy_fc():
    rows = []
    for c in ("IN-AA", "IN-BB"):
        for sec in SECTORS:
            for y in range(2025, 2030):
                rows.append({"state_code": c, "sector": sec, "year": y, "p10": 8.0, "p50": 10.0, "p90": 12.0})
    return pd.DataFrame(rows)


def _struct():
    return pd.DataFrame({"fossil_share": [0.8, 0.4], "grid_ef": [0.9, 0.5], "road_share": [0.9, 0.8]}, index=["IN-AA", "IN-BB"])


def test_e13_more_renewables_never_increase_power():
    from src.scenarios import Params, apply

    prev = None
    for pp in (0, 5, 10, 20, 40):
        out = apply(_toy_fc(), Params(renewable_pp=pp, ev_share_pct=20), _struct())
        power = out[out.sector == "POWER"].scenario_p50.sum()
        assert prev is None or power <= prev + 1e-9
        prev = power
    out = apply(_toy_fc(), Params(renewable_pp=40), _struct())
    assert (out.scenario_p50 >= 0).all()  # capped at the fossil share, never negative


def test_e13_other_levers_monotone_and_bau_identity():
    from src.scenarios import Params, apply

    bau = apply(_toy_fc(), Params(), _struct())
    np.testing.assert_allclose(bau.scenario_p50, bau.p50)
    ev = apply(_toy_fc(), Params(ev_share_pct=30), _struct())
    assert ev[ev.sector == "TRANSPORT"].scenario_p50.sum() < bau[bau.sector == "TRANSPORT"].p50.sum()
    assert ev[ev.sector == "POWER"].scenario_p50.sum() > bau[bau.sector == "POWER"].p50.sum()  # EV load hits the grid
    hi = apply(_toy_fc(), Params(industrial_growth_pp=3), _struct())
    assert hi[hi.sector == "INDUSTRY"].scenario_p50.sum() > bau[bau.sector == "INDUSTRY"].p50.sum()
    assert (ev.scenario_p10 <= ev.scenario_p50).all() and (ev.scenario_p50 <= ev.scenario_p90).all()


def test_scenario_bounds_validated():
    from src.scenarios import Params

    with pytest.raises(ValueError):
        Params(renewable_pp=90).validate()
    with pytest.raises(ValueError):
        Params(industrial_growth_pp=float("nan")).validate()
