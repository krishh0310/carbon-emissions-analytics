// ⓘ "How is this calculated?" popover — formula, inputs, source, freshness. Keyboard + hover accessible.
import { useState, type ReactNode } from "react";
import { Info as InfoIcon } from "lucide-react";
import { cn } from "./ui";

export type HowCalc = { formula: ReactNode; inputs?: ReactNode; source?: string; updated?: string; note?: ReactNode };

export function Info({ how, className, align = "right" }: { how: HowCalc; className?: string; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  return (
    <span className={cn("relative inline-flex", className)} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-label="How is this calculated?" aria-expanded={open} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)} className="grid h-5 w-5 place-items-center rounded-full text-slate-400 hover:bg-slate-200 dark:hover:bg-white/10 hover:text-emerald-700 dark:hover:text-emerald-300">
        <InfoIcon size={13} />
      </button>
      {open && (
        <span role="tooltip" className={cn("absolute top-6 z-50 w-80 rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950/95 p-3 text-left text-[11px] font-normal leading-relaxed text-slate-700 dark:text-slate-300 shadow-2xl backdrop-blur",
          align === "right" ? "right-0" : "left-0")}>
          <span className="block text-[10px] uppercase tracking-wider text-emerald-400">How is this calculated?</span>
          <span className="mt-1 block rounded-md bg-slate-100 dark:bg-white/5 px-2 py-1.5 font-mono text-[11px] text-slate-900 dark:text-slate-100">{how.formula}</span>
          {how.inputs && <span className="mt-1.5 block"><b className="text-slate-400">Inputs:</b> {how.inputs}</span>}
          {how.note && <span className="mt-1 block text-slate-400">{how.note}</span>}
          {(how.source || how.updated) && (
            <span className="mt-1.5 block text-slate-500">{how.source && <>Source: {how.source}</>}{how.updated && <> · Updated {how.updated}</>}</span>
          )}
        </span>
      )}
    </span>
  );
}

export function SourceTag({ children }: { children: ReactNode }) {
  return <span className="rounded border border-slate-200 dark:border-white/10 bg-slate-100 dark:bg-white/5 px-1.5 py-px text-[10px] text-slate-400">{children}</span>;
}
