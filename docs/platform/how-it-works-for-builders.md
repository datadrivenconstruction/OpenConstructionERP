# How the platform works for builders

This is the reference for the extension model. Every mechanism below is backed
by a file you can open. Paths are relative to the repository root.

## A module is a package plus a manifest

A module is a Python package under `backend/app/modules/<short_name>/`. The only
required file is `manifest.py`, which exposes a value named `manifest` of type
`ModuleManifest`. The dataclass is defined in
`backend/app/core/module_loader.py`:

```python
@dataclass
class ModuleManifest:
    name: str                 # unique, e.g. "oe_boq"
    version: str              # SemVer, e.g. "1.0.0"
    display_name: str
    description: str = ""
    author: str = ""
    category: str = "core"    # "core" | "integration" | "regional" | "community"
    depends: list[str] = field(default_factory=list)
    optional_depends: list[str] = field(default_factory=list)
    display_name_i18n: dict[str, str] = field(default_factory=dict)
    auto_install: bool = False
    enabled: bool = True
```

A real one, from `backend/app/modules/tendering/manifest.py`:

```python
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_tendering",
    version="0.1.0",
    display_name="Tendering",
    description="Bid package management, distribution, collection, and comparison",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_boq"],
    auto_install=True,
    enabled=True,
)
```

A few rules that the loader actually enforces or relies on:

- `name` is the global identity and, by convention, starts with `oe_`. The
  package directory is the name with the `oe_` prefix removed, so `oe_tendering`
  lives in `backend/app/modules/tendering/`. The loader derives this with
  `name.removeprefix("oe_")` and falls back to the full name if that package is
  not found.
- `depends` drives load order. The loader topologically sorts modules so a
  dependency always loads before its dependents. A cycle raises
  `ValueError("Circular dependency detected involving: ...")`. A `depends` entry
  that is not installed logs an `Unknown dependency` warning and is skipped, so
  use `optional_depends` for soft, present-if-installed relationships.
- `category` decides whether an admin can turn the module off at runtime. Core
  modules cannot be disabled. Everything else can.
- `enabled` and the persisted module state decide whether a discovered module
  loads at all. `auto_install` is advisory metadata for the install and
  marketplace flow, it is not what gates loading.

## What the loader does on boot

The lifecycle lives in `ModuleLoader.load_all` and `ModuleLoader._load_module`
in `backend/app/core/module_loader.py`. In order:

1. Discovery. Scan `backend/app/modules/` for directories that contain a
   `manifest.py`. Directories whose name starts with `_` are skipped. Each
   manifest is imported and collected.
2. Resolution. Read persisted module state (so an admin-disabled non-core module
   stays off), then topologically sort the enabled modules by `depends`.
3. Loading. For each module in order, import the package, then attempt to import
   these submodules by convention, each guarded so a missing file is fine:
   - `router` and, if it exposes an `APIRouter` named `router`, mount it.
   - `models` so the SQLAlchemy tables register on `Base.metadata` for Alembic.
   - `hooks`, `events`, `validators`, `pipeline_nodes` purely for their
     import-time side effects (registering handlers and rules).
4. Startup. If the package defines `async def on_startup()`, the loader awaits
   it. This is where a module registers its permissions.

The important consequence: there is no place you register a module. You do not
edit a central list and you do not add an `app.include_router(...)` call. The
package being present under `backend/app/modules/` with a valid manifest is the
registration.

### Router mounting and URLs

When a module has `router.py` with `router = APIRouter(...)`, the loader mounts
it under a versioned, kebab-case prefix built from the directory name:

- `backend/app/modules/rom_estimate/` mounts at `/api/v1/rom-estimate/`.
- `backend/app/modules/tendering/` mounts at `/api/v1/tendering/`.

The directory uses underscores because it is a Python package. The public URL
uses hyphens. For a module whose name contains an underscore, the loader also
mirrors the router at the legacy underscore prefix (for example
`/api/v1/rom_estimate/`) with `include_in_schema=False`, so older callers do not
break. Treat the hyphenated path as canonical.

## The file conventions

None of these files except `manifest.py` are mandatory. They are the shape that
every core module follows so the codebase reads the same everywhere, and so an
AI assistant can extend a module from one file to the next. Using
`backend/app/modules/rom_estimate/` as the reference:

| File | Role | Imported by the loader |
| --- | --- | --- |
| `manifest.py` | `ModuleManifest` metadata and dependencies | yes, at discovery |
| `models.py` | SQLAlchemy ORM models, tables named `oe_<short>_<entity>` | yes, for Alembic |
| `schemas.py` | Pydantic v2 request and response models | transitively, via router |
| `repository.py` | data access, pure queries against an `AsyncSession` | transitively |
| `service.py` | business logic, stateless or session-bound | transitively |
| `router.py` | `APIRouter` named `router` | yes, and mounted |
| `hooks.py` | filter and action handlers | yes, for side effects |
| `events.py` | event subscribers | yes, for side effects |
| `validators.py` | validation rules registered on the global registry | yes, for side effects |
| `permissions.py` | permission definitions | no, call it from `on_startup()` |
| `__init__.py` | optional `async def on_startup()` | yes, awaited last |

