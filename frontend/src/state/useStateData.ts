// All data one state view needs, fetched once and derived into chart-ready series.
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { SECTORS } from "../lib/sectors";

export type Pt = { year: number; p10: number; p50: number; p90: number; p50_reconciled?: number | null };
export type Target = "co2e" | "co2" | "pc" | "ci";

const cagr = (a?: number | null, b?: number | null, n = 10) => (a && b && a > 0 && b > 0 ? 100 * ((b / a) ** (1 / n) - 1) : null);

export function useStateData(code: string | null) {
  const on = !!code;
  const hist = useQuery({ queryKey: ["hist", code], queryFn: () => api(`/states/${code}/history`), enabled: on });
  const fc = useQuery({ queryKey: ["fc", code], queryFn: () => api(`/states/${code}/forecast?horizon=5`), enabled: on });
  const sec = useQuery({ queryKey: ["sec", code], queryFn: () => api(`/api/v2/states/${code}/sectors`), enabled: on, retry: false });
  const sfc = useQuery({ queryKey: ["sfc", code], queryFn: () => api(`/api/v2/states/${code}/sectors/forecast`), enabled: on, retry: false });
  const loading = hist.isLoading || sec.isLoading;

  const d = useMemo(() => {
    const feats: Record<number, any> = Object.fromEntries((hist.data?.features ?? []).map((f: any) => [f.year, f]));
    const fossil: Record<number, number> = Object.fromEntries((hist.data?.points ?? []).map((p: any) => [p.year, p.value]));
    const cea: Record<number, number> = Object.fromEntries((hist.data?.points ?? []).filter((p: any) => p.cea_power_co2_mt != null).map((p: any) => [p.year, p.cea_power_co2_mt]));
    const bySector: Record<string, Record<number, number>> = {};
    for (const s of SECTORS) bySector[s] = Object.fromEntries((sec.data?.history?.[s] ?? []).map((r: any) => [r.year, r.co2e_mt]));
    const years = Object.keys(bySector.POWER ?? {}).map(Number).sort((a, b) => a - b);
    const lastObs = years[years.length - 1] ?? 2024;
    const total: Record<number, number> = Object.fromEntries(years.map((y) => [y, SECTORS.reduce((a, s) => a + (bySector[s][y] ?? 0), 0)]));
    const secFc: Record<string, Pt[]> = sfc.data?.sectors ?? {};
    const fcYears = (secFc.POWER ?? []).map((p) => p.year);
    const val = (p: Pt) => p.p50_reconciled ?? p.p50;
    // CO2e forecast of the state = Σ reconciled sector P50 (coherent by MinT). Band = Σ sector P10/P90 (conservative:
    // assumes sector errors move together).
    const totalFc: Pt[] = fcYears.map((y) => {
      const at = (s: string) => secFc[s]?.find((p) => p.year === y);
      return { year: y, p50: SECTORS.reduce((a, s) => a + (at(s) ? val(at(s)!) : 0), 0),
        p10: SECTORS.reduce((a, s) => a + (at(s)?.p10 ?? 0), 0), p90: SECTORS.reduce((a, s) => a + (at(s)?.p90 ?? 0), 0) };
    });
    const fossilFc: Pt[] = (fc.data?.points ?? []).map((p: Pt) => ({ ...p, p50: val(p) }));
    const pop: Record<number, number> = Object.fromEntries(years.map((y) => [y, feats[y]?.population_mn]).filter(([, v]) => v));
    const gsdp: Record<number, number> = Object.fromEntries(years.map((y) => [y, feats[y]?.gsdp_const_cr]).filter(([, v]) => v));
    const popG = pop[lastObs] && pop[lastObs - 5] ? (pop[lastObs] / pop[lastObs - 5]) ** (1 / 5) : 1;
    const popAt = (y: number) => pop[y] ?? (pop[lastObs] ? pop[lastObs] * popG ** (y - lastObs) : NaN);
    return { feats, fossil, cea, bySector, years, lastObs, total, secFc, fcYears, totalFc, fossilFc, pop, gsdp, popAt, val };
  }, [hist.data, fc.data, sec.data, sfc.data]);

  /** Chart rows for a target: history (+CEA for fossil) then forecast; the forecast starts AT the last observed point. */
  const series = (t: Target) => {
    const rows: any[] = [];
    const H = (y: number) =>
      t === "co2e" ? d.total[y] : t === "co2" ? d.fossil[y] : t === "pc" ? d.total[y] / (d.pop[y] ?? NaN)
        : d.gsdp[y] ? (d.total[y] * 1e6) / d.gsdp[y] : undefined;
    for (const y of d.years) rows.push({ year: y, hist: H(y), cea: t === "co2" ? d.cea[y] : undefined });
    const f = t === "co2e" ? d.totalFc : t === "co2" ? d.fossilFc : t === "pc" ? d.totalFc.map((p) => ({ ...p,
      p10: p.p10 / d.popAt(p.year), p50: p.p50 / d.popAt(p.year), p90: p.p90 / d.popAt(p.year) })) : [];
    const last = rows.find((r) => r.year === d.lastObs);
    if (last && f.length && last.hist != null) Object.assign(last, { p50: last.hist, band: [last.hist, last.hist] });
    for (const p of f) rows.push({ year: p.year, p50: p.p50, band: [p.p10, p.p90] });
    return rows;
  };

  const kpis = useMemo(() => {
    const y = d.lastObs;
    const tot = d.total[y];
    const top = [...SECTORS].sort((a, b) => (d.bySector[b][y] ?? 0) - (d.bySector[a][y] ?? 0))[0];
    return {
      total: tot, fossil: d.fossil[y], perCapita: tot / (d.pop[y] ?? NaN), intensity: d.gsdp[y] ? (tot * 1e6) / d.gsdp[y] : null,
      cagr10: cagr(d.total[y - 10], tot), topSector: top, topShare: tot ? (d.bySector[top][y] ?? 0) / tot : 0,
      fc5: d.totalFc[d.totalFc.length - 1]?.p50, fcYear: d.totalFc[d.totalFc.length - 1]?.year,
    };
  }, [d]);

  return { ...d, series, kpis, loading, name: hist.data?.name as string | undefined, meta: sec.data, cagr };
}
