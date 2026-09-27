"""City metadata for the Cities page: `python -m src.data.cities_meta`.

- Census 2011 urban-agglomeration (UA) population (Wikipedia mirror of Census tables; fallback: city-proper 2011).
- EDGAR grid cells inside each city's buffer and the buffer area → shown in the per-city "how estimated" panel.
Output: data/processed/city_meta.parquet
"""
from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd

from src.data import edgar
from src.data.cache import PROCESSED, RAW, fetch
from src.data.reference import cities_df

ALIASES = {"bengaluru": "bangalore", "prayagraj": "allahabad", "vishakhapatnam": "visakhapatnam", "gurugram": "gurgaon",
           "thiruvananthapuram": "trivandrum", "kochi": "cochin", "puducherry": "pondicherry", "mysuru": "mysore",
           "vasai-virar": "vasai virar", "aurangabad": "chhatrapati sambhajinagar"}


def _norm(s: str) -> str:
    s = re.sub(r"\[.*?\]|[‡†*]|\(.*?\)", "", str(s)).strip().lower()
    return s.split(",")[0].strip()


def census_population() -> dict[str, tuple[float, str]]:
    out: dict[str, tuple[float, str]] = {}
    ua = pd.read_html(io.StringIO(fetch("https://en.wikipedia.org/wiki/List_of_million-plus_urban_agglomerations_in_India",
                                        RAW / "wiki" / "million_plus_ua.html").read_text()))[0]
    for _, r in ua.iterrows():
        v = pd.to_numeric(str(r["Pop. (2011)"]).replace(",", ""), errors="coerce")
        if pd.notna(v):
            out[_norm(r.iloc[0])] = (float(v), "Census 2011 urban agglomeration")
    cp = pd.read_html(io.StringIO(fetch("https://en.wikipedia.org/wiki/List_of_cities_in_India_by_population",
                                        RAW / "wiki" / "cities_by_population.html").read_text()))[0]
    cp.columns = [" ".join(dict.fromkeys(map(str, c))) for c in cp.columns]
    ncol = next(c for c in cp.columns if c.startswith("Name"))
    pcol = next(c for c in cp.columns if "2011" in c)
    for _, r in cp.iterrows():
        v = pd.to_numeric(str(r[pcol]).replace(",", ""), errors="coerce")
        k = _norm(r[ncol])
        if pd.notna(v) and k not in out:
            out[k] = (float(v), "Census 2011 city (municipal corporation)")
    return out


def build() -> pd.DataFrame:
    c = cities_df()
    pops = census_population()
    _, da = edgar._nc("ENE", 2024)
    cw = edgar.city_weights(da.lat.values, da.lon.values)
    cells = cw.groupby("city_id").size()
    lat = np.radians(c.lat.to_numpy())
    cell_km2 = (0.1 * 111.32) ** 2 * np.cos(lat)
    rows = []
    for i, r in enumerate(c.itertuples()):
        k = r.name.lower()
        hit = pops.get(k) or pops.get(ALIASES.get(k, k)) or next((v for kk, v in pops.items() if kk.startswith(k)), None)
        rows.append({"city_id": r.id, "pop_2011": hit[0] if hit else np.nan, "pop_source": hit[1] if hit else None,
                     "n_cells": int(cells.get(r.id, 0)), "buffer_km": r.buffer_km,
                     "buffer_area_km2": float(np.pi * r.buffer_km ** 2), "cells_area_km2": float(cells.get(r.id, 0) * cell_km2[i])})
    out = pd.DataFrame(rows)
    out.to_parquet(PROCESSED / "city_meta.parquet", index=False)
    return out


if __name__ == "__main__":
    m = build()
    print(f"{m.pop_2011.notna().sum()}/{len(m)} cities matched to Census 2011 population; cells per city median {m.n_cells.median():.0f}")
    print(m.merge(cities_df()[["id", "name"]], left_on="city_id", right_on="id")[m.pop_2011.isna()].name.tolist())
