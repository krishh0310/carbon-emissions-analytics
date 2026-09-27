// v2 side panels: state drill-down (donut, sector fan chart, ATAR cards, importance), scenario sandbox,
// ATAR intelligence feed, and two-state compare mode.
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Area, Bar, BarChart, Cell, ComposedChart, Line, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Bell, Info, Sparkles, X, Zap } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { cn, fmt } from "../components/ui";
import { SECTOR_COLORS } from "./FlowLayer";
import { GROUP_LABEL } from "../lib/sectors";
import { InsightCard } from "../insights/InsightCard";

export const SECTORS = ["POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER"] as const;
export const SECTOR_LABEL: Record<string, string> = {
  POWER: "Power", TRANSPORT: "Transport", INDUSTRY: "Industry", BUILDINGS: "Buildings", AGRICULTURE: "Agriculture", WASTE: "Waste", OTHER: "Other",
};
export const SEV_STYLE: Record<string, string> = {
  alert: "border-rose-500/50 bg-rose-500/10 text-rose-200", warning: "border-amber-500/50 bg-amber-500/10 text-amber-100",
  notice: "border-sky-500/40 bg-sky-500/10 text-sky-100", info: "border-white/10 bg-white/5 text-slate-200",
};
const TT = { background: "#020617", border: "1px solid #1e293b", fontSize: 11 };
const glass = "rounded-2xl border border-white/10 bg-slate-950/85 shadow-2xl backdrop-blur-xl";

export type SectorSeries = { history: Record<string, Record<string, Record<string, number>>>; forecast: Record<string, Record<string, { year: number; p10: number; p50: number; p90: number }[]>> };

export function sevIcon(s: string) {
  return s === "alert" ? <AlertTriangle size={13} /> : s === "warning" ? <Bell size={13} /> : s === "notice" ? <Zap size={13} /> : <Info size={13} />;
}

export function InsightCardLegacy({ i, onGo }: { i: any; onGo?: (code: string) => void }) {
  return (
    <button onClick={() => i.state_code && onGo?.(i.state_code)} className={cn("w-full rounded-xl border p-2.5 text-left transition hover:brightness-125", SEV_STYLE[i.severity])}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider opacity-80">
        {sevIcon(i.severity)}{i.type}{i.sector && <span className="rounded bg-black/30 px-1">{SECTOR_LABEL[i.sector] ?? i.sector}</span>}
        <span className="ml-auto">{i.state_code ?? "India"}</span>
      </div>
      <div className="mt-1 text-xs font-semibold leading-snug">{i.title}</div>
      <div className="mt-0.5 text-[11px] leading-snug opacity-80">{i.body}</div>
    </button>
  );
}

