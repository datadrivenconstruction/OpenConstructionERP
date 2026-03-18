.PHONY: help dev stop test lint format migrate seed build

# ─── Variables ──────────────────────────────────────────────────────────────
BACKEND_DIR = backend
FRONTEND_DIR = frontend
DOCKER_COMPOSE = docker compose

# ─── Help ───────────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

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

dev: ## Start everything (run in separate terminals or use tmux)
	@echo "Run in separate terminals:"
	@echo "  make dev-backend"
	@echo "  make dev-frontend"

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

# ─── Code Quality ───────────────────────────────────────────────────────────
lint: ## Lint all code
	cd $(BACKEND_DIR) && ruff check app/ tests/
	cd $(FRONTEND_DIR) && npm run lint

format: ## Format all code
	cd $(BACKEND_DIR) && ruff format app/ tests/
	cd $(FRONTEND_DIR) && npm run format

typecheck: ## Run type checking
	cd $(BACKEND_DIR) && mypy app/
	cd $(FRONTEND_DIR) && npm run typecheck

# ─── Database ───────────────────────────────────────────────────────────────
migrate: ## Run all pending migrations
	cd $(BACKEND_DIR) && alembic upgrade head

migrate-new: ## Create new migration (usage: make migrate-new MSG="add users table")
	cd $(BACKEND_DIR) && alembic revision --autogenerate -m "$(MSG)"

migrate-down: ## Rollback last migration
	cd $(BACKEND_DIR) && alembic downgrade -1

seed: ## Load seed data (CWICR, classifications, demo)
	cd $(BACKEND_DIR) && python -m app.scripts.seed

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

# ─── Build & Deploy ────────────────────────────────────────────────────────
build: ## Build Docker images
	docker build -t openestimate-backend:latest -f deploy/docker/Dockerfile.backend .
	docker build -t openestimate-frontend:latest -f deploy/docker/Dockerfile.frontend .

# ─── Utilities ──────────────────────────────────────────────────────────────
clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	rm -rf $(BACKEND_DIR)/htmlcov
	rm -rf $(FRONTEND_DIR)/dist
