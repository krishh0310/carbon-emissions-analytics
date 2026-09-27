// State Explorer charts: history+forecast (full-opacity history, connected fan) and the 6-part sector deep-dive.
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, Bar, BarChart, Cell, ComposedChart, LabelList, Line, LineChart, Pie, PieChart, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { api } from "../lib/api";
import { ChartCard } from "../components/ChartCard";
import { Info } from "../components/Info";
import { glossify } from "../lib/glossary";
import { cn, fmt } from "../components/ui";
import { GROUP_LABEL, SECTORS, SECTOR_LABEL, colorOf } from "../lib/sectors";
import type { Target, useStateData } from "./useStateData";

type D = ReturnType<typeof useStateData>;
export const TT = { background: "#020617", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 };
const AX = { stroke: "#64748b", fontSize: 11 };
const HIST = "#10b981", FC = "#38bdf8", CEA = "#f59e0b";
export const SRC_EDGAR = "EDGAR 2025, downscaled to states";

export const TARGETS: Record<Target, { label: string; unit: string; digits: number; how: { formula: string; inputs: string; note?: string } }> = {
  co2e: { label: "Total CO₂e", unit: "MtCO₂e (million tonnes CO₂-equivalent)", digits: 1,
    how: { formula: "CO₂e = Σ sectors (CO₂ + 29.8/27.0 × CH₄ + 273 × N₂O)", inputs: "EDGAR 0.1° sector grids × state-area overlay; AR6 GWP-100",
      note: "Forecast = Σ reconciled sector P50; band = Σ sector P10…P90 (conservative)." } },
  co2: { label: "Fossil CO₂", unit: "MtCO₂", digits: 1,
    how: { formula: "Fossil CO₂ = Σ EDGAR CO₂ grid cells × area share inside the state", inputs: "EDGAR TOTALS CO₂ grid; CEA plant-level power CO₂ shown as amber dots (FY2017+)" } },
  pc: { label: "Per-capita CO₂e", unit: "tCO₂e per person", digits: 2,
    how: { formula: "Per-capita = CO₂e (t) ÷ population", inputs: "Population: Census 2001/2011 + 2023/24 estimates, log-linear; forecast years extrapolate the last 5-yr population CAGR" } },
  ci: { label: "Carbon intensity", unit: "tCO₂e per ₹ crore real GSDP (2011-12 prices)", digits: 0,
    how: { formula: "Intensity = CO₂e (t) ÷ real GSDP (₹ crore, 2011-12 prices)", inputs: "MoSPI GSDP (constant prices); no forecast because GSDP is not forecast",
      note: "Years before FY2011 use back-cast GSDP (flagged imputed in the data)." } },
};

const yearTick = (props: any) => {
  const { x, y, payload } = props;
  const lab = payload.value % 5 === 0;
  return (
    <g transform={`translate(${x},${y})`}>
      <line y1={0} y2={lab ? 6 : 3} stroke="#64748b" />
      {lab && <text y={17} textAnchor="middle" fill="#94a3b8" fontSize={10}>{payload.value}</text>}
    </g>
  );
};
const yearAxis = (rows: { year: number }[]) => {
  const ys = rows.map((r) => r.year);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  return { type: "number" as const, dataKey: "year", domain: [lo, hi], ticks: Array.from({ length: hi - lo + 1 }, (_, i) => lo + i), tick: yearTick, interval: 0 as const, height: 26 };
};

