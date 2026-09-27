// Methodology: data sources (URL + license), full formula sheet, data gaps, monsoon rationale, searchable glossary.
import { useMemo, useState } from "react";
import { BookOpen, Calculator, Database, Search } from "lucide-react";
import { Card, Input } from "../components/ui";
import { GLOSSARY, glossify } from "../lib/glossary";

const F = ({ name, f, notes }: { name: string; f: string; notes?: string }) => (
  <div className="rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-white/[0.02] p-3">
    <div className="text-sm font-semibold">{glossify(name)}</div>
    <div className="mt-1.5 overflow-x-auto rounded-md bg-slate-100 dark:bg-black/30 px-2.5 py-2 font-mono text-[12px] text-emerald-800 dark:text-emerald-200">{f}</div>
    {notes && <p className="mt-1.5 text-xs leading-relaxed text-slate-600 dark:text-slate-400">{glossify(notes)}</p>}
  </div>
);

const SOURCES: [string, string, string, string, string][] = [
  ["EDGAR 2025 GHG (EU JRC)", "https://edgar.jrc.ec.europa.eu/dataset_ghg2025", "CO₂/CH₄/N₂O 0.1° sector grids, 1990–2024 — state & city emissions backbone", "CC BY 4.0 (cite JRC)", "all emission layers"],
  ["CEA CO₂ Baseline Database v22", "https://cea.nic.in/cdm-co2-baseline-database/", "Plant-level net generation & CO₂, FY2017–FY2025", "Government of India open data", "power calibration, GEF, generation mix"],
  ["MoSPI GSDP (via Wikipedia mirror of MoSPI tables)", "https://mospi.gov.in", "Real & nominal GSDP 2011-12 series", "GODL-India", "carbon intensity, decoupling"],
  ["Census 2001/2011 + 2023/24 estimates", "https://censusindia.gov.in", "State population, urban share; UA population for cities", "GODL-India", "per-capita values"],
  ["World Bank WDI", "https://data.worldbank.org", "India real GDP & deflator (GSDP back-cast, constant prices)", "CC BY 4.0", "GSDP pre-2011"],
  ["NASA POWER (monthly)", "https://power.larc.nasa.gov", "Temperature, precipitation → CDD/HDD, JJAS monsoon, drought flag", "Public domain (NASA)", "climate layers & drivers"],
  ["OxCGRT subnational", "https://github.com/OxCGRT/covid-policy-dataset", "Lockdown stringency 2020–22", "CC BY 4.0", "COVID shock feature"],
  ["Boundaries: datta07/INDIAN-SHAPEFILES", "https://github.com/datta07/INDIAN-SHAPEFILES", "36 state/UT polygons incl. Ladakh", "Open (repository licence)", "maps, grid→state allocation"],
];

const GAPS = [
  ["GHG Platform India state inventories", "Downloads are form-gated; validation layer shows 'n/a' until a CSV is placed in data/manual/extra."],
  ["PPAC state fuel sales", "Published as PDF/XLS behind dynamic pages; drop-in CSV slot `diesel_sales_kt`, `petrol_sales_kt`, `lpg_sales_kt`."],
  ["VAHAN EV registrations", "Dashboard is JavaScript-only (no open API); drop-in CSV slot `ev_registrations`."],
  ["Indian Railways freight, DGCA airport traffic", "Year-book PDFs; drop-in CSV slots `rail_freight_mt`, `air_passengers_mn`."],
  ["VIIRS nightlights", "Annual composites require an EOG login; drop-in CSV slot `nightlights_radiance`."],
  ["IMD gridded rainfall/temperature", "Replaced by NASA POWER monthly data at each state's main city (documented)."],
];

