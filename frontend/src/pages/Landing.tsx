// Public landing page (shown before sign-in, and at /about after). Its own identity: fog + coal palette, Archivo with
// the width axis as the display device, and one signature element — India's emission stripes, 1970 → latest.
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { login } from "../lib/api";
import { SECTORS, SECTOR_LABEL, colorOf } from "../lib/sectors";

type Pub = {
  years: number[]; sectors: Record<string, number[]>;
  facts: {
    latest_year: number; india_mt: number; first_year: number; first_mt: number; power_share_pct: number;
    top_states: { name: string; mt: number }[]; fastest: { name: string; cagr_pct: number };
    states: number; cities: number; facilities: number;
  };
};

const INK = "#14202B", FOG = "#E9EDEE", SLATE = "#5B6770", TEAL = "#2F6F73", OCHRE = "#C98A1B";
const RAMP = ["#BFD8DE", "#C98A1B", "#A8432A", "#2B2521"]; // monsoon sky → ochre → rust → coal
const n0 = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 0 });

function ramp(t: number) {
  const x = Math.min(0.999, Math.max(0, t)) * (RAMP.length - 1), i = Math.floor(x), f = x - i;
  const hex = (h: string) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16));
  const a = hex(RAMP[i]), b = hex(RAMP[i + 1]);
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(",")})`;
}

// ---- signature: emission stripes --------------------------------------------------------------------------
function Stripes({ d }: { d?: Pub }) {
  const years = useMemo(() => d?.years ?? [], [d]);
  const totals = useMemo(() => years.map((_, i) => SECTORS.reduce((a, s) => a + (d?.sectors[s]?.[i] ?? 0), 0)), [d, years]);
  const [i, setI] = useState<number | null>(null);
  const k = i ?? years.length - 1;
  const ref = useRef<HTMLDivElement>(null);
  const lo = Math.min(...totals), hi = Math.max(...totals);
  const pick = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    setI(Math.max(0, Math.min(years.length - 1, Math.floor(((clientX - r.left) / r.width) * years.length))));
  };
  const key = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      setI(Math.max(0, Math.min(years.length - 1, k + (e.key === "ArrowRight" ? 1 : -1))));
    }
  };
  const tot = totals[k] ?? 0;
  return (
    <div className="relative">
      <div ref={ref} role="slider" tabIndex={0} aria-label="Year" aria-valuemin={years[0]} aria-valuemax={years[years.length - 1]}
        aria-valuenow={years[k]} aria-valuetext={`${years[k]}: ${n0(tot)} million tonnes CO2 equivalent`}
        onMouseMove={(e) => pick(e.clientX)} onTouchMove={(e) => pick(e.touches[0].clientX)} onKeyDown={key}
        className="flex h-[46vh] min-h-[280px] w-full cursor-crosshair overflow-hidden outline-none focus-visible:ring-4 focus-visible:ring-[#C98A1B]/60"
        style={{ background: FOG }}>
        {years.map((y, j) => (
          <div key={y} className="stripe relative h-full flex-1" style={{ background: ramp((totals[j] - lo) / (hi - lo || 1)), animationDelay: `${j * 18}ms`, marginRight: -1 }}>
            {j === k && i !== null && <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-white/70" />}
          </div>
        ))}
      </div>
      {d && (
        <div className="pointer-events-none absolute left-4 top-4 w-[min(22rem,calc(100%-2rem))] rounded-md p-4 shadow-[0_8px_30px_rgba(20,32,43,.25)] sm:left-8 sm:top-8"
          style={{ background: FOG, color: INK }} aria-hidden>
          <div className="wide text-5xl font-extrabold leading-none tracking-tight tabular-nums">{years[k]}</div>
          <div className="mt-1 text-sm" style={{ color: SLATE }}><b className="text-base tabular-nums" style={{ color: INK }}>{n0(tot)}</b> million tonnes CO₂e emitted in India</div>
          <div className="mt-3 flex h-2 overflow-hidden rounded-sm">
            {SECTORS.map((s) => <div key={s} style={{ width: `${(100 * (d.sectors[s]?.[k] ?? 0)) / (tot || 1)}%`, background: colorOf(s) }} />)}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[12px]" style={{ color: SLATE }}>
            {SECTORS.slice(0, 6).map((s) => (
              <span key={s} className="flex justify-between"><span><i className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: colorOf(s) }} />{SECTOR_LABEL[s]}</span>
                <span className="tabular-nums">{Math.round((100 * (d.sectors[s]?.[k] ?? 0)) / (tot || 1))}%</span></span>
            ))}
          </div>
        </div>
      )}
      <div className="flex justify-between px-4 pt-2 text-[13px] sm:px-8" style={{ color: SLATE }}>
        <span>{years[0]}</span><span className="hidden sm:inline">Move across the stripes to read any year</span><span>{years[years.length - 1]}</span>
      </div>
    </div>
  );
}

// ---- feature tour ---------------------------------------------------------------------------------------
const TOUR = [
  ["live", "Live Map", "An animated India map with 20 layers, emission-flow particles and a time slider running from 2000 into the 2029 forecast."],
  ["state", "State Explorer", "Each state's full history, its five-year forecast with an uncertainty range, the sector breakdown and a side-by-side comparison."],
  ["analytics", "Analytics", "Every sector, state and city on its own chart since 1970, India against the world since 1850, and the largest individual facilities."],
  ["compare", "Compare", "Up to eight states or cities on one chart, as absolute values, indexed to a base year, or as a share of the total."],
  ["cities", "Cities", "Estimated footprints for 64 cities, ranked, with their sector mix and their share of the state."],
  ["insights", "Insights", "Findings written automatically from the data — anomalies, decoupling, watchlists — each with its chart and formula, in English and Hindi."],
] as const;

function Tour() {
  const [on, setOn] = useState(0);
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,20rem)_1fr] lg:gap-12">
      <ul className="grid content-start gap-1" role="tablist" aria-label="Platform pages">
        {TOUR.map(([id, title, text], j) => (
          <li key={id}>
            <button role="tab" aria-selected={on === j} aria-controls="tour-panel" onClick={() => setOn(j)} onMouseEnter={() => setOn(j)}
              className="w-full rounded-md border-l-4 px-4 py-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-[#C98A1B]"
              style={{ borderColor: on === j ? OCHRE : "transparent", background: on === j ? "#fff" : "transparent" }}>
              <span className="wide block text-lg font-bold">{title}</span>
              <span className={`mt-1 text-[15px] leading-snug ${on === j ? "block" : "hidden lg:block"}`} style={{ color: SLATE }}>{text}</span>
            </button>
          </li>
        ))}
      </ul>
      <div id="tour-panel" role="tabpanel" className="self-start overflow-hidden rounded-lg border lg:sticky lg:top-24 shadow-[0_24px_60px_-20px_rgba(20,32,43,.45)]" style={{ borderColor: "#cfd6da", background: INK }}>
        {TOUR.map(([id, title], j) => (
          <img key={id} src={`/tour/${id}.jpg`} alt={`${title} screen`} loading={j ? "lazy" : "eager"} width={1440} height={851}
            className={`block h-auto w-full ${on === j ? "" : "hidden"}`} />
        ))}
      </div>
    </div>
  );
}

// ---- how it works: the leakage-safe year split is the one interactive bit ------------------------------------
const SPLIT = [
  ["Train", 1990, 2014, "#5B6770", "Models learn only from these years."],
  ["Validate", 2015, 2019, TEAL, "Used to choose the best model and its settings."],
  ["Test", 2020, 2024, OCHRE, "Held back until the end, including the COVID-19 shock, for an honest score."],
  ["Forecast", 2025, 2029, "#A8432A", "Five years ahead, with a P10–P90 range."],
] as const;

function SplitBar() {
  const [h, setH] = useState(0);
  return (
    <div className="mt-4">
      <div className="flex h-10 overflow-hidden rounded-md" role="group" aria-label="How the years are split">
        {SPLIT.map(([name, a, b, c], j) => (
          <button key={name} onMouseEnter={() => setH(j)} onFocus={() => setH(j)} onClick={() => setH(j)}
            className="flex items-center justify-center text-[13px] font-semibold text-white transition-opacity focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#14202B]"
            style={{ flex: b - a + 1, background: c, opacity: h === j ? 1 : 0.7 }}>{name}</button>
        ))}
      </div>
      <p className="mt-2 text-[15px]" style={{ color: SLATE }} aria-live="polite">
        <b style={{ color: INK }}>{SPLIT[h][1]}–{SPLIT[h][2]}.</b> {SPLIT[h][4]}
      </p>
    </div>
  );
}

const STEPS: [string, string][] = [
  ["Collect open data", "EDGAR 0.1° emission grids, CEA power-plant data, MoSPI state GDP, the Census, NASA POWER climate, Our World in Data, the World Bank and Climate TRACE. No paid licences, no API keys."],
  ["Map it to states and cities", "Each grid cell is split across state borders by area, giving 36 states and union territories × 7 sectors × every year since 1970, plus footprints for 64 cities."],
  ["Train forecasting models", "Eleven models, from a same-as-last-year baseline to LSTM, GRU, TCN, Seq2Seq with attention and a Temporal Fusion Transformer, never shown the years they are scored on."],
  ["Make the numbers add up", "MinT reconciliation adjusts the forecasts so that sectors sum to states and states sum to India exactly."],
  ["Explain what it means", "Automatic insights, what-if scenarios for renewables and electric vehicles, and a methodology page with every formula and source."],
];

// ---- sign in -------------------------------------------------------------------------------------------------
function SignIn({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent, register = false) => {
    e.preventDefault();
    // "Create account" is a type=button, so run the form's native validation (email format, ≥10 chars) ourselves
    if (!(e.currentTarget as HTMLElement).closest("form")?.reportValidity()) return;
    setBusy(true);
    try {
      await login(email, password, register);
      if (register) toast.success("Account created. You're signed in.");
      onDone();
    } catch (err: any) {
      toast.error(err.status === 409 ? "This email already has an account. Use Sign in."
        : err.status === 401 ? "Wrong email or password."
        : err.status === 429 ? "Too many attempts. Wait a minute and try again."
        : err.message);
    } finally {
      setBusy(false);
    }
  };
  const field = "h-12 w-full rounded-md border bg-white px-4 text-[16px] outline-none focus:border-[#C98A1B] focus:ring-2 focus:ring-[#C98A1B]/40";
  return (
    <form className="grid w-full max-w-md gap-3" onSubmit={(e) => submit(e)}>
      <label className="grid gap-1 text-sm font-medium">Email
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} style={{ borderColor: "#c3ccd1" }} />
      </label>
      <label className="grid gap-1 text-sm font-medium">Password
        <input type="password" required minLength={10} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} style={{ borderColor: "#c3ccd1" }} />
        <span className="text-[13px] font-normal" style={{ color: SLATE }}>At least 10 characters.</span>
      </label>
      <div className="mt-2 flex flex-wrap gap-3">
        <button disabled={busy} className="h-12 flex-1 rounded-md px-6 text-[16px] font-semibold text-white transition-colors hover:bg-[#233545] disabled:opacity-60" style={{ background: INK }}>Sign in</button>
        <button type="button" disabled={busy} onClick={(e) => submit(e as any, true)}
          className="h-12 flex-1 rounded-md border-2 px-6 text-[16px] font-semibold transition-colors hover:bg-white disabled:opacity-60" style={{ borderColor: INK }}>Create account</button>
      </div>
    </form>
  );
}

export default function Landing({ onDone }: { onDone?: () => void }) {
  const q = useQuery<Pub>({ queryKey: ["public-summary"], queryFn: () => fetch("/api/v2/analytics/public").then((r) => r.json()), staleTime: 3600e3 });
  const f = q.data?.facts;
  useEffect(() => { document.title = "CarbonScope India"; }, []);
  const nav = [["#why", "Why"], ["#inside", "What's inside"], ["#how", "How it works"], ["#team", "Team"]];
  return (
    <div className="lp min-h-screen">
      <header className="sticky top-0 z-30 border-b backdrop-blur" style={{ borderColor: "#d5dcdf", background: "rgba(233,237,238,.86)" }}>
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3 sm:px-8">
          <a href="#top" className="wide text-lg font-extrabold tracking-tight">CarbonScope India</a>
          <nav className="hidden flex-1 gap-5 text-[15px] md:flex" style={{ color: SLATE }}>
            {nav.map(([h, l]) => <a key={h} href={h} className="hover:text-[#14202B]">{l}</a>)}
          </nav>
          {onDone ? <a href="#signin" className="ml-auto rounded-md px-4 py-2 text-[15px] font-semibold text-white md:ml-0" style={{ background: INK }}>Sign in</a>
            : <Link to="/" className="ml-auto rounded-md px-4 py-2 text-[15px] font-semibold text-white md:ml-0" style={{ background: INK }}>Open the dashboard</Link>}
        </div>
      </header>

      <main id="top">
        <Stripes d={q.data} />
        <section className="mx-auto max-w-6xl px-4 pb-20 pt-12 sm:px-8">
          <h1 className="wide max-w-5xl text-[clamp(2.6rem,6.6vw,6rem)] font-extrabold leading-[0.95] tracking-[-0.02em]">
            India's carbon emissions, state by state.
          </h1>
          <p className="mt-6 max-w-[62ch] text-[1.1875rem] leading-relaxed" style={{ color: SLATE }}>
            CarbonScope India shows where India's greenhouse gases come from across {f?.states ?? 36} states and union territories,
            7 sectors and {f?.cities ?? 64} cities, from {f?.first_year ?? 1970} to today, and forecasts the next five years with deep learning.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a href={onDone ? "#signin" : "/"} className="rounded-md px-6 py-3 text-[16px] font-semibold text-white" style={{ background: INK }}>{onDone ? "Sign in to explore" : "Open the dashboard"}</a>
            <a href="#inside" className="rounded-md border-2 px-6 py-3 text-[16px] font-semibold" style={{ borderColor: INK }}>See what's inside</a>
          </div>
        </section>

        <section id="why" className="scroll-mt-16 border-t" style={{ borderColor: "#d5dcdf" }}>
          <div className="mx-auto grid max-w-6xl gap-12 px-4 py-20 sm:px-8 lg:grid-cols-2">
            <div>
              <h2 className="wide text-[clamp(1.9rem,3.6vw,2.9rem)] font-extrabold leading-tight tracking-tight">Why we built this</h2>
              <div className="mt-6 grid max-w-[60ch] gap-4 text-[17px] leading-relaxed" style={{ color: SLATE }}>
                <p>India reports its emissions as one national number. But the choices that change that number are made state by state:
                  coal power in Chhattisgarh and Odisha, cement and steel in Gujarat, paddy and livestock across the Gangetic plain, traffic in every growing city.</p>
                <p>Official state inventories are few, and they are years out of date. So we took open, global emission data, mapped it onto
                  every Indian state and major city, checked it against Indian power-plant records and three other independent sources, and trained models to forecast it.</p>
                <p>The result is a place where anyone can see who emits what, how fast it is growing, and where it is likely to be in 2029.</p>
              </div>
            </div>
            <dl className="grid content-start gap-8">
              {f ? ([
                [`${n0(f.india_mt)} Mt`, `CO₂e emitted by India in ${f.latest_year}, up from ${n0(f.first_mt)} Mt in ${f.first_year}.`],
                [`${f.power_share_pct}%`, "of it came from power stations, still the largest single source."],
                [f.top_states[0]?.name, `is the largest emitting state, at ${f.top_states[0]?.mt} Mt a year.`],
                [f.fastest.name, `is the fastest-growing large emitter: +${f.fastest.cagr_pct}% a year over the last decade.`],
              ] as const).map(([big, small]) => (
                <div key={small} className="border-l-4 pl-5" style={{ borderColor: OCHRE }}>
                  <dt className="wide text-[clamp(2rem,4vw,3.2rem)] font-extrabold leading-none tracking-tight tabular-nums">{big}</dt>
                  <dd className="mt-2 text-[17px]" style={{ color: SLATE }}>{small}</dd>
                </div>
              )) : <div className="h-72 animate-pulse rounded-md bg-white/60" />}
            </dl>
          </div>
        </section>

        <section id="inside" className="scroll-mt-16" style={{ background: "#DDE3E5" }}>
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-8">
            <h2 className="wide text-[clamp(1.9rem,3.6vw,2.9rem)] font-extrabold leading-tight tracking-tight">What's inside the platform</h2>
            <p className="mb-10 mt-3 max-w-[60ch] text-[17px]" style={{ color: SLATE }}>Real screens from the platform. Choose a page to see it.</p>
            <Tour />
          </div>
        </section>

        <section id="how" className="scroll-mt-16">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-8">
            <h2 className="wide text-[clamp(1.9rem,3.6vw,2.9rem)] font-extrabold leading-tight tracking-tight">How it works</h2>
            <ol className="mt-10 grid gap-10">
              {STEPS.map(([t, body], j) => (
                <li key={t} className="grid gap-4 sm:grid-cols-[5rem_1fr]">
                  <span className="wide text-5xl font-extrabold leading-none tabular-nums" style={{ color: j === 2 ? OCHRE : "#b7c1c6" }} aria-hidden>{j + 1}</span>
                  <div className="max-w-[64ch]">
                    <h3 className="wide text-2xl font-bold tracking-tight">{t}</h3>
                    <p className="mt-2 text-[17px] leading-relaxed" style={{ color: SLATE }}>{body}</p>
                    {j === 2 && <SplitBar />}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="team" className="scroll-mt-16" style={{ background: INK, color: FOG }}>
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-8">
            <h2 className="wide text-[clamp(1.9rem,3.6vw,2.9rem)] font-extrabold leading-tight tracking-tight">Team</h2>
            <p className="mt-3 max-w-[60ch] text-[17px]" style={{ color: "#aeb9c0" }}>A mini project, built with open data and open-source tools.</p>
            <ul className="mt-12 grid gap-8 sm:grid-cols-3">
              {["Sai Krish", "Karthik", "B Shiva"].map((name) => (
                <li key={name} className="border-t-4 pt-5" style={{ borderColor: OCHRE }}>
                  <span className="wide block text-[clamp(1.8rem,3.2vw,2.6rem)] font-extrabold leading-tight tracking-tight">{name}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {onDone && (
          <section id="signin" className="scroll-mt-16">
            <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-8 lg:grid-cols-2">
              <div>
                <h2 className="wide text-[clamp(1.9rem,3.6vw,2.9rem)] font-extrabold leading-tight tracking-tight">Open the platform</h2>
                <p className="mt-4 max-w-[52ch] text-[17px] leading-relaxed" style={{ color: SLATE }}>
                  Create an account with any email address to explore every map, chart and forecast. New accounts can view everything on the platform; model training is limited to administrators.
                </p>
              </div>
              <SignIn onDone={onDone} />
            </div>
          </section>
        )}
      </main>

      <footer className="border-t" style={{ borderColor: "#d5dcdf" }}>
        <div className="mx-auto max-w-6xl px-4 py-8 text-[14px] leading-relaxed sm:px-8" style={{ color: SLATE }}>
          Data from EDGAR 2025 (EU JRC), CEA, MoSPI, Census of India, NASA POWER, Our World in Data, the World Bank and Climate TRACE.
          State values are downscaled estimates and city values are proxy estimates, not official inventories.
        </div>
      </footer>
    </div>
  );
}
