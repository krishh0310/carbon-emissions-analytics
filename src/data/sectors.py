"""State × sector × year emissions (MtCO2e, AR6 GWP-100) from EDGAR 2025 CO2/CH4/N2O sector grids.

Taxonomy (fixed, 7 sectors) and EDGAR sub-sector mapping:
  POWER        ENE (power & heat generation)
  TRANSPORT    TRO (road), TNR_Other (rail, inland navigation, off-road), TNR_Aviation_LTO (airport cycles),
               TNR_Ship (domestic/coastal shipping; mostly offshore so only coastal cells fall inside states)
  INDUSTRY     IND (combustion in manufacturing), NMM (cement/minerals), IRO (iron & steel), CHE (chemicals),
               NFE (non-ferrous), NEU (non-energy use), PRU_SOL (solvents/products), REF_TRF (refineries)
  BUILDINGS    RCO (residential + commercial)
  AGRICULTURE  ENF (enteric fermentation), MNM (manure), AGS (rice cultivation, soils, liming/urea),
               AWB (agricultural waste burning)
  WASTE        SWD_LDF (landfills), SWD_INC (incineration/open burning), WWT (wastewater)
  OTHER        residual: CO2 TOTALS − Σ assigned CO2 sub-sectors, plus CH4/N2O from fuel production/fugitives
               (PRO_*), indirect N2O (IDE, N2O). By construction Σ sectors == state total.

GWP-100 (IPCC AR6 WG1 Table 7.15): CO2 = 1; CH4 fossil = 29.8, CH4 non-fossil = 27.0; N2O = 273.
Non-fossil CH4 factor applies to AGRICULTURE and WASTE; fossil factor everywhere else.
Aviation cruise/climb (CRS/CDS/SPS) is excluded: it is allocated to airspace, not to states.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import pandas as pd

from src.data import edgar
from src.data.cache import PROCESSED

SECTORS = ["POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER"]
GWP = {"CO2": 1.0, "CH4_fossil": 29.8, "CH4_bio": 27.0, "N2O": 273.0}

MAP: dict[str, dict[str, list[str]]] = {
    "POWER": {"CO2": ["ENE"], "CH4": ["ENE"], "N2O": ["ENE"]},
    "TRANSPORT": {"CO2": ["TRO", "TNR_Other", "TNR_Aviation_LTO", "TNR_Ship"], "CH4": ["TRO"], "N2O": ["TRO"]},
    "INDUSTRY": {"CO2": ["IND", "NMM", "IRO", "CHE", "NFE", "NEU", "PRU_SOL", "REF_TRF"],
                 "CH4": ["IND", "IRO", "CHE", "REF_TRF"], "N2O": ["IND", "CHE", "PRU_SOL", "REF_TRF"]},
    "BUILDINGS": {"CO2": ["RCO"], "CH4": ["RCO"], "N2O": ["RCO"]},
    "AGRICULTURE": {"CO2": ["AGS"], "CH4": ["ENF", "MNM", "AGS", "AWB"], "N2O": ["AGS", "MNM", "AWB"]},
    "WASTE": {"CO2": ["SWD_INC"], "CH4": ["SWD_LDF", "SWD_INC", "WWT"], "N2O": ["SWD_LDF", "SWD_INC", "WWT"]},
    # explicit OTHER non-CO2 sources; OTHER CO2 is the residual vs TOTALS
    "OTHER": {"CO2": [], "CH4": ["PRO_COAL", "PRO_GAS", "PRO_OIL", "PRO_FFF"], "N2O": ["PRO_FFF", "IDE", "N2O"]},
}
BIO = {"AGRICULTURE", "WASTE"}
CONFIDENCE = {  # EDGAR sub-national allocation quality by sector (documented judgement, see README)
    "POWER": "B", "INDUSTRY": "B", "TRANSPORT": "B", "BUILDINGS": "C", "AGRICULTURE": "C", "WASTE": "C", "OTHER": "C",
}


def grid_jobs(years) -> list[tuple[str, str, int]]:
    jobs = {(gas, sec, y) for s in MAP.values() for gas, secs in s.items() for sec in secs for y in years}
    jobs |= {("CO2", "TOTALS", y) for y in years}
    return sorted(jobs)


def prefetch(years, workers: int = 16) -> list:
    """Parallel download of every grid needed (cached). Returns failures (gas, sector, year, error)."""
    def one(j):
        try:
            edgar.zip_path(j[1], j[2], j[0])
            return None
        except Exception as e:  # noqa: BLE001
            return (*j, str(e)[:120])
    with ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(one, grid_jobs(years)) if r]


def build(bounds: gpd.GeoDataFrame, years) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (state_sector: state_code, sector, year, co2e_mt, co2_mt, ch4_co2e_mt, n2o_co2e_mt, source, method,
    confidence) and (city_sector: city_id, sector, year, co2e_mt). Missing grids are logged and treated as 0."""
    sw = cw = None
    st_rows, ct_rows, missing = [], [], []

    def agg(arr):
        s = pd.Series(arr[sw.iy.values, sw.ix.values] * sw.frac.values).groupby(sw.code.values).sum() / 1e6
        c = pd.Series(arr[cw.iy.values, cw.ix.values]).groupby(cw.city_id.values).sum() / 1e6
        return s, c

    for y in years:
        acc_s: dict[tuple[str, str], pd.Series] = {}
        acc_c: dict[tuple[str, str], pd.Series] = {}
        tot_s = tot_c = None
        for gas, sec in sorted({(g, x) for s in MAP.values() for g, xs in s.items() for x in xs} | {("CO2", "TOTALS")}):
            try:
                arr, da = edgar._nc(sec, y, gas)
            except RuntimeError:
                missing.append((gas, sec, y))
                continue
            if sw is None:
                sw = edgar.state_weights(bounds, da.lat.values, da.lon.values)
                cw = edgar.city_weights(da.lat.values, da.lon.values)
            s, c = agg(arr)
            if sec == "TOTALS":
                tot_s, tot_c = s, c
                continue
            for sector, spec in MAP.items():
                if sec in spec.get(gas, []):
                    f = GWP["CO2"] if gas == "CO2" else GWP["N2O"] if gas == "N2O" else \
                        GWP["CH4_bio"] if sector in BIO else GWP["CH4_fossil"]
                    for ser, acc in ((s, acc_s), (c, acc_c)):
                        acc[(sector, gas)] = acc.get((sector, gas), 0) + ser * f
        # OTHER CO2 = TOTALS − Σ assigned CO2 (can be slightly <0 from grid rounding -> clipped, logged)
        for tot, acc, rows, idcol in ((tot_s, acc_s, st_rows, "state_code"), (tot_c, acc_c, ct_rows, "city_id")):
            assigned = sum(v for (sec, gas), v in acc.items() if gas == "CO2")
            acc[("OTHER", "CO2")] = (tot - assigned).clip(lower=0)
            for sector in SECTORS:
                parts = {g: acc.get((sector, g)) for g in ("CO2", "CH4", "N2O")}
                idx = tot.index
                vals = {g: (p.reindex(idx).fillna(0) if isinstance(p, pd.Series) else pd.Series(0.0, idx)) for g, p in parts.items()}
                for k in idx:
                    rows.append({idcol: k, "sector": sector, "year": y, "co2_mt": vals["CO2"][k],
                                 "ch4_co2e_mt": vals["CH4"][k], "n2o_co2e_mt": vals["N2O"][k],
                                 "co2e_mt": vals["CO2"][k] + vals["CH4"][k] + vals["N2O"][k]})
        print(f"  [sectors] {y} done")
    st = pd.DataFrame(st_rows)
    st["source"] = "EDGAR-2025-downscaled"
    st["method"] = "EDGAR 0.1° sector grids, area-weighted to state polygons; CO2e with AR6 GWP-100"
    st["confidence"] = st.sector.map(CONFIDENCE)
    if missing:
        print(f"  [sectors] {len(missing)} grids unavailable (treated as 0): {missing[:5]} ...")
    st.attrs["missing"] = missing
    return st, pd.DataFrame(ct_rows)


def save(st: pd.DataFrame, ct: pd.DataFrame) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    st.to_parquet(PROCESSED / "india_states_sector_panel.parquet", index=False)
    ct.to_parquet(PROCESSED / "india_cities_sector_panel.parquet", index=False)


if __name__ == "__main__":
    import sys

    yrs = range(1990, 2025)
    if "--prefetch" in sys.argv:
        fails = prefetch(yrs)
        print("prefetch failures:", len(fails), fails[:10])
