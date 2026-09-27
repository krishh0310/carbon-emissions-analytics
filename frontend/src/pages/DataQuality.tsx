import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { useBi } from "../lib/i18n";
import { ChartCard } from "../components/ChartCard";
import { Table, fmt } from "../components/ui";

const TT = { background: "#0f172a", border: "1px solid #334155", fontSize: 12 };

export default function DataQuality() {
  const bi = useBi();
  const q = useQuery({ queryKey: ["dq"], queryFn: () => api("/data-quality") });
  const cov: any[] = q.data?.coverage ?? [];
  const states = [...new Set(cov.map((r) => r.state_code))].sort();
  const years = [...new Set(cov.map((r) => r.year))].sort();
  const cell = Object.fromEntries(cov.map((r) => [`${r.state_code}|${r.year}`, r.coverage]));
  const cmp: any[] = q.data?.edgar_vs_cea ?? [];
  const cmpS: any[] = (q.data?.edgar_vs_cea_state ?? []).filter((r: any) => (r.edgar_power_mt ?? 0) + (r.cea_power_co2_mt ?? 0) > 5)
    .sort((a: any, b: any) => b.cea_power_co2_mt - a.cea_power_co2_mt);

  return (
    <div className="grid gap-4">
      <ChartCard name="coverage" title={bi("Coverage heatmap")} data={cov} loading={q.isLoading}
        sub="Share of core series present per state × year: EDGAR CO₂, real GSDP, population, climate, CEA power CO₂ (CEA baseline DB starts FY2017).">
        <div className="overflow-x-auto">
          <div className="grid gap-px text-[9px]" style={{ gridTemplateColumns: `48px repeat(${years.length}, minmax(12px,1fr))` }}>
            <div />
            {years.map((y) => <div key={y} className="rotate-[-60deg] text-slate-500">{y % 5 === 0 ? y : ""}</div>)}
            {states.map((s) => [
              <div key={s} className="text-slate-500">{s}</div>,
              ...years.map((y) => {
                const v = cell[`${s}|${y}`] ?? 0;
                return <div key={s + y} title={`${s} ${y}: ${Math.round(v * 100)}%`} className="h-3"
                  style={{ background: v >= 0.99 ? "#10b981" : v >= 0.79 ? "#14b8a6aa" : v >= 0.59 ? "#f59e0b" : "#f43f5e" }} />;
              }),
            ])}
          </div>
        </div>
        <p className="mt-2 text-[11px] text-slate-500">Green = 5/5 series · teal = 4/5 (typically pre-2017, no CEA) · amber = 3/5 · red ≤ 2/5.</p>
      </ChartCard>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard name="edgar_vs_cea_national" title="EDGAR vs CEA — power-sector CO₂ (India)" sub="Sum over states, MtCO₂. EDGAR ENE sector vs CEA plant-level baseline database (FY→calendar year t)." data={cmp} loading={q.isLoading}>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={cmp}>
              <CartesianGrid stroke="#33415555" />
              <XAxis dataKey="year" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} width={45} />
              <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 0)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line dataKey="edgar_power_mt" name="EDGAR ENE" stroke="#14b8a6" strokeWidth={2} />
              <Line dataKey="cea_power_co2_mt" name="CEA" stroke="#f59e0b" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard name="edgar_vs_cea_state" title="EDGAR vs CEA by state (latest year)" sub="Large gaps = EDGAR's proxy-based spatial allocation of power plants differs from CEA plant locations." data={cmpS} loading={q.isLoading}>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={cmpS}>
              <XAxis dataKey="state_code" stroke="#64748b" fontSize={10} interval={0} angle={-60} textAnchor="end" height={45} />
              <YAxis stroke="#64748b" fontSize={11} width={40} />
              <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 1)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="edgar_power_mt" name="EDGAR" fill="#14b8a6" />
              <Bar dataKey="cea_power_co2_mt" name="CEA" fill="#f59e0b" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
      <ChartCard name="imputations" title={bi("Imputation report")} data={q.data?.imputations} loading={q.isLoading}>
        <Table head={["Feature", "Method", "# values", "Note"]}
          rows={(q.data?.imputations ?? []).map((r: any) => [r.feature, r.method, r.n_values, <span className="text-xs text-slate-500">{r.note}</span>])} />
      </ChartCard>
    </div>
  );
}
