# CLAUDE.md — OpenEstimate Platform

## Идентичность проекта

**OpenEstimate** — open-source модульная платформа для строительной калькуляции и управления стоимостью.
Замена iTWO, HeavyBid, Sage Estimating. Глобальный рынок. AI-first подход.
Лицензия: AGPL-3.0 (community) + Commercial (enterprise).

**Основатель**: Artem — 10+ лет опыта в строительной смете, автор CWICR (55 000+ позиций, 9 языков), cad2db pipeline, DDC.

---

## Философия разработки

### Принципы (нарушение = блокер PR)

1. **LIGHTWEIGHT & SIMPLE** — минимум зависимостей, быстрый старт (`docker compose up` или `pip install openestimate`). Никаких тяжёлых фреймворков. Core должен запускаться на VPS с 2GB RAM.
2. **i18n EVERYWHERE** — 20 языков вшиты в ядро. Все строки UI, validation messages, cost database labels — через i18n. Новый язык = JSON-файл. Zero hardcoded strings.
3. **CAD-agnostic через конвертацию** — мы НЕ используем IfcOpenShell, BCF, нативный IFC. Все CAD-форматы (DWG, DGN, RVT, IFC) конвертируются в наш canonical формат через DDC cad2data + собственный reverse engineering.
4. **Data validation as first-class citizen** — каждый импорт проходит validation pipeline с configurable rule sets (DIN, NRM, MasterFormat, custom). Validation НЕ optional — это часть core workflow.
5. **Modules = plugins** — скачал → положил в папку → перезагрузил → работает. Как npm install. Каждый модуль = zip с manifest. Marketplace для поиска и установки.
6. **Open data standards** — GAEB XML 3.3, DIN 276, NRM, MasterFormat нативно. Проприетарные форматы — через модули.
7. **AI-augmented, human-confirmed** — AI предлагает, человек подтверждает. Confidence scores. Никаких авто-действий без review.
8. **Single-database simplicity** — PostgreSQL единственная обязательная зависимость. SQLite для локальной разработки. Redis optional.

### Языки и стек

| Слой | Технология | Обоснование |
|------|-----------|------------|
| Backend API | **Python 3.12+ / FastAPI** | Async, Pydantic v2, прямой доступ к ML/CV стеку |
| Background tasks | **Celery + Redis** (optional: in-process для dev) | Heavy async: CAD conversion, CV processing, AI inference |
| Frontend | **React 18+ / TypeScript** | AG Grid (BOQ), Three.js (3D viewer), PDF.js (takeoff), Yjs (collab) |
| Database | **PostgreSQL 16+** | OLTP + pg_duckdb (OLAP) + pgvector (AI) + PostGIS (geo) |
| CAD conversion | **DDC cad2data** / **Rust** (RVT reverse engineering) | Все форматы → canonical JSON/Parquet |
| CV/OCR | **PaddleOCR 3.0 + YOLOv11** | PDF takeoff, symbol detection |
| Vector search | **Qdrant** (production) / **pgvector** (simple deploy) | Semantic search по cost database |
| File storage | **MinIO** (S3-compatible) / local filesystem (dev) | Чертежи, модели |
| Real-time | **Yjs + y-websocket** | CRDT-based collaborative editing |

### Конвенции кода

**Python (Backend)**:
- Formatter: `ruff format` (line-length=100)
- Linter: `ruff check` с `select = ["E", "F", "W", "I", "N", "UP", "ANN", "B", "A", "COM", "C4", "PT", "RET", "SIM", "ARG"]`
- Type hints: обязательны для всех public функций и методов
- Docstrings: Google style, обязательны для модулей и public API
- Tests: pytest, минимум 80% coverage для core, 60% для modules
- Async: `async def` для всех endpoint handlers, sync допустим в domain logic
- Imports: absolute imports, группировка stdlib → third-party → local