// ---- A. history + forecast -----------------------------------------------------------------------------
export function HistoryForecast({ d, height = 360 }: { d: D; height?: number }) {
  const [target, setTarget] = useState<Target>("co2e");
  const [log, setLog] = useState(false);
  const rows = useMemo(() => d.series(target), [d, target]);
  const t = TARGETS[target];
  const fcStart = d.lastObs, fcEnd = rows[rows.length - 1]?.year;
  return (
    <ChartCard name={`${d.name}_${target}`} title={`${d.name ?? ""} — ${t.label}: history and forecast`}
      sub="Solid green = observed estimates · blue line = forecast median (P50) · shaded fan = P10–P90 range (80 % of outcomes)"
      data={rows.map(({ band, ...r }) => ({ ...r, p10: band?.[0], p90: band?.[1] }))} loading={d.loading} unit={t.unit}
      source={target === "co2" ? `${SRC_EDGAR} · CEA CO₂ Baseline DB` : target === "ci" ? `${SRC_EDGAR} · MoSPI GSDP` : SRC_EDGAR}
      how={t.how}
      right={
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="flex overflow-hidden rounded-md border border-slate-200 dark:border-white/10 text-[11px]">
            {(Object.keys(TARGETS) as Target[]).map((k) => (
              <button key={k} onClick={() => setTarget(k)} className={cn("px-2 py-1", k === target ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-200" : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/5")}>{TARGETS[k].label}</button>
            ))}
          </div>
          <button onClick={() => setLog(!log)} className={cn("rounded-md border border-slate-200 dark:border-white/10 px-2 py-1 text-[11px]", log ? "bg-sky-100 dark:bg-sky-500/20 text-sky-800 dark:text-sky-200" : "text-slate-600 dark:text-slate-400")}>
            {log ? "log" : "linear"} scale
          </button>
        </div>
      }
      legend={<>
        <span className="flex items-center gap-1"><i className="inline-block h-2 w-4 rounded-sm" style={{ background: HIST }} />Observed</span>
        {target !== "ci" && <span className="flex items-center gap-1"><i className="inline-block h-0.5 w-4" style={{ background: FC }} />Forecast P50</span>}
        {target !== "ci" && <span className="flex items-center gap-1"><i className="inline-block h-2 w-4 rounded-sm" style={{ background: FC, opacity: 0.3 }} />P10–P90</span>}
        {target === "co2" && <span className="flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-full" style={{ background: CEA }} />CEA power-sector CO₂ (grid plants)</span>}
      </>}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
          <defs>
            <linearGradient id="histFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={HIST} stopOpacity={0.45} /><stop offset="100%" stopColor={HIST} stopOpacity={0.05} /></linearGradient>
            <linearGradient id="fanFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={FC} stopOpacity={0.45} /><stop offset="100%" stopColor={FC} stopOpacity={0.15} /></linearGradient>
          </defs>
          {fcEnd > fcStart && target !== "ci" && <ReferenceArea x1={fcStart} x2={fcEnd} fill="#38bdf8" fillOpacity={0.05} label={{ value: "forecast", position: "insideTop", fill: "#7dd3fc", fontSize: 10 }} />}
          <XAxis {...yearAxis(rows)} {...AX} />
          <YAxis {...AX} width={56} scale={log ? "log" : "auto"} domain={log ? ["auto", "auto"] : [0, "auto"]} allowDataOverflow
            tickFormatter={(v) => fmt(v, t.digits > 1 ? 1 : 0)} label={{ value: t.unit.split(" (")[0], angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 10, dx: -2 }} />
          <Tooltip contentStyle={TT} labelFormatter={(y: any) => `${y}${Number(y) > d.lastObs ? " (forecast)" : ""}`}
            formatter={(v: any, n: any) => [Array.isArray(v) ? `${fmt(v[0], t.digits)} – ${fmt(v[1], t.digits)}` : fmt(v, t.digits), n]} />
          <Area dataKey="band" name="P10–P90" stroke="none" fill="url(#fanFill)" isAnimationActive={false} />
          <Area dataKey="hist" name="Observed" stroke={HIST} strokeWidth={2.5} fill="url(#histFill)" dot={false} connectNulls isAnimationActive={false} />
          <Line dataKey="p50" name="Forecast P50" stroke={FC} strokeWidth={2.5} dot={{ r: 2.5, fill: FC }} isAnimationActive={false} />
          {target === "co2" && <Scatter dataKey="cea" name="CEA power CO₂" fill={CEA} />}
          <ReferenceLine x={d.lastObs} stroke="#475569" strokeDasharray="3 3" />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// ---- B. sector deep-dive -------------------------------------------------------------------------------
const DRIVER_METRICS: Record<string, { label: string; unit: string; get: (d: D, y: number) => number | null | undefined }[]> = {
  POWER: [
    { label: "Coal generation", unit: "TWh", get: (d, y) => (d.feats[y]?.coal_generation_gwh ?? null) && d.feats[y].coal_generation_gwh / 1000 },
    { label: "Grid emission factor (GEF)", unit: "tCO₂/MWh", get: (d, y) => d.feats[y]?.grid_emission_factor },
    { label: "Hydro+nuclear share", unit: "% of CEA gen.", get: (d, y) => d.feats[y]?.renewable_share_pct },
    { label: "Power share of state CO₂", unit: "%", get: (d, y) => d.bySector.POWER[y] && d.total[y] ? (100 * d.bySector.POWER[y]) / d.total[y] : null },
  ],
  TRANSPORT: [
    { label: "Road CO₂ share of total", unit: "%", get: (d, y) => (d.feats[y]?.road_share ?? null) && 100 * d.feats[y].road_share },
    { label: "Urban population", unit: "million", get: (d, y) => d.feats[y] && (d.feats[y].population_mn * d.feats[y].urban_population_pct) / 100 },
    { label: "Real GSDP", unit: "₹ lakh crore", get: (d, y) => d.gsdp[y] && d.gsdp[y] / 1e5 },
  ],
  INDUSTRY: [
    { label: "Real GSDP growth", unit: "%/yr", get: (d, y) => d.feats[y]?.gsdp_growth_pct },
    { label: "Industry CO₂e per ₹ cr", unit: "tCO₂e/₹cr", get: (d, y) => d.gsdp[y] && d.bySector.INDUSTRY[y] ? (d.bySector.INDUSTRY[y] * 1e6) / d.gsdp[y] : null },
    { label: "Cement & minerals CO₂", unit: "MtCO₂", get: (d, y) => d.feats[y]?.edgar_cement_mt },
  ],
  BUILDINGS: [
    { label: "Cooling degree days (CDD)", unit: "°C·days", get: (d, y) => d.feats[y]?.cooling_degree_days },
    { label: "Population", unit: "million", get: (d, y) => d.pop[y] },
    { label: "Urban share", unit: "%", get: (d, y) => d.feats[y]?.urban_population_pct },
  ],
  AGRICULTURE: [
    { label: "Monsoon rainfall (JJAS)", unit: "mm", get: (d, y) => d.feats[y]?.monsoon_rainfall_mm },
    { label: "Drought year", unit: "flag", get: (d, y) => d.feats[y]?.drought_year },
    { label: "Rural population", unit: "million", get: (d, y) => d.feats[y] && d.feats[y].population_mn * (1 - d.feats[y].urban_population_pct / 100) },
  ],
  WASTE: [
    { label: "Urban population", unit: "million", get: (d, y) => d.feats[y] && (d.feats[y].population_mn * d.feats[y].urban_population_pct) / 100 },
    { label: "Population density", unit: "per km²", get: (d, y) => d.feats[y]?.population_density },
  ],
  OTHER: [
    { label: "Coal dependence (power ÷ total CO₂)", unit: "%", get: (d, y) => (d.feats[y]?.coal_dependence ?? null) && 100 * d.feats[y].coal_dependence },
  ],
};

function Delta({ v }: { v: number | null | undefined }) {
  if (v == null || !Number.isFinite(v)) return <span className="text-slate-500 dark:text-slate-500">—</span>;
  const up = v >= 0;
  return <span className={cn("inline-flex items-center", up ? "text-amber-400" : "text-emerald-400")}>{up ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{fmt(Math.abs(v), 1)}%</span>;
}

export function SectorBreakdown({ d }: { d: D }) {
  const drivers = useQuery({ queryKey: ["drivers"], queryFn: () => api("/api/v2/drivers"), retry: false, staleTime: Infinity });
  const y = d.lastObs, y0 = y - 10;
  const stacked = useMemo(() => [
    ...d.years.map((yy) => Object.fromEntries([["year", yy], ...SECTORS.map((s) => [s, d.bySector[s][yy] ?? 0])])),
    ...d.fcYears.map((yy) => Object.fromEntries([["year", yy], ...SECTORS.map((s) => {
      const p = d.secFc[s]?.find((q) => q.year === yy); return [s, p ? d.val(p) : 0];
    })])),
  ], [d]);
  const tot = d.total[y] ?? 0;
  const donut = SECTORS.map((s) => ({ name: SECTOR_LABEL[s], s, v: d.bySector[s][y] ?? 0 }));
  const wf = useMemo(() => {
    const out: any[] = [{ name: `${y0} total`, base: 0, v: d.total[y0] ?? 0, kind: "total", lab: fmt(d.total[y0], 0) }];
    let cum = d.total[y0] ?? 0;
    for (const s of SECTORS) {
      const dv = (d.bySector[s][y] ?? 0) - (d.bySector[s][y0] ?? 0);
      out.push({ name: SECTOR_LABEL[s], base: dv >= 0 ? cum : cum + dv, v: Math.abs(dv), delta: dv, kind: dv >= 0 ? "up" : "down", s,
        lab: `${dv >= 0 ? "+" : "−"}${fmt(Math.abs(dv), 1)}` });
      cum += dv;
    }
    out.push({ name: `${y} total`, base: 0, v: d.total[y] ?? 0, kind: "total", lab: fmt(d.total[y], 0) });
    return out;
  }, [d, y, y0]);
  const how = (formula: string, inputs?: string, note?: string) => ({ formula, inputs, note });

  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-2"><h2 className="text-lg font-semibold">Sector breakdown</h2>
        <span className="text-xs text-slate-500 dark:text-slate-500">7 sectors · CO₂e with IPCC AR6 GWP-100 · forecasts reconciled so sectors sum to the state total</span></div>
      <div className="grid gap-4 @3xl:grid-cols-[1.6fr_1fr]">
        <ChartCard name={`${d.name}_sector_stack`} title="1 · Sector composition over time" sub="Stacked: each band is one sector; the top edge is the state total" data={stacked}
          unit="MtCO₂e" source={SRC_EDGAR} loading={d.loading}
          how={how("Band height = sector CO₂e; stack top = Σ sectors = state total", "EDGAR CO₂/CH₄/N₂O sub-sector grids mapped to 7 sectors", "Right-hand shaded years are the reconciled forecast (P50).")}
          legend={SECTORS.map((s) => <span key={s} className="flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: colorOf(s) }} />{SECTOR_LABEL[s]}</span>)}>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={stacked} margin={{ left: 4, right: 12, top: 8 }}>
              <XAxis {...yearAxis(stacked as any)} {...AX} />
              <YAxis {...AX} width={50} />
              <Tooltip contentStyle={TT} formatter={(v: any, n: any) => [`${fmt(v, 1)} Mt`, SECTOR_LABEL[n] ?? n]} labelFormatter={(yy: any) => `${yy}${Number(yy) > y ? " (forecast)" : ""}`} />
              {d.fcYears.length > 0 && <ReferenceArea x1={y} x2={d.fcYears[d.fcYears.length - 1]} fill="#ffffff" fillOpacity={0.06} label={{ value: "forecast", position: "insideTop", fill: "#94a3b8", fontSize: 10 }} />}
              {SECTORS.map((s) => <Area key={s} type="monotone" dataKey={s} stackId="1" stroke={colorOf(s)} fill={colorOf(s)} fillOpacity={0.85} isAnimationActive={false} />)}
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard name={`${d.name}_donut`} title={`3 · Sector share, ${y}`} sub={`Total ${fmt(tot, 1)} MtCO₂e`} data={donut} unit="% of state CO₂e" source={SRC_EDGAR}
          how={how("Share = sector CO₂e ÷ Σ sectors × 100")} loading={d.loading}>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={donut} dataKey="v" nameKey="name" innerRadius={62} outerRadius={105} paddingAngle={1} stroke="none" isAnimationActive={false}
                label={({ name, value }: any) => (tot && value / tot > 0.04 ? `${name} ${Math.round((100 * value) / tot)}%` : "")} labelLine={false} fontSize={10}>
                {donut.map((x) => <Cell key={x.s} fill={colorOf(x.s)} />)}
              </Pie>
              <Tooltip contentStyle={TT} formatter={(v: any, n: any) => [`${fmt(v, 1)} Mt (${fmt((100 * v) / (tot || 1), 1)}%)`, n]} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <ChartCard name={`${d.name}_small_multiples`} title="2 · Every sector's own trajectory" unit="MtCO₂e (each panel has its own scale)" source={SRC_EDGAR}
        sub="Green area = observed · blue = forecast P50 with P10–P90 fan · arrow = 10-year compound annual growth (CAGR)"
        how={how("CAGR = (value_end ÷ value_start)^(1/years) − 1", `${y0}→${y} observed; forecast = reconciled sector P50`)} loading={d.loading}>
        <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-4 @5xl:grid-cols-7">
          {SECTORS.map((s) => {
            const rows: any[] = d.years.filter((yy) => yy >= 2000).map((yy) => ({ year: yy, hist: d.bySector[s][yy] }));
            const f = d.secFc[s] ?? [];
            const last = rows[rows.length - 1];
            if (last && f.length) Object.assign(last, { p50: last.hist, band: [last.hist, last.hist] });
            rows.push(...f.map((p) => ({ year: p.year, p50: d.val(p), band: [p.p10, p.p90] })));
            const g = d.cagr(d.bySector[s][y0], d.bySector[s][y]);
            return (
              <div key={s} className="rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/[0.02] p-2">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1 font-medium"><i className="inline-block h-2 w-2 rounded-full" style={{ background: colorOf(s) }} />{SECTOR_LABEL[s]}</span>
                  <Delta v={g} />
                </div>
                <div className="text-sm font-semibold tabular-nums">{fmt(d.bySector[s][y], 1)} <span className="text-[10px] font-normal text-slate-500 dark:text-slate-500">Mt</span></div>
                <div className="h-20">
                  <ResponsiveContainer>
                    <ComposedChart data={rows} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                      <XAxis dataKey="year" hide type="number" domain={["dataMin", "dataMax"]} />
                      <YAxis hide domain={[0, "auto"]} />
                      <Tooltip contentStyle={TT} formatter={(v: any) => (Array.isArray(v) ? `${fmt(v[0], 2)}–${fmt(v[1], 2)}` : fmt(v, 2))} />
                      <Area dataKey="band" stroke="none" fill={FC} fillOpacity={0.25} isAnimationActive={false} />
                      <Area dataKey="hist" stroke={colorOf(s)} strokeWidth={1.8} fill={colorOf(s)} fillOpacity={0.25} isAnimationActive={false} />
                      <Line dataKey="p50" stroke={FC} strokeWidth={1.6} dot={false} isAnimationActive={false} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <div className="text-[10px] text-slate-500 dark:text-slate-500">{f.length ? `${f[f.length - 1].year}: ${fmt(d.val(f[f.length - 1]), 1)} Mt` : ""}</div>
              </div>
            );
          })}
        </div>
      </ChartCard>

      <div className="grid gap-4 @3xl:grid-cols-2">
        <ChartCard name={`${d.name}_waterfall`} title={`4 · What changed, ${y0} → ${y}`} data={wf.map(({ name, delta, v }) => ({ name, delta_mt: delta ?? v }))}
          sub="Grey = totals · amber = sector increase · green = sector decrease" unit="MtCO₂e" source={SRC_EDGAR}
          how={how("Δ sector = CO₂e(end) − CO₂e(start); end total = start total + Σ Δ sectors")} loading={d.loading}>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={wf} margin={{ left: 4, right: 8, top: 16 }}>
              <XAxis dataKey="name" {...AX} fontSize={10} interval={0} angle={-25} textAnchor="end" height={50} />
              <YAxis {...AX} width={50} />
              <Tooltip contentStyle={TT} formatter={(v: any, n: any, p: any) => (n === "base" ? [null, null] : [p.payload.delta != null ? `${p.payload.delta >= 0 ? "+" : "−"}${fmt(Math.abs(p.payload.delta), 1)} Mt` : `${fmt(v, 1)} Mt`, p.payload.name])} />
              <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
              <Bar dataKey="v" stackId="w" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                {wf.map((r) => <Cell key={r.name} fill={r.kind === "total" ? "#64748b" : r.kind === "up" ? "#f59e0b" : "#10b981"} />)}
                <LabelList dataKey="lab" position="top" fontSize={10} fill="#cbd5e1" />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard name={`${d.name}_intensity`} title="6 · Sector carbon intensity" unit="tCO₂e per ₹ crore real GSDP (2011-12 prices)" source={`${SRC_EDGAR} · MoSPI GSDP`}
          sub={`Emissions per unit of economic output, ${d.years.find((yy) => yy >= 2000) ?? 2000}–${y}. Falling = decoupling.`}
          how={how("Sector intensity = sector CO₂e (t) ÷ state real GSDP (₹ crore)", "GSDP at 2011-12 prices; years before FY2011 are back-cast")} loading={d.loading}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 @xl:grid-cols-3">
            {SECTORS.map((s) => {
              const rows = d.years.filter((yy) => yy >= 2000 && d.gsdp[yy]).map((yy) => ({ year: yy, v: ((d.bySector[s][yy] ?? 0) * 1e6) / d.gsdp[yy] }));
              const a = rows[0]?.v, b = rows[rows.length - 1]?.v;
              return (
                <div key={s}>
                  <div className="flex items-center justify-between text-[11px]"><span style={{ color: colorOf(s) }}>{SECTOR_LABEL[s]}</span>
                    <span className="tabular-nums text-slate-700 dark:text-slate-300">{fmt(b, b != null && b < 10 ? 1 : 0)}</span></div>
                  <div className="h-8"><ResponsiveContainer><LineChart data={rows}><YAxis hide domain={["auto", "auto"]} />
                    <Line dataKey="v" stroke={colorOf(s)} dot={false} strokeWidth={1.5} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
                  <div className="text-[10px] text-slate-500 dark:text-slate-500">{a && b ? <>since {rows[0].year}: <Delta v={100 * (b / a - 1)} /></> : "—"}</div>
                </div>
              );
            })}
          </div>
        </ChartCard>
      </div>

      <ChartCard name={`${d.name}_drivers`} title="5 · Top drivers per sector" sub={`Measured activity drivers (${y0} → ${y}) and what most influences each sector's forecast`}
        source="CEA · MoSPI · Census · NASA POWER · EDGAR"
        how={how("Influence % = share of the forecast-error increase when an input group is randomly shuffled (permutation importance), normalised to 100 %",
          "Driver values are the observed series used as model inputs", "Chips show the latest value and the change since " + y0 + "; '—' = source not available for this state/year.")}>
        <div className="grid gap-3 @2xl:grid-cols-2 @5xl:grid-cols-4">
          {SECTORS.map((s) => {
            const inf = Object.entries(drivers.data?.sectors?.[s] ?? {}).slice(0, 3);
            const mets = DRIVER_METRICS[s].map((m) => ({ ...m, now: m.get(d, y), then: m.get(d, y0) })).filter((m) => m.now != null && Number.isFinite(m.now as number)).slice(0, 3);
            return (
              <div key={s} className="rounded-lg border border-slate-200 dark:border-white/10 p-2.5" style={{ borderLeft: `3px solid ${colorOf(s)}` }}>
                <div className="text-xs font-semibold">{SECTOR_LABEL[s]}</div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {mets.length ? mets.map((m) => (
                    <span key={m.label} className="rounded-full bg-slate-100 dark:bg-white/5 px-2 py-0.5 text-[10px] text-slate-700 dark:text-slate-300">
                      {m.label}: <b className="tabular-nums">{fmt(m.now as number, (m.now as number) < 10 ? 2 : 0)}</b> {m.unit}{" "}
                      {m.then ? <Delta v={100 * ((m.now as number) / (m.then as number) - 1)} /> : null}
                    </span>
                  )) : <span className="text-[10px] text-slate-500 dark:text-slate-500">No activity data for this sector yet (see Methodology → data gaps).</span>}
                </div>
                {inf.length > 0 && (
                  <div className="mt-2 space-y-0.5">
                    {inf.map(([g, w]) => (
                      <div key={g} className="flex items-center gap-1.5 text-[10px] text-slate-600 dark:text-slate-400">
                        <span className="w-32 truncate">{GROUP_LABEL[g] ?? g}</span>
                        <div className="h-1.5 flex-1 rounded bg-slate-100 dark:bg-white/5"><div className="h-full rounded" style={{ width: `${100 * (w as number)}%`, background: colorOf(s) }} /></div>
                        <span className="w-8 text-right tabular-nums">{Math.round(100 * (w as number))}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </ChartCard>
    </div>
  );
}

export function KpiRow({ d, accent = "#10b981" }: { d: D; accent?: string }) {
  const k = d.kpis;
  const items: [string, string, string, string][] = [
    ["Total CO₂e", fmt(k.total, 1), "MtCO₂e", "Σ 7 sectors, AR6 GWP-100"],
    ["Per capita", fmt(k.perCapita, 2), "t/person", "CO₂e ÷ population"],
    ["Carbon intensity", fmt(k.intensity, 0), "t/₹ crore", "CO₂e ÷ real GSDP (2011-12 ₹)"],
    ["10-yr CAGR", k.cagr10 == null ? "—" : `${k.cagr10 >= 0 ? "+" : ""}${fmt(k.cagr10, 1)}%`, "per year", `(CO₂e ${d.lastObs} ÷ CO₂e ${d.lastObs - 10})^(1/10) − 1`],
    ["Largest sector", SECTOR_LABEL[k.topSector] ?? "—", `${fmt(100 * k.topShare, 0)}% of total`, "highest sector CO₂e"],
    [`Forecast ${k.fcYear ?? ""}`, fmt(k.fc5, 1), "MtCO₂e (P50)", "Σ reconciled sector P50"],
  ];
  return (
    <div className="@container"><div className="grid grid-cols-2 gap-2 @xl:grid-cols-3 @5xl:grid-cols-6">
      {items.map(([l, v, u, f]) => (
        <div key={l} className="rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-white/[0.03] px-3 py-2" style={{ borderTop: `2px solid ${accent}` }}>
          <div className="flex items-center justify-between gap-1 text-[11px] text-slate-600 dark:text-slate-400"><span className="truncate">{glossify(l)}</span><Info how={{ formula: f, source: SRC_EDGAR }} /></div>
          <div className="text-lg font-semibold tabular-nums">{v}</div>
          <div className="text-[10px] text-slate-500 dark:text-slate-500">{glossify(u)} · {d.lastObs}</div>
        </div>
      ))}
    </div></div>
  );
}

