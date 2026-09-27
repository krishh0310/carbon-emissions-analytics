PY ?= .venv/bin/python
export MLFLOW_DISABLE_AGENT_HINT=1


.PHONY: scheduler cycle drift
.PHONY: localdb external setup ingest refresh train train-fast train-sectors flow tune explain insights seed api worker web test lint up down paper all

setup:            ## create venv + install everything
	python3.11 -m venv .venv || python3 -m venv .venv
	$(PY) -m pip install -U pip && $(PY) -m pip install -r requirements-dev.txt
	cd frontend && npm ci

ingest:           ## download (cached) + build data/processed/*.parquet
	$(PY) -m src.data.ingest
refresh:          ## re-download all sources (sha256 detects unchanged files)
	$(PY) -m src.data.ingest --refresh
train:            ## all 11 models: backtest metrics + production forecasts
	$(PY) -m src.train.run
train-fast:
	$(PY) -m src.train.run --fast
tune:             ## Optuna, 30 trials per deep model -> configs/tuned/*.yaml
	$(PY) -m src.train.tune --trials 30
train-sectors:    ## v2: 36x7 state x sector models, two-level MinT, experiments E10-E14
	$(PY) -m src.train.sector_run
external:         ## live open APIs (OWID, World Bank, Climate TRACE) + EDGAR 1970–1989 back-history
	$(PY) -m src.data.external --history
flow:             ## v2: particle flow field from EDGAR sector grids
	$(PY) -m src.flowfield
explain:
	$(PY) -m src.explain.importance
insights:         ## v1 analytics + ATAR insight feed
	$(PY) -m src.insights
seed:             ## load processed data + results into PostGIS
	$(PY) -m alembic upgrade head && $(PY) -m backend.app.seed
all: ingest external train train-sectors flow explain insights seed

localdb:          ## local Postgres+PostGIS (:5433) and Redis (:6380) with data kept in ~/.carbonscope (survives reboots)
	@mkdir -p $(HOME)/.carbonscope
	@test -d $(HOME)/.carbonscope/pg || (initdb -D $(HOME)/.carbonscope/pg -U carbonscope --auth=trust >/dev/null)
	@pg_ctl -D $(HOME)/.carbonscope/pg status >/dev/null || pg_ctl -D $(HOME)/.carbonscope/pg -o "-p 5433 -k /tmp" -l $(HOME)/.carbonscope/pg.log start
	@sleep 2; createdb -h 127.0.0.1 -p 5433 -U carbonscope carbonscope 2>/dev/null && psql -h 127.0.0.1 -p 5433 -U carbonscope carbonscope -qc "create extension postgis" && echo "new DB: run make seed" || true
	@redis-cli -p 6380 ping >/dev/null 2>&1 || redis-server --port 6380 --daemonize yes --dir $(HOME)/.carbonscope
api:
	$(PY) -m uvicorn backend.app.main:app --reload --port 8000
scheduler:        ## continuous-learning scheduler (enqueues jobs for the worker)
	$(PY) -m backend.app.scheduler
cycle:            ## run one full continuous-learning cycle now (needs worker + Redis)
	$(PY) -c "from backend.app.mlops import enqueue_cycle; print('job', enqueue_cycle('full', 'make'))"
drift:
	$(PY) -c "from backend.app.mlops import drift_check; print(drift_check(auto_retrain=False))"
worker:
	OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES .venv/bin/rq worker carbonscope --url $${REDIS_URL:-redis://localhost:6379/0}
web:
	cd frontend && npm run dev

test:
	$(PY) -m pytest -q
lint:
	$(PY) -m ruff check src backend tests && $(PY) -m mypy
paper:            ## regenerate LaTeX tables from results/tables/metrics.csv and build PDF
	$(PY) paper/make_tables.py && cd paper && (latexmk -pdf main.tex || pdflatex main.tex)

up:
	docker compose up --build
down:
	docker compose down
