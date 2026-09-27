// Premium ATAR insight card: severity header · type-specific mini-chart · narrative (EN/HI) · formula footer.
import { useContext, useEffect, useRef, useState } from "react";
import {
  Area, Bar, BarChart, Cell, ComposedChart, LabelList, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, Bell, ChevronDown, ChevronUp, Info, Zap } from "lucide-react";
import { LangCtx } from "../lib/i18n";
import { glossify } from "../lib/glossary";
import { cn, fmt } from "../components/ui";
import { SECTOR_LABEL, colorOf } from "../lib/sectors";

const TT = { background: "#020617", border: "1px solid #1e293b", borderRadius: 8, fontSize: 11 };
export const SEV: Record<string, { label: string; hi: string; chip: string; ring: string; icon: any }> = {
  alert: { label: "Alert", hi: "चेतावनी", chip: "from-rose-500 to-orange-500", ring: "hover:shadow-rose-500/20 border-rose-500/30", icon: AlertTriangle },
  warning: { label: "Watch", hi: "निगरानी", chip: "from-amber-500 to-yellow-500", ring: "hover:shadow-amber-500/20 border-amber-500/25", icon: Bell },
  notice: { label: "Notice", hi: "सूचना", chip: "from-sky-500 to-cyan-500", ring: "hover:shadow-sky-500/20 border-sky-500/20", icon: Zap },
  info: { label: "Info", hi: "जानकारी", chip: "from-slate-500 to-slate-400", ring: "hover:shadow-emerald-500/10 border-slate-200 dark:border-white/10", icon: Info },
};
export const TYPE_LABEL: Record<string, string> = {
  ANOMALY: "Anomaly", DECOUPLING: "Decoupling", WATCHLIST: "Watchlist", LEADER: "Leader", LAGGARD: "Laggard",
  DRIVERS: "Forecast drivers", COMPARISON: "Comparison", TREND: "Trend",
};

