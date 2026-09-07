# Your first module in 10 minutes

This walkthrough scaffolds a real module, gives it a model, a schema, a router
and one validation rule, wires its migration, and shows the loader mounting it
on the next restart. Every command and code block matches the conventions in the
repository. We build a small "Site Log" module.

## Before you start

Install the backend once and have a dev database available. From the repository
root:

```bash
make setup           # installs backend and frontend dependencies
```

The platform runs an embedded PostgreSQL by default, so no separate database
service is required for local work. If you prefer an external database, set
`DATABASE_URL` before running migrations.

## Step 1: scaffold the module

```bash
make module-new NAME=oe_site_log
```

The target runs `python -m app.scripts.scaffold_module oe_site_log`, which
validates the name against `^oe_[a-z][a-z0-9_]*$`, copies
`modules/oe-module-template/` to `backend/app/modules/site_log/` (the `oe_`
prefix is stripped for the directory), and substitutes the `{{module_name}}`,
`{{module_short}}`, `{{display_name}}` and `{{author}}` placeholders in every
file and in the test filename. It refuses to overwrite an existing module.

You will see:

```
Done - module scaffolded at .../backend/app/modules/site_log
  Next:
    1. Edit .../manifest.py (description, depends).
    2. Move .../migrations/v0001_initial.py into
       backend/alembic/versions/ and set down_revision to the
       current head (run `alembic current` to find it).
    3. Run `make migrate` then `make test-backend`.
```

To set the author too, call the script directly:
`python -m app.scripts.scaffold_module oe_site_log "Your Name"`.

## Step 2: look at what you got

```
backend/app/modules/site_log/
├── manifest.py            # ModuleManifest for oe_site_log
├── __init__.py            # on_startup() hook
├── models.py              # SQLAlchemy Item, table oe_site_log_item
├── schemas.py             # ItemCreate / ItemUpdate / ItemRead
├── repository.py          # ItemRepository (async CRUD)
├── service.py             # create/update/delete + event publish
├── router.py              # APIRouter, mounts at /api/v1/site-log/
├── migrations/
│   └── v0001_initial.py   # Alembic migration for the stub table
└── tests/
    └── test_site_log.py   # 3 smoke tests, no DB required
```

The template ships a working `Item` entity so the pattern is complete on the
first boot. We keep `Item` as our site-log entry for this walkthrough and rename
it later. The generated `manifest.py`:

```python
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_site_log",
    version="0.1.0",
    display_name="Site Log",
    description="TODO: one-sentence description of what this module does.",
    author="Module Author",
    category="community",
    depends=[],
    optional_depends=[],
    auto_install=False,
    enabled=True,
)
```

The generated `models.py` (comments trimmed):

```python
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Item(Base):
    __tablename__ = "oe_site_log_item"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
```

The generated `router.py` gives you a health ping plus full CRUD, already using
the shared dependencies:

```python
from app.dependencies import CurrentUserId, SessionDep
from app.modules.site_log import service
from app.modules.site_log.repository import ItemRepository
from app.modules.site_log.schemas import ItemCreate, ItemRead, ItemUpdate

router = APIRouter()


@router.get("/", tags=["oe_site_log"])
async def module_info() -> dict[str, str]:
    return {"module": "oe_site_log", "status": "active"}


@router.post("/items", response_model=ItemRead, status_code=status.HTTP_201_CREATED, tags=["oe_site_log"])
async def create_item(payload: ItemCreate, session: SessionDep, _user_id: CurrentUserId) -> ItemRead:
    item = await service.create_item(session, payload)
    await session.commit()
    return ItemRead.model_validate(item)
```

`service.create_item` publishes `oe_site_log.item.created` on the event bus, so
other modules can already react to your data.

## Step 3: declare the dependency

The model has a foreign key to `oe_projects_project`, so the module depends on
the projects module. Open `manifest.py`, write a real description, and add the
dependency:

```python
    description="Simple per-project site log of daily entries.",
    depends=["oe_projects"],
```

The loader loads `oe_projects` before `oe_site_log` because of this line.

## Step 4: wire the migration

Find the current migration head, set it as the migration's parent, then move the
file into the Alembic versions folder.

```bash
cd backend
alembic current          # prints the active head, e.g. 4f2a9c1b7e30
```

Open `backend/app/modules/site_log/migrations/v0001_initial.py` and set
`down_revision` to that id:

```python
revision: str = "oe_site_log_v0001_initial"
down_revision = "4f2a9c1b7e30"     # the head you just printed
```

Move it into `backend/alembic/versions/`, then apply it:

```bash
mv app/modules/site_log/migrations/v0001_initial.py \
   alembic/versions/oe_site_log_v0001_initial.py
cd ..
make migrate
```

The migration is inspector-guarded, so it is idempotent. It creates
`oe_site_log_item` with the `id`, `name`, `description`, `project_id`,
`created_at` and `updated_at` columns and an index on `project_id`.

## Step 5: add one validation rule

Validation is a first-class extension point, and the loader auto-imports a
module's `validators.py`. Create
`backend/app/modules/site_log/validators.py`:

