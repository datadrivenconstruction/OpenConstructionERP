# Build your own module

OpenConstructionERP is built entirely from modules. Every business feature you see (BOQ, BIM Hub, Schedule, CDE, regional packs, AI tooling) is a self-contained module that the platform discovers, loads and mounts on its own. This guide is a practical, ten-minute walkthrough for adding your own.

There are two ways to extend the platform. A **partner pack** is a code-free preset bundle (branding, locale, currency, which modules to show) that anyone can build and share. A **module** is real code: new screens, endpoints, tables, validation rules. Start with the part you need.

---

## Partner Packs

A partner pack is a small, code-free preset bundle for a country, region or company. It carries presets only: branding (logo and colours), a default locale, currency and tax defaults, which modules to show or hide, an optional onboarding script, and references to cost-database regions and validation rule packs that already exist in the core. Anyone can build one, share it, and let an admin activate it in one click from the Partner Packs tab.

> A pack switches on what already exists. It can set a default currency and tax template, default and additional languages, which modules are visible, co-branding, an onboarding script, and which built-in CWICR regions and validation rule packs to turn on.

> A pack ships no code and no data. It is declarative only and is never executed. It cannot ship new validation rule classes or its own catalog data; it only references rule packs and cost regions the core already provides. If you need new screens, endpoints, tables or rules, build a module instead.

### 1. Scaffold the pack

The CLI scaffolds a ready-to-edit folder with a valid manifest, a placeholder logo, an onboarding script and a README. Edit the placeholders and you are done, no code to write.

```bash
openconstructionerp pack new acme-co
# -> creates acme-co/ with:
#      manifest.json    the pack definition (only required file)
#      logo.svg         your logo, shown in-app
#      onboarding.yaml  optional first-login onboarding script
#      README.md
```

Prefer to author it by hand? Just create a folder with a `manifest.json`. The minimal shape is below.

### 2. Edit manifest.json

`manifest.json` is a serialized PartnerPackManifest. `slug`, `partner_name` and `pack_version` identify the pack; the rest are the presets it applies. An empty `default_modules` means all modules stay visible.

```json
{
  "slug": "acme-co",
  "partner_name": "ACME Construction",
  "partner_url": "https://acme.example",
  "pack_version": "0.1.0",
  "description": "Preset for ACME teams in the UK.",
  "default_locale": "en",
  "additional_locales": {},
  "cwicr_regions": [],
  "default_currency": "GBP",
  "default_tax_template": "uk_vat",
  "validation_rule_packs": [],
  "default_modules": [],
  "hidden_modules": [],
  "branding": {
    "primary_color": "#0F2C5F",
    "accent_color": null,
    "logo_path": "logo.svg",
    "favicon_path": null,
    "powered_by_text": null
  },
  "onboarding_script_path": "onboarding.yaml",
  "metadata": {
    "country": "GB",
    "country_name_en": "United Kingdom",
    "support_email": "hello@acme.example"
  }
}
```

### 3. Install it (two ways)

Drop the folder (or a `.zip` of it) into your install's data directory under `packs/`, by default `~/.openestimate/packs/` next to the database, then open the Partner Packs tab and click Rescan. No restart needed.

```bash
# Drop-in: place the pack beside the database, then Rescan in the app
~/.openestimate/packs/acme-co/manifest.json
```

Or zip the folder and upload the `.zip` directly on the Partner Packs tab using the in-app installer (admins only). It is extracted into the same `packs/` directory and appears immediately.

### 4. Activate it

Open Modules then Partner Packs, find your pack and press Activate. It applies the currency, language, validation standards, module visibility and branding, and can install a demo project. Activation is reversible: Deactivate restores the previous state at any time.

> Packs dropped into the data dir, and packs in the repo `packs/` folder, are picked up by Rescan with no restart. Only a brand-new pack shipped as a pip package (registered via an entry point) may still need a backend restart before it appears.

### Optional: ship as a pip package

To distribute on PyPI instead of as a folder or zip, expose the manifest through the entry-point group so it is discovered after `pip install`. A pip-installed pack may require a one-time backend restart.

