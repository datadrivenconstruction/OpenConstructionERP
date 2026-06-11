# Module Development Quickstart

OpenConstructionERP is **modular by design**. Every feature — projects, BOQ,
takeoff, validation, even the cost database — is a plugin that the
core loader discovers on boot. Adding a new feature means writing a
new module, not editing the platform.

This guide takes you from zero to a running module in about 10 minutes.

## The plugin model

A module is a Python package that:

1. Lives under `backend/app/modules/<short_name>/`.
2. Exposes a `manifest.py` defining a `ModuleManifest(...)` value.
3. (Optionally) provides `models.py`, `schemas.py`, `repository.py`,
   `service.py`, `router.py`, `hooks.py`, `events.py`, `permissions.py`.

The loader (`backend/app/core/module_loader.py`) discovers manifests,
topologically sorts by `depends`, imports the package, registers
SQLAlchemy models on `Base.metadata`, mounts the router at
`/api/v1/<short_name>/`, and calls `on_startup()` if defined.

No central registry to edit. No `app.include_router(...)` call to add.
Drop the package in, restart, done.

## Scaffold a new module

```bash
make module-new NAME=oe_my_module
```

What happens:

1. The Makefile target calls `python -m app.scripts.scaffold_module oe_my_module`.
2. The script validates `NAME` matches `^oe_[a-z][a-z0-9_]*$`.
3. It copies `modules/oe-module-template/` to
   `backend/app/modules/my_module/` (note: the `oe_` prefix is stripped
   for the directory — the manifest still carries the full name).
4. Placeholders `{{module_name}}`, `{{module_short}}`,
   `{{display_name}}`, `{{author}}` are substituted in every file
   AND in the test filename.

On Linux, macOS, and Windows the same target works because the script
is pure Python — no shell tricks, no `sed`, no `cp -r`.

## What's in the box

The generated module ships with a working Item entity so you can see
the pattern end-to-end. Replace it with your real domain.

```
backend/app/modules/my_module/
├── manifest.py          # ModuleManifest — name, version, depends, category
├── __init__.py          # on_startup() hook
├── models.py            # SQLAlchemy ORM — table oe_my_module_item
├── schemas.py           # Pydantic ItemCreate / ItemUpdate / ItemRead
├── repository.py        # async CRUD against the DB
├── service.py           # business logic + event publishing
├── router.py            # FastAPI routes — /api/v1/my_module/items
├── migrations/
│   └── v0001_initial.py # Alembic migration for the stub table
└── tests/
    └── test_my_module.py  # 3 smoke tests (no DB required)
```

## File-by-file

### manifest.py

The only required file. Everything else is convention. The dataclass
fields the loader cares about:

- `name` — globally unique, must start with `oe_`.
- `version` — SemVer string.
- `depends` — list of other manifest names. Topological sort ensures
  load order. Cycles raise.
- `category` — `core` modules can't be disabled at runtime; community
  modules can be toggled from the UI.
- `auto_install` — `True` to enable on first boot, `False` to leave
  disabled until an operator turns it on.

### models.py

SQLAlchemy 2.0 declarative. Every table name MUST be prefixed
`oe_<short_name>_` so future migration tooling can scope downgrades
to a single module.

Inherit from `app.database.Base` to get `id` (UUID PK), `created_at`,
`updated_at` for free.

### schemas.py

Pydantic v2 models. Convention: one trio per entity —
`<Entity>Create`, `<Entity>Update`, `<Entity>Read`. `Read` sets
`model_config = ConfigDict(from_attributes=True)` to project the ORM
row directly.

### repository.py

Pure data access. Methods take an `AsyncSession`, return model
instances or primitives. No HTTP, no business logic, no transaction
commits — those live in the service layer.

### service.py

Stateless functions that compose repository calls, publish events,
and raise `HTTPException` for caller-visible errors. The router
commits the session once per request after the service returns.

### router.py

FastAPI `APIRouter` named `router`. Loader auto-mounts it at
`/api/v1/<short_name>/`. Endpoints inject `SessionDep` and (when auth
is required) `CurrentUserId` from `app.dependencies`.

### migrations/v0001_initial.py

A template Alembic revision. After scaffolding:

1. Run `cd backend && alembic current` to find the active head.
2. Set `down_revision = "<that-head>"` in the migration.
3. Move the file into `backend/alembic/versions/`.
4. Run `make migrate`.

The migration is idempotent (inspector-guarded), so re-runs are safe.

### tests/test_<short>.py

Three smoke tests: manifest well-formed, schema rejects bad input,
schema accepts good input. They run without a DB so they pass on a
fresh checkout. Move into `backend/tests/unit/` (and rename if the
name collides) to wire into the main test run.

## Events and hooks

Publish:

```python
from app.core.events import event_bus

event_bus.publish_detached(
    "my_module.item.created",
    {"id": str(item.id), "project_id": str(item.project_id)},
    source_module="oe_my_module",
)
```

Subscribe in `events.py`:

```python
from app.core.events import event_bus

@event_bus.subscribe("oe_boq.position.updated")
async def on_position_updated(payload: dict) -> None:
    ...
```

Hooks (filter/action) live in `hooks.py` and use the same registry —
see `backend/app/core/hooks.py` for the API.

## Permissions

Register inside `on_startup()`:

```python
async def on_startup() -> None:
    from app.core.permissions import register_permission

    register_permission("my_module.item.read",  "Read items")
    register_permission("my_module.item.write", "Create / update items")
```

Routes guard with `Depends(require_permission("my_module.item.write"))`.

## Vibe-coding tip

The scaffold is small and self-similar. Paste `manifest.py` plus
`models.py` into your AI chat of choice and prompt:

> "This is one entity in an OpenConstructionERP module. Add a second entity
> called `Comment` that belongs to an Item, with `author_id` (UUID),
> `body` (text), and a created_at timestamp. Generate the model,
> schemas, repository, service, and router changes. Match the existing
> style."

The model returns a coherent patch because every layer follows the
same shape. That's the whole point of the convention.

## Distribute

Zip the module directory (skip `__pycache__`) and another deployment
can drop it into their `modules/` folder, then restart:

```bash
zip -r oe-my-module-0.1.0.zip my_module -x "*__pycache__*"
```

A signed manifest registry / marketplace is on the roadmap for
Phase 5 — for now distribution is a plain zip.

## Troubleshooting

- **Module not discovered**: check `manifest.py` exists, the package
  has an `__init__.py`, and the directory name does not start with `_`.
- **`Unknown dependency`** warning at boot: a `depends=[...]` entry
  points to a module that isn't installed. Either install it or move
  it to `optional_depends`.
- **Table already exists** on migrate: the inspector guard in
  `v0001_initial.py` skips re-runs, but if you renamed the table after
  the first migration ran you need to write a follow-up revision.
- **Routes 404**: confirm the router is named exactly `router` (the
  loader looks for that attribute) and that `manifest.enabled` is `True`.
