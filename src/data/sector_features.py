"""State × sector feature panel: `python -m src.data.sector_features` (after `src.data.sectors` grids are cached).

Output data/processed/india_sector_features.parquet — one row per (state_code, sector, year) with:
  target        co2e_mt (AR6 GWP-100)
  own history   sec_log, sec_lag1/3/5, sec_roll5, sec_growth_yoy, sec_share_lag1   (strictly past, shift >= 1)
  state total   tot_lag1, tot_growth_lag1                                           (strictly past)
  shared        GSDP, population, urban %, climate (CDD/HDD/rain/drought), policy, lockdown   (from v1 state panel)
  sector        per-sector drivers (see SECTOR_DRIVERS); present for every row so the global model can learn
                sector interactions through the sector embedding; absent sources -> NaN + *_missing indicator.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.cache import PROCESSED
from src.data.features import KNOWN_FUTURE, engineer, load_panel
from src.data.sectors import CONFIDENCE, SECTORS

TARGET = "co2e_mt"
SHARED = ["gsdp_const_cr", "gsdp_growth_pct", "gsdp_imputed", "population_mn", "urban_population_pct",
          "population_density", "avg_temp_c", "cooling_degree_days", "heating_degree_days", "monsoon_rainfall_mm",
          "drought_year", "lockdown_stringency", "pat_scheme_dummy", "nsm_phase", *KNOWN_FUTURE]
SECTOR_DRIVERS = {
    "POWER": ["coal_generation_gwh", "gas_generation_gwh", "hydro_generation_gwh", "nuclear_generation_gwh",
              "renewable_share_pct", "grid_emission_factor", "per_capita_electricity_kwh", "tnd_losses_pct",
              "installed_capacity_mw", "renewable_capacity_mw"],
    "TRANSPORT": ["urban_population_mn", "vehicles_total", "vehicles_2w", "vehicles_car", "vehicles_goods",
                  "diesel_sales_kt", "petrol_sales_kt", "rail_freight_mt", "air_passengers_mn", "highway_length_km"],
    "INDUSTRY": ["industry_share_pct", "manufacturing_share_pct", "construction_share_pct"],
    "BUILDINGS": ["households_mn", "lpg_households_pct", "nightlights_radiance"],
    "AGRICULTURE": ["fertiliser_consumption_kt", "rice_production_kt", "wheat_production_kt", "gross_sown_area_kha",
                    "cattle_mn", "buffalo_mn"],
    "WASTE": ["msw_tpd"],
    "OTHER": ["pol_sales_kt"],
}
HISTORY = ["sec_log", "sec_lag1", "sec_lag3", "sec_lag5", "sec_roll5", "sec_growth_yoy", "sec_share_lag1",
           "tot_lag1", "tot_growth_lag1"]
LOG1P = ["pol_sales_kt", "diesel_sales_kt", "petrol_sales_kt", "sec_lag1", "sec_lag3", "sec_lag5", "sec_roll5", "tot_lag1", "gsdp_const_cr", "population_mn",
         "population_density", "urban_population_mn", "coal_generation_gwh", "gas_generation_gwh", "hydro_generation_gwh",
         "nuclear_generation_gwh", "vehicles_total", "vehicles_2w", "vehicles_car", "vehicles_goods", "msw_tpd",
         "fertiliser_consumption_kt", "rice_production_kt", "wheat_production_kt"]


def build(state_df: pd.DataFrame | None = None, sector_df: pd.DataFrame | None = None) -> pd.DataFrame:
    st = engineer(state_df if state_df is not None else load_panel())
    sec = sector_df if sector_df is not None else pd.read_parquet(PROCESSED / "india_states_sector_panel.parquet")
    st["urban_population_mn"] = st.population_mn * st.urban_population_pct / 100
    drivers = [c for cols in SECTOR_DRIVERS.values() for c in cols]
    for c in drivers + SHARED:
        if c not in st:
            st[c] = np.nan
    keep = ["state_code", "year", "region", "is_ut", "coastal", "income_group", *dict.fromkeys(SHARED + drivers)]
    df = sec.merge(st[keep], on=["state_code", "year"], how="left")
    df = df.sort_values(["state_code", "sector", "year"]).reset_index(drop=True)

    g = df.groupby(["state_code", "sector"])[TARGET]
    df["sec_log"] = np.log1p(df[TARGET].clip(lower=0))
    df["sec_lag1"], df["sec_lag3"], df["sec_lag5"] = g.shift(1), g.shift(3), g.shift(5)
    df["sec_roll5"] = g.transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df["sec_growth_yoy"] = g.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).clip(-1, 5) * 100
    tot = df.groupby(["state_code", "year"])[TARGET].transform("sum")
    df["state_total_co2e_mt"] = tot  # not a feature (contemporaneous) — used for reconciliation/aggregates only
    df["sec_share_lag1"] = (df[TARGET] / tot.replace(0, np.nan)).groupby([df.state_code, df.sector]).shift(1)
    t = df.drop_duplicates(["state_code", "year"])[["state_code", "year", "state_total_co2e_mt"]].sort_values(["state_code", "year"])
    t["tot_lag1"] = t.groupby("state_code").state_total_co2e_mt.shift(1)
    t["tot_growth_lag1"] = t.groupby("state_code").state_total_co2e_mt.pct_change(fill_method=None).shift(1) * 100
    df = df.merge(t[["state_code", "year", "tot_lag1", "tot_growth_lag1"]], on=["state_code", "year"], how="left")
    df["confidence"] = df.sector.map(CONFIDENCE)
    for c in drivers:
        if df[c].isna().any() and df[c].notna().any():
            df[f"{c}_missing"] = df[c].isna().astype(int)
    assert set(df.sector) <= set(SECTORS)
    return df


def feature_columns(df: pd.DataFrame, train_end: int = 2014) -> list[str]:
    """Features usable for training: present and non-constant in train years (others stay in the parquet)."""
    cand = HISTORY + SHARED + [c for cols in SECTOR_DRIVERS.values() for c in cols] + [c for c in df if c.endswith("_missing")]
    tr = df[df.year <= train_end]
    return [c for c in dict.fromkeys(cand) if c in df and tr[c].notna().any() and tr[c].nunique() > 1]


def state_total_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Direct state-total CO2e panel (E10 baseline + aggregate base forecasts for reconciliation)."""
    first = df[df.sector == SECTORS[0]].copy()
    first["sector"] = "TOTAL"
    first[TARGET] = first["state_total_co2e_mt"]
    g = first.groupby("state_code")[TARGET]
    first["sec_log"] = np.log1p(first[TARGET])
    first["sec_lag1"], first["sec_lag3"], first["sec_lag5"] = g.shift(1), g.shift(3), g.shift(5)
    first["sec_roll5"] = g.transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    first["sec_growth_yoy"] = g.pct_change(fill_method=None) * 100
    first["sec_share_lag1"] = 1.0
    return first


if __name__ == "__main__":
    out = build()
    out.to_parquet(PROCESSED / "india_sector_features.parquet", index=False)
    print(out.shape, "features usable in training:", len(feature_columns(out)))
