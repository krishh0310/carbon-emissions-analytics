// MapLibre choropleth of India's 36 states/UTs (no basemap tiles, no API key) + optional city bubbles.
import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

export const SEQ = ["#ccfbf1", "#99f6e4", "#5eead4", "#2dd4bf", "#14b8a6", "#0d9488", "#0f766e", "#115e59"];

export function quantileBreaks(values: number[], n = SEQ.length): number[] {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return [];
  return Array.from({ length: n - 1 }, (_, i) => v[Math.floor(((i + 1) * v.length) / n)]);
}

type StateFeature = { code: string; name: string; value: number | null; geometry: any };
type Bubble = { id: number; name: string; lat: number; lon: number; value: number; tier: string };

export function IndiaMap({ states, bubbles, onSelect, unit, height = 520 }: {
  states: StateFeature[]; bubbles?: Bubble[]; onSelect?: (code: string) => void; unit: string; height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const fc = () => {
    const breaks = quantileBreaks(states.map((s) => s.value ?? NaN));
    const color = (v: number | null) => (v == null ? "#475569" : SEQ[breaks.filter((b) => v > b).length]);
    return {
      type: "FeatureCollection" as const,
      features: states.filter((s) => s.geometry).map((s) => ({
        type: "Feature" as const, geometry: s.geometry,
        properties: { code: s.code, name: s.name, value: s.value, color: color(s.value) },
      })),
    };
  };
  const bc = () => ({
    type: "FeatureCollection" as const,
    features: (bubbles ?? []).map((b) => ({
      type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [b.lon, b.lat] },
      properties: { name: b.name, value: b.value, tier: b.tier, r: 3 + Math.sqrt(Math.max(b.value, 0)) * 2.2 },
    })),
  });

  useEffect(() => {
    const dark = document.documentElement.classList.contains("dark");
    const m = new maplibregl.Map({
      container: el.current!,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": dark ? "#020617" : "#f8fafc" } }] },
      bounds: [[67.5, 6], [98, 37.5]], fitBoundsOptions: { padding: 12 }, attributionControl: false, dragRotate: false,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("states", { type: "geojson", data: fc() });
      m.addLayer({ id: "fill", type: "fill", source: "states", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.9 } });
      m.addLayer({ id: "line", type: "line", source: "states", paint: { "line-color": dark ? "#0f172a" : "#ffffff", "line-width": 0.8 } });
      m.addSource("cities", { type: "geojson", data: bc() });
      m.addLayer({
        id: "bubbles", type: "circle", source: "cities",
        paint: {
          "circle-radius": ["get", "r"], "circle-color": ["match", ["get", "tier"], "B", "#f59e0b", "#fb7185"],
          "circle-opacity": 0.65, "circle-stroke-color": "#fff", "circle-stroke-width": 0.6,
        },
      });
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
      const fmt = (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—");
      m.on("mousemove", "fill", (e: any) => {
        const p = e.features?.[0]?.properties;
        m.getCanvas().style.cursor = "pointer";
        if (p) popup.setLngLat(e.lngLat).setHTML(`<b>${p.name}</b><br/>${fmt(p.value)} ${unit}`).addTo(m);
      });
      m.on("mouseleave", "fill", () => { m.getCanvas().style.cursor = ""; popup.remove(); });
      m.on("mousemove", "bubbles", (e: any) => {
        const p = e.features?.[0]?.properties;
        if (p) popup.setLngLat(e.lngLat).setHTML(`<b>${p.name}</b> (estimate, tier ${p.tier})<br/>${fmt(p.value)} MtCO₂`).addTo(m);
      });
      m.on("click", "fill", (e: any) => {
        const code = e.features?.[0]?.properties?.code;
        if (code) onSelectRef.current?.(code);
      });
      ready.current = true;
    });
    map.current = m;
    return () => { ready.current = false; m.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!ready.current || !map.current) return;
    (map.current.getSource("states") as GeoJSONSource | undefined)?.setData(fc());
    (map.current.getSource("cities") as GeoJSONSource | undefined)?.setData(bc());
  });

  return <div ref={el} style={{ height }} className="w-full overflow-hidden rounded-lg" role="img" aria-label="India choropleth map" />;
}

export function Legend({ values, unit }: { values: number[]; unit: string }) {
  const b = quantileBreaks(values);
  const f = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: v < 10 ? 2 : 0 });
  return (
    <div className="flex flex-wrap items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400">
      {SEQ.map((c, i) => (
        <div key={c} className="flex items-center gap-1">
          <span className="inline-block h-3 w-5 rounded-sm" style={{ background: c }} />
          {i < b.length && <span>{f(b[i])}</span>}
        </div>
      ))}
      <span className="ml-1">{unit} (quantile classes)</span>
    </div>
  );
}