**TypeScript (Frontend)**:
- Strict mode: `"strict": true` в tsconfig
- Formatter: Prettier (printWidth=100, singleQuote=true)
- Linter: ESLint с `@typescript-eslint/recommended`
- State: Zustand для global state, React Query для server state
- Styling: Tailwind CSS + CSS variables для theming
- Components: functional only, named exports, co-located tests

**Общее**:
- Commits: Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`)
- Branch naming: `feat/OE-123-short-description`, `fix/OE-456-bug-name`
- PR: squash merge, linked issue, minimum 1 approval
- Всё на английском (код, комменты, docs). README/user-facing docs — EN + DE + RU.

---

## Архитектура

### Монорепозиторий

```
openestimate/
├── CLAUDE.md                    # ← ВЫ ЗДЕСЬ
├── LICENSE                      # AGPL-3.0
├── README.md
├── docker-compose.yml           # Dev environment
├── docker-compose.prod.yml      # Production
├── Makefile                     # Common commands
│
├── packages/                    # Shared packages
│   ├── oe-schema/               # Canonical data models (Pydantic + TypeScript)
│   ├── oe-sdk/                  # Module SDK (Python)
│   └── oe-ui-kit/               # Shared UI components (React)
│
├── backend/                     # FastAPI application
│   ├── CLAUDE.md                # Backend-specific instructions
│   ├── pyproject.toml
│   ├── alembic/                 # DB migrations
│   ├── app/
│   │   ├── main.py              # FastAPI app factory
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── database.py          # SQLAlchemy async engine + session
│   │   ├── dependencies.py      # DI container
│   │   ├── middleware/           # Auth, CORS, rate limiting, tenant
│   │   ├── core/                # Framework: events, hooks, module loader
│   │   │   ├── events.py        # Event bus (publish/subscribe)
│   │   │   ├── hooks.py         # Hook registry (filter/action)
│   │   │   ├── module_loader.py # Dynamic module discovery & loading
│   │   │   ├── permissions.py   # RBAC engine
│   │   │   └── validation/      # Validation framework
│   │   │       ├── engine.py    # Rule engine (configurable)
│   │   │       ├── rules/       # Built-in rule sets
│   │   │       │   ├── din276.py
│   │   │       │   ├── nrm.py
│   │   │       │   ├── masterformat.py
│   │   │       │   ├── gaeb.py
│   │   │       │   └── custom.py
│   │   │       └── schemas.py   # Validation result models
│   │   │
│   │   └── modules/             # Business modules (each = self-contained)
│   │       ├── projects/        # Project management
│   │       ├── boq/             # Bill of Quantities (core estimation)
│   │       ├── takeoff/         # Quantity takeoff (manual + AI)
│   │       ├── costs/           # Cost databases & rate management
│   │       ├── cad/             # CAD import/conversion pipeline
│   │       ├── validation/      # Data validation & compliance checking
│   │       ├── tendering/       # Bid management & tender workflows
│   │       ├── reporting/       # Reports, exports, dashboards
│   │       ├── users/           # Auth, teams, permissions
│   │       └── ai/              # AI services (CV, LLM, predictions)
│   │
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       ├── integration/
│       └── fixtures/
│
├── frontend/                    # React SPA
│   ├── CLAUDE.md                # Frontend-specific instructions
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── app/                 # App shell, routing, providers
│   │   ├── features/            # Feature modules (mirror backend modules)
│   │   │   ├── projects/
│   │   │   ├── boq/             # BOQ editor (AG Grid, block-based)
│   │   │   ├── takeoff/         # Takeoff viewer (PDF.js + Canvas overlay)
│   │   │   ├── cad/             # 3D viewer (Three.js)
│   │   │   ├── costs/           # Cost database browser
│   │   │   ├── validation/      # Validation dashboard
│   │   │   ├── tendering/
│   │   │   └── reporting/
│   │   ├── shared/              # Shared components, hooks, utils
│   │   │   ├── ui/              # Design system components
│   │   │   ├── hooks/           # Custom hooks
│   │   │   └── lib/             # Utilities
│   │   └── stores/              # Zustand stores
│   └── tests/
│
├── services/                    # Standalone services
│   ├── cad-converter/           # DDC cad2data + Rust RVT converter
│   │   ├── CLAUDE.md
│   │   ├── Cargo.toml           # Rust workspace
│   │   ├── ddc-bridge/          # Python ↔ DDC cad2data bridge
│   │   └── rvt-parser/          # RVT reverse engineering (Rust)
│   │
│   ├── cv-pipeline/             # Computer Vision for takeoff
│   │   ├── CLAUDE.md
│   │   ├── models/              # YOLO + PaddleOCR configs
│   │   └── pipeline/            # Processing stages
│   │
│   └── ai-service/              # LLM integration service
│       ├── CLAUDE.md
│       └── agents/              # AI agents (BOQ generation, classification, etc.)
│
├── modules/                     # Community/third-party modules (examples)
│   ├── oe-module-template/      # Cookiecutter template
│   ├── oe-gaeb-extended/        # Extended GAEB features
│   └── oe-rsmeans-connector/    # RSMeans API integration
│
├── data/                        # Seed data & migrations
│   ├── cwicr/                   # CWICR database (CSV/Parquet)
│   ├── classifications/         # DIN 276, NRM, MasterFormat mappings
│   └── seeds/                   # Demo project data
│
├── docs/                        # Documentation
│   ├── architecture/
│   ├── api/
│   ├── module-development/
│   └── user-guide/
│
└── deploy/                      # Deployment configs
    ├── docker/
    ├── kubernetes/
    └── terraform/
