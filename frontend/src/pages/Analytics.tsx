// Analytics: one place for every individual view — sectors, states, cities, compare, global peers, facilities and
// source triangulation. Long history (EDGAR 1970+, OWID 1850+) and live external APIs (World Bank, Climate TRACE).
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { ArrowUpRight, X } from "lucide-react";
import { api } from "../lib/api";
import { SECTORS, SECTOR_LABEL, colorOf } from "../lib/sectors";
import { ChartCard } from "../components/ChartCard";
import { Card, Select, Skeleton, Table, cn, fmt } from "../components/ui";
import { TT } from "../state/StateCharts";

const AX = { stroke: "#64748b", fontSize: 11 };
const PALETTE = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#a855f7", "#14b8a6", "#ec4899", "#84cc16"];
type Series = Record<string, (number | null)[]>;
type Panel = { years: number[]; entities: any[]; data: Record<string, Series>; source: string };

const TABS = ["Sectors", "States", "Cities", "Compare", "Global", "Facilities", "Sources"] as const;
type Tab = (typeof TABS)[number];

const total = (s: Series | undefined, i: number) => (s ? SECTORS.reduce((a, k) => a + (s[k]?.[i] ?? 0), 0) : 0);
const val = (s: Series | undefined, sector: string, i: number) => (sector === "TOTAL" ? total(s, i) : s?.[sector]?.[i] ?? 0);
const cagr = (a: number, b: number, n: number) => (a > 0 && b > 0 && n > 0 ? 100 * ((b / a) ** (1 / n) - 1) : null);
const stackRows = (years: number[], s: Series | undefined) =>
  years.map((year, i) => ({ year, ...Object.fromEntries(SECTORS.map((k) => [k, +(s?.[k]?.[i] ?? 0).toFixed(3)])) }));

