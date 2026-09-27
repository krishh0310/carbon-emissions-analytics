// State Explorer: KPIs, history+forecast (full-opacity history, connected fan), 6-part sector deep-dive, compare mode.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { GitCompare, X } from "lucide-react";
import { api } from "../lib/api";
import { Select } from "../components/ui";
import { useStateData } from "../state/useStateData";
import { HistoryForecast, KpiRow, SectorBreakdown } from "../state/StateCharts";
import { Compare } from "../state/Compare";

/** Reusable body (also used by the Live Map slide-over). */
export function StateView({ code, compact = false }: { code: string; compact?: boolean }) {
  const [other, setOther] = useState<string | null>(null);
  const states = useQuery({ queryKey: ["states-list"], queryFn: () => api("/states?limit=50&geometry=false") });
  const a = useStateData(code);
  const b = useStateData(other);
  const opts = (states.data?.items ?? []) as any[];
  return (
    // @container: grids below respond to this panel's width (full page or Live Map slide-over), not the viewport
    <div className="@container grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {other ? (
          <button onClick={() => setOther(null)} className="flex items-center gap-1 rounded-md border border-slate-200 dark:border-white/10 px-2 py-1 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/5"><X size={12} />Exit compare</button>
        ) : (
          <label className="flex items-center gap-1.5 text-xs text-slate-400"><GitCompare size={14} />Compare with
            <select value="" onChange={(e) => setOther(e.target.value || null)} className="h-7 rounded-md border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-slate-900 px-1.5 text-xs text-slate-900 dark:text-slate-100">
              <option value="">choose a state…</option>
              {opts.filter((s) => s.code !== code).map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select>
          </label>
        )}
      </div>
      {other ? <Compare a={a} b={b} /> : (
        <>
          <KpiRow d={a} />
          <HistoryForecast d={a} height={compact ? 300 : 380} />
          <SectorBreakdown d={a} code={code} />
        </>
      )}
    </div>
  );
}

export default function StateExplorer() {
  const { code = "IN-MH" } = useParams();
  const nav = useNavigate();
  const states = useQuery({ queryKey: ["states-list"], queryFn: () => api("/states?limit=50&geometry=false") });
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select label="State / UT" value={code} onChange={(e) => nav(`/state/${e.target.value}`)} className="min-w-56">
          {(states.data?.items ?? []).map((s: any) => <option key={s.code} value={s.code}>{s.name}{s.is_ut ? " (UT)" : ""}</option>)}
        </Select>
        <span className="text-xs text-slate-500">All values are EDGAR-downscaled estimates; the forecast is the CarbonScope Forecast (P50 with P10–P90 range).</span>
      </div>
      <StateView code={code} />
    </div>
  );
}
