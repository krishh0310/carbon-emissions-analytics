import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useBi, useT } from "../lib/i18n";
import { IndiaMap, Legend } from "../components/IndiaMap";
import { ChartCard } from "../components/ChartCard";
import { Badge, Card, Select, Skeleton, fmt } from "../components/ui";

const METRICS = {
  co2_mt: { label: "Total emissions", unit: "MtCO₂" },
  co2_per_capita: { label: "Per capita", unit: "tCO₂/person" },
  carbon_intensity: { label: "Carbon intensity", unit: "tCO₂ per ₹ crore (2011-12 prices)" },
} as const;
type M = keyof typeof METRICS;

export default function MapOverview() {
  const [year, setYear] = useState(2024);
  const [metric, setMetric] = useState<M>("co2_mt");
  const nav = useNavigate();
  const t = useT();
  const bi = useBi();
  const q = useQuery({ queryKey: ["states", year], queryFn: () => api(`/states?year=${year}&limit=50`) });
  const items: any[] = q.data?.items ?? [];
  const values = items.map((s) => s[metric]).filter((v) => v != null);
  const top = [...items].sort((a, b) => (b[metric] ?? -1) - (a[metric] ?? -1)).slice(0, 10);
  const national = items.reduce((a, s) => a + (s.co2_mt ?? 0), 0);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <ChartCard
        name={`india_${metric}_${year}`}
        title={bi("India Map")}
        sub={`${t(METRICS[metric].label)} · ${year} · EDGAR-downscaled estimates · ${t("Click a state to drill down")}`}
        data={items.map(({ geometry, ...r }) => r)}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Select label={t("Metric")} value={metric} onChange={(e) => setMetric(e.target.value as M)}>
              {Object.entries(METRICS).map(([k, v]) => <option key={k} value={k}>{t(v.label)}</option>)}
            </Select>
          </div>
        }
      >
        {q.isLoading ? <Skeleton className="h-[520px]" /> : (
          <IndiaMap unit={METRICS[metric].unit} onSelect={(c) => nav(`/state/${c}`)}
            states={items.map((s) => ({ code: s.code, name: s.name, value: s[metric], geometry: s.geometry }))} />
        )}
        <div className="mt-3 flex flex-col gap-2">
          <Legend values={values} unit={METRICS[metric].unit} />
          <label className="flex items-center gap-3 text-xs text-slate-500">
            {t("Year")}
            <input type="range" min={1990} max={2024} value={year} onChange={(e) => setYear(+e.target.value)}
              className="w-full accent-emerald-500" aria-label="Year" />
            <span className="w-10 font-mono text-slate-300">{year}</span>
          </label>
        </div>
      </ChartCard>
      <div className="flex flex-col gap-4">
        <Card>
          <div className="text-xs text-slate-500">India (sum of 36 states/UTs), {year}</div>
          <div className="mt-1 text-3xl font-semibold tracking-tight">{fmt(national, 0)} <span className="text-base font-normal text-slate-500">MtCO₂</span></div>
          <p className="mt-2 text-xs text-slate-500">Fossil CO₂ from EDGAR 2025 0.1° grid, area-weighted to state boundaries. Excludes international bunkers. Typical subnational uncertainty ±20–50%.</p>
        </Card>
        <Card>
          <div className="mb-2 text-sm font-semibold">Top 10 · {t(METRICS[metric].label)}</div>
          {q.isLoading ? <Skeleton className="h-60" /> : (
            <ol className="space-y-1.5 text-sm">
              {top.map((s, i) => (
                <li key={s.code} className="flex cursor-pointer items-center justify-between rounded px-1 hover:bg-slate-100 dark:hover:bg-slate-800"
                  onClick={() => nav(`/state/${s.code}`)}>
                  <span><span className="mr-2 text-slate-500">{i + 1}</span>{s.name}{s.is_ut && <Badge className="ml-1">UT</Badge>}</span>
                  <span className="tabular-nums">{fmt(s[metric], metric === "co2_mt" ? 1 : 2)}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </div>
  );
}