```

### Модульная система

Каждый модуль — Python package с `manifest.py`:

```python
# backend/app/modules/boq/manifest.py
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_boq",
    version="1.0.0",
    display_name="Bill of Quantities",
    description="Core BOQ editor with hierarchical structure and assembly support",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects", "oe_costs"],  # Module dependencies
    auto_install=True,                     # Installed by default
    # Routes, models, hooks автоматически discovered по конвенции
)
```

**Module conventions**:
```
modules/boq/
├── manifest.py          # Required: metadata & dependencies
├── models.py            # SQLAlchemy models (auto-registered)
├── schemas.py           # Pydantic schemas (request/response)
├── router.py            # FastAPI router (auto-mounted at /api/v1/{module_name}/)
├── service.py           # Business logic (stateless)
├── repository.py        # Data access layer
├── hooks.py             # Hook definitions & handlers
├── events.py            # Event definitions & handlers
├── validators.py        # Module-specific validation rules
├── permissions.py       # Permission definitions
├── migrations/          # Alembic migrations (module-scoped)
└── tests/               # Module tests
```

### Validation Pipeline (КРИТИЧЕСКИ ВАЖНО)

Validation — first-class citizen. Каждый импорт/изменение данных проходит configurable validation:

```python
# Validation rule interface
class ValidationRule(ABC):
    """Base class for all validation rules."""
    
    rule_id: str           # Unique ID, e.g. "din276.cost_group_required"
    name: str              # Human-readable name
    standard: str          # "DIN276", "NRM", "MasterFormat", "GAEB", "custom"
    severity: Severity     # ERROR (blocks), WARNING (flags), INFO (suggests)
    category: str          # "structure", "completeness", "consistency", "compliance"
    
    @abstractmethod
    async def validate(self, context: ValidationContext) -> ValidationResult:
        """Execute validation logic. Return pass/fail with details."""
        ...

