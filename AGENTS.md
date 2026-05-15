# AGENTS.md — OpenConstructionERP

## Stack
- **Backend**: Python 3.12+ / FastAPI / SQLAlchemy (async) / Alembic / Pydantic v2
- **Frontend**: React 18 / TypeScript / Vite / Tailwind / AG Grid / i18next
- **Database**: PostgreSQL 16+ (prod) / SQLite (dev, zero-config)
- **CLI**: `openestimate` / `openconstructionerp` (installed via pip)

## Repo Structure

```
backend/app/          # FastAPI app (60+ auto-discovered modules)
frontend/src/         # React SPA
Makefile              # Root task runner
```

## Dev Commands

```bash
# First time
make setup             # pip install backend[server] + npm install frontend

# Local dev (two terminals required — not backgrounded)
# Terminal 1:
make dev-backend      # uvicorn app.main:create_app --factory --reload --port 8000
# Terminal 2:
make dev-frontend     # cd frontend && npm run dev  (http://localhost:5173)

# POSIX-only shortcut (Linux/macOS, backgrounds both):
make dev-unix         # Does NOT work on Windows cmd.exe or MSYS2 make

# Code quality (run before committing)
make lint             # ruff check (backend) + eslint (frontend)
make format           # ruff format (backend) + prettier (frontend)
make typecheck        # mypy (backend) + tsc --noEmit (frontend)

# Testing
make test             # backend + frontend tests
make test-backend     # pytest -x -v (cd backend && pytest also works)
make test-backend-cov # pytest --cov=app --cov-report=term
make test-frontend    # cd frontend && npm run test

# Database
make migrate          # alembic upgrade head
make seed             # python -m app.scripts.seed_catalog
make db-reset         # DESTRUCTIVE: drop + recreate + migrate + seed

# Single module: make module-test NAME=oe_boq
```

## Key Conventions

- **Lint/format tools**: ruff (backend, NOT flake8), prettier/eslint (frontend)
- **Typecheck**: mypy (strict with `ignore_missing_imports: true`); FastAPI DI uses unused-arg params intentionally
- **pytest markers**: `-m unit` (no DB), `-m integration` (requires DB)
- **Backend entrypoint**: `uvicorn app.main:create_app --factory` (--factory required)
- **API types**: regenerate with `openapi-typescript http://localhost:8000/api/openapi.json -o frontend/src/shared/lib/api-types.ts`
- **Version sync**: `backend/pyproject.toml` and `frontend/package.json` versions must stay in sync (pre-commit hook guards this)

## Install Gotchas

- **Ubuntu/Debian**: `pip install` fails with `externally-managed-environment` (PEP 668). Use venv:
  ```bash
  python3.12 -m venv venv && source venv/bin/activate && pip install openconstructionerp
  ```
- **pip install from repo**: `pip install -e ./backend[server]`
- **Building wheel**: frontend builds first (`cd frontend && npm ci && npm run build`), then backend builds

## Docker / Production

```bash
make quickstart        # docker compose -f docker-compose.quickstart.yml up --build (zero-config, http://localhost:8080)
make quickstart-down
make quickstart-reset  # DESTRUCTIVE: deletes volumes
make build             # build all Docker images
```

## Demo Accounts
Auto-created on first startup. Default password `DemoPass1234!` for all three:
- Admin: `demo@openestimator.io`
- Estimator: `estimator@openestimator.io`
- Manager: `manager@openestimator.io`

Override with `DEMO_ADMIN_PASSWORD` / `DEMO_ESTIMATOR_PASSWORD` / `DEMO_MANAGER_PASSWORD` env vars before first boot, or disable with `DISABLE_DEMO_ACCOUNTS=1`.

## Pre-commit
```bash
pre-commit install    # Installs: ruff, gitleaks, conventional commits, version-sync-check
```
Commit messages must follow: `feat, fix, refactor, docs, test, chore, perf, ci, build, style`.

## AI Integration
AI providers (Anthropic, OpenAI, Gemini, Mistral, Groq, DeepSeek) are called via REST/httpx — no vendor SDKs in deps. API keys stored in DB and `~/.openestimate/config.json`.
