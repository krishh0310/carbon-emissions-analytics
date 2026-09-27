"""EDGAR 2025 gridded CO2 (0.1°, tonnes/cell/yr) -> state/UT and city totals ("EDGAR-downscaled estimates").

State totals use area-weighted cell/polygon overlay (not centroid-in-polygon) so small UTs and coastal
cells are not dropped. City totals sum cells whose centre lies within the city buffer.
"""
from __future__ import annotations

import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box

from src.data.cache import PROCESSED, RAW, fetch
from src.data.reference import cities_df

RELEASE = "EDGAR_2025_GHG"
BASE = f"https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/EDGAR/datasets/{RELEASE}/CO2"
# fallback mirror: previous release (covers to 2023)
BASE_FALLBACK = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/EDGAR/datasets/EDGAR_2024_GHG/CO2"
# target + sector drivers. ENE=power, IND=manufacturing combustion, TRO=road transport,
# NMM=non-metallic minerals (cement), RCO=residential/commercial buildings
SECTORS = {"TOTALS": "co2_mt", "ENE": "edgar_power_mt", "IND": "edgar_industry_mt",
           "TRO": "edgar_road_mt", "NMM": "edgar_cement_mt", "RCO": "edgar_buildings_mt"}
LAT, LON = (6.0, 37.5), (68.0, 98.0)  # India bbox
RES = 0.1


def zip_path(sector: str, year: int, gas: str = "CO2"):
    """Download (cached) one EDGAR grid zip. Thread-safe (no HDF5 access)."""
    name = f"{RELEASE}_{gas}_{year}_{sector}_emi_nc.zip"
    base, fb = BASE.replace("/CO2", f"/{gas}"), BASE_FALLBACK.replace("/CO2", f"/{gas}")
    urls = [f"{base}/{sector}/emi_nc/{name}", f"{fb}/{sector}/emi_nc/{name.replace(RELEASE, 'EDGAR_2024_GHG')}"]
    return fetch(urls, RAW / "edgar" / (sector if gas == "CO2" else f"{gas}/{sector}") / name)


def _nc(sector: str, year: int, gas: str = "CO2"):
    """Download (cached) + read one EDGAR grid, cropped to India. Returns (array tonnes/cell, DataArray coords).
    NOT thread-safe (HDF5) — call from one thread; use zip_path() for parallel downloads."""
    z = zip_path(sector, year, gas)
    # read the .nc straight from the zip in memory: extracted global grids are 26 MB each (x ~2,000 files)
    import netCDF4

    with zipfile.ZipFile(z) as zf:
        member = next(n for n in zf.namelist() if n.endswith(".nc"))
        buf = zf.read(member)
    with xr.open_dataset(xr.backends.NetCDF4DataStore(netCDF4.Dataset("mem.nc", memory=buf))) as ds:
        da = ds["emissions"].sel(lat=slice(*LAT), lon=slice(*LON)).load()
    return da.values.astype("float64"), da


def state_weights(bounds: gpd.GeoDataFrame, lats: np.ndarray, lons: np.ndarray) -> pd.DataFrame:
    """(iy, ix, code, frac) — fraction of each grid cell's area inside each state. Cached."""
    path = PROCESSED / "edgar_state_weights.parquet"
    if path.exists():
        return pd.read_parquet(path)
    h = RES / 2
    iy, ix = np.meshgrid(np.arange(len(lats)), np.arange(len(lons)), indexing="ij")
    cells = gpd.GeoDataFrame(
        {"iy": iy.ravel(), "ix": ix.ravel()},
        geometry=[box(lons[j] - h, lats[i] - h, lons[j] + h, lats[i] + h) for i, j in zip(iy.ravel(), ix.ravel(), strict=True)],
        crs=4326,
    )
    cells = cells[cells.intersects(bounds.union_all())]
    # equal-area CRS for fractions
    ea = "EPSG:6933"
    cells_ea = cells.to_crs(ea)
    cells_ea["cell_area"] = cells_ea.area
    ov = gpd.overlay(cells_ea, bounds[["code", "geometry"]].to_crs(ea), how="intersection", keep_geom_type=True)
    ov["frac"] = ov.area / ov["cell_area"]
    w = ov.groupby(["iy", "ix", "code"], as_index=False)["frac"].sum()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    w.to_parquet(path)
    return w


def city_weights(lats: np.ndarray, lons: np.ndarray) -> pd.DataFrame:
    """(iy, ix, city_id) for cells whose centre is within the city buffer (haversine)."""
    rows = []
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    for c in cities_df().itertuples():
        p1, p2 = np.radians(c.lat), np.radians(la)
        d = 2 * 6371 * np.arcsin(np.sqrt(np.sin((p2 - p1) / 2) ** 2 +
                                         np.cos(p1) * np.cos(p2) * np.sin(np.radians(lo - c.lon) / 2) ** 2))
        iy, ix = np.nonzero(d <= c.buffer_km)
        if len(iy) == 0:  # tiny islands: nearest cell
            iy, ix = np.unravel_index(np.argmin(d), d.shape)
            iy, ix = np.atleast_1d(iy), np.atleast_1d(ix)
        rows.append(pd.DataFrame({"iy": iy, "ix": ix, "city_id": c.id}))
    return pd.concat(rows)


def aggregate(bounds: gpd.GeoDataFrame, years: range) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (state_year_sectors, city_year_sectors) in MtCO2."""
    st_rows, ct_rows = [], []
    sw = cw = None
    for sector, col in SECTORS.items():
        for y in years:
            try:
                arr, da = _nc(sector, y)
            except RuntimeError as e:
                print(f"  [edgar] skip {sector} {y}: {e}")
                continue
            if sw is None:
                sw = state_weights(bounds, da.lat.values, da.lon.values)
                cw = city_weights(da.lat.values, da.lon.values)
            vals = arr[sw.iy.values, sw.ix.values] * sw.frac.values
            s = pd.Series(vals).groupby(sw.code.values).sum() / 1e6
            st_rows += [{"state_code": k, "year": y, "sector": col, "value": v} for k, v in s.items()]
            c = pd.Series(arr[cw.iy.values, cw.ix.values]).groupby(cw.city_id.values).sum() / 1e6
            ct_rows += [{"city_id": k, "year": y, "sector": col, "value": v} for k, v in c.items()]
        print(f"  [edgar] {sector} done")
    st = pd.DataFrame(st_rows).pivot_table(index=["state_code", "year"], columns="sector", values="value").reset_index()
    ct = pd.DataFrame(ct_rows).pivot_table(index=["city_id", "year"], columns="sector", values="value").reset_index()
    st.columns.name = ct.columns.name = None
    return st, ct
