// Cities: proxy-estimate analytics (no feature importance — proxy-input importance would be misleading).
import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDown, ArrowUp, ChevronDown, ChevronUp, MapPin, Plus, X } from "lucide-react";
import { api } from "../lib/api";
import { useBi } from "../lib/i18n";
import { IndiaMap } from "../components/IndiaMap";
import { ChartCard } from "../components/ChartCard";
import { Badge, Card, Input, cn, fmt } from "../components/ui";
import { SECTORS, SECTOR_LABEL, colorOf } from "../lib/sectors";

const TT = { background: "#020617", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 };
const PAL = ["#10b981", "#60a5fa", "#f472b6"];
const SRC = "EDGAR 2025 grid cells within city buffer (estimate)";
type SortKey = "co2e_mt" | "cagr10_pct" | "per_capita_t" | "share_of_state_pct" | "confidence_tier" | "name";

export default function Cities() {
  const bi = useBi();
  const [picked, setPicked] = useState<number[]>([2]);
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: "co2e_mt", desc: true });
  const [q, setQ] = useState("");
  const [how, setHow] = useState(false);
  const rank = useQuery({ queryKey: ["cities-v3"], queryFn: () => api("/api/v2/cities?limit=200") });
  const states = useQuery({ queryKey: ["states", 2024], queryFn: () => api("/states?year=2024&limit=50") });
  const details = useQueries({ queries: picked.map((id) => ({ queryKey: ["city", id], queryFn: () => api(`/api/v2/cities/${id}`) })) });
  const items: any[] = rank.data?.items ?? [];
  const rows = useMemo(() => {
    const f = items.filter((c) => `${c.name} ${c.state_code}`.toLowerCase().includes(q.toLowerCase()));
    const k = sort.k;
    return [...f].sort((a, b) => {
      const av = a[k], bv = b[k];
      if (av == null) return 1;
      if (bv == null) return -1;
      const c = typeof av === "string" ? av.localeCompare(bv) : av - bv;
      return sort.desc ? -c : c;
    });
  }, [items, q, sort]);
  const main = details[0]?.data;
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= 3 ? [...p.slice(1), id] : [...p, id]));

  const trend = useMemo(() => {
    const m: Record<number, any> = {};
    details.forEach((d, i) => {
      const c = d.data;
      if (!c) return;
      for (const h of c.history) if (h.year >= 2000) (m[h.year] ??= { year: h.year })[`c${i}`] = h.co2e_mt;
      const last = c.history[c.history.length - 1];
      if (c.forecast.length) (m[last.year] ??= { year: last.year })[`f${i}`] = last.co2e_mt;
      for (const f of c.forecast) Object.assign((m[f.year] ??= { year: f.year }), { [`f${i}`]: f.p50, [`b${i}`]: [f.p10, f.p90] });
      if (c.forecast.length) (m[last.year])[`b${i}`] = [last.co2e_mt, last.co2e_mt];
    });
    return Object.values(m).sort((a: any, b: any) => a.year - b.year);
  }, [details]);
  const split = (main?.history ?? []).filter((h: any) => h.year % 5 === 0 || h.year === main?.year).filter((h: any) => h.year >= 1995);
  const share = (main?.history ?? []).filter((h: any) => h.year >= 1995);
  const H = ({ k, children, className }: { k: SortKey; children: React.ReactNode; className?: string }) => (
    <th className={cn("cursor-pointer select-none px-2 py-2 font-medium hover:text-slate-800 dark:hover:text-slate-200", className)} onClick={() => setSort({ k, desc: sort.k === k ? !sort.desc : true })}
      aria-sort={sort.k === k ? (sort.desc ? "descending" : "ascending") : "none"}>
      <span className="inline-flex items-center gap-0.5">{children}{sort.k === k && (sort.desc ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}</span>
    </th>
  );

  return (
    <div className="grid gap-4">
      <Card className="border-amber-500/40 bg-amber-500/5 text-sm">
        <b>{bi("Estimated")}:</b> city values are <u>proxy estimates</u> — EDGAR 0.1° (~11 km) grid cells whose centre lies within
        a 25 km (metro) / 12 km buffer of the city centre. They are not measured municipal inventories; buffers can cross state lines
        (Delhi NCR) and include nearby industrial clusters. <b>Tier B</b> = metro buffer (≈16–20 cells); <b>Tier C</b> = small city (≈4 cells).
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_1.15fr]">
        <ChartCard name="cities_map" title={`${bi("Cities")} — estimated CO₂e`} sub={`${rank.data?.year ?? ""} · bubble area ∝ city estimate · state fill = state fossil CO₂ · click a bubble in the table to analyse`}
          unit="MtCO₂e (bubbles), MtCO₂ (states)" source={SRC} loading={rank.isLoading || states.isLoading}
          how={{ formula: "City CO₂e = Σ grid-cell CO₂e for cells with centre ≤ buffer radius from city centre", inputs: "EDGAR CO₂/CH₄/N₂O sector grids, AR6 GWP-100" }}
          data={items}>
          <IndiaMap unit="MtCO₂e" height={430}
            states={(states.data?.items ?? []).map((s: any) => ({ code: s.code, name: s.name, value: s.co2_mt, geometry: s.geometry }))}
            bubbles={items.map((c) => ({ id: c.id, name: c.name, lat: c.lat, lon: c.lon, value: c.co2e_mt ?? 0, tier: c.confidence_tier }))} />
        </ChartCard>

        <ChartCard name="city_trend" title={`City trend${picked.length > 1 ? " — comparison" : ""}`} data={trend}
          sub="Solid = estimated history · dashed = forecast P50 · band = P10–P90 · pick up to 3 cities in the table (+)"
          unit="MtCO₂e" source={SRC} loading={details.some((d) => d.isLoading)}
          how={{ formula: "Forecast_city = Σ_sector [ state reconciled forecast_sector × mean(city_sector ÷ state_sector, last 3 yrs) ]",
            inputs: "State × sector reconciled forecast (P10/P50/P90); city sector shares 2022–2024", note: "Assumes each city keeps its recent share of its state's sector emissions." }}
          legend={details.map((d, i) => d.data && <span key={i} className="flex items-center gap-1"><i className="inline-block h-2 w-3 rounded-sm" style={{ background: PAL[i] }} />{d.data.name}
            <Badge tone={d.data.confidence_tier}>Tier {d.data.confidence_tier}</Badge></span>)}>
          <ResponsiveContainer width="100%" height={330}>
            <ComposedChart data={trend} margin={{ left: 4, right: 8, top: 8 }}>
              <CartesianGrid stroke="#33415544" vertical={false} />
              <XAxis dataKey="year" stroke="#64748b" fontSize={10} />
              <YAxis stroke="#64748b" fontSize={10} width={44} />
              <Tooltip contentStyle={TT} formatter={(v: any, n: any) => [Array.isArray(v) ? `${fmt(v[0], 2)}–${fmt(v[1], 2)}` : fmt(v, 2), n]} />
              {details.map((d, i) => d.data && [
                <Area key={`b${i}`} dataKey={`b${i}`} name={`${d.data.name} P10–P90`} stroke="none" fill={PAL[i]} fillOpacity={0.15} isAnimationActive={false} legendType="none" />,
                <Area key={`c${i}`} dataKey={`c${i}`} name={d.data.name} stroke={PAL[i]} strokeWidth={2.2} fill={PAL[i]} fillOpacity={picked.length > 1 ? 0.05 : 0.25} isAnimationActive={false} />,
                <Line key={`f${i}`} dataKey={`f${i}`} name={`${d.data.name} forecast`} stroke={PAL[i]} strokeDasharray="5 3" strokeWidth={2} dot={false} isAnimationActive={false} />,
              ])}
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {main && (
        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard name={`city_${main.id}_sectors`} title={`${main.name} — estimated sector allocation`} data={split}
            sub="Share of the buffer's emissions by sector (every 5 years + latest). Labelled 'estimated allocation'." unit="MtCO₂e" source={SRC}
            how={{ formula: "City sector = Σ sector-grid CO₂e over the same buffer cells", note: "Point sources near the city (plants, refineries) are included if their cell centre is inside the buffer." }}
            legend={SECTORS.map((s) => <span key={s} className="flex items-center gap-1"><i className="inline-block h-2 w-2 rounded-sm" style={{ background: colorOf(s) }} />{SECTOR_LABEL[s]}</span>)}>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={split} margin={{ left: 0, right: 4, top: 6 }}>
                <XAxis dataKey="year" stroke="#64748b" fontSize={10} />
                <YAxis stroke="#64748b" fontSize={10} width={40} />
                <Tooltip contentStyle={TT} formatter={(v: any, n: any) => [`${fmt(v, 2)} Mt`, SECTOR_LABEL[n] ?? n]} />
                {SECTORS.map((s) => <Bar key={s} dataKey={s} stackId="s" fill={colorOf(s)} isAnimationActive={false} />)}
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard name={`city_${main.id}_share`} title={`${main.name} vs ${main.state_code}`} data={share}
            sub="City estimate as % of its state's total CO₂e over time" unit="% of state CO₂e" source={SRC}
            how={{ formula: "Share = city buffer CO₂e ÷ state CO₂e × 100", note: "Can exceed 100 % when the buffer crosses into neighbouring states (e.g. Delhi NCR)." }}>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={share} margin={{ left: 0, right: 8, top: 6 }}>
                <CartesianGrid stroke="#33415544" vertical={false} />
                <XAxis dataKey="year" stroke="#64748b" fontSize={10} />
                <YAxis stroke="#64748b" fontSize={10} width={40} unit="%" />
                <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 1)} %`} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line dataKey="share_of_state_pct" name="share of state" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
          <Card>
            <div className="flex items-center gap-2"><MapPin size={16} className="text-emerald-400" /><span className="font-semibold">{main.name}</span>
              <Badge tone={main.confidence_tier}>Tier {main.confidence_tier}</Badge><span className="text-xs text-slate-500 dark:text-slate-500">{main.state_code}</span></div>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
              <dt className="text-slate-500 dark:text-slate-500">Estimate {main.year}</dt><dd className="tabular-nums">{fmt(main.history[main.history.length - 1]?.co2e_mt, 2)} MtCO₂e</dd>
              <dt className="text-slate-500 dark:text-slate-500">Buffer radius</dt><dd>{main.buffer_km} km ({fmt(main.buffer_area_km2, 0)} km²)</dd>
              <dt className="text-slate-500 dark:text-slate-500">Grid cells used</dt><dd>{main.n_cells} × 0.1° (~11 km) cells</dd>
              <dt className="text-slate-500 dark:text-slate-500">Method</dt><dd>{main.estimation_method}</dd>
              <dt className="text-slate-500 dark:text-slate-500">Population (for per-capita)</dt><dd>{main.pop_2011 ? `${fmt(main.pop_2011 / 1e6, 2)} M · ${main.pop_source}` : "not available"}</dd>
            </dl>
            <button onClick={() => setHow(!how)} className="mt-3 flex w-full items-center justify-between rounded-lg bg-slate-100 dark:bg-white/5 px-3 py-2 text-left text-xs hover:bg-slate-200 dark:hover:bg-white/10">
              How this estimate was made {how ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {how && (
              <ol className="mt-2 list-decimal space-y-1 pl-5 text-[11px] leading-relaxed text-slate-700 dark:text-slate-300">
                <li>Take EDGAR 2025 gridded CO₂, CH₄ and N₂O emissions (0.1° cells, tonnes/yr) for each sub-sector.</li>
                <li>Convert to CO₂e with IPCC AR6 GWP-100 (CH₄ 29.8 fossil / 27.0 biogenic, N₂O 273).</li>
                <li>Select the {main.n_cells} cells whose centre is within {main.buffer_km} km of ({fmt(main.lat, 3)}°N, {fmt(main.lon, 3)}°E).</li>
                <li>Sum them per sector and year → city estimate. Tier {main.confidence_tier}: {main.confidence_tier === "B" ? "metro buffer, many cells — reasonable spatial support" : "few cells — dominated by 1–4 cells, treat as indicative"}.</li>
                <li>Forecast: {rank.data?.method?.split("Forecast = ")[1]?.split(". These")[0]}.</li>
              </ol>
            )}
          </Card>
        </div>
      )}

      <ChartCard name="city_ranking" title="City ranking" data={rows} source={SRC} unit="see column headers"
        sub="Click a column to sort · + adds a city to the comparison (max 3) · per-capita only for million-plus urban agglomerations (Census 2011 UA population)"
        how={{ formula: "10-yr CAGR = (CO₂e_2024 ÷ CO₂e_2014)^(1/10) − 1 · per-capita = buffer CO₂e ÷ UA population 2011 (indicative)" }}
        right={<Input placeholder="Filter city or state…" value={q} onChange={(e) => setQ(e.target.value)} className="h-7 w-44 text-xs" />}>
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-900 text-left text-xs text-slate-600 dark:text-slate-400">
              <tr>
                <th className="px-2 py-2">#</th><H k="name">City</H><th className="px-2 py-2 font-medium">State</th>
                <H k="co2e_mt" className="text-right">MtCO₂e (est.)</H><H k="cagr10_pct" className="text-right">10-yr CAGR</H>
                <H k="per_capita_t" className="text-right">t/person</H><H k="share_of_state_pct" className="text-right">% of state</H>
                <H k="confidence_tier">Tier</H><th />
              </tr>
            </thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={c.id} className={cn("border-b border-slate-200 dark:border-white/5", picked.includes(c.id) && "bg-emerald-500/5")}>
                  <td className="px-2 py-1.5 text-slate-500 dark:text-slate-500">{i + 1}</td>
                  <td className="px-2 py-1.5"><button onClick={() => setPicked([c.id, ...picked.filter((x) => x !== c.id)].slice(0, 3))} className="text-emerald-400 hover:underline">{c.name}</button></td>
                  <td className="px-2 py-1.5 text-slate-600 dark:text-slate-400">{c.state_code}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmt(c.co2e_mt, 2)}</td>
                  <td className={cn("px-2 py-1.5 text-right tabular-nums", (c.cagr10_pct ?? 0) > 0 ? "text-amber-400" : "text-emerald-400")}>{c.cagr10_pct == null ? "—" : `${c.cagr10_pct > 0 ? "+" : ""}${fmt(c.cagr10_pct, 1)}%`}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmt(c.per_capita_t, 1)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmt(c.share_of_state_pct, 1)}</td>
                  <td className="px-2 py-1.5"><Badge tone={c.confidence_tier}>{c.confidence_tier}</Badge></td>
                  <td className="px-2 py-1.5">
                    <button aria-label={picked.includes(c.id) ? "Remove from comparison" : "Add to comparison"} onClick={() => toggle(c.id)}
                      className="rounded p-1 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-white/10 hover:text-white">{picked.includes(c.id) ? <X size={13} /> : <Plus size={13} />}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartCard>
    </div>
  );
}