```toml
[project.entry-points."openconstructionerp.partner_packs"]
acme-co = "openconstructionerp_acme_co:MANIFEST"
```

### Sharing your pack

- Add it as a package to the platform (publish your pip package) so anyone can install and activate it.
- Or contribute it directly through a pull request, which makes it visible to everyone out of the box.
- The pack can display your contact details or website to whoever uses it (your partner website, support email and your co-branding line).
- We can also share information about you and your pack through our social networks, so more people discover your work.

To list your pack or get featured, contact info@datadrivenconstruction.io. A pack holds presets only, no code. If you need new screens, endpoints or tables, build a module (below) and reference it from your pack via `default_modules`.

---

## Prerequisites

Have these ready before starting. If you can run the app locally, you already have everything you need.

- **Python 3.12+**: backend runtime
- **Node.js 22+**: frontend build (CI builds on 24)
- **Git**: clone and commit
- **PostgreSQL 16 or SQLite**: SQLite is auto-created in dev
- **An editor**: VS Code, Cursor, or anything with Python + TypeScript support
- **A clone of the repo** to hack on the module

```bash
git clone https://github.com/datadrivenconstruction/OpenConstructionERP.git
cd OpenConstructionERP
# Backend
cd backend && pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload --port 8000
# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 and log in. Confirm the Modules page loads before starting.

---

## Hello World: your first module in 3 minutes

A minimal end-to-end backend module that serves a greeting endpoint. Copy-paste the blocks below, restart the backend, and curl the route. That is the full loop.

```bash
# 1. Create the folder
mkdir -p backend/app/modules/hello_world

# 2. Mark it as a package (empty file)
touch backend/app/modules/hello_world/__init__.py
```

```python
# 3. backend/app/modules/hello_world/manifest.py
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_hello_world",
    version="0.1.0",
    display_name="Hello World",
    description="My first module",
    author="Me",
    category="community",
    depends=[],
    auto_install=True,
    enabled=True,
)
```

```python
# 4. backend/app/modules/hello_world/router.py
from fastapi import APIRouter

router = APIRouter(prefix="/hello_world", tags=["hello_world"])

@router.get("/")
async def greet(name: str = "World"):
    return {"message": f"Hello, {name}!"}
```

```bash
# 5. Restart backend (Ctrl+C, re-run uvicorn) and test
curl "http://localhost:8000/api/v1/hello_world/?name=Artem"
# -> {"message":"Hello, Artem!"}
```

> That is it: no `main.py` edit, no registry import, no migration. The module loader discovers the folder, reads the manifest, and mounts the router. The module also appears under Modules & Marketplace automatically.

---

## What is a module?

Every business feature is a self-contained module. A module can add REST routes, database tables, UI pages, validation rules, translations, or any combination. You can enable, disable, install or replace any module without touching the core.

- **Backend only**: e.g. a new API connector or webhook receiver.
- **Frontend only**: e.g. a regional BOQ-exchange UI or a niche report.
- **Full-stack**: most real features, with routes, UI and a database migration.

---

## Backend module in 5 minutes

Everything starts from the template in the repo. The module loader auto-discovers anything you drop into `backend/app/modules/`, with no manual wiring of routes or migrations.

1. **Scaffold from the template.** The Makefile target is the one used in CI examples; a raw copy works on machines without `make`.

```bash
# Option A - Makefile target (uses the scaffolder script)
make module-new NAME=oe_my_module

