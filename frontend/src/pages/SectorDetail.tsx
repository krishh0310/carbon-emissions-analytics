import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Area, Brush, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { SECTORS, SECTOR_LABEL, colorOf } from "../lib/sectors";
import { ChartCard } from "../components/ChartCard";
import { fmt } from "../components/ui";
import { DRIVER_METRICS, SRC_EDGAR, TT } from "../state/StateCharts";
import { useStateData } from "../state/useStateData";

const source = SRC_EDGAR;
const unit = "MtCO₂e";
const axes = { stroke: "#64748b", fontSize: 11 };
const how = (formula: string, inputs = "EDGAR 2025 sector grids and CarbonScope forecasts") => ({ formula, inputs });
const levers = [
  { key: "renewable_pp", label: "Additional renewable share (pp)", sector: "POWER", min: 0, max: 40 },
  { key: "ev_share_pct", label: "EV share (%)", sector: "TRANSPORT", min: 0, max: 60 },
  { key: "industrial_growth_pp", label: "Industry growth shift (pp)", sector: "INDUSTRY", min: -5, max: 5 },
  { key: "building_efficiency_pct", label: "Building efficiency gain (%)", sector: "BUILDINGS", min: 0, max: 30 },
] as const;

function Plot({ rows, lines, height = 280, log = false, reference }: { rows: any[]; lines: { key: string; label: string; color: string; band?: boolean }[]; height?: number; log?: boolean; reference?: number }) {
  return <ResponsiveContainer width="100%" height={height}><ComposedChart data={rows} margin={{ top: 10, right: 14, bottom: 4, left: 5 }}>
    <XAxis dataKey="year" {...axes} type="number" domain={["dataMin", "dataMax"]} allowDuplicatedCategory={false} />
    <YAxis {...axes} width={55} scale={log ? "log" : "auto"} domain={log ? ["auto", "auto"] : [0, "auto"]} tickFormatter={(v: number) => fmt(v, 1)} />
    <Tooltip contentStyle={TT} formatter={(v: any, n: any) => [Array.isArray(v) ? `${fmt(v[0], 2)}–${fmt(v[1], 2)}` : fmt(v, 2), n]} />
    <Legend />{reference !== undefined && <ReferenceLine y={reference} stroke="#94a3b8" strokeDasharray="4 4" />}
    {lines.filter((l) => l.band).map((l) => <Area key={l.key} dataKey={l.key} name={l.label} fill={l.color} fillOpacity={0.18} stroke="none" isAnimationActive={false} />)}
    {lines.filter((l) => !l.band).map((l) => <Line key={l.key} dataKey={l.key} name={l.label} stroke={l.color} strokeWidth={2.2} dot={false} connectNulls isAnimationActive={false} />)}
    <Brush dataKey="year" height={22} stroke="#10b981" />
  </ComposedChart></ResponsiveContainer>;
}