// ---- drill-down -----------------------------------------------------------------------------------------
export function DrillDown({ code, name, data, year, lastObs, onClose, onCompare, onOpen }: {
  code: string; name: string; data: SectorSeries | undefined; year: number; lastObs: number; onClose: () => void; onCompare: () => void; onOpen: () => void;
}) {
  const [sector, setSector] = useState<string>("POWER");
  const ins = useQuery({ queryKey: ["ins", code], queryFn: () => api(`/api/v2/insights?state=${code}&limit=20`) });
  const drv = useQuery({ queryKey: ["drivers"], queryFn: () => api("/api/v2/drivers"), retry: false });
  const h = data?.history[code] ?? {};
  const fc = data?.forecast[code] ?? {};
  const y = Math.min(year, lastObs);
  const donut = SECTORS.map((s, k) => ({ name: SECTOR_LABEL[s], v: h[s]?.[y] ?? 0, c: SECTOR_COLORS[k] }));
  const tot = donut.reduce((a, d) => a + d.v, 0);
  const fan = useMemo(() => {
    const rows: any[] = Object.entries(h[sector] ?? {}).map(([yy, v]) => ({ year: +yy, actual: v }));
    const f = fc[sector] ?? [];
    const last = rows.find((r) => r.year === lastObs);
    if (last && f.length) Object.assign(last, { p50: last.actual, band: [last.actual, last.actual] });
    return [...rows.filter((r) => r.year >= 2000), ...f.map((p) => ({ year: p.year, p50: p.p50, band: [p.p10, p.p90] }))];
  }, [h, fc, sector, lastObs]);
  const impRows = Object.entries(drv.data?.sectors?.[sector] ?? {}).map(([group, w]) => ({ group: GROUP_LABEL[group] ?? group, importance: 100 * (w as number) }));
  return (
    <div className={cn(glass, "absolute left-4 top-36 z-20 flex max-h-[calc(100%-300px)] w-[380px] flex-col overflow-hidden")}>
      <div className="flex items-start justify-between p-4 pb-2">
        <div>
          <div className="text-base font-semibold">{name}</div>
          <div className="text-[11px] text-slate-400">{code} · {fmt(tot, 1)} MtCO₂e in {y} · 7-sector view (AR6 GWP-100)</div>
        </div>
        <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white"><X size={16} /></button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 pb-4">
        <div className="flex items-center gap-3">
          <div className="h-32 w-32 shrink-0">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={donut} dataKey="v" innerRadius={34} outerRadius={60} paddingAngle={1} stroke="none"
                  onClick={(d: any) => setSector(SECTORS[donut.findIndex((x) => x.name === d.name)])}>
                  {donut.map((d) => <Cell key={d.name} fill={d.c} className="cursor-pointer" />)}
                </Pie>
                <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 2)} Mt`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="grid flex-1 grid-cols-1 gap-0.5 text-[11px]">
            {donut.map((d, k) => (
              <button key={d.name} onClick={() => setSector(SECTORS[k])}
                className={cn("flex items-center gap-1.5 rounded px-1 text-left hover:bg-white/5", SECTORS[k] === sector && "bg-white/10")}>
                <i className="inline-block h-2 w-2 rounded-sm" style={{ background: d.c }} />{d.name}
                <span className="ml-auto tabular-nums text-slate-400">{tot ? Math.round((100 * d.v) / tot) : 0}%</span>
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="text-[11px] text-slate-400">{SECTOR_LABEL[sector]} — history + reconciled forecast (P10–P90)</div>
          <div className="h-36">
            <ResponsiveContainer>
              <ComposedChart data={fan} margin={{ left: -18, right: 4, top: 6 }}>
                <XAxis dataKey="year" stroke="#475569" fontSize={9} />
                <YAxis stroke="#475569" fontSize={9} />
                <Tooltip contentStyle={TT} formatter={(v: any) => (Array.isArray(v) ? v.map((x) => fmt(x, 2)).join("–") : fmt(v, 2))} />
                <Area dataKey="band" fill={SECTOR_COLORS[SECTORS.indexOf(sector as any)]} fillOpacity={0.25} stroke="none" />
                <Line dataKey="actual" stroke="#e2e8f0" dot={false} strokeWidth={1.5} />
                <Line dataKey="p50" stroke={SECTOR_COLORS[SECTORS.indexOf(sector as any)]} dot={false} strokeWidth={2} strokeDasharray="4 2" />
                <ReferenceLine x={year} stroke="#34d399" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        {impRows.length > 0 && (
          <div>
            <div className="text-[11px] text-slate-400">Drivers of the {SECTOR_LABEL[sector].toLowerCase()} forecast (relative influence, %)</div>
            <div className="h-28">
              <ResponsiveContainer>
                <BarChart data={impRows} layout="vertical" margin={{ left: 30 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="group" stroke="#64748b" fontSize={9} width={120} />
                  <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 0)}%`} />
                  <Bar dataKey="importance" fill={SECTOR_COLORS[SECTORS.indexOf(sector as any)]} radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
        <div className="space-y-1.5">
          <div className="flex items-center gap-1 text-[11px] text-slate-400"><Sparkles size={12} />ATAR insights</div>
          {(ins.data?.items ?? []).slice(0, 6).map((i: any) => <InsightCard key={i.id} i={i} />)}
          {ins.data && !ins.data.items.length && <div className="text-[11px] text-slate-500">No notable signals for this state.</div>}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button onClick={onCompare} className="rounded-lg bg-sky-500/15 py-1.5 text-xs text-sky-300 hover:bg-sky-500/25">Compare with…</button>
          <button onClick={onOpen} className="rounded-lg bg-emerald-500/15 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/25">State Explorer →</button>
        </div>
      </div>
    </div>
  );
}

