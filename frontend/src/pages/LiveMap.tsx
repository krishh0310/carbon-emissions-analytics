// CarbonScope v2 Live Map (windy.com-style): full-bleed animated choropleth with 7 sector layers, anomaly /
// uncertainty / scenario layers, particle flow, timeline 2000→2029 with forecast band, glass tooltips,
// drill-down, compare mode, scenario sandbox and the ATAR intelligence feed with pulsing alert markers.
import { Suspense, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  Activity, Building2, Car, CircleDot, CloudRain, Factory, Flame, FlaskConical, Gauge, GitCompare, Leaf, Moon, Mountain,
  AlertTriangle, BadgeCheck, Pause, Play, Recycle, Search, Shapes, ShieldCheck, SkipBack, SkipForward, Sparkles, Thermometer, TrendingDown, Users, Waves,
  Wind, X, Zap,
} from "lucide-react";
import { api } from "../lib/api";
import { LangCtx } from "../lib/i18n";
import { useMe } from "../lib/me";
import { cn, fmt } from "../components/ui";
import { FlowLayer, SECTOR_COLORS, type Field } from "../live/FlowLayer";
import { ComparePanel, InsightFeed, SECTORS, SECTOR_LABEL, ScenarioPanel, type SectorSeries } from "../live/Panels";
import { Info } from "../components/Info";
import { StateView } from "./StateExplorer";

const PLASMA = ["#0d0887", "#41049d", "#6a00a8", "#8f0da4", "#b12a90", "#cc4778", "#e16462", "#f2844b", "#fca636", "#fcce25", "#f0f921"];
const TEMP = ["#313695", "#4575b4", "#74add1", "#abd9e9", "#e0f3f8", "#fee090", "#fdae61", "#f46d43", "#d73027", "#a50026"];
const RAIN = ["#1a1f3a", "#1e3a8a", "#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#e0f2fe"];
const DIVERGE = ["#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f1f5f9", "#fddbc7", "#f4a582", "#d6604d", "#b2182b"];
const GREENRED = ["#065f46", "#059669", "#34d399", "#a7f3d0", "#f1f5f9", "#fde68a", "#f59e0b", "#d97706", "#92400e"];
const VIRIDIS = ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"];
const MAGMA = ["#000004", "#1c1044", "#4f127b", "#812581", "#b5367a", "#e55064", "#fb8761", "#fec287", "#fcfdbf"];
const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const mixHex = (a: string, b: string, t: number) => "#" + hex(a).map((v, i) => Math.round(v + (hex(b)[i] - v) * t).toString(16).padStart(2, "0")).join("");
const ramp = (c: string) => ["#0b1020", mixHex("#0b1020", c, 0.35), mixHex("#0b1020", c, 0.65), c, mixHex(c, "#ffffff", 0.35), mixHex(c, "#ffffff", 0.7)];

type V1 = Record<string, Record<string, Record<string, number | null>>>;
type Fc1 = Record<string, { year: number; p10: number; p50: number; p90: number }[]>;
type Tri = Record<string, Record<string, { agreement?: number; divergent?: boolean; calibrated_co2e_mt?: number; edgar_power_mt?: number; cea_power_mt?: number }>>;
type Ctx = { v1: V1; fc1: Fc1; sec?: SectorSeries; anomaly?: Record<string, Record<string, number>>; unc?: Record<string, Record<string, number>>; scen?: any;
  tri?: Tri; dec?: Record<string, { status: string; gsdp_cagr: number; co2_cagr: number }>; wl?: Record<string, { excess_pct: number; severity: string }> };
type Layer = {
  key: string; label: string; hi: string; icon: any; unit: string; palette: string[]; diverging?: boolean; forecast?: boolean;
  digits: number; group: string; sector?: string; get: (c: Ctx, code: string, y: number) => number | null; disabled?: string;
  source: string; formula: string; extensive?: boolean; domain?: [number, number]; categories?: [string, string][];
};

const v1raw = (k: string) => (c: Ctx, s: string, y: number) => c.v1[s]?.[k]?.[y] ?? null;
const co2At = (c: Ctx, s: string, y: number): number | null => c.v1[s]?.co2?.[y] ?? c.fc1[s]?.find((p) => p.year === y)?.p50 ?? null;
const secAt = (c: Ctx, s: string, k: string, y: number): number | null =>
  c.sec?.history[s]?.[k]?.[y] ?? c.sec?.forecast[s]?.[k]?.find((p) => p.year === y)?.p50 ?? null;
const totAt = (c: Ctx, s: string, y: number) => {
  let t = 0, any = false;
  for (const k of SECTORS) { const v = secAt(c, s, k, y); if (v != null) { t += v; any = true; } }
  return any ? t : null;
};
const SECTOR_HI: Record<string, string> = { POWER: "बिजली", TRANSPORT: "परिवहन", INDUSTRY: "उद्योग", BUILDINGS: "भवन", AGRICULTURE: "कृषि", WASTE: "अपशिष्ट", OTHER: "अन्य" };
const SECTOR_ICON: Record<string, any> = { POWER: Zap, TRANSPORT: Car, INDUSTRY: Factory, BUILDINGS: Building2, AGRICULTURE: Leaf, WASTE: Recycle, OTHER: Shapes };
const E = "EDGAR 2025, downscaled";

