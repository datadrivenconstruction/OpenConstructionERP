# Modules — Developer Guide

How to build, install, and publish modules for OpenConstructionERP.

OpenConstructionERP is modular by design: every business feature (BOQ, BIM,
Takeoff, Schedule, CDE, regional BOQ packs…) is a self-contained module that
can be enabled, disabled, installed, or replaced without touching the core.

This file is the **single entry point**. Deeper material lives alongside the
code it describes — the links point there.

---

## 1. What is a module?

A module is a self-contained unit that may contribute any of:

| Surface       | Where it lives                                  | Registered by            |
|---------------|-------------------------------------------------|--------------------------|
| REST routes   | `backend/app/modules/<name>/router.py`          | `manifest.py`            |
| DB models     | `backend/app/modules/<name>/models.py`          | auto-discovered          |
| Business code | `backend/app/modules/<name>/service.py`         | imported from router     |
| UI pages      | `frontend/src/modules/<name>/manifest.ts`       | `_registry.ts`           |
| i18n strings  | `manifest.ts` → `translations` + `i18n-fallbacks.ts` | runtime i18next       |
| Validation    | `backend/app/modules/<name>/validators.py`      | central validation engine |

A module that only adds UI (e.g. a regional BOQ exchange) can live purely in
`frontend/src/modules/`. A module that only adds API logic (e.g. a new
connector) can live purely in `backend/app/modules/`. Most full-stack features
have both.

---

## 2. Backend module — 5-minute walkthrough

**Start from the template**:

```bash
cp -r modules/oe-module-template backend/app/modules/my_module
```

Then edit `backend/app/modules/my_module/manifest.py`:

```python
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_my_module",        # unique, snake_case, oe_ prefix
    version="0.1.0",
    display_name="My Module",
    description="One-line description",
    author="Your Name",
    category="community",        # core | integration | regional | community
    depends=["oe_projects"],     # other modules this needs
    auto_install=False,          # False = user enables it from /modules
    enabled=True,
)
```

**Minimum viable file set**:

```
backend/app/modules/my_module/
├── __init__.py
├── manifest.py          # REQUIRED — metadata
├── router.py            # FastAPI router, auto-mounted at /api/v1/my_module/*
├── models.py            # SQLAlchemy models (optional)
├── schemas.py           # Pydantic request/response models
├── service.py           # Business logic (stateless, sync or async)
└── tests/
```

**Router convention** (`router.py`):

```python
from fastapi import APIRouter

router = APIRouter(prefix="/my_module", tags=["my_module"])

@router.get("/")
async def list_items():
    return {"items": []}
```

The prefix is mounted under `/api/v1/`, so the endpoint becomes
`GET /api/v1/my_module/`. The module loader wires this automatically — no
need to edit `main.py`.

**Migrations**: if you add models, put Alembic migrations under
`backend/app/modules/my_module/migrations/` and run `make migrate`.

**Validation rules**: drop a file under
`backend/app/core/validation/rules/my_module.py` that subclasses
`ValidationRule`. The engine auto-registers it.

Reference implementations: `backend/app/modules/boq/`, `backend/app/modules/projects/`.

---

## 3. Frontend module — 5-minute walkthrough

Full 450-line guide lives at:
**[`frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md`](frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md)**

**Short version**:

```bash
mkdir frontend/src/modules/my-feature
```

Create `frontend/src/modules/my-feature/manifest.ts`:

```ts
import { lazy } from 'react';
import { Sparkles } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const MyFeatureModule = lazy(() => import('./MyFeatureModule'));

export const manifest: ModuleManifest = {
  id: 'my-feature',
  name: 'My Feature',
  description: 'What this module does in one line',
  version: '1.0.0',
  icon: Sparkles,
  category: 'tools',           // estimation | planning | procurement | tools
  defaultEnabled: false,
  depends: ['boq'],

  routes: [{ path: '/my-feature', title: 'My Feature', component: MyFeatureModule }],

  navItems: [{
    labelKey: 'nav.my_feature',
    to: '/my-feature',
    icon: Sparkles,
    group: 'tools',
    advancedOnly: true,
  }],
};
```

Then register in `frontend/src/modules/_registry.ts`:

```ts
import { manifest as myFeature } from './my-feature/manifest';
export const MODULE_REGISTRY = [..., myFeature];
```

All nav/routes appear automatically once registered.

---

## 4. Installing a third-party module

Two supported paths:

**Zip install** (recommended for distribution):

```bash
openestimate module install path/to/my-module-1.0.0.zip
```

**Manual install** (development):

```bash
cp -r downloaded-module backend/app/modules/
# restart backend — module loader picks it up
```

Then enable it from the UI: **Settings → Modules & Marketplace → System Modules**.

---

## 5. Core rules (enforced in PR review)

1. **i18n everywhere** — every user-visible string goes through `t()`. No
   hardcoded English. Fallbacks live in `frontend/src/app/i18n-fallbacks.ts`.
2. **No IfcOpenShell / BCF / native IFC** — CAD/BIM is always converted
   through DDC cad2data to the canonical JSON format (see `CLAUDE.md`).
3. **Validation is not optional** — any module that ingests data must declare
   validation rules. See `backend/app/core/validation/`.
4. **AI-augmented, human-confirmed** — AI suggestions must show a confidence
   score and require user confirmation before mutating data.
5. **AGPL-3.0 compliance** — contributions are dual-licensed (AGPL + Commercial).
   First-time contributors sign a CLA via bot.

---

## 6. Quick reference

| I need to…                          | Look at…                                                                 |
|-------------------------------------|--------------------------------------------------------------------------|
| Scaffold a backend module           | `modules/oe-module-template/`                                            |
| Full frontend module spec           | `frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md`                       |
| Real-world backend example          | `backend/app/modules/boq/`                                               |
| Real-world frontend example         | `frontend/src/modules/pdf-takeoff/`                                      |
| Add validation rules                | `backend/app/core/validation/rules/`                                     |
| Hook into events                    | `backend/app/core/events.py` + `<your_module>/events.py`                 |
| Add/override translations           | `frontend/src/app/i18n-fallbacks.ts`                                     |
| Contribute back                     | [`CONTRIBUTING.md`](CONTRIBUTING.md)                                     |
| Overall architecture                | [`CLAUDE.md`](CLAUDE.md) — §Архитектура                                  |

---

## 7. Notes for AI agents

If you are an AI agent creating a module on behalf of a user:

- Copy the template, don't start from scratch — the manifest contract changes
  faster than this doc.
- Read the relevant module's `CLAUDE.md` (if present) before modifying it.
- Run `npm run typecheck` (frontend) and `ruff check` + `pytest` (backend)
  before reporting the module done.
- Never edit `frontend/src/modules/_types.ts` or `_registry.ts` contract —
  only *add* to the registry array.
- If a module needs a new translation key, add the English fallback to
  `i18n-fallbacks.ts` in all locale blocks you touch — never leave a raw
  English string in TSX code.
