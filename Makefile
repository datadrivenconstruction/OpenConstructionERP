.PHONY: help dev dev-backend dev-frontend dev-unix stop test lint format migrate seed seed-regional seed-cwicr-v3 build qa-screenshots

# ─── Variables ──────────────────────────────────────────────────────────────
BACKEND_DIR = backend
FRONTEND_DIR = frontend
DOCKER_COMPOSE = docker compose

# ─── Help ───────────────────────────────────────────────────────────────────
help: ## Show this help
	@echo ""
	@echo "  OpenConstructionERP — Construction Cost Estimation Platform"
	@echo "  ─────────────────────────────────────────────────────────────"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Quick start: make quickstart → http://localhost:8080"
	@echo "  Local dev:   make setup && make dev → http://localhost:5173"
	@echo ""

# ─── Development ────────────────────────────────────────────────────────────
infra: ## Start infrastructure (PostgreSQL, Redis, MinIO)
	$(DOCKER_COMPOSE) up -d postgres redis minio

infra-ai: ## Start infrastructure + AI services (Qdrant)
	$(DOCKER_COMPOSE) --profile ai up -d

stop: ## Stop all services
	$(DOCKER_COMPOSE) --profile ai down

dev-backend: infra ## Start backend dev server
	cd $(BACKEND_DIR) && uvicorn app.main:create_app --factory --reload --port 8000

dev-frontend: ## Start frontend dev server
	cd $(FRONTEND_DIR) && npm run dev

dev: ## Show how to start dev (cross-platform: two terminals)
	@echo "OpenConstructionERP local dev needs two terminals (cross-platform safe):"
	@echo "  Terminal 1:  make dev-backend   (http://localhost:8000)"
	@echo "  Terminal 2:  make dev-frontend  (http://localhost:5173)"
	@echo ""
	@echo "Linux/macOS users may also try the POSIX-only shortcut: make dev-unix"

# POSIX-only: backgrounds the backend with `&` (bash job control).
# Does NOT work in Windows cmd.exe or MSYS2 make — use `make dev-backend`
# and `make dev-frontend` in two terminals instead.
dev-unix: infra ## Start backend (background) + frontend — POSIX shells only
	@echo "Starting OpenConstructionERP (POSIX dev)..."
	@echo "  Backend:  http://localhost:8000"
	@echo "  Frontend: http://localhost:5173"
	@echo ""
	@cd $(BACKEND_DIR) && uvicorn app.main:create_app --factory --reload --port 8000 &
	@cd $(FRONTEND_DIR) && npm run dev

# ─── Testing ────────────────────────────────────────────────────────────────
test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests
	cd $(BACKEND_DIR) && pytest -x -v

test-backend-cov: ## Run backend tests with coverage
	cd $(BACKEND_DIR) && pytest --cov=app --cov-report=term --cov-report=html

test-frontend: ## Run frontend tests
	cd $(FRONTEND_DIR) && npm run test

test-unit: ## Run only unit tests (no DB required)
	cd $(BACKEND_DIR) && pytest -x -v -m unit

test-integration: ## Run integration tests (requires DB)
	cd $(BACKEND_DIR) && pytest -x -v -m integration

qa-screenshots: ## Capture full-app route grid → qa-report/screenshots/<date>/ (needs backend on :8000 + frontend on :5180)
	# NODE_PATH lets a Playwright config sitting outside frontend/ still
	# resolve @playwright/test from frontend/node_modules — required when
	# running from a worktree that doesn't have its own node_modules.
	cd $(FRONTEND_DIR) && NODE_PATH="$(CURDIR)/$(FRONTEND_DIR)/node_modules" npx playwright test --config ../qa/screenshots/playwright.config.ts --reporter=line

# ─── Code Quality ───────────────────────────────────────────────────────────
lint: ## Lint all code
	cd $(BACKEND_DIR) && ruff check app/ tests/
	cd $(FRONTEND_DIR) && npm run lint

format: ## Format the backend code (the frontend has no automatic formatter)
	cd $(BACKEND_DIR) && ruff format app/ tests/

