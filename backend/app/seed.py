"""Seed/refresh the DB from data/processed + results/: `python -m backend.app.seed`. Idempotent (replaces data tables;
users are kept). Creates the PostGIS extension + tables if missing, and a bootstrap admin if ADMIN_EMAIL/PASSWORD set."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, select, text

from backend.app.config import settings
from backend.app.db import (
    Artifact,
    Base,
    City,
    EmissionCity,
    EmissionState,
    EmissionStateSector,
    FeatureState,
    Forecast,
    ForecastSector,
    Insight,
    Model,
    State,
    User,
    engine,
    session,
)
from backend.app.security import hash_password

ROOT = Path(__file__).resolve().parents[2]
PROC, RES = ROOT / "data" / "processed", ROOT / "results"

from src.data.reference import NAME_HI  # noqa: E402

FEATURE_COLS = ["edgar_power_mt", "edgar_industry_mt", "edgar_road_mt", "edgar_cement_mt", "edgar_buildings_mt",
                "coal_generation_gwh", "gas_generation_gwh", "hydro_generation_gwh", "nuclear_generation_gwh",
                "renewable_share_pct", "grid_emission_factor", "gsdp_cr", "gsdp_const_cr", "gsdp_growth_pct",
                "population_mn", "urban_population_pct", "population_density", "avg_temp_c", "cooling_degree_days",
                "monsoon_rainfall_mm", "drought_year", "covid_dummy", "lockdown_stringency", "ev_policy_dummy",
                "coal_dependence", "road_share", "gsdp_imputed", "heating_degree_days", "diesel_sales_kt", "petrol_sales_kt",
                "pol_sales_kt", "climate_source", "ndc_phase", "annual_rainfall_mm"]


def _clean(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.replace([np.inf, -np.inf], np.nan).to_json(orient="records"))


def _multipolygon_wkt(geom):
    from shapely.geometry import MultiPolygon

    return (MultiPolygon([geom]) if geom.geom_type == "Polygon" else geom).wkt


def seed(keep_registry: bool = False) -> None:
    """keep_registry=True (used by the continuous-learning cycle): refresh data tables only; model versions,
    champion/challenger status and their forecasts are untouched (states/cities are upserted, not deleted)."""
    import geopandas as gpd

    from src.data.features import engineer

    eng = engine()
    pg = eng.dialect.name == "postgresql"
    if pg:
        with eng.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(eng)

    panel = engineer(pd.read_parquet(PROC / "india_states_panel.parquet"))
    cities = pd.read_parquet(PROC / "india_cities_panel.parquet")
    geo = gpd.read_file(PROC / "india_states.geojson")
    inc = panel.drop_duplicates("state_code").set_index("state_code").income_group

    with session() as db:
        db._prev_insights = [type("P", (), {c: getattr(r, c) for c in ("state_code", "sector", "type", "title", "body", "approved",
                                                                         "admin_note", "edited_by")}) for r in db.scalars(select(Insight))]
        tables = (Insight, EmissionStateSector, EmissionCity, FeatureState, EmissionState, Artifact) if keep_registry else \
            (ForecastSector, Forecast, Model, Insight, EmissionStateSector, EmissionCity, FeatureState, EmissionState, City, State, Artifact)
        for T in tables:
            db.execute(delete(T))
        for r in geo.itertuples():
            g = f"SRID=4326;{_multipolygon_wkt(r.geometry)}" if pg else json.dumps(r.geometry.__geo_interface__)
            db.merge(State(code=r.code, name=r.name, name_hi=NAME_HI.get(r.code), region=r.region,
                         income_group=inc.get(r.code), is_ut=bool(r.is_ut), coastal=bool(r.coastal), geometry=g,
                         boundary_source=r.boundary_source))
        db.flush()
        for r in panel.itertuples():
            db.add(EmissionState(state_code=r.state_code, year=int(r.year), co2_mt=_clean(r.co2_mt),
                                 co2_per_capita=_clean(r.per_capita_co2), carbon_intensity=_clean(r.carbon_intensity),
                                 cea_power_co2_mt=_clean(r.cea_power_co2_mt), source=r.emissions_source,
                                 is_imputed=bool(r.gsdp_imputed)))
            db.add(FeatureState(state_code=r.state_code, year=int(r.year),
                                features={c: _clean(getattr(r, c, None)) for c in FEATURE_COLS}))
        for c in cities.drop_duplicates("city_id").itertuples():
            db.merge(City(id=int(c.city_id), state_code=c.state_code, name=c.name, lat=c.lat, lon=c.lon,
                        estimation_method=c.estimation_method, confidence_tier=c.confidence_tier))
        db.flush()
        for c in cities.itertuples():
            db.add(EmissionCity(city_id=int(c.city_id), year=int(c.year), co2_mt=_clean(c.co2_mt), method=c.method,
                                confidence=c.confidence))
        db.flush()
        _seed_artifacts(db, panel)
        _seed_v2(db, panel)
        _seed_cities_v3(db)
        db.flush()
        s = settings()
        if s.admin_email and s.admin_password and not db.scalar(select(User).where(User.email == s.admin_email.lower())):
            db.add(User(email=s.admin_email.lower(), hash=hash_password(s.admin_password), role="admin"))
        db.commit()
    if not keep_registry:  # fresh install: register current results as version 'initial' and bootstrap champions
        from backend.app import mlops

        with session() as db:
            mlops.register_candidates(db, "initial")
        mlops.promotion_check()
    print("seeded", len(geo), "states,", cities.city_id.nunique(), "cities", "(registry kept)" if keep_registry else "")


def _seed_artifacts(db, panel: pd.DataFrame) -> None:
    tab = RES / "tables"
    if (RES / "insights.json").exists():
        ins = json.loads((RES / "insights.json").read_text())
        names = panel.drop_duplicates("state_code").set_index("state_code")
        from src.data.reference import states_df
        nm = states_df().set_index("code").name
        for k in ("decoupling", "carbon_intensity", "watchlist"):
            for row in ins[k]:
                row["name"] = nm.get(row["state_code"])
                row["name_hi"] = NAME_HI.get(row["state_code"])
                row["region"] = names.region.get(row["state_code"])
        db.add(Artifact(key="insights", data=ins))
    if (tab / "metrics.csv").exists():
        m = pd.read_csv(tab / "metrics.csv")
        m = m[m.level == "state"] if "level" in m else m  # v1 leaderboard: state-level rows only
        allm = m[m.state_code == "ALL"]
        db.add(Artifact(key="leaderboard", data={
            "rows": _records(allm[["model", "horizon", "split", "mae", "rmse", "mape", "smape", "mase", "r2",
                                   "reconciled_mase", "training_time"]]),
            "per_state_test": _records(m[(m.split == "test") & (m.state_code != "ALL") & (m.horizon.isin([1, 3, 5]))]
                                       [["model", "state_code", "horizon", "mase", "mape"]]),
            "note": "MASE scaled by each state's train-period naive-1 MAE. Test = target years 2020+ (includes COVID shock). "
                    "ARIMA is fit on the 10 largest emitters only."}))
    for p in tab.glob("importance_*.csv"):
        name = p.stem.split("_", 1)[1]
        d = {"groups": _records(pd.read_csv(p))}
        for extra, key in ((f"attention_{name}.csv", "attention"), ):
            if (tab / extra).exists():
                d[key] = _records(pd.read_csv(tab / extra))
        if name == "lightgbm":
            for f, k in (("shap_lightgbm.csv", "shap"), ("pdp_renewable_share.csv", "pdp_renewable_share")):
                if (tab / f).exists():
                    d[k] = _records(pd.read_csv(tab / f).head(30))
        if name == "tft" and (tab / "tft_variable_selection.csv").exists():
            d["variable_selection"] = _records(pd.read_csv(tab / "tft_variable_selection.csv").head(30))
        db.add(Artifact(key=f"importance:{name}", data=d))
    if (RES / "backtest.parquet").exists():
        bt = pd.read_parquet(RES / "backtest.parquet")
        bt = bt[bt.horizon.isin([1, 3, 5])]
        for name, g in bt.groupby("model"):
            db.add(Artifact(key=f"backtest:{name}", data=_records(
                g[["state_code", "origin", "horizon", "year", "p10", "p50", "p90", "p50_reconciled", "actual"]].round(4))))
    dq = {}
    if (tab / "coverage_state_year.csv").exists():
        dq["coverage"] = _records(pd.read_csv(tab / "coverage_state_year.csv").round(3))
    if (tab / "imputation_report.csv").exists():
        dq["imputations"] = _records(pd.read_csv(tab / "imputation_report.csv"))
    cmp_ = panel[panel.cea_power_co2_mt.notna()].groupby("year")[["edgar_power_mt", "cea_power_co2_mt"]].sum().reset_index()
    dq["edgar_vs_cea"] = _records(cmp_.round(2))
    dq["edgar_vs_cea_state"] = _records(panel[panel.year == cmp_.year.max() if len(cmp_) else 0]
                                        [["state_code", "edgar_power_mt", "cea_power_co2_mt"]].round(2))
    db.add(Artifact(key="data_quality", data=dq))


def _nan_free(o):
    """Recursively replace NaN/inf (invalid JSON) with None."""
    if isinstance(o, dict):
        return {k: _nan_free(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_nan_free(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def _seed_cities_v3(db) -> None:
    """City analytics artifact: CO2e history + sector split inside the buffer, share of state, CO2e forecast
    (= Σ_sector state reconciled forecast × city's mean share of that state-sector over the last 3 years), ranking."""
    cp, sp = PROC / "india_cities_sector_panel.parquet", PROC / "india_states_sector_panel.parquet"
    if not cp.exists() or not sp.exists():
        return
    from src.champion import best
    from src.data.reference import cities_df

    cs, ss = pd.read_parquet(cp), pd.read_parquet(sp)
    meta = cities_df().set_index("id")
    cm = pd.read_parquet(PROC / "city_meta.parquet").set_index("city_id") if (PROC / "city_meta.parquet").exists() else pd.DataFrame()
    last = int(cs.year.max())
    fc = pd.read_parquet(RES / "forecasts_sector.parquet") if (RES / "forecasts_sector.parquet").exists() else pd.DataFrame()
    if len(fc):
        fc = fc[fc.model == best("state_sector")]
    st_sec = ss.set_index(["state_code", "sector", "year"]).co2e_mt
    st_tot = ss.groupby(["state_code", "year"]).co2e_mt.sum()
    details, ranking = {}, []
    for cid, g in cs.groupby("city_id"):
        m = meta.loc[cid]
        piv = g.pivot_table(index="year", columns="sector", values="co2e_mt").fillna(0)
        tot = piv.sum(1)
        share = (tot / st_tot.xs(m.state_code, level=0).reindex(tot.index)).replace([np.inf], np.nan)
        # forecast
        fpts = []
        if len(fc):
            f = fc[fc.state_code == m.state_code]
            for y, fy in f.groupby("year"):
                p10 = p50 = p90 = 0.0
                for r in fy.itertuples():
                    shr = np.nanmean([piv.get(r.sector, pd.Series(dtype=float)).get(yy, 0) / max(st_sec.get((m.state_code, r.sector, yy), np.nan), 1e-9)
                                      for yy in range(last - 2, last + 1)])
                    shr = 0.0 if not np.isfinite(shr) else shr
                    p10 += shr * r.p10
                    p50 += shr * (r.p50_reconciled if pd.notna(r.p50_reconciled) else r.p50)
                    p90 += shr * r.p90
                fpts.append({"year": int(y), "p10": round(p10, 5), "p50": round(p50, 5), "p90": round(p90, 5)})
        pop = cm.pop_2011.get(cid) if len(cm) else np.nan
        pop = float(pop) if pd.notna(pop) else None
        v0, v1 = tot.get(last - 10), tot.get(last)
        cagr = float(100 * ((v1 / v0) ** 0.1 - 1)) if v0 and v1 and v0 > 0 else None
        info = {"id": int(cid), "name": m["name"], "state_code": m.state_code, "lat": float(m.lat), "lon": float(m.lon),
                "confidence_tier": m.confidence_tier, "estimation_method": m.estimation_method, "buffer_km": float(m.buffer_km),
                "n_cells": int(cm.n_cells.get(cid, 0)) if len(cm) else None,
                "buffer_area_km2": float(cm.buffer_area_km2.get(cid, np.nan)) if len(cm) else None,
                "pop_2011": pop, "pop_source": (cm.pop_source.get(cid) if len(cm) else None)}
        # per-capita only where the population unit matches the buffer scale (million-plus urban agglomerations)
        pc_ok = bool(pop and v1 and pop >= 1e6 and str(info["pop_source"]).startswith("Census 2011 urban agglomeration"))
        ranking.append({**info, "co2e_mt": float(v1 or 0), "cagr10_pct": cagr, "per_capita_t": (float(v1) * 1e6 / float(pop)) if pc_ok and pop else None,
                        "share_of_state_pct": float(100 * share.get(last)) if pd.notna(share.get(last)) else None})
        details[str(cid)] = {**info, "year": last,
                             "history": [{"year": int(y), "co2e_mt": round(float(tot[y]), 5), "share_of_state_pct": round(float(100 * share[y]), 3) if pd.notna(share[y]) else None,
                                          **{k: round(float(piv.loc[y, k]), 5) for k in piv.columns}} for y in tot.index],
                             "forecast": fpts}
    db.add(Artifact(key="cities_v3", data=_nan_free({"year": last, "ranking": sorted(ranking, key=lambda r: -r["co2e_mt"]), "details": details})))


def _seed_triangulation(db, sec: pd.DataFrame, panel: pd.DataFrame) -> None:
    """Source triangulation + v3 analytics layers.
    power agreement = 1 − |EDGAR_power_CO2 − CEA_power_CO2| ÷ CEA_power_CO2 (FY2017+); divergent if |Δ| > 15 %.
    CEA-calibrated CO2e = total CO2e − EDGAR power CO2 + CEA power CO2 (grid plants; captive plants remain EDGAR).
    GHG Platform India validation is not scriptable (form-gated) -> reported as unavailable."""
    tot = sec.groupby(["state_code", "year"]).co2e_mt.sum()
    epow = sec[sec.sector == "POWER"].set_index(["state_code", "year"]).co2_mt
    p = panel.set_index(["state_code", "year"])
    vals: dict[str, dict] = {}
    factors: dict[str, float | None] = {}
    for c in panel.state_code.unique():
        vals[c] = {}
        rat = []
        for y in range(1990, int(panel.year.max()) + 1):
            e, t = epow.get((c, y)), tot.get((c, y))
            cea = p.cea_power_co2_mt.get((c, y)) if (c, y) in p.index else None
            rec = {"edgar_power_mt": _clean(e), "cea_power_mt": _clean(cea), "total_co2e_mt": _clean(t)}
            if cea is not None and pd.notna(cea) and e is not None:
                if cea > 0.05:
                    rec["agreement"] = round(float(max(0.0, 1 - abs(float(e) - cea) / cea)), 4)
                    rec["divergent"] = bool(abs(e - cea) / cea > 0.15)
                    rec["calibrated_co2e_mt"] = round(float(t - e + cea), 4)
                    rat.append(cea / e if e > 0.05 else np.nan)
                else:  # no CEA grid plants: EDGAR power here is captive/industrial -> keep EDGAR, no agreement score
                    rec["calibrated_co2e_mt"] = _clean(t)
            vals[c][y] = rec
        r = [x for x in rat if np.isfinite(x)]
        factors[c] = round(float(np.mean(r)), 4) if r else None
    db.add(Artifact(key="layer:triangulation", data=_nan_free({
        "unit": "agreement (0–1); MtCO₂e", "values": vals, "cea_over_edgar_factor": factors,
        "ghgpi": "unavailable (GHG Platform India downloads are form-gated; drop data/manual/extra/ghgpi_co2e_mt.csv to enable)",
        "method": "agreement = 1 − |EDGAR − CEA| ÷ CEA (power-sector CO₂, FY2017+); divergent if > 15 %; calibrated = total − EDGAR power + CEA power"})))
    ins_p = RES / "insights.json"
    if ins_p.exists():
        ins = json.loads(ins_p.read_text())
        db.add(Artifact(key="layer:decoupling", data={"unit": "category", "values": {
            d["state_code"]: {"status": d["status"], "gsdp_cagr": d["gsdp_cagr"], "co2_cagr": d["co2_cagr"]} for d in ins["decoupling"]}}))
    ai = RES / "atar_insights.json"
    if ai.exists():
        wl = [i for i in json.loads(ai.read_text()) if i["type"] == "WATCHLIST"]
        db.add(Artifact(key="layer:watchlist", data={"unit": "% above fair-share path by 2029", "values": {
            i["state_code"]: {"excess_pct": i["evidence"]["excess_pct"], "severity": i["severity"]} for i in wl}}))


def _seed_v2(db, panel: pd.DataFrame) -> None:
    """State x sector tables, sector models/forecasts, ATAR insights and v2 map artifacts (skipped if absent)."""
    sp = PROC / "india_states_sector_panel.parquet"
    if not sp.exists():
        print("no sector panel — run ingestion (v2) first; skipping v2 seed")
        return
    sec = pd.read_parquet(sp)
    db.bulk_insert_mappings(EmissionStateSector, [
        {"state_code": r.state_code, "sector": r.sector, "year": int(r.year), "co2e_mt": float(r.co2e_mt),
         "co2_mt": _clean(r.co2_mt), "ch4_co2e_mt": _clean(r.ch4_co2e_mt), "n2o_co2e_mt": _clean(r.n2o_co2e_mt),
         "source": r.source, "method": r.method[:160], "confidence": r.confidence} for r in sec.itertuples()])
    fc_p = RES / "forecasts_sector.parquet"
    ai = RES / "atar_insights.json"
    if ai.exists():
        from datetime import datetime

        # preserve admin moderation (approval / edited text) across reseeds, keyed by (state, sector, type, title)
        prev = {(r.state_code, r.sector, r.type, r.title): r for r in getattr(db, "_prev_insights", [])}
        rows = []
        for i in json.loads(ai.read_text()):
            p = prev.get((i["state_code"], i["sector"], i["type"], i["title"]))
            rows.append({"state_code": i["state_code"], "sector": i["sector"], "type": i["type"], "severity": i["severity"],
                         "title": i["title"], "body": p.body if p and p.edited_by else i["body"],
                         "title_hi": i.get("title_hi"), "body_hi": i.get("body_hi"),
                         "evidence": {"data": i["evidence"], "viz": i.get("viz"), "how": i.get("how")},
                         "approved": p.approved if p else True, "admin_note": p.admin_note if p else None,
                         "edited_by": p.edited_by if p else None,
                         "created_at": datetime.fromisoformat(i["generated_at"].replace("Z", "+00:00"))})
        db.bulk_insert_mappings(Insight, rows)
    tab = RES / "tables"
    if (tab / "metrics.csv").exists():
        m = pd.read_csv(tab / "metrics.csv")
        m = m[m.get("level", "state") == "state_sector"] if "level" in m else m.iloc[0:0]
        agg = m[m.state_code == "ALL"][["model", "sector", "horizon", "split", "mase", "reconciled_mase", "smape", "training_time"]]
        db.add(Artifact(key="sector_leaderboard", data=_records(agg)))
    if (tab / "experiments.csv").exists():
        db.add(Artifact(key="experiments", data=_records(pd.read_csv(tab / "experiments.csv"))))
    for p in tab.glob("importance_sector_*.csv"):
        db.add(Artifact(key=f"importance_sector:{p.stem.removeprefix('importance_sector_')}", data=_records(pd.read_csv(p))))
    ff = RES / "flow_field.json"
    if ff.exists():
        f = json.loads(ff.read_text())
        for k in ("TOTAL", *f.get("sectors", [])):
            db.add(Artifact(key=f"flow:{k}", data={**f[k], "year": f["year"], "method": f["method"], "sectors": f["sectors"]}))
    # derived layers: anomaly (actual vs trailing 5-yr log-linear trend) and forecast uncertainty
    tot = sec.groupby(["state_code", "year"]).co2e_mt.sum().unstack()
    an = {}
    for c, row in tot.iterrows():
        vals = {}
        for y in row.index:
            past = row.loc[y - 5: y - 1].dropna()
            if len(past) == 5 and (past > 0).all() and row[y] > 0:
                b = np.polyfit(past.index, np.log(past.values), 1)
                vals[int(y)] = round(float(100 * (row[y] / np.exp(np.polyval(b, y)) - 1)), 3)
        an[c] = vals
    db.add(Artifact(key="layer:anomaly", data={"unit": "% vs 5-yr trend", "values": an}))
    if fc_p.exists():
        f = pd.read_parquet(fc_p)
        from src.champion import best

        f = f[f.model == best("state_sector")].groupby(["state_code", "year"])[["p10", "p50", "p90"]].sum()
        un: dict[str, dict[int, float]] = {}
        for (c, y), r in f.iterrows():
            un.setdefault(c, {})[int(y)] = round(float(100 * (r.p90 - r.p10) / max(r.p50, 1e-9)), 3)
        db.add(Artifact(key="layer:uncertainty", data={"unit": "(P90−P10)/P50 %", "values": un}))
    _seed_triangulation(db, sec, panel)
    try:
        from backend.app.v2 import invalidate_cache

        invalidate_cache()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    import sys

    seed(keep_registry="--keep-registry" in sys.argv)
