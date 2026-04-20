# Contributing to OpenConstructionERP

Thank you for your interest in contributing! OpenConstructionERP is an open-source platform
for construction cost estimation, and we welcome contributions of all kinds.

## Quick Start

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/OpenConstructionERP.git
cd OpenConstructionERP

# 2. Start dev environment
docker compose up -d   # PostgreSQL + Redis

# 3. Backend
cd backend
pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload --port 8000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## Code Style

### Python (Backend)
- Formatter: `ruff format` (line-length=100)
- Linter: `ruff check`
- Type hints required for all public functions
- Docstrings: Google style

### TypeScript (Frontend)
- Formatter: Prettier (printWidth=100, singleQuote=true)
- Linter: ESLint with `@typescript-eslint/recommended`
- Strict mode enabled

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add GAEB X86 export support
fix: correct unit rate calculation for assemblies
refactor: extract validation engine into separate module
docs: update API reference for BOQ endpoints
test: add integration tests for cost database import
chore: update dependencies
```

## Branch Naming

```
feat/OE-123-short-description
fix/OE-456-bug-name
refactor/OE-789-description
docs/update-readme
```

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with tests
3. Ensure CI passes: `ruff check`, `pytest`, `npm run lint`, `npm run build`
4. Submit a PR with a clear description
5. Address review feedback
6. Squash merge after approval

### PR Checklist

- [ ] Code follows the project's style guidelines
- [ ] Tests added/updated for changes
- [ ] Documentation updated if needed
- [ ] Conventional commit message used
- [ ] No secrets or credentials in the code
- [ ] i18n: all user-facing strings use translation keys

## Module Development

Each module lives in `backend/app/modules/` and follows this structure:

```
modules/my_module/
├── manifest.py      # Required: metadata & dependencies
├── models.py        # SQLAlchemy models
├── schemas.py       # Pydantic request/response schemas
├── router.py        # FastAPI routes
├── service.py       # Business logic
├── repository.py    # Data access
├── permissions.py   # Permission definitions
└── tests/           # Module tests
```

See existing modules (`boq`, `costs`, `projects`) for reference implementations.

## Reporting Issues

- Use [GitHub Issues](https://github.com/datadrivenconstruction/OpenConstructionERP/issues)
- Include: version, steps to reproduce, expected vs actual behavior
- For security issues, see [SECURITY.md](SECURITY.md)

## Contributor License Agreement (CLA)

OpenConstructionERP uses dual licensing (AGPL-3.0 + Commercial). By submitting a PR,
you agree that your contribution can be distributed under both licenses.

First-time contributors will be asked to sign a CLA via a GitHub bot.

## Questions?

- Open a [Discussion](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions)
- Join our community chat (coming soon)

Thank you for helping make construction cost estimation open and accessible!