# Validation is part of the core workflow pipeline:
# Import → Parse → VALIDATE → Enrich → Store
#                    ↓
#           ValidationReport (
#               passed: list[RuleResult],
#               warnings: list[RuleResult],
#               errors: list[RuleResult],
#               score: float  # 0.0 - 1.0
#           )
```

**Built-in rule sets** (enabled per project/tenant configuration):

| Rule Set | Scope | Examples |
|----------|-------|---------|
| `din276` | DACH cost structure | Cost group hierarchy, allowed KG codes, completeness per level |
| `gaeb` | DACH tender format | GAEB XML schema validation, LV structure, Einheitspreise checks |
| `nrm` | UK measurement | NRM 1/2 element compliance, measurement rules, BCIS compatibility |
| `masterformat` | US classification | Division structure, code format, description requirements |
| `boq_quality` | Universal | Missing quantities, zero prices, duplicate positions, unrealistic unit rates |
| `bim_compliance` | CAD/BIM data | Required properties present, geometry validity, classification mapped |
| `project_completeness` | Universal | All trades covered, total cost benchmarks, missing scope detection |
| `custom` | User-defined | Custom rules via Python scripting or rule builder UI |

Validation results visible in UI as traffic-light dashboard: 🟢 Passed / 🟡 Warnings / 🔴 Errors.
Each result links back to the source element (BOQ position, drawing area, cost item).

### CAD Conversion Pipeline (DDC cad2data + Rust, NO IfcOpenShell)

```
Input (any CAD format)
    ↓
┌─────────────────────────────────┐
│  CAD Converter Service          │
│                                 │
│  DWG → DDC cad2data → Canon JSON │
│  DGN → DDC cad2data → Canon JSON │
│  RVT → Rust parser → Canon JSON │  ← Собственный reverse engineering
│  IFC → DDC cad2data → Canon JSON │  ← Через DDC, НЕ через IfcOpenShell
│  PDF → PyMuPDF → Raster/Vector  │
│  Photos → CV pipeline → Elements│
│                                 │
│  Output: Canonical Format (JSON)│
│  + DuckDB/Parquet (analytics)   │
│  + Metadata extraction          │
└─────────────────────────────────┘
    ↓
VALIDATION (structure, completeness, required properties)
    ↓
Enrichment (classification mapping, cost matching via Qdrant)
    ↓
Storage (PostgreSQL + files in MinIO)
```

**Canonical format** — единый JSON-формат для всех CAD-источников:
```json
{
  "format_version": "1.0",
  "source": {"type": "rvt", "filename": "project.rvt", "converter": "oe-rvt-parser/0.3.0"},
  "metadata": {"project_name": "...", "units": "metric", "coordinate_system": "..."},
  "elements": [
    {
      "id": "elem_001",
      "category": "wall",
      "classification": {"din276": "330", "masterformat": "04 20 00"},
      "geometry": {
        "type": "extrusion",
        "length_m": 12.5,
        "height_m": 3.0,
        "thickness_m": 0.24,
        "area_m2": 37.5,
        "volume_m3": 9.0
      },
      "properties": {"material": "concrete_c30_37", "fire_rating": "F90"},
      "quantities": {"area": 37.5, "volume": 9.0, "length": 12.5},
      "relations": {"level": "level_01", "zone": "zone_a", "parent": null}
    }
  ],
  "levels": [...],
  "zones": [...],
  "spatial_structure": {...}
}
```

### Целевой Workflow (полный)

```
1. IMPORT
   ├── Upload PDF / Photo / CAD file (drag-and-drop или API)
   ├── Auto-detect format (magic bytes + extension)
   └── Route to appropriate converter

2. CONVERT
   ├── CAD → Canonical JSON (DDC cad2data/Rust)
   ├── PDF → Vector extraction + OCR (PyMuPDF + PaddleOCR)
   ├── Photo → CV pipeline (YOLO + OCR)
   └── Output: structured elements with quantities

3. ✅ VALIDATE (NEW — обязательный шаг)
   ├── Structural validation (format correctness, required fields)
   ├── Classification validation (DIN 276 / NRM / MasterFormat compliance)
   ├── Completeness check (all trades covered? missing scope?)
   ├── Consistency check (quantities vs geometry, unit rate ranges)
   ├── Custom rules (project-specific / client-specific)
   ├── Generate ValidationReport with traffic-light dashboard
   └── User reviews & resolves issues before proceeding

4. ENRICH
   ├── AI classification (auto-assign cost codes via ML)
   ├── Cost matching (vector search CWICR/RSMeans via Qdrant)
   ├── Assembly suggestion (similar historical assemblies)
   └── Confidence scores on each AI suggestion