Two accuracy notes. First, `permissions.py` is not auto-imported. The convention
is to register permissions from `on_startup()`, which is what
`backend/app/modules/rom_estimate/__init__.py` does:

```python
async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.rom_estimate.permissions import register_rom_estimate_permissions

    register_rom_estimate_permissions()
```

Second, `schemas.py`, `service.py` and `repository.py` are not touched by the
loader directly. They are pulled in transitively when `router.py` imports them.
That is why a broken import inside a router matters: the loader logs a loud
warning and the module's endpoints do not mount, rather than failing silently.

### Models inherit id and timestamps

Models subclass `Base` from `backend/app/database.py`, which provides `id` (a
UUID primary key), `created_at` and `updated_at`. Do not redeclare them. The
`GUID` type decorator, also in `app.database`, gives a portable UUID column. A
minimal model:

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class SiteVisit(Base):
    __tablename__ = "oe_site_log_visit"   # oe_<short>_<entity>
    title: Mapped[str] = mapped_column(String(255), nullable=False)
```

Money and other exact-decimal values are stored as strings, not floats. This is
a platform-wide convention, visible throughout `backend/app/modules/rom_estimate/`,
that keeps large totals from drifting through binary floating point.

### Routers use shared dependencies

Handlers inject the shared FastAPI dependencies from `app.dependencies`. The
common ones:

- `SessionDep` gives an `AsyncSession` that commits or rolls back around the
  request.
- `CurrentUserId` is the authenticated user id, and forces a 401 when there is
  no valid token.
- `RequirePermission("<perm>")` gates a route by permission. Wire it in
  `dependencies=[Depends(RequirePermission("..."))]`.
- `verify_project_access(project_id, user_id, session)` enforces that the caller
  owns or is a team member of a project, returning 404 rather than 403 so it
  cannot be used to probe for ids.

A real route, from `backend/app/modules/rom_estimate/router.py`:

```python
@router.post(
    "/projects/{project_id}/estimates/",
    response_model=RomEstimateRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("rom_estimate.write"))],
)
async def create_estimate(
    project_id: uuid.UUID,
    request: RomEstimateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RomEstimateService = Depends(_get_service),
) -> RomEstimateRecord:
    await verify_project_access(project_id, user_id, session)
    ...
```

## The event bus

The event bus in `backend/app/core/events.py` lets modules react to each other
without importing each other. There is one global instance, `event_bus`.

Subscribe with the `on` decorator. Handlers receive an `Event` object with
`name`, `data`, `id`, `timestamp` and `source_module`:

```python
from app.core.events import event_bus, Event

@event_bus.on("oe_boq.position.created")
async def index_new_position(event: Event) -> None:
    position_id = event.data["position_id"]
    ...
```

Publish with `publish` or `publish_detached`:

```python
# Awaited: returns an EventResult with per-handler outcomes and errors.
result = await event_bus.publish(
    "oe_site_log.visit.created",
    {"id": str(visit.id), "project_id": str(visit.project_id)},
    source_module="oe_site_log",
)

# Fire and forget: schedules the publish as a background task and returns it.
event_bus.publish_detached(
    "oe_site_log.visit.created",
    {"id": str(visit.id)},
    source_module="oe_site_log",
)
```

What to know about the semantics, straight from the source:

- Event names are dot-notation, `{module}.{entity}.{action}`.
- Both async and sync handlers work. A sync handler is run in a thread so it
  never blocks the loop.
- One handler failing does not stop the others. Exceptions are caught, logged,
  and collected into `EventResult.errors`. `result.success` is true when there
  were none.
- Use `publish_detached` from inside a request handler that still holds an open
  database session. It lets the request commit and release its writer before
  subscribers open their own sessions, which avoids self-inflicted lock waits.
  Use `await publish(...)` in tests when you want to see the result.
- `*` is a wildcard subscription that receives every event.

## The hook registry

Events are for notifying. Hooks are for changing data and for injecting side
effects at named points. The registry is in `backend/app/core/hooks.py`, exposed
as the global `hooks`. There are two kinds.

Filters transform a value through a chain of handlers in priority order. Each
handler receives the previous handler's output and returns the next value:

```python
from app.core.hooks import hooks

@hooks.filter("boq.position.before_save", priority=10)
async def auto_classify(position: dict) -> dict:
    position["classification"]["din276"] = classify(position["description"])
    return position
```

Core applies a filter at the point it chooses to expose:

```python
position = await hooks.apply_filters("boq.position.before_save", position)
```

Actions are fire-and-forget side effects at a named point:

```python
@hooks.action("boq.export.completed")
async def notify(boq_id: str) -> None:
    ...