# The frontend half runs the build rather than `npm run typecheck`. Both start
# from the same compiler, but `npm run typecheck` is `tsc --noEmit` and stops
# there, while `npm run build` is `tsc -b` followed by `vite build`, so it also
# resolves the module graph the way the bundle does and `tsc -b` answers from
# .tsbuildinfo where a cold --noEmit does not. `npm run build` is the gate this
# project treats as authoritative, and a green `tsc --noEmit` read as a green
# build is how three broken HEADs shipped recently. It costs a bundle write
# into frontend/dist, which is the price of checking the thing that ships.
typecheck: ## Run type checking
	cd $(BACKEND_DIR) && mypy app/
	cd $(FRONTEND_DIR) && npm run build

# ─── Database ───────────────────────────────────────────────────────────────
migrate: ## Run all pending migrations
	cd $(BACKEND_DIR) && alembic upgrade head

migrate-new: ## Create new migration (usage: make migrate-new MSG="add users table")
	cd $(BACKEND_DIR) && alembic revision --autogenerate -m "$(MSG)"

migrate-down: ## Rollback last migration
	cd $(BACKEND_DIR) && alembic downgrade -1

seed: ## Load seed data (cost catalog + regional indices). Demo projects are auto-created on first backend startup.
	cd $(BACKEND_DIR) && python -m app.scripts.seed_catalog
	cd $(BACKEND_DIR) && python -m app.scripts.seed_regional_indices

seed-regional: ## Load regional cost-index seed (v3.12.0, idempotent)
	cd $(BACKEND_DIR) && python -m app.scripts.seed_regional_indices

# Override with REGIONS="--regions USA_USD,GB_LONDON" or REGIONS="--top-n 5".
# Default ``--top-n 3`` installs the 3 most-popular catalogues so a fresh
# deployment boots with US/UK/DE rate books pre-loaded — operators no
# longer need to visit /costs and click Install for every region.
REGIONS ?= --top-n 3
seed-cwicr-v3: ## Install CWICR v3 catalogues (REGIONS="--top-n 3" by default; needs CWICR_QDRANT_URL)
	cd $(BACKEND_DIR) && python -m scripts.seed_cwicr_v3 $(REGIONS)

db-reset: ## Drop and recreate database (DESTRUCTIVE)
	$(DOCKER_COMPOSE) exec postgres psql -U oe -c "DROP DATABASE IF EXISTS openestimate;"
	$(DOCKER_COMPOSE) exec postgres psql -U oe -c "CREATE DATABASE openestimate;"
	$(MAKE) migrate
	$(MAKE) seed

# ─── Module Development ────────────────────────────────────────────────────
module-new: ## Create new module (usage: make module-new NAME=oe_tendering)
	cd $(BACKEND_DIR) && python -m app.scripts.scaffold_module $(NAME)

module-test: ## Test specific module (usage: make module-test NAME=oe_boq)
	cd $(BACKEND_DIR) && pytest -x -v tests/ -k "$(NAME)"

# ─── Setup (first time) ──────────────────────────────────────────────────
setup: ## First-time setup: install backend + frontend dependencies
	@echo "Installing backend dependencies..."
	cd $(BACKEND_DIR) && pip install -e .[server]
	@echo ""
	@echo "Installing frontend dependencies..."
	cd $(FRONTEND_DIR) && npm install
	@echo ""
	@echo "Setup complete! Run 'make dev' to start the application."
	@echo "  Backend:  http://localhost:8000 (FastAPI + SQLite)"
	@echo "  Frontend: http://localhost:5173 (Vite dev server)"

