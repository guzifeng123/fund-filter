# Fund-filter developer commands for Linux/macOS.
#
# Windows users should keep using the existing PowerShell scripts under
# scripts/ (e.g. scripts/check-all.ps1, scripts/db-migrate.ps1). This Makefile
# is a thin, cross-platform mirror of those entry points and always routes
# through the repository-root virtualenv at ./.venv.

PYTHON ?= $(CURDIR)/.venv/bin/python
API_DIR := $(CURDIR)/apps/api

.PHONY: help install migrate seed test lint mypy connectivity sync-eastmoney smoke dev-api

help:
	@echo "Fund-filter developer targets (Linux/macOS):"
	@echo "  install         install npm workspaces and API dev dependencies into .venv"
	@echo "  migrate          apply Alembic migrations to the head revision"
	@echo "  seed             (re)seed sample fund data (idempotent)"
	@echo "  test             run the backend pytest suite"
	@echo "  lint             run ruff check (pinned 0.14.9)"
	@echo "  mypy             run mypy --strict on the backend package"
	@echo "  connectivity     smoke-test the AKShare upstream contract"
	@echo "  sync-eastmoney   pull an audited EastMoney snapshot into the local SQLite DB"
	@echo "  smoke            hit /health and /api/data/status on a locally running API"
	@echo "  dev-api          start the FastAPI dev server on :8000"

install:
	npm install
	$(PYTHON) -m pip install -e ./apps/api[dev]

migrate:
	cd $(API_DIR) && $(PYTHON) -m alembic -c alembic.ini upgrade head

seed:
	cd $(API_DIR) && $(PYTHON) -m app.jobs.seed_sample_data

test:
	cd $(API_DIR) && $(PYTHON) -m pytest app/tests -q

lint:
	cd $(API_DIR) && $(PYTHON) -m ruff check app

mypy:
	cd $(API_DIR) && $(PYTHON) -m mypy app --strict

connectivity:
	$(PYTHON) scripts/verify_akshare.py --fund 000001 --stock 600036

sync-eastmoney:
	$(PYTHON) scripts/sync_sqlite_data.py --fund-code 000001

smoke:
	curl -fsS http://localhost:8000/health
	curl -fsS http://localhost:8000/api/data/status

dev-api:
	cd $(API_DIR) && $(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
