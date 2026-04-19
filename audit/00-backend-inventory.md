# Backend FastAPI Endpoint Inventory — OpenConstructionERP

**Scope**: `backend/app/modules/*/router.py` + `backend/app/core/*_router.py` + inline routes in `backend/app/main.py`.
**Generated**: audit pass against current `main` branch.
**Stack**: FastAPI 0.11x + async SQLAlchemy, module loader auto-mounts each module router at `/api/v1/{dir_name}`.

---

## Route aggregation pattern

- `backend/app/main.py::create_app()` is the FastAPI app factory.
- System routes mounted explicitly:
  - `i18n_router` at `/api/v1` (router has its own `/i18n` prefix)
  - `module_mgmt_router`, `audit_router`, `global_search_router`, `activity_feed_router`, `sidebar_badges_router` (each carries its own `/api/v1/...` prefix).
- Business modules are discovered by `app.core.module_loader.ModuleLoader.discover()` — it walks `backend/app/modules/*/manifest.py`, topologically sorts by `depends=[...]`, imports `router.py`, and auto-mounts with `prefix=f"/api/v1/{dir_name}"` (dir name with the `oe_` prefix stripped).
- Duplicate mounts via aliases (inside `on_event("startup")`): `changeorders` at `/api/v1/variations`, `costmodel` at `/api/v1/finance/evm`, `tendering` at `/api/v1/procurement/tenders`, `opencde_api` also at `/api/v1/opencde`.
- Middleware chain (order of `app.add_middleware(...)`): `CORSMiddleware` -> `APIVersionMiddleware` -> `DDCFingerprintMiddleware` -> `SecurityHeadersMiddleware` -> `SlowRequestLoggerMiddleware` -> `AcceptLanguageMiddleware`.
- CORS is configured from `settings.cors_origins`; wildcard `*` is stripped when `is_production`, falling back to `https://openconstructionerp.com`.
- Global `@app.exception_handler(Exception)` returns 500 JSON `{"detail": "Internal server error"}`.

## Module loader (summary)

`backend/app/core/module_loader.py`:

1. **Discover**: walks `backend/app/modules/`, imports each `manifest.py`, expects a `manifest: ModuleManifest` singleton.
2. **Persist state**: `load_module_states()` reads a JSON file; non-core modules can be disabled.
3. **Topological sort** by `manifest.depends`.
4. **Load** each module: imports `router.py`, `models.py`, `hooks.py`, `events.py`, `validators.py` lazily with `contextlib.suppress(ModuleNotFoundError)`.
5. **Mount** at `/api/v1/{dir_name}` with `tags=[manifest.display_name]`.
6. **Lifecycle**: calls `package.on_startup()` if defined; `enable_module` / `disable_module` can re-mount or strip routes at runtime (core modules cannot be disabled).

---

## Endpoint inventory table

Counts below are occurrences of `@router.(get|post|put|patch|delete)`. Secondary `@router.post(...)` decorators stacked on the same function (used in `users/router.py` to expose both `/auth/login` and `/auth/login/`) are counted separately — those are the 2 duplicated pairs noted in the anomaly section. Auth column is YES if the router imports any of `CurrentUserId`, `RequirePermission`, `get_current_user_id`, `require_permission`.

### Core system routers (`backend/app/core/*_router.py`)

| Module | Prefix | Endpoints | Methods | Auth? | Manifest? | Notes |
|---|---|---|---|---|---|---|
| `i18n_router` | `/api/v1/i18n` | 2 | GET | NO | N/A (core) | Public: `/locales`, `/{locale}` — intentional, used by i18next-http-backend on every page load |
| `module_router` | `/api/v1/modules` | 5 | GET, POST | PARTIAL | N/A (core) | Admin enable/disable gated by `RequirePermission("admin")`; 3 GETs are PUBLIC (list all, get detail, dependency tree) |
| `audit_router` | `/api/v1/audit` | 2 | GET | YES | N/A (core) | Uses `CurrentUserId` (note: default `= None` — see anomaly) |
| `global_search_router` | `/api/v1/search` | 1 | GET | YES | N/A (core) | Cross-module search |
| `activity_feed_router` | `/api/v1/activity` | 1 | GET | YES | N/A (core) | Cross-module activity feed |
| `sidebar_badges_router` | `/api/v1/sidebar` | 1 | GET | PARTIAL | N/A (core) | Uses `SessionDep` + Query but no explicit `CurrentUserId` in route sig — verify |

