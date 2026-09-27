import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Moon, Sun, Leaf } from "lucide-react";
import { api, auth } from "./lib/api";
import { LangCtx, useT, type Lang } from "./lib/i18n";
import { glossify } from "./lib/glossary";
import { Button, Skeleton } from "./components/ui";

const LiveMap = lazy(() => import("./pages/LiveMap"));
const MapOverview = lazy(() => import("./pages/MapOverview"));
const StateExplorer = lazy(() => import("./pages/StateExplorer"));
const Cities = lazy(() => import("./pages/Cities"));
const Insights = lazy(() => import("./pages/Insights"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Methodology = lazy(() => import("./pages/Methodology"));
const AdminConsole = lazy(() => import("./pages/AdminConsole"));
const Landing = lazy(() => import("./pages/Landing"));

// Viewer navigation. Model/training/data-quality internals live only under /admin (role-gated here AND in the API).
const NAV = [["/", "Live Map"], ["/overview", "India Map"], ["/state/IN-MH", "State Explorer"], ["/cities", "Cities"],
  ["/analytics", "Analytics"], ["/insights", "Insights"], ["/methodology", "Methodology"], ["/about", "About"]] as const;

function Shell() {
  const t = useT();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api("/auth/me") });
  const fullBleed = useLocation().pathname === "/";
  const [dark, setDark] = useState(() => localStorage.getItem("theme") !== "light");
  const [, force] = useState(0);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);
  const logout = () => { auth.set(null); qc.clear(); force((x) => x + 1); location.href = "/"; };
  const link = ({ isActive }: { isActive: boolean }) =>
    `whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`;
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2">
          <div className="flex items-center gap-1.5 font-semibold"><Leaf size={18} className="text-emerald-500" />CarbonScope <span className="text-emerald-500">India</span></div>
          <nav className="flex flex-1 gap-1 overflow-x-auto">
            {NAV.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"} className={link}>{t(label)}</NavLink>)}
            {me.data?.role === "admin" && <NavLink to="/admin" className={({ isActive }) => `${link({ isActive })} ring-1 ring-amber-400/30`}>{t("Admin")}</NavLink>}
          </nav>
          <LangToggle />
          <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={() => setDark(!dark)}>{dark ? <Sun size={16} /> : <Moon size={16} />}</Button>
          <Button variant="outline" size="sm" onClick={logout}>{t("Sign out")}</Button>
        </div>
      </header>
      <main className={fullBleed ? "" : "mx-auto min-h-[calc(100vh-49px)] max-w-7xl p-4"}>
        <Suspense fallback={<Skeleton className="h-96" />}>
          <Routes>
            <Route path="/" element={<LiveMap />} />
            <Route path="/overview" element={<MapOverview />} />
            <Route path="/state/:code" element={<StateExplorer />} />
            <Route path="/cities" element={<Cities />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/insights" element={<Insights />} />
            <Route path="/methodology" element={<Methodology />} />
            <Route path="/about" element={<Landing />} />
            <Route path="/admin/*" element={me.isLoading ? <Skeleton className="h-96" /> : me.data?.role === "admin" ? <AdminConsole /> : <Navigate to="/" />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </Suspense>
      </main>
      {!fullBleed && <SiteFooter />}
    </div>
  );
}

function SiteFooter() {
  return (
    <footer className="mx-auto max-w-7xl px-4 pb-6 pt-2 text-[11px] leading-relaxed text-slate-500">
      <div className="border-t border-white/5 pt-3">
        Data: {glossify("EDGAR 2025 · CEA · MoSPI · Census · NASA POWER · OxCGRT · World Bank")} — state values are EDGAR-downscaled estimates and city values are
        proxy estimates where noted; not official inventories. Emissions exclude {glossify("LULUCF")}. <a href="/methodology" className="text-emerald-400 hover:underline">Methodology, formulas &amp; glossary →</a>
      </div>
    </footer>
  );
}

function LangToggle() {
  return (
    <LangCtx.Consumer>
      {({ lang, setLang }) => (
        <Button variant="ghost" size="sm" aria-label="Toggle language" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
          {lang === "en" ? "हिन्दी" : "EN"}
        </Button>
      )}
    </LangCtx.Consumer>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(() => !!auth.get());
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem("lang") as Lang) || "en");
  useEffect(() => { localStorage.setItem("lang", lang); document.documentElement.lang = lang; }, [lang]);
  useEffect(() => {
    const h = () => setAuthed(false);
    window.addEventListener("carbonscope:logout", h);
    return () => window.removeEventListener("carbonscope:logout", h);
  }, []);
  return (
    <LangCtx.Provider value={{ lang, setLang }}>
      <BrowserRouter>{authed ? <Shell /> : <Suspense fallback={null}><Landing onDone={() => setAuthed(true)} /></Suspense>}</BrowserRouter>
    </LangCtx.Provider>
  );
}
