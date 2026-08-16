.DEFAULT_GOAL := help
SHELL := /bin/bash

PY      := .venv/bin/python
PIP     := uv pip install --python .venv/bin/python
PORT    ?= 8000
WEBPORT ?= 5173

.PHONY: help setup setup-py setup-web fixtures dev dev-api dev-web build build-web \
        demo demo-headless benchmark test test-unit test-integration test-benchmark \
        fmt lint typecheck check clean nuke

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Quick start:  make setup && make demo"

# -- setup -------------------------------------------------------------------

setup: setup-py setup-web ## Install everything (Python venv + web deps)
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "Ready. The app runs fully in fixture mode with no credentials."
	@echo "Next:  make demo"

setup-py: ## Create the venv and install the Python package
	@command -v uv >/dev/null 2>&1 || { \
	  echo "uv not found. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	uv venv --python 3.12 .venv
	$(PIP) -e ".[dev]"

setup-web: ## Install web dependencies
	cd web && npm install

fixtures: ## Regenerate the seeded VEGF-A fixture (verifies the demo narrative)
	$(PY) scripts/build_fixtures.py

# -- run ---------------------------------------------------------------------

dev: ## Run API and Vite dev server together (hot reload, two ports)
	@echo "API  http://127.0.0.1:$(PORT)"
	@echo "UI   http://127.0.0.1:$(WEBPORT)"
	@trap 'kill 0' EXIT INT TERM; \
	$(PY) -m uvicorn bioforge.api.main:app --reload --port $(PORT) & \
	(cd web && npm run dev -- --port $(WEBPORT)) & \
	wait

dev-api: ## Run only the API with reload
	$(PY) -m uvicorn bioforge.api.main:app --reload --port $(PORT)

dev-web: ## Run only the Vite dev server
	cd web && npm run dev -- --port $(WEBPORT)

build: build-web ## Production build

build-web: ## Type-check and build the UI into web/dist
	cd web && npm run build

demo: build-web ## Build the UI and serve the whole app on one port
	@echo ""
	@echo "  BioForge Judge — http://127.0.0.1:$(PORT)"
	@echo "  Press 'Seed VEGF-A demo' in the header to start."
	@echo ""
	$(PY) -m uvicorn bioforge.api.main:app --port $(PORT)

demo-headless: ## Run the seeded investigation with no server; write artifacts
	$(PY) scripts/run_headless.py --out artifacts/demo

benchmark: ## Run the retrospective benchmark and the ablations
	$(PY) scripts/run_benchmark.py --seeds 1 2 3 --out artifacts/benchmark.json

# -- quality -----------------------------------------------------------------

test: ## Run every test
	$(PY) -m pytest -q

test-unit: ## Unit tests only
	$(PY) -m pytest tests/unit -q

test-integration: ## Integration tests only
	$(PY) -m pytest tests/integration -q

test-benchmark: ## Benchmark tests only
	$(PY) -m pytest tests/benchmark -q

fmt: ## Format Python
	$(PY) -m ruff format bioforge scripts tests
	$(PY) -m ruff check --fix bioforge scripts tests

lint: ## Lint Python
	$(PY) -m ruff check bioforge scripts tests
	$(PY) -m ruff format --check bioforge scripts tests

typecheck: ## Type-check Python and TypeScript
	$(PY) -m mypy bioforge
	cd web && npm run typecheck

check: lint typecheck test build-web ## Everything CI would run

# -- housekeeping ------------------------------------------------------------

clean: ## Remove generated artifacts and caches
	rm -rf artifacts/demo artifacts/benchmark.json web/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache

nuke: clean ## Also drop the local database and installed dependencies
	rm -f bioforge.db
	rm -rf .venv web/node_modules