### Business modules (`backend/app/modules/*/router.py`)

| Module | Prefix | Endpoints | Methods | Auth? | Manifest? | Notes |
|---|---|---|---|---|---|---|
| `ai` | `/api/v1/ai` | 10 | GET, POST | YES | YES | depends=`oe_boq`, `oe_projects` |
| `architecture_map` | `/api/v1/architecture_map` | 6 | GET | **NO** | YES | Public — serves architecture manifest JSON, read-only |
| `asia_pac_pack` | `/api/v1/asia_pac_pack` | 1 | GET | **NO** | YES | Public — returns `PACK_CONFIG` |
| `assemblies` | `/api/v1/assemblies` | 16 | GET, POST, PUT, PATCH, DELETE | YES | YES | depends=`oe_costs` |
| `backup` | `/api/v1/backup` | 3 | POST | YES | YES | All gated by `RequirePermission("backup.admin")`; 100 MB upload cap |
| `bim_hub` | `/api/v1/bim_hub` | 37 | GET, POST, PUT, PATCH, DELETE | YES | YES | Largest after `boq` / `schedule`; depends=`oe_users,oe_projects,oe_boq` |
| `bim_requirements` | `/api/v1/bim_requirements` | 8 | GET, POST, PUT, PATCH, DELETE | YES | YES | |
| `boq` | `/api/v1/boq` | 69 | GET, POST, PATCH, DELETE | YES | YES | Core estimation surface — largest module |
| `cad` | (not mounted) | 0 | — | — | YES | **ANOMALY**: manifest exists but no `router.py`; only `classification_mapper.py` + `__init__.py` |
| `catalog` | `/api/v1/catalog` | 9 | GET, POST, DELETE | YES | YES | |
| `cde` | `/api/v1/cde` | 12 | GET, POST, PATCH | YES | YES | |
| `changeorders` | `/api/v1/changeorders` + alias `/api/v1/variations` | 12 | GET, POST, PATCH, DELETE | YES | YES | Also mounted at alias inside startup |
| `collaboration` | `/api/v1/collaboration` | 7 | GET, POST, DELETE | YES | YES | |
| `collaboration_locks` | `/api/v1/collaboration_locks` | 5 | GET, POST, DELETE | YES | YES | Heartbeat-based pessimistic locks |
| `contacts` | `/api/v1/contacts` | 11 | GET, POST, PATCH, DELETE | YES | YES | |
| `correspondence` | `/api/v1/correspondence` | 5 | GET, POST, PATCH | YES | YES | |
| `costmodel` | `/api/v1/costmodel` + alias `/api/v1/finance/evm` | 18 | GET, POST, PATCH, DELETE | YES | YES | |
| `costs` | `/api/v1/costs` | 24 | GET, POST, PATCH, DELETE | YES | YES | Cost database CRUD |
| `dach_pack` | `/api/v1/dach_pack` | 1 | GET | **NO** | YES | Public — `/config` |
| `documents` | `/api/v1/documents` | 26 | GET, POST, PATCH, DELETE | YES | YES | |
| `dwg_takeoff` | `/api/v1/dwg_takeoff` | 17 | GET, POST, PATCH, DELETE | YES | YES | |
| `enterprise_workflows` | `/api/v1/enterprise_workflows` | 10 | GET, POST, PATCH | YES | YES | |
| `erp_chat` | `/api/v1/erp_chat` | 6 | GET, POST, DELETE | YES | YES | |
| `fieldreports` | `/api/v1/fieldreports` | 24 | GET, POST, PATCH, DELETE | YES | YES | |
| `finance` | `/api/v1/finance` | 17 | GET, POST, PATCH, DELETE | YES | YES | |
| `full_evm` | `/api/v1/full_evm` | 3 | GET, POST | YES | YES | depends=`oe_finance` |
| `i18n_foundation` | `/api/v1/i18n_foundation` | 19 | GET, POST, PATCH, DELETE | YES | YES | Distinct from core `i18n_router` |
| `india_pack` | `/api/v1/india_pack` | 1 | GET | **NO** | YES | Public — `/config` |
| `inspections` | `/api/v1/inspections` | 8 | GET, POST, PATCH | YES | YES | |
| `integrations` | `/api/v1/integrations` | 12 | GET, POST, PATCH, DELETE | YES | YES | |
| `latam_pack` | `/api/v1/latam_pack` | 1 | GET | **NO** | YES | Public — `/config` |
| `markups` | `/api/v1/markups` | 16 | GET, POST, PATCH, DELETE | YES | YES | |
| `meetings` | `/api/v1/meetings` | 10 | GET, POST, PATCH, DELETE | YES | YES | |
| `middle_east_pack` | `/api/v1/middle_east_pack` | 1 | GET | **NO** | YES | Public — `/config` |
| `ncr` | `/api/v1/ncr` | 7 | GET, POST, PATCH | YES | YES | |
| `notifications` | `/api/v1/notifications` | 5 | GET, POST, DELETE | YES | YES | |
| `opencde_api` | `/api/v1/opencde_api` + alias `/api/v1/opencde` | 13 | GET, POST, PUT | PARTIAL | YES | Foundation discovery endpoints (`/foundation/versions/`, `/foundation/1.1/auth/`) are intentionally public per OpenCDE spec |
| `procurement` | `/api/v1/procurement` | 10 | GET, POST, PATCH | YES | YES | |
| `project_intelligence` | `/api/v1/project_intelligence` | 8 | GET, POST | YES | YES | |
| `projects` | `/api/v1/projects` | 18 | GET, POST, PATCH, DELETE | YES | YES | Note: 1 `soft-delete` + 1 `hard-delete` endpoint for same `{project_id}` |
| `punchlist` | `/api/v1/punchlist` | 12 | GET, POST, PATCH, DELETE | YES | YES | |
| `reporting` | `/api/v1/reporting` | 9 | GET, POST | YES | YES | |
| `requirements` | `/api/v1/requirements` | 19 | GET, POST, PATCH, DELETE | YES | YES | |
| `rfi` | `/api/v1/rfi` | 12 | GET, POST, PATCH, DELETE | YES | YES | |
| `rfq_bidding` | `/api/v1/rfq_bidding` | 11 | GET, POST, PATCH | YES | YES | |
| `risk` | `/api/v1/risk` | 10 | GET, POST, PATCH, DELETE | YES | YES | |
| `russia_pack` | `/api/v1/russia_pack` | 1 | GET | **NO** | YES | Public — `/config` |
| `safety` | `/api/v1/safety` | 14 | GET, POST, PATCH, DELETE | YES | YES | |
| `schedule` | `/api/v1/schedule` | 40 | GET, POST, PATCH, DELETE | YES | YES | CPM / Gantt |
| `search` | `/api/v1/search` | 3 | GET | YES | YES | Shadows prefix of core `global_search_router` — see anomaly |
| `submittals` | `/api/v1/submittals` | 8 | GET, POST, PATCH | YES | YES | |
| `takeoff` | `/api/v1/takeoff` | 34 | GET, POST, PATCH, DELETE | YES | YES | depends=`oe_projects,oe_cad` (cad has no router) |
| `tasks` | `/api/v1/tasks` | 16 | GET, POST, PATCH, DELETE | YES | YES | |
| `teams` | `/api/v1/teams` | 8 | GET, POST, PATCH, DELETE | YES | YES | |
| `tendering` | `/api/v1/tendering` + alias `/api/v1/procurement/tenders` | 10 | GET, POST, PATCH | YES | YES | |
| `transmittals` | `/api/v1/transmittals` | 8 | GET, POST, PATCH | YES | YES | |
| `uk_pack` | `/api/v1/uk_pack` | 1 | GET | **NO** | YES | Public — `/config` |
| `us_pack` | `/api/v1/us_pack` | 1 | GET | **NO** | YES | Public — `/config` |
| `users` | `/api/v1/users` | 26 | GET, POST, PATCH, DELETE | PARTIAL | YES | Auth bootstrap endpoints (`/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/forgot-password`, `/auth/reset-password`) are intentionally public; all 5 have duplicate trailing-slash variants |
| `validation` | `/api/v1/validation` | 7 | GET, POST | YES | YES | depends=`oe_projects,oe_boq` |