const LAYERS: Layer[] = [
  { key: "co2e", group: "Totals", label: "Total CO₂e", hi: "कुल CO₂e", icon: Flame, unit: "MtCO₂e", palette: PLASMA, forecast: true, digits: 1, get: totAt, extensive: true,
    source: E, formula: "Σ 7 sectors (CO₂ + GWP-weighted CH₄, N₂O); forecast = Σ reconciled sector P50" },
  { key: "co2e_cal", group: "Totals", label: "CO₂e, CEA-calibrated", hi: "CEA-समायोजित CO₂e", icon: BadgeCheck, unit: "MtCO₂e", palette: PLASMA, digits: 1, extensive: true,
    get: (c, s, y) => c.tri?.[s]?.[y]?.calibrated_co2e_mt ?? totAt(c, s, y),
    source: `${E} · CEA CO₂ Baseline DB`, formula: "total CO₂e − EDGAR power CO₂ + CEA power CO₂ (FY2017+; grid plants only → lower bound where captive power is large)" },
  { key: "co2", group: "Totals", label: "Fossil CO₂", hi: "जीवाश्म CO₂", icon: Wind, unit: "MtCO₂", palette: PLASMA, forecast: true, digits: 1, get: co2At, extensive: true,
    source: E, formula: "Σ EDGAR CO₂ grid cells × area share inside state" },
  { key: "co2_per_capita", group: "Totals", label: "Per capita", hi: "प्रति व्यक्ति", icon: Users, unit: "tCO₂/person", palette: MAGMA, digits: 2, get: v1raw("co2_per_capita"),
    source: `${E} · Census`, formula: "fossil CO₂ (t) ÷ population" },
  { key: "carbon_intensity", group: "Totals", label: "Carbon intensity", hi: "कार्बन तीव्रता", icon: Gauge, unit: "tCO₂/₹ crore", palette: MAGMA, digits: 0, get: v1raw("carbon_intensity"),
    source: `${E} · MoSPI GSDP`, formula: "fossil CO₂ (t) ÷ real GSDP (₹ crore, 2011-12 prices)" },
  ...SECTORS.map((s, i): Layer => ({
    key: `sec:${s}`, group: "Sectors", sector: s, label: SECTOR_LABEL[s], hi: SECTOR_HI[s], icon: SECTOR_ICON[s], unit: "MtCO₂e",
    palette: ramp(SECTOR_COLORS[i]), forecast: true, digits: 2, get: (c, code, y) => secAt(c, code, s, y), extensive: true,
    source: E, formula: `${SECTOR_LABEL[s]} CO₂e from mapped EDGAR sub-sectors (AR6 GWP-100); forecast = reconciled P50`,
  })),
  { key: "anomaly", group: "Analytics", label: "Anomaly vs trend", hi: "रुझान से विचलन", icon: Activity, unit: "% vs 5-yr trend", palette: DIVERGE, diverging: true, digits: 1,
    get: (c, s, y) => c.anomaly?.[s]?.[y] ?? null, source: E, formula: "100 × (CO₂e_t ÷ exp(log-linear fit of t−5…t−1 evaluated at t) − 1)" },
  { key: "uncertainty", group: "Analytics", label: "Uncertainty (P90−P10)", hi: "अनिश्चितता", icon: Waves, unit: "(P90−P10)/P50 %", palette: VIRIDIS, forecast: true, digits: 1,
    get: (c, s, y) => c.unc?.[s]?.[y] ?? null, source: "CarbonScope Forecast", formula: "100 × (Σ sector P90 − Σ sector P10) ÷ Σ sector P50" },
  { key: "decoupling", group: "Analytics", label: "Decoupling status", hi: "डीकपलिंग स्थिति", icon: TrendingDown, unit: "category (last 10 yrs)", digits: 0,
    palette: ["#f43f5e", "#14b8a6", "#10b981"], domain: [0, 2], categories: [["#f43f5e", "none"], ["#14b8a6", "relative"], ["#10b981", "absolute"]],
    get: (c, s) => { const d = c.dec?.[s]?.status; return d === "absolute" ? 2 : d === "relative" ? 1 : d ? 0 : null; },
    source: `${E} · MoSPI GSDP`, formula: "absolute: GSDP CAGR > 0 & CO₂ CAGR < 0; relative: CO₂ CAGR < GSDP CAGR" },
  { key: "coal", group: "Analytics", label: "Coal-dependence index", hi: "कोयला निर्भरता", icon: Factory, unit: "% of fossil CO₂ from power", palette: MAGMA, digits: 0,
    get: (c, s, y) => { const v = c.v1[s]?.coal_dependence?.[y]; return v == null ? null : 100 * v; }, source: E, formula: "power-sector CO₂ ÷ total fossil CO₂ × 100" },
  { key: "watch", group: "Analytics", label: "Watchlist severity", hi: "निगरानी सूची", icon: AlertTriangle, unit: "% above fair-share path (2029)", palette: ["#1e293b", "#f59e0b", "#f97316", "#f43f5e"], digits: 0,
    domain: [0, 15], get: (c, s) => (c.wl ? c.wl[s]?.excess_pct ?? 0 : null), source: "CarbonScope Forecast · ATAR",
    formula: "forecast_2029 ÷ (CO₂e_2024 × (1 + fair-share CAGR)^5) − 1; 0 = on or below fair share" },
  { key: "scenario", group: "Forecast", label: "Scenario Δ 2029", hi: "परिदृश्य Δ", icon: FlaskConical, unit: "% vs baseline", palette: GREENRED, diverging: true, digits: 1,
    get: (c, s) => { const r = c.scen?.by_state?.find((x: any) => x.state_code === s); return r ? (100 * r.delta_mt) / Math.max(r.p50, 1e-9) : null; },
    source: "CarbonScope scenario engine", formula: "100 × (scenario P50 − baseline P50) ÷ baseline P50 in 2029" },
  { key: "cdd", group: "Context", label: "Cooling degree days", hi: "शीतलन डिग्री दिन", icon: Thermometer, unit: "°C·days (base 18 °C)", palette: TEMP, digits: 0,
    get: v1raw("cooling_degree_days"), source: "IMD gridded (NASA POWER fallback)", formula: "Σ_days max(daily mean temperature − 18 °C, 0), area-weighted" },
  { key: "avg_temp_c", group: "Context", label: "Temperature", hi: "तापमान", icon: Thermometer, unit: "°C", palette: TEMP, digits: 1, get: v1raw("avg_temp_c"),
    source: "IMD gridded (NASA POWER fallback)", formula: "annual mean of (Tmax + Tmin) ÷ 2, area-weighted" },
  { key: "monsoon_rainfall_mm", group: "Context", label: "Monsoon rain", hi: "मानसून वर्षा", icon: CloudRain, unit: "mm (Jun–Sep)", palette: RAIN, digits: 0, get: v1raw("monsoon_rainfall_mm"),
    source: "IMD gridded 0.25° (NASA POWER fallback)", formula: "Σ JJAS daily rainfall, area-weighted over the state — drives hydro output, cooling demand and paddy activity" },
  { key: "population_mn", group: "Context", label: "Population", hi: "जनसंख्या", icon: Users, unit: "million", palette: VIRIDIS, digits: 1, get: v1raw("population_mn"),
    source: "Census 2001/2011 + estimates", formula: "log-linear interpolation between census anchors" },
  { key: "nightlights", group: "Context", label: "Nightlights", hi: "रात्रि प्रकाश", icon: Moon, unit: "", palette: MAGMA, digits: 0, get: () => null, source: "NOAA VIIRS", formula: "—",
    disabled: "VIIRS nightlights need an EOG login — drop data/manual/extra/nightlights_radiance.csv to enable" },
  { key: "ev", group: "Context", label: "EV fleet", hi: "EV बेड़ा", icon: Car, unit: "", palette: VIRIDIS, digits: 0, get: () => null, source: "VAHAN", formula: "—",
    disabled: "VAHAN has no open API — drop data/manual/extra/ev_registrations.csv to enable" },
];

