"""Driver sources (all free, no keys). Each loader returns long/wide frames keyed on (state_code, year).

Fiscal years (FY t-(t+1), April-March) are mapped to calendar year t (9 of 12 months).
Every imputation is logged via `log_imputation` and written to results/tables/imputation_report.csv.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.cache import RAW, ROOT, fetch
from src.data.reference import STATE_CODES, name_to_code

IMPUTATIONS: list[dict] = []


def log_imputation(feature: str, method: str, n: int, note: str = "") -> None:
    IMPUTATIONS.append({"feature": feature, "method": method, "n_values": int(n), "note": note})


def _clean_name(s: str) -> str:
    return re.sub(r"\[.*?\]|\*| |\(.*?\)", "", str(s)).strip()


def _fy_start(s: str) -> int | None:
    m = re.match(r"\s*(\d{4})\s*[-–]", str(s))
    return int(m.group(1)) if m else None


# ---- CEA CO2 baseline database (plant-level, FY 2017-18 onwards) ------------------------------
CEA_URLS = [
    "https://cea.nic.in/wp-content/uploads/baseline/2026/09/Baseline_Carbon_Dioxide_Emission_Database_Version_22.0.xlsx",
    "https://cea.nic.in/wp-content/uploads/baseline/2025/12/CO2_Database_V_21.0.xlsx",
    "https://cea.nic.in/wp-content/uploads/2021/03/CO2_Database_Version_20.0_2023_24.xlsx",
]
_CEA_STATE_FIX = {"ARUNACHAL": "IN-AR", "HIMACHAL": "IN-HP", "TSECL": "IN-TR", "CHATTISGARH": "IN-CG"}
_FUEL = {"COAL": "coal", "LIGN": "coal", "GAS": "gas", "DISL": "oil", "OIL": "oil"}


def cea_power() -> pd.DataFrame:
    """State x year: {coal,gas,oil,hydro,nuclear}_generation_gwh, cea_power_co2_mt, grid_emission_factor."""
    d = pd.read_excel(fetch(CEA_URLS, RAW / "cea" / "co2_baseline_latest.xlsx"), "Data")
    d.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in d.columns]
    d = d[d["UNIT_NO"] == 0]  # station totals; unit rows would double count
    st = d["STATE"].astype(str).str.strip().str.upper()
    d = d.assign(state_code=st.map(lambda s: _CEA_STATE_FIX.get(s) or name_to_code(s)))
    d["fuel"] = np.where(d["TYPE"].str.strip() == "THERMAL", d["FUEL 1"].map(_FUEL), d["TYPE"].str.strip().str.lower())
    rows = []
    for c in d.columns:
        m = re.match(r"(\d{4})-\d{2} Net Generation GWh", c)
        if not m:
            continue
        y = int(m.group(1))
        em = c.replace("Net Generation GWh", "Absolute Emissions t CO2")
        g = d.assign(**{c: pd.to_numeric(d[c], errors="coerce"), em: pd.to_numeric(d[em], errors="coerce")}).groupby(["state_code", "fuel"])[[c, em]].sum(min_count=1).reset_index()
        for r in g.itertuples(index=False):
            rows.append({"state_code": r[0], "fuel": r[1], "year": y, "gwh": r[2], "t": r[3]})
    long = pd.DataFrame(rows).dropna(subset=["state_code"])
    gen = long.pivot_table(index=["state_code", "year"], columns="fuel", values="gwh", aggfunc="sum")
    gen.columns = [f"{c}_generation_gwh" for c in gen.columns]
    out = gen.reset_index()
    co2 = long.groupby(["state_code", "year"])["t"].sum().div(1e6).rename("cea_power_co2_mt").reset_index()
    out = out.merge(co2, on=["state_code", "year"], how="outer")
    conv = out.filter(like="_generation_gwh").sum(axis=1)
    out["grid_emission_factor"] = (out["cea_power_co2_mt"] * 1e6 / (conv * 1e3)).where(conv > 0)  # tCO2/MWh
    return out


# ---- GSDP (MoSPI series, via Wikipedia mirror) + World Bank backcast -----------------------------
WIKI = "https://en.wikipedia.org/wiki/"


def _wiki_tables(page: str) -> list[pd.DataFrame]:
    p = fetch(WIKI + page, RAW / "wiki" / f"{page}.html")
    return pd.read_html(io.StringIO(p.read_text()))


def world_bank(indicator: str) -> pd.Series:
    url = f"https://api.worldbank.org/v2/country/IND/indicator/{indicator}?format=json&per_page=200"
    js = json.loads(fetch(url, RAW / "worldbank" / f"{indicator}.json").read_text())
    return pd.Series({int(r["date"]): r["value"] for r in js[1] if r["value"] is not None}).sort_index()


def gsdp() -> pd.DataFrame:
    """gsdp_cr (current ₹ crore), gsdp_const_cr (2011-12 prices), gsdp_imputed flag."""
    long = []
    for t in _wiki_tables("List_of_Indian_states_and_union_territories_by_GDP"):
        t = t.copy()
        if not isinstance(t.columns[0], str):  # headerless table: first row holds the header
            t.columns = [str(x) for x in t.iloc[0]]
            t = t.iloc[1:]
        name_col = next((c for c in t.columns if str(c).startswith("State")), None)
        year_cols = [c for c in t.columns if _fy_start(c)]
        if not name_col or not year_cols or "Change" in "".join(map(str, t.columns[-1:])) and len(year_cols) < 3:
            continue
        # growth-rate table has decimals <100 for all states; value tables are in ₹ billion
        vals = pd.to_numeric(t[year_cols[0]], errors="coerce")
        if vals.max() < 100:
            continue
        for _, r in t.iterrows():
            code = name_to_code(_clean_name(r[name_col]))
            for c in year_cols:
                v = pd.to_numeric(str(r[c]).replace(",", ""), errors="coerce")
                if code and pd.notna(v) and _fy_start(c) <= 2025:
                    long.append({"state_code": code, "year": _fy_start(c), "gsdp_cr": v * 100})  # ₹bn -> ₹cr
    g = pd.DataFrame(long).groupby(["state_code", "year"], as_index=False)["gsdp_cr"].mean()
    # constant prices via national GDP deflator (rebased to 2011)
    defl = world_bank("NY.GDP.DEFL.ZS")
    defl = defl / defl.loc[2011]
    real = world_bank("NY.GDP.MKTP.KN")
    frames = []
    for code in STATE_CODES:
        s = g[g.state_code == code].set_index("year")["gsdp_cr"]
        idx = pd.Index(range(1990, 2026), name="year")
        f = pd.DataFrame(index=idx)
        f["gsdp_const_cr"] = (s / defl.reindex(s.index)).reindex(idx)
        f["gsdp_imputed"] = f["gsdp_const_cr"].isna().astype(int)
        if s.empty:
            f["state_code"] = code
            frames.append(f.reset_index())
            continue
        # backcast/forward-fill with national real growth (constant state share of GDP)
        first, last = f["gsdp_const_cr"].first_valid_index(), f["gsdp_const_cr"].last_valid_index()
        for y in idx:
            if y < first:
                f.loc[y, "gsdp_const_cr"] = f.loc[first, "gsdp_const_cr"] * real.get(y, np.nan) / real[first]
            elif y > last:
                f.loc[y, "gsdp_const_cr"] = f.loc[last, "gsdp_const_cr"] * real.get(y, np.nan) / real[last]
        f["gsdp_cr"] = f["gsdp_const_cr"] * defl.reindex(idx)
        f["state_code"] = code
        frames.append(f.reset_index())
    out = pd.concat(frames)
    log_imputation("gsdp_cr/gsdp_const_cr", "constant-share backcast with World Bank real GDP (NY.GDP.MKTP.KN)",
                   out.gsdp_imputed.sum(), "MoSPI 2011-12 series starts FY2011; earlier years assume constant state share")
    missing = out.groupby("state_code").gsdp_const_cr.apply(lambda s: s.isna().all())
    for c in missing[missing].index:
        log_imputation("gsdp_cr", "unavailable", 36, f"{c}: no MoSPI series (e.g. Ladakh/Lakshadweep/DNHDD)")
    return out


# ---- Population (Census 2001/2011 + 2023/2024 estimates) ------------------------------------------
def recent_anchors(p2011: float, growth: float | None, p2023: float | None, p2024: float | None) -> dict[int, float]:
    """2023/2024 population anchors. The source table sometimes carries contradictory figures (e.g. DNH&DD:
    2023 = 1.26 M, 2024 = 0.66 M). If the two differ by > 10 %, keep the one closer to the 2001–2011 trend."""
    a = {y: v for y, v in ((2023, p2023), (2024, p2024)) if v is not None and pd.notna(v) and v > 0}
    if len(a) == 2 and abs(np.log(a[2024] / a[2023])) > np.log(1.1):
        g = (1 + growth) ** 0.1 - 1 if growth is not None and pd.notna(growth) else 0.012
        a = {y: v for y, v in a.items() if y == min(a, key=lambda k: abs(np.log(a[k] / (p2011 * (1 + g) ** (k - 2011)))))}
    return a


def population() -> pd.DataFrame:
    t = _wiki_tables("List_of_states_and_union_territories_of_India_by_population")[1]
    t.columns = [" ".join(dict.fromkeys(map(str, c))) if isinstance(c, tuple) else str(c) for c in t.columns]
    col = lambda pat: next(c for c in t.columns if re.search(pat, c))  # noqa: E731
    num = lambda s: pd.to_numeric(s.astype(str).str.replace(r"\[.*?\]|,|%", "", regex=True), errors="coerce")  # noqa: E731
    df = pd.DataFrame({
        "state_code": t[col(r"^State")].map(lambda s: name_to_code(_clean_name(s))),
        "p2011": num(t[col(r"2011 Census Pop")]),
        "growth": num(t[col(r"Growth")]) / 100,
        "p2023": num(t[col(r"2023 Population")]),
        "p2024": num(t[col(r"Population \(2024\)")]),
        "urban": num(t[col(r"Urban pop.*Nos")]),
        "area": num(t[col(r"^Area")]),
    }).dropna(subset=["state_code"])
    df = df.groupby("state_code", as_index=False).sum(min_count=1)  # merges DNH + DD if listed separately
    rows = []
    for r in df.itertuples():
        anchors = {2011: r.p2011}
        if pd.notna(r.growth):
            anchors[2001] = r.p2011 / (1 + r.growth)
        anchors.update(recent_anchors(r.p2011, r.growth, r.p2023, r.p2024))
        ay = np.array(sorted(anchors))
        av = np.log([anchors[y] for y in ay])
        for y in range(1990, 2026):
            # log-linear interpolation; extrapolate with nearest segment's growth
            if len(ay) == 1:
                lv = av[0]
            else:
                i = int(np.clip(np.searchsorted(ay, y) - 1, 0, len(ay) - 2))
                lv = av[i] + (av[i + 1] - av[i]) * (y - ay[i]) / (ay[i + 1] - ay[i])
            rows.append({"state_code": r.state_code, "year": y, "population_mn": np.exp(lv) / 1e6,
                         "urban_population_pct": 100 * r.urban / r.p2011 if r.p2011 else np.nan,
                         "area_km2": r.area})
    out = pd.DataFrame(rows)
    out["population_density"] = out.population_mn * 1e6 / out.area_km2
    log_imputation("population_mn", "log-linear interpolation between Census 2001/2011 and 2023/2024 estimates",
                   len(out), "pre-2001 extrapolated with 2001-2011 growth")
    log_imputation("urban_population_pct", "held at Census 2011 value", len(out))
    return out


# ---- Climate (NASA POWER monthly, state representative point) --------------------------------------
def climate(points: pd.DataFrame, start: int = 1990, end: int = 2024) -> pd.DataFrame:
    rows = []
    for r in points.itertuples():
        url = (f"https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=T2M,PRECTOTCORR&community=AG"
               f"&longitude={r.lon:.3f}&latitude={r.lat:.3f}&start={start}&end={end}&format=JSON")
        js = json.loads(fetch(url, RAW / "climate" / f"{r.code}_{start}_{end}.json").read_text())
        p = js["properties"]["parameter"]
        for y in range(start, end + 1):
            t = [p["T2M"].get(f"{y}{m:02d}", -999) for m in range(1, 13)]
            pr = [p["PRECTOTCORR"].get(f"{y}{m:02d}", -999) for m in range(1, 13)]
            if min(t) <= -999:
                continue
            days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            rows.append({"state_code": r.code, "year": y, "avg_temp_c": float(np.mean(t)),
                         "cooling_degree_days": float(sum(max(tm - 18, 0) * d for tm, d in zip(t, days, strict=True))),
                         "heating_degree_days": float(sum(max(18 - tm, 0) * d for tm, d in zip(t, days, strict=True))),
                         "monsoon_rainfall_mm": float(sum(pr[m] * days[m] for m in range(5, 9)))})  # JJAS
    out = pd.DataFrame(rows)
    # drought year: JJAS rainfall < 80% of the state's 1990-2014 mean (train period only; no leakage)
    base = out[out.year <= 2014].groupby("state_code").monsoon_rainfall_mm.mean()
    out["drought_year"] = (out.monsoon_rainfall_mm < 0.8 * out.state_code.map(base)).astype(int)
    log_imputation("climate", "major-city point per state (not area-weighted); CDD from monthly means", len(out))
    return out


# ---- Policy / shocks ------------------------------------------------------------------------------
# State EV policy notification year (approximate, from state gazette notifications; verify before citing).
EV_POLICY_YEAR = {"IN-KA": 2017, "IN-MH": 2018, "IN-AP": 2018, "IN-UK": 2018, "IN-KL": 2019, "IN-TN": 2019,
                  "IN-UP": 2019, "IN-DL": 2020, "IN-TS": 2020, "IN-MP": 2019, "IN-PB": 2019, "IN-GJ": 2021,
                  "IN-RJ": 2019, "IN-WB": 2021, "IN-AS": 2021, "IN-OD": 2021, "IN-BR": 2019, "IN-HR": 2022,
                  "IN-MN": 2022, "IN-ML": 2021, "IN-GA": 2021, "IN-CH": 2022, "IN-HP": 2022, "IN-JH": 2022}


def oxcgrt() -> pd.DataFrame:
    p = fetch("https://raw.githubusercontent.com/OxCGRT/covid-policy-dataset/main/data/OxCGRT_compact_subnational_v1.csv",
              RAW / "oxcgrt" / "subnational.csv")
    d = pd.read_csv(p, usecols=["CountryCode", "RegionName", "Date", "StringencyIndex_Average"], low_memory=False)
    d = d[d.CountryCode == "IND"].dropna(subset=["RegionName"])
    d["state_code"] = d.RegionName.map(name_to_code)
    d["year"] = d.Date // 10000
    return d.groupby(["state_code", "year"], as_index=False).StringencyIndex_Average.mean().rename(
        columns={"StringencyIndex_Average": "lockdown_stringency"})


def policy_frame() -> pd.DataFrame:
    idx = pd.MultiIndex.from_product([STATE_CODES, range(1990, 2026)], names=["state_code", "year"]).to_frame(index=False)
    y = idx.year
    idx["covid_dummy"] = y.isin([2020, 2021]).astype(int)
    idx["ujala_led_dummy"] = (y >= 2015).astype(int)          # UJALA launched Jan 2015
    idx["pat_scheme_dummy"] = (y >= 2012).astype(int)         # PAT cycle I began FY2012-13
    idx["renewable_target_dummy"] = (y >= 2015).astype(int)   # 175 GW target announced 2015
    idx["nsm_phase"] = np.select([y < 2010, y < 2013, y < 2017, y < 2022], [0, 1, 2, 3], 4)  # JNNSM phases
    idx["ndc_phase"] = np.select([y < 2015, y < 2022], [0, 1], 2)  # INDC/first NDC (2015), updated NDC (Aug 2022)
    idx["ev_policy_dummy"] = [int(yr >= EV_POLICY_YEAR.get(c, 9999)) for c, yr in zip(idx.state_code, y, strict=True)]
    try:
        idx = idx.merge(oxcgrt(), on=["state_code", "year"], how="left")
    except Exception as e:  # noqa: BLE001
        print(f"  [policy] OxCGRT unavailable: {e}")
        idx["lockdown_stringency"] = np.nan
    idx["lockdown_stringency"] = idx.lockdown_stringency.fillna(0.0)  # 0 outside 2020-22 by definition
    return idx


# ---- PPAC state-wise petroleum sales (FY2008-09 onwards, '000 t) ----------------------------------------
PPAC_URL = "https://ppac.gov.in/uploads/page-images/1787137273_Statewise_Sales-POL_Consumption_Final.xlsx"
PPAC_SHEETS = {"PT_Cons_Statewise": "pol_sales_kt", "PT_Cons_Statewise MS": "petrol_sales_kt", "PT_Cons_Statewise HSD": "diesel_sales_kt"}


def ppac_sales() -> pd.DataFrame:
    """State x year petrol (MS), diesel (HSD) and all-product sales in thousand tonnes (PPAC). FY t-(t+1) -> year t."""
    path = fetch(PPAC_URL, RAW / "ppac" / "statewise_sales.xlsx")
    out = None
    for sheet, col in PPAC_SHEETS.items():
        raw = pd.read_excel(path, sheet, header=None)
        hdr = next(i for i in range(len(raw)) if str(raw.iloc[i, 0]).strip().upper().startswith("STATE"))
        years = {j: _fy_start(v) for j, v in enumerate(raw.iloc[hdr]) if _fy_start(v)}
        rows = []
        for _, r in raw.iloc[hdr + 1:].iterrows():
            code = name_to_code(_clean_name(r.iloc[0]))
            if not code:
                continue
            rows += [{"state_code": code, "year": y, col: pd.to_numeric(r.iloc[j], errors="coerce")} for j, y in years.items()]
        df = pd.DataFrame(rows).groupby(["state_code", "year"], as_index=False).sum(min_count=1)
        out = df if out is None else out.merge(df, on=["state_code", "year"], how="outer")
    log_imputation("petrol/diesel/pol_sales_kt", "unavailable before FY2008 (PPAC series start)", 0, "missing-indicator columns added")
    return out


# ---- Optional manual RBI Handbook of Statistics on Indian States drops -----------------------------
# rbidocs.rbi.org.in serves a CAPTCHA to scripts, so these cannot be auto-downloaded.
# Download the XLSX in a browser and save to data/manual/rbi/<feature>.xlsx using these names:
RBI_FILES = {
    "industry_gsva_cr": "Table 41 GSVA Industry (current)", "manufacturing_gsva_cr": "Table 33 GSVA Manufacturing (current)",
    "construction_gsva_cr": "Table 37 GSVA Construction (current)", "installed_capacity_mw": "Table 140",
    "renewable_capacity_mw": "Table 143", "electricity_consumption_gwh": "Table 139 Availability of Power (MU=GWh)",
    "per_capita_electricity_kwh": "Table 138", "tnd_losses_pct": "Table 148", "highway_length_km": "Table 144",
    # v2 sector drivers available in the same handbook
    "fertiliser_consumption_kt": "Table 89 Fertiliser (N+P+K)", "rice_production_kt": "Table 58",
    "wheat_production_kt": "Table 59", "gross_sown_area_kha": "Table 53",
}

# Other official sources with no scriptable free download (login walls / PDFs). Drop a CSV with columns
# state,year,<feature> into data/manual/extra/<feature>.csv and it is merged on (state_code, year).
MANUAL_EXTRA = {
    "vehicles_total": "MoRTH Road Transport Year Book (registered vehicles)", "vehicles_2w": "MoRTH (two-wheelers)",
    "vehicles_car": "MoRTH (cars/jeeps/taxis)", "vehicles_goods": "MoRTH (goods vehicles)",
    "diesel_sales_kt": "PPAC state-wise HSD sales", "petrol_sales_kt": "PPAC state-wise MS sales",
    "rail_freight_mt": "Indian Railways Year Book", "air_passengers_mn": "AAI/DGCA traffic statistics",
    "cattle_mn": "20th Livestock Census", "buffalo_mn": "20th Livestock Census", "msw_tpd": "CPCB/MoHUA SBM MSW generation",
    "lpg_households_pct": "PPAC/PMUY LPG coverage", "households_mn": "Census 2011 households", "nightlights_radiance": "VIIRS (EOG, login)",
}


def manual_extra(folder: Path = ROOT / "data" / "manual" / "extra") -> pd.DataFrame:
    out = pd.DataFrame(columns=["state_code", "year"])
    for p in sorted(folder.glob("*.csv")) if folder.exists() else []:
        d = pd.read_csv(p)
        d["state_code"] = d.pop("state").map(lambda x: name_to_code(str(x)) or (x if str(x).startswith("IN-") else None))
        d = d.dropna(subset=["state_code"]).groupby(["state_code", "year"], as_index=False).mean(numeric_only=True)
        out = d if out.empty else out.merge(d, on=["state_code", "year"], how="outer")
        print(f"  [manual] {p.name}: {len(d)} rows")
    return out


def rbi_manual(folder: Path = ROOT / "data" / "manual" / "rbi") -> pd.DataFrame:
    """Parse RBI state tables (states in rows, FY columns). Returns long->wide on (state_code, year)."""
    out = None
    for feat in RBI_FILES:
        p = folder / f"{feat}.xlsx"
        if not p.exists():
            continue
        raw = pd.read_excel(p, header=None)
        hdr = next(i for i in range(len(raw)) if sum(_fy_start(v) is not None for v in raw.iloc[i]) >= 2)
        cols = raw.iloc[hdr]
        rows = []
        for _, r in raw.iloc[hdr + 1:].iterrows():
            code = next((name_to_code(_clean_name(v)) for v in r if isinstance(v, str) and name_to_code(_clean_name(v))), None)
            if not code:
                continue
            for j, c in enumerate(cols):
                if _fy_start(c):
                    rows.append({"state_code": code, "year": _fy_start(c), feat: pd.to_numeric(r.iloc[j], errors="coerce")})
        df = pd.DataFrame(rows).groupby(["state_code", "year"], as_index=False).mean()
        out = df if out is None else out.merge(df, on=["state_code", "year"], how="outer")
        print(f"  [rbi] parsed {feat}: {len(df)} rows")
    return out if out is not None else pd.DataFrame(columns=["state_code", "year"])
