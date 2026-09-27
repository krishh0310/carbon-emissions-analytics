"""ATAR — deterministic insight engine (templates + statistics; no LLM).

Every insight carries:
  evidence  the numbers behind it (auditable)
  viz       a chart spec + the exact series the UI plots (kind: deviation | dual_index | corridor | ranking | bars | spark | waterfall)
  how       formula (readable notation), inputs, data source, freshness date  → the card's "How is this calculated?" footer
  title_hi / body_hi   Hindi text (numbers identical to the English)
Types: ANOMALY, DECOUPLING, WATCHLIST, LEADER, LAGGARD, DRIVERS, COMPARISON, TREND.  Severity: alert > warning > notice > info.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from src.data.cache import PROCESSED, ROOT
from src.data.reference import NAME_HI, states_df
from src.data.sectors import SECTORS

RES = ROOT / "results"
NAME = states_df().set_index("code").name.to_dict()
LOW = {s: s.lower() for s in SECTORS}
SEC_HI = {"POWER": "बिजली", "TRANSPORT": "परिवहन", "INDUSTRY": "उद्योग", "BUILDINGS": "भवन", "AGRICULTURE": "कृषि",
          "WASTE": "अपशिष्ट", "OTHER": "अन्य"}
TODAY = time.strftime("%Y-%m-%d")
SRC_EDGAR = "EDGAR 2025 sector grids, downscaled to states (CO₂e, AR6 GWP-100)"


def poss(code: str) -> str:
    n = NAME[code]
    return f"{n}'" if n.endswith("s") else f"{n}'s"


def hi(code: str | None) -> str:
    return NAME_HI.get(code, NAME.get(code, "भारत")) if code else "भारत"


def _mt(x: float) -> str:
    return f"{x:,.1f} Mt" if abs(x) >= 1 else f"{x * 1000:,.0f} kt"


def _r(x, d=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


def _item(state, sector, typ, sev, title, body, ev, viz, how, title_hi, body_hi) -> dict:
    return {"state_code": state, "sector": sector, "type": typ, "severity": sev, "title": title, "body": body,
            "title_hi": title_hi, "body_hi": body_hi,
            "evidence": {k: (_r(v) if isinstance(v, float) else v) for k, v in ev.items()},
            "viz": viz, "how": {"updated": TODAY, **how},
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def anomalies(sec: pd.DataFrame, last: int) -> list[dict]:
    """Latest-year growth vs the trailing 5-year growth distribution of the same state × sector."""
    out, cand = [], []
    for (c, s), g in sec.groupby(["state_code", "sector"]):
        v = g.set_index("year").co2e_mt
        if v.get(last, 0) < 1.0 or last - 6 not in v.index:
            continue
        gr = v.pct_change(fill_method=None) * 100
        hist = gr.loc[last - 5: last - 1]
        z = (gr[last] - hist.mean()) / max(hist.std(), 1.0)
        cand.append((abs(z), c, s, gr[last], hist.mean(), z, v[last], gr.loc[last - 7: last]))
    cand.sort(key=lambda x: -x[0])
    for az, c, s, g, mu, z, lvl, series in cand:
        if az < 2:
            break
        peers = [x for x in cand if x[2] == s and x[0] >= 2]
        largest = bool(peers and peers[0][1] == c)
        word, word_hi = ("jumped", "उछला") if g > 0 else ("fell", "गिरा")
        out.append(_item(
            c, s, "ANOMALY", "warning" if az >= 3 else "notice",
            f"{NAME[c]} {LOW[s]} emissions {word} {abs(g):.0f}% in {last}",
            f"{poss(c)} {LOW[s]} CO₂e {word} {abs(g):.1f}% in {last} against a 5-year average of {mu:+.1f}%/yr "
            f"(z = {z:+.1f}){' — the largest ' + LOW[s] + ' deviation of any state' if largest else ''}.",
            {"year": last, "growth_pct": g, "trend_growth_pct": mu, "z": z, "level_mt": lvl},
            {"kind": "deviation", "unit": "% growth y/y", "trend": _r(mu, 2), "z": _r(z, 2),
             "series": [{"year": int(y), "value": _r(v, 2), "is_latest": int(y) == last} for y, v in series.items() if pd.notna(v)]},
            {"formula": "z = (growth_latest − mean(growth over prior 5 yrs)) ÷ max(sd(growth over prior 5 yrs), 1 pp); "
                        "growth = CO₂e_t ÷ CO₂e_(t−1) − 1",
             "inputs": f"{NAME[c]} {LOW[s]} CO₂e {last - 6}–{last}; flagged when |z| ≥ 2 (≥ 3 = warning); sector ≥ 1 Mt",
             "source": SRC_EDGAR},
            f"{hi(c)}: {SEC_HI[s]} उत्सर्जन {last} में {abs(g):.0f}% {word_hi}",
            f"{hi(c)} का {SEC_HI[s]} CO₂e {last} में {abs(g):.1f}% {word_hi}, जबकि पिछले 5 वर्षों का औसत {mu:+.1f}% प्रति वर्ष था (z = {z:+.1f})।"))
    return out[:40]


def decoupling(sec: pd.DataFrame, st: pd.DataFrame, last: int) -> list[dict]:
    out = []
    gdp = st.set_index(["state_code", "year"]).gsdp_const_cr
    imputed = st.set_index(["state_code", "year"]).gsdp_imputed
    for (c, s), g in sec[sec.sector.isin(["POWER", "INDUSTRY", "TRANSPORT"])].groupby(["state_code", "sector"]):
        v = g.set_index("year").co2e_mt
        if v.get(last, 0) < 2:
            continue
        run = 0
        for y in range(last, last - 10, -1):
            if (c, y) not in gdp.index or (c, y - 1) not in gdp.index or imputed.get((c, y), 1):
                break
            if gdp[(c, y)] > gdp[(c, y - 1)] and v.get(y, np.nan) < v.get(y - 1, np.nan):
                run += 1
            else:
                break
        if run >= 2:
            y0 = last - run
            gg = 100 * (gdp[(c, last)] / gdp[(c, y0)] - 1)
            eg = 100 * (v[last] / v[y0] - 1)
            base_y = max(y0 - 3, int(v.index.min()))
            series = [{"year": y, "gsdp": _r(100 * gdp[(c, y)] / gdp[(c, base_y)], 2), "co2e": _r(100 * v[y] / v[base_y], 2)}
                      for y in range(base_y, last + 1) if (c, y) in gdp.index and y in v.index]
            out.append(_item(
                c, s, "DECOUPLING", "info", f"{NAME[c]}: {LOW[s]} decoupling for {run} straight years",
                f"{poss(c)} real GSDP grew {gg:.0f}% over {y0}–{last} while {LOW[s]} CO₂e fell {abs(eg):.0f}% — "
                f"{run} consecutive years of absolute decoupling.",
                {"years": run, "gsdp_growth_pct": gg, "co2e_change_pct": eg, "from": y0, "to": last},
                {"kind": "dual_index", "unit": f"index, {base_y} = 100", "base_year": base_y, "highlight_from": y0, "series": series},
                {"formula": "Absolute decoupling year: GSDP_t > GSDP_(t−1) AND CO₂e_t < CO₂e_(t−1); streak counted back from the latest year. "
                            f"Index_t = value_t ÷ value_{base_y} × 100",
                 "inputs": f"Real GSDP (2011-12 ₹, MoSPI; imputed years excluded) and {LOW[s]} CO₂e", "source": f"{SRC_EDGAR} · MoSPI GSDP"},
                f"{hi(c)}: लगातार {run} वर्षों से {SEC_HI[s]} डीकपलिंग",
                f"{y0}–{last} में {hi(c)} का वास्तविक GSDP {gg:.0f}% बढ़ा जबकि {SEC_HI[s]} CO₂e {abs(eg):.0f}% घटा — लगातार {run} वर्ष पूर्ण डीकपलिंग।"))
    return sorted(out, key=lambda i: -i["evidence"]["years"])


def watchlist(sec: pd.DataFrame, st: pd.DataFrame, fc: pd.DataFrame, last: int) -> list[dict]:
    if fc.empty:
        return []
    end = int(fc.year.max())
    fc = fc.assign(v=fc.p50_reconciled.fillna(fc.p50))
    now = sec[sec.year == last].groupby("state_code").co2e_mt.sum()
    path = fc.groupby(["state_code", "year"])[["v", "p10", "p90"]].sum()
    fut = path.xs(end, level="year").v
    pop = st[st.year == last].set_index("state_code").population_mn
    n = end - last
    nat_cagr = 100 * ((fut.sum() / now.sum()) ** (1 / n) - 1)
    nat_pc = now.sum() / pop.sum()
    out = []
    for c in fut.index:
        if now.get(c, 0) < 5 or pop.get(c, 0) < 2:  # material emitters; tiny UTs have per-capita artefacts
            continue
        cagr = 100 * ((fut[c] / now[c]) ** (1 / n) - 1)
        fair = nat_cagr * min(nat_pc / (now[c] / pop[c]), 2.0)
        excess_path = 100 * (fut[c] / (now[c] * (1 + fair / 100) ** n) - 1)
        if cagr <= fair or excess_path < 1:  # below 1 % is within rounding noise
            continue
        contrib = (fc[(fc.state_code == c) & (fc.year == end)].set_index("sector").v
                   - sec[(sec.state_code == c) & (sec.year == last)].set_index("sector").co2e_mt).sort_values(ascending=False)
        top = [s for s in contrib.index[:2] if contrib[s] > 0]
        hist = sec[(sec.state_code == c) & (sec.year >= last - 6)].groupby("year").co2e_mt.sum()
        series = [{"year": int(y), "observed": _r(v, 3)} for y, v in hist.items()]
        series[-1].update({"forecast": _r(now[c], 3), "fair": _r(now[c], 3), "fair_hi": _r(now[c], 3), "band": [_r(now[c], 3), _r(now[c], 3)]})
        for y in range(last + 1, end + 1):
            p = path.loc[(c, y)]
            series.append({"year": y, "forecast": _r(p.v, 3), "band": [_r(p.p10, 3), _r(p.p90, 3)],
                           "fair": _r(now[c] * (1 + fair / 100) ** (y - last), 3),
                           "fair_hi": _r(now[c] * (1 + max(fair, nat_cagr) / 100) ** (y - last), 3)})
        out.append(_item(
            c, None, "WATCHLIST", "alert" if excess_path > 10 else "warning",
            f"{NAME[c]} forecast exceeds fair-share path by {excess_path:.0f}%",
            f"{poss(c)} {end} forecast ({_mt(fut[c])} CO₂e, {cagr:+.1f}%/yr) exceeds its fair-share trajectory "
            f"({fair:+.1f}%/yr) by {excess_path:.0f}%" + (f" — driven by {' + '.join(LOW[s] for s in top)}." if top else "."),
            {"forecast_mt": float(fut[c]), "now_mt": float(now[c]), "cagr_pct": cagr, "fair_cagr_pct": fair, "national_cagr_pct": nat_cagr,
             "excess_pct": excess_path, "drivers": {s: _r(contrib[s], 3) for s in contrib.index[:3]}},
            {"kind": "corridor", "unit": "MtCO₂e", "series": series,
             "labels": {"fair": f"fair-share path ({fair:+.1f}%/yr)", "fair_hi": f"national pace ({nat_cagr:+.1f}%/yr)"}},
            {"formula": "Fair-share CAGR = national forecast CAGR × min(national per-capita CO₂e ÷ state per-capita CO₂e, 2); "
                        f"excess = forecast_{end} ÷ (CO₂e_{last} × (1 + fair CAGR)^{n}) − 1",
             "inputs": f"State & national CO₂e {last}; population {last}; reconciled P50 forecast {end}; national CAGR {nat_cagr:+.2f}%/yr",
             "source": f"{SRC_EDGAR} · CarbonScope Forecast (P50, 5-yr) · Census/MoSPI population"},
            f"{hi(c)} का पूर्वानुमान उचित-हिस्सा पथ से {excess_path:.0f}% अधिक",
            f"{hi(c)} का {end} पूर्वानुमान ({_mt(fut[c])} CO₂e, {cagr:+.1f}% प्रति वर्ष) उसके उचित-हिस्सा पथ ({fair:+.1f}% प्रति वर्ष) से {excess_path:.0f}% अधिक है"
            + (f" — मुख्यतः {' + '.join(SEC_HI[s] for s in top)} के कारण।" if top else "।")))
    return sorted(out, key=lambda i: -i["evidence"]["excess_pct"])


def leaders(sec: pd.DataFrame, st: pd.DataFrame, last: int) -> list[dict]:
    out = []
    s = st[st.year == last].set_index("state_code")
    x = sec[sec.year == last].pivot_table(index="state_code", columns="sector", values="co2e_mt")
    big = s.gsdp_const_cr[~s.gsdp_imputed.astype(bool)]
    big = big[big >= big.quantile(2 / 3)].index
    for sector, denom, unit, label, lab_hi, formula in (
            ("INDUSTRY", s.gsdp_const_cr / 1e5, "MtCO₂e per ₹ lakh crore", "industrial emissions intensity", "औद्योगिक उत्सर्जन तीव्रता",
             "Industrial intensity = industry CO₂e (Mt) ÷ real GSDP (₹ lakh crore, 2011-12 prices)"),
            ("TRANSPORT", s.population_mn, "tCO₂e per person", "per-capita transport emissions", "प्रति व्यक्ति परिवहन उत्सर्जन",
             "Per-capita transport = transport CO₂e (t) ÷ population"),
            ("AGRICULTURE", s.gsdp_const_cr / 1e5, "MtCO₂e per ₹ lakh crore", "agricultural emissions intensity", "कृषि उत्सर्जन तीव्रता",
             "Agricultural intensity = agriculture CO₂e (Mt) ÷ real GSDP (₹ lakh crore)")):
        r = (x[sector] / denom).dropna()
        r = r[(x[sector].reindex(r.index) >= 1) & (s.population_mn.reindex(r.index) >= 2)]  # material states only
        if r.empty:
            continue
        hi_c, lo = r.idxmax(), r.reindex(big).dropna().idxmin()
        ranking = [{"state_code": k, "value": _r(v, 4)} for k, v in r.sort_values(ascending=False).items()]
        how = {"formula": formula, "inputs": f"{last}; states with ≥ 1 Mt in the sector and ≥ 2 M people; 'high-GSDP' = top third by real GSDP",
               "source": f"{SRC_EDGAR} · MoSPI GSDP · Census population"}
        for code, typ, sev, title, body, t_hi, b_hi in (
                (hi_c, "LEADER", "notice", f"{NAME[hi_c]} has India's highest {label}",
                 f"{NAME[hi_c]} leads all states on {label} ({r[hi_c]:.2f} {unit}); {NAME[lo]} is lowest among high-GSDP states ({r[lo]:.2f}).",
                 f"{hi(hi_c)}: भारत में सर्वाधिक {lab_hi}", f"{hi(hi_c)} {lab_hi} में सभी राज्यों में सबसे आगे है ({r[hi_c]:.2f} {unit}); उच्च-GSDP राज्यों में {hi(lo)} सबसे कम ({r[lo]:.2f})।"),
                (lo, "LAGGARD", "info", f"{NAME[lo]}: lowest {label} among high-GSDP states",
                 f"{NAME[lo]} records {r[lo]:.2f} {unit} vs India-high {NAME[hi_c]} at {r[hi_c]:.2f} ({last}).",
                 f"{hi(lo)}: उच्च-GSDP राज्यों में न्यूनतम {lab_hi}", f"{hi(lo)}: {r[lo]:.2f} {unit}, जबकि सर्वाधिक {hi(hi_c)} {r[hi_c]:.2f} ({last})।")):
            out.append(_item(code, sector, typ, sev, title, body,
                             {"metric": label, "value": float(r[code]), "highest": hi_c, "lowest_high_gsdp": lo, "year": last},
                             {"kind": "ranking", "unit": unit, "highlight": code, "series": ranking}, how, t_hi, b_hi))
    return out


def drivers(sec: pd.DataFrame, fc: pd.DataFrame, last: int) -> list[dict]:
    if fc.empty:
        return []
    end = int(fc.year.max())
    fc = fc.assign(v=fc.p50_reconciled.fillna(fc.p50))
    out = []
    for c, g in fc[fc.year == end].groupby("state_code"):
        base = sec[(sec.state_code == c) & (sec.year == last)].set_index("sector").co2e_mt
        d = (g.set_index("sector").v - base).dropna()
        if base.sum() < 1:
            continue
        top3 = d.reindex(d.abs().sort_values(ascending=False).index)[:3]
        parts = [f"{LOW[s]} ({'+' if v >= 0 else '−'}{_mt(abs(v))})" for s, v in top3.items()]
        parts_hi = [f"{SEC_HI[s]} ({'+' if v >= 0 else '−'}{_mt(abs(v))})" for s, v in top3.items()]
        lead = top3.index[0]
        wf = [{"name": f"{last}", "value": _r(base.sum(), 3), "total": True}]
        wf += [{"name": s, "value": _r(d[s], 3)} for s in SECTORS if s in d.index]
        wf += [{"name": f"{end}", "value": _r(g.v.sum(), 3), "total": True}]
        out.append(_item(
            c, lead, "DRIVERS", "info", f"What drives {poss(c)} forecast",
            f"Top 3 sector drivers of {poss(c)} {last}→{end} forecast change: " + ", ".join(parts) + ".",
            {"changes_mt": {s: _r(v, 3) for s, v in top3.items()}, "from": last, "to": end},
            {"kind": "waterfall", "unit": "MtCO₂e", "series": wf},
            {"formula": f"Δ_sector = forecast P50_{end} (reconciled) − observed CO₂e_{last}; ranked by |Δ|",
             "inputs": "Reconciled state × sector forecast; observed sector CO₂e", "source": f"{SRC_EDGAR} · CarbonScope Forecast (P50)"},
            f"{hi(c)} के पूर्वानुमान के मुख्य कारक", f"{last}→{end} के बीच {hi(c)} के पूर्वानुमान परिवर्तन के शीर्ष 3 क्षेत्र: " + ", ".join(parts_hi) + "।"))
    return out


def comparisons(sec: pd.DataFrame, st: pd.DataFrame, last: int) -> list[dict]:
    tot = sec[sec.year == last].groupby("state_code").co2e_mt.sum()
    pop = st[st.year == last].set_index("state_code").population_mn
    pc = (tot / pop).dropna()
    big = pc[pop.reindex(pc.index) >= 20]
    nat = tot.sum() / pop.sum()
    how = {"formula": "Per-capita CO₂e = state CO₂e (t) ÷ population; India average = Σ CO₂e ÷ Σ population",
           "inputs": f"{last}; comparisons limited to states with ≥ 2 M people (≥ 20 M for the low end)", "source": f"{SRC_EDGAR} · Census/MoSPI population"}
    out = []
    lo, hi_c = big.idxmin(), pc[pop.reindex(pc.index) >= 2].idxmax()
    ratio = pc[hi_c] / pc[lo]
    out.append(_item(lo, None, "COMPARISON", "info", f"{NAME[lo]} vs {NAME[hi_c]}: {ratio:.0f}× per-capita gap",
                     f"{poss(lo)} per-capita CO₂e is {pc[lo]:.2f} t — about 1/{ratio:.0f} of {poss(hi_c)} {pc[hi_c]:.1f} t (India average {nat:.2f} t, {last}).",
                     {"low": lo, "low_t": float(pc[lo]), "high": hi_c, "high_t": float(pc[hi_c]), "national_t": float(nat)},
                     {"kind": "bars", "unit": "tCO₂e per person", "series": [{"name": NAME[lo], "value": _r(pc[lo], 3), "state_code": lo},
                                                                          {"name": "India", "value": _r(nat, 3)},
                                                                          {"name": NAME[hi_c], "value": _r(pc[hi_c], 3), "state_code": hi_c}]},
                     how, f"{hi(lo)} बनाम {hi(hi_c)}: प्रति व्यक्ति {ratio:.0f}× अंतर",
                     f"{hi(lo)} का प्रति व्यक्ति CO₂e {pc[lo]:.2f} t है — {hi(hi_c)} ({pc[hi_c]:.1f} t) का लगभग 1/{ratio:.0f} (भारत औसत {nat:.2f} t, {last})।"))
    for c, v in pc.items():
        r = v / nat
        if (r >= 2 or r <= 0.5) and pop.get(c, 0) >= 5:
            out.append(_item(c, None, "COMPARISON", "info", f"{NAME[c]} per-capita CO₂e is {r:.1f}× the national average",
                             f"{NAME[c]}: {v:.2f} tCO₂e per person vs India {nat:.2f} t ({last}).",
                             {"per_capita_t": float(v), "national_t": float(nat), "ratio": float(r)},
                             {"kind": "bars", "unit": "tCO₂e per person", "series": [{"name": NAME[c], "value": _r(v, 3), "state_code": c},
                                                                                  {"name": "India", "value": _r(nat, 3)}]},
                             how, f"{hi(c)} का प्रति व्यक्ति CO₂e राष्ट्रीय औसत का {r:.1f}×",
                             f"{hi(c)}: {v:.2f} tCO₂e प्रति व्यक्ति, जबकि भारत {nat:.2f} t ({last})।"))
    return out


def trends(sec: pd.DataFrame, st: pd.DataFrame, last: int) -> list[dict]:
    out = []
    nat = sec.groupby(["year", "sector"]).co2e_mt.sum().unstack()
    gdp = st.groupby("year").gsdp_const_cr.sum()
    for s in ("POWER", "INDUSTRY", "TRANSPORT"):
        inten = (nat[s] * 1e6 / gdp).loc[2005:last]
        i15, il = inten[2015], inten[last]
        ch = 100 * (il / i15 - 1)
        cagr = 100 * ((il / i15) ** (1 / (last - 2015)) - 1)
        out.append(_item(None, s, "TREND", "info", f"National {LOW[s]} emissions intensity {ch:+.0f}% since 2015",
                         f"India's {LOW[s]} CO₂e per unit of real GDP changed {ch:+.1f}% between 2015 and {last} "
                         f"({cagr:+.1f}%/yr, {'decoupling' if ch < 0 else 'intensifying'}).",
                         {"from": 2015, "to": last, "intensity_change_pct": float(ch), "cagr_pct": float(cagr)},
                         {"kind": "spark", "unit": "tCO₂e per ₹ crore real GDP", "cagr": _r(cagr, 2), "from": 2015,
                          "series": [{"year": int(y), "value": _r(v, 3)} for y, v in inten.items()]},
                         {"formula": "Intensity_t = Σ_states sector CO₂e_t ÷ Σ_states real GSDP_t; CAGR = (I_end ÷ I_2015)^(1/n) − 1",
                          "inputs": f"National totals 2005–{last}", "source": f"{SRC_EDGAR} · MoSPI GSDP"},
                         f"राष्ट्रीय {SEC_HI[s]} उत्सर्जन तीव्रता 2015 से {ch:+.0f}%",
                         f"2015 से {last} के बीच भारत की {SEC_HI[s]} CO₂e प्रति इकाई वास्तविक GDP {ch:+.1f}% बदली ({cagr:+.1f}% प्रति वर्ष)।"))
    cea = st[st.cea_available == 1]
    if len(cea):
        ef = cea.groupby("year").apply(lambda g: (g.cea_power_co2_mt.sum() * 1e6) /
                                       (g.filter(like="_generation_gwh").sum().sum() * 1e3), include_groups=False)
        a, b = int(ef.index.min()), int(ef.index.max())
        ch = 100 * (ef[b] / ef[a] - 1)
        cagr = 100 * ((ef[b] / ef[a]) ** (1 / max(b - a, 1)) - 1)
        out.append(_item(None, "POWER", "TREND", "info", f"Grid emission factor {ch:+.0f}% since FY{a}",
                         f"CEA plant data: the conventional fleet's average emission factor moved from {ef[a]:.3f} to {ef[b]:.3f} tCO₂/MWh "
                         f"(FY{a}→FY{b}). Solar/wind are outside the CEA baseline database, so this understates the all-source decline.",
                         {"from": a, "to": b, "ef_from": float(ef[a]), "ef_to": float(ef[b])},
                         {"kind": "spark", "unit": "tCO₂/MWh (conventional grid plants)", "cagr": _r(cagr, 2), "from": a,
                          "series": [{"year": int(y), "value": _r(v, 4)} for y, v in ef.items()]},
                         {"formula": "GEF_t = Σ plant CO₂_t ÷ Σ plant net generation_t (grid-connected coal, gas, oil, hydro, nuclear)",
                          "inputs": f"CEA CO₂ Baseline Database v22, FY{a}–FY{b} (FY t–t+1 → year t)", "source": "CEA CO₂ Baseline Database"},
                         f"ग्रिड उत्सर्जन कारक FY{a} से {ch:+.0f}%",
                         f"CEA संयंत्र आंकड़े: पारंपरिक बिजली संयंत्रों का औसत उत्सर्जन कारक {ef[a]:.3f} से {ef[b]:.3f} tCO₂/MWh (FY{a}→FY{b})।"))
    return out


def generate(model: str | None = None) -> list[dict]:
    from src.champion import best

    model = model or best("state_sector")
    sec = pd.read_parquet(PROCESSED / "india_states_sector_panel.parquet")
    st = pd.read_parquet(PROCESSED / "india_states_panel.parquet")
    fp = RES / "forecasts_sector.parquet"
    fc = pd.read_parquet(fp) if fp.exists() else pd.DataFrame()
    if len(fc):
        fc = fc[fc.model == model]
    last = int(sec.year.max())
    items = (watchlist(sec, st, fc, last) + anomalies(sec, last) + decoupling(sec, st, last) + leaders(sec, st, last)
             + drivers(sec, fc, last) + comparisons(sec, st, last) + trends(sec, st, last))
    order = {"alert": 0, "warning": 1, "notice": 2, "info": 3}
    return sorted(items, key=lambda i: order[i["severity"]])


def save(items: list[dict]) -> None:
    (RES / "atar_insights.json").write_text(json.dumps(items, indent=1, default=float, ensure_ascii=False))