### Inline `main.py` routes (system-level, not via a router)

| Path | Method | Auth? | Notes |
|---|---|---|---|
| `/api/health` | GET | NO | Public — liveness probe, memory, DB ping |
| `/api/source` | GET | NO | Public — AGPL source disclosure |
| `/api/system/status` | GET | NO | Public — exposes DB engine, vector engine, configured AI providers (name only, not keys) |
| `/api/system/version-check` | GET | NO | Public — queries GitHub releases |
| `/api/system/modules` | GET | NO | Public — duplicates `/api/v1/modules/` from core `module_router` |
| `/api/marketplace` | GET | NO | Public — marketplace catalog |
| `/api/demo/catalog` | GET | NO | Public — list demo templates |
| `/api/demo/install/{demo_id}` | POST | YES | `Depends(get_current_user_id)` |
| `/api/demo/status` | GET | NO | Public — lists installed demo IDs (may leak tenant state) |
| `/api/demo/uninstall/{demo_id}` | DELETE | YES | |
| `/api/demo/clear-all` | DELETE | YES | |
| `/api/system/validation-rules` | GET | NO | Public — lists configured validation rules |
| `/api/system/hooks` | GET | NO | Public — lists registered hooks (framework introspection) |
| `/api/v1/feedback` | POST | **NO** | Public — writes user feedback into SQLite table; **rate-limit not applied** |

