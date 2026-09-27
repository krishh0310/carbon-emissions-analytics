// Insights: ATAR intelligence feed (every card = chart + narrative + formula) and the ranking tables.
import { lazy, Suspense, useContext, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { LayoutGrid, List, Search, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { LangCtx } from "../lib/i18n";
import { cn } from "../components/ui";
import { SECTORS, SECTOR_LABEL } from "../lib/sectors";
import { InsightCard, InsightSkeleton, SEV, TYPE_LABEL } from "../insights/InsightCard";

const Rankings = lazy(() => import("../insights/Rankings"));

export default function Insights() {
  const nav = useNavigate();
  const { lang, setLang } = useContext(LangCtx);
  const [tab, setTab] = useState<"feed" | "rank">("feed");
  const [view, setView] = useState<"grid" | "feed">("grid");
  const [sev, setSev] = useState<string[]>([]);
  const [sector, setSector] = useState("");
  const [type, setType] = useState("");
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(12);
  const states = useQuery({ queryKey: ["states-list"], queryFn: () => api("/states?limit=50&geometry=false") });
  const ins = useQuery({
    queryKey: ["atar", sector, type, state, q],
    queryFn: () => api(`/api/v2/insights?limit=200${sector ? `&sector=${sector}` : ""}${type ? `&type=${type}` : ""}${state ? `&state=${state}` : ""}${q.length > 2 ? `&q=${encodeURIComponent(q)}` : ""}`),
  });
  const items: any[] = useMemo(() => (ins.data?.items ?? []).filter((i: any) => !sev.length || sev.includes(i.severity)), [ins.data, sev]);
  const counts = useMemo(() => Object.fromEntries(Object.keys(SEV).map((k) => [k, (ins.data?.items ?? []).filter((i: any) => i.severity === k).length])), [ins.data]);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-lg border border-slate-200 dark:border-white/10 text-sm">
          <button onClick={() => setTab("feed")} className={cn("flex items-center gap-1.5 px-3 py-1.5", tab === "feed" ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-200" : "text-slate-600 dark:text-slate-400")}><Sparkles size={14} />Intelligence feed</button>
          <button onClick={() => setTab("rank")} className={cn("px-3 py-1.5", tab === "rank" ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-200" : "text-slate-600 dark:text-slate-400")}>Rankings & tables</button>
        </div>
        <button onClick={() => setLang(lang === "en" ? "hi" : "en")} className="rounded-lg border border-slate-200 dark:border-white/10 px-2.5 py-1.5 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/5">
          {lang === "en" ? "हिन्दी में पढ़ें" : "Read in English"}
        </button>
      </div>

      {tab === "rank" ? <Suspense fallback={<InsightSkeleton />}><Rankings /></Suspense> : (
        <>
          <div className="grid gap-2 rounded-2xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-900/60 p-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search size={13} className="absolute left-2.5 top-2 text-slate-500 dark:text-slate-500" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search insights…" aria-label="Search insights"
                  className="h-7 w-52 rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 pl-8 pr-2 text-xs outline-none focus:border-emerald-400/50" />
              </div>
              {Object.entries(SEV).map(([k, s]) => (
                <button key={k} onClick={() => setSev(sev.includes(k) ? sev.filter((x) => x !== k) : [...sev, k])}
                  className={cn("w-[86px] rounded-full px-2.5 py-1 text-left text-[11px] font-medium transition", sev.includes(k) ? cn("bg-gradient-to-r text-white", s.chip) : "bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200")}>
                  {lang === "hi" ? s.hi : s.label} <span className="float-right w-5 text-right opacity-70">{ins.isLoading ? "" : counts[k] ?? 0}</span>
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select value={type} onChange={(e) => setType(e.target.value)} className="h-7 w-36 rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 px-1.5 text-xs" aria-label="Insight type">
                <option value="">All types</option>{Object.entries(TYPE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              <select value={sector} onChange={(e) => setSector(e.target.value)} className="h-7 w-32 rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 px-1.5 text-xs" aria-label="Sector">
                <option value="">All sectors</option>{SECTORS.map((s) => <option key={s} value={s}>{SECTOR_LABEL[s]}</option>)}
              </select>
              <select value={state} onChange={(e) => setState(e.target.value)} className="h-7 w-48 rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 px-1.5 text-xs" aria-label="State">
                <option value="">All states + India</option><option value="NATIONAL">India (national)</option>
                {(states.data?.items ?? []).map((s: any) => <option key={s.code} value={s.code}>{s.name}</option>)}
              </select>
              <div className="ml-auto flex overflow-hidden rounded-lg border border-slate-200 dark:border-white/10">
                <button aria-label="Grid view" onClick={() => setView("grid")} className={cn("p-1.5", view === "grid" ? "bg-slate-200 dark:bg-white/10" : "text-slate-500 dark:text-slate-500")}><LayoutGrid size={14} /></button>
                <button aria-label="Feed view" onClick={() => setView("feed")} className={cn("p-1.5", view === "feed" ? "bg-slate-200 dark:bg-white/10" : "text-slate-500 dark:text-slate-500")}><List size={14} /></button>
              </div>
            </div>
          </div>
          <p className="min-h-[4em] text-[11px] text-slate-500 dark:text-slate-500 sm:min-h-[2.5em]">
            {ins.isLoading ? "…" : items.length} insights generated automatically from the emission panels and the CarbonScope Forecast. Every card shows the chart behind it and, under
            “How is this calculated?”, the exact formula, inputs, data source and date. Estimates are EDGAR-downscaled (not official inventories).
          </p>
          {ins.isLoading ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 12 }, (_, k) => <InsightSkeleton key={k} />)}</div>
          ) : items.length === 0 ? (
            <div className="grid place-items-center rounded-2xl border border-dashed border-slate-200 dark:border-white/10 py-16 text-center text-sm text-slate-500 dark:text-slate-500">
              <Sparkles className="mb-2 text-slate-600" />No insights match these filters.<button className="mt-2 text-emerald-400 hover:underline" onClick={() => { setSev([]); setType(""); setSector(""); setState(""); setQ(""); }}>Clear filters</button>
            </div>
          ) : (
            <div className={cn("grid gap-3", view === "grid" ? "md:grid-cols-2 xl:grid-cols-3" : "mx-auto w-full max-w-3xl")}>
              {items.slice(0, shown).map((i) => <InsightCard key={i.id} i={i} onGo={(c) => nav(`/state/${c}`)} />)}
            </div>
          )}
          {!ins.isLoading && items.length > shown && (
            <button onClick={() => setShown(shown + 12)} className="mx-auto rounded-lg border border-slate-200 dark:border-white/10 px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/5">
              Show more ({items.length - shown} remaining)
            </button>
          )}
        </>
      )}
    </div>
  );
}
