# Changelog

## v4 follow-up — landing placement (2026-09-27)

- `frontend/src/App.tsx`, `frontend/src/pages/Landing.tsx`: About is linked from the public header at `/about`; it stays outside the signed-in navigation. Authenticated `/about` returns to the dashboard.

## v4 — stages 1–2 (2026-09-27)

### Stage 1 — full sector drill-down
- `frontend/src/pages/SectorDetail.tsx`: added `/state/:code/sector/:sector` with a full history and P10–P90 forecast, detected annual shifts and smoothed trend, indexed drivers, sector intensity, national benchmark, up to three peer forecasts and fans, scenario levers, and a copyable/exportable yearly table. Charts have units, sources, formulas, tooltips, legends, brush controls and PNG/CSV export.
- `frontend/src/App.tsx`, `frontend/src/pages/StateExplorer.tsx`, `frontend/src/pages/Analytics.tsx`, `frontend/src/state/StateCharts.tsx`, `frontend/src/insights/InsightCard.tsx`: wired state sector panels, stacked areas, driver panels, analytics top-state bars and state-specific insight sector chips to the URL-addressable drill-down.
- `src/scenarios.py`: scenario responses now include per-state, per-sector yearly paths so the drill-down can overlay the entire counterfactual band.

### Stage 2 — five-year coverage and city allocation
- `src/train/coverage.py`, `src/train/sector_run.py`: training fails if any state × sector × horizon 1–5 forecast or reconciled median is missing.
- `src/train/city_share.py`, `backend/app/seed.py`: seeded city forecasts use the trailing three-year city/state-sector shares, cap overlapping city buffers collectively at the state sector total, and keep the remainder as an explicit unallocated state amount. No rural emissions are assigned to sampled cities merely to force coverage. At full precision, city forecasts plus the unallocated remainder equal the state-sector sums to `1e-6` Mt; the public five-decimal city values can differ by up to `0.000005 × (number of cities + 1)` Mt per state/year due to rounding.
- `backend/app/v2.py`: added viewer-safe `GET /api/v2/cities/{city_id}/forecast`; sector endpoints now return nonnegative bounds enclosing reconciled P50.
- `tests/test_forecast_coverage.py`, `tests/test_api.py`: CI checks the complete 36 × 7 × 5 and 64 × 5 coverage contracts, real artifacts when present, city/state reconciliation, and the viewer city forecast endpoint.

The existing state × sector models already forecast through 2029, and the city-share model is an allocation of those forecasts. Regenerate the city analytics artifact with `python -m backend.app.seed` before serving the new city values.

## v3.2 — public landing page (2026-09-27)

- A public home page greets visitors before sign-in, and signed-in users can reach it at `/about`.
  - **Emission stripes:** India's real 1970–2024 emissions, one stripe per year. Hover, touch or use the arrow keys to read any year's total and sector split.
  - **Why we built this:** includes live facts.
  - **What's inside:** a tour of 6 real screens.
  - **How it works:** 5 steps, with an interactive train / validate / test / forecast year bar.
  - **Team:** Sai Krish Karthik and B Shiva.
  - **Sign in / create account form.**
- **Design:** a light fog-and-coal identity with Archivo's width axis for display type. The page is responsive down to phones, respects reduced motion, and has keyboard-accessible controls.
- **New public endpoint** `GET /api/v2/analytics/public`: no login, rate-limited, returns national history and headline facts only (no forecasts or model details).
- The old standalone login card was removed; sign-in now lives on the landing page.

## v3.1 — live open-data APIs, 1970+ history, Analytics page (2026-09-27)

### Data
- **New sources (no API key, SHA-256 cached, `make external`):**
  - Our World in Data CO₂/GHG: India + 11 peers, 1850–2024.
  - World Bank WDI `EN.GHG.*` API: India, 1970–2024.
  - Climate TRACE v6 API: India by subsector 2021–2025, plus the top 900 facilities with coordinates, owner and capacity, assigned to states by point-in-polygon.