5. ESTIMATE
   ├── BOQ editor (block-based, AG Grid, assemblies)
   ├── Rate application (manual + AI-suggested)
   ├── What-if scenarios (material substitution, regional adjustment)
   ├── Real-time cost rollup with live totals
   └── Collaborative editing (Yjs multiplayer)

6. ✅ VALIDATE ESTIMATE (второй validation pass)
   ├── BOQ quality rules (zero prices, missing quantities, duplicates)
   ├── Benchmark comparison (cost/m² vs historical)
   ├── Anomaly detection (AI flags outliers)
   ├── Completeness vs original scope (coverage %)
   └── Client-specific rules (budget limits, preferred suppliers)

7. TENDER
   ├── Generate tender documents (GAEB X83, PDF, Excel)
   ├── Distribute to subcontractors
   ├── Collect & compare bids
   ├── Bid analysis (price spread, coverage, anomalies)
   └── Award recommendation

8. REPORT & EXPORT
   ├── Executive summary (PDF)
   ├── Detailed BOQ (GAEB XML, Excel, CSV)
   ├── Cost breakdown by KG/NRM/Division
   ├── Validation report (compliance certificate)
   ├── API export (JSON, Parquet)
   └── Integration push (SAP, Procore, MS Project via n8n)
```

---

## Пошаговый план разработки

### Фаза 0: Foundation (Текущая задача — 2 недели)
**Цель**: рабочий monorepo со всей инфраструктурой, без бизнес-логики.

- [ ] Инициализация monorepo (структура директорий, git, .gitignore)
- [ ] `pyproject.toml` с ruff, pytest, dependencies
- [ ] FastAPI app factory (`main.py`, `config.py`, `database.py`)
- [ ] Docker Compose (PostgreSQL 16 + Redis + MinIO)
- [ ] Alembic setup с multi-module migration support
- [ ] Module loader (dynamic discovery, dependency resolution, lifecycle)
- [ ] Event bus (sync + async publish/subscribe)
- [ ] Hook system (filters + actions)
- [ ] Validation framework (rule engine, rule registry, ValidationResult)
- [ ] Auth module (JWT + API keys, basic RBAC)
- [ ] Frontend: Vite + React + TypeScript + Tailwind + Zustand + React Query
- [ ] API client auto-generation (openapi-typescript)
- [ ] Health check endpoint, OpenAPI docs, CORS
- [ ] CI: GitHub Actions (lint + test + build)
- [ ] README с quickstart (docker compose up)

### Фаза 1: Core Estimation (4 недели)
**Цель**: можно создать проект и вручную составить BOQ.

- [ ] Module: `projects` (CRUD, settings, team members)
- [ ] Module: `costs` (cost database CRUD, CWICR import, rate management)
- [ ] Module: `boq` (BOQ editor — hierarchical positions, assemblies, calculations)
- [ ] Module: `validation` (built-in rule sets: DIN 276, GAEB, boq_quality)
- [ ] Frontend: Project dashboard
- [ ] Frontend: BOQ editor (AG Grid, keyboard navigation, inline editing)
- [ ] Frontend: Cost database browser (search, filter, apply to BOQ)
- [ ] Frontend: Validation dashboard (traffic-light, drill-down)
- [ ] GAEB XML import/export (X83 Angebotsabgabe)
- [ ] Excel/CSV import/export
- [ ] Basic reporting (PDF summary)
- [ ] CWICR seed data (all 55K positions)
- [ ] DIN 276 classification tree

### Фаза 2: CAD Integration (4 недели)
**Цель**: загрузка DWG/RVT/IFC → автоматические объёмы.

- [ ] Service: `cad-converter` (DDC cad2data bridge for DWG/DGN/IFC)
- [ ] Service: `rvt-parser` (Rust reverse engineering)
- [ ] Canonical format implementation
- [ ] Validation rules for CAD data (structure, completeness, classification)
- [ ] Frontend: 3D viewer (Three.js, load canonical format)
- [ ] Frontend: Element selection → BOQ position linking
- [ ] Auto quantity extraction from geometry
- [ ] Classification auto-mapping (element category → DIN 276 / NRM)

### Фаза 3: AI Takeoff (4 недели)
**Цель**: загрузка PDF → AI распознаёт элементы → предлагает объёмы.

- [ ] Service: `cv-pipeline` (PaddleOCR + YOLO)
- [ ] PDF page zone detection (drawing area, legend, title block, tables)
- [ ] Symbol detection (doors, windows, MEP symbols)
- [ ] Area/length measurement from vector PDF
- [ ] OCR for dimension strings and annotations
- [ ] Frontend: Takeoff viewer (PDF.js + Canvas overlay)
- [ ] Frontend: Click-to-measure, AI suggestion overlay
- [ ] Confidence scores UI (green/yellow/red)
- [ ] Validation: takeoff results vs manual checks

### Фаза 4: Collaboration & Enterprise (4 недели)
- [ ] Yjs integration (real-time BOQ editing)
- [ ] Multi-user cursors, presence awareness
- [ ] Comment system (threaded, on BOQ positions)
- [ ] Version history & compare
- [ ] Module: `tendering` (bid packages, distribution, collection, comparison)
- [ ] Multi-tenant support (RLS in PostgreSQL)
- [ ] SSO (SAML, OIDC)
- [ ] Audit logging

### Фаза 5: Marketplace & Ecosystem (ongoing)
- [ ] Module SDK v1.0 (documentation, CLI scaffolding)
- [ ] Module marketplace (registry, install, update)
- [ ] NRM rule set, MasterFormat rule set
- [ ] RSMeans connector module
- [ ] BKI/BCIS connector modules
- [ ] n8n integration nodes
- [ ] Mobile PWA
- [ ] Data API (CWICR public API)

---

## Инструкции для Claude Code

### При генерации кода

1. **Всегда проверяй текущую фазу** — не прыгай вперёд. Если мы на фазе 0, не пиши бизнес-логику фазы 1.
2. **Один модуль за раз** — полностью завершай модуль (models → schemas → repository → service → router → tests) прежде чем переходить к следующему.
3. **Tests first для core** — validation engine, module loader, event bus ОБЯЗАТЕЛЬНО с тестами. Business modules — tests после основной реализации.
4. **Читай CLAUDE.md модуля** перед работой с ним — каждый модуль и сервис имеет свой CLAUDE.md с контекстом.
5. **Canonical format — источник истины** — все конверсии CAD → canonical. BOQ работает с canonical. Validation проверяет canonical.
6. **Validation всегда** — при добавлении нового модуля, добавь соответствующие validation rules. Нет модуля без validation.

### При решении проблем

1. Предлагай решение → жди подтверждения → реализуй
2. Если задача неоднозначна — предложи 2–3 варианта с trade-offs
3. Не удаляй существующий код без объяснения и подтверждения
4. Не добавляй зависимости без обоснования (проверь: есть ли stdlib-решение?)

### Стиль ответов

- Код — на английском (переменные, комменты, docs)
- Обсуждение — на русском (если я пишу на русском)
- Технические термины — оставляй на английском (не переводи "validation", "canonical format", "hook")
- Будь конкретен: вместо "нужно добавить validation" → "добавлю ValidationRule `din276_cost_group_hierarchy` в `backend/app/core/validation/rules/din276.py`"

### Команды для разработки

```bash
# Development
make dev              # docker compose up + backend + frontend
make test             # Run all tests
make test-backend     # Run backend tests only
make test-frontend    # Run frontend tests only
make lint             # Ruff + ESLint
make format           # Ruff format + Prettier
make migrate          # Alembic upgrade head
make seed             # Load CWICR + demo data

