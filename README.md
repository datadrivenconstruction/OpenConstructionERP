# OpenEstimate

**Open-source modular platform for construction cost estimation.**

Replaces iTWO, HeavyBid, Sage Estimating. AI-first. 20 languages built-in. Plugin architecture.

[![CI](https://github.com/openestimate/openestimate/actions/workflows/ci.yml/badge.svg)](https://github.com/openestimate/openestimate/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![GitHub release](https://img.shields.io/github/v/release/openestimate/openestimate)](https://github.com/openestimate/openestimate/releases)
[![Docker Image](https://img.shields.io/badge/ghcr.io-openestimate-blue)](https://ghcr.io/openestimate/openestimate)
[![i18n: 20 languages](https://img.shields.io/badge/i18n-20_languages-green)](#languages)

## Features

- **BOQ Editor** — Block-based bill of quantities with assemblies, keyboard navigation, real-time totals
- **Multi-CAD Import** — DWG, DGN, RVT, IFC to automatic quantity extraction (via ODA SDK)
- **AI Takeoff** — Upload PDF/photo, computer vision detects elements, suggests quantities
- **Validation Pipeline** — DIN 276, GAEB, NRM, MasterFormat compliance checking
- **Cost Database** — 55,000+ items (CWICR), 9 languages, semantic search
- **Plugin Modules** — Download, install, works. Cost databases, AI models, integrations
- **20 Languages** — EN, DE, RU, FR, ES, PT, IT, NL, PL, CS, TR, AR, ZH, JA, KO, HI, SV, NO, DA, FI
- **Collaboration** — Real-time multiplayer editing (Figma-style)
- **GAEB XML** — Full support for X81-X89 phases
- **Cost Modeling** — Parametric models, benchmarking, sensitivity analysis
- **Tendering** — Bid packages, distribution, comparison, award recommendations
- **Schedule** — Gantt charts linked to BOQ positions
- **Dark Mode** — System-aware with manual toggle

## Quick Start

### Option 1: Docker (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/openestimate/openestimate/main/docker-compose.quickstart.yml \
  -o docker-compose.yml
docker compose up
```

Open http://localhost:8080 — register your first account.

### Option 2: pip install

```bash
pip install openestimate
openestimate serve --open
```

Opens browser at http://localhost:8080. Data stored in `~/.openestimate/`.

### Option 3: Docker Compose (full stack)

```bash
git clone https://github.com/openestimate/openestimate.git
cd openestimate
cp .env.example .env
docker compose up -d
```

### Option 4: Desktop App

Download from [Releases](https://github.com/openestimate/openestimate/releases) — available for Windows (.exe), macOS (.dmg), Linux (.AppImage/.deb).

## One-Click Cloud Deploy

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/openestimate)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/openestimate/openestimate)

## Development

```bash
# 1. Clone
git clone https://github.com/openestimate/openestimate.git
cd openestimate

# 2. Start infrastructure
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

Open http://localhost:5173

### Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

## Architecture

```
openestimate/
├── backend/          # Python/FastAPI — API, business logic, validation
├── frontend/         # React/TypeScript — UI, i18n, AG Grid
├── desktop/          # Tauri v2 — desktop app wrapper
├── services/         # CAD converter (ODA/Rust), CV pipeline, AI
├── modules/          # Plugin modules (install from marketplace)
├── data/             # Cost catalogs, classification mappings
├── deploy/           # Docker, Railway, Render, Terraform configs
└── scripts/          # Installation scripts
```

Every feature = module with `manifest.py`. Core is minimal. Everything extensible via hooks and events.

## Module System

```bash
# Install a module
openestimate module install oe-rsmeans-connector

# Create your own module
make module-new NAME=oe_my_module
```

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+ / FastAPI |
| Frontend | React 18 / TypeScript / Tailwind |
| Database | PostgreSQL 16 (SQLite for local/desktop) |
| CAD | ODA SDK + Rust (RVT reverse engineering) |
| AI/CV | PaddleOCR + YOLOv11 |
| Search | LanceDB (embedded) / Qdrant (production) |
| i18n | 20 languages, JSON-based |
| Real-time | Yjs (CRDT) |
| Desktop | Tauri v2 |

## Languages

EN, DE, RU, FR, ES, PT, IT, NL, PL, CS, TR, AR, ZH, JA, KO, HI, SV, NO, DA, FI

Adding a new language = one JSON file. See `frontend/src/app/i18n.ts`.

## License

AGPL-3.0 — free for everyone. See [LICENSE](LICENSE).

Commercial license available for enterprise. Contact: license@openestimate.io

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. All contributions welcome.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## Links

- [Changelog](CHANGELOG.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md)
