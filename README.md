# OpenEstimate

**Open-source modular platform for construction cost estimation.**

Replaces iTWO, HeavyBid, Sage Estimating. AI-first. 20 languages built-in. Plugin architecture.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

## Features

- **BOQ Editor** — Block-based bill of quantities with assemblies, keyboard navigation, real-time totals
- **Multi-CAD Import** — DWG, DGN, RVT, IFC → automatic quantity extraction (via ODA SDK)
- **AI Takeoff** — Upload PDF/photo → computer vision detects elements → suggests quantities
- **Validation Pipeline** — DIN 276, GAEB, NRM, MasterFormat compliance checking
- **Cost Database** — 55,000+ items (CWICR), 9 languages, semantic search
- **Plugin Modules** — Download → install → works. Cost databases, AI models, integrations
- **20 Languages** — EN, DE, RU, FR, ES, PT, IT, NL, PL, CS, TR, AR, ZH, JA, KO, HI, SV, NO, DA, FI
- **Collaboration** — Real-time multiplayer editing (Figma-style)
- **GAEB XML** — Full support for X81–X89 phases

## Quick Start

```bash
# 1. Clone
git clone https://github.com/openestimate/openestimate.git
cd openestimate

# 2. Start infrastructure
cp .env.example .env
docker compose up -d

# 3. Backend
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:create_app --factory --reload

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Architecture

```
openestimate/
├── backend/          # Python/FastAPI — API, business logic, validation
├── frontend/         # React/TypeScript — UI, i18n, AG Grid
├── services/         # CAD converter (ODA/Rust), CV pipeline, AI
├── modules/          # Plugin modules (install from marketplace)
├── data/             # CWICR database, classification mappings
└── docs/             # Documentation
```

Every feature = module with `manifest.py`. Core is minimal. Everything extensible via hooks/events.

## Module System

```bash
# Install a module from zip
make module-install FILE=oe-rsmeans-connector-1.0.0.zip

# Or from the marketplace (coming soon)
openestimate module install oe-rsmeans-connector
```

Create your own module:
```bash
make module-new NAME=oe_my_module
```

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+ / FastAPI |
| Frontend | React 18 / TypeScript / Tailwind |
| Database | PostgreSQL 16 (+ pg_duckdb for analytics) |
| CAD | ODA SDK + Rust (RVT reverse engineering) |
| AI/CV | PaddleOCR + YOLOv11 |
| Search | Qdrant (vector) / pgvector (simple) |
| i18n | 20 languages, JSON-based |
| Real-time | Yjs (CRDT) |

## License

AGPL-3.0 — free for everyone. Commercial license available for enterprise.

## Contributing

See [CONTRIBUTING.md](docs/CONTRIBUTING.md). All contributions welcome.