function makeScale(values: number[], palette: string[], diverging?: boolean, domain?: [number, number]) {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  let stops: number[];
  if (domain) {
    stops = palette.map((_, i) => domain[0] + ((domain[1] - domain[0]) * i) / (palette.length - 1));
  } else if (diverging) {
    const m = Math.max(1e-6, Math.abs(v[Math.floor(v.length * 0.05)] ?? 1), Math.abs(v[Math.floor(v.length * 0.95)] ?? 1));
    stops = palette.map((_, i) => -m + (2 * m * i) / (palette.length - 1));
  } else {
    stops = palette.map((_, i) => v[Math.min(v.length - 1, Math.floor((i / (palette.length - 1)) * (v.length - 1)))] ?? 0);
    for (let i = 1; i < stops.length; i++) if (stops[i] <= stops[i - 1]) stops[i] = stops[i - 1] + 1e-9;
  }
  const t = (x: number) => {
    if (x <= stops[0]) return 0;
    if (x >= stops[stops.length - 1]) return 1;
    const i = stops.findIndex((s) => s > x) - 1;
    return (i + (x - stops[i]) / (stops[i + 1] - stops[i])) / (stops.length - 1);
  };
  const color = (x: number | null) => {
    if (x == null || !Number.isFinite(x)) return "#1e293b";
    const p = t(x) * (palette.length - 1), i = Math.min(Math.floor(p), palette.length - 2);
    return mixHex(palette[i], palette[i + 1], p - i);
  };
  return { color, t, min: stops[0], max: stops[stops.length - 1] };
}

