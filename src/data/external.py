"""External open emission APIs (all free, no key) + EDGAR back-history 1970–1989.

`python -m src.data.external [--history]` writes to data/processed/:
  ext_owid.parquet               Our World in Data CO2/GHG (GCP + PRIMAP), India + peers, 1850–latest
  ext_worldbank.parquet          World Bank WDI GHG indicators (AR5 CO2e), India, 1970–latest
  ext_climatetrace_sectors.parquet  Climate TRACE v6 India emissions by sector and year (satellite/asset models)
  ext_facilities.parquet         Climate TRACE top emitting facilities in India with coordinates → state
  india_states_sector_history.parquet / india_cities_sector_history.parquet
                                 EDGAR 1970–1989 (same method as the 1990+ panel) — display only, never trained on
Raw responses are cached with SHA-256 like every other source (src.data.cache.fetch).
"""
from __future__ import annotations

import json
import re
import sys

import geopandas as gpd
import pandas as pd

from src.data.cache import PROCESSED, RAW, fetch

OWID_URL = "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv"
OWID_PEERS = ["India", "China", "United States", "European Union (27)", "World", "Japan", "Russia", "Brazil",
              "Indonesia", "Pakistan", "Bangladesh", "United Kingdom"]
OWID_COLS = ["country", "year", "population", "gdp", "co2", "co2_per_capita", "coal_co2", "oil_co2", "gas_co2",
             "cement_co2", "flaring_co2", "other_industry_co2", "methane", "nitrous_oxide", "total_ghg", "total_ghg_excluding_lucf",
             "ghg_per_capita", "share_global_co2", "cumulative_co2", "co2_per_gdp", "land_use_change_co2",
             "consumption_co2", "energy_per_capita"]

WB_IND = {"EN.GHG.ALL.MT.CE.AR5": "ghg_total_mt", "EN.GHG.CO2.MT.CE.AR5": "co2_mt", "EN.GHG.CH4.MT.CE.AR5": "ch4_mt",
          "EN.GHG.N2O.MT.CE.AR5": "n2o_mt", "EN.GHG.CO2.PC.CE.AR5": "co2_per_capita_t"}

CT = "https://api.climatetrace.org/v6"
CT_MAP = {"power": "POWER", "transportation": "TRANSPORT", "manufacturing": "INDUSTRY", "buildings": "BUILDINGS",
          "agriculture": "AGRICULTURE", "waste": "WASTE", "fossil-fuel-operations": "OTHER",
          "mineral-extraction": "OTHER", "fluorinated-gases": "OTHER", "forestry-and-land-use": None}
FAC_SECTORS = ["power", "manufacturing", "fossil-fuel-operations", "mineral-extraction", "waste"]


def _json(url: str, name: str):
    return json.loads(fetch(url, RAW / "ext" / name).read_text())


def owid() -> pd.DataFrame:
    df = pd.read_csv(fetch(OWID_URL, RAW / "ext" / "owid-co2-data.csv"), usecols=lambda c: c in OWID_COLS)
    return df[df.country.isin(OWID_PEERS) & (df.year >= 1850)].reset_index(drop=True)


def worldbank() -> pd.DataFrame:
    out = None
    for ind, col in WB_IND.items():
        d = _json(f"https://api.worldbank.org/v2/country/IND/indicator/{ind}?format=json&per_page=200", f"wb_{ind}.json")
        s = pd.DataFrame([(int(r["date"]), r["value"]) for r in (d[1] if len(d) > 1 and d[1] else [])],
                         columns=["year", col]).dropna()
        out = s if out is None else out.merge(s, on="year", how="outer")
    return out.sort_values("year").reset_index(drop=True)


# Climate TRACE subsector -> CarbonScope sector (keyword rules, first match wins). LULUCF and international
# bunkers are excluded so the scope matches EDGAR's.
CT_SUB_RULES = [
    (r"^(net-|removals|forest-|shrubgrass|wetland|water-reservoirs|international-)", None),
    (r"electricity|heat-plants", "POWER"),
    (r"road|aviation|shipping|railways|other-transport|vessels", "TRANSPORT"),
    (r"residential|non-residential|other-onsite", "BUILDINGS"),
    (r"enteric|manure|rice|fertilizer|crop|agricultural", "AGRICULTURE"),
    (r"waste|wastewater", "WASTE"),
    (r"cement|steel|aluminum|chemical|petrochemical|glass|lime|pulp|textiles|food|wood|other-manufacturing|other-metals", "INDUSTRY"),
]