# Option B - plain copy of the template
cp -r modules/oe-module-template backend/app/modules/my_module
```

2. **Edit the manifest.** Open `backend/app/modules/my_module/manifest.py` and set `name`, `version`, `display_name`, and any dependencies on other modules.

```python
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_my_module",            # unique, snake_case, oe_ prefix
    version="0.1.0",
    display_name="My Module",
    description="One-line description",
    author="Your Name",
    category="community",            # core | integration | regional | community
    depends=["oe_projects"],         # hard deps - load fails without them
    optional_depends=["oe_boq"],     # soft deps - present-if-installed
    display_name_i18n={              # localized display names (optional)
        "de": "Mein Modul",
        "ru": "Мой модуль",
    },
    auto_install=False,              # True = enabled on first boot
    enabled=True,
)
```

3. **Add a router.** Routes live in `router.py`. The loader mounts the router at `/api/v1/my_module/*` automatically; you do not touch `main.py`.

```python
from fastapi import APIRouter

router = APIRouter(prefix="/my_module", tags=["my_module"])

@router.get("/")
async def list_items():
    return {"items": []}
```

4. **Add models and schemas (optional).** Drop SQLAlchemy models into `models.py`, Pydantic request/response schemas into `schemas.py`. If you add tables, generate an Alembic migration (see below).

5. **Declare validation rules.** Modules that ingest data must ship validation rules. Subclass `ValidationRule` in `backend/app/core/validation/rules/` and the engine registers it.

6. **Restart and enable.** Restart the backend. The module loader picks up your folder, and the module appears under Modules & Marketplace, System Modules. Toggle it on.

> Reference implementations: `backend/app/modules/boq/` and `backend/app/modules/projects/`.

---

## File structure: what goes where

Both backend and frontend modules follow a strict convention. Follow it and the loader and registry wire everything up; deviate and things break in surprising places. All files except the manifest are optional; start with the smallest set and add files as the module grows.

```text
backend/app/modules/my_module/
├── __init__.py          # empty, marks as package
├── manifest.py          # required: metadata + deps
├── models.py            # SQLAlchemy models (auto-registered)
├── schemas.py           # Pydantic request/response
├── router.py            # FastAPI routes (auto-mounted)
├── service.py           # business logic (stateless)
├── repository.py        # data access layer
├── permissions.py       # permission declarations
├── events.py            # event handlers (optional)
├── hooks.py             # hook handlers (optional)
├── validators.py        # validation rules (optional)
├── migrations/          # Alembic migrations (module-scoped)
│   └── versions/
└── tests/               # pytest
```

```text
frontend/src/modules/my-feature/
├── manifest.ts          # required: id, routes, navItems
├── MyFeatureModule.tsx  # main React component
├── components/          # sub-components (optional)
├── api.ts               # API client fns (uses shared/lib/api)
├── hooks/               # custom hooks (optional)
├── types.ts             # TS types (optional)
└── __tests__/           # vitest
```

---

## Database migrations

If your module adds or changes tables, you must ship a migration. The project uses Alembic; autogenerate is your friend but always review the result.

1. **Define your model.**

```python
# backend/app/modules/my_module/models.py
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.sql import func
from app.database import Base

class MyItem(Base):
    __tablename__ = "oe_my_module_item"   # prefix with the module name

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

2. **Register the model on app startup.** Open `backend/app/main.py`, find the `_import_models_for_migrations` block, and add one line:

```python
from app.modules.my_module import models as _my_module_models  # noqa: F401
```

3. **Generate the migration.**

```bash
cd backend
alembic revision --autogenerate -m "my_module: initial schema"
# Review alembic/versions/<hash>_my_module_initial_schema.py
alembic upgrade head
```

4. **Ship it.** Commit the migration file in `backend/alembic/versions/`. On upgrade, existing installs run `alembic upgrade head` and pick up your new tables automatically.

> Always prefix table names with the module slug (`oe_my_module_*`) to avoid collisions. Never drop columns in a single migration: add the new column, backfill, then drop in a later release.

---

## Frontend module in 5 minutes

Frontend modules live in `frontend/src/modules/`. Each exports a manifest that declares routes, nav items and translations. The registry wires them into the sidebar and router automatically.

1. **Create the folder:** `mkdir frontend/src/modules/my-feature`.

2. **Create manifest.ts.**

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
  category: 'tools',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    { path: '/my-feature', title: 'My Feature', component: MyFeatureModule },
  ],
  navItems: [
    { labelKey: 'nav.my_feature', to: '/my-feature', icon: Sparkles, group: 'tools', advancedOnly: true },
  ],
};
```

3. **Build the React page.** Create `MyFeatureModule.tsx`, a normal React component. Use `useTranslation()` for every user-visible string.

4. **Register it.** Open `frontend/src/modules/_registry.ts` and add your import to the `MODULE_REGISTRY` array.

```ts
import { manifest as myFeature } from './my-feature/manifest';
export const MODULE_REGISTRY = [/* ... */ myFeature];
```

5. **Add translations.** Add the English string for every new i18n key to `frontend/src/app/locales/en` and provide an inline `defaultValue`. Never leave a raw English string in TSX.

---

## Events and hooks: how modules talk to each other

Never import from another module directly. Emit events and subscribe to them. This keeps modules decoupled and makes installing or disabling safe.

```python
# Publish an event
from app.core.events import event_bus