- **EDGAR back-history 1970–1989:** state and city × sector, built with the same method as the panel from 1,000 extra grids. It is used for display only; training splits are unchanged.
- **Fix: single-cell dumps.** EDGAR parks ~57% of India's enteric/manure CH₄ and ~96% of waste-incineration emissions in one 0.1° cell in Tamil Nadu. As a result, Tamil Nadu showed 269 Mt of agriculture. For diffuse sectors, such a cell is now spread over India's other cells in proportion to their own emissions, preserving the national total. Uttar Pradesh is now the top agriculture state (106 Mt).
- **Fix: fuel-exploitation CH₄ double count.** `PRO_FFF` is EDGAR's aggregate of `PRO_COAL + PRO_OIL + PRO_GAS` (+ fires), verified on the India grids. It had been added on top of its own parts, inflating OTHER by ~88 Mt CO₂e in 2023.
- The monthly incremental cycle now refreshes the external APIs. Analytics picks up new files without an API restart (mtime-keyed cache).

### Product
- **`/analytics`** (viewer): Sectors · States · Cities · Compare · Global · Facilities · Sources.
  - **Sectors:** every sector on its own chart with its top-5 states.
  - **States (36) and cities (64):** small multiples with a drill-down (stacked chart plus 7 per-sector charts).
  - **Compare:** up to 8 states or cities; absolute, indexed or share views; sector mix; key-number table.
  - **Global:** India vs peers since 1850; CO₂ by fuel.
  - **Facilities:** Climate TRACE facility rankings.
  - **Sources:** 4-source triangulation (EDGAR, OWID, World Bank, Climate TRACE) and EDGAR-vs-Climate TRACE by sector.
  - Every chart exports to PNG and CSV.
- **API `/api/v2/analytics/{national,world,states,cities,facilities}`:** viewer-auth, parquet-backed, no model internals.
- **Methodology:** added 3 new sources and 2 new formulas (dump correction, Climate TRACE mapping).
- **Sector models retrained** on the corrected panel. Results are updated in the README.
- **Fix: contradictory population anchors.** The source table gives DNH&DD 1.26 M (2023) but 0.66 M (2024), and Puducherry has a similar drop. When the 2023 and 2024 figures differ by more than 10%, the one closer to the 2001–2011 trend is kept. This removes a false 2024 per-capita spike.
- State models were retrained as a result. Deep-model rankings moved noticeably: TFT went from 2.90 to 4.47 at h=5, and Seq2Seq is now best. This is reported as-is; paper tables were regenerated.

### UI fixes
- **Live Map slide-over and compare in light mode:** the panel is always dark, but its cards switched to light styling, giving white-on-white text. The Live Map now scopes `.dark` to itself.
- **Congested KPI and compare grids:** layouts now use container queries (`@container`, `@xl` / `@5xl`), so they adapt to the panel width rather than the window width. KPIs show 3 per row in the slide-over and in compare halves.
- **KPI labels:** labels such as "10-yr CAGR" no longer get split across the card by `justify-between`.
- **Chart cards:** export and info buttons stay pinned top-right instead of wrapping under long subtitles.
- **Create account:** runs form validation first (valid email, 10+ characters), explains itself on the login card, and shows clear messages for duplicate email, wrong password and rate limiting.
- **Local database:** moved to `~/.carbonscope` via `make localdb`. It previously lived in a temporary folder, so it and every account in it could vanish.

## v3.0 — premium optimization pass (2026-09-26)

### Stage 1 — RBAC split (viewer / admin)
- **API (enforced server-side):**
  - Admin-only endpoints (viewers get 403): `/api/v1/models`, `/api/v1/models/{name}/importance`, `/api/v1/models/{name}/backtest`, `/api/v1/data-quality`, `/api/v2/models`, `/api/v2/models/{name}/importance`. `/api/v1/admin/*` was already admin-only.
  - The forecast endpoints (`/states/{code}/forecast`, `/cities/{id}/forecast`, `/map/series`, `/api/v2/states/{code}/sectors[/…]/forecast`, `/api/v2/sectors/series`, `/api/v2/scenarios/run`) serve the **champion** model through the new `backend/app/registry.py`.
  - Viewers receive `"forecast": "CarbonScope Forecast"` with no model name, version or metrics. The `?model=` override is admin-only (403 for viewers).
  - `/api/v1/insights/*` no longer returns `best_model` to viewers, and scenarios strip model identity for viewers.