---

## Totals

- Business module router files: **59** (of 60 module directories; `cad` has a manifest but no router)
- Total business-module router endpoints: **736**
- Core `*_router.py` files: **6** with **12** endpoints
- Inline `main.py` system endpoints: **14**
- **Grand total endpoints**: **736 + 12 + 14 = 762**
- **Total modules with a manifest**: **60** (directory count), of which 59 have a working router
- **Modules via `module_loader`** (mount at `/api/v1/{dir}`): all 59 routers
- **Alias mounts**: 4 (`/api/v1/opencde`, `/api/v1/variations`, `/api/v1/finance/evm`, `/api/v1/procurement/tenders`)

---

## Anomalies

### A1 — `cad` module has manifest but no router (HIGH — broken dependency)
- `backend/app/modules/cad/manifest.py` declares `name="oe_cad"` with `depends=["oe_projects"]`.
- Only `__init__.py`, `manifest.py`, `classification_mapper.py` exist — **no** `router.py`, `models.py`, `service.py`, etc.
- `backend/app/modules/takeoff/manifest.py` lists `oe_cad` in `depends`, so the module loader loads `cad` first and finds no router (logged as debug, not an error).
- The global `CAD Conversion Pipeline` section of `CLAUDE.md` treats `cad` as a core module. The current state is a stub.

### A2 — Public regional `/config/` endpoints (LOW)
`us_pack`, `uk_pack`, `dach_pack`, `india_pack`, `russia_pack`, `middle_east_pack`, `latam_pack`, `asia_pac_pack` each expose a single `GET /config/` endpoint with no auth. Payload is `PACK_CONFIG`, a static dict of regional classifications / VAT rates / currency — not sensitive, but should still be gated behind `CurrentUserId` for consistency with the rest of the platform.

### A3 — `architecture_map` is fully public (LOW / INFO)
6 GET endpoints serve `frontend/src/features/architecture/architecture_manifest.json`. No auth. The manifest describes the entire module graph (names, connections, tags) — useful for the "architecture diagram" page. No sensitive data, but should be confirmed as intentionally public.

### A4 — Inline `main.py` public endpoints include system introspection (MEDIUM)
`/api/system/status`, `/api/system/modules`, `/api/system/validation-rules`, `/api/system/hooks`, `/api/marketplace`, `/api/demo/catalog`, `/api/demo/status` are unauthenticated. They leak:
- DB engine (`sqlite` vs `postgresql`)
- Vector backend + vector count
- **Configured AI provider names** (OpenAI / Anthropic / Gemini booleans)
- Installed demo project IDs
- Full list of validation rule IDs and hook names

None expose secrets directly, but taken together they are a fingerprinting gift. `/api/health` and `/api/source` are reasonable to keep public (liveness + AGPL compliance); the rest should be admin-gated.

