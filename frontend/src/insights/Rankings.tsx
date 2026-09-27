import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api } from "../lib/api";
import { LangCtx, useBi } from "../lib/i18n";
import { ChartCard } from "../components/ChartCard";
import { Badge, Table, fmt } from "../components/ui";
import { useContext } from "react";

const TT = { background: "#0f172a", border: "1px solid #334155", fontSize: 12 };

export default function Rankings() {
  const bi = useBi();
  const { lang } = useContext(LangCtx);
  const nm = (r: any) => (lang === "hi" && r.name_hi ? r.name_hi : r.name ?? r.state_code);
  const dec = useQuery({ queryKey: ["ins", "decoupling"], queryFn: () => api("/insights/decoupling?limit=50") });
  const ci = useQuery({ queryKey: ["ins", "ci"], queryFn: () => api("/insights/carbon-intensity?limit=50") });
  const wl = useQuery({ queryKey: ["ins", "wl"], queryFn: () => api("/insights/watchlist?limit=50") });
  const d: any[] = dec.data?.items ?? [];
  const c: any[] = ci.data?.items ?? [];
  const w: any[] = wl.data?.items ?? [];
  const y = dec.data?.year;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard name="decoupling" title={bi("Decoupling leaderboard")} data={d} loading={dec.isLoading}
        sub={`10-year CAGR ${y ? y - 10 : ""}–${y ?? ""}: real GSDP vs CO₂. Above diagonal = economy outgrew emissions. Absolute = CO₂ fell while GSDP grew.`}>
        <ResponsiveContainer width="100%" height={320}>
          <ScatterChart margin={{ bottom: 10 }}>
            <CartesianGrid stroke="#33415555" />
            <XAxis type="number" dataKey="co2_cagr" name="CO₂ CAGR %" stroke="#64748b" fontSize={11} label={{ value: "CO₂ CAGR %", position: "insideBottom", offset: -5, fill: "#64748b", fontSize: 11 }} />
            <YAxis type="number" dataKey="gsdp_cagr" name="GSDP CAGR %" stroke="#64748b" fontSize={11} width={40} />
            <ZAxis range={[40, 40]} />
            <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 2)} labelFormatter={() => ""} cursor={{ strokeDasharray: "3 3" }}
              content={({ payload }) => payload?.[0] ? <div style={TT} className="rounded p-2">{nm(payload[0].payload)}<br />GSDP {fmt(payload[0].payload.gsdp_cagr)}% · CO₂ {fmt(payload[0].payload.co2_cagr)}%</div> : null} />
            <Scatter data={d}>
              {d.map((r) => <Cell key={r.state_code} fill={r.status === "absolute" ? "#10b981" : r.status === "relative" ? "#14b8a6" : "#f43f5e"} />)}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
        <Table head={["State", "GSDP CAGR", "CO₂ CAGR", "Status"]}
          rows={d.slice(0, 8).map((r) => [nm(r), `${fmt(r.gsdp_cagr)}%`, `${fmt(r.co2_cagr)}%`,
            <Badge tone={r.status === "absolute" ? "A" : r.status === "relative" ? "B" : "danger"}>{r.status}{r.gsdp_imputed ? "*" : ""}</Badge>])} />
        <p className="mt-1 text-[11px] text-slate-500">* GSDP imputed (no MoSPI series) — treat with caution.</p>
      </ChartCard>
      <ChartCard name="carbon_intensity" title={bi("Carbon-intensity ranking")} sub="tCO₂ per ₹ crore real GSDP (2011-12 prices)" data={c} loading={ci.isLoading}>
        <ResponsiveContainer width="100%" height={560}>
          <BarChart data={c} layout="vertical" margin={{ left: 10 }}>
            <XAxis type="number" stroke="#64748b" fontSize={11} />
            <YAxis type="category" dataKey={nm} stroke="#64748b" fontSize={10} width={120} interval={0} />
            <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 0)} />
            <Bar dataKey="tco2_per_crore" name="tCO₂/₹cr" radius={[0, 3, 3, 0]}>
              {c.map((r) => <Cell key={r.state_code} fill={r.coal_dependence > 0.5 ? "#f59e0b" : "#14b8a6"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="text-[11px] text-slate-500">Amber = power sector is &gt;50% of state CO₂ (coal-dependence proxy).</p>
      </ChartCard>
      <ChartCard className="lg:col-span-2" name="watchlist" title={bi("Watchlist")} data={w} loading={wl.isLoading}
        sub={`${wl.data?.notes?.fair_share ?? ""} ${wl.data?.notes?.watchlist ?? ""} Forecast: CarbonScope Forecast (P50, 5-year).`}>
        <Table head={["State", "5-yr forecast CAGR", "Fair-share CAGR", "Excess (pp)", "2029 P50 (Mt)", "P90", "Coal dep.", ""]}
          rows={w.map((r) => [nm(r), `${fmt(r.forecast_cagr_5y)}%`, `${fmt(r.fair_share_cagr_5y)}%`, fmt(r.excess_pp),
            fmt(r.forecast_2029_mt), fmt(r.p90_mt), `${fmt(100 * r.coal_dependence, 0)}%`,
            r.on_watchlist ? <Badge tone="danger">watch</Badge> : <Badge>ok</Badge>])} />
      </ChartCard>
      <ChartCard className="lg:col-span-2" name="per_capita" title="Per-capita emissions (tCO₂/person)" data={c} loading={ci.isLoading}>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={[...c].sort((a, b) => b.per_capita_t - a.per_capita_t)}>
            <XAxis dataKey="state_code" stroke="#64748b" fontSize={10} interval={0} angle={-60} textAnchor="end" height={50} />
            <YAxis stroke="#64748b" fontSize={11} width={35} />
            <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 2)} labelFormatter={(l) => nm(c.find((r) => r.state_code === l) ?? { state_code: l })} />
            <Bar dataKey="per_capita_t" fill="#10b981" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>
    </div>
  );
}