function Tabs({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  return (
    <div className="flex flex-wrap gap-1 rounded-xl border border-slate-200 bg-white p-1 dark:border-white/10 dark:bg-slate-900/60">
      {TABS.map((t) => (
        <button key={t} onClick={() => setTab(t)}
          className={cn("rounded-lg px-3 py-1.5 text-sm", tab === t ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200" : "text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-white/5")}>
          {t}
        </button>
      ))}
    </div>
  );
}

function SectorStack({ rows, h = 300 }: { rows: any[]; h?: number }) {
  return (
    <ResponsiveContainer width="100%" height={h}>
      <AreaChart data={rows}>
        <CartesianGrid strokeDasharray="3 3" stroke="#64748b33" />
        <XAxis dataKey="year" {...AX} /><YAxis {...AX} width={50} />
        <Tooltip contentStyle={TT} formatter={(v: any, n: any) => [`${fmt(v, 1)} Mt`, SECTOR_LABEL[n] ?? n]} />
        {SECTORS.map((s) => <Area key={s} dataKey={s} stackId="1" stroke={colorOf(s)} fill={colorOf(s)} fillOpacity={0.75} isAnimationActive={false} />)}
        {rows[0]?.year < 1990 && <ReferenceLine x={1990} stroke="#64748b" strokeDasharray="4 3" label={{ value: "modelled panel →", fill: "#64748b", fontSize: 10, position: "insideTopRight" }} />}
      </AreaChart>
    </ResponsiveContainer>
  );
}

const SectorLegend = () => (
  <>{SECTORS.map((s) => <span key={s} className="flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: colorOf(s) }} />{SECTOR_LABEL[s]}</span>)}</>
);

// ---- Sectors ----------------------------------------------------------------------------------------------
function SectorsTab({ nat, st }: { nat: any; st: Panel }) {
  const years: number[] = nat.years;
  const [year, setYear] = useState(years[years.length - 1]);
  const i = years.indexOf(year);
  const rows = years.map((y, k) => ({ year: y, ...Object.fromEntries(SECTORS.map((s) => [s, nat.sectors[s][k]])) }));
  const tot = SECTORS.reduce((a, s) => a + nat.sectors[s][i], 0);
  const name = (c: string) => st.entities.find((e) => e.code === c)?.name ?? c;
  return (
    <div className="grid gap-4">
      <ChartCard title={`India emissions by sector, ${years[0]}–${years[years.length - 1]}`} name="india_sectors_history" data={rows}
        sub="Sum of 36 states, EDGAR-downscaled CO₂e (AR6 GWP-100). Pre-1990 years are display-only back-history; the 1989→1990 step in Other is EDGAR's own coal-mine CH₄ revision." unit="Mt CO₂e/yr"
        source="EDGAR 2025" legend={<SectorLegend />}
        how={{ formula: "India_sector,t = Σ_states E_state,sector,t", note: "CO₂ + CH₄ + N₂O converted with AR6 GWP-100." }}>
        <SectorStack rows={rows} h={320} />
      </ChartCard>
      <div className="flex items-center gap-3">
        <Select label="Year for rankings" value={year} onChange={(e) => setYear(+e.target.value)}>
          {[...years].reverse().map((y) => <option key={y}>{y}</option>)}
        </Select>
        <span className="text-xs text-slate-500">India total {fmt(tot, 0)} Mt CO₂e</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {SECTORS.map((s) => {
          const v = nat.sectors[s];
          const i10 = Math.max(0, i - 10);
          const top = st.entities.map((e) => ({ name: name(e.code), code: e.code, v: st.data[e.code]?.[s]?.[i] ?? 0 }))
            .sort((a, b) => b.v - a.v).slice(0, 5);
          const line = years.map((y, k) => ({ year: y, v: v[k] }));
          return (
            <ChartCard key={s} title={SECTOR_LABEL[s]} name={`sector_${s}`} data={line} unit="Mt CO₂e"
              sub={<>{fmt(v[i], 1)} Mt in {year} · {fmt((100 * v[i]) / (tot || 1), 1)}% of India · 10-yr CAGR {fmt(cagr(v[i10], v[i], i - i10), 1)}%</>}>
              <ResponsiveContainer width="100%" height={130}>
                <AreaChart data={line}>
                  <XAxis dataKey="year" {...AX} /><YAxis {...AX} width={40} />
                  <Tooltip contentStyle={TT} formatter={(x: any) => [`${fmt(x, 1)} Mt`, SECTOR_LABEL[s]]} />
                  <Area dataKey="v" stroke={colorOf(s)} fill={colorOf(s)} fillOpacity={0.3} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
              <div className="mt-2 text-[11px] font-medium text-slate-500">Top states, {year}</div>
              <ResponsiveContainer width="100%" height={120}>
                <BarChart data={top} layout="vertical" margin={{ left: 10 }}>
                  <XAxis type="number" {...AX} /><YAxis type="category" dataKey="name" {...AX} width={110} />
                  <Tooltip contentStyle={TT} formatter={(x: any) => [`${fmt(x, 1)} Mt`, SECTOR_LABEL[s]]} />
                  <Bar dataKey="v" fill={colorOf(s)} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          );
        })}
      </div>
    </div>
  );
}

// ---- States / Cities: small multiples + drill-down ----------------------------------------------------------
function EntityGrid({ p, kind }: { p: Panel; kind: "state" | "city" }) {
  const nav = useNavigate();
  const idOf = (e: any) => String(kind === "state" ? e.code : e.id);
  const [sort, setSort] = useState("TOTAL");
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const n = p.years.length - 1;
  const i90 = Math.max(0, p.years.indexOf(1990));
  const list = useMemo(() => p.entities
    .filter((e) => !filter || (kind === "city" ? e.state_code === filter : e.region === filter))
    .map((e) => ({ e, id: idOf(e), v: val(p.data[idOf(e)], sort, n), v0: val(p.data[idOf(e)], sort, i90) }))
    .sort((a, b) => b.v - a.v), [p, sort, filter]); // eslint-disable-line react-hooks/exhaustive-deps
  const groups = [...new Set(p.entities.map((e) => (kind === "city" ? e.state_code : e.region)))].sort();
  const sel = open ? p.entities.find((e) => idOf(e) === open) : null;
  const s = open ? p.data[open] : undefined;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select label="Rank by" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="TOTAL">Total CO₂e</option>{SECTORS.map((x) => <option key={x} value={x}>{SECTOR_LABEL[x]}</option>)}
        </Select>
        <Select label={kind === "city" ? "State" : "Region"} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All</option>{groups.map((g) => <option key={g}>{g}</option>)}
        </Select>
        <span className="text-xs text-slate-500">{list.length} {kind === "city" ? "cities" : "states/UTs"} · {p.years[0]}–{p.years[n]} · click a card to open</span>
      </div>
      {sel && s && (
        <Card className="grid gap-3 ring-1 ring-emerald-400/40">
          <div className="flex items-center justify-between">
            <div className="text-lg font-semibold">{sel.name} <span className="text-sm font-normal text-slate-500">{kind === "city" ? sel.state_code : sel.region}</span></div>
            <div className="flex gap-2">
              {kind === "state" && <button onClick={() => nav(`/state/${open}`)} className="flex items-center gap-1 text-sm text-emerald-600 hover:underline dark:text-emerald-400">State Explorer <ArrowUpRight size={14} /></button>}
              <button aria-label="Close" onClick={() => setOpen(null)} className="rounded p-1 hover:bg-slate-100 dark:hover:bg-white/5"><X size={16} /></button>
            </div>
          </div>
          <ChartCard title="All sectors, stacked" name={`${kind}_${open}_sectors`} data={stackRows(p.years, s)} unit="Mt CO₂e" source={p.source} legend={<SectorLegend />}>
            <SectorStack rows={stackRows(p.years, s)} />
          </ChartCard>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {SECTORS.map((k) => {
              const d = p.years.map((year, i) => ({ year, v: s[k]?.[i] ?? 0 }));
              return (
                <div key={k} className="rounded-xl border border-slate-200 p-2 dark:border-white/10">
                  <div className="flex justify-between text-xs"><b style={{ color: colorOf(k) }}>{SECTOR_LABEL[k]}</b><span className="tabular-nums">{fmt(d[n].v, 2)} Mt</span></div>
                  <ResponsiveContainer width="100%" height={90}>
                    <AreaChart data={d}><XAxis dataKey="year" hide /><YAxis hide />
                      <Tooltip contentStyle={TT} formatter={(x: any) => [`${fmt(x, 2)} Mt`, SECTOR_LABEL[k]]} labelFormatter={(_, pl: any) => pl?.[0]?.payload.year} />
                      <Area dataKey="v" stroke={colorOf(k)} fill={colorOf(k)} fillOpacity={0.3} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                  <div className="text-[10px] text-slate-500">share {fmt((100 * d[n].v) / (total(s, n) || 1), 1)}% · since 1990 {fmt(cagr(d[i90].v, d[n].v, n - i90), 1)}%/yr</div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {list.map(({ e, id, v, v0 }, rank) => (
          <button key={id} onClick={() => setOpen(id)}
            className={cn("rounded-xl border bg-white p-2.5 text-left transition hover:border-emerald-400/60 dark:bg-slate-900/60",
              open === id ? "border-emerald-400" : "border-slate-200 dark:border-white/10")}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-sm font-medium">{rank + 1}. {e.name}</span>
              <span className="whitespace-nowrap text-xs tabular-nums">{fmt(v, v < 1 ? 2 : 1)} Mt</span>
            </div>
            <div className="text-[10px] text-slate-500">{cagr(v0, v, n - i90) == null ? "—" : `${fmt(cagr(v0, v, n - i90), 1)}%/yr since 1990`}</div>
            <ResponsiveContainer width="100%" height={60}>
              <AreaChart data={stackRows(p.years, p.data[id])}>
                {(sort === "TOTAL" ? SECTORS : [sort]).map((k) => <Area key={k} dataKey={k} stackId="1" stroke="none" fill={colorOf(k)} fillOpacity={0.8} isAnimationActive={false} />)}
              </AreaChart>
            </ResponsiveContainer>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---- Compare --------------------------------------------------------------------------------------------
function CompareTab({ st, ct }: { st: Panel; ct: Panel }) {
  const [kind, setKind] = useState<"state" | "city">("state");
  const p = kind === "state" ? st : ct;
  const idOf = (e: any) => String(kind === "state" ? e.code : e.id);
  const [picked, setPicked] = useState<Record<string, string[]>>({ state: ["IN-MH", "IN-GJ", "IN-UP", "IN-TN"], city: [] });
  const ids = picked[kind].length ? picked[kind] : kind === "city" ? p.entities.filter((e) => e.is_metro).slice(0, 4).map(idOf) : [];
  const [sector, setSector] = useState("TOTAL");
  const [mode, setMode] = useState<"abs" | "index" | "share">("abs");
  const [base, setBase] = useState(1990);
  const n = p.years.length - 1;
  const bi = Math.max(0, p.years.indexOf(base));
  const name = (id: string) => p.entities.find((e) => idOf(e) === id)?.name ?? id;
  const natTot = (i: number) => Object.values(p.data).reduce((a, s) => a + val(s, sector, i), 0);
  const rows = p.years.map((year, i) => ({
    year, ...Object.fromEntries(ids.map((id) => {
      const v = val(p.data[id], sector, i);
      const b = val(p.data[id], sector, bi);
      return [name(id), mode === "abs" ? v : mode === "index" ? (b ? (100 * v) / b : null) : (100 * v) / (natTot(i) || 1)];
    })),
  }));
  const mix = ids.map((id) => {
    const t = total(p.data[id], n) || 1;
    return { name: name(id), ...Object.fromEntries(SECTORS.map((k) => [k, +((100 * (p.data[id]?.[k]?.[n] ?? 0)) / t).toFixed(1)])) };
  });
  const setIds = (next: string[]) => setPicked({ ...picked, [kind]: next });
  return (
    <div className="grid gap-4">
      <Card className="flex flex-wrap items-center gap-3">
        <Select label="Compare" value={kind} onChange={(e) => setKind(e.target.value as any)}><option value="state">States</option><option value="city">Cities</option></Select>
        <Select label="Add" value="" onChange={(e) => e.target.value && ids.length < 8 && setIds([...ids, e.target.value])}>
          <option value="">{ids.length >= 8 ? "max 8" : "choose…"}</option>
          {p.entities.filter((e) => !ids.includes(idOf(e))).map((e) => <option key={idOf(e)} value={idOf(e)}>{e.name}</option>)}
        </Select>
        <Select label="Metric" value={sector} onChange={(e) => setSector(e.target.value)}>
          <option value="TOTAL">Total CO₂e</option>{SECTORS.map((x) => <option key={x} value={x}>{SECTOR_LABEL[x]}</option>)}
        </Select>
        <Select label="View" value={mode} onChange={(e) => setMode(e.target.value as any)}>
          <option value="abs">Absolute (Mt)</option><option value="index">Index (base = 100)</option><option value="share">Share of all {kind === "state" ? "states" : "cities"} (%)</option>
        </Select>
        {mode === "index" && <Select label="Base year" value={base} onChange={(e) => setBase(+e.target.value)}>{p.years.map((y) => <option key={y}>{y}</option>)}</Select>}
        <div className="flex w-full flex-wrap gap-1.5">
          {ids.map((id, k) => (
            <span key={id} className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs text-white" style={{ background: PALETTE[k % 8] }}>
              {name(id)}<button aria-label={`Remove ${name(id)}`} onClick={() => setIds(ids.filter((x) => x !== id))}><X size={12} /></button>
            </span>
          ))}
        </div>
      </Card>
      <ChartCard title={`${sector === "TOTAL" ? "Total" : SECTOR_LABEL[sector]} emissions — ${mode === "abs" ? "absolute" : mode === "index" ? `index, ${base} = 100` : "share"}`}
        name="compare" data={rows} unit={mode === "abs" ? "Mt CO₂e" : mode === "index" ? "index" : "%"} source={p.source}>
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#64748b33" />
            <XAxis dataKey="year" {...AX} /><YAxis {...AX} width={50} />
            <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 1)} /><Legend wrapperStyle={{ fontSize: 12 }} />
            {ids.map((id, k) => <Line key={id} dataKey={name(id)} stroke={PALETTE[k % 8]} dot={false} strokeWidth={2} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={`Sector mix, ${p.years[n]}`} name="compare_mix" data={mix} unit="% of total" legend={<SectorLegend />}>
          <ResponsiveContainer width="100%" height={Math.max(160, ids.length * 34)}>
            <BarChart data={mix} layout="vertical" margin={{ left: 10 }}>
              <XAxis type="number" domain={[0, 100]} {...AX} /><YAxis type="category" dataKey="name" {...AX} width={110} />
              <Tooltip contentStyle={TT} formatter={(v: any, k: any) => [`${v}%`, SECTOR_LABEL[k]]} />
              {SECTORS.map((k) => <Bar key={k} dataKey={k} stackId="1" fill={colorOf(k)} isAnimationActive={false} />)}
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Key numbers" name="compare_stats"
          data={ids.map((id) => ({ name: name(id), latest_mt: val(p.data[id], sector, n), cagr10_pct: cagr(val(p.data[id], sector, n - 10), val(p.data[id], sector, n), 10) }))}>
          <Table head={["", `${p.years[n]} (Mt)`, "10-yr CAGR", `vs ${p.years[0]}`, "Largest sector"]}
            rows={ids.map((id) => {
              const s = p.data[id];
              const big = SECTORS.reduce((a, k) => ((s?.[k]?.[n] ?? 0) > (s?.[a]?.[n] ?? 0) ? k : a), SECTORS[0]);
              const first = val(s, sector, 0);
              return [name(id), fmt(val(s, sector, n), 2), `${fmt(cagr(val(s, sector, n - 10), val(s, sector, n), 10), 1)}%`,
                first ? `×${fmt(val(s, sector, n) / first, 1)}` : "—", SECTOR_LABEL[big]];
            })} />
        </ChartCard>
      </div>
    </div>
  );
}

// ---- Global (OWID) -----------------------------------------------------------------------------------------
const GMETRIC: Record<string, [string, string]> = {
  co2: ["Fossil CO₂", "Mt CO₂"], co2_per_capita: ["CO₂ per person", "t/person"], total_ghg_excluding_lucf: ["All GHGs (excl. land use)", "Mt CO₂e"],
  share_global_co2: ["Share of world CO₂", "%"], cumulative_co2: ["Cumulative CO₂ since 1750", "Mt CO₂"], co2_per_gdp: ["Carbon intensity of GDP", "kg CO₂ per $ (PPP)"],
};
function GlobalTab({ world, nat }: { world: any[]; nat: any }) {
  const [m, setM] = useState("co2_per_capita");
  const [from, setFrom] = useState(1950);
  const [log, setLog] = useState(false);
  const countries = [...new Set(world.map((r) => r.country))].filter((c) => c !== "World" || !["share_global_co2"].includes(m));
  const [on, setOn] = useState<string[]>(["India", "China", "United States", "European Union (27)", "World"]);
  const rows = useMemo(() => {
    const by: Record<number, any> = {};
    world.forEach((r) => { if (r.year >= from && on.includes(r.country) && r[m] != null) (by[r.year] ??= { year: r.year })[r.country] = r[m]; });
    return Object.values(by).sort((a: any, b: any) => a.year - b.year);
  }, [world, m, from, on]);
  const FUEL = [["coal_co2", "Coal", "#475569"], ["oil_co2", "Oil", "#f59e0b"], ["gas_co2", "Gas", "#3b82f6"], ["cement_co2", "Cement", "#a8a29e"], ["flaring_co2", "Flaring", "#ef4444"], ["other_industry_co2", "Other industry", "#a855f7"]];
  const fuel = nat.owid.filter((r: any) => r.year >= 1900);
  return (
    <div className="grid gap-4">
      <Card className="flex flex-wrap items-center gap-3">
        <Select label="Metric" value={m} onChange={(e) => setM(e.target.value)}>{Object.entries(GMETRIC).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</Select>
        <Select label="From" value={from} onChange={(e) => setFrom(+e.target.value)}>{[1850, 1900, 1950, 1970, 1990, 2000].map((y) => <option key={y}>{y}</option>)}</Select>
        <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} />log scale</label>
        <div className="flex w-full flex-wrap gap-1.5">
          {countries.map((c) => (
            <button key={c} onClick={() => setOn(on.includes(c) ? on.filter((x) => x !== c) : [...on, c])}
              className={cn("rounded-full px-2.5 py-0.5 text-xs", on.includes(c) ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-400")}>{c}</button>
          ))}
        </div>
      </Card>
      <ChartCard title={`${GMETRIC[m][0]} — India vs peers`} name={`global_${m}`} data={rows} unit={GMETRIC[m][1]} source="Our World in Data (GCP; GHG from Jones et al. 2023)">
        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#64748b33" />
            <XAxis dataKey="year" {...AX} /><YAxis {...AX} width={56} scale={log ? "log" : "auto"} domain={log ? ["auto", "auto"] : [0, "auto"]} allowDataOverflow />
            <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 2)} /><Legend wrapperStyle={{ fontSize: 12 }} />
            {on.map((c, k) => <Line key={c} dataKey={c} stroke={c === "India" ? "#10b981" : PALETTE[(k + 1) % 8]} strokeWidth={c === "India" ? 3 : 1.5} dot={false} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>
      <ChartCard title="India fossil CO₂ by fuel, 1900–latest" name="india_fuel" data={fuel} unit="Mt CO₂" source="Our World in Data (Global Carbon Project)"
        legend={<>{FUEL.map(([, l, c]) => <span key={l} className="flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: c }} />{l}</span>)}</>}>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={fuel}>
            <CartesianGrid strokeDasharray="3 3" stroke="#64748b33" />
            <XAxis dataKey="year" {...AX} /><YAxis {...AX} width={50} />
            <Tooltip contentStyle={TT} formatter={(v: any, k: any) => [`${fmt(v, 1)} Mt`, FUEL.find((f) => f[0] === k)?.[1] ?? k]} />
            {FUEL.map(([k, , c]) => <Area key={k} dataKey={k} stackId="1" stroke={c} fill={c} fillOpacity={0.75} isAnimationActive={false} />)}
          </AreaChart>
        </ResponsiveContainer>
      </ChartCard>
    </div>
  );
}

// ---- Facilities (Climate TRACE) --------------------------------------------------------------------------------
function FacilitiesTab({ st }: { st: Panel }) {
  const [state, setState] = useState("");
  const [sector, setSector] = useState("");
  const q = useQuery({ queryKey: ["fac", state, sector], queryFn: () => api(`/api/v2/analytics/facilities?limit=300${state ? `&state=${state}` : ""}${sector ? `&sector=${sector}` : ""}`) });
  const items: any[] = useMemo(() => q.data?.items ?? [], [q.data]);
  const byState = useMemo(() => {
    const m: Record<string, number> = {};
    items.forEach((f) => { if (f.state_code) m[f.state_code] = (m[f.state_code] ?? 0) + f.co2e_mt; });
    return Object.entries(m).map(([code, v]) => ({ name: st.entities.find((e) => e.code === code)?.name ?? code, v: +v.toFixed(2) })).sort((a, b) => b.v - a.v).slice(0, 15);
  }, [items, st]);
  const top = items.slice(0, 20).map((f) => ({ ...f, short: f.name.length > 28 ? f.name.slice(0, 27) + "…" : f.name }));
  return (
    <div className="grid gap-4">
      <Card className="flex flex-wrap items-center gap-3">
        <Select label="State" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All India</option>{st.entities.map((e) => <option key={e.code} value={e.code}>{e.name}</option>)}
        </Select>
        <Select label="Sector" value={sector} onChange={(e) => setSector(e.target.value)}>
          <option value="">All</option>{["POWER", "INDUSTRY", "WASTE", "OTHER"].map((s) => <option key={s} value={s}>{SECTOR_LABEL[s]}{s === "OTHER" ? " (fossil fuel ops, mining)" : ""}</option>)}
        </Select>
        <span className="text-xs text-slate-500">{items.length} facilities · {fmt(items.reduce((a, f) => a + f.co2e_mt, 0), 0)} Mt CO₂e ({items[0]?.year ?? "—"})</span>
      </Card>
      {q.isLoading ? <Skeleton className="h-80" /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard title="Top 20 emitting facilities" name="facilities_top" data={top} unit="Mt CO₂e/yr" source="Climate TRACE v6">
            <ResponsiveContainer width="100%" height={520}>
              <BarChart data={top} layout="vertical" margin={{ left: 10 }}>
                <XAxis type="number" {...AX} /><YAxis type="category" dataKey="short" {...AX} width={170} interval={0} />
                <Tooltip contentStyle={TT} formatter={(v: any, _: any, pl: any) => [`${fmt(v, 2)} Mt`, `${pl.payload.owner ?? ""} · ${pl.payload.state_code ?? ""}`]} />
                <Bar dataKey="co2e_mt" isAnimationActive={false}>{top.map((f) => <Cell key={f.id} fill={colorOf(f.sector)} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard title="Facility emissions by state" name="facilities_by_state" data={byState} unit="Mt CO₂e/yr" source="Climate TRACE v6"
            sub="Only the facilities listed (top 200 per Climate TRACE sector nationally), not the state total.">
            <ResponsiveContainer width="100%" height={520}>
              <BarChart data={byState} layout="vertical" margin={{ left: 10 }}>
                <XAxis type="number" {...AX} /><YAxis type="category" dataKey="name" {...AX} width={130} interval={0} />
                <Tooltip contentStyle={TT} formatter={(v: any) => [`${fmt(v, 1)} Mt`, "facilities"]} />
                <Bar dataKey="v" fill="#10b981" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>
      )}
      <ChartCard title="Facility list" name="facilities" data={items}>
        <div className="max-h-[480px] overflow-y-auto">
          <Table head={["#", "Facility", "Owner", "Type", "State", "Mt CO₂e", "Capacity"]}
            rows={items.map((f, k) => [k + 1, f.name, f.owner ?? "—", `${f.subsector}${f.asset_type ? ` · ${f.asset_type}` : ""}`, f.state_code ?? "offshore",
              fmt(f.co2e_mt, 2), f.capacity ? `${fmt(f.capacity, 0)} ${f.capacity_units ?? ""}` : "—"])} />
        </div>
      </ChartCard>
    </div>
  );
}

// ---- Sources (triangulation) ------------------------------------------------------------------------------------
function SourcesTab({ nat }: { nat: any }) {
  const edgar = Object.fromEntries(nat.years.map((y: number, i: number) => [y, SECTORS.reduce((a, s) => a + nat.sectors[s][i], 0)]));
  const owid = Object.fromEntries(nat.owid.map((r: any) => [r.year, r.total_ghg_excluding_lucf]));
  const wb = Object.fromEntries(nat.worldbank.map((r: any) => [r.year, r.ghg_total_mt]));
  const ct = Object.fromEntries(Object.entries(nat.climatetrace).map(([y, s]: any) => [y, Object.values(s).reduce((a: number, v: any) => a + v, 0)]));
  const rows = Array.from({ length: 2025 - 1970 + 1 }, (_, k) => 1970 + k).map((y) => ({
    year: y, "EDGAR (Σ states)": edgar[y] ?? null, "OWID (Jones et al.)": owid[y] ?? null, "World Bank": wb[y] ?? null, "Climate TRACE": ct[y] ?? null,
  }));
  const ctYears = Object.keys(nat.climatetrace).map(Number).filter((y) => edgar[y] != null);
  const [y, setY] = useState(ctYears[ctYears.length - 1]);
  const i = nat.years.indexOf(y);
  const bars = SECTORS.map((s) => ({ sector: SECTOR_LABEL[s], EDGAR: +(nat.sectors[s][i] ?? 0).toFixed(1), "Climate TRACE": nat.climatetrace[y]?.[s] ?? 0 }));
  return (
    <div className="grid gap-4">
      <ChartCard title="India total GHG — four independent sources" name="sources_total" data={rows} unit="Mt CO₂e/yr (excl. land use)"
        sub="Differences reflect methods: EDGAR & World Bank (EDGAR-based, AR5) vs OWID (Jones et al. 2023, own GWP basis) vs Climate TRACE (asset/satellite models, 2021+)."
        how={{ formula: "gap % = (source − EDGAR) ÷ EDGAR", note: "Land-use (LULUCF) and international bunkers excluded everywhere for a like-for-like comparison." }}>
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#64748b33" />
            <XAxis dataKey="year" {...AX} /><YAxis {...AX} width={56} />
            <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 0)} Mt`} /><Legend wrapperStyle={{ fontSize: 12 }} />
            {["EDGAR (Σ states)", "OWID (Jones et al.)", "World Bank", "Climate TRACE"].map((k, j) => (
              <Line key={k} dataKey={k} stroke={PALETTE[j]} strokeWidth={j ? 1.5 : 2.5} dot={k === "Climate TRACE"} connectNulls={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>
      {ctYears.length > 0 && (
        <ChartCard title={`By sector: EDGAR vs Climate TRACE, ${y}`} name="sources_sector" data={bars} unit="Mt CO₂e" source="EDGAR 2025 · Climate TRACE v6"
          right={<Select value={y} onChange={(e) => setY(+e.target.value)}>{ctYears.map((x) => <option key={x}>{x}</option>)}</Select>}
          sub="Climate TRACE subsectors mapped to CarbonScope sectors; coal mining, oil & gas operations → Other.">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={bars}>
              <CartesianGrid strokeDasharray="3 3" stroke="#64748b33" />
              <XAxis dataKey="sector" {...AX} /><YAxis {...AX} width={50} />
              <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 1)} Mt`} /><Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="EDGAR" fill="#10b981" isAnimationActive={false} /><Bar dataKey="Climate TRACE" fill="#3b82f6" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      )}
      <Card className="text-xs text-slate-600 dark:text-slate-400">
        <ul className="grid gap-1">{Object.entries(nat.sources).map(([k, v]: any) => <li key={k}><b className="uppercase">{k}</b> — {v}</li>)}</ul>
      </Card>
    </div>
  );
}

export default function Analytics() {
  const [tab, setTab] = useState<Tab>("Sectors");
  const nat = useQuery({ queryKey: ["an-national"], queryFn: () => api("/api/v2/analytics/national"), staleTime: 3600e3 });
  const st = useQuery<Panel>({ queryKey: ["an-states"], queryFn: () => api("/api/v2/analytics/states"), staleTime: 3600e3 });
  const ct = useQuery<Panel>({ queryKey: ["an-cities"], queryFn: () => api("/api/v2/analytics/cities"), staleTime: 3600e3, enabled: tab === "Cities" || tab === "Compare" });
  const world = useQuery({ queryKey: ["an-world"], queryFn: () => api("/api/v2/analytics/world"), staleTime: 3600e3, enabled: tab === "Global" });
  const ready = nat.data && st.data;
  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Every sector, state and city on its own chart, side-by-side comparisons, India against the world since 1850,
          the largest individual facilities, and four independent data sources checked against each other.
        </p>
      </div>
      <Tabs tab={tab} setTab={setTab} />
      {!ready ? <Skeleton className="h-96" /> :
        tab === "Sectors" ? <SectorsTab nat={nat.data} st={st.data!} /> :
        tab === "States" ? <EntityGrid p={st.data!} kind="state" /> :
        tab === "Cities" ? (ct.data ? <EntityGrid p={ct.data} kind="city" /> : <Skeleton className="h-96" />) :
        tab === "Compare" ? (ct.data ? <CompareTab st={st.data!} ct={ct.data} /> : <Skeleton className="h-96" />) :
        tab === "Global" ? (world.data ? <GlobalTab world={world.data.items} nat={nat.data} /> : <Skeleton className="h-96" />) :
        tab === "Facilities" ? <FacilitiesTab st={st.data!} /> :
        <SourcesTab nat={nat.data} />}
    </div>
  );
}
