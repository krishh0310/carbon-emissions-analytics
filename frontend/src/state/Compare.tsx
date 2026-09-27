// Two-state comparison: side-by-side KPIs, synchronized history charts, sector radar, growth-share matrix.
import { useMemo } from "react";
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart,
  ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { ChartCard } from "../components/ChartCard";
import { fmt } from "../components/ui";
import { SECTORS, SECTOR_LABEL } from "../lib/sectors";
import { KpiRow, SRC_EDGAR, TT } from "./StateCharts";
import type { useStateData } from "./useStateData";

type D = ReturnType<typeof useStateData>;
const A = "#10b981", B = "#60a5fa";

export function Compare({ a, b }: { a: D; b: D }) {
  const y = a.lastObs, y0 = y - 10;
  const merged = useMemo(() => {
    const ys = [...new Set([...a.years, ...b.years, ...a.fcYears])].filter((yy) => yy >= 2000).sort((p, q) => p - q);
    return ys.map((yy) => ({
      year: yy, a: a.total[yy], b: b.total[yy],
      a_fc: yy >= y ? (yy === y ? a.total[yy] : a.totalFc.find((p) => p.year === yy)?.p50) : undefined,
      b_fc: yy >= y ? (yy === y ? b.total[yy] : b.totalFc.find((p) => p.year === yy)?.p50) : undefined,
      a_pc: a.total[yy] && a.pop[yy] ? a.total[yy] / a.pop[yy] : undefined, b_pc: b.total[yy] && b.pop[yy] ? b.total[yy] / b.pop[yy] : undefined,
    }));
  }, [a, b, y]);
  const radar = SECTORS.map((s) => ({
    sector: SECTOR_LABEL[s],
    a: (a.bySector[s][y] ?? 0) / (a.pop[y] || NaN), b: (b.bySector[s][y] ?? 0) / (b.pop[y] || NaN),
  }));
  const matrix = (d: D) => SECTORS.map((s) => ({
    sector: SECTOR_LABEL[s], share: (100 * (d.bySector[s][y] ?? 0)) / (d.total[y] || 1), cagr: d.cagr(d.bySector[s][y0], d.bySector[s][y]) ?? 0,
    mt: d.bySector[s][y] ?? 0,
  }));
  const names = [a.name ?? "A", b.name ?? "B"];
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 @5xl:grid-cols-2">
        <div><div className="mb-1 text-sm font-semibold" style={{ color: A }}>{names[0]}</div><KpiRow d={a} accent={A} /></div>
        <div><div className="mb-1 text-sm font-semibold" style={{ color: B }}>{names[1]}</div><KpiRow d={b} accent={B} /></div>
      </div>
      <div className="grid gap-4 @5xl:grid-cols-2">
        {([["Total CO₂e", "a", "b", "MtCO₂e"], ["Per-capita CO₂e", "a_pc", "b_pc", "tCO₂e per person"]] as const).map(([title, ka, kb, unit]) => (
          <ChartCard key={title} name={`compare_${ka}`} title={`${title}: ${names[0]} vs ${names[1]}`} data={merged} unit={unit} source={SRC_EDGAR}
            sub="Charts are synchronised — hover one to read the same year on both" how={{ formula: title.startsWith("Per") ? "CO₂e ÷ population" : "Σ 7 sectors CO₂e" }}>
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={merged} syncId="state-compare" margin={{ left: 4, right: 8, top: 6 }}>
                <CartesianGrid stroke="#33415544" vertical={false} />
                <XAxis dataKey="year" stroke="#64748b" fontSize={10} />
                <YAxis stroke="#64748b" fontSize={10} width={48} />
                <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 2)} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Area dataKey={ka} name={names[0]} stroke={A} fill={A} fillOpacity={0.15} strokeWidth={2} isAnimationActive={false} />
                <Area dataKey={kb} name={names[1]} stroke={B} fill={B} fillOpacity={0.15} strokeWidth={2} isAnimationActive={false} />
                {ka === "a" && <Line dataKey="a_fc" name={`${names[0]} forecast`} stroke={A} strokeDasharray="5 3" dot={false} isAnimationActive={false} />}
                {ka === "a" && <Line dataKey="b_fc" name={`${names[1]} forecast`} stroke={B} strokeDasharray="5 3" dot={false} isAnimationActive={false} />}
              </ComposedChart>
            </ResponsiveContainer>
          </ChartCard>
        ))}
      </div>
      <div className="grid gap-4 @5xl:grid-cols-2">
        <ChartCard name="compare_radar" title={`Sector footprint per person, ${y}`} data={radar} unit="tCO₂e per person (by sector)" source={SRC_EDGAR}
          sub="Radar spokes = sectors; further out = more emissions per resident" how={{ formula: "Sector CO₂e ÷ state population" }}>
          <ResponsiveContainer width="100%" height={300}>
            <RadarChart data={radar} outerRadius={105}>
              <PolarGrid stroke="#334155" />
              <PolarAngleAxis dataKey="sector" tick={{ fill: "#94a3b8", fontSize: 10 }} />
              <PolarRadiusAxis tick={{ fill: "#64748b", fontSize: 9 }} angle={90} />
              <Radar dataKey="a" name={names[0]} stroke={A} fill={A} fillOpacity={0.3} isAnimationActive={false} />
              <Radar dataKey="b" name={names[1]} stroke={B} fill={B} fillOpacity={0.3} isAnimationActive={false} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Tooltip contentStyle={TT} formatter={(v: any) => `${fmt(v, 2)} t`} />
            </RadarChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard name="compare_matrix" title={`Growth-share matrix (${y0}→${y})`} unit="x: % of state CO₂e · y: %/yr · bubble: MtCO₂e" source={SRC_EDGAR}
          sub="Top-right = big AND fast-growing sectors (priority for policy). Dashed lines: equal share (14.3 %) and zero growth."
          how={{ formula: "x = sector share of state CO₂e; y = sector CAGR = (CO₂e_end ÷ CO₂e_start)^(1/10) − 1" }}
          data={[...matrix(a).map((r) => ({ state: names[0], ...r })), ...matrix(b).map((r) => ({ state: names[1], ...r }))]}>
          <ResponsiveContainer width="100%" height={300}>
            <ScatterChart margin={{ left: 4, right: 12, top: 8, bottom: 8 }}>
              <CartesianGrid stroke="#33415544" />
              <XAxis type="number" dataKey="share" name="share" unit="%" stroke="#64748b" fontSize={10} />
              <YAxis type="number" dataKey="cagr" name="CAGR" unit="%" stroke="#64748b" fontSize={10} width={44} />
              <ZAxis type="number" dataKey="mt" range={[40, 600]} />
              <ReferenceLine x={100 / 7} stroke="#475569" strokeDasharray="4 4" />
              <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 4" />
              <Tooltip contentStyle={TT} formatter={(v: any, n: any) => [fmt(v, 1), n]} labelFormatter={() => ""}
                content={({ payload }) => payload?.[0] ? (
                  <div style={TT} className="p-2 text-xs">{payload[0].payload.sector}<br />share {fmt(payload[0].payload.share, 1)}% · CAGR {fmt(payload[0].payload.cagr, 1)}%/yr · {fmt(payload[0].payload.mt, 1)} Mt</div>
                ) : null} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Scatter name={names[0]} data={matrix(a)} fill={A} fillOpacity={0.7} />
              <Scatter name={names[1]} data={matrix(b)} fill={B} fillOpacity={0.7} />
            </ScatterChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}
