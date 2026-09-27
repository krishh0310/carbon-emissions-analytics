"""Ingestion entrypoint: `python -m src.data.ingest [--refresh] [--start 1990 --end 2024]`.

Produces:
  data/processed/india_states_panel.parquet   (state_code, year) — 36 units
  data/processed/india_cities_panel.parquet   (city_id, year)
  data/processed/india_states.geojson          boundaries (simplified) for DB seeding / map
  results/tables/imputation_report.csv, data_coverage.csv
Idempotent: cached raw files are reused (sha256 in data/raw/manifest.json); outputs are overwritten.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from src.data import cache
from src.data.cache import PROCESSED, RAW, ROOT, sha256


def backfill_manifest() -> None:
    m = json.loads(cache.MANIFEST.read_text()) if cache.MANIFEST.exists() else {}
    for p in RAW.rglob("*"):
        k = str(p.relative_to(RAW))
        if p.is_file() and p.name != "manifest.json" and not p.name.endswith((".part", ".nc")) and k not in m:
            m[k] = {"url": None, "sha256": sha256(p), "fetched": None}
    cache.MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True))


def build(start: int, end: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    from src.data import drivers, edgar
    from src.data.reference import STATE_CODES, cities_df, load_boundaries, states_df

    print("[1/6] boundaries")
    bounds = load_boundaries()
    geo = bounds.copy()
    geo["geometry"] = geo.geometry.simplify(0.01, preserve_topology=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    geo.to_file(PROCESSED / "india_states.geojson", driver="GeoJSON")

    print("[2/6] EDGAR gridded CO2 -> states/cities")
    st_em, ct_em = edgar.aggregate(bounds, range(start, end + 1))

    print("[3/6] CEA power, GSDP, population")
    cea = drivers.cea_power()
    gsdp = drivers.gsdp()
    pop = drivers.population()

    print("[4/6] climate (IMD gridded, area-weighted; NASA POWER fallback)")
    # NASA POWER at each state's main city: fallback for islands outside IMD's land mask and any missing IMD year
    pts = cities_df().drop_duplicates("state_code").rename(columns={"state_code": "code"})[["code", "lat", "lon"]]
    nasa = drivers.climate(pts, start, min(end, 2024))
    try:
        from src.data import imd

        imd.prefetch(range(start, min(end, 2024) + 1))
        ic = imd.state_climate(bounds, range(start, min(end, 2024) + 1))
    except Exception as e:  # noqa: BLE001
        print(f"  [imd] unavailable, using NASA POWER only: {e}")
        ic = pd.DataFrame(columns=["state_code", "year"])
    clim = nasa.merge(ic, on=["state_code", "year"], how="left", suffixes=("_nasa", ""))
    for c in ("monsoon_rainfall_mm", "avg_temp_c", "cooling_degree_days", "heating_degree_days"):
        if c in clim:
            clim["climate_source"] = np.where(clim[c].notna(), "IMD gridded", "NASA POWER (city point)")
            clim[c] = clim[c].fillna(clim[f"{c}_nasa"])
        else:
            clim[c] = clim[f"{c}_nasa"]
            clim["climate_source"] = "NASA POWER (city point)"
    clim = clim.drop(columns=[c for c in clim if c.endswith("_nasa")])
    # drought flag recomputed on the merged series (train-period baseline, no leakage)
    base = clim[clim.year <= 2014].groupby("state_code").monsoon_rainfall_mm.mean()
    clim["drought_year"] = (clim.monsoon_rainfall_mm < 0.8 * clim.state_code.map(base)).astype(int)
    drivers.log_imputation("climate", "IMD gridded area-weighted; NASA POWER city point where IMD has no land cells",
                           int((clim.climate_source != "IMD gridded").sum()))

    print("[5/6] policy + optional RBI manual tables")
    pol = drivers.policy_frame()
    rbi = drivers.rbi_manual()
    extra = drivers.manual_extra()
    try:
        ppac = drivers.ppac_sales()
    except Exception as e:  # noqa: BLE001
        print(f"  [ppac] unavailable: {e}")
        ppac = pd.DataFrame(columns=["state_code", "year"])

    print("[6/6] merge + clean")
    grid = pd.MultiIndex.from_product([STATE_CODES, range(start, end + 1)], names=["state_code", "year"]).to_frame(index=False)
    df = grid
    for part in (st_em, cea, gsdp, pop, clim, pol, rbi, extra, ppac):
        if len(part):
            df = df.merge(part, on=["state_code", "year"], how="left")
    ref = states_df().rename(columns={"code": "state_code"})
    df = df.merge(ref[["state_code", "region", "is_ut", "coastal"]], on="state_code")
    df["emissions_source"] = "EDGAR-downscaled"
    df["emissions_uncertainty_note"] = ("EDGAR 2025 0.1° grid area-weighted to state polygons; proxy-based spatial "
                                        "allocation, typical subnational uncertainty ±20-50%.")

    # GSDP gaps (UTs without MoSPI series): population x regional median per-capita GSDP
    pc = (df.gsdp_const_cr / df.population_mn)
    reg_pc = pc.groupby([df.region, df.year]).transform("median")
    miss = df.gsdp_const_cr.isna() & df.population_mn.notna()
    df.loc[miss, "gsdp_const_cr"] = df.population_mn[miss] * reg_pc[miss]
    defl = drivers.world_bank("NY.GDP.DEFL.ZS")
    defl = defl / defl.loc[2011]
    df.loc[miss, "gsdp_cr"] = df.gsdp_const_cr[miss] * df.year[miss].map(defl)
    df.loc[miss, "gsdp_imputed"] = 1
    drivers.log_imputation("gsdp_const_cr", "population x regional median per-capita GSDP", miss.sum())

    # CEA covers FY2017+ only; generation absent before -> indicator, not zero
    gen_cols = [c for c in df.columns if c.endswith("_generation_gwh")]
    df["cea_available"] = df[gen_cols].notna().any(axis=1).astype(int)

    # missingness indicators for every numeric driver, then document remaining gaps
    num = df.select_dtypes("number").columns.difference(["year", "co2_mt"])
    for c in num:
        if df[c].isna().any() and not c.endswith(("_imputed", "_available", "_dummy")):
            df[f"{c}_missing"] = df[c].isna().astype(int)
    cov = df.drop(columns=[c for c in df.columns if c.endswith("_missing")]).notna().groupby(df.year).mean().T
    cov.to_csv(_tables() / "data_coverage.csv")
    # state x year coverage of core targets/drivers for the Data Quality heatmap
    core = ["co2_mt", "gsdp_const_cr", "population_mn", "avg_temp_c", "cea_power_co2_mt"]
    df.assign(coverage=df[core].notna().mean(axis=1))[["state_code", "year", "coverage"]].to_csv(
        _tables() / "coverage_state_year.csv", index=False)

    # cities
    cities = cities_df()
    ct = ct_em.merge(cities, left_on="city_id", right_on="id").drop(columns=["id"])
    ct = ct.merge(df[["state_code", "year", "co2_mt"]].rename(columns={"co2_mt": "state_co2_mt"}),
                  on=["state_code", "year"], how="left")
    ct["share_of_state"] = ct.co2_mt / ct.state_co2_mt
    ct["method"] = ct.estimation_method
    ct["confidence"] = ct.confidence_tier
    return df, ct


def _tables():
    p = ROOT / "results" / "tables"
    p.mkdir(parents=True, exist_ok=True)
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download sources (unchanged files detected by sha256)")
    ap.add_argument("--start", type=int, default=1990)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--no-sectors", action="store_true", help="skip the v2 state x sector panel")
    a = ap.parse_args()
    if a.refresh:
        os.environ["CARBONSCOPE_REFRESH"] = "1"
        cache.REFRESH = True
    from src.data import drivers

    states, cities = build(a.start, a.end)
    states.to_parquet(PROCESSED / "india_states_panel.parquet", index=False)
    cities.to_parquet(PROCESSED / "india_cities_panel.parquet", index=False)
    if not a.no_sectors:
        from src.data import sector_features, sectors
        from src.data.reference import load_boundaries

        print("[v2] state x sector panel (EDGAR CO2/CH4/N2O sector grids)")
        yrs = range(a.start, a.end + 1)
        fails = sectors.prefetch(yrs)
        if fails:
            print(f"  [sectors] {len(fails)} grids failed to download: {fails[:5]}")
        st_sec, ct_sec = sectors.build(load_boundaries(), yrs)
        sectors.save(st_sec, ct_sec)
        sector_features.build(states, st_sec).to_parquet(PROCESSED / "india_sector_features.parquet", index=False)
        tot = st_sec.groupby("year").co2e_mt.sum()
        print(f"  national CO2e (7 sectors) Mt: {tot.iloc[0]:.0f} -> {tot.iloc[-1]:.0f}")
    pd.DataFrame(drivers.IMPUTATIONS).to_csv(_tables() / "imputation_report.csv", index=False)
    backfill_manifest()
    nat = states.groupby("year").co2_mt.sum()
    print(f"states panel {states.shape}, cities panel {cities.shape}")
    print(f"national (sum of states) CO2 Mt: {nat.iloc[0]:.0f} ({a.start}) -> {nat.iloc[-1]:.0f} ({a.end})")
    assert states.state_code.nunique() == 36 and not states.co2_mt.isna().all()
    assert np.isfinite(states.co2_mt.dropna()).all()


if __name__ == "__main__":
    main()
