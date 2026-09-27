// Windy-style animated particle layer on a 2D canvas over MapLibre. Particles advect through a precomputed
// emission-density flow field (/api/v2/flow-field), spawn in proportion to local intensity, and are coloured by the
// dominant sector of their cell. ~3k particles at 60 fps on integrated GPUs; low-power mode draws 800.
import type { Map as MLMap } from "maplibre-gl";

import { SECTOR_COLORS } from "../lib/sectors";

export { SECTOR_COLORS };

export type Field = { bbox: number[]; nx: number; ny: number; res: number; u: number[]; v: number[]; s: number[]; dom: number[] };

export class FlowLayer {
  private ctx: CanvasRenderingContext2D;
  private field: Field | null = null;
  private cdf: Float32Array = new Float32Array(0);
  private cells: Int32Array = new Int32Array(0);
  private px = new Float32Array(0);
  private py = new Float32Array(0);
  private age = new Float32Array(0);
  private raf = 0;
  private running = false;
  private dpr = Math.min(window.devicePixelRatio || 1, 2);
  count = 3000;
  speed = 1;
  fps = 0;

  private map: MLMap;
  private canvas: HTMLCanvasElement;

  constructor(map: MLMap, canvas: HTMLCanvasElement) {
    this.map = map;
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d")!;
    const clear = () => this.clear();
    map.on("movestart", clear);
    map.on("move", clear);
    map.on("resize", () => this.resize());
    this.resize();
  }

  resize() {
    const r = this.map.getContainer().getBoundingClientRect();
    this.canvas.width = r.width * this.dpr;
    this.canvas.height = r.height * this.dpr;
    this.canvas.style.width = `${r.width}px`;
    this.canvas.style.height = `${r.height}px`;
    this.clear();
  }

  clear() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  setField(f: Field) {
    this.field = f;
    // spawn distribution ∝ intensity² (concentrates particles on real emission clusters)
    const idx: number[] = [];
    const w: number[] = [];
    for (let i = 0; i < f.s.length; i++) if (f.s[i] > 25) { idx.push(i); w.push((f.s[i] / 255) ** 2); }
    this.cells = Int32Array.from(idx);
    this.cdf = new Float32Array(w.length);
    let acc = 0;
    w.forEach((x, i) => { acc += x; this.cdf[i] = acc; });
    for (let i = 0; i < this.cdf.length; i++) this.cdf[i] /= acc || 1;
    this.setCount(this.count);
  }

  setCount(n: number) {
    this.count = n;
    this.px = new Float32Array(n);
    this.py = new Float32Array(n);
    this.age = new Float32Array(n);
    for (let i = 0; i < n; i++) this.spawn(i, true);
    this.clear();
  }

  private spawn(i: number, randomAge = false) {
    const f = this.field;
    if (!f || !this.cdf.length) return;
    const r = Math.random();
    let lo = 0, hi = this.cdf.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (this.cdf[m] < r) lo = m + 1; else hi = m; }
    const c = this.cells[lo];
    const iy = Math.floor(c / f.nx), ix = c % f.nx;
    this.px[i] = f.bbox[0] + (ix + Math.random() - 0.5) * f.res;
    this.py[i] = f.bbox[1] + (iy + Math.random() - 0.5) * f.res;
    this.age[i] = randomAge ? Math.random() * 80 : 0;
  }

  private sample(lon: number, lat: number) {
    const f = this.field!;
    const ix = Math.round((lon - f.bbox[0]) / f.res), iy = Math.round((lat - f.bbox[1]) / f.res);
    if (ix < 0 || iy < 0 || ix >= f.nx || iy >= f.ny) return null;
    const k = iy * f.nx + ix;
    return { u: f.u[k] / 127, v: f.v[k] / 127, s: f.s[k] / 255, d: f.dom[k] };
  }

  start() {
    if (this.running) return;
    this.running = true;
    let last = performance.now(), frames = 0, t0 = last;
    const tick = (now: number) => {
      if (!this.running) return;
      const dt = Math.min((now - last) / 16.7, 3);
      last = now;
      this.step(dt);
      frames++;
      if (now - t0 > 1000) { this.fps = Math.round((frames * 1000) / (now - t0)); frames = 0; t0 = now; }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.clear();
  }

  private step(dt: number) {
    if (!this.field) return;
    const ctx = this.ctx, d = this.dpr;
    ctx.globalCompositeOperation = "destination-in";
    ctx.fillStyle = "rgba(0,0,0,0.9)";
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = 1.2 * d;
    const zoomK = 0.035 / Math.pow(1.6, this.map.getZoom() - 4); // keep on-screen speed roughly zoom-independent
    for (let i = 0; i < this.count; i++) {
      const p = this.sample(this.px[i], this.py[i]);
      if (!p || p.s < 0.08 || this.age[i] > 90) { this.spawn(i); continue; }
      const a = this.map.project([this.px[i], this.py[i]]);
      const sp = (0.25 + 1.6 * p.s) * zoomK * this.speed * dt;
      this.px[i] += p.u * sp;
      this.py[i] += p.v * sp;
      this.age[i] += dt;
      const b = this.map.project([this.px[i], this.py[i]]);
      ctx.strokeStyle = SECTOR_COLORS[p.d] ?? "#e2e8f0";
      ctx.globalAlpha = Math.min(0.9, 0.25 + p.s);
      ctx.beginPath();
      ctx.moveTo(a.x * d, a.y * d);
      ctx.lineTo(b.x * d, b.y * d);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
}
