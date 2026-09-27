// shadcn/ui-style primitives (same API shape: className + variants via cva), kept in one file.
import { cva, type VariantProps } from "class-variance-authority";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export const cn = (...c: ClassValue[]) => twMerge(clsx(c));

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/70", className)}
      {...p}
    />
  );
}

export function CardTitle({ children, sub, right }: { children: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">{children}</h3>
        {sub && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

const button = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 disabled:opacity-50 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        default: "bg-brand-600 text-white hover:bg-brand-500",
        outline: "border border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800",
        ghost: "hover:bg-slate-100 dark:hover:bg-slate-800",
      },
      size: { default: "h-9 px-3", sm: "h-7 px-2 text-xs", icon: "h-8 w-8" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({ className, variant, size, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>) {
  return <button className={cn(button({ variant, size }), className)} {...p} />;
}

const badge = cva("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold", {
  variants: {
    tone: {
      A: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300",
      B: "bg-teal-500/15 text-teal-600 dark:text-teal-300",
      C: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
      muted: "bg-slate-500/15 text-slate-600 dark:text-slate-300",
      danger: "bg-rose-500/15 text-rose-600 dark:text-rose-300",
    },
  },
  defaultVariants: { tone: "muted" },
});

export function Badge({ tone, className, ...p }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...p} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-slate-200 dark:bg-slate-800", className)} />;
}

export function Select({ className, label, ...p }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
      {label}
      <select
        className={cn(
          "h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
          className,
        )}
        {...p}
      />
    </label>
  );
}

export function Input(p: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...p}
      className={cn(
        "h-9 w-full rounded-md border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900",
        p.className,
      )}
    />
  );
}

export function Table({ head, rows }: { head: ReactNode[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500 dark:border-slate-800">
            {head.map((h, i) => (
              <th key={i} className="px-2 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0 dark:border-slate-800/60">
              {r.map((c, j) => (
                <td key={j} className="px-2 py-1.5 tabular-nums">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const fmt = (v: number | null | undefined, d = 1) =>
  v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