function Viz({ v, h = 130 }: { v: any; h?: number }) {
  if (!v?.series?.length) return null;
  const S = v.series;
  switch (v.kind) {
    case "deviation": // growth bars vs 5-yr trend line, latest bar highlighted
      return (
        <ResponsiveContainer width="100%" height={h}>
          <BarChart data={S} margin={{ top: 14, right: 6, left: -18, bottom: 0 }}>
            <XAxis dataKey="year" stroke="#64748b" fontSize={9} /><YAxis stroke="#64748b" fontSize={9} unit="%" />
            <Tooltip contentStyle={TT} formatter={(x: any) => `${fmt(x, 1)} %`} />
            <ReferenceLine y={v.trend} stroke="#38bdf8" strokeDasharray="4 3" label={{ value: `5-yr avg ${fmt(v.trend, 1)}%`, fill: "#7dd3fc", fontSize: 9, position: "insideTopLeft" }} />
            <ReferenceLine y={0} stroke="#475569" />
            <Bar dataKey="value" radius={2} isAnimationActive={false}>
              {S.map((r: any) => <Cell key={r.year} fill={r.is_latest ? "#f43f5e" : "#64748b"} />)}
              <LabelList dataKey="value" position="top" fontSize={8} fill="#94a3b8" formatter={(x: any) => fmt(x, 0)} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    case "dual_index":
      return (
        <ResponsiveContainer width="100%" height={h}>
          <ComposedChart data={S.map((r: any) => ({ ...r, gap: [Math.min(r.gsdp, r.co2e), Math.max(r.gsdp, r.co2e)] }))} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
            <XAxis dataKey="year" stroke="#64748b" fontSize={9} /><YAxis stroke="#64748b" fontSize={9} domain={["auto", "auto"]} />
            <Tooltip contentStyle={TT} formatter={(x: any, n: any) => [Array.isArray(x) ? "" : fmt(x, 1), n]} />
            {v.highlight_from && <ReferenceArea x1={v.highlight_from} x2={S[S.length - 1].year} fill="#10b981" fillOpacity={0.08} />}
            <Area dataKey="gap" stroke="none" fill="#10b981" fillOpacity={0.25} isAnimationActive={false} name="gap" legendType="none" />
            <Line dataKey="gsdp" name="GSDP index" stroke="#38bdf8" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="co2e" name="CO₂e index" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      );
    case "corridor":
      return (
        <ResponsiveContainer width="100%" height={h}>
          <ComposedChart data={S.map((r: any) => ({ ...r, corridor: r.fair != null ? [r.fair, r.fair_hi] : undefined }))} margin={{ top: 6, right: 6, left: -14, bottom: 0 }}>
            <XAxis dataKey="year" stroke="#64748b" fontSize={9} /><YAxis stroke="#64748b" fontSize={9} domain={["auto", "auto"]} />
            <Tooltip contentStyle={TT} formatter={(x: any, n: any) => [Array.isArray(x) ? `${fmt(x[0], 1)}–${fmt(x[1], 1)}` : fmt(x, 1), n]} />
            <Area dataKey="corridor" name="fair-share corridor" stroke="none" fill="#10b981" fillOpacity={0.25} isAnimationActive={false} />
            <Area dataKey="band" name="forecast P10–P90" stroke="none" fill="#f43f5e" fillOpacity={0.18} isAnimationActive={false} />
            <Line dataKey="observed" name="observed" stroke="currentColor" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="forecast" name="forecast P50" stroke="#f43f5e" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="fair" name="fair-share path" stroke="#10b981" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      );
    case "ranking":
      return (
        <ResponsiveContainer width="100%" height={h}>
          <BarChart data={S} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
            <XAxis dataKey="state_code" stroke="#64748b" fontSize={7} interval={0} tickFormatter={(c: string) => c.slice(3)} />
            <YAxis stroke="#64748b" fontSize={9} />
            <Tooltip contentStyle={TT} formatter={(x: any) => fmt(x, 2)} />
            <Bar dataKey="value" isAnimationActive={false}>{S.map((r: any) => <Cell key={r.state_code} fill={r.state_code === v.highlight ? "#f59e0b" : "#94a3b8"} />)}</Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    case "bars":
      return (
        <ResponsiveContainer width="100%" height={h}>
          <BarChart data={S} layout="vertical" margin={{ top: 4, right: 36, left: 8, bottom: 0 }}>
            <XAxis type="number" hide /><YAxis type="category" dataKey="name" stroke="#94a3b8" fontSize={10} width={90} />
            <Tooltip contentStyle={TT} formatter={(x: any) => fmt(x, 2)} />
            <Bar dataKey="value" radius={3} isAnimationActive={false}>
              {S.map((r: any) => <Cell key={r.name} fill={r.name === "India" ? "#64748b" : "#10b981"} />)}
              <LabelList dataKey="value" position="right" fontSize={10} fill="#cbd5e1" formatter={(x: any) => fmt(x, 2)} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    case "spark":
      return (
        <ResponsiveContainer width="100%" height={h}>
          <LineChart data={S} margin={{ top: 14, right: 8, left: -14, bottom: 0 }}>
            <XAxis dataKey="year" stroke="#64748b" fontSize={9} /><YAxis stroke="#64748b" fontSize={9} domain={["auto", "auto"]} />
            <Tooltip contentStyle={TT} formatter={(x: any) => fmt(x, 3)} />
            {v.from && <ReferenceLine x={v.from} stroke="#475569" strokeDasharray="3 3" label={{ value: `CAGR since ${v.from}: ${fmt(v.cagr, 1)}%/yr`, fill: "#94a3b8", fontSize: 9, position: "insideTopLeft" }} />}
            <Line dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      );
    case "waterfall": {
      let cum = 0;
      const rows = S.map((r: any) => {
        if (r.total) { cum = r.value; return { ...r, base: 0, bar: r.value, label: fmt(r.value, 0) }; }
        const b = r.value >= 0 ? cum : cum + r.value;
        cum += r.value;
        return { ...r, base: b, bar: Math.abs(r.value), label: `${r.value >= 0 ? "+" : "−"}${fmt(Math.abs(r.value), 1)}` };
      });
      return (
        <ResponsiveContainer width="100%" height={h}>
          <BarChart data={rows} margin={{ top: 14, right: 4, left: -14, bottom: 0 }}>
            <XAxis dataKey="name" stroke="#64748b" fontSize={8} interval={0} tickFormatter={(n: string) => SECTOR_LABEL[n]?.slice(0, 5) ?? n} />
            <YAxis stroke="#64748b" fontSize={9} domain={[(dataMin: number) => Math.floor(dataMin * 0.9), "auto"]} />
            <Tooltip contentStyle={TT} formatter={(_x: any, n: any, p: any) => (n === "base" ? [null, null] : [p.payload.label, SECTOR_LABEL[p.payload.name] ?? p.payload.name])} />
            <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
            <Bar dataKey="bar" stackId="w" isAnimationActive={false}>
              {rows.map((r: any) => <Cell key={r.name} fill={r.total ? "#64748b" : colorOf(r.name)} fillOpacity={r.total ? 1 : r.value >= 0 ? 1 : 0.5} />)}
              <LabelList dataKey="label" position="top" fontSize={8} fill="#cbd5e1" />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    }
    default:
      return null;
  }
}

export function InsightCard({ i, onGo, compact = false }: { i: any; onGo?: (code: string) => void; compact?: boolean }) {
  const { lang } = useContext(LangCtx);
  const [open, setOpen] = useState(false);
  const sev = SEV[i.severity] ?? SEV.info;
  const I = sev.icon;
  const title = lang === "hi" && i.title_hi ? i.title_hi : i.title;
  const body = lang === "hi" && i.body_hi ? i.body_hi : i.body;
  return (
    <article className={cn("group flex flex-col rounded-2xl border bg-white dark:bg-slate-900/60 p-3 shadow-lg transition duration-200 hover:-translate-y-0.5 hover:shadow-xl",
      !compact && "min-h-[430px]", sev.ring)}>
      <header className="flex flex-wrap items-center gap-1.5 text-[10px]">
        <span className={cn("inline-flex items-center gap-1 rounded-full bg-gradient-to-r px-2 py-0.5 font-semibold text-white", sev.chip)}><I size={11} />{lang === "hi" ? sev.hi : sev.label}</span>
        <span className="rounded-full bg-slate-100 dark:bg-white/5 px-2 py-0.5 text-slate-700 dark:text-slate-300">{TYPE_LABEL[i.type] ?? i.type}</span>
        {i.sector && i.state_code && onGo ? <button onClick={() => onGo(`${i.state_code}/sector/${i.sector.toLowerCase()}`)} className="cursor-pointer rounded-full px-2 py-0.5 text-slate-800 hover:underline dark:text-slate-200" style={{ background: `${colorOf(i.sector)}33` }}>{SECTOR_LABEL[i.sector]} ↗</button> : i.sector && <span className="rounded-full px-2 py-0.5 text-slate-800 dark:text-slate-200" style={{ background: `${colorOf(i.sector)}33` }}>{SECTOR_LABEL[i.sector]}</span>}
        <button disabled={!i.state_code || !onGo} onClick={() => i.state_code && onGo?.(i.state_code)}
          className="ml-auto rounded-full bg-slate-100 dark:bg-white/5 px-2 py-0.5 text-slate-700 dark:text-slate-300 enabled:hover:bg-emerald-500/20">{i.state_code ?? "India"}</button>
      </header>
      <h3 className="mt-2 text-sm font-semibold leading-snug">{title}</h3>
      {!compact && i.viz && (
        <figure className="mt-2 rounded-lg text-slate-700 dark:text-slate-200 bg-slate-50 dark:bg-black/20 p-1.5">
          <LazyViz v={i.viz} />
          <figcaption className="px-1 text-[9px] text-slate-500 dark:text-slate-500">Unit: {i.viz.unit}{i.viz.labels ? ` · green band = ${i.viz.labels.fair} → ${i.viz.labels.fair_hi}` : ""}</figcaption>
        </figure>
      )}
      <p className="mt-2 text-xs leading-relaxed text-slate-700 dark:text-slate-300">{glossify(body)}</p>
      {i.how && (
        <footer className="mt-auto pt-2">
          <button onClick={() => setOpen(!open)} aria-expanded={open}
            className="flex w-full items-center justify-between rounded-lg border border-slate-200 dark:border-white/5 bg-white dark:bg-white/[0.03] px-2 py-1.5 text-[10px] text-slate-600 dark:text-slate-400 hover:text-emerald-700 dark:hover:text-emerald-300">
            <span>{lang === "hi" ? "यह कैसे गणना की गई?" : "How is this calculated?"}</span>{open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
          <div className={cn("overflow-hidden text-[10px] leading-relaxed text-slate-600 dark:text-slate-400 transition-all", open ? "mt-1.5 max-h-96" : "max-h-0")}>
            <div className="rounded-md bg-slate-100 dark:bg-white/5 px-2 py-1.5 font-mono text-[10px] text-slate-800 dark:text-slate-200">{i.how.formula}</div>
            {i.how.inputs && <div className="mt-1"><b className="text-slate-700 dark:text-slate-300">Inputs:</b> {i.how.inputs}</div>}
            <div className="mt-0.5"><b className="text-slate-700 dark:text-slate-300">Source:</b> {i.how.source} · <b className="text-slate-700 dark:text-slate-300">Updated:</b> {i.how.updated}</div>
          </div>
          {!open && <div className="mt-1 truncate px-1 font-mono text-[9px] text-slate-600" title={i.how.formula}>ƒ {i.how.formula}</div>}
        </footer>
      )}
    </article>
  );
}

/** Mounts the chart only when the card scrolls near the viewport (keeps main-thread work low with 60+ cards). */
function LazyViz({ v }: { v: any }) {
  const ref = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || on) return;
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setOn(true); io.disconnect(); } }, { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [on]);
  return <div ref={ref} style={{ height: 130 }}>{on ? <Viz v={v} /> : null}</div>;
}

export function InsightSkeleton() {
  return <div className="h-[430px] animate-pulse rounded-2xl border border-slate-200 dark:border-white/5 bg-white dark:bg-white/[0.03]" />;
}