### A5 — `/api/v1/feedback` is public + rate-limit-free (MEDIUM)
`submit_feedback` in `main.py` writes arbitrary `category / subject / description / email / page_path` into a SQLite table with only `len(str)` truncation. No CAPTCHA, no IP rate limit, no auth. Trivial spam vector. Contrast with `users/router.py::register` which uses `login_limiter.is_allowed(f"reg_{client_ip}")`.

### A6 — Core `module_router.py` leaks module graph publicly (LOW)
`GET /api/v1/modules/`, `GET /api/v1/modules/{name}`, `GET /api/v1/modules/dependency-tree/{name}` have **no auth**. Only enable/disable are admin-gated. This duplicates the inline `/api/system/modules` route — both unauthenticated.

### A7 — Prefix collision: `search` module vs `global_search_router` (MEDIUM)
Both mount under `/api/v1/search`:
- `backend/app/core/global_search_router.py` — `APIRouter(prefix="/api/v1/search")` adds `GET /api/v1/search` (cross-module, 1 endpoint).
- `backend/app/modules/search/router.py` — auto-mounted at `/api/v1/search` via module loader, adds 3 endpoints (`/status`, `/types`, etc.).
FastAPI registers both (no startup error because paths differ after the shared prefix), but routing is order-sensitive — whichever `include_router` runs last wins for overlapping paths. As coded, `global_search_router` is mounted during `create_app()` **before** `module_loader.load_all()` runs inside `on_event("startup")` so the module loader entries win. Name collision is still a maintenance trap.

### A8 — `audit_router` default None for `CurrentUserId` (LOW)
`backend/app/core/audit_router.py:37`:
```python
_user_id: CurrentUserId = None,  # type: ignore[assignment]
```
`CurrentUserId` is an `Annotated[str, Depends(get_current_user_id)]`. Assigning `= None` as the default cannot actually bypass the dependency (FastAPI still resolves it), but the `type: ignore` suggests the author was fighting the type system. Worth verifying that `get_current_user_id` raises (not returns None) when no valid JWT is present.

### A9 — Duplicate `/auth/*` endpoints in `users` (LOW / cosmetic)
`backend/app/modules/users/router.py` registers both `/auth/login/` and `/auth/login` (the latter with `include_in_schema=False`) for `register`, `login`, `refresh`. This inflates the raw `@router.post` count by 3 but produces only 3 unique routes. Same for the no-trailing-slash/with-trailing-slash pattern elsewhere — `FastAPI(redirect_slashes=False)` is set in `main.py`, so both forms must be registered explicitly if the frontend sometimes omits the trailing slash. Works, but noise in the OpenAPI schema.

### A10 — Many manifests declare `depends` on modules whose names collide with other declarations (INFO)
E.g. `full_evm.depends=["oe_finance"]`, `rfq_bidding.depends=["oe_procurement"]`, `erp_chat.depends=["oe_ai"]`. All present, but some transitive chains are deep (`rfq_bidding -> procurement -> contacts -> users`) which slows cold-start and means a single broken manifest can brick the whole load. Consider a `startup --skip-broken` flag.

---

## Auth surface summary

- Routers using auth dependencies (`CurrentUserId` / `RequirePermission` / `get_current_user_id`): **50 of 59 module routers** + **5 of 6 core routers**.
- Routers with **no** auth at all: `architecture_map`, `us_pack`, `uk_pack`, `dach_pack`, `russia_pack`, `asia_pac_pack`, `india_pack`, `middle_east_pack`, `latam_pack` (all public by design; 9 routers, 14 endpoints total).
- Routers with **partial** auth (mix of public + protected): `users` (auth bootstrap), `opencde_api` (OpenCDE discovery), core `module_router` (admin-only writes, public reads).

---

## Final numbers

- **Total modules with `manifest.py`**: 60
- **Total modules with a working `router.py`**: 59 (`cad` missing)
- **Total router files inventoried**: 59 + 6 core = 65
- **Total `@router.(method)` decorators**: 736 (modules) + 12 (core) = **748**
- **Total routed endpoints** (incl. inline `main.py`): **762**
- **Alias mounts**: 4
- **Middleware in chain**: 6 (CORS, APIVersion, DDCFingerprint, SecurityHeaders, SlowRequestLogger, AcceptLanguage)
- **Anomalies identified**: 10

