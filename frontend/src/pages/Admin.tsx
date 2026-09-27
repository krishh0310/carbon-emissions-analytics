import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../lib/api";
import { useBi } from "../lib/i18n";
import { MODELS } from "../lib/sectors";
import { Badge, Button, Card, CardTitle, Table } from "../components/ui";

export default function Admin() {
  const bi = useBi();
  const qc = useQueryClient();
  const [sel, setSel] = useState<string[]>(["lightgbm", "tft"]);
  const [fast, setFast] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api("/admin/jobs?limit=20"), refetchInterval: 5000 });
  const job = useQuery({ queryKey: ["job", open], queryFn: () => api(`/admin/jobs/${open}`), enabled: open != null, refetchInterval: 3000 });
  const sched = useQuery({ queryKey: ["schedule"], queryFn: () => api("/admin/schedule") });
  const cycle = useMutation({
    mutationFn: (kind: string) => api("/admin/cycle", { method: "POST", body: JSON.stringify({ kind }) }),
    onSuccess: (d: any) => { toast.success(`Cycle job #${d.job_id} queued`); setOpen(d.job_id); qc.invalidateQueries({ queryKey: ["jobs"] }); },
    onError: (e: any) => toast.error(e.message),
  });
  const retrain = useMutation({
    mutationFn: () => api("/admin/retrain", { method: "POST", body: JSON.stringify({ models: sel, fast }) }),
    onSuccess: (d: any) => { toast.success(`Job #${d.job_id} queued`); setOpen(d.job_id); qc.invalidateQueries({ queryKey: ["jobs"] }); },
    onError: (e: any) => toast.error(e.message),
  });
  const tone = (s: string) => (s === "succeeded" ? "A" : s === "failed" ? "danger" : s === "running" ? "B" : "muted") as any;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle sub="Runs train → explain → insights → DB reseed as a background RQ job.">{bi("Retrain models")}</CardTitle>
        <div className="flex flex-wrap gap-2">
          {MODELS.map((m) => (
            <label key={m} className="flex items-center gap-1 text-sm">
              <input type="checkbox" className="accent-emerald-500" checked={sel.includes(m)}
                onChange={(e) => setSel(e.target.checked ? [...sel, m] : sel.filter((x) => x !== m))} />{m}
            </label>
          ))}
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={fast} onChange={(e) => setFast(e.target.checked)} className="accent-emerald-500" />fast (smoke test: 5 epochs)</label>
        <Button className="mt-3" disabled={!sel.length || retrain.isPending} onClick={() => retrain.mutate()}>Start retraining</Button>
      </Card>
      <Card>
        <CardTitle>{bi("Jobs")}</CardTitle>
        <Table head={["#", "Status", "Created", "Finished", ""]}
          rows={(jobs.data?.items ?? []).map((j: any) => [j.id, <Badge tone={tone(j.status)}>{j.status}</Badge>,
            new Date(j.created_at).toLocaleString(), j.finished_at ? new Date(j.finished_at).toLocaleTimeString() : "—",
            <Button size="sm" variant="outline" onClick={() => setOpen(j.id)}>logs</Button>])} />
      </Card>
      {open != null && (
        <Card className="lg:col-span-2">
          <CardTitle right={<Badge tone={tone(job.data?.status)}>{job.data?.status}</Badge>}>Job #{open} logs</CardTitle>
          <pre className="max-h-80 overflow-auto rounded bg-slate-950 p-3 text-[11px] text-slate-300">{job.data?.logs ?? "…"}</pre>
        </Card>
      )}
      <Card className="lg:col-span-2">
        <CardTitle sub={sched.data?.note}>Continuous learning schedule ({sched.data?.timezone})</CardTitle>
        <div className="grid gap-2 sm:grid-cols-3">
          {(sched.data?.jobs ?? []).map((j: any) => (
            <div key={j.job} className="rounded-lg border border-white/10 p-2.5 text-xs">
              <div className="font-semibold">{j.label}</div><div className="text-slate-400">next: {new Date(j.next_run).toLocaleString()}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex gap-2">
          <Button onClick={() => cycle.mutate("full")} disabled={cycle.isPending}>Run full cycle now</Button>
          <Button variant="outline" onClick={() => cycle.mutate("incremental")} disabled={cycle.isPending}>Incremental refresh now</Button>
        </div>
      </Card>
    </div>
  );
}