# Core fires it:
await hooks.do_actions("boq.export.completed", boq_id=boq_id)
```

The one difference that matters when you choose between them:

- Filter errors propagate. A filter is on a data path, so a failing filter
  raises and stops the chain rather than silently corrupting the value.
- Action errors are logged and swallowed. A failing action never breaks the
  operation it was attached to.

Both take a `priority` (lower runs first) and an optional `module` label for
introspection. A hook only fires where core calls `apply_filters` or
`do_actions` for that name, so hooks are a contract the core offers at specific
points, not a way to intercept arbitrary functions.

## The module SDK

The SDK ships as a small package, `oe-sdk`, that gives a module author one clean
import surface for the platform building blocks. It is a thin, faithful facade:
every name you import from `oe_sdk` is the same object the running platform uses,
so `from oe_sdk import event_bus` and `from app.core.events import event_bus`
return the same singleton. There is no second implementation to drift out of
sync.

Install it next to the backend. Locally, install both editable so nothing is
downloaded:

```bash
pip install -e ./backend
pip install -e ./packages/oe-sdk
```

Standalone, `pip install oe-sdk` pulls the backend in as a dependency. Run
`oe-sdk info` to check the core resolved, and `oe-sdk new oe_site_log` to
scaffold a full module (models, schemas, repository, service, router, a
migration and tests); the CLI wraps the platform's own generator.

Through that one import you reach:

- Data and web layer: `Base` and `GUID` from `app.database`; the shared
  dependencies `SessionDep`, `CurrentUserId`, `RequirePermission`,
  `verify_project_access` from `app.dependencies`.
- Extension singletons: `event_bus` from `app.core.events`, `hooks` from
  `app.core.hooks`, `rule_registry` from `app.core.validation.engine`,
  `permission_registry` and `Role` from `app.core.permissions`.
- The manifest builder `module_manifest`, plus the template at
  `modules/oe-module-template/` and `make module-new`.

Everything the tutorial uses is one of these names, so you are always building
against documented, stable core surfaces rather than reaching into another
module's internals.

## Validation is a first-class extension point

Validation is not a bolt-on. The engine in
`backend/app/core/validation/engine.py` runs configurable rule sets over any
data, and modules contribute rules to it. The pieces:

- `ValidationRule` is an abstract base with `rule_id`, `name`, `standard`,
  `severity`, `category`, `description`, and an abstract
  `async def validate(self, context) -> list[RuleResult]`.
- `ValidationContext` carries the `data` to check plus `project_id`, `region`,
  `standard` and `metadata`.
- `RuleResult` records `passed`, `severity`, a `message`, an optional
  `element_ref` back to the offending element, and an optional `suggestion`.
- `rule_registry` is the global registry. A module registers a rule instance
  into one or more named rule sets.
- `validation_engine` runs `await validation_engine.validate(data, rule_sets=[...])`
  and returns a `ValidationReport` with a status, a severity-weighted score and
  the individual results.

Because the loader auto-imports `validators.py`, a module adds rules simply by
registering them at import time. The pattern, from
`backend/app/modules/carbon/validators.py`:

```python
from app.core.validation.engine import (
    RuleCategory, RuleResult, Severity, ValidationContext, ValidationRule, rule_registry,
)

class Carbon6DCoverageRule(ValidationRule):
    rule_id = "carbon.6d_coverage"
    name = "6D carbon coverage of BIM elements"
    standard = "carbon_6d"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ...

def register_carbon_validation_rules() -> None:
    rule_registry.register(Carbon6DCoverageRule(), ["carbon_6d"])

# Side-effect registration on import (module-loader autodiscovery contract).
register_carbon_validation_rules()
```

The [tutorial](./first-module-in-10-minutes.md) adds a rule this way.

Register a rule into the set it is about, and no others. A set that no rule
implements is reported to the caller as unsupported and shown on the dashboard
as a check that did not run, which is the truth. Adding one unrelated rule to
it makes the whole set resolve, so the same dashboard shows it as a check that
ran and found nothing.

## How modules reach the marketplace

There are two related surfaces, both open.

Runtime module management lives in `backend/app/core/module_router.py`, mounted
at `/api/v1/modules`:

- `GET /api/v1/modules/` lists every discovered module with its enabled, loaded
  and dependency status, straight from `module_loader.list_modules()`.
- `GET /api/v1/modules/{name}` returns detail for one module.
- `POST /api/v1/modules/{name}/enable` and `.../disable`, both admin-only, turn a
  non-core module on or off at runtime. Disable refuses if another enabled
  module still depends on it, and core modules cannot be disabled at all.
- `GET /api/v1/modules/dependency-tree/{name}` shows who depends on a module.

The add-on marketplace catalog lives in `backend/app/core/marketplace.py` and is
served at `GET /api/marketplace`. It is a curated catalog of installable add-ons,
regional cost databases, resource catalogs, vector indices, language packs,
converters, analytics and demo projects, each with metadata for the frontend. The
`installed` flag is computed at runtime from what the loader has actually loaded,
so the same catalog reflects the state of a live deployment. This is the surface
the frontend Modules page reads.

Distribution of a third-party module today is a plain package drop-in. Zip your
module directory, skipping `__pycache__`, place it where the loader scans
(`backend/app/modules/`), and restart so the loader discovers the manifest. A
signed manifest registry with one-click install is on the roadmap. Until then,
the honest story is: a module is a package, and installing it is putting the
package where the loader looks.

## Next

Build one end-to-end with the
[10-minute tutorial](./first-module-in-10-minutes.md).