export default function SectorDetail() {
  const { code = "IN-MH", sector: raw = "power" } = useParams();
  const sector = raw.toUpperCase();
  const valid = SECTORS.includes(sector as typeof SECTORS[number]);
  const d = useStateData(valid ? code : null);
  const states = useQuery({ queryKey: ["states-list"], queryFn: () => api("/states?limit=50&geometry=false") });
  const national = useQuery({ queryKey: ["national-analytics"], queryFn: () => api("/api/v2/analytics/national"), enabled: valid });
  const [log, setLog] = useState(false);
  const [peers, setPeers] = useState<string[]>([]);
  const [drivers, setDrivers] = useState<string[]>([]);
  const [params, setParams] = useState<Record<string, number>>({});
  const [scenario, setScenario] = useState<any>(null);
  const [scenarioError, setScenarioError] = useState("");
  const [running, setRunning] = useState(false);
  const [copied, setCopied] = useState(false);
  const peerData = useQuery({ queryKey: ["sector-peers", sector, peers], enabled: peers.length > 0,
    queryFn: async () => Promise.all(peers.map(async (c) => ({ code: c, history: await api(`/api/v2/states/${c}/sectors`), forecast: await api(`/api/v2/states/${c}/sectors/${sector}/forecast`) }))) });
  const rows = useMemo(() => {
    const history = d.years.map((year) => ({ year, observed: d.bySector[sector]?.[year] }));
    const forecast = d.secFc[sector] ?? [];
    if (history.length && forecast.length) Object.assign(history[history.length - 1], { median: history[history.length - 1].observed });
    return [...history, ...forecast.map((p) => ({ year: p.year, median: d.val(p), fan: [p.p10, p.p90] }))];
  }, [d, sector]);
  if (!valid) return <p>Unknown sector. <Link to={`/state/${code}`}>Back to state</Link></p>;
  const label = SECTOR_LABEL[sector];
  const changes = d.years.slice(1).map((year) => ({ year, delta: (d.bySector[sector][year] ?? 0) - (d.bySector[sector][year - 1] ?? 0) }));
  const mean = changes.reduce((sum, x) => sum + x.delta, 0) / (changes.length || 1);
  const sd = Math.sqrt(changes.reduce((sum, x) => sum + (x.delta - mean) ** 2, 0) / (changes.length || 1));
  const breakYears = changes.filter((x) => sd > 0 && Math.abs(x.delta - mean) > 2 * sd).map((x) => ({ year: x.year, label: x.year === 2020 ? "COVID-19 · detected" : "Detected shift" }));
  const indexed = d.years.map((year) => ({ year, ...Object.fromEntries(DRIVER_METRICS[sector].map((m) => {
    const baseYear = d.years.find((y) => (m.get(d, y) ?? 0) > 0);
    const base = baseYear && m.get(d, baseYear);
    return [m.label, base && m.get(d, year) != null ? 100 * Number(m.get(d, year)) / Number(base) : null];
  })) }));
  const intensity = d.years.map((year) => ({ year, value: d.gsdp[year] ? d.bySector[sector][year] * 1e6 / d.gsdp[year] : null }));
  const natYears: number[] = national.data?.years ?? [];
  const benchmark = d.years.map((year) => {
    const ni = natYears.indexOf(year);
    const nationalValue = ni < 0 ? null : national.data.sectors[sector]?.[ni] / 36;
    return { year, ratio: nationalValue ? d.bySector[sector][year] / nationalValue : null };
  });
  const comparison = rows.map((r) => ({ ...r, ...Object.fromEntries((peerData.data ?? []).map((p) => {
    const h = p.history.history?.[sector]?.find((x: any) => x.year === r.year);
    const f = p.forecast.points?.find((x: any) => x.year === r.year);
    return [p.code, h?.co2e_mt ?? f?.p50 ?? null];
  })), ...Object.fromEntries((peerData.data ?? []).map((p) => {
    const f = p.forecast.points?.find((x: any) => x.year === r.year);
    return [`${p.code}_fan`, f ? [f.p10, f.p90] : undefined];
  })) }));
  const sc = new Map((scenario?.cell_path ?? []).filter((x: any) => x.state_code === code && x.sector === sector).map((x: any) => [x.year, x]));
  const scenarioRows = rows.map((r) => {
    const p: any = sc.get(r.year);
    return { ...r, scenario: p?.scenario_p50, scenarioFan: p ? [p.scenario_p10, p.scenario_p90] : undefined };
  });
  const csv = rows.map((r: any) => ({ year: r.year, observed_mt: r.observed ?? null, p10_mt: r.fan?.[0] ?? null, p50_mt: r.median ?? null, p90_mt: r.fan?.[1] ?? null }));
  const runScenario = async () => {
    setRunning(true); setScenarioError("");
    try { setScenario(await api("/api/v2/scenarios/run", { method: "POST", body: JSON.stringify({ name: `${label} scenario`, states: [code], ...params }) })); }
    catch (e) { setScenarioError(e instanceof Error ? e.message : "Scenario failed"); }
    finally { setRunning(false); }
  };
  useEffect(() => {
    if (!Object.keys(params).length) return;
    const timer = window.setTimeout(() => { void runScenario(); }, 700);
    return () => window.clearTimeout(timer);
  }, [params]);
  return <div className="grid gap-4 pb-12">
    <nav className="text-xs text-slate-500"><Link className="text-emerald-500 hover:underline" to={`/state/${code}`}>← {d.name ?? code} State Explorer</Link> / {label}</nav>
    <header><h1 className="text-3xl font-semibold">{d.name ?? code} · {label}</h1><p className="text-sm text-slate-500">EDGAR-downscaled estimates · AR6 GWP-100 · reconciled forecast through {d.fcYears.at(-1) ?? "—"}</p></header>
    <ChartCard name={`${code}_${sector}_forecast`} title="History and five-year forecast" data={csv} unit={unit} source={source} how={how("Observed = EDGAR sector cells; P50 = reconciled sector forecast; fan = raw P10–P90 quantiles")}
      right={<button className="rounded border px-2 py-1 text-xs" onClick={() => setLog(!log)}>{log ? "Log" : "Linear"} scale</button>}>
      <Plot rows={rows} log={log} height={410} lines={[{ key: "fan", label: "P10–P90", color: "#38bdf8", band: true }, { key: "observed", label: "Observed", color: colorOf(sector) }, { key: "median", label: "Forecast P50", color: "#38bdf8" }]} />
    </ChartCard>
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard name={`${code}_${sector}_decomposition`} title="Trend and structural breaks" data={rows} unit={unit} source={source} how={how("Trend = centered five-year average; break marker = annual change more than 2 standard deviations from its historical mean", "Observed EDGAR sector emissions; breaks are descriptive, not causal attribution")}>
        <div className="mb-2 text-xs text-slate-500">{breakYears.length ? breakYears.map((x) => `${x.year} ${x.label}`).join(" · ") : "No large year-on-year shifts detected"} · markers do not establish cause</div>
        <ResponsiveContainer width="100%" height={270}><ComposedChart data={d.years.map((year, i) => ({ year, observed: d.bySector[sector][year], trend: d.years.slice(Math.max(0, i - 2), i + 3).reduce((sum, y) => sum + d.bySector[sector][y], 0) / d.years.slice(Math.max(0, i - 2), i + 3).length }))}>
          <XAxis dataKey="year" {...axes} /><YAxis {...axes} width={55} /><Tooltip contentStyle={TT} /><Legend />
          {breakYears.map((x) => <ReferenceLine key={x.year} x={x.year} stroke="#f59e0b" strokeDasharray="3 3" label={{ value: x.label, fontSize: 10, fill: "#f59e0b" }} />)}
          <Line dataKey="observed" stroke={colorOf(sector)} dot={false} /><Line dataKey="trend" stroke="#38bdf8" dot={false} />
          <Brush dataKey="year" height={22} stroke="#10b981" />
        </ComposedChart></ResponsiveContainer>
      </ChartCard>
      <ChartCard name={`${code}_${sector}_drivers`} title="Driver explorer · indexed to 100" data={indexed} unit="index (first positive year = 100)" source="CEA · MoSPI · Census · NASA POWER · EDGAR" how={how("Index = driver value ÷ first positive observed value × 100", "Available measured drivers; association does not establish causality")}>
        <div className="mb-2 flex flex-wrap gap-2">{DRIVER_METRICS[sector].map((m) => <label key={m.label} className="text-xs"><input type="checkbox" checked={drivers.includes(m.label)} onChange={() => setDrivers(drivers.includes(m.label) ? drivers.filter((x) => x !== m.label) : [...drivers, m.label])} /> {m.label}</label>)}</div>
        <Plot rows={indexed} lines={drivers.map((x, i) => ({ key: x, label: x, color: ["#10b981", "#38bdf8", "#f59e0b", "#a855f7"][i % 4] }))} />
      </ChartCard>
      <ChartCard name={`${code}_${sector}_intensity`} title="Sector intensity" data={intensity} unit="tCO₂e per ₹ crore real state GSDP" source={`${source} · MoSPI GSDP`} how={how("Sector emissions (Mt) × 1,000,000 ÷ state real GSDP (₹ crore)", "State GSDP is used because sector GSVA is not available consistently")}>
        <Plot rows={intensity} lines={[{ key: "value", label: "Intensity", color: colorOf(sector) }]} />
      </ChartCard>
      <ChartCard name={`${code}_${sector}_benchmark`} title="National benchmark" data={benchmark} unit="ratio to mean state sector emissions" source={source} how={how("State sector emissions ÷ (India sector total ÷ 36)", "An absolute-size comparison, not a per-capita or intensity comparison")}>
        <Plot rows={benchmark} reference={1} lines={[{ key: "ratio", label: "State ÷ mean state", color: colorOf(sector) }]} />
      </ChartCard>
    </div>
    <ChartCard name={`${code}_${sector}_peers`} title="Peer states" data={comparison} unit={unit} source={source} how={how("Each line = state sector observed estimates followed by reconciled forecast P50; select up to three states")}>
      <div className="mb-2 flex flex-wrap gap-2"><select aria-label="Add peer state" value="" onChange={(e) => { if (e.target.value && peers.length < 3) setPeers([...peers, e.target.value]); }} className="rounded border bg-transparent p-1 text-xs"><option value="">Add peer state…</option>{(states.data?.items ?? []).filter((x: any) => x.code !== code && !peers.includes(x.code)).map((x: any) => <option key={x.code} value={x.code}>{x.name}</option>)}</select>{peers.map((p) => <button key={p} onClick={() => setPeers(peers.filter((x) => x !== p))} className="rounded bg-slate-100 px-2 text-xs dark:bg-slate-800">{p} ×</button>)}</div>
      <Plot rows={comparison} lines={[{ key: "fan", label: `${code} P10–P90`, color: "#38bdf8", band: true }, { key: "observed", label: d.name ?? code, color: colorOf(sector) }, { key: "median", label: `${code} forecast`, color: "#38bdf8" }, ...peers.flatMap((p, i) => [{ key: `${p}_fan`, label: `${p} P10–P90`, color: ["#f59e0b", "#a855f7", "#ef4444"][i], band: true }, { key: p, label: p, color: ["#f59e0b", "#a855f7", "#ef4444"][i] }])]} />
    </ChartCard>
    <ChartCard name={`${code}_${sector}_scenario`} title="Scenario levers" data={scenarioRows} unit={unit} source="CarbonScope forecast · explicit scenario identities" how={how("Scenario = reconciled P50 adjusted by documented sector lever; P10/P90 scaled and widened for parameter uncertainty", "Counterfactual, not a retrained model or measured outcome")}>
      <div className="mb-3 flex flex-wrap gap-4">{levers.filter((x) => x.sector === sector || (sector === "POWER" && x.sector === "TRANSPORT")).map((x) => <label key={x.key} className="text-xs">{x.label}: <b>{params[x.key] ?? 0}</b><input type="range" min={x.min} max={x.max} value={params[x.key] ?? 0} onChange={(e) => setParams({ ...params, [x.key]: Number(e.target.value) })} className="ml-2 align-middle" /></label>)}<button disabled={running} onClick={runScenario} className="rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-50">{running ? "Running…" : "Run scenario"}</button></div>
      {scenarioError && <p role="alert" className="text-sm text-red-500">{scenarioError}</p>}
      <Plot rows={scenarioRows} lines={[{ key: "fan", label: "BAU P10–P90", color: "#38bdf8", band: true }, { key: "median", label: "BAU P50", color: "#38bdf8" }, { key: "scenarioFan", label: "Scenario P10–P90", color: "#f59e0b", band: true }, { key: "scenario", label: "Scenario P50", color: "#f59e0b" }]} />
    </ChartCard>
    <ChartCard name={`${code}_${sector}_table`} title="Yearly data" data={csv} unit={unit} source={source} how={how("Observed values are EDGAR-downscaled estimates; future values are forecast quantiles and reconciled median")} right={<button className="rounded border px-2 py-1 text-xs" onClick={async () => { await navigator.clipboard.writeText(["year,observed_mt,p10_mt,p50_mt,p90_mt", ...csv.map((r) => Object.values(r).map((v) => v ?? "").join(","))].join("\n")); setCopied(true); }}>{copied ? "Copied" : "Copy CSV"}</button>}>
      <div className="max-h-80 overflow-auto"><table className="w-full text-left text-xs"><thead className="sticky top-0 bg-white dark:bg-slate-900"><tr>{["Year", "Observed", "P10", "P50", "P90"].map((x) => <th key={x} className="p-2">{x}</th>)}</tr></thead><tbody>{csv.map((r) => <tr key={r.year} className="border-t border-slate-200 dark:border-white/10">{Object.values(r).map((v, i) => <td key={i} className="p-2 tabular-nums">{v == null ? "—" : i ? fmt(v, 2) : v}</td>)}</tr>)}</tbody></table></div>
    </ChartCard>
  </div>;
}