# ─── Quickstart (single command) ──────────────────────────────────────────
# The two secrets the quickstart stack will not start without, checked here
# rather than left to compose. Compose does say which variable is missing, and
# says it well, but it says it by exiting nonzero - and `quickstart` below turns
# every nonzero exit into "the local build did not finish" and points at
# `quickstart-image`. On a fresh clone with no .env that is the wrong sentence
# twice over: nothing was built, and the remedy loads this same compose file, so
# it stops on the identical `${POSTGRES_PASSWORD:?}` a moment later. The
# stranger this path exists for got a wrong diagnosis followed by a second
# failure that looked unrelated to the first.
#
# Both entry points depend on this, because both read docker-compose.quickstart.yml.
#
# The .env is looked up at $(CURDIR), not as a relative path. Compose resolves it
# beside the compose file, and a recipe resolves a bare `.env` against whatever
# directory make was called from, so `make -C /path/to/repo quickstart` would
# have had this guard report two missing secrets that are sitting right there.
quickstart-secrets:
	@if [ -n "$$POSTGRES_PASSWORD" ] && [ -n "$$JWT_SECRET" ]; then exit 0; fi; \
	if [ -f "$(CURDIR)/.env" ] \
	   && grep -q '^POSTGRES_PASSWORD=..*' "$(CURDIR)/.env" \
	   && grep -q '^JWT_SECRET=..*' "$(CURDIR)/.env"; then exit 0; fi; \
	echo ""; \
	echo "Nothing has started yet. The quickstart stack needs two secrets and"; \
	echo "ships no defaults for them, so that no two installations share a"; \
	echo "database password or a key that signs their sessions."; \
	echo ""; \
	echo "Write them once, into a .env beside this Makefile:"; \
	echo ""; \
	echo "  echo \"POSTGRES_PASSWORD=\$$(openssl rand -base64 24)\" >  .env"; \
	echo "  echo \"JWT_SECRET=\$$(openssl rand -hex 32)\"           >> .env"; \
	echo ""; \
	echo "Then run this command again. On Windows PowerShell, where there is no"; \
	echo "openssl and no make, README.md has the two-line equivalent."; \
	echo ""; \
	exit 1

# Building is optional. A failed build used to end at a raw compose error,
# which left people stuck on a step they never had to run, so the failure
# path now names the published image instead.
quickstart: quickstart-secrets ## Start OpenEstimate (PostgreSQL + App) — needs a .env with two secrets
	@$(DOCKER_COMPOSE) -f docker-compose.quickstart.yml up --build || $(MAKE) --no-print-directory quickstart-build-failed

quickstart-build-failed:
	@echo ""
	@echo "The local build did not finish. You do not have to build it:"
	@echo ""
	@echo "  make quickstart-image   the same stack, from the image we publish"
	@echo ""
	@echo "If you would rather we fixed the build, please open an issue with the"
	@echo "output above and we will take a look."
	@exit 1

# Same stack, but the app comes from the image we publish on every release
# instead of building the frontend here. `pull` is spelled out rather than left
# to `up`, so which artefact runs is stated by the command and not inferred from
# compose's build-versus-pull rules. See docker-compose.quickstart.image.yml.
QUICKSTART_IMAGE_FILES = -f docker-compose.quickstart.yml -f docker-compose.quickstart.image.yml

quickstart-image: quickstart-secrets ## Start quickstart from the published image (no local build)
	$(DOCKER_COMPOSE) $(QUICKSTART_IMAGE_FILES) pull app
	$(DOCKER_COMPOSE) $(QUICKSTART_IMAGE_FILES) up -d
	@echo "  OpenConstructionERP: http://localhost:8080"

quickstart-image-down: ## Stop the published-image quickstart
	$(DOCKER_COMPOSE) $(QUICKSTART_IMAGE_FILES) down

quickstart-down: ## Stop quickstart
	$(DOCKER_COMPOSE) -f docker-compose.quickstart.yml down

quickstart-reset: ## Reset quickstart (delete data)
	$(DOCKER_COMPOSE) -f docker-compose.quickstart.yml down -v

# ─── Build & Deploy ────────────────────────────────────────────────────────
build: ## Build all Docker images
	docker build -t openestimate:latest -f deploy/docker/Dockerfile.unified .
	docker build -t openestimate-backend:latest --target api -f deploy/docker/Dockerfile.unified .
	docker build -t openestimate-frontend:latest -f deploy/docker/Dockerfile.frontend .

build-unified: ## Build single all-in-one Docker image
	docker build -t openestimate:latest -f deploy/docker/Dockerfile.unified .

build-wheel: ## Build Python wheel (pip installable)
	cd $(FRONTEND_DIR) && npm ci && npm run build
	cd $(BACKEND_DIR) && pip install build && python -m build

# ─── Utilities ──────────────────────────────────────────────────────────────
clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	rm -rf $(BACKEND_DIR)/htmlcov
	rm -rf $(FRONTEND_DIR)/dist