function Spark({ vals, color = "#34d399" }: { vals: number[]; color?: string }) {
  if (vals.length < 2) return null;
  const lo = Math.min(...vals), hi = Math.max(...vals), W = 90, H = 24;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * W},${H - ((v - lo) / (hi - lo || 1)) * (H - 2) - 1}`).join(" ");
  return <svg width={W} height={H}><polyline points={pts} fill="none" stroke={color} strokeWidth={1.6} /></svg>;
}

export default function LiveMap() {
  const nav = useNavigate();
  const { lang } = useContext(LangCtx);
  const [layerKey, setLayerKey] = useState("co2e");
  const { isAdmin } = useMe();
  const [model, setModel] = useState<string | null>(null); // admin-only override; viewers always get the champion
  const [yi, setYi] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [is3d, set3d] = useState(false);
  const [showCities, setShowCities] = useState(true);
  const [opacity, setOpacity] = useState(0.92);
  const [flowOn, setFlowOn] = useState(true);
  const [lowPower, setLowPower] = useState(false);
  const [density, setDensity] = useState(3000);
  const [panel, setPanel] = useState<"none" | "feed" | "scenario">("none");
  const [sel, setSel] = useState<string | null>(null);
  const [cmp, setCmp] = useState<{ a: string; b: string | null } | null>(null);
  const [scen, setScen] = useState<any>(null);
  const [hover, setHover] = useState<{ code: string; x: number; y: number } | null>(null);
  const [query, setQuery] = useState("");
  const [qi, setQi] = useState(0);
  const [fps, setFps] = useState(0);
  const [srcCheck, setSrcCheck] = useState(true);

  const layer = LAYERS.find((l) => l.key === layerKey)!;
  const geo = useQuery({ queryKey: ["states-geo"], queryFn: () => api("/states?limit=50"), staleTime: Infinity });
  const ser = useQuery({ queryKey: ["map-series", model], queryFn: () => api(`/map/series${model ? `?model=${model}` : ""}`) });
  const secq = useQuery({ queryKey: ["sector-series"], queryFn: () => api("/api/v2/sectors/series"), retry: false });
  const anq = useQuery({ queryKey: ["layer", "anomaly"], queryFn: () => api("/api/v2/layers/anomaly"), retry: false });
  const unq = useQuery({ queryKey: ["layer", "uncertainty"], queryFn: () => api("/api/v2/layers/uncertainty"), retry: false });
  const flowSector = layer.sector ?? "TOTAL";
  const flowq = useQuery({ queryKey: ["flow", flowSector], queryFn: () => api(`/api/v2/flow-field?sector=${flowSector}`), retry: false, staleTime: Infinity });
  const triq = useQuery({ queryKey: ["layer", "triangulation"], queryFn: () => api("/api/v2/layers/triangulation"), retry: false, staleTime: Infinity });
  const decq = useQuery({ queryKey: ["layer", "decoupling"], queryFn: () => api("/api/v2/layers/decoupling"), retry: false, staleTime: Infinity });
  const wlq = useQuery({ queryKey: ["layer", "watchlist"], queryFn: () => api("/api/v2/layers/watchlist"), retry: false, staleTime: Infinity });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => api("/api/v2/insights?severity=alert&limit=50"), retry: false });
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api("/cities?limit=100") });

  const ctx: Ctx = useMemo(() => ({ v1: ser.data?.series ?? {}, fc1: ser.data?.forecast ?? {}, sec: secq.data, anomaly: anq.data?.values,
    unc: unq.data?.values, scen, tri: triq.data?.values, dec: decq.data?.values, wl: wlq.data?.values }),
  [ser.data, secq.data, anq.data, unq.data, scen, triq.data, decq.data, wlq.data]);
  const obsYears: number[] = useMemo(() => (ser.data?.years ?? []).filter((y: number) => y >= 2000), [ser.data]);
  const fcYears: number[] = useMemo(() => ser.data?.forecast_years ?? [], [ser.data]);
  const allYears = useMemo(() => [...obsYears, ...fcYears], [obsYears, fcYears]);
  const lastObs = obsYears[obsYears.length - 1] ?? 2024;
  const idx = yi ?? Math.max(0, obsYears.length - 1);
  const year = layerKey === "scenario" ? fcYears[fcYears.length - 1] ?? 2029 : allYears[idx] ?? 2024;
  const isFc = year > lastObs;
  const effYear = isFc && !layer.forecast && layerKey !== "scenario" ? lastObs : year;
  const states: any[] = useMemo(() => geo.data?.items ?? [], [geo.data]);
  const nameOf = useCallback((c: string) => { const s = states.find((x) => x.code === c); return lang === "hi" && s?.name_hi ? s.name_hi : s?.name ?? c; }, [states, lang]);

  const scale = useMemo(() => {
    const vals: number[] = [];
    for (const s of states) for (const y of layerKey === "scenario" ? [year] : allYears) {
      const v = layer.get(ctx, s.code, y);
      if (v != null) vals.push(v);
    }
    return makeScale(vals, layer.palette, layer.diverging, layer.domain);
  }, [ctx, layer, allYears, states, layerKey, year]);
  const values = useMemo(() => Object.fromEntries(states.map((s) => [s.code, layer.get(ctx, s.code, effYear)])), [states, ctx, layer, effYear]);
  const ranked = useMemo(() => Object.entries(values).filter(([, v]) => v != null).sort((a, b) => (b[1] as number) - (a[1] as number)).map(([c]) => c), [values]);
  const national = useMemo(() => states.reduce((a, s) => a + ((layer.sector ? layer.get(ctx, s.code, year) : layerKey === "co2" ? co2At(ctx, s.code, year) : totAt(ctx, s.code, year) ?? co2At(ctx, s.code, year)) ?? 0), 0), [ctx, states, year, layer, layerKey]);

  const el = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const flow = useRef<FlowLayer | null>(null);
  const [ready, setReady] = useState(false);
  const shown = useRef<Record<string, number | null>>({});

  useEffect(() => {
    const m = new maplibregl.Map({
      container: el.current!, attributionControl: false, maxPitch: 65, bounds: [[66, 5.5], [99.5, 38]],
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#070b16" } }] },
    });
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    m.on("load", () => {
      const empty = { type: "FeatureCollection", features: [] } as any;
      m.addSource("st", { type: "geojson", data: empty });
      m.addSource("ct", { type: "geojson", data: empty });
      m.addSource("al", { type: "geojson", data: empty });
      m.addSource("dv", { type: "geojson", data: empty });
      m.addLayer({ id: "glow", type: "line", source: "st", paint: { "line-color": "#38bdf8", "line-width": 8, "line-blur": 8, "line-opacity": 0.12 } });
      m.addLayer({ id: "fill", type: "fill", source: "st", paint: { "fill-color": ["get", "c"], "fill-opacity": 0.92 } });
      m.addLayer({ id: "ext", type: "fill-extrusion", source: "st", layout: { visibility: "none" },
        paint: { "fill-extrusion-color": ["get", "c"], "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.95 } });
      m.addLayer({ id: "edge", type: "line", source: "st", paint: { "line-color": "#0b1020", "line-width": 0.7 } });
      // source-agreement ring (EDGAR vs CEA power CO₂): green ≥ 85 %, amber 70–85 %, red < 70 %
      m.addLayer({ id: "ring", type: "line", source: "st", paint: { "line-color": ["get", "ring"], "line-width": 2.2, "line-offset": -1.5, "line-opacity": 0.9 } });
      m.addLayer({ id: "hov", type: "line", source: "st", filter: ["==", ["get", "code"], ""], paint: { "line-color": "#ffffff", "line-width": 2 } });
      m.addLayer({ id: "sel", type: "line", source: "st", filter: ["==", ["get", "code"], ""], paint: { "line-color": "#34d399", "line-width": 3 } });
      m.addLayer({ id: "cmp", type: "line", source: "st", filter: ["==", ["get", "code"], ""], paint: { "line-color": "#60a5fa", "line-width": 3 } });
      m.addLayer({ id: "halo", type: "circle", source: "ct", minzoom: 4.3, paint: { "circle-radius": ["get", "r"], "circle-color": "#fde68a", "circle-opacity": 0, "circle-blur": 0.6 } });
      m.addLayer({ id: "dot", type: "circle", source: "ct", minzoom: 4.3, paint: {
        "circle-radius": ["*", ["get", "r"], 0.45], "circle-color": ["match", ["get", "tier"], "B", "#fde68a", "#fb923c"],
        "circle-stroke-color": "#0b1020", "circle-stroke-width": 1, "circle-opacity": 0.95 } });
      m.addLayer({ id: "dv", type: "circle", source: "dv", paint: { "circle-radius": 6, "circle-color": "#0b1020", "circle-stroke-color": "#f59e0b", "circle-stroke-width": 2 } });
      m.addLayer({ id: "dv-in", type: "circle", source: "dv", paint: { "circle-radius": 2, "circle-color": "#f59e0b" } });
      m.addLayer({ id: "al-pulse", type: "circle", source: "al", paint: { "circle-radius": 10, "circle-color": "#f43f5e", "circle-opacity": 0, "circle-blur": 0.4 } });
      m.addLayer({ id: "al-dot", type: "circle", source: "al", paint: { "circle-radius": 4.5, "circle-color": "#f43f5e", "circle-stroke-color": "#fff", "circle-stroke-width": 1.2 } });
      flow.current = new FlowLayer(m, cv.current!);
      setReady(true);
    });
    map.current = m;
    return () => { flow.current?.stop(); m.remove(); };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const hit = (e: any) => m.queryRenderedFeatures(e.point, { layers: [is3d ? "ext" : "fill"] })[0]?.properties?.code as string | undefined;
    const move = (e: any) => {
      const code = hit(e);
      m.setFilter("hov", ["==", ["get", "code"], code ?? ""]);
      m.getCanvas().style.cursor = code ? "pointer" : "";
      setHover(code ? { code, x: e.point.x, y: e.point.y } : null);
    };
    const click = (e: any) => {
      const code = hit(e) ?? null;
      if (cmp && code && code !== cmp.a) setCmp({ ...cmp, b: code });
      else setSel(code);
    };
    const leave = () => { setHover(null); m.setFilter("hov", ["==", ["get", "code"], ""]); };
    m.on("mousemove", move); m.on("click", click); m.getCanvas().addEventListener("mouseleave", leave);
    return () => { m.off("mousemove", move); m.off("click", click); m.getCanvas().removeEventListener("mouseleave", leave); };
  }, [ready, is3d, cmp]);

  const maxV = useMemo(() => Math.max(1e-9, ...Object.values(values).filter((v): v is number => v != null)), [values]);
  const agreeAt = useCallback((c: string) => ctx.tri?.[c]?.[Math.min(effYear, lastObs)]?.agreement, [ctx.tri, effYear, lastObs]);
  const paint = useCallback((vals: Record<string, number | null>) => {
    (map.current?.getSource("st") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: states.filter((s) => s.geometry).map((s) => {
        const v = vals[s.code] ?? null;
        const ag = srcCheck ? agreeAt(s.code) : undefined;
        // 3D: height ∝ Mt for emission layers (linear), rank-based for ratios/indices
        const h = v == null ? 0 : layer.extensive ? 12000 + (Math.max(v, 0) / maxV) * 650000 : 15000 + scale.t(v) * 520000;
        return { type: "Feature", geometry: s.geometry, properties: { code: s.code, c: scale.color(v), h,
          ring: ag == null ? "rgba(0,0,0,0)" : ag >= 0.85 ? "#10b981" : ag >= 0.7 ? "#f59e0b" : "#f43f5e" } };
      }),
    } as any);
  }, [states, scale, layer.extensive, maxV, srcCheck, agreeAt]);

  useEffect(() => {
    if (!ready || !states.length) return;
    const from = { ...shown.current }, to = values, t0 = performance.now(), D = 340;
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / D), e = 1 - (1 - k) ** 3;
      const cur: Record<string, number | null> = {};
      for (const c of Object.keys(to)) { const a = from[c], b = to[c]; cur[c] = a == null || b == null ? b : a + (b - a) * e; }
      paint(cur);
      shown.current = cur;
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [ready, values, paint, states.length]);

  useEffect(() => { if (ready) map.current!.setPaintProperty("fill", "fill-opacity", opacity); }, [opacity, ready]);
  // source-divergence markers (EDGAR vs CEA power CO₂ differ by > 15 %) at state centres, for the shown year
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const y = Math.min(effYear, lastObs);
    const feats = srcCheck ? states.filter((st) => st.geometry && ctx.tri?.[st.code]?.[y]?.divergent).map((st) => {
      const b = new maplibregl.LngLatBounds();
      const walk = (c: any) => (typeof c[0] === "number" ? b.extend(c as [number, number]) : c.forEach(walk));
      walk(st.geometry.coordinates);
      return { type: "Feature", geometry: { type: "Point", coordinates: b.getCenter().toArray() }, properties: { code: st.code } };
    }) : [];
    (m.getSource("dv") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: feats } as any);
  }, [ready, srcCheck, ctx.tri, effYear, lastObs, states]);
  useEffect(() => { if (ready) map.current!.setFilter("sel", ["==", ["get", "code"], sel ?? ""]); }, [sel, ready]);
  useEffect(() => { if (ready) map.current!.setFilter("cmp", ["==", ["get", "code"], cmp?.b ?? ""]); }, [cmp, ready]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    m.setLayoutProperty("ext", "visibility", is3d ? "visible" : "none");
    m.setLayoutProperty("fill", "visibility", is3d ? "none" : "visible");
    m.easeTo({ pitch: is3d ? 52 : 0, bearing: is3d ? -12 : 0, duration: 900 });
  }, [is3d, ready]);

  useEffect(() => {
    const f = flow.current;
    if (!ready || !f) return;
    if (flowq.data) f.setField(flowq.data as Field);
    f.setCount(lowPower ? Math.min(density, 800) : density);
    if (flowOn && flowq.data && !is3d) f.start(); else f.stop();
    const id = setInterval(() => setFps(f.fps), 1000);
    return () => clearInterval(id);
  }, [ready, flowq.data, flowOn, density, lowPower, is3d]);

  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const items: any[] = cities.data?.items ?? [];
    (m.getSource("ct") as GeoJSONSource).setData({ type: "FeatureCollection", features: showCities ? items.map((c) => ({ type: "Feature",
      geometry: { type: "Point", coordinates: [c.lon, c.lat] }, properties: { r: 6 + Math.sqrt(Math.max(c.co2_mt ?? 0, 0)) * 3.2, tier: c.confidence_tier } })) : [] } as any);
    const al = [...new Set<string>((alerts.data?.items ?? []).map((i: any) => i.state_code).filter(Boolean))];
    const center = (code: string) => {
      const s = states.find((x) => x.code === code);
      if (!s?.geometry) return null;
      const b = new maplibregl.LngLatBounds();
      const walk = (c: any) => (typeof c[0] === "number" ? b.extend(c as [number, number]) : c.forEach(walk));
      walk(s.geometry.coordinates);
      return b.getCenter().toArray();
    };
    (m.getSource("al") as GeoJSONSource).setData({ type: "FeatureCollection", features: al.map((c) => ({ type: "Feature",
      geometry: { type: "Point", coordinates: center(c) ?? [0, 0] }, properties: { code: c } })).filter((f) => f.geometry.coordinates[0]) } as any);
    let raf = 0;
    const loop = (now: number) => {
      const p = (now % 1800) / 1800;
      if (showCities) { m.setPaintProperty("halo", "circle-radius", ["*", ["get", "r"], 0.45 + p * 0.9]); m.setPaintProperty("halo", "circle-opacity", 0.55 * (1 - p)); }
      const q = (now % 1400) / 1400;
      m.setPaintProperty("al-pulse", "circle-radius", 5 + q * 22);
      m.setPaintProperty("al-pulse", "circle-opacity", 0.6 * (1 - q));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [ready, cities.data, showCities, alerts.data, states]);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setYi((i) => ((i ?? idx) + 1) % allYears.length), 750);
    return () => clearInterval(id);
  }, [playing, allYears.length, idx]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t?.tagName === "INPUT" && (t as HTMLInputElement).type === "text") return;
      if (e.code === "Space") { e.preventDefault(); setPlaying((p) => !p); }
      if (e.key === "ArrowRight") setYi(Math.min(allYears.length - 1, idx + 1));
      if (e.key === "ArrowLeft") setYi(Math.max(0, idx - 1));
      if (e.key === "Escape") { setSel(null); setCmp(null); setPanel("none"); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [idx, allYears.length]);

  const flyTo = (code: string) => {
    const s = states.find((x) => x.code === code);
    if (!s?.geometry || !map.current) return;
    const b = new maplibregl.LngLatBounds();
    const walk = (c: any) => (typeof c[0] === "number" ? b.extend(c as [number, number]) : c.forEach(walk));
    walk(s.geometry.coordinates);
    map.current.fitBounds(b, { padding: 140, duration: 1200, maxZoom: 7 });
    if (cmp) setCmp({ ...cmp, b: code }); else setSel(code);
  };
  // fuzzy match: in-order subsequence score (contiguous runs and word starts score higher); Hindi names and codes too
  const fuzzy = (q: string, t: string) => {
    q = q.toLowerCase(); t = t.toLowerCase();
    let i = 0, score = 0, run = 0;
    for (let j = 0; j < t.length && i < q.length; j++) {
      if (t[j] === q[i]) { run++; score += run * 2 + (j === 0 || t[j - 1] === " " ? 3 : 0); i++; } else run = 0;
    }
    return i === q.length ? score : -1;
  };
  const matches = query.length > 0 ? states.map((s) => ({ s, sc: Math.max(fuzzy(query, s.name), fuzzy(query, s.name_hi ?? ""), fuzzy(query, s.code)) }))
    .filter((x) => x.sc >= 0).sort((a, b) => b.sc - a.sc).slice(0, 7).map((x) => x.s) : [];
  const hv = hover ? values[hover.code] : null;
  const hvBand = hover && isFc ? (layer.sector ? ctx.sec?.forecast[hover.code]?.[layer.sector]?.find((p) => p.year === year)
    : layerKey === "co2" ? ctx.fc1[hover.code]?.find((p) => p.year === year) : null) : null;
  const hvSectors = hover ? SECTORS.map((s, k) => ({ s, k, v: secAt(ctx, hover.code, s, effYear) ?? 0 })) : [];
  const hvTot = hvSectors.reduce((a, x) => a + x.v, 0);
  const hvSpark = hover ? [effYear - 2, effYear - 1, effYear].map((y) => layer.get(ctx, hover.code, y)).filter((v): v is number => v != null) : [];
  const hvPrev = hover ? layer.get(ctx, hover.code, effYear - 1) : null;
  const hvYoy = hv != null && hvPrev ? 100 * (hv / hvPrev - 1) : null;
  const hvPc = hover ? (totAt(ctx, hover.code, Math.min(effYear, lastObs)) ?? 0) / (ctx.v1[hover.code]?.population_mn?.[Math.min(effYear, lastObs)] || NaN) : null;
  const hvAgree = hover ? agreeAt(hover.code) : undefined;
  const groups = [...new Set(LAYERS.map((l) => l.group))];

  return (
    <div className="relative h-[calc(100vh-49px)] w-full overflow-hidden bg-[#070b16] text-slate-100 select-none">
      <div className="absolute inset-0"><div ref={el} className="h-full w-full" role="application" aria-label="Interactive India emissions map" /></div>
      <canvas ref={cv} className="pointer-events-none absolute inset-0 z-[1] mix-blend-screen" />
      {(geo.isLoading || ser.isLoading) && <div className="absolute inset-0 grid place-items-center text-sm text-slate-400"><div className="animate-pulse">Loading India…</div></div>}

      <div className="absolute left-4 top-4 z-10 w-72 space-y-2">
        <div className="relative">
          <Search size={15} className="absolute left-3 top-2.5 text-slate-400" />
          <input value={query} onChange={(e) => { setQuery(e.target.value); setQi(0); }} placeholder="Search state / UT (fuzzy, ↑↓ Enter)…" aria-label="Search state"
            role="combobox" aria-expanded={matches.length > 0} aria-controls="state-search-list"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setQi((i) => Math.min(i + 1, matches.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setQi((i) => Math.max(i - 1, 0)); }
              if (e.key === "Enter" && matches[qi]) { flyTo(matches[qi].code); setQuery(""); }
              if (e.key === "Escape") setQuery("");
            }}
            className="h-9 w-full rounded-full border border-white/10 bg-slate-900/80 pl-9 pr-3 text-sm backdrop-blur outline-none focus:border-emerald-400/60" />
          {matches.length > 0 && (
            <div className="absolute mt-1 w-full overflow-hidden rounded-xl border border-white/10 bg-slate-900/95 backdrop-blur">
              <div id="state-search-list" role="listbox">
                {matches.map((s, k) => <button key={s.code} role="option" aria-selected={k === qi} className={cn("block w-full px-3 py-1.5 text-left text-sm hover:bg-white/10", k === qi && "bg-emerald-500/15")}
                  onMouseEnter={() => setQi(k)} onClick={() => { flyTo(s.code); setQuery(""); }}>{s.name} <span className="text-slate-500">{s.code}{s.is_ut ? " · UT" : ""}</span></button>)}
              </div>
            </div>
          )}
        </div>
        <div className="rounded-2xl border border-white/10 bg-slate-900/70 px-4 py-3 backdrop-blur">
          <div className="text-[11px] uppercase tracking-wider text-slate-400">India · {layer.sector ? SECTOR_LABEL[layer.sector] : "all sectors"} · {year} {isFc && <span className="text-amber-300">forecast</span>}</div>
          <div className="text-2xl font-semibold tabular-nums">{fmt(national, 0)} <span className="text-sm font-normal text-slate-400">{layerKey === "co2" ? "MtCO₂" : "MtCO₂e"}</span></div>
          <div className="mt-0.5 text-[11px] text-slate-500">{isFc ? "Σ MinT-reconciled state×sector P50" : "EDGAR-downscaled, Σ 36 states/UTs"}</div>
        </div>
      </div>

      {panel !== "feed" && (
        <div className="absolute right-4 top-4 z-10 flex max-h-[calc(100%-170px)] w-52 flex-col gap-0.5 overflow-y-auto rounded-2xl border border-white/10 bg-slate-900/75 p-1.5 backdrop-blur">
          {groups.map((g) => (
            <div key={g}>
              <div className="px-2 pb-0.5 pt-1.5 text-[9px] uppercase tracking-widest text-slate-500">{g}</div>
              {LAYERS.filter((l) => l.group === g).map((l) => {
                const I = l.icon;
                const sc = l.sector ? SECTOR_COLORS[SECTORS.indexOf(l.sector as any)] : undefined;
                return (
                  <button key={l.key} disabled={!!l.disabled || (l.key === "scenario" && !scen)} title={l.disabled ?? (l.key === "scenario" && !scen ? "Run a scenario first" : l.label)}
                    onClick={() => setLayerKey(l.key)}
                    className={cn("flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition disabled:cursor-not-allowed disabled:opacity-35",
                      l.key === layerKey ? "bg-emerald-500/20 text-emerald-100 ring-1 ring-emerald-400/40" : "text-slate-300 hover:bg-white/5")}>
                    <I size={14} className="shrink-0" style={sc ? { color: sc } : undefined} />
                    <span className="truncate">{lang === "hi" ? l.hi : l.label}</span>
                    {l.forecast && <span className="ml-auto rounded bg-amber-400/15 px-1 text-[9px] text-amber-300">FC</span>}
                  </button>
                );
              })}
            </div>
          ))}
          <div className="my-1 h-px bg-white/10" />
          <div className="grid grid-cols-2 gap-1 px-0.5">
            {([[Wind, "Particles", flowOn, () => setFlowOn(!flowOn)], [Mountain, "3D", is3d, () => set3d(!is3d)], [CircleDot, "Cities", showCities, () => setShowCities(!showCities)],
              [Sparkles, "ATAR feed", false, () => setPanel("feed")], [FlaskConical, "Scenario", panel === "scenario", () => setPanel(panel === "scenario" ? "none" : "scenario")],
              [GitCompare, "Pin 2 states", !!cmp, () => setCmp(cmp ? null : { a: sel ?? "IN-MH", b: null })],
              [ShieldCheck, "Source check", srcCheck, () => setSrcCheck(!srcCheck)]] as const).map(([I, label, on, fn]) => (
              <button key={label} onClick={fn} className={cn("flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px]", on ? "bg-sky-500/20 text-sky-100" : "text-slate-300 hover:bg-white/5")}><I size={13} />{label}</button>
            ))}
          </div>
          {flowOn && (
            <div className="space-y-1 px-2 pb-1 pt-1.5 text-[10px] text-slate-400">
              <div className="flex justify-between"><span>Particle density</span><span>{fps ? `${fps} fps` : ""}</span></div>
              <input type="range" min={500} max={6000} step={250} value={density} onChange={(e) => setDensity(+e.target.value)} className="w-full accent-sky-400" aria-label="Particle density" />
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={lowPower} onChange={(e) => setLowPower(e.target.checked)} className="accent-sky-400" />Low-power mode (≤800)</label>
            </div>
          )}
          {isAdmin && (
            <label className="flex items-center gap-2 px-2 py-1 text-[10px] text-amber-300/80">Admin: fossil model
              <select value={model ?? ""} onChange={(e) => setModel(e.target.value || null)} className="flex-1 rounded bg-slate-800 px-1 py-0.5 text-[11px] text-slate-100">
                <option value="">champion</option>
                {["tft", "seq2seq_attn", "lstm", "gru", "tcn", "deepar", "lightgbm", "ridge", "drift", "naive"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </label>
          )}
        </div>
      )}
      {panel === "feed" && <InsightFeed onGo={flyTo} onClose={() => setPanel("none")} />}
      {panel === "scenario" && <ScenarioPanel stateFilter={sel} onClose={() => setPanel("none")} onResult={(r) => { setScen(r); setLayerKey("scenario"); }} />}

      {hover && !sel && (
        <div className="pointer-events-none absolute z-20 w-56 rounded-xl border border-white/15 bg-slate-950/70 px-3 py-2 text-xs shadow-2xl backdrop-blur-xl"
          style={{ left: Math.min(hover.x + 16, window.innerWidth - 240), top: hover.y + 16 }}>
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold">{nameOf(hover.code)}</span>
            {hvAgree != null && (
              <span className="flex items-center gap-1 text-[9px] text-slate-400" title="EDGAR vs CEA power-sector agreement">
                <svg width="18" height="18" viewBox="0 0 36 36"><circle cx="18" cy="18" r="15" fill="none" stroke="#1e293b" strokeWidth="5" />
                  <circle cx="18" cy="18" r="15" fill="none" stroke={hvAgree >= 0.85 ? "#10b981" : hvAgree >= 0.7 ? "#f59e0b" : "#f43f5e"} strokeWidth="5"
                    strokeDasharray={`${94.2 * hvAgree} 94.2`} transform="rotate(-90 18 18)" /></svg>{Math.round(100 * hvAgree)}% src
              </span>
            )}
          </div>
          <div className="mt-0.5 grid grid-cols-3 gap-1 text-center">
            <div className="rounded bg-white/5 px-1 py-0.5"><div className="text-[9px] text-slate-400">{layer.label.split(" (")[0]}</div>
              <div className="font-semibold tabular-nums" style={{ color: scale.color(hv) }}>{fmt(hv, layer.digits)}</div></div>
            <div className="rounded bg-white/5 px-1 py-0.5"><div className="text-[9px] text-slate-400">t/person</div><div className="font-semibold tabular-nums">{fmt(hvPc, 2)}</div></div>
            <div className="rounded bg-white/5 px-1 py-0.5"><div className="text-[9px] text-slate-400">vs {effYear - 1}</div>
              <div className={cn("font-semibold tabular-nums", hvYoy == null ? "" : hvYoy > 0 ? "text-amber-400" : "text-emerald-400")}>{hvYoy == null ? "—" : `${hvYoy > 0 ? "▲" : "▼"}${fmt(Math.abs(hvYoy), 1)}%`}</div></div>
          </div>
          <div className="mt-1 flex items-center justify-between text-[10px] text-slate-400"><span>{layer.unit}</span><Spark vals={hvSpark} color={hvYoy != null && hvYoy > 0 ? "#f59e0b" : "#34d399"} /></div>
          {hvBand && <div className="text-amber-300">P10–P90: {fmt(hvBand.p10, layer.digits)} – {fmt(hvBand.p90, layer.digits)}</div>}
          {hvTot > 0 && (
            <div className="mt-1">
              <div className="flex h-2.5 overflow-hidden rounded">{hvSectors.map(({ s, k, v }) => <div key={s} style={{ width: `${(100 * v) / hvTot}%`, background: SECTOR_COLORS[k] }} />)}</div>
              <div className="mt-0.5 flex flex-wrap gap-x-1.5 text-[9px] text-slate-400">
                {hvSectors.filter((x) => x.v / hvTot >= 0.05).map(({ s, k, v }) => <span key={s}><i className="mr-0.5 inline-block h-1.5 w-1.5 rounded-full" style={{ background: SECTOR_COLORS[k] }} />{SECTOR_LABEL[s]} {Math.round((100 * v) / hvTot)}%</span>)}
              </div>
            </div>
          )}
          <div className="mt-1 text-slate-500">#{ranked.indexOf(hover.code) + 1} of {ranked.length} · {effYear}{cmp ? " · click to compare" : ""}</div>
        </div>
      )}

      {sel && !cmp && (
        <aside className="absolute inset-y-0 right-0 z-30 flex w-full max-w-[920px] flex-col border-l border-white/10 bg-slate-950/95 shadow-2xl backdrop-blur-xl animate-[slidein_.25s_ease-out]"
          aria-label={`${nameOf(sel)} details`}>
          <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
            <span className="text-base font-semibold">{nameOf(sel)}</span><span className="text-xs text-slate-500">{sel}</span>
            <button onClick={() => setCmp({ a: sel, b: null })} className="ml-auto rounded-md border border-white/10 px-2 py-1 text-xs text-sky-300 hover:bg-white/5">Pin & compare</button>
            <button onClick={() => nav(`/state/${sel}`)} className="rounded-md border border-white/10 px-2 py-1 text-xs text-emerald-300 hover:bg-white/5">Open full page →</button>
            <button onClick={() => setSel(null)} aria-label="Close" className="rounded-md p-1 text-slate-400 hover:bg-white/10"><X size={16} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-4"><Suspense fallback={<div className="h-96 animate-pulse rounded-xl bg-white/5" />}><StateView code={sel} compact /></Suspense></div>
        </aside>
      )}
      {cmp && <ComparePanel a={cmp.a} b={cmp.b} names={nameOf} data={ctx.sec} lastObs={lastObs} onClose={() => setCmp(null)} onPick={(c) => setCmp({ ...cmp, b: c })}
        pop={(c: string) => ctx.v1[c]?.population_mn?.[lastObs] ?? null} />}

      <div className="absolute inset-x-4 bottom-4 z-10 rounded-2xl border border-white/10 bg-slate-900/80 px-4 pb-3 pt-2 backdrop-blur">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-300"><b>{lang === "hi" ? layer.hi : layer.label}</b>
            <Info how={{ formula: layer.formula, source: layer.source }} align="left" />
            <span className="text-slate-500"> · {layer.unit}{isFc && !layer.forecast && layerKey !== "scenario" ? ` · no forecast for this layer, showing ${lastObs}` : ""}{layerKey === "scenario" && scen ? ` · ${scen.name}` : ""}</span></div>
          <div className="flex flex-1 items-center gap-2 sm:max-w-lg">
            {layer.categories ? (
              <div className="flex flex-1 gap-3 text-[10px] text-slate-300">{layer.categories.map(([c, l]) => <span key={l} className="flex items-center gap-1"><i className="inline-block h-2.5 w-4 rounded-sm" style={{ background: c }} />{l}</span>)}</div>
            ) : (<>
              <span className="text-[10px] tabular-nums text-slate-400">{fmt(scale.min, layer.digits)}</span>
              <div className="h-2.5 flex-1 rounded-full" style={{ background: `linear-gradient(90deg, ${layer.palette.join(",")})` }} />
              <span className="text-[10px] tabular-nums text-slate-400">{fmt(scale.max, layer.digits)}</span>
            </>)}
            <span className="hidden rounded border border-white/10 px-1.5 text-[9px] text-slate-500 md:inline">{layer.source}</span>
            <label className="ml-2 flex items-center gap-1 text-[10px] text-slate-400">opacity
              <input type="range" min={0.2} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(+e.target.value)} className="w-20 accent-emerald-500" aria-label="Layer opacity" />
            </label>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button aria-label="Previous year" onClick={() => setYi(Math.max(0, idx - 1))} className="text-slate-400 hover:text-white"><SkipBack size={16} /></button>
          <button aria-label={playing ? "Pause" : "Play"} onClick={() => setPlaying(!playing)}
            className="grid h-9 w-9 place-items-center rounded-full bg-emerald-500 text-slate-950 shadow-lg shadow-emerald-500/30 hover:bg-emerald-400">
            {playing ? <Pause size={16} /> : <Play size={16} className="ml-0.5" />}
          </button>
          <button aria-label="Next year" onClick={() => setYi(Math.min(allYears.length - 1, idx + 1))} className="text-slate-400 hover:text-white"><SkipForward size={16} /></button>
          <div className={cn("w-14 text-center text-xl font-semibold tabular-nums", isFc && "text-amber-300")}>{year}</div>
          <div className="relative flex-1">
            <div className="flex h-7 items-end">
              {allYears.map((y, i) => (
                <div key={y} className="relative flex-1">
                  <div className={cn("mx-px rounded-t-sm transition-all", y > lastObs ? "bg-amber-400/40 [background-image:repeating-linear-gradient(45deg,transparent_0_3px,rgba(0,0,0,.35)_3px_5px)]" : "bg-slate-500/40",
                    i === idx && "!bg-emerald-400", i < idx && y <= lastObs && "bg-emerald-400/35")}
                    style={{ height: i === idx ? 22 : y % 5 === 0 ? 12 : 6 }} />
                  {y % 5 === 0 && <div className="absolute -bottom-4 left-0 text-[9px] text-slate-500">{y}</div>}
                </div>
              ))}
            </div>
            {fcYears.length > 0 && <div className="pointer-events-none absolute -top-3 right-0 text-[9px] uppercase tracking-wider text-amber-300" style={{ width: `${(100 * fcYears.length) / Math.max(allYears.length, 1)}%` }}>forecast →</div>}
            <input type="range" min={0} max={Math.max(0, allYears.length - 1)} value={idx} aria-label="Year"
              onChange={(e) => { setPlaying(false); setYi(+e.target.value); }} className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
          </div>
        </div>
        <div className="mt-3 text-[10px] text-slate-500">
          Space play/pause · ←/→ year · Esc close · particles = emission-density flow by dominant sector (not wind) ·{" "}
          {SECTORS.map((s, k) => <span key={s} className="mr-1.5 inline-flex items-center gap-0.5"><i className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: SECTOR_COLORS[k] }} />{SECTOR_LABEL[s]}</span>)}
          · red pulses = ATAR alerts · state outline ring = EDGAR-vs-CEA power agreement (green ≥ 85 %, amber, red), amber ◎ = source divergence &gt; 15 % · EDGAR-downscaled estimates
        </div>
      </div>
    </div>
  );
}