// ---- scenario sandbox -----------------------------------------------------------------------------------
const LEVERS = [
  ["renewable_pp", "Extra renewable share", "pp", 0, 40, 1],
  ["ev_share_pct", "EV share of road travel", "%", 0, 60, 1],
  ["industrial_growth_pp", "Industrial growth change", "pp/yr", -5, 5, 0.5],
  ["building_efficiency_pct", "Building efficiency gain", "%", 0, 30, 1],
] as const;

export function ScenarioPanel({ onResult, onClose, stateFilter }: { onResult: (r: any) => void; onClose: () => void; stateFilter: string | null }) {
  const [p, setP] = useState<Record<string, number>>({ renewable_pp: 10, ev_share_pct: 15, industrial_growth_pp: 0, building_efficiency_pct: 5 });
  const [onlySel, setOnlySel] = useState(false);
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => api("/api/v2/scenarios/presets") });
  const run = useMutation({
    mutationFn: (body: any) => api("/api/v2/scenarios/run", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => onResult(r),
    onError: (e: any) => toast.error(e.message),
  });
  const go = (extra: any = {}) => run.mutate({ name: "sandbox", ...p, states: onlySel && stateFilter ? [stateFilter] : null, ...extra });
  const r = run.data;
  return (
    <div className={cn(glass, "absolute bottom-40 left-1/2 z-20 w-[560px] max-w-[calc(100%-32px)] -translate-x-1/2 p-4")}>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold">Scenario sandbox <span className="font-normal text-slate-400">· projected {r?.end_year ?? 2029}</span></div>
        <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white"><X size={16} /></button>
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {Object.entries(presets.data?.presets ?? {}).map(([k, v]: any) => (
          <button key={k} onClick={() => { setP({ renewable_pp: v.renewable_pp, ev_share_pct: v.ev_share_pct, industrial_growth_pp: v.industrial_growth_pp, building_efficiency_pct: v.building_efficiency_pct }); go({ preset: k }); }}
            className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] hover:bg-white/10">{v.name}</button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-x-5 gap-y-2">
        {LEVERS.map(([k, label, unit, lo, hi, st]) => (
          <label key={k} className="text-[11px] text-slate-300">
            <div className="flex justify-between"><span>{label}</span><span className="tabular-nums text-emerald-300">{p[k] > 0 && k === "industrial_growth_pp" ? "+" : ""}{p[k]} {unit}</span></div>
            <input type="range" min={lo} max={hi} step={st} value={p[k]} className="w-full accent-emerald-500"
              onChange={(e) => setP({ ...p, [k]: +e.target.value })} onMouseUp={() => go()} onKeyUp={() => go()} onTouchEnd={() => go()} />
          </label>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={onlySel} disabled={!stateFilter} onChange={(e) => setOnlySel(e.target.checked)} className="accent-emerald-500" />
          apply only to {stateFilter ?? "selected state"}</label>
        <button onClick={() => go()} disabled={run.isPending} className="rounded-md bg-emerald-500 px-3 py-1 text-xs font-medium text-slate-950 hover:bg-emerald-400">{run.isPending ? "Running…" : "Run"}</button>
      </div>
      {r && (
        <div className="mt-3 grid grid-cols-[1fr_1.4fr] gap-3 border-t border-white/10 pt-3">
          <div>
            <div className="text-[11px] text-slate-400">India {r.end_year}</div>
            <div className="text-xl font-semibold tabular-nums">{fmt(r.national.scenario_mt, 0)} <span className="text-xs text-slate-400">MtCO₂e</span></div>
            <div className={cn("text-sm tabular-nums", r.national.delta_mt < 0 ? "text-emerald-400" : "text-amber-400")}>
              {r.national.delta_mt < 0 ? "▼" : "▲"} {fmt(Math.abs(r.national.delta_mt), 1)} Mt vs baseline ({fmt((100 * r.national.delta_mt) / r.national.baseline_mt, 1)}%)
            </div>
            <div className="mt-1 text-[10px] leading-snug text-slate-500">Map shows Δ vs baseline per state. Structural levers on top of the reconciled forecast — see method.</div>
          </div>
          <div className="h-28">
            <ResponsiveContainer>
              <BarChart data={r.by_sector} layout="vertical" margin={{ left: 10 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="sector" stroke="#64748b" fontSize={9} width={80} tickFormatter={(s) => SECTOR_LABEL[s]} />
                <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 2)} Mt`} />
                <ReferenceLine x={0} stroke="#475569" />
                <Bar dataKey="delta_mt" radius={2}>{r.by_sector.map((s: any) => <Cell key={s.sector} fill={s.delta_mt < 0 ? "#10b981" : "#f59e0b"} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

// ---- ATAR feed -------------------------------------------------------------------------------------------
export function InsightFeed({ onGo, onClose }: { onGo: (code: string) => void; onClose: () => void }) {
  const [sev, setSev] = useState("");
  const [sector, setSector] = useState("");
  const q = useQuery({ queryKey: ["feed", sev, sector], queryFn: () => api(`/api/v2/insights?limit=200${sev ? `&severity=${sev}` : ""}${sector ? `&sector=${sector}` : ""}`) });
  return (
    <div className={cn(glass, "absolute right-4 top-4 bottom-40 z-20 flex w-[340px] flex-col")}>
      <div className="flex items-center justify-between p-3 pb-2">
        <div className="flex items-center gap-1.5 text-sm font-semibold"><Sparkles size={15} className="text-emerald-400" />ATAR live intelligence
          <span className="rounded-full bg-white/10 px-1.5 text-[10px] font-normal">{q.data?.total ?? "…"}</span></div>
        <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white"><X size={16} /></button>
      </div>
      <div className="flex gap-1.5 px-3 pb-2">
        <select value={sev} onChange={(e) => setSev(e.target.value)} className="flex-1 rounded bg-slate-800 px-1.5 py-1 text-[11px]">
          <option value="">All severities</option>{["alert", "warning", "notice", "info"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <select value={sector} onChange={(e) => setSector(e.target.value)} className="flex-1 rounded bg-slate-800 px-1.5 py-1 text-[11px]">
          <option value="">All sectors</option>{SECTORS.map((s) => <option key={s} value={s}>{SECTOR_LABEL[s]}</option>)}
        </select>
      </div>
      <div className="flex-1 space-y-1.5 overflow-y-auto px-3 pb-3">
        {(q.data?.items ?? []).map((i: any) => <InsightCard key={i.id} i={i} onGo={onGo} />)}
      </div>
    </div>
  );
}

// ---- compare mode ----------------------------------------------------------------------------------------
export function ComparePanel({ a, b, names, data, lastObs, onClose, onPick, pop }: {
  a: string; b: string | null; names: (c: string) => string; data: SectorSeries | undefined; lastObs: number;
  onClose: () => void; onPick: (c: string) => void; pop?: (c: string) => number | null;
}) {
  const total = (c: string) => {
    const h = data?.history[c] ?? {};
    const f = data?.forecast[c] ?? {};
    const years = Object.keys(h.POWER ?? {}).map(Number).filter((y) => y >= 2000);
    const rows: any[] = years.map((y) => ({ year: y, [c]: SECTORS.reduce((s, k) => s + (h[k]?.[y] ?? 0), 0) }));
    const fy = (f.POWER ?? []).map((p) => p.year);
    return [...rows, ...fy.map((y) => ({ year: y, [`${c}_fc`]: SECTORS.reduce((s, k) => s + (f[k]?.find((p) => p.year === y)?.p50 ?? 0), 0) }))];
  };
  const merged = useMemo(() => {
    const m: Record<number, any> = {};
    for (const c of [a, b].filter(Boolean) as string[]) for (const r of total(c)) m[r.year] = { ...(m[r.year] ?? { year: r.year }), ...r };
    if (m[lastObs]) for (const c of [a, b].filter(Boolean) as string[]) m[lastObs][`${c}_fc`] = m[lastObs][c];
    return Object.values(m).sort((x: any, y: any) => x.year - y.year);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a, b, data]);
  const mix = (c: string) => SECTORS.map((s, k) => ({ sector: SECTOR_LABEL[s], v: data?.history[c]?.[s]?.[lastObs] ?? 0, fill: SECTOR_COLORS[k] }));
  return (
    <div className={cn(glass, "absolute bottom-40 left-4 right-4 z-20 p-4")}>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold">Compare · <span style={{ color: "#34d399" }}>{names(a)}</span> vs <span style={{ color: "#60a5fa" }}>{b ? names(b) : "click another state on the map"}</span></div>
        <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white"><X size={16} /></button>
      </div>
      {b && pop && (() => {
        const tot = (c: string) => SECTORS.reduce((s, k) => s + (data?.history[c]?.[k]?.[lastObs] ?? 0), 0);
        const pcA = tot(a) / (pop(a) || NaN), pcB = tot(b) / (pop(b) || NaN);
        const rows: [string, number, number, string, number][] = [["Total CO₂e", tot(a), tot(b), "Mt", 1], ["Per capita", pcA, pcB, "t/person", 2]];
        return (
          <div className="mb-3 grid gap-2 sm:grid-cols-2">
            {rows.map(([l, va, vb, u, d]) => (
              <div key={l} className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs">
                <span className="text-slate-400">{l} ({lastObs}) · A − B = </span>
                <b className={cn("tabular-nums", va - vb > 0 ? "text-amber-300" : "text-emerald-300")}>{va - vb > 0 ? "+" : "−"}{fmt(Math.abs(va - vb), d)} {u}</b>
                <span className="ml-1 text-slate-500">({fmt(va, d)} vs {fmt(vb, d)})</span>
              </div>
            ))}
          </div>
        );
      })()}
      {!b ? <div className="py-6 text-center text-xs text-slate-400">Pick a second state on the map (or search) to compare.<button className="hidden" onClick={() => onPick(a)} /></div> : (
        <div className="grid gap-4 md:grid-cols-[1.4fr_1fr_1fr]">
          <div className="h-40">
            <ResponsiveContainer>
              <ComposedChart data={merged} syncId="cmp" margin={{ left: -15 }}>
                <XAxis dataKey="year" stroke="#475569" fontSize={9} /><YAxis stroke="#475569" fontSize={9} />
                <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 1)} Mt`} />
                <Line dataKey={a} stroke="#34d399" dot={false} strokeWidth={2} name={names(a)} />
                <Line dataKey={`${a}_fc`} stroke="#34d399" dot={false} strokeDasharray="4 2" name={`${names(a)} forecast`} />
                <Line dataKey={b} stroke="#60a5fa" dot={false} strokeWidth={2} name={names(b)} />
                <Line dataKey={`${b}_fc`} stroke="#60a5fa" dot={false} strokeDasharray="4 2" name={`${names(b)} forecast`} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {[a, b].map((c) => (
            <div key={c} className="h-40">
              <div className="text-[11px] text-slate-400">{names(c)} · sector mix {lastObs}</div>
              <ResponsiveContainer height="90%">
                <BarChart data={mix(c)} syncId="cmp-mix" layout="vertical" margin={{ left: 10 }}>
                  <XAxis type="number" hide /><YAxis type="category" dataKey="sector" stroke="#64748b" fontSize={9} width={70} />
                  <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 2)} Mt`} />
                  <Bar dataKey="v" radius={2}>{mix(c).map((m) => <Cell key={m.sector} fill={m.fill} />)}</Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
