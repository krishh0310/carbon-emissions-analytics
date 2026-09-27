# CarbonScope India

State/UT- and city-level CO₂ forecasting for all **28 states + 8 union territories** of India, with a secure REST API and an India-map dashboard.

> **Data honesty.** State emissions are **EDGAR-downscaled estimates**: EDGAR 2025 gridded CO₂, area-weighted to state polygons. They are not official inventories. City values are **proxy estimates** with a confidence tier, never measured inventories.

## Architecture

```
  public sources (no API keys)                 offline pipeline (python -m ...)                 serving
 ┌──────────────────────────────┐   ┌─────────────────────────────────────────────┐   ┌─────────────────────────┐
 │ EDGAR 2025 0.1° grids (JRC)  │──▶│ src.data.ingest   → data/processed/*.parquet │   │ PostgreSQL 16 + PostGIS │
 │ CEA CO₂ Baseline DB v22      │   │ src.data.features → leakage-safe windows     │   │  states(geometry) ...   │
 │ MoSPI GSDP / Census (wiki)   │   │ src.train.run     → 11 models, MinT, metrics │──▶│ backend.app.seed        │
 │ World Bank, NASA POWER       │   │ src.explain       → SHAP/perm/attention      │   └───────────┬─────────────┘
 │ OxCGRT, datta07 boundaries   │   │ src.insights      → decoupling, watchlist    │               │
 └──────────────────────────────┘   └─────────────────────────────────────────────┘   ┌───────────▼─────────────┐
                                           ▲  RQ job (admin retrain)                   │ FastAPI /api/v1 (JWT)   │
                                     ┌─────┴─────┐       ┌────────┐                    └───────────┬─────────────┘
                                     │ rq worker │◀──────│ Redis  │◀── POST /admin/retrain         │
                                     └───────────┘       └────────┘                    ┌───────────▼─────────────┐
                                                                                       │ Nginx → React dashboard │
                                                                                       └─────────────────────────┘
```

## Quick start

### Docker (one command)

```bash
cp .env.example .env            # then change every secret
docker compose up --build       # http://localhost:8080   (API docs: http://localhost:8080/docs)
```

