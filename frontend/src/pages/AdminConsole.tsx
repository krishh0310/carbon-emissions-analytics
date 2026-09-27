// Admin-only console (/admin). The route is hidden for viewers and every API it calls returns 403 to non-admins.
import { lazy, Suspense } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { Skeleton } from "../components/ui";

const Training = lazy(() => import("./Admin"));
const ModelLab = lazy(() => import("./ModelLab"));
const DataQuality = lazy(() => import("./DataQuality"));
const P = (k: "Registry" | "Drift" | "Sources" | "Features" | "Moderation") => lazy(() => import("./AdminPanels").then((m) => ({ default: m[k] })));
const Registry = P("Registry"), Drift = P("Drift"), Sources = P("Sources"), Features = P("Features"), Moderation = P("Moderation");

const TABS = [
  ["", "Training Control"], ["registry", "Model Registry"], ["drift", "Drift"], ["models", "Model Lab"], ["data", "Data Quality"],
  ["sources", "Source Reconciliation"], ["features", "Feature Store"], ["insights", "Insight Moderation"],
] as const;

export default function AdminConsole() {
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-400/30 bg-amber-400/5 px-3 py-2">
        <ShieldCheck size={16} className="text-amber-400" />
        <span className="text-sm font-semibold">Admin console</span>
        <span className="text-xs text-slate-500">model internals, training and data quality — not visible to viewers</span>
        <nav className="ml-auto flex flex-wrap gap-1">
          {TABS.map(([to, label]) => (
            <NavLink key={to} to={`/admin${to ? `/${to}` : ""}`} end className={({ isActive }) => `rounded-md px-2.5 py-1 text-xs ${isActive ? "bg-amber-100 dark:bg-amber-400/20 text-amber-800 dark:text-amber-200" : "text-slate-400 hover:bg-slate-100 dark:hover:bg-white/5"}`}>{label}</NavLink>
          ))}
        </nav>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Routes>
          <Route index element={<Training />} />
          <Route path="models" element={<ModelLab />} />
          <Route path="data" element={<DataQuality />} />
          <Route path="registry" element={<Registry />} />
          <Route path="drift" element={<Drift />} />
          <Route path="sources" element={<Sources />} />
          <Route path="features" element={<Features />} />
          <Route path="insights" element={<Moderation />} />
        </Routes>
      </Suspense>
    </div>
  );
}
