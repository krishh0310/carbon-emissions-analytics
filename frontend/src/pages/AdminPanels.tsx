// Admin console panels: Registry · Drift · Source reconciliation · Feature store · Insight moderation.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { api, auth } from "../lib/api";
import { Badge, Button, Card, CardTitle, Table, cn, fmt } from "../components/ui";
import { InsightCard } from "../insights/InsightCard";

const TT = { background: "#020617", border: "1px solid #1e293b", borderRadius: 8, fontSize: 11 };
const STATUS_TONE: Record<string, any> = { champion: "A", challenger: "B", candidate: "muted", archived: "danger" };

function useAct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ path, method = "POST", body }: { path: string; method?: string; body?: any }) => api(path, { method, body: body ? JSON.stringify(body) : undefined }),
    onSuccess: () => { toast.success("Done"); qc.invalidateQueries(); },
    onError: (e: any) => toast.error(e.message),
  });
}

export function Registry() {
  const [level, setLevel] = useState<"state" | "state_sector">("state_sector");
  const [archived, setArchived] = useState(false);
  const q = useQuery({ queryKey: ["registry", level, archived], queryFn: () => api(`/admin/registry?level=${level}&include_archived=${archived}`) });
  const act = useAct();
  const items: any[] = q.data?.items ?? [];
  const champ = items.find((m) => m.status === "champion"), chal = items.find((m) => m.status === "challenger");
  const download = async () => {
    const r = await fetch("/api/v1/admin/metrics.csv", { headers: { Authorization: `Bearer ${auth.get()?.access_token}` } });
    if (!r.ok) return toast.error("download failed");
    const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = "carbonscope_metrics.csv"; a.click();
  };
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {(["state_sector", "state"] as const).map((l) => (
          <button key={l} onClick={() => setLevel(l)} className={cn("rounded-md px-2.5 py-1 text-xs", level === l ? "bg-amber-100 dark:bg-amber-400/20 text-amber-800 dark:text-amber-200" : "text-slate-400 hover:bg-slate-100 dark:hover:bg-white/5")}>
            {l === "state" ? "Fossil CO₂ (state)" : "CO₂e (state × sector)"}</button>
        ))}
        <label className="ml-2 flex items-center gap-1 text-xs text-slate-400"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />show archived</label>
        <Button size="sm" variant="outline" className="ml-auto" onClick={download}>Download full metrics CSV</Button>
      </div>
      <p className="text-xs text-slate-500">{q.data?.policy?.selection} · {q.data?.policy?.promotion}</p>
      <div className="grid gap-3 md:grid-cols-2">
        {[["Champion", champ, "#10b981"], ["Challenger (shadow)", chal, "#38bdf8"]].map(([t, m, c]: any) => (
          <Card key={t} style={{ borderTop: `2px solid ${c}` }}>
            <CardTitle sub={m ? `version ${m.version}${m.shadow_until ? ` · shadow until ${new Date(m.shadow_until).toLocaleDateString()}` : ""}${m.pinned ? " · pinned" : ""}` : "none"}>{t}{m ? `: ${m.name}` : ""}</CardTitle>
            {m && <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <div><div className="text-slate-500">val MASE@5</div><div className="text-lg font-semibold">{fmt(m.val_score, 3)}</div></div>
              <div><div className="text-slate-500">backtest (test h1/3/5)</div><div className="text-lg font-semibold">{fmt(m.backtest_score, 3)}</div></div>
              <div><div className="text-slate-500">served (14 d)</div><div className="text-lg font-semibold">{m.served_14d}</div></div>
            </div>}
          </Card>
        ))}
      </div>
      <Card>
        <CardTitle sub="Candidates are every model trained in a cycle; promotion is automatic after the shadow window if it still qualifies.">Model registry</CardTitle>
        <Table head={["Model", "Version", "Status", "val MASE@5", "backtest", "served 14d", "Actions"]}
          rows={items.map((m) => [m.name, <code className="text-[11px]">{m.version}</code>, <Badge tone={STATUS_TONE[m.status]}>{m.status}{m.pinned ? " 📌" : ""}</Badge>,
            fmt(m.val_score, 3), fmt(m.backtest_score, 3), m.served_14d,
            <div className="flex flex-wrap gap-1">
              {m.status !== "champion" && <Button size="sm" variant="outline" onClick={() => act.mutate({ path: `/admin/models/${m.id}/promote` })}>Promote</Button>}
              {m.status === "candidate" && <Button size="sm" variant="outline" onClick={() => act.mutate({ path: `/admin/models/${m.id}/challenge` })}>Shadow 20%</Button>}
              {m.status === "champion" && <Button size="sm" variant="outline" onClick={() => act.mutate({ path: `/admin/models/${m.id}/pin?pinned=${!m.pinned}` })}>{m.pinned ? "Unpin" : "Pin"}</Button>}
              {m.status !== "champion" && m.status !== "archived" && <Button size="sm" variant="ghost" onClick={() => act.mutate({ path: `/admin/models/${m.id}/archive` })}>Archive</Button>}
            </div>])} />
      </Card>
    </div>
  );
}