export default function Methodology() {
  const [q, setQ] = useState("");
  const terms = useMemo(() => Object.entries(GLOSSARY).filter(([k, v]) => `${k} ${v.full} ${v.def}`.toLowerCase().includes(q.toLowerCase())), [q]);
  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div>
        <h1 className="text-2xl font-semibold">Methodology</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">How every number on CarbonScope India is produced — sources, formulas, limitations and definitions.
          State values are <b>EDGAR-downscaled estimates</b>; city values are <b>proxy estimates</b>. Neither is an official inventory.</p>
      </div>

      <section className="grid gap-3" id="sources">
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Database size={18} className="text-emerald-400" />Data sources</h2>
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-600 dark:text-slate-400"><tr className="border-b border-slate-200 dark:border-white/10">
              <th className="px-3 py-2">Source</th><th className="px-3 py-2">What we use</th><th className="px-3 py-2">Feeds</th><th className="px-3 py-2">Licence</th></tr></thead>
            <tbody>{SOURCES.map(([n, url, what, lic, feeds]) => (
              <tr key={n} className="border-b border-slate-200 dark:border-white/5 align-top">
                <td className="px-3 py-2"><a href={url} target="_blank" rel="noreferrer" className="text-emerald-400 hover:underline">{n}</a></td>
                <td className="px-3 py-2 text-slate-700 dark:text-slate-300">{glossify(what)}</td><td className="px-3 py-2 text-slate-600 dark:text-slate-400">{feeds}</td><td className="px-3 py-2 text-slate-600 dark:text-slate-400">{lic}</td>
              </tr>))}</tbody>
          </table>
        </Card>
        <p className="text-xs text-slate-500 dark:text-slate-500">Every download is cached in <code>data/raw/</code> with a SHA-256 checksum; re-runs skip unchanged files and log upstream changes.</p>
      </section>

      <section className="grid gap-3" id="formulas">
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Calculator size={18} className="text-emerald-400" />Formula sheet</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <F name="CO₂e conversion (AR6 GWP-100)" f="CO₂e = CO₂ + 29.8·CH₄(fossil) + 27.0·CH₄(biogenic) + 273·N₂O"
            notes="IPCC AR6 WG1 Table 7.15. Biogenic CH₄ factor applies to agriculture and waste. (The commonly quoted single AR6 CH₄ value of 27.2 is close to our biogenic factor; we keep the fossil/biogenic split.)" />
          <F name="State allocation of EDGAR grids" f="E_state = Σ_cells E_cell × (area of cell inside state ÷ cell area)"
            notes="Exact polygon overlay in an equal-area projection (EPSG:6933), so small UTs and coastal cells are kept." />
          <F name="Per-capita emissions" f="per-capita (t/person) = CO₂e (t) ÷ population" notes="Population: Census 2001/2011 + 2023/24 estimates, log-linear between anchors." />
          <F name="Carbon intensity" f="intensity (tCO₂e per ₹ crore) = CO₂e (t) ÷ real GSDP (₹ crore, 2011-12 prices)" notes="GSDP before FY2011 is back-cast with national real GDP growth (flagged imputed)." />
          <F name="CAGR" f="CAGR = (value_end ÷ value_start)^(1 / years) − 1" />
          <F name="Fair-share CAGR (watchlist)" f="fair = national forecast CAGR × min(national per-capita ÷ state per-capita, 2); excess = forecast_end ÷ (CO₂e_now × (1+fair)^n) − 1"
            notes="States emitting < 5 Mt or with < 2 M people are not flagged (per-capita artefacts)." />
          <F name="Anomaly score" f="z = (growth_latest − mean(growth, prior 5 yrs)) ÷ max(sd(growth, prior 5 yrs), 1 pp)" notes="Flagged at |z| ≥ 2; ≥ 3 = watch." />
          <F name="Decoupling" f="absolute decoupling year: GSDP_t > GSDP_(t−1) and CO₂e_t < CO₂e_(t−1)" notes="Relative decoupling: CO₂e CAGR < GSDP CAGR." />
          <F name="Forecast (CarbonScope Forecast)" f="ŷ_(t+h) = exp(log(1+y_t) + Δ̂_h) − 1,  h = 1…5;  bands = P10/P50/P90"
            notes="A panel of statistical and deep-learning models is trained on 1990–2014, validated on 2015–2019 and tested on 2020–2024; the model with the best validation score is served. Models are retrained on schedule and a new model is promoted only if it beats the current one." />
          <F name="MinT reconciliation" f="ỹ = S (Sᵀ W⁻¹ S)⁻¹ Sᵀ W⁻¹ ŷ,  W = diag(train residual variances)"
            notes="Hierarchy: India → 36 states and 7 sectors → 252 state×sector cells. After reconciliation Σ cells = state total = national total exactly." />
          <F name="MASE (forecast accuracy)" f="MASE = mean |ŷ − y| ÷ mean |y_t − y_(t−1)| (training period)" notes="< 1 beats a naive 'same as last year' forecast." />
          <F name="City buffer estimate" f="E_city = Σ E_cell for cells with centre ≤ r from city centre;  r = 25 km (metro) / 12 km"
            notes="City forecast = Σ_sector state reconciled forecast × city's mean share of that state-sector over the last 3 years." />
          <F name="Source triangulation (power)" f="agreement = 1 − |EDGAR_power − CEA_power| ÷ CEA_power;  divergence flag if > 15 %"
            notes="CEA (plant-level, FY2017+) is the calibration anchor for the power sector; EDGAR is the baseline elsewhere." />
          <F name="Scenario counterfactual" f="power × (1 − ΔRE ÷ fossil share) + EV load;  transport × (1 − EV share × road share);  industry × (1+Δg)^t;  buildings × (1 − efficiency)"
            notes="Applied to the reconciled forecast, ramping to 2029; bands widened by ±20 % of the change. The levers never varied in the training data, so they are applied as explicit identities rather than learned responses." />
        </div>
      </section>

      <section className="grid gap-3" id="monsoon">
        <h2 className="text-lg font-semibold">Why monsoon rainfall is a driver</h2>
        <Card className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">
          The June–September (JJAS) monsoon changes emissions through three real channels: <b>hydropower</b> (wet years raise hydro output and displace coal),
          <b> cooling demand</b> (weak monsoons are hotter, raising CDD and air-conditioning load), and <b>agriculture</b> (paddy area, irrigation pumping and
          residue burning scale with rainfall). A drought year is flagged when JJAS rainfall &lt; 80 % of the state's 1990–2014 mean.
        </Card>
      </section>

      <section className="grid gap-3" id="gaps">
        <h2 className="text-lg font-semibold">Known data gaps</h2>
        <Card className="p-0"><ul className="divide-y divide-white/5 text-sm">
          {GAPS.map(([n, d]) => <li key={n} className="px-3 py-2"><b>{n}</b><span className="text-slate-600 dark:text-slate-400"> — {d}</span></li>)}
        </ul></Card>
        <p className="text-xs text-slate-500 dark:text-slate-500">Nothing is fabricated: missing sources stay missing, flagged with a <code>_missing</code> indicator, and the UI shows "—".</p>
      </section>

      <section className="grid gap-3" id="glossary">
        <h2 className="flex items-center gap-2 text-lg font-semibold"><BookOpen size={18} className="text-emerald-400" />Glossary</h2>
        <div className="relative w-72"><Search size={14} className="absolute left-2.5 top-2.5 text-slate-500 dark:text-slate-500" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search terms…" className="pl-8" aria-label="Search glossary" /></div>
        <Card className="p-0"><dl className="divide-y divide-white/5">
          {terms.map(([k, v]) => (
            <div key={k} className="grid gap-1 px-3 py-2 sm:grid-cols-[140px_1fr]">
              <dt className="font-mono text-sm text-emerald-700 dark:text-emerald-300">{k}</dt>
              <dd className="text-sm"><b>{v.full}.</b> <span className="text-slate-600 dark:text-slate-400">{v.def}</span></dd>
            </div>
          ))}
        </dl></Card>
      </section>
    </div>
  );
}
