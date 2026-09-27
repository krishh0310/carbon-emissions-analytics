import { useRef, type ReactNode } from "react";
import { toPng } from "html-to-image";
import { Download, Image } from "lucide-react";
import { toast } from "sonner";
import { Button, Card, CardTitle, Skeleton } from "./ui";
import { Info, SourceTag, type HowCalc } from "./Info";
import { glossify } from "../lib/glossary";

function downloadCsv(name: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `${name}.csv`;
  a.click();
}

/** Card with PNG + CSV export for any chart/table. */
export function ChartCard({ title, sub, name, data, loading, right, children, className, unit, source, how, legend }: {
  title: ReactNode; sub?: ReactNode; name: string; data?: Record<string, unknown>[]; loading?: boolean;
  right?: ReactNode; children: ReactNode; className?: string;
  unit?: string; source?: string; how?: HowCalc; legend?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const png = async () => {
    try {
      const bg = document.documentElement.classList.contains("dark") ? "#0f172a" : "#ffffff";
      const a = document.createElement("a");
      a.href = await toPng(ref.current!, { backgroundColor: bg, pixelRatio: 2 });
      a.download = `${name}.png`;
      a.click();
    } catch {
      toast.error("PNG export failed");
    }
  };
  return (
    <Card className={className}>
      <CardTitle
        sub={glossify(sub)}
        right={
          <div className="flex items-center gap-1">
            {right}
            {how && <Info how={{ source, ...how }} />}
            <Button variant="ghost" size="icon" title="Export PNG" aria-label="Export PNG" onClick={png}>
              <Image size={15} />
            </Button>
            <Button variant="ghost" size="icon" title="Export CSV" aria-label="Export CSV" disabled={!data?.length}
              onClick={() => downloadCsv(name, data ?? [])}>
              <Download size={15} />
            </Button>
          </div>
        }
      >
        {glossify(title)}
      </CardTitle>
      <div ref={ref}>
        {loading ? <Skeleton className="h-64 w-full" /> : children}
        {(unit || source || legend) && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
            {legend}
            {unit && <span>Unit: <b className="font-medium text-slate-400">{glossify(unit)}</b></span>}
            {source && <SourceTag>{source}</SourceTag>}
          </div>
        )}
      </div>
    </Card>
  );
}
