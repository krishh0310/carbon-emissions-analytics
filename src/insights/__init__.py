"""Analytics layer on the processed panel + forecasts: `python -m src.insights` writes results/insights.json."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.data.cache import PROCESSED, ROOT

RES = ROOT / "results"


def _cagr(a, b, n):
    return 100 * ((b / a) ** (1 / n) - 1) if a and a > 0 and b > 0 else np.nan


def compute(best_model: str | None = None) -> dict:
    df = pd.read_parquet(PROCESSED / "india_states_panel.parquet")
    last = int(df.year.max())
    cur = df[df.year == last].set_index("state_code")
    old = df[df.year == last - 10].set_index("state_code")

    # decoupling: 10-yr real GSDP CAGR vs CO2 CAGR (absolute: CO2 falls; relative: CO2 grows slower than GSDP)
    dec = pd.DataFrame({"gsdp_cagr": [_cagr(old.gsdp_const_cr[c], cur.gsdp_const_cr[c], 10) for c in cur.index],
                        "co2_cagr": [_cagr(old.co2_mt[c], cur.co2_mt[c], 10) for c in cur.index]}, index=cur.index)
    dec["decoupling_index"] = dec.gsdp_cagr - dec.co2_cagr
    dec["status"] = np.select([(dec.gsdp_cagr > 0) & (dec.co2_cagr < 0), dec.co2_cagr < dec.gsdp_cagr],
                              ["absolute", "relative"], "none")
    dec["gsdp_imputed"] = cur.gsdp_imputed.astype(bool)

    ci = pd.DataFrame({"co2_mt": cur.co2_mt, "gsdp_const_cr": cur.gsdp_const_cr,
                       "tco2_per_crore": cur.co2_mt * 1e6 / cur.gsdp_const_cr,
                       "per_capita_t": cur.co2_mt / cur.population_mn,
                       "coal_dependence": cur.edgar_power_mt / cur.co2_mt})

    # watchlist: 5-yr forecast CAGR vs fair-share trajectory (national per-capita convergence proxy:
    # a state's fair share grows at national forecast CAGR scaled by (national per-capita / state per-capita))
    watch = []
    fp = RES / "forecasts.parquet"
    if fp.exists():
        f = pd.read_parquet(fp)
        if best_model is None:
            from src.champion import best

            best_model = best("state")
        f = f[(f.model == best_model) & (f.horizon == 5)].set_index("state_code")
        col = "p50_reconciled" if f.p50_reconciled.notna().all() else "p50"
        nat_now, nat_f = cur.co2_mt.sum(), f[col].sum()
        nat_cagr = _cagr(nat_now, nat_f, 5)
        nat_pc = nat_now / cur.population_mn.sum()
        for c in f.index:
            fc = _cagr(cur.co2_mt[c], f.loc[c, col], 5)
            pc = cur.co2_mt[c] / cur.population_mn[c]
            fair = nat_cagr * min(nat_pc / pc, 2.0) if pc > 0 else nat_cagr
            watch.append({"state_code": c, "forecast_cagr_5y": fc, "fair_share_cagr_5y": fair,
                          "excess_pp": fc - fair, "forecast_2029_mt": float(f.loc[c, col]), "p90_mt": float(f.loc[c, "p90"]),
                          "coal_dependence": float(ci.coal_dependence[c]),
                          # material emitters only: tiny UTs have noisy growth on a near-zero base
                          "on_watchlist": bool(fc > fair and cur.co2_mt[c] >= 5.0)})
    watch = pd.DataFrame(watch)

    cp = pd.read_parquet(PROCESSED / "india_cities_panel.parquet")
    cities = cp[cp.year == last][["city_id", "name", "state_code", "co2_mt", "share_of_state", "estimation_method",
                                  "confidence_tier"]].sort_values("co2_mt", ascending=False)

    def rec(d):
        return json.loads(d.reset_index().replace({np.nan: None}).to_json(orient="records"))

    return {"year": last, "best_model": best_model,
            "decoupling": rec(dec.sort_values("decoupling_index", ascending=False)),
            "carbon_intensity": rec(ci.sort_values("tco2_per_crore", ascending=False)),
            "watchlist": rec(watch.sort_values("excess_pp", ascending=False)) if len(watch) else [],
            "cities": json.loads(cities.to_json(orient="records")),
            "notes": {"emissions": "EDGAR-downscaled estimates (not official state inventories).",
                      "cities": "City values are EDGAR grid-buffer ESTIMATES, never measured inventories.",
                      "watchlist": "Only states/UTs emitting >= 5 Mt are eligible.",
                      "fair_share": "Fair-share CAGR = national forecast CAGR × (national per-capita / state per-capita), capped at 2×."}}