export function Drift() {
  const q = useQuery({ queryKey: ["drift"], queryFn: () => api("/admin/drift") });
  const act = useAct();
  const last = q.data?.items?.[0];
  const psi: { f: string; v: number }[] = last ? Object.entries(last.details?.psi_top ?? {}).map(([f, v]) => ({ f, v: Number(v) })) : [];
  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => act.mutate({ path: "/admin/drift/check" })}>Run drift check now</Button>
        <span className="text-xs text-slate-500">Thresholds: PSI &gt; {q.data?.thresholds?.psi} on ≥ {q.data?.thresholds?.psi_inputs} inputs, or error ratio &gt; {q.data?.thresholds?.error_ratio} → auto-retrain + alert</span>
      </div>
      {!last ? <Card className="text-sm text-slate-400">No drift reports yet — run a check (the scheduler also runs one daily at 04:00 IST).</Card> : (
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <Card>
            <CardTitle sub={`PSI of year-on-year input changes, ${last.details?.window}. PSI < 0.1 stable · 0.1–0.25 moderate · > 0.25 drift`}>Input drift (top 8)</CardTitle>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={psi} layout="vertical" margin={{ left: 40 }}>
                <XAxis type="number" stroke="#64748b" fontSize={10} /><YAxis type="category" dataKey="f" stroke="#94a3b8" fontSize={10} width={150} />
                <Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 3)} />
                <Bar dataKey="v" name="PSI" isAnimationActive={false}>{psi.map((p) => <Cell key={p.f} fill={p.v > 0.25 ? "#f43f5e" : p.v > 0.1 ? "#f59e0b" : "#10b981"} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
          <Card>
            <CardTitle sub="Champion's newest 1-year-ahead MASE ÷ its validation MASE (h=1)">Error drift</CardTitle>
            <div className={cn("text-4xl font-semibold", (last.error_ratio ?? 0) > 1.5 ? "text-rose-400" : "text-emerald-400")}>{fmt(last.error_ratio, 2)}×</div>
            <div className="mt-2 text-sm">{last.triggered ? <Badge tone="danger">triggered — retrain queued</Badge> : <Badge tone="A">within thresholds</Badge>}</div>
            <div className="mt-4 text-xs text-slate-500">History</div>
            <ul className="mt-1 space-y-1 text-xs">{(q.data?.items ?? []).slice(0, 8).map((r: any) => (
              <li key={r.id} className="flex justify-between"><span>{new Date(r.created_at).toLocaleString()}</span><span>PSI max {fmt(r.psi_max, 2)} · err {fmt(r.error_ratio, 2)}× {r.triggered ? "⚠" : ""}</span></li>))}</ul>
          </Card>
        </div>
      )}
    </div>
  );
}