- **New viewer-safe endpoints:**
  - `/api/v2/drivers`: relative input-group influence per sector, normalised to 100%, no metric names.
  - `/api/v2/states/{code}/sectors/forecast`: all 7 sector forecasts in one call.
- **Registry:**
  - Migration `0003`: `models.level|status|val_score|pinned|shadow_until|created_at`; `insights.approved|admin_note|edited_by|title_hi|body_hi`; new tables `serving_log` and `drift_reports`.
  - The champion is the lowest validation MASE at h=5. ARIMA is excluded (it covers only 10 states). Current champions: GRU (fossil CO₂) and MT-GRU (state × sector).
  - `src/champion.py` applies the same rule offline, so insights, scenarios and derived layers follow the champion instead of a hard-coded model.
- **Frontend:**
  - Viewer navigation: Live Map, India Map, State Explorer, Cities, Insights, Methodology.
  - Model Lab and Data Quality moved into a role-gated `/admin` console (Training Control · Model Lab · Data Quality).
  - Model selectors were removed from viewer pages; the Live Map keeps an admin-only override.
  - An automated leak scan of 5 viewer pages found no model names or metric terms.
- **Tests:** a new RBAC test (8 endpoints return 403 for viewers; the model override returns 403; viewer forecast responses carry no model identity).

### Stage 2 — State Explorer chart fix
- History is drawn as a full-opacity emerald area with a gradient fill (it used to be a thin light line that disappeared in light mode). The forecast P50 starts **at** the last observed point, and the P10–P90 fan has a gradient.
- Complete year axis: a tick every year, labelled every 5 years. Forecast years are shaded and marked "forecast".
- Targets: Total CO₂e · Fossil CO₂ (with CEA power-sector dots, FY2017+) · Per-capita CO₂e · Carbon intensity. Linear/log toggle.
- Every chart shows its unit, source tag, legend, an ⓘ "How is this calculated?" popover (`components/Info.tsx`), and PNG/CSV export.
- KPI row: total, per capita, intensity, 10-yr CAGR, largest sector, 2029 forecast. Each KPI has a formula popover.

### Stage 3 — Sector deep-dive
1. Stacked-area sector composition, 1990–2029 (forecast shaded).
2. Small multiples: one chart per sector (history + forecast fan, 10-yr CAGR arrow, 2029 P50).
3. Donut of the latest-year share, with % labels.
4. Waterfall of the 2014→2024 change per sector (sector deltas labelled).
5. Driver chips per sector: sector-relevant measured drivers with value and 10-yr change, plus forecast influence by input group.
6. Sector carbon-intensity sparklines (tCO₂e per ₹ crore real GSDP).
- **Compare mode:** side-by-side KPI cards, synchronised total and per-capita charts, a per-person sector radar, and a growth-share matrix (sector share vs sector CAGR, bubble = Mt).
- The State Explorer body is a reusable `StateView`, so the Live Map can use it in a slide-over (stage 8).

### Stage 4 — Cities rebuild
- **Removed:** there is no feature-importance chart anywhere on the Cities page. Importance of proxy inputs would be misleading for buffer estimates.
- **New `src/data/cities_meta.py`:**
  - Census 2011 urban-agglomeration populations (55 of 64 cities matched; the 9 small capitals without data show "—").
  - EDGAR cells per buffer (metro ≈ 16–20, small ≈ 4) and buffer area.
