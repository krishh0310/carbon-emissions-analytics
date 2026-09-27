"""Scenario / counterfactual engine (v2). Structural adjustment of the reconciled state x sector P50/P10/P90 forecast.

Why not re-run the network with edited covariates: renewable share, EV adoption and industrial-policy variables are
constant or unobserved during the training years (<= 2014), so the network has no learned response to them —
perturbing its inputs would return arbitrary numbers. Instead each lever acts through an explicit, auditable identity,
ramping linearly from the last observed year to the end of the forecast horizon:

  POWER      × (1 − Δrenewable_pp·r / fossil_share)            fossil_share from CEA generation mix (latest FY)
             + EV load: removed_road_CO2 × EF_grid / (EF_fuel × η_EV)  (EF_fuel 0.25 tCO2/MWh-fuel, η_EV = 3.2×)
  TRANSPORT  − ev_share·r × road_share × TRANSPORT           road_share = EDGAR road / transport (≈0.9)
  INDUSTRY   × (1 + Δgrowth_pp/100)^(years ahead)
  BUILDINGS  × (1 − efficiency_pct·r/100)
  others     unchanged
Uncertainty: the model's P10/P90 are scaled by the same factor, then widened by ±20 % of the scenario delta
(parameter uncertainty of the identities).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.data.cache import PROCESSED, ROOT

BOUNDS = {"renewable_pp": (0.0, 40.0), "ev_share_pct": (0.0, 60.0), "industrial_growth_pp": (-5.0, 5.0),
          "building_efficiency_pct": (0.0, 30.0)}
EF_FUEL, ETA_EV, ROAD_SHARE_DEFAULT, FOSSIL_DEFAULT, EF_GRID_DEFAULT = 0.25, 3.2, 0.9, 0.75, 0.72


@dataclass
class Params:
    renewable_pp: float = 0.0
    ev_share_pct: float = 0.0
    industrial_growth_pp: float = 0.0
    building_efficiency_pct: float = 0.0

    def validate(self) -> Params:
        for k, (lo, hi) in BOUNDS.items():
            v = getattr(self, k)
            if not (isinstance(v, (int, float)) and np.isfinite(v) and lo <= v <= hi):
                raise ValueError(f"{k}={v} outside [{lo}, {hi}]")
        return self


PRESETS = {
    "bau": ("Business-as-usual", Params()),
    "moderate": ("Moderate policy", Params(renewable_pp=10, ev_share_pct=15, industrial_growth_pp=0, building_efficiency_pct=5)),
    "ambitious": ("Ambitious policy", Params(renewable_pp=25, ev_share_pct=35, industrial_growth_pp=-1, building_efficiency_pct=15)),
}


def state_structure() -> pd.DataFrame:
    """Per-state fossil share of generation, grid EF (latest CEA FY) and road share of transport (latest EDGAR)."""
    st = pd.read_parquet(PROCESSED / "india_states_panel.parquet")
    gen_cols = [c for c in st if c.endswith("_generation_gwh")]
    last = st[st.cea_available == 1].sort_values("year").groupby("state_code").tail(1).set_index("state_code")
    fossil = last[[c for c in gen_cols if c.split("_")[0] in ("coal", "gas", "oil")]].sum(1) / last[gen_cols].sum(1).replace(0, np.nan)
    ef = last.grid_emission_factor
    sec = pd.read_parquet(PROCESSED / "india_states_sector_panel.parquet")
    ly = sec.year.max()
    tr = sec[(sec.year == ly) & (sec.sector == "TRANSPORT")].set_index("state_code").co2_mt
    road = st[st.year == ly].set_index("state_code").edgar_road_mt
    out = pd.DataFrame({"fossil_share": fossil, "grid_ef": ef}).reindex(tr.index)
    out["road_share"] = (road / tr.replace(0, np.nan)).clip(0, 1)
    return out.fillna({"fossil_share": FOSSIL_DEFAULT, "grid_ef": EF_GRID_DEFAULT, "road_share": ROAD_SHARE_DEFAULT})


def apply(fc: pd.DataFrame, p: Params, structure: pd.DataFrame, states: list[str] | None = None) -> pd.DataFrame:
    """fc: rows (state_code, sector, year, p10, p50, p90) — forecast years only. Returns same + scenario columns."""
    p.validate()
    fc = fc.copy()
    y0 = fc.year.min() - 1
    span = max(fc.year.max() - y0, 1)
    r = (fc.year - y0) / span
    s = structure.reindex(fc.state_code)
    fossil, ef, road = s.fossil_share.to_numpy(), s.grid_ef.to_numpy(), s.road_share.to_numpy()
    fossil = np.clip(fossil, 0.05, 1)
    factor = np.ones(len(fc))
    sec = fc.sector.to_numpy()
    active = np.ones(len(fc), bool) if not states else fc.state_code.isin(states).to_numpy()

    tr = active & (sec == "TRANSPORT")
    ev_cut = np.where(tr, p.ev_share_pct / 100 * r * road, 0)
    factor = np.where(tr, 1 - ev_cut, factor)
    removed_road = pd.Series(np.where(tr, fc.p50 * ev_cut, 0)).groupby([fc.state_code.to_numpy(), fc.year.to_numpy()]).sum()

    pw = active & (sec == "POWER")
    ren = np.minimum(p.renewable_pp / 100 * r, fossil) / fossil
    factor = np.where(pw, 1 - ren, factor)
    ev_load = np.array([removed_road.get((c, y), 0.0) for c, y in zip(fc.state_code, fc.year, strict=True)]) * ef / (EF_FUEL * ETA_EV)
    add = np.where(pw, ev_load * (1 - ren), 0)  # EV electricity also gets cleaner as renewables rise

    ind = active & (sec == "INDUSTRY")
    factor = np.where(ind, (1 + p.industrial_growth_pp / 100) ** (fc.year - y0), factor)
    bld = active & (sec == "BUILDINGS")
    factor = np.where(bld, 1 - p.building_efficiency_pct / 100 * r, factor)

    base = fc["p50"].to_numpy()
    fc["scenario_p50"] = base * factor + add
    delta = fc.scenario_p50 - base
    fc["scenario_p10"] = np.minimum(fc.p10 * factor + add - 0.2 * np.abs(delta), fc.scenario_p50)
    fc["scenario_p90"] = np.maximum(fc.p90 * factor + add + 0.2 * np.abs(delta), fc.scenario_p50)
    fc["delta_mt"] = delta
    return fc


def run(params: Params, states: list[str] | None = None, model: str | None = None) -> dict:
    from src.champion import best

    model = model or best("state_sector")
    fc = pd.read_parquet(ROOT / "results" / "forecasts_sector.parquet")
    fc = fc[fc.model == model].copy()
    if fc.empty:
        raise ValueError(f"no sector forecasts for model {model}")
    fc["p50"] = fc.p50_reconciled.fillna(fc.p50)
    out = apply(fc[["state_code", "sector", "year", "p10", "p50", "p90"]], params, state_structure(), states)
    end = out[out.year == out.year.max()]
    by_state = end.groupby("state_code")[["p50", "scenario_p50", "scenario_p10", "scenario_p90", "delta_mt"]].sum()
    by_sector = end.groupby("sector")[["p50", "scenario_p50", "delta_mt"]].sum()
    return {"params": asdict(params), "states": states or "ALL", "model": model, "end_year": int(out.year.max()),
            "national": {"baseline_mt": float(end.p50.sum()), "scenario_mt": float(end.scenario_p50.sum()),
                         "delta_mt": float(end.delta_mt.sum())},
            "by_state": by_state.round(4).reset_index().to_dict("records"),
            "by_sector": by_sector.round(4).reset_index().to_dict("records"),
            "path": out.groupby("year")[["p50", "scenario_p50", "scenario_p10", "scenario_p90"]].sum().round(3).reset_index().to_dict("records"),
            "cell_path": out[["state_code", "sector", "year", "p50", "scenario_p50", "scenario_p10", "scenario_p90"]].round(4).to_dict("records"),
            "cells": end[["state_code", "sector", "p50", "scenario_p50", "scenario_p10", "scenario_p90", "delta_mt"]].round(4).to_dict("records"),
            "method": __doc__.split("\n\n")[1].strip()[:600]}
