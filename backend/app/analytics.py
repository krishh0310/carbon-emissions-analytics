"""/api/v2/analytics — long-history and multi-source views for the Analytics page (viewer-safe: no model internals).

Reads the processed parquet files directly (built by src.data.ingest + src.data.external); nothing here is trained on.
Series are returned column-wise ({key: [values aligned to `years`]}) to keep payloads small.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query

from backend.app.db import User
from backend.app.security import current_user

PROC = Path(__file__).resolve().parents[2] / "data" / "processed"
SECTORS = ["POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER"]
Viewer = Annotated[User, Depends(current_user)]
router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])

SOURCES = {
    "edgar": "EDGAR 2025 (EU JRC) 0.1° grids, downscaled — 1970–1989 back-history + 1990–2024 panel",
    "owid": "Our World in Data CO₂ & GHG dataset (Global Carbon Project; GHGs from Jones et al. 2023) — github.com/owid/co2-data",
    "worldbank": "World Bank WDI API, EN.GHG.* (AR5 CO₂e, excl. LULUCF)",
    "climatetrace": "Climate TRACE v6 API (asset- & satellite-based estimates) — api.climatetrace.org",
}


def _read(name: str) -> pd.DataFrame:
    p = PROC / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _panel(kind: Literal["states", "cities"]) -> pd.DataFrame:
    # keyed on file mtimes so a refresh by the worker is picked up without restarting the API
    names = (f"india_{kind}_sector_history", f"india_{kind}_sector_panel")
    return _panel_cached(kind, tuple((PROC / f"{n}.parquet").stat().st_mtime if (PROC / f"{n}.parquet").exists() else 0 for n in names))


@lru_cache(maxsize=4)
def _panel_cached(kind: str, _mtimes: tuple) -> pd.DataFrame:
    """History (1970–1989, if built) + main panel (1990+), long format: id, sector, year, co2e_mt."""
    idc = "state_code" if kind == "states" else "city_id"
    df = pd.concat([_read(f"india_{kind}_sector_history"), _read(f"india_{kind}_sector_panel")], ignore_index=True)
    if df.empty:
        return pd.DataFrame(columns=["id", "sector", "year", "co2e_mt"])
    df = df.rename(columns={idc: "id"})[["id", "sector", "year", "co2e_mt"]]
    return df.drop_duplicates(["id", "sector", "year"], keep="last")


def _wide(df: pd.DataFrame, years: list[int]) -> dict:
    """{id: {sector: [values per year]}} rounded to kt."""
    out: dict = {}
    for (i, s), g in df.groupby(["id", "sector"]):
        v = g.set_index("year").co2e_mt.reindex(years)
        out.setdefault(str(i), {})[s] = [None if pd.isna(x) else round(float(x), 4) for x in v]
    return out


def _clean(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


@router.get("/national")
def national(_: Viewer):
    p = _panel("states")
    years = sorted(p.year.unique().tolist())
    nat = p.groupby(["sector", "year"]).co2e_mt.sum().unstack(0).reindex(years)
    ct = _read("ext_climatetrace_sectors")
    ct = ct.dropna(subset=["sector"]).groupby(["year", "sector"]).co2e_mt.sum().unstack(1) if not ct.empty else pd.DataFrame()
    owid = _read("ext_owid")
    return {
        "years": years,
        "sectors": {s: [round(float(x), 3) for x in nat.get(s, pd.Series(0, index=years)).fillna(0)] for s in SECTORS},
        "history_from": int(years[0]) if years else None,
        "owid": _clean(owid[owid.country == "India"]) if not owid.empty else [],
        "worldbank": _clean(_read("ext_worldbank")),
        "climatetrace": {int(y): {s: round(float(v), 2) for s, v in r.items() if pd.notna(v)} for y, r in ct.iterrows()},
        "sources": SOURCES,
    }


@router.get("/world")
def world(_: Viewer):
    owid = _read("ext_owid")
    cols = ["country", "year", "co2", "co2_per_capita", "total_ghg", "total_ghg_excluding_lucf", "ghg_per_capita", "share_global_co2",
            "cumulative_co2", "co2_per_gdp"]
    return {"items": _clean(owid[[c for c in cols if c in owid]]) if not owid.empty else [], "source": SOURCES["owid"]}


@router.get("/states")
def states(_: Viewer):
    from src.data.reference import states_df

    p = _panel("states")
    years = sorted(p.year.unique().tolist())
    meta = states_df()[["code", "name", "region", "is_ut"]]
    return {"years": years, "sectors": SECTORS, "entities": _clean(meta), "data": _wide(p, years), "source": SOURCES["edgar"]}


@router.get("/cities")
def cities(_: Viewer):
    from src.data.reference import cities_df

    p = _panel("cities")
    years = sorted(p.year.unique().tolist())
    meta = cities_df()[["id", "name", "state_code", "is_metro", "confidence_tier"]]
    return {"years": years, "sectors": SECTORS, "entities": _clean(meta), "data": _wide(p, years),
            "source": SOURCES["edgar"] + " (city buffers; proxy estimates)"}


@router.get("/facilities")
def facilities(_: Viewer, state: str | None = Query(None, pattern=r"^IN-[A-Z]{2}$"),
               sector: Literal["POWER", "INDUSTRY", "WASTE", "OTHER"] | None = None,
               limit: int = Query(100, ge=1, le=500)):
    f = _read("ext_facilities")
    if f.empty:
        return {"items": [], "source": SOURCES["climatetrace"]}
    if state:
        f = f[f.state_code == state]
    if sector:
        f = f[f.sector == sector]
    cols = ["id", "name", "owner", "sector", "subsector", "asset_type", "co2e_mt", "capacity", "capacity_units",
            "lat", "lon", "state_code", "year"]
    return {"items": _clean(f.sort_values("co2e_mt", ascending=False).head(limit)[cols]), "source": SOURCES["climatetrace"]}