await event_bus.publish(
    "my_module.item.created",
    {"item_id": item.id, "name": item.name},
)
```

```python
# Subscribe in events.py
from app.core.events import event_bus

async def on_boq_change(event):
    # event.payload is the dict from publish()
    ...

event_bus.subscribe("boq.position.updated", on_boq_change)
```

Common events you can listen for:

- `projects.project.created`: after a project is created
- `boq.position.created` / `.updated` / `.deleted`
- `users.user.created` / `.role_changed`
- `documents.document.uploaded`
- `bim.model.ingested`: after CAD/BIM conversion succeeds

---

## Permissions and RBAC

Declare the permissions your module uses. Protect every mutating endpoint with `RequirePermission`; never rely on the user being logged in alone.

```python
# backend/app/modules/my_module/permissions.py
from app.core.permissions import Role, permission_registry

def register_my_module_permissions() -> None:
    permission_registry.register_module_permissions(
        "my_module",
        {
            "my_module.read":   Role.VIEWER,   # anyone signed in
            "my_module.create": Role.EDITOR,
            "my_module.update": Role.EDITOR,
            "my_module.delete": Role.MANAGER,
        },
    )

register_my_module_permissions()
```

```python
from fastapi import Depends
from app.dependencies import RequirePermission

@router.post("/items", dependencies=[Depends(RequirePermission("my_module.create"))])
async def create_item(data: CreateItemSchema):
    return await service.create(data)
```

> Roles are ordered admin > manager > editor > viewer. Grant a permission to `Role.EDITOR` and every editor, manager and admin gets it automatically; admin always bypasses, so you never list it explicitly. Unregistered permission names default to admin-only, which is safe but usually not what you want.

---

## Testing your module

Tests gate every PR. The project uses pytest for backend, vitest for frontend, and Playwright for end-to-end. Running them locally uses the same commands as CI.

```bash
# Backend - pytest
pytest backend/app/modules/my_module
pytest backend/tests/integration

# Frontend - vitest
cd frontend
npm run test
npm run typecheck

# End-to-end - Playwright
cd frontend
npx playwright test
```

Backend tests use httpx + ASGITransport, with no real HTTP. Frontend tests run in jsdom. Shared integration fixtures live in `backend/tests/integration/_auth_helpers.py`.

---

## Installing a third-party module

```bash
# Zip install (recommended)
openconstructionerp module install path/to/my-module-1.0.0.zip