```python
"""Site Log validation rules, registered at import time."""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)


class SiteLogEntryHasNoteRule(ValidationRule):
    """Warn when a site-log entry has no description."""

    rule_id = "site_log.entry_has_note"
    name = "Site log entry has a note"
    standard = "site_log"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every site log entry should carry a non-empty description."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data
        items: list[Any] = data.get("items", []) if isinstance(data, dict) else []
        results: list[RuleResult] = []
        for item in items:
            note = (item.get("description") or "").strip() if isinstance(item, dict) else ""
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=bool(note),
                    message="OK" if note else "Site log entry has no description.",
                    element_ref=str(item.get("id")) if isinstance(item, dict) else None,
                    suggestion="Add a short note describing what happened on site.",
                )
            )
        return results


def register_site_log_rules() -> None:
    rule_registry.register(SiteLogEntryHasNoteRule(), ["site_log"])
    logger.debug("Registered site_log validation rules")


# Side-effect registration on import (module-loader autodiscovery contract).
register_site_log_rules()
```

This is the exact shape used by `backend/app/modules/carbon/validators.py`. The
rule belongs to the `site_log` set, which is the set it is about, and anyone who
asks for that set gets it.

A rule can be registered into more than one set, and the second name is worth
thinking about before you write it. A set that no rule implements comes back
from the engine in `unsupported_rule_sets` and the dashboard shows it under
"not implemented (did not run)". Your one rule is enough to make that whole set
resolve, and then the same dashboard shows it as a check that ran and found
nothing, which is a stronger claim than your module can make. Add your rule to
a set you would be willing to answer for, and leave the rest visibly empty.

## Step 6: register permissions

Add `backend/app/modules/site_log/permissions.py`, mirroring
`backend/app/modules/rom_estimate/permissions.py`:

```python
from app.core.permissions import Role, permission_registry


def register_site_log_permissions() -> None:
    permission_registry.register_module_permissions(
        "site_log",
        {
            "site_log.read": Role.VIEWER,
            "site_log.write": Role.EDITOR,
        },
    )
```

Call it from `on_startup()` in `backend/app/modules/site_log/__init__.py`:

```python
async def on_startup() -> None:
    from app.modules.site_log.permissions import register_site_log_permissions

    register_site_log_permissions()
```

Now gate the write route. In `router.py`, add `Depends` and `RequirePermission`
to the imports and put the permission on the create endpoint:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.dependencies import CurrentUserId, RequirePermission, SessionDep

@router.post(
    "/items",
    response_model=ItemRead,
    status_code=status.HTTP_201_CREATED,
    tags=["oe_site_log"],
    dependencies=[Depends(RequirePermission("site_log.write"))],
)
async def create_item(payload: ItemCreate, session: SessionDep, _user_id: CurrentUserId) -> ItemRead:
    ...
```

## Step 7: restart and watch it mount

```bash
make dev-backend         # starts the API on http://localhost:8000
```

During startup the loader logs the module coming up. Representative lines:

```
Discovered module: oe_site_log v0.1.0 (Site Log)
Loading N modules in order: [..., 'oe_projects', ..., 'oe_site_log']
Mounted router for oe_site_log at /api/v1/site-log
Registered 2 permissions for module 'site_log'
```

The router mount is automatic. You did not edit a central list and you did not
add an `app.include_router(...)` call anywhere.

## Step 8: verify the auto-load

The health ping is public, so a plain request confirms the mount:

```bash
curl http://localhost:8000/api/v1/site-log/
# {"module":"oe_site_log","status":"active"}
```

The module management API reports it as discovered, loaded and routed:

```bash
curl http://localhost:8000/api/v1/modules/
# [ ... {"name":"oe_site_log","loaded":true,"has_router":true,"enabled":true,...} ... ]
```

Your validation rule is now in the global registry, so the engine runs it for
its rule sets:

```python
from app.core.validation.engine import validation_engine

report = await validation_engine.validate(
    data={"items": [{"id": "a1", "description": ""}, {"id": "a2", "description": "Poured slab"}]},
    rule_sets=["site_log"],
    target_type="site_log",
)
print(report.status.value, report.score)   # "warnings", a score below 1.0
```

Open `http://localhost:8000/docs` and the Site Log endpoints appear under their
own tag. The CRUD routes require a bearer token; the health ping does not.

## Step 9: run the smoke tests

The generated test only exercises the schemas and the manifest, so it needs no
database. Move it into the backend test tree and run it:

```bash
mv backend/app/modules/site_log/tests/test_site_log.py backend/tests/unit/
make module-test NAME=site_log     # pytest -x -v tests/ -k "site_log"
```

The bundled tests assert the manifest is well formed
(`manifest.name == "oe_site_log"`), that `ItemCreate` rejects a missing name, and
that it accepts a valid payload.

## What you built

A real module that the loader discovers by convention. It has a table
(`oe_site_log_item`), a Pydantic schema trio, a mounted router at
`/api/v1/site-log/`, a validation rule contributed to two rule sets, module
permissions, and an event (`oe_site_log.item.created`) that other modules can
subscribe to. None of it required editing a core file.

## Where to go next

- Rename `Item` to your real entity across `models.py`, `schemas.py`,
  `repository.py`, `service.py` and `router.py`, then write a follow-up
  migration. Keep the table prefixed `oe_site_log_`.
- Subscribe to another module's events, or expose a hook, without touching core.
  See [Extend, do not fork](./extend-dont-fork.md).
- Re-read [How the platform works for builders](./how-it-works-for-builders.md)
  for the full loader, event bus, hook and validation reference.