- **New seed artifact `cities_v3` and endpoints `GET /api/v2/cities` (sortable ranking) and `GET /api/v2/cities/{id}`:**
  - CO₂e history and sector split within the buffer, and city share of state CO₂e over time.
  - CO₂e forecast = Σ_sector state reconciled forecast × the city's mean share of that state-sector over 2022–2024.
  - Per-capita is only computed for million-plus urban agglomerations, where the population unit matches the buffer scale. This avoids artefacts like Amaravati, whose buffer covers Vijayawada.
- **UI:**
  - City trend with forecast band and tier badge; compare up to 3 cities.
  - Estimated sector-allocation stacked bars, and a city-vs-state share chart.
  - Method card (radius, cells, area, population source) with a step-by-step "How this estimate was made".
  - Sortable, filterable ranking table (estimate, 10-yr CAGR, t/person, % of state, tier).

### Stage 5 — Premium insights
- **ATAR (`src/insights/atar.py`):** every insight now carries:
  - `viz`: a chart type plus the exact series to plot;
  - `how`: formula, inputs, source and update date;
  - `title_hi` / `body_hi`: a Hindi narrative with the same numbers.
- **Chart per type:** anomaly = deviation bars vs 5-yr average with z; decoupling = GSDP vs CO₂e indexed to 100 with the gap shaded; watchlist = forecast fan vs fair-share corridor; leader/laggard = highlighted national ranking; comparison = grouped bars; trend = sparkline with CAGR; drivers = waterfall.
- **Rules:** watchlist entries need at least a 1% excess.
- **Storage and moderation:** insights are stored with viz/how. `approved` insights only for viewers, admin edits survive reseeds, and there is `?q=` search.
- **UI (`frontend/src/insights/InsightCard.tsx`, new Insights page):** gradient severity chips (Alert / Watch / Notice / Info), hover-lift cards, a mini-chart per type, an always-visible formula footer that expands, filters (search, severity, type, sector, state), grid/feed views, skeletons, an empty state and an EN/HI toggle. The old ranking charts moved to a "Rankings & tables" tab.
- **Coverage:** 100% of cards carry charts and formula footers (65 insights).

### Stage 6 — Legends, units and glossary system
- **`frontend/src/lib/glossary.tsx`:** 45 terms (MtCO₂e, CO₂e, GSDP, CAGR, CDD/HDD, GEF, MinT, MASE, P10/P50/P90, EDGAR, CEA, GHGPI, PPAC, FC, Tier A/B/C, AR6 GWP, BAU, T&D, ASI, VAHAN, DGCA, NDC, EV, RPO, UT(s), NCR, LULUCF, JJAS, UA, PAT, UJALA, OxCGRT, VIIRS, IMD, MoSPI, MoRTH, RBI, NASA POWER, …).
- **Automatic tooltips:** `glossify()` wraps every known abbreviation in a keyboard-accessible hover definition. It's applied automatically to every chart title, subtitle and unit (via `ChartCard`), to insight narratives and to KPI labels.
- **Site footer:** on every page, listing data sources, the estimate disclaimer, the LULUCF exclusion and a link to Methodology.
- **Methodology page:**
  - Data sources with URL, licence and "feeds" column.
  - A 14-formula sheet: CO₂e conversion, state allocation, per-capita, intensity, CAGR, fair-share, anomaly z, decoupling, the forecast (model-agnostic), MinT, MASE, city buffers, source triangulation, and the scenario counterfactual.
  - Monsoon justification, known data gaps (nothing fabricated), and a searchable glossary.
- **GWP note:** we keep AR6 WG1 Table 7.15 fossil/biogenic CH₄ factors (29.8/27.0) rather than a single 27.2. The difference is documented on the page.

### Stage 7 — Data expansion
- **IMD gridded climate (`src/data/imd.py`):**
  - 0.25° daily rainfall and 1° daily Tmax/Tmin, 1990–2024 (105 files, form-POST downloads with checksum caching).
  - Area-weighted to state polygons: JJAS monsoon rainfall, annual rainfall, mean temperature, and **daily-based** CDD/HDD.
  - 1,238 of 1,260 state-years now use IMD. Islands outside IMD's land mask fall back to NASA POWER; `climate_source` records which was used.
  - Caveat: the IMD 1° temperature grid reads warm over the high Himalaya (e.g. Ladakh).