export function Sources() {
  const q = useQuery({ queryKey: ["sources"], queryFn: () => api("/admin/sources") });
  const rows: any[] = (q.data?.items ?? []).filter((r: any) => r.cea_power_mt > 0.05 || r.edgar_power_mt > 1);
  return (
    <div className="grid gap-4">
      <Card className="text-xs text-slate-400">{q.data?.method} · GHG Platform India: {q.data?.ghgpi}. CEA covers grid-connected utility plants only; large positive EDGAR−CEA gaps usually indicate captive (industrial) power.</Card>
      <Card>
        <CardTitle sub={`${q.data?.year ?? ""} · power-sector CO₂, MtCO₂`}>EDGAR vs CEA by state</CardTitle>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={rows} margin={{ bottom: 20 }}>
            <XAxis dataKey="state_code" stroke="#64748b" fontSize={9} interval={0} angle={-60} textAnchor="end" height={45} tickFormatter={(c) => c.slice(3)} />
            <YAxis stroke="#64748b" fontSize={10} width={40} /><Tooltip contentStyle={TT} formatter={(v: any) => fmt(v, 1)} /><Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="edgar_power_mt" name="EDGAR (ENE)" fill="#14b8a6" isAnimationActive={false} />
            <Bar dataKey="cea_power_mt" name="CEA (plant-level)" fill="#f59e0b" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <Card>
        <Table head={["State", "EDGAR power", "CEA power", "Agreement", "Divergent", "CEA ÷ EDGAR (mean)", "Calibrated CO₂e", "EDGAR CO₂e"]}
          rows={(q.data?.items ?? []).map((r: any) => [r.state_code, fmt(r.edgar_power_mt, 1), fmt(r.cea_power_mt, 1),
            r.agreement == null ? "—" : `${Math.round(100 * r.agreement)}%`, r.divergent ? <Badge tone="danger">&gt;15%</Badge> : r.agreement != null ? <Badge tone="A">ok</Badge> : "—",
            fmt(r.cea_over_edgar_factor, 2), fmt(r.calibrated_co2e_mt, 1), fmt(r.total_co2e_mt, 1)])} />
      </Card>
    </div>
  );
}

export function Features() {
  const q = useQuery({ queryKey: ["features"], queryFn: () => api("/admin/features") });
  return (
    <Card>
      <CardTitle sub="Coverage = share of state-years with a value. Low-coverage features enter models with a *_missing flag.">Feature store</CardTitle>
      <Table head={["Feature", "Source", "Coverage", "Years"]}
        rows={(q.data?.items ?? []).map((r: any) => [<code className="text-[11px]">{r.feature}</code>, r.source,
          <div className="flex items-center gap-2"><div className="h-1.5 w-24 rounded bg-slate-100 dark:bg-white/5"><div className="h-full rounded bg-emerald-500" style={{ width: `${100 * r.coverage}%` }} /></div>{Math.round(100 * r.coverage)}%</div>,
          r.first_year ? `${r.first_year}–${r.last_year}` : "—"])} />
    </Card>
  );
}

export function Moderation() {
  const q = useQuery({ queryKey: ["mod"], queryFn: () => api("/api/v2/insights?limit=200&include_hidden=true") });
  const act = useAct();
  const [edit, setEdit] = useState<{ id: number; body: string; note: string } | null>(null);
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {(q.data?.items ?? []).map((i: any) => (
        <div key={i.id} className={cn("grid gap-2", !i.approved && "opacity-50")}>
          <InsightCard i={i} />
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <Button size="sm" variant="outline" onClick={() => act.mutate({ path: `/admin/insights/${i.id}`, method: "PATCH", body: { approved: !i.approved } })}>{i.approved ? "Hide from viewers" : "Approve"}</Button>
            <Button size="sm" variant="ghost" onClick={() => setEdit({ id: i.id, body: i.body, note: i.admin_note ?? "" })}>Edit text</Button>
            {i.edited && <Badge tone="B">edited</Badge>}{i.admin_note && <span className="text-slate-500">note: {i.admin_note}</span>}
          </div>
          {edit && edit.id === i.id && (
            <div className="grid gap-1.5 rounded-lg border border-slate-200 dark:border-white/10 p-2">
              <textarea className="h-24 rounded bg-white dark:bg-slate-950 p-2 text-xs" value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} aria-label="Insight text" />
              <input className="rounded bg-white dark:bg-slate-950 px-2 py-1 text-xs" placeholder="admin note" value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} />
              <div className="flex gap-1.5"><Button size="sm" onClick={() => { act.mutate({ path: `/admin/insights/${i.id}`, method: "PATCH", body: { body: edit.body, admin_note: edit.note } }); setEdit(null); }}>Save</Button>
                <Button size="sm" variant="ghost" onClick={() => setEdit(null)}>Cancel</Button></div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
