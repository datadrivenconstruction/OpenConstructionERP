<div align="center">

# OpenConstructionERP

**The #1 open-source platform for construction cost estimation**

[Demo](https://openconstructionerp.com) · [Documentation](https://openconstructionerp.com/docs) · [Community](https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR/discussions)

![License](https://img.shields.io/badge/license-AGPL--3.0-blue)
![Version](https://img.shields.io/badge/version-0.1.0-green)
![Languages](https://img.shields.io/badge/languages-21-orange)
![Validation Rules](https://img.shields.io/badge/validation_rules-42-purple)

</div>

---

Professional construction cost estimation for everyone — from solo quantity surveyors to enterprise contractors.

## Why OpenConstructionERP?

- **Free & Open Source** — AGPL-3.0. Self-hosted. Your data stays on your machine.
- **21 Languages** — Full i18n for DE, FR, ES, PT, RU, ZH, AR, JA, KO, HI, BG and more
- **20 Regional Standards** — DIN 276, NRM, MasterFormat, ГЭСН, DPGF, GB/T 50500, CPWD, and 13 more
- **AI-Powered** — Connect any LLM (Anthropic, OpenAI, Gemini, Mistral, Groq, DeepSeek) for smart estimation
- **55,000+ Cost Items** — CWICR database with 11 regional pricing databases
- **42 Validation Rules** — Automatic compliance checking for 13 international standards

## Key Features

### Estimation

- **BOQ Editor** — Hierarchical Bill of Quantities with AG Grid, inline editing, resources, markups (overhead, profit, VAT)
- **Cost Database** — 55K+ items across 11 regions (US, UK, DE, FR, ES, PT, RU, AE, CN, IN, CA)
- **Resource Catalog** — 7,000+ materials, labor, equipment with catalog picker and assemblies
- **Assemblies** — Reusable cost recipes with component breakdown

### Planning & Analysis

- **4D Schedule** — Gantt chart with CPM critical path, dependencies, resource assignment
- **5D Cost Model** — Earned Value Management (SPI, CPI), S-curve, budget tracking, what-if scenarios
- **Risk Register** — Risk matrix, probability x impact, mitigation strategies
- **Analytics** — Cross-project KPIs, budget comparison, variance analysis

### Collaboration & Export

- **Tendering** — Bid packages, subcontractor management, bid comparison charts
- **Change Orders** — Scope changes with cost and schedule impact tracking
- **Reports** — PDF, Excel, GAEB XML, CSV export with 12 report templates
- **Documents** — File management with drag-and-drop upload

### AI Features

- **AI Quick Estimate** — Generate BOQ from text, photo, PDF, Excel, or CAD/BIM
- **AI Cost Advisor** — Chat with AI about costs, materials, pricing
- **AI Smart Actions** — Enhance descriptions, suggest prerequisites, escalate rates, check scope

### Regional Standards (20 exchange modules)

| Standard | Region | Format |
|----------|--------|--------|
| DIN 276 / ÖNORM / SIA | DE/AT/CH | Excel/CSV |
| NRM 1/2 (RICS) | UK | Excel/CSV |
| CSI MasterFormat | US/CA | Excel/CSV |
| GAEB DA XML 3.3 | DACH | XML |
| DPGF / DQE | France | Excel/CSV |
| ГЭСН / ФЕР | Russia/CIS | Excel/CSV |
| GB/T 50500 | China | Excel/CSV |
| CPWD / IS 1200 | India | Excel/CSV |
| Bayındırlık Birim Fiyat | Turkey | Excel/CSV |
| 積算基準 (Sekisan) | Japan | Excel/CSV |
| Computo Metrico / DEI | Italy | Excel/CSV |
| STABU / RAW | Netherlands | Excel/CSV |
| KNR / KNNR | Poland | Excel/CSV |
| 표준품셈 | South Korea | Excel/CSV |
| NS 3420 / AMA | Nordic | Excel/CSV |
| ÚRS / TSKP | Czech/Slovakia | Excel/CSV |
| ACMM / ANZSMM | Australia/NZ | Excel/CSV |
| CSI/CIQS | Canada | Excel/CSV |
| FIDIC | UAE/GCC | Excel/CSV |
| PBC / Base de Precios | Spain | Excel/CSV |

## Quick Start

### Option 1: Docker (recommended)

```bash
git clone https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR.git
cd OpenConstructionEstimate-DDC-CWICR
docker compose up
```

Open http://localhost:5173 — demo account: `demo@openestimator.io` / `DemoPass1234!`

### Option 2: Local Development

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Option 3: One-Click Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/...)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+ / FastAPI |
| Frontend | React 18 / TypeScript / Vite |
| Database | PostgreSQL 16+ / SQLite (dev) |
| UI | Tailwind CSS / AG Grid |
| AI | Any LLM via API (Anthropic, OpenAI, etc.) |
| Search | LanceDB vector search |
| i18n | 21 languages |

## Architecture

```
Frontend (React SPA)
    ↓ REST API
Backend (FastAPI)
    ↓
Database (PostgreSQL/SQLite)
    ↓
Modules: BOQ, Costs, Schedule, 5D, Validation, AI, Tendering, ...
```

17 auto-discovered modules, 42 validation rules, plugin architecture.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

AGPL-3.0 — see [LICENSE](LICENSE).

For commercial licensing (without AGPL obligations), contact [info@datadrivenconstruction.io](mailto:info@datadrivenconstruction.io).

## Created by

**Artem Boiko** — [datadrivenconstruction.io](https://datadrivenconstruction.io)

Author of CWICR (55K+ cost items, 9 languages) and cad2db pipeline. Building open-source tools for the global construction industry.
