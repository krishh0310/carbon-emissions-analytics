"""IMD gridded climate (India Meteorological Department, Pune) → state-year climate, area-weighted.

- Rainfall: 0.25° daily (Pai et al. 2014), 135 lon (66.5–100.0 E) × 129 lat (6.5–38.5 N), float32, missing = -999.
- Tmax/Tmin: 1° daily (Srivastava et al. 2009), 31 lon (67.5–97.5 E) × 31 lat (7.5–37.5 N), float32, missing = 99.9.
Outputs per state-year: monsoon_rainfall_mm (JJAS total), annual_rainfall_mm, avg_temp_c, cooling_degree_days,
heating_degree_days (daily base 18 °C). Cells are weighted by their area share inside each state polygon.
Islands outside IMD's land mask (A&N, Lakshadweep) fall back to NASA POWER in ingest.
"""
from __future__ import annotations

import calendar
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from src.data.cache import PROCESSED, RAW, fetch

BASE = "https://imdpune.gov.in/cmpg/Griddata/"
RAIN = {"url": BASE + "rainfall.php", "field": "rain", "lon0": 66.5, "lat0": 6.5, "nx": 135, "ny": 129, "res": 0.25, "miss": -999.0}
TMAX = {"url": BASE + "maxtemp.php", "field": "maxtemp", "lon0": 67.5, "lat0": 7.5, "nx": 31, "ny": 31, "res": 1.0, "miss": 99.9}
TMIN = {"url": BASE + "mintemp.php", "field": "mintemp", "lon0": 67.5, "lat0": 7.5, "nx": 31, "ny": 31, "res": 1.0, "miss": 99.9}


def _path(g: dict, year: int):
    return RAW / "imd" / g["field"] / f"{g['field']}_{year}.bin"


def download(g: dict, year: int):
    return fetch(g["url"], _path(g, year), data={g["field"]: str(year)})


def prefetch(years, workers: int = 4) -> list:
    jobs = [(g, y) for y in years for g in (RAIN, TMAX, TMIN)]
    def one(j):
        try:
            download(*j)
        except Exception as e:  # noqa: BLE001
            return (j[0]["field"], j[1], str(e)[:100])
    with ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(one, jobs) if r]


def read(g: dict, year: int) -> np.ndarray:
    """(days, ny, nx) float array with NaN for missing."""
    a = np.fromfile(download(g, year), dtype="<f4")
    days = 366 if calendar.isleap(year) else 365
    a = a[: days * g["ny"] * g["nx"]].reshape(days, g["ny"], g["nx"]).astype("float64")
    a[np.isclose(a, g["miss"]) | (a < -900)] = np.nan
    return a


def weights(bounds: gpd.GeoDataFrame, g: dict) -> pd.DataFrame:
    path = PROCESSED / f"imd_weights_{g['field'] if g is RAIN else 'temp'}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    h = g["res"] / 2
    cells = gpd.GeoDataFrame(
        [{"iy": i, "ix": j} for i in range(g["ny"]) for j in range(g["nx"])],
        geometry=[box(g["lon0"] + j * g["res"] - h, g["lat0"] + i * g["res"] - h, g["lon0"] + j * g["res"] + h, g["lat0"] + i * g["res"] + h)
                  for i in range(g["ny"]) for j in range(g["nx"])], crs=4326).to_crs("EPSG:6933")
    ov = gpd.overlay(cells, bounds[["code", "geometry"]].to_crs("EPSG:6933"), how="intersection", keep_geom_type=True)
    ov["w"] = ov.area
    w = ov.groupby(["iy", "ix", "code"], as_index=False).w.sum()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    w.to_parquet(path)
    return w


def _state_mean(field: np.ndarray, w: pd.DataFrame) -> pd.Series:
    """Area-weighted mean over valid cells per state for a 2-D field."""
    v = field[w.iy.values, w.ix.values]
    ok = np.isfinite(v)
    df = pd.DataFrame({"code": w.code.values[ok], "vw": v[ok] * w.w.values[ok], "w": w.w.values[ok]})
    g = df.groupby("code")[["vw", "w"]].sum()
    return g.vw / g.w


def state_climate(bounds: gpd.GeoDataFrame, years) -> pd.DataFrame:
    wr, wt = weights(bounds, RAIN), weights(bounds, TMAX)
    rows = []
    for y in years:
        try:
            r = read(RAIN, y)
            tmean = (read(TMAX, y) + read(TMIN, y)) / 2
        except Exception as e:  # noqa: BLE001
            print(f"  [imd] {y} unavailable: {e}")
            continue
        doy = pd.date_range(f"{y}-01-01", periods=r.shape[0])
        jjas = (doy.month >= 6) & (doy.month <= 9)
        with np.errstate(invalid="ignore"):
            mons, ann = np.nansum(r[jjas], 0), np.nansum(r, 0)
            valid = np.isfinite(r).any(0)
            mons[~valid], ann[~valid] = np.nan, np.nan
            cdd = np.nansum(np.clip(tmean - 18, 0, None), 0)
            hdd = np.nansum(np.clip(18 - tmean, 0, None), 0)
            tv = np.isfinite(tmean).any(0)
            cdd[~tv], hdd[~tv] = np.nan, np.nan
            tavg = np.nanmean(tmean, 0)
        out = pd.DataFrame({"monsoon_rainfall_mm": _state_mean(mons, wr), "annual_rainfall_mm": _state_mean(ann, wr),
                            "avg_temp_c": _state_mean(tavg, wt), "cooling_degree_days": _state_mean(cdd, wt),
                            "heating_degree_days": _state_mean(hdd, wt)})
        out["year"] = y
        rows.append(out.rename_axis("state_code").reset_index())
        print(f"  [imd] {y} done")
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


if __name__ == "__main__":
    fails = prefetch(range(1990, 2025))
    print("IMD download failures:", fails)