# Module development
make module-new NAME=oe_tendering    # Scaffold new module
make module-test NAME=oe_boq         # Test specific module
make module-migrate NAME=oe_boq      # Generate module migration

# Build & Deploy
make build            # Docker build all services
make deploy-staging   # Deploy to staging
make deploy-prod      # Deploy to production
```

---

## Ключевые модели данных (Canonical)

### Project
```
Project → has many → BOQs → has many → Sections → has many → Positions
Project → has many → Documents (PDFs, CAD files)
Project → has many → ValidationReports
Project → has one → ProjectConfig (enabled standards, rules, regional settings)
```

### BOQ Position (core entity)
```
Position:
  - id: UUID
  - boq_id: FK
  - parent_id: FK (nullable, for hierarchy)
  - ordinal: str ("01.02.003")
  - description: text
  - unit: enum (m, m2, m3, kg, pcs, lsum, ...)
  - quantity: Decimal
  - unit_rate: Decimal
  - total: Decimal (computed: quantity × unit_rate)
  - classification: JSONB {din276: "330", nrm: "2.6.1", masterformat: "03 30 00"}
  - source: enum (manual, cad_import, ai_takeoff, gaeb_import)
  - confidence: float (0.0-1.0, nullable — only for AI-sourced)
  - assembly_id: FK (nullable — link to assembly template)
  - cad_element_ids: list[str] (links to canonical format elements)
  - validation_status: enum (pending, passed, warnings, errors)
  - metadata: JSONB (flexible, module-extensible)
