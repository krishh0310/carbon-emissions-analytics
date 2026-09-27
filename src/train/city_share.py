"""Allocate reconciled state-sector forecasts to city buffers and an unallocated remainder.

City buffers are partial, sometimes overlapping samples of states. Each city's three-year
mean sector share is capped collectively at 1; the leftover remains explicitly unallocated.
This preserves the state-sector forecast without pretending sampled cities cover all land.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def allocate(city: pd.DataFrame, state: pd.DataFrame, forecast: pd.DataFrame, city_states: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    last = int(city.year.max())
    recent = city[city.year.between(last - 2, last)].copy()
    recent["state_code"] = recent.city_id.map(city_states)
    st = state.set_index(["state_code", "sector", "year"]).co2e_mt
    recent["denominator"] = [st.get((r.state_code, r.sector, r.year), np.nan) for r in recent.itertuples()]
    recent["share"] = (recent.co2e_mt / recent.denominator).replace([np.inf, -np.inf], np.nan).fillna(0).clip(lower=0)
    weights = recent.groupby(["state_code", "sector", "city_id"], as_index=False).share.mean()
    sums = weights.groupby(["state_code", "sector"]).share.transform("sum")
    weights["share"] = weights.share / sums.clip(lower=1)
    fc = forecast.copy()
    fc["p50"] = fc.p50_reconciled.fillna(fc.p50) if "p50_reconciled" in fc else fc.p50
    fc["p50"] = fc.p50.clip(lower=0)
    fc["p10"] = fc.p10.clip(lower=0).clip(upper=fc.p50)
    fc["p90"] = fc.p90.clip(lower=fc.p50)
    joined = fc.merge(weights, on=["state_code", "sector"], how="left")
    for q in ("p10", "p50", "p90"):
        joined[q] = joined[q] * joined.share.fillna(0)
    cities = joined.groupby(["city_id", "year"], as_index=False)[["p10", "p50", "p90"]].sum()
    cities = cities[cities.city_id.notna()].copy()
    cities.city_id = cities.city_id.astype(int)
    totals = fc.groupby(["state_code", "year"], as_index=False)[["p10", "p50", "p90"]].sum()
    used = joined.groupby(["state_code", "year"], as_index=False)[["p10", "p50", "p90"]].sum()
    residual = totals.merge(used, on=["state_code", "year"], suffixes=("", "_used"))
    for q in ("p10", "p50", "p90"):
        residual[q] = (residual[q] - residual[f"{q}_used"]).clip(lower=0)
    return cities, residual[["state_code", "year", "p10", "p50", "p90"]]