def ct_sector(sub: str) -> str | None:
    return next((sec for pat, sec in CT_SUB_RULES if re.search(pat, sub)), "OTHER")


def climatetrace_sectors(years=range(2021, 2026)) -> pd.DataFrame:
    """India CO2e by subsector per year (API serves 2021+ at subsector level), mapped to the 7 CarbonScope sectors."""
    rows = []
    for y in years:
        try:
            d = _json(f"{CT}/assets/emissions?countries=IND&years={y}&gas=co2e_100yr", f"ct_sub_{y}.json")
        except RuntimeError:
            continue
        for x in d.get("IND") or []:
            rows.append({"year": y, "subsector": x["Sector"], "sector": ct_sector(x["Sector"]),
                         "co2e_mt": (x["Emissions"] or 0) / 1e6, "assets": x.get("AssetCount")})
    return pd.DataFrame(rows)


def facilities(bounds: gpd.GeoDataFrame, year: int = 2024, per_sector: int = 200) -> pd.DataFrame:
    rows = []
    for s in FAC_SECTORS:
        d = _json(f"{CT}/assets?countries=IND&sectors={s}&year={year}&limit={per_sector}", f"ct_assets_{s}_{year}.json")
        for a in d.get("assets") or []:
            em = next((x for x in a.get("EmissionsSummary") or [] if x.get("Gas") == "co2e_100yr"), None)
            geom = (a.get("Centroid") or {}).get("Geometry")
            # skip basin-level aggregates ("India_OtherBasins_OtherResources") — not a locatable facility
            if not em or not geom or not em.get("EmissionsQuantity") or "_Other" in a["Name"]:
                continue
            rows.append({"id": int(a["Id"]), "name": a["Name"], "ct_sector": s, "sector": CT_MAP[s], "subsector": a.get("Sector"), "asset_type": a.get("AssetType"),
                         "owner": ((a.get("Owners") or [{}])[0]).get("CompanyName"),
                         "co2e_mt": em["EmissionsQuantity"] / 1e6, "capacity": em.get("Capacity"),
                         "capacity_units": em.get("CapacityUnits"), "lon": geom[0], "lat": geom[1], "year": year})
    df = pd.DataFrame(rows).drop_duplicates("id")
    pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=4326)
    j = gpd.sjoin(pts, bounds[["code", "geometry"]].rename(columns={"code": "state_code"}), how="left", predicate="within")
    return pd.DataFrame(j.drop(columns=["geometry", "index_right"])).drop_duplicates("id").sort_values("co2e_mt", ascending=False)


def history(bounds: gpd.GeoDataFrame, years=range(1970, 1990)) -> None:
    from src.data import sectors

    fails = sectors.prefetch(years)
    if fails:
        print(f"  [history] {len(fails)} grids unavailable: {fails[:5]}")
    st, ct = sectors.build(bounds, years)
    st.to_parquet(PROCESSED / "india_states_sector_history.parquet", index=False)
    ct.to_parquet(PROCESSED / "india_cities_sector_history.parquet", index=False)


def main() -> None:
    from src.data.reference import load_boundaries

    bounds = load_boundaries()
    for name, fn in (("owid", owid), ("worldbank", worldbank), ("climatetrace_sectors", climatetrace_sectors),
                     ("facilities", lambda: facilities(bounds))):
        try:
            df = fn()
            df.to_parquet(PROCESSED / f"ext_{name}.parquet", index=False)
            print(f"[ext] {name}: {len(df)} rows")
        except Exception as e:  # noqa: BLE001 — one dead API must not block the others
            print(f"[ext] {name} FAILED: {e}")
    if "--history" in sys.argv:
        history(bounds)
        print("[ext] EDGAR 1970–1989 history written")


if __name__ == "__main__":
    main()
