import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { useBi } from "../lib/i18n";
import { ChartCard } from "../components/ChartCard";
import { Card, Select, Table, fmt } from "../components/ui";
import { MODELS } from "../lib/sectors";

const TT = { background: "#0f172a", border: "1px solid #334155", fontSize: 12 };
const PAL = ["#10b981", "#14b8a6", "#38bdf8", "#a78bfa", "#f59e0b", "#f43f5e", "#84cc16", "#e879f9", "#94a3b8", "#fb923c", "#22d3ee"];

export default function ModelLab() {
  const bi = useBi();
  const [split, setSplit] = useState("test");
  const [model, setModel] = useState("tft");
  const [state, setState] = useState("IN-MH");
  const lb = useQuery({ queryKey: ["lb"], queryFn: () => api("/models") });
  const v2 = useQuery({ queryKey: ["lb2"], queryFn: () => api("/api/v2/models"), retry: false });
  const v2rows: any[] = (v2.data?.leaderboard ?? []).filter((r: any) => r.split === "test" && r.sector === "ALL");
  const v2models = [...new Set(v2rows.map((r) => r.model))].sort((a, b) =>
    (v2rows.find((r) => r.model === a && r.horizon === 5)?.reconciled_mase ?? 99) - (v2rows.find((r) => r.model === b && r.horizon === 5)?.reconciled_mase ?? 99));
  const exps: any[] = (v2.data?.experiments ?? []).filter((r: any) => [1, 3, 5].includes(r.horizon));
  const expKeys = [...new Set(exps.map((r) => `${r.experiment}|${r.model}|${r.variant}`))];
  const imp = useQuery({ queryKey: ["imp", model], queryFn: () => api(`/models/${model}/importance`), retry: false });
  const bt = useQuery({ queryKey: ["bt", model, state], queryFn: () => api(`/models/${model}/backtest?state=${state}`), retry: false });
  const rows: any[] = (lb.data?.rows ?? []).filter((r: any) => r.split === split);
  const byH = [1, 2, 3, 4, 5].map((h) => Object.fromEntries([["horizon", h], ...rows.filter((r) => r.horizon === h).map((r) => [r.model, r.mase])]));
  const models = [...new Set(rows.map((r) => r.model))].sort((a, b) =>
    (rows.find((r) => r.model === a && r.horizon === 5)?.mase ?? 99) - (rows.find((r) => r.model === b && r.horizon === 5)?.mase ?? 99));
  const resid = (bt.data?.points ?? []).filter((p: any) => p.actual != null).map((p: any) => ({ ...p, resid: p.p50 - p.actual }));
  const att: any[] = imp.data?.attention ?? [];
  const attCols = att.length ? Object.keys(att[0]).filter((k) => k.startsWith("t-")) : [];
  const shap: any[] = imp.data?.shap ?? [];
  const vs: any[] = imp.data?.variable_selection ?? [];

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-3">
        <Select label="Split" value={split} onChange={(e) => setSplit(e.target.value)}>{["train", "val", "test"].map((s) => <option key={s}>{s}</option>)}</Select>
        <Select label="Model" value={model} onChange={(e) => setModel(e.target.value)}>{MODELS.map((m) => <option key={m}>{m}</option>)}</Select>
        <Select label="State" value={state} onChange={(e) => setState(e.target.value)}>
          {["IN-MH", "IN-GJ", "IN-UP", "IN-CG", "IN-OD", "IN-TN", "IN-KA", "IN-DL", "IN-KL", "IN-WB"].map((s) => <option key={s}>{s}</option>)}
        </Select>
      </div>
      <Card className="text-xs text-slate-500">{lb.data?.note}</Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard name={`leaderboard_${split}`} title={bi("Leaderboard")} sub={`${split} · MASE by horizon (lower is better; <1 beats in-sample naive)`} data={rows} loading={lb.isLoading}>
          <Table head={["Model", "h=1", "h=3", "h=5", "MinT h=5", "train s"]}
            rows={models.map((m) => {
              const g = (h: number, k = "mase") => rows.find((r) => r.model === m && r.horizon === h)?.[k];
              return [m, fmt(g(1), 2), fmt(g(3), 2), <b>{fmt(g(5), 2)}</b>, fmt(g(5, "reconciled_mase"), 2), fmt(g(1, "training_time"), 0)];
            })} />
        </ChartCard>
        <ChartCard name={`mase_by_horizon_${split}`} title="MASE by horizon" data={byH} loading={lb.isLoading}>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={byH}>
              <CartesianGrid stroke="#33415555" />
              <XAxis dataKey="horizon" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} width={35} />
              <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 2)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {models.map((m, i) => <Line key={m} dataKey={m} stroke={PAL[i % PAL.length]} dot={false} strokeWidth={m === model ? 3 : 1.2} />)}
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard name={`residuals_${model}_${state}`} title={`Residuals — ${model} · ${state}`} sub="P50 − actual (MtCO₂), backtest years 2015+, by target year" data={resid} loading={bt.isLoading}>
          <ResponsiveContainer width="100%" height={260}>
            <ScatterChart>
              <CartesianGrid stroke="#33415555" />
              <XAxis dataKey="year" type="number" domain={["dataMin", "dataMax"]} stroke="#64748b" fontSize={11} />
              <YAxis dataKey="resid" stroke="#64748b" fontSize={11} width={40} />
              <ReferenceLine y={0} stroke="#94a3b8" />
              <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 2)} />
              {[1, 3, 5].map((h, i) => <Scatter key={h} name={`h=${h}`} data={resid.filter((r: any) => r.horizon === h)} fill={PAL[i]} />)}
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </ScatterChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard name={`attention_${model}`} title="Attention heatmap" sub="Mean attention weight on each input year (rows = forecast horizon). Seq2Seq-Attention & TFT only." data={att} loading={imp.isLoading}>
          {att.length ? (
            <div className="overflow-x-auto">
              <div className="grid gap-0.5 text-[10px]" style={{ gridTemplateColumns: `40px repeat(${attCols.length}, minmax(28px,1fr))` }}>
                <div />
                {attCols.map((c) => <div key={c} className="text-center text-slate-500">{c}</div>)}
                {att.map((r) => {
                  const mx = Math.max(...attCols.map((c) => r[c]));
                  return [<div key={r.horizon} className="text-slate-500">h={r.horizon}</div>,
                    ...attCols.map((c) => <div key={c + r.horizon} title={fmt(r[c], 3)} className="h-7 rounded-sm" style={{ background: `rgba(20,184,166,${(r[c] / mx).toFixed(2)})` }} />)];
                })}
              </div>
            </div>
          ) : <p className="text-sm text-slate-500">Select tft or seq2seq_attn.</p>}
        </ChartCard>
        {v2rows.length > 0 && (
          <ChartCard name="v2_sector_leaderboard" title="v2 · State×sector leaderboard (test, 252 series)" data={v2rows}
            sub="MASE over material cells; MinT = two-level reconciliation (national → states/sectors → cells). Headline = MinT.">
            <Table head={["Model", "h=1", "h=3", "h=5", "MinT h=1", "MinT h=3", "MinT h=5"]}
              rows={v2models.map((m) => {
                const g = (h: number, k: string) => v2rows.find((r) => r.model === m && r.horizon === h)?.[k];
                return [m, ...[1, 3, 5].map((h) => fmt(g(h, "mase"), 2)), ...[1, 3, 5].map((h) => h === 5 ? <b key={h}>{fmt(g(h, "reconciled_mase"), 2)}</b> : fmt(g(h, "reconciled_mase"), 2))];
              })} />
          </ChartCard>
        )}
        {exps.length > 0 && (
          <ChartCard name="v2_experiments" title="v2 · Experiments E10–E14" data={exps}
            sub="E10 bottom-up vs direct state totals · E11 multi-task vs per-sector heads · E12 reconciliation · E14 zero-shot held-out states (E13 = CI tests)">
            <Table head={["Exp", "Model", "Variant", "h=1", "h=3", "h=5"]}
              rows={expKeys.map((k) => {
                const [e, m, v] = k.split("|");
                const g = (h: number) => exps.find((r) => r.experiment === e && r.model === m && r.variant === v && r.horizon === h)?.mase;
                return [e, m, v.replaceAll("_", " "), fmt(g(1), 2), fmt(g(3), 2), fmt(g(5), 2)];
              })} />
          </ChartCard>
        )}
        {(shap.length > 0 || vs.length > 0) && (
          <ChartCard className="lg:col-span-2" name={`shap_${model}`} title={shap.length ? "SHAP — LightGBM (h=1, P50)" : "TFT variable-selection weights"}
            data={shap.length ? shap : vs}>
            <ResponsiveContainer width="100%" height={380}>
              <BarChart data={(shap.length ? shap : vs).slice(0, 20)} layout="vertical" margin={{ left: 40 }}>
                <XAxis type="number" stroke="#64748b" fontSize={11} />
                <YAxis type="category" dataKey="feature" stroke="#64748b" fontSize={10} width={160} interval={0} />
                <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 4)} />
                <Bar dataKey={shap.length ? "mean_abs_shap" : "weight"} fill="#10b981" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}
      </div>
    </div>
  );
}