# Manual copy (development)
cp -r downloaded-module backend/app/modules/
# restart backend
```

Then enable it under Modules & Marketplace, System Modules.

---

## Core rules (enforced in PR review)

1. **i18n everywhere.** Every user-visible string goes through `t()`. English strings live in `frontend/src/app/locales/en`.
2. **No IfcOpenShell, no native IFC.** CAD/BIM is always converted through DDC cad2data into the canonical JSON format.
3. **Validation is not optional.** Any module that ingests data must declare validation rules.
4. **AI-augmented, human-confirmed.** AI suggestions must show a confidence score and require user confirmation before mutating data.
5. **AGPL-3.0 compliance.** Contributions are dual-licensed (AGPL + Commercial). First-time contributors sign a CLA via bot.

---

## Quick reference

| I need to...                         | Look at...                                                     |
| ------------------------------------ | ------------------------------------------------------------- |
| Scaffold a backend module            | `modules/oe-module-template/`                                  |
| Real-world backend example           | `backend/app/modules/boq/`                                     |
| Real-world frontend example          | `frontend/src/modules/pdf-takeoff/`                            |
| Add validation rules                 | `backend/app/core/validation/rules/`                          |
| Hook into events                     | `backend/app/core/events.py`                                  |
| Add translations                     | `frontend/src/app/locales/en`                                 |
| Declare a permission                 | `backend/app/modules/my_module/permissions.py`               |
| Guard an endpoint                    | `Depends(RequirePermission("my_module.create"))`             |
| Register a model for migrations      | `backend/app/main.py` -> `_import_models_for_migrations`      |
| Generate a migration                 | `alembic revision --autogenerate -m "msg"`                   |
| Publish an event                     | `event_bus.publish("my_module.item.created", payload)`        |
| Subscribe to an event                | `event_bus.subscribe("boq.position.updated", handler)`        |
| Run backend tests                    | `pytest backend/app/modules/my_module`                        |
| Run frontend typecheck               | `cd frontend && npm run typecheck`                            |
| Package module for sharing           | `zip -r my-module-0.1.0.zip my_module/`                       |

---

## For AI agents

If you are an AI agent scaffolding a module on behalf of a user, follow the same rules as humans, plus:

- Copy the template; do not invent the manifest schema. It changes faster than any document.
- Before reporting the module done, run `npm run typecheck` and `ruff check` + `pytest`. A green build is the contract.
- Never edit the contract files (`_types.ts` or the shape of `_registry.ts`); only append to the registry array.
- Every new user-visible string gets a translation key, an English string in `frontend/src/app/locales/en`, and an inline `defaultValue` fallback.

---

## Troubleshooting

**Module does not appear under Modules & Marketplace.** The backend must have been restarted after dropping the folder. Check the startup log for `[modules] loaded oe_your_module`. Missing? Verify `__init__.py` exists and `manifest.py` defines a `manifest` object at module scope.

**404 on your routes.** The loader prefixes with `/api/v1/<module_name>/`. So `router.py` paths like `@router.get("/")` become `/api/v1/my_module/`. Keep the trailing slash on the frontend API client; `redirect_slashes` is disabled on the backend.

**Alembic autogenerate produces an empty migration.** Alembic only sees models imported at app startup. Add `from app.modules.my_module import models as _m  # noqa: F401` to `_import_models_for_migrations` in `backend/app/main.py`.

**Frontend shows a raw i18n key like `modules.my_feature.title`.** You forgot the English string. Add it to `frontend/src/app/locales/en` with an inline `defaultValue`. The app boots from `locales/en` and lazy-loads the other locales on demand.

**403 Missing permission: my_module.create.** You declared a new permission but no role has it. Edit `backend/app/modules/users/seed_roles.py` and re-run seed. Admin always bypasses; every other role needs an explicit grant.

**TypeScript error in manifest.ts about routes.** The contract lives in `frontend/src/modules/_types.ts`; import `ModuleManifest` from there. Never modify `_types.ts` or the shape of `_registry.ts`; only append your import to the `MODULE_REGISTRY` array.

**Nav item not appearing in the sidebar.** Check that `defaultEnabled` is true in `manifest.ts` (users can still disable it later), and that the nav item's `group` matches an existing sidebar group id. `advancedOnly: true` hides the item until the user turns on Advanced mode in Settings.

---

## Sharing your module with others

Once your module works locally, package it as a zip so others can install it with one command.

```bash
# 1. Build a zip of the module folder
cd backend/app/modules
zip -r ~/my-module-0.1.0.zip my_module

# 2. Share the zip; recipients install with:
openconstructionerp module install ~/my-module-0.1.0.zip

# 3. Optional - publish on the marketplace by opening a PR against
#    github.com/datadrivenconstruction/OpenConstructionERP-modules
#    adding your zip URL + manifest summary
```

Always bump `manifest.version` on every release; the installer uses it to decide when to upgrade an existing install.

---

## Further reading

- [MODULES.md on GitHub](https://github.com/datadrivenconstruction/OpenConstructionERP/blob/main/MODULES.md): single source of truth
- [CONTRIBUTING.md](https://github.com/datadrivenconstruction/OpenConstructionERP/blob/main/CONTRIBUTING.md): style, commits, PR process