The first run downloads about 1 GB, ingests it, trains all models (roughly 30–40 min on CPU) and seeds PostGIS. Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`. Set `CARBONSCOPE_SKIP_TRAIN=1` to skip training.

### Local

Requires Python 3.11+, Node 22, PostgreSQL with PostGIS, and Redis.

```bash
make setup
make ingest        # python -m src.data.ingest [--refresh]
make train         # python -m src.train.run   (add --fast for a smoke test)
make explain insights seed
make api           # :8000
make worker        # RQ worker for admin retraining
make web           # :5173, proxies /api -> :8000
make test lint
```

## Data sources and processing

| Feature group | Source | Notes |
|---|---|---|
| **Target `co2_mt`** | EDGAR 2025 GHG CO₂ TOTALS, 0.1°, 1990–2024 | Exact cell × polygon area overlay (EPSG:6933), so small UTs and coastal cells aren't dropped. |
| Sector drivers | EDGAR sector grids: ENE (power), IND, TRO (road), NMM (cement), RCO (buildings) | Same aggregation as the target. |
| Power, validation | CEA CO₂ Baseline Database v22, plant level, FY2017-18 to 2025-26 | Station totals (`UNIT_NO==0`) give coal/gas/oil/hydro/nuclear GWh, CO₂ and grid emission factor. Mirrors: v21, v20. |
| GSDP | MoSPI 2011-12 series via Wikipedia tables | Constant prices use the World Bank deflator. Before FY2011: constant-share backcast with World Bank real GDP. UTs with no series: population × regional median per-capita GSDP. |
| Population | Census 2001/2011 plus 2023/2024 estimates | Log-linear interpolation; urban % held at 2011. |
| Climate | NASA POWER monthly (temperature, precipitation) at the main city of each state | CDD base 18 °C; JJAS rainfall; drought = JJAS < 80% of the train-period mean. |
| Policy | OxCGRT subnational stringency; UJALA, PAT, JNNSM phases, 175 GW target, state EV policy years | EV policy years are approximate; verify before citing. |
| Boundaries | datta07/INDIAN-SHAPEFILES (fallback: udit-001/india-maps-data) | Ladakh separate; DNH and DD dissolved into IN-DH; validated to exactly 36 ISO 3166-2:IN codes. |

- **Caching:** downloads go to `data/raw/` with SHA256 in `data/raw/manifest.json`. `--refresh` re-downloads and reports upstream changes.
- **RBI tables:** RBI's document server shows a CAPTCHA to scripts, so its *Handbook of Statistics on Indian States* tables can't be fetched automatically. Save them in a browser to `data/manual/rbi/<feature>.xlsx` (names in `src/data/drivers.py::RBI_FILES`: sector GSVA, installed capacity, renewables, consumption, T&D losses, highways) and they are merged automatically.
- **Not ingested:** MoRTH vehicle registrations (no machine-readable free source) and VIIRS nightlights (the EOG download now needs a login). EDGAR road-transport CO₂ is used as the transport driver instead.
- **Cleaning:** units in MtCO₂; `log1p` on skewed variables; winsorisation at 1/99% and standardisation fitted on train years only; `*_missing` indicator columns; every imputation is written to `results/tables/imputation_report.csv`.
- **Outputs:** `data/processed/india_states_panel.parquet` (1,260 rows = 36 × 35), `india_cities_panel.parquet` (64 cities × 35 years), and `india_states.geojson`.

## Modelling

- **Splits** are by *target* year: train ≤ 2014, validation 2015–2019, test 2020–2024. There is no shuffling across time; shuffling only reorders training samples. Leakage is enforced in `src/data/features.py` and tested in `tests/test_data.py`.
- **Windows:** 10 input years. Horizons 1–5 are predicted jointly; 1, 3 and 5 are reported. The target is log-growth relative to the last observed year, which makes it scale-free across Uttar Pradesh and Lakshadweep.
- **Global panel:** one network for all 36 units, with a learned 8-d **state embedding** plus static covariates (region, coastal, UT, income tercile from train-period per-capita GSDP).
- **Models:**
  - Naive and drift.
  - Ridge and LightGBM (quantile) global panels.
  - ARIMA(1,1,0) with trend, top 10 emitters only (refit per origin).
  - LSTM, GRU, TCN, Seq2Seq-GRU with Bahdanau attention.
  - TFT-lite: static enrichment, variable selection, GRU encoder/decoder with known-future policy covariates, multi-head attention, P10/P50/P90.
  - DeepAR-style Gaussian head (direct multi-horizon, no ancestral sampling).
- **Training:** PyTorch Lightning; pinball loss weighted by each state's inverse MASE scale; early stopping on validation MASE; gradient clipping; AdamW; seeded and deterministic.
  - Hyper-parameters are in `configs/models.yaml`. `make tune` (Optuna TPE, 30 trials) writes `configs/tuned/*.yaml`, which override them.
  - MLflow logs to `mlruns/`.
- **Reconciliation:** MinT (national = Σ states). It uses Schäfer–Strimmer shrinkage when there are more residual rows than series, otherwise the WLS-variance form. The error covariance is estimated from train-split residuals and reused for production forecasts. Both raw and reconciled MASE are reported.
- **Production forecasts** (2025–2029) come from each model refit on all years with the same hyper-parameters.
- **Outputs:**
  - `results/tables/metrics.csv`: model, level, state_code, target, horizon, split, mae, rmse, mape, smape, mase, r2, reconciled_mase, training_time.
  - `results/forecasts.parquet`, `results/backtest.parquet`, `results/model_registry.json`.
  - Checkpoints in `models/checkpoints/`.

### Current results (test 2020–2024, all states, MASE)

| Model | h=1 | h=3 | h=5 |
|---|---|---|---|
| Seq2Seq-Attention | 1.96 | **3.32** | **3.08** |
| DeepAR-style | 2.92 | 4.27 | 3.19 |
| ARIMA (top 10 only) | 1.75 | 3.58 | 3.91 |
| Naive | 2.18 | 3.84 | 4.02 |
| TFT-lite | 4.29 | 4.44 | 4.47 |
| LSTM | 1.86 | 4.05 | 4.68 |
| LightGBM | **1.72** | 3.83 | 6.25 |
| Ridge | 2.31 | 5.12 | 11.00 |

MASE is scaled by each state's naive-1 error over the train period. The test window contains the COVID-19 shock, so every model scores above 1.

- **Best by horizon:** Seq2Seq-Attention is best at 3 and 5 years; LightGBM is best at 1 year.
- **Deep models are unstable on this 36-state panel.** Re-running with only two small UTs' population corrected (v3.1) moved TFT's h=5 score from 2.90 to 4.47. Treat single-run rankings between the deep models as noisy.
- **Why sector forecasts are served:** the state × sector models (below) are far steadier, which is why State Explorer forecasts are built from the reconciled sector forecasts.

### Explainability

`python -m src.explain.importance` writes:
- Permutation importance of feature **groups** (energy, economy, demography, transport, climate, policy, history).
- SHAP for LightGBM.
- Attention heatmaps for Seq2Seq and TFT.
- TFT variable-selection weights.
- Partial dependence of predicted growth on renewable share.

## API (`/docs`)

All routes are under `/api/v1`:

- **Auth:** `POST /auth/register` (viewer role only), `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`.
- **States:** `GET /states?year=&limit=&offset=&geometry=`, `/states/{code}/history?target=co2|co2_per_capita|carbon_intensity`, `/states/{code}/forecast?horizon=5&model=tft` (P10/P50/P90 + MinT P50).
- **Cities:** `GET /cities?state=MH`, `/cities/{id}/forecast`.
- **Insights:** `GET /insights/{decoupling|carbon-intensity|watchlist|cities}`.
- **Models and data:** `GET /models` (leaderboard), `/models/{name}/importance`, `/models/{name}/backtest?state=`, `/data-quality`.
- **Admin only:** `POST /admin/retrain` (RQ background job), `GET /admin/jobs`, `/admin/jobs/{id}`, `/admin/registry`.

Security:
- Argon2id password hashing.
- JWT access tokens (15 min) and refresh tokens (7 days) with rotation. Reusing a refresh token revokes all of that user's tokens.
- viewer/admin roles; admins can't self-register.
- slowapi rate limits (auth 10/min, API 120/min, retrain 5/hour).
- Pydantic validation, max page size 200, ORM-parameterised queries only.
- Restricted CORS; security headers (CSP, HSTS, XFO) on both the API and Nginx.
- Secrets live in `.env`.

## Retraining

Either:
- **Dashboard:** Admin → select models → Start (runs train → explain → insights → reseed as one job, with logs polled live), or
- **CLI:** `make train explain insights seed`.

To tune first: `make tune`, then `make train`.

## Known limitations and how the design mitigates them

1. **EDGAR downscaling.** EDGAR places emissions using proxies (point sources, population, road networks), so state totals carry roughly ±20–50% uncertainty. Power-plant placement can differ from CEA's. The Data Quality page shows the EDGAR-vs-CEA gap per state.
2. **City estimates.** They are EDGAR cells within a 25 km (metro) or 12 km buffer. Buffers can cross state lines (Delhi NCR's share of IN-DL is above 1) and can include nearby industry (Surat–Hazira, Visakhapatnam). Tier B is metros; tier C is small cities covered by only 1–4 cells. City forecasts are the state forecast × the city's recent share of state emissions.
3. **Short panel for deep learning.** There are about 35 years per state and about 540 training windows. Mitigations:
   - one global model with state embeddings instead of 36 local models;
   - a scale-free log-growth target;
   - MASE-weighted loss, heavy regularisation and early stopping;
   - strong baselines kept in every comparison;
   - MinT reconciliation to borrow strength from the national total.
4. **Imputation and other data gaps.**
   - GSDP before FY2011, and for Ladakh, Lakshadweep and DNH&DD, is imputed (flagged `gsdp_imputed`).
   - CEA data exists only from FY2017.
   - Policy dummies that are constant over the train period are dropped as features; TFT still sees them as known-future inputs.
   - Climate comes from one point per state.
5. **The test period includes COVID-19**, so absolute accuracy is pessimistic for normal years.

## Repository layout

```
src/data        reference.py (36 units, 64 cities) · cache.py · edgar.py · drivers.py · ingest.py · features.py
src/models      baselines.py · deep.py
src/train       run.py · evaluate.py (metrics + MinT) · tune.py (Optuna)
src/explain     importance.py        src/insights.py
backend/app     main.py (API) · db.py (ORM/PostGIS) · security.py · seed.py · jobs.py (RQ) · config.py
frontend/       React 18 + Vite + TS + Tailwind; MapLibre choropleth, Recharts, React Query, EN/HI
configs/ alembic/ docker/ tests/ paper/ results/ data/ models/
```


## v2: State × Sector intelligence

v2 extends v1 without rewriting it. It forecasts **36 states × 7 sectors = 252 series** of CO₂e, using IPCC AR6 100-year GWPs.

### Sector taxonomy and data

The backbone is the EDGAR 2025 CO₂, CH₄ and N₂O sub-sector grids: 1,785 files for 1990–2024, aggregated to states like v1 (`src/data/sectors.py`).

| Sector | EDGAR sub-sectors |
|---|---|
| POWER | ENE |
| TRANSPORT | TRO (road), TNR_Other (rail, inland navigation, off-road), TNR_Aviation_LTO (airports), TNR_Ship (coastal cells) |
| INDUSTRY | IND, NMM (cement), IRO (steel), CHE, NFE, NEU, PRU_SOL, REF_TRF |
| BUILDINGS | RCO |
| AGRICULTURE | ENF (enteric), MNM (manure), AGS (rice, soils, urea), AWB (residue burning) |
| WASTE | SWD_LDF (landfill), SWD_INC, WWT (wastewater) |
| OTHER | residual: CO₂ TOTALS − assigned CO₂, plus fugitive CH₄ (PRO_*) and indirect N₂O |

- **GWPs:** CH₄ 29.8 (fossil) / 27.0 (non-fossil, used for agriculture and waste); N₂O 273.
- **What's excluded:** aviation cruise/climb, because EDGAR allocates it to airspace rather than to states.
- **Consistency:** by construction, the sector CO₂ adds up exactly to the v1 state CO₂. This is tested.
- **2024 totals (MtCO₂e):** power 1,386 · industry 1,031 · agriculture 759 · transport 339 · other 278 · buildings 257 · waste 146. India total 4,197.
- **Labelling:** every row carries a `source`, `method` and `confidence` tier (B for power, industry and transport; C elsewhere).
- **Drivers:**
  - Automated: CEA (power), HDD and CDD, urban population, GSDP and policy.
  - RBI handbook tables for fertiliser, rice, wheat and sown area (manual drop-in, like v1).
  - Sources without a scriptable free download use drop-in CSVs (`data/manual/extra/<feature>.csv`, see `drivers.MANUAL_EXTRA`): MoRTH vehicles, PPAC fuel sales, Railways/DGCA traffic, Livestock Census, CPCB/MoHUA waste, PMUY LPG, VIIRS nightlights. Absent features are NaN with a `_missing` flag; nothing is fabricated.
- **Outputs:** `data/processed/india_states_sector_panel.parquet`, `india_sector_features.parquet` and `india_cities_sector_panel.parquet`.

### Models (`python -m src.train.sector_run`)

- **Embeddings:** a joint (state, sector) embedding, `E_state[s] + E_sector[k]`, is shared by every deep architecture. The same windows code handles both state and state × sector panels, with the same splits and the same leakage tests.
- **Models trained:** naive, drift, sector-aware LightGBM, LightGBM per sector, GRU, TCN, Seq2Seq-Attention, TFT-lite, and the multi-task **MT-GRU** / **MT-TFT**.
  - The multi-task models use a shared per-sector temporal encoder, then a cross-sector Transformer layer (the 7 sectors of a state attend to each other), then per-sector quantile heads.
  - All 7 sectors are predicted in one forward pass.
- **Two-level MinT:** hierarchy national → {36 states, 7 sectors} → 252 cells.
  - Base forecasts: model output for cells; a direct state-total TFT for state totals; drift for sector and national totals.
  - W is the diagonal of train-residual variances (the full covariance is ill-posed with T ≪ 296 series).
  - Cells are clipped at ≥ 0. Sums are exact by construction; `/api/v2/consistency` and CI check this.
- **Metrics:** `metrics.csv` gains `level=state_sector` and `sector`. Aggregate MASE excludes 25 near-zero cells (train mean < 10 kt, e.g. power in UTs without plants); per-cell rows are kept for all 252 cells.
- **Experiments** (`results/tables/experiments.csv`):
  - E10: bottom-up sector sums vs a direct state-total model.
  - E11: multi-task vs per-sector heads.
  - E12: unreconciled vs two-level MinT.
  - E13: counterfactual sanity (unit tests in CI).
  - E14: zero-shot transfer to 6 held-out states, using the mean state embedding.

### v2 results (test 2020–2024, material cells; re-run in v3.1 on the corrected panel)

| Model | MASE h=1 | h=3 | h=5 | two-level MinT h=5 |
|---|---|---|---|---|
| TFT-lite (+state/sector emb.) | 1.44 | **2.49** | **2.28** | **2.50** |
| MT-GRU (multi-task) | 1.41 | 2.73 | 2.53 | 2.63 |
| TCN | 1.49 | 2.84 | 2.64 | 2.70 |
| GRU | 1.53 | 2.71 | 2.66 | 2.76 |
| MT-TFT (multi-task) | 1.37 | 2.72 | 3.07 | 3.20 |
| LightGBM | **1.31** | 2.58 | 3.33 | 3.42 |
| Naive | 1.69 | 3.15 | 3.65 | 3.21 |

Findings, reported as they came out:

- **E10:** bottom-up sector forecasts beat a direct state-total model for most models. For example, GRU scores 1.64 vs 1.99 at h=1 and 2.57 vs 4.24 at h=5.
- **E11:** multi-task heads do not beat single-task TFT on test at h=5 (MT-GRU 2.53, MT-TFT 3.07 vs TFT 2.28). MT-TFT is best at h=1 (1.37).
- **E12:** two-level MinT costs about 0.05–0.2 MASE on these cells, but it guarantees Σ cells = state = national exactly.
- **E14:** GRU transfers zero-shot to held-out states with a modest cost (h=5 MASE 2.49 vs 2.26 when those states are in training). MT-TFT scores 2.86 zero-shot vs 3.70.

Before v3.1, Tamil Nadu agriculture and fuel-exploitation CH₄ were distorted by EDGAR artefacts (see CHANGELOG). The earlier numbers (TFT 2.50 h=5) are superseded.

### Scenario engine (`src/scenarios.py`)

Renewable share, EV adoption and industrial policy are constant or unobserved in the training years (≤ 2014). The networks therefore have no learned response to them, and re-running the decoder with edited covariates would return arbitrary numbers.

Instead, the engine applies explicit identities to the reconciled P10/P50/P90, ramping linearly to 2029:

| Lever | Effect |
|---|---|
| Renewables | power × (1 − Δ/fossil share) |
| EVs | removes road CO₂ and adds grid load at the state's CEA emission factor (EV efficiency 3.2× ICE) |
| Industrial growth | compounding change to industry |
| Building efficiency | linear cut to buildings |

- **Presets:** BAU, Moderate, Ambitious.
- **Uncertainty:** bands are widened by ±20% of the scenario delta.
- **E13 tests:** more renewables never raise power; EVs cut transport and add power; BAU is the identity; P10 ≤ P50 ≤ P90; bounds are validated.

### ATAR insight engine (`src/insights/atar.py`)

ATAR generates insights deterministically from templates and statistics (no LLM). Each insight has `state_code, sector, type, severity, title, body, evidence, generated_at`.

| Type | Rule |
|---|---|
| ANOMALY | z-score of latest growth vs the 5-year distribution |
| DECOUPLING | consecutive years with GSDP up and sector CO₂e down |
| WATCHLIST | forecast vs fair-share path, with driving sectors |
| LEADER / LAGGARD | intensity rankings |
| DRIVERS | sector contributions to the forecast change, plus the model's top input group |
| COMPARISON | per-capita gaps |
| TREND | national intensity changes and the CEA grid emission factor |

Insights regenerate after every training job and are stored in the `insights` table.

### API v2 (`/api/v2`, all v1 security controls apply)

- `GET /states/{code}/sectors`
- `GET /states/{code}/sectors/{sector}/forecast?horizon&model`
- `GET /sectors/series`: bulk data for the map, cached in Redis.
- `GET /insights?state=&sector=&severity=&type=&limit=`
- `POST /scenarios/run`: bounds validated server-side, rate-limited to 20/min, persisted to `scenarios`.
- `GET /scenarios/presets`, `GET /scenarios/{id}`
- `GET /layers/{anomaly|uncertainty}`
- `GET /flow-field?sector=`
- `GET /models`: sector leaderboard plus experiments.
- `GET /models/{name}/importance`: per-sector group importance.
- `GET /consistency`

Scenarios run synchronously (under 50 ms), so they aren't queued. There are no vector tiles: 36 simplified polygons (about 200 KB) are served once, and layers are cached value tables.

### Live Map v2 (windy.com-style)

- **Layer rail:**
  - Totals: total CO₂e, fossil CO₂, per capita, carbon intensity.
  - The 7 sectors, each with its own colour ramp.
  - Analytics: anomaly vs trend, uncertainty (P90−P10)/P50, scenario Δ.
  - Context: temperature, monsoon rain, population. Nightlights is disabled until VIIRS data is supplied.
- **Layer controls:** gradient legend with min/max, opacity slider.
- **Particle flow** (`src/flowfield.py` + `frontend/src/live/FlowLayer.ts`):
  - About 3,000 canvas particles advect through the down-gradient of smoothed log CO₂e density, with a small swirl term.
  - Speed is proportional to intensity; colour shows the dominant sector of each cell.
  - Controls: density slider, low-power mode (≤ 800 particles), fps readout.
  - This is a visual encoding of emission density, **not wind**.
- **Timeline:** 2000 → 2029, with play/pause and 60 fps tweening between years. Forecast years are hatched; hover shows P50 and P10–P90.
- **Glass tooltip:** value, sector mini-bars, 3-year sparkline.
- **Drill-down:** sector donut, fan chart per sector, the model's input-group importance per sector, and ATAR cards.
- **Compare mode:** two states with synchronised charts.
- **Scenario sandbox:** sliders and presets update the map live with a "Scenario Δ 2029" layer.
- **ATAR feed:** filterable by severity and sector; clicking an item flies to the state. Alerts show as pulsing red markers.
- **Zoom:** city estimates appear once zoomed past the national view.

### Running v2

`make ingest` (the sector panel is included unless `--no-sectors`), then:

```
make train train-sectors flow insights seed
```

Docker `init` does all of this.

v2 limitations:
- Sector allocation inherits EDGAR's proxy uncertainty, which is higher for agriculture and waste (tier C).
- OTHER is a residual.
- Scenario levers are structural rather than learned.
- Several sector drivers need manual CSVs.
- Particles are illustrative, not atmospheric transport.

## v3: Premium optimisation (RBAC, analytics, continuous learning)

See `CHANGELOG.md` for the stage-by-stage record. In short:

- **Roles:**
  - Viewers see the Live Map, India Map, State Explorer, Cities, Insights and Methodology. Forecasts appear only as "CarbonScope Forecast"; model names, metrics, training and data-quality internals are admin-only in both the UI and the API (403).
  - Admins get `/admin`: registry, drift, training, sources, feature store and moderation.
- **State Explorer:** full-opacity history with a connected forecast fan and complete axes; a 6-part sector deep-dive (stacked area, small multiples, donut, waterfall, driver chips, intensity sparklines); compare mode (KPIs, synchronised charts, radar, growth-share matrix).
- **Cities:** proxy-estimate analytics only (trend + band, estimated sector allocation, share of state, method card, sortable ranking, 3-city comparison). No feature importance.
- **Insights:** every card has a type-specific chart, an EN/HI narrative, and a "How is this calculated?" footer with formula, inputs, source and date.
- **Glossary:** 45 terms with automatic hover definitions on every chart, KPI and insight; a site footer; and a Methodology page with sources, licences, a 14-formula sheet and data gaps.
- **Data:** IMD gridded rainfall/temperature (area-weighted, daily CDD/HDD), PPAC fuel sales, NDC phases, and Census UA populations. Non-scriptable sources are documented drop-in slots.
- **Live Map:** EDGAR-vs-CEA triangulation rings and divergence markers, a CEA-calibrated layer, 6 new layers, tooltip v2, a slide-over State Explorer, A−B pinning, fuzzy keyboard search, and 3D height ∝ Mt.
- **Continuous learning (`make scheduler`, `make cycle`, `make drift`):**
  - Quarterly full retrain, monthly incremental refresh, and a daily drift / shadow review.
  - Champion → challenger (≥ 2% better backtest + consistency) → 14-day shadow at 20% traffic → promotion.
  - Deep models retrain from scratch; online learning is out of scope.

## v3.1: Live open-data APIs, history since 1970/1850, Analytics page

- **Data:** `make external` pulls three no-key sources, cached with SHA-256 like everything else:
  - Our World in Data (India + peers, 1850+)
  - the World Bank GHG API
  - Climate TRACE v6 (subsector totals + 900 geolocated facilities)

  It also extends EDGAR state/city × sector estimates back to **1970**. The 1970–1989 years are display-only; training stays 1990+.
- **`/analytics`** shows every sector, state and city individually. It adds up-to-8-way comparison, India vs the world, facility rankings, and a 4-source triangulation of the national total.
- **Data fixes:**
  - EDGAR single-cell dumps in diffuse sectors are redistributed (Tamil Nadu's agriculture artefact).
  - The `PRO_FFF` fuel-exploitation CH₄ double count is removed.

  See `CHANGELOG.md` v3.1.

**v3.2:** signed-out visitors land on a public home page with an interactive emission-stripes hero, a feature tour, how-it-works, the team and sign-up. Signed-in users can find it at `/about`. It reads `GET /api/v2/analytics/public`, which needs no login.

## Paper

`paper/main.tex` is an IEEE skeleton. `make paper` regenerates `paper/tables/*.tex` from `results/tables/metrics.csv` and builds the PDF.
