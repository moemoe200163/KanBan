# DevFlow Makefile
#
# Quality-of-life entrypoints for development and CI. The targets that
# match the name of a Docker Compose service (``backend``, ``frontend``)
# delegate to ``docker compose`` so the same command works locally
# without rebuilding a Python or Node environment.
#
# Run ``make help`` for the full list of targets.
SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
DOCKER_COMPOSE := docker compose

# Database connection used by the audit scripts. Override on the
# command line for staging or a different host, e.g.
#   make audit-drift AUDIT_DATABASE_URL=postgresql+psycopg2://...
AUDIT_DATABASE_URL ?= postgresql+psycopg2://devflow:devflow_secret@127.0.0.1:5433/devflow

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------

.PHONY: up
up: ## Start all Docker services in the background
	$(DOCKER_COMPOSE) up -d

.PHONY: down
down: ## Stop all Docker services
	$(DOCKER_COMPOSE) down

.PHONY: logs
logs: ## Tail logs from all services
	$(DOCKER_COMPOSE) logs -f --tail=100

.PHONY: build
build: ## Rebuild backend + frontend images
	$(DOCKER_COMPOSE) up -d --build

# ---------------------------------------------------------------------------
# Audit gates
# ---------------------------------------------------------------------------
# These are the CI quality gates. They exit non-zero on failure so a
# pull request with a violation is blocked from merge. ``audit-drift``
# is the headline one — it catches the silent failure mode where a
# model field is added without a corresponding Alembic migration,
# which only blows up at runtime when a real request hits the
# affected endpoint.

.PHONY: audit-drift
audit-drift: ## Schema/migration drift audit (CI gate)
	cd $(BACKEND_DIR) && AUDIT_DATABASE_URL=$(AUDIT_DATABASE_URL) \
		python3 scripts/audit_schema_drift.py

.PHONY: audit-unused
audit-unused: ## Endpoints defined in the backend but never called from the frontend
	cd $(BACKEND_DIR) && python3 scripts/audit_unused_endpoints.py

.PHONY: audit
audit: audit-drift audit-unused ## Run all audit gates
	@echo "all audit gates OK"

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

.PHONY: backend-migrate
backend-migrate: ## Apply the latest Alembic migrations
	$(DOCKER_COMPOSE) exec backend alembic upgrade head

.PHONY: backend-revision
backend-revision: ## Create a new Alembic migration (use msg= to set the slug)
	$(DOCKER_COMPOSE) exec backend alembic revision --autogenerate -m "$(msg)"

.PHONY: backend-logs
backend-logs: ## Tail backend logs
	$(DOCKER_COMPOSE) logs -f --tail=100 backend

.PHONY: backend-shell
backend-shell: ## Open a shell in the backend container
	$(DOCKER_COMPOSE) exec backend bash

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

.PHONY: frontend-logs
frontend-logs: ## Tail frontend logs
	$(DOCKER_COMPOSE) logs -f --tail=100 frontend

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

.PHONY: db-shell
db-shell: ## Open a psql shell against the devflow database
	$(DOCKER_COMPOSE) exec postgres psql -U devflow -d devflow

.PHONY: db-reset
db-reset: ## Truncate all data tables (DEV ONLY — keep alembic_version)
	$(DOCKER_COMPOSE) exec postgres psql -U devflow -d devflow -c \
		"DO \$\$ DECLARE r record; BEGIN FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version') LOOP EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' CASCADE'; END LOOP; END \$\$;"