- **PPAC state-wise sales (FY2008–FY2025):** petrol (MS), diesel (HSD) and all petroleum products. These feed the transport drivers and v1 transport features (missing before FY2008 → `_missing` flags).
- **NDC phases** (2015 first NDC, 2022 updated NDC) added as a policy feature and a known-future input.
- **Census 2011 UA populations** for city per-capita values (stage 4).
- **Not scriptable, documented as drop-in CSV slots** (nothing fabricated): VAHAN EV registrations (JS-only dashboard), Indian Railways and DGCA (PDF year-books), VIIRS (EOG login), GHG Platform India (form-gated), NITI Aayog ICED (reCAPTCHA).
- **Monsoon rainfall kept, with its justification in Methodology:** hydro output, cooling demand and paddy activity.
- **Cache:** `cache.fetch` now supports form POSTs, with the same SHA-256 caching.

### Stage 8 — Live Map accuracy and detail
- **Triangulation (`layer:triangulation`):**
  - For every state-year from 2017: agreement = 1 − |EDGAR − CEA| ÷ CEA for power-sector CO₂, a divergence flag above 15%, a CEA-calibrated CO₂e, and a mean CEA ÷ EDGAR factor per state.
  - Finding: EDGAR power exceeds CEA in industrial states (Maharashtra 179 vs 124 Mt in 2023; also Odisha, Karnataka and Jharkhand). This is consistent with captive power being outside CEA's grid-plant database. The calibrated layer is labelled a lower bound.
  - GHG Platform India validation is documented as unavailable.
- **New layers:** CO₂e CEA-calibrated · Decoupling status (categorical) · Coal-dependence index · Watchlist severity · Cooling degree days · EV fleet (disabled until VAHAN data is supplied). Groups are now Totals / Sectors / Analytics / Forecast / Context, and every layer carries its source and formula.
- **Source check toggle:** agreement ring on each state outline (green ≥ 85%, amber, red) plus amber divergence markers.
- **Tooltip v2:** KPI row (value, t/person, year-on-year arrow), 7-sector stacked bar with % labels, 3-yr sparkline and a source-agreement ring.
- **Click opens a slide-over** with the full State Explorer (`StateView`), plus pin & compare and a link to the full page.
- **Pinning 2 states** shows A−B totals and per-capita differences, alongside the synchronised comparison charts.
- **3D extrusion:** height is proportional to Mt for emission layers (rank-based for ratios).
- **Search:** fuzzy matching (in-order subsequence scoring over English name, Hindi name and code) with ↑/↓/Enter/Esc keyboard control and an ARIA combobox.
- **Legend:** always shows the unit, range (or categories), source tag and an ⓘ formula.

### Stage 9 — Continuous learning
- **`backend/app/mlops.py`:**
  - Cycles: full, and incremental (re-downloads with `--refresh` and skips training when no source checksum changed).
  - Every run registers **candidate versions** with their forecasts.
  - Promotion gate: the best-by-validation candidate becomes a **challenger** only if its backtest score (mean test MASE over h1/h3/h5, reconciled for the sector level) is ≥ 2% better than the champion's **and** it passes consistency tests (complete grid; no NaN, negative or crossing quantiles; renewables↑ ⇒ power CO₂ not↑).
  - Shadow mode serves the challenger to 20% of requests (stable hash per user) for 14 days, with every served request counted in `serving_log`. It is then promoted if it still qualifies and the champion isn't pinned; otherwise it's archived.
- **Drift:**
  - Input drift = PSI of year-on-year changes (latest 3 years vs the preceding 5).
  - Error drift = the champion's newest 1-yr-ahead MASE ÷ its validation MASE.
  - PSI > 0.25 on ≥ 3 inputs, or an error ratio > 1.5, stores a `drift_reports` row, raises an admin `drift_alert` job and auto-queues a full retrain.