```

### Assembly (сборная расценка / recipe)
```
Assembly:
  - id: UUID
  - name: str ("Stahlbetonwand C30/37, 24cm, Schalung, Bewehrung")
  - category: str
  - components: list[AssemblyComponent]
    - cost_item_id: FK to CostDatabase
    - factor: Decimal (e.g., 1.0 for concrete, 0.12 for rebar per m3)
    - unit: str
  - total_rate: Decimal (computed from components)
  - regional_factors: JSONB (Berlin: 1.05, München: 1.12, ...)
```

### Validation
```
ValidationReport:
  - id: UUID
  - project_id: FK
  - target_type: enum (boq, document, cad_import, tender)
  - target_id: UUID
  - rule_set: str ("din276+gaeb+boq_quality")
  - status: enum (passed, warnings, errors)
  - score: float (0.0-1.0)
  - results: list[ValidationResult]
    - rule_id: str
    - status: enum (pass, warning, error)
    - message: str
    - element_ref: str (link to specific BOQ position / CAD element / document page)
    - details: JSONB
  - created_at: datetime
  - created_by: FK
```

---

## Переменные окружения (.env.example)

```env
# Database
DATABASE_URL=postgresql+asyncpg://oe:oe@localhost:5432/openestimate
DATABASE_SYNC_URL=postgresql://oe:oe@localhost:5432/openestimate

# Redis (optional for dev — falls back to in-memory)
REDIS_URL=redis://localhost:6379/0

# MinIO / S3
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=openestimate

# Auth
JWT_SECRET=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# AI Services (optional — features degrade gracefully)
QDRANT_URL=http://localhost:6333
OPENAI_API_KEY=             # For LLM features
ANTHROPIC_API_KEY=          # For LLM features

# CAD Converter
# CAD converter uses DDC cad2data (no separate license key needed)
CAD_CONVERTER_URL=http://localhost:8001

# CV Pipeline
CV_PIPELINE_URL=http://localhost:8002

# App
APP_ENV=development
APP_DEBUG=true
LOG_LEVEL=INFO
ALLOWED_ORIGINS=http://localhost:5173
```

---

## Важные ограничения

1. **НЕ используем IfcOpenShell** — весь BIM/CAD через DDC cad2data + собственный reverse engineering
2. **НЕ используем BCF** — своя система issues/comments/collaboration
3. **НЕ используем natively IFC** — IFC это просто ещё один CAD формат для конвертации в canonical
4. **НЕ монолитная архитектура** — каждая функция = модуль с manifest
5. **НЕ optional validation** — validation pipeline обязателен в workflow
6. **НЕ auto-apply AI results** — всегда human review с confidence scores
7. **НЕ vendor lock-in** — все данные exportable, все форматы open