- **`backend/app/scheduler.py` (APScheduler, IST; new docker-compose `scheduler` service):** quarterly full retrain, monthly incremental refresh, and a daily drift + shadow-promotion review. It only enqueues; the RQ worker executes, so the API keeps serving the champion with zero downtime.
- **Seed is registry-aware:** `--keep-registry` refreshes data tables without touching model versions, statuses or served forecasts. A fresh install registers version `initial` and bootstraps champions.
- **Honesty note:** deep models retrain from scratch on the updated windowed panel. True online/incremental learning for TFT-style models is out of scope (documented in `/admin/schedule` and the README).
- **Tests:** `tests/test_mlops.py` covers PSI detection, backtest scoring, the 2% gate, consistency rejection and shadow start.

### Stage 10 — Admin console
- **`/admin` tabs:** Training Control (schedule with next runs, "run full / incremental cycle now", job logs) · **Model Registry** (champion vs challenger cards with val / backtest / 14-day serving; promote / shadow 20% / pin / archive; full metrics CSV download) · **Drift** (PSI bars with thresholds, error-drift gauge, history, run-now) · Model Lab · Data Quality · **Source Reconciliation** (EDGAR vs CEA per state, agreement, factors, calibrated totals) · **Feature Store** (coverage and year span per stored driver, with source) · **Insight Moderation** (approve/hide, edit text, admin note; edits survive regeneration).
- **API (`backend/app/admin.py`, all admin-only):** `/admin/registry`, `/admin/models/{id}/promote|archive|challenge|pin`, `/admin/cycle`, `/admin/drift`, `/admin/drift/check`, `/admin/schedule`, `/admin/metrics.csv`, `/admin/features`, `/admin/sources`, `PATCH /admin/insights/{id}`. The legacy `/admin/retrain` now enqueues a cycle, and `backend/app/jobs.py` was removed.

### Final QA (Section 10 acceptance)
| Criterion | Result |
|---|---|
| No viewer page mentions model names or internal metrics | ✅ Automated text scan of all 7 viewer pages. Only Methodology contains "MASE", deliberately, as part of the requested formula sheet and glossary. The API returns 403 for every admin/model route to viewers (tested). |
| Every visualisation has title, units, legend, source and ⓘ formula | ✅ Enforced via `ChartCard(unit, source, how, legend)`, with auto-glossary on titles, subtitles and units. |
| History at full opacity, forecast connected | ✅ Emerald area plus a P50 that starts at the last observed point. |
| Reconciliation Σ(state×sector) = state = national | ✅ `/api/v2/consistency` → ok (max gap 6e-14 Mt, 0 negative cells). CI tests `test_two_level_mint_is_coherent` and `test_real_sector_panel_reconciles_to_state_total`. |
| Live Map ≥ 40 fps with particles, low-power fallback | ✅ 38–44 fps measured under **software** WebGL (SwiftShader) in headless tests; a GPU will be higher. Low-power mode caps particles at 800. |
| Insights: 100% of cards carry formula footers with real inputs | ✅ 64/64 have `how` + `viz`. |
| Lighthouse ≥ 90 on viewer pages (desktop, authenticated) | ✅ Performance: State Explorer 100 · Insights 100 (after fixing a 0.5 layout shift) · Cities 100 · India Map 100 · Methodology 100. Accessibility 96–97; Best practices 96–100. |
| Continuous learning end to end | ✅ A real cycle (job #2) retrained on the new IMD/PPAC data, registered 21 candidates, and promoted LSTM (fossil, backtest 3.53 vs 4.43) and MT-TFT (sector, 2.45 vs 2.51) to 20% shadow until 2026-10-10. Serving counts are visible in the admin console. |
| Tests / lint / types | ✅ 32 pytest, ruff clean, mypy clean, frontend `tsc` + build clean. |
| Docker one-command | ⚠ `docker-compose.yml` updated (adds the `scheduler` service), but it was not run: the Docker daemon is not running on this machine. |
