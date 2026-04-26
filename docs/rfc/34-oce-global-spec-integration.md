# RFC 34 — OCE_TECH_SPEC_GLOBAL integration plan

**Status:** draft → ready for review
**Date:** 2026-04-25
**Author:** Claude Opus + Artem
**Related:**
- `OCE_TECH_SPEC_GLOBAL.md` (1941 lines, six modules: CDE, BIM Diff, Validation EAC, Classification, QTO, AI Copilot)
- `OCE_EAC_Implementation_Spec_v2_International.md` (1748 lines, six sections: engine, aliases, block editor, Excel import, composition, 4D)
- ADR 002 — No IfcOpenShell, DDC canonical format is single source of truth
- RFC 33 — CDE module deep audit (continues)
- **RFC 35 — EAC v2 platform implementation (deep plan for §3+§4 of this RFC plus a new §10 Wave 6 4D module)**

> **2026-04-25 update.** A second spec — the EAC v2 international implementation spec — has landed. It replaces this RFC's separate Wave 3 (Validation+Classification) and Wave 4 (QTO) narrative with **one unified EAC engine + four output modes** (aggregate / boolean / clash / issue), and adds a new Wave 6 (4D module). All deep schema, ticket breakdown, and TDD/Playwright contracts for those waves now live in **RFC 35**. This RFC remains the umbrella; §7, §8, and §11 below are updated to reflect the new shape.

## 1. Context

`OCE_TECH_SPEC_GLOBAL.md` is a 1941-line specification of six fundamental modules that constitute the technical core of OpenConstructionERP. About 60–70 % of its surface already exists in the codebase in some form; the remaining 30–40 % is either missing entirely or implemented at a much shallower level than the spec demands.

This RFC is the **strategic integration plan** that locks decisions, names the gaps, sequences the work into waves, and defines the per-ticket acceptance criteria. Per-module RFCs (35–40) are intentionally NOT created here — each module gets its own RFC at the start of its wave, with the deep schema and algorithm details. RFC 34 is the umbrella.

### What the user locked in (2026-04-25)

1. **DDC `cad2data` only.** No IfcOpenShell, no `web-ifc`, no `ifctester` runtime parsing — see ADR 002.
2. **Stack: pick what's best for fast iteration.** I'm choosing Celery (already in `CLAUDE.md` stack, mature, integrates with Redis we already need), pgvector (single PG dep, no separate Qdrant), `bge-m3` for multilingual embeddings (open-source, multilingual, dense+sparse modes — perfect for hybrid search).
3. **TDD + browser-verified.** Every ticket = unit/integration tests written **first**, then implementation, then Playwright E2E with screenshot. No ticket is "done" without a screenshot in `frontend/test-results/`.

### What the gap audit found

Existing modules vs. spec coverage (verified via two parallel codebase audits):

| Spec module | Existing surface | Coverage | Critical gaps |
|---|---|---|---|
| 0. Cross-cutting | `core/storage.py`, `core/events.py`, `core/cde_states.py` | 70 % | **No async job runner.** Multi-tenant RLS not enforced. |
| 1. CDE (ISO 19650) | `cde/`, `opencde_api/`, `features/cde/` | 75 % | DAG version edges, multipart upload, naming validator, 50-format extractor registry, partitioned audit log. |
| 2. BIM Diff | `bim_hub/BIMModelDiff` (table only) | **25 %** | **No engine.** No BCF/SARIF export. No diff UI. No requirements-impact analysis. |
| 3. Validation EAC | `validation/`, `compliance_ai/`, `features/validation/` | 60 % | EAC tuple formalization, IDS XML round-trip, computed constraints with safe-eval, SARIF export. |
| 4. Classification | embedded in `validation/`, `boq/`, `catalog/` | **40 %** | No formal `classification/` module. No multi-system registry. No ML auto-classify. |
| 5. QTO + BoQ formats | `boq/`, `takeoff/`, `dwg_takeoff/`, three frontend features | 70 % | Nine locale adapters (GAEB DA XML 3.3, AIA G702/G703, RICS NRM2, …), progress billing, variation tracking from BIM diff. |
| 6. AI Copilot | `ai/`, `cost_match/`, `erp_chat/`, `features/erp-chat/` | 65 % | Hybrid search (sparse+dense+RRF+rerank), citation post-validation, semantic chunking, on-prem LLM provider abstraction. |
| **EAC v2 Platform** (added 2026-04-25, deep audit in RFC 35 §2) | `core/validation/engine.py` + `validation/` + `compliance_ai/` skeleton + `bim_requirements/parsers/ids_parser.py` + `schedule/` (skeleton) | **~25 %** | EAC engine + JSON Schema + 4 output modes greenfield; aliases greenfield; block editor greenfield; Excel-DSL import greenfield; classifier composition greenfield; 4D simulation + PWA greenfield. |

## 2. Locked decisions (cannot be reopened during implementation)

| # | Decision | Rationale |
|---|---|---|
| L1 | **DDC `cad2data`** is the single CAD/BIM parser. All six modules read its canonical Parquet/JSON. | ADR 002. User-confirmed 2026-04-25. |
| L2 | **Celery + Redis** is the async job runner. `JobRun` table records all background work. | Already in `CLAUDE.md` stack table. Mature. Integrates with existing Redis. |
| L3 | **pgvector** is the vector store. No Qdrant in core; Qdrant remains as an optional enterprise plugin. | User emphasis on pgvector. One DB to operate. PostgreSQL 16 already required. |
| L4 | **`bge-m3`** is the embedding model (1024-dim dense + sparse). Loaded via `sentence-transformers` or via `infinity` server (CPU-tolerant). | Multilingual (50+ langs), open-source, dense + sparse out of the box, retrieval-tuned, runs on CPU for on-prem. |
| L5 | **Tests first, every ticket.** Unit (pytest) + integration (httpx + real PG/Redis) + E2E (Playwright) + visual screenshot. No screenshot, no merge. | User mandate 2026-04-25. |
| L6 | **i18n from day one** for every new user-facing string. 21 locales already supported by the stack. | `CLAUDE.md` §i18n + spec §0.6. |
| L7 | **One PR = one logical change.** Wave names map to GitHub project columns; tickets map to PRs. | `CLAUDE.md` + spec §"Финальные принципы". |
| L8 | **Schema migrations are reversible.** Each ticket = one Alembic migration with `downgrade()` that survives `alembic downgrade base && alembic upgrade head` round-trip. | Spec §0.3, project convention. |
| L9 | **Multi-tenancy via RLS.** PostgreSQL Row-Level Security policies are enabled for every new table that has `tenant_id`. | Spec §0.7 #2. Currently `tenant_id` columns exist but RLS is off. |
| L10 | **Observability built-in.** Every new endpoint emits an OpenTelemetry span; every Celery task emits a `JobRun` row with structured outcome. | Spec §"Финальные принципы" #8. |
| L11 | **One EAC engine, four output modes.** No parallel engines for QTO, validation, clash, or issue. | EAC v2 spec §0.1; RFC 35 L11. |
| L12 | **Rule definition is JSONB (`EacRuleDefinition` v2.0)** with a stable JSON Schema; code parses, never branches on shape. | RFC 35 L12. |
| L13 | **DuckDB over canonical Parquet** is the rule-execution kernel — selectors and predicates compile to one query per rule. | RFC 35 L13; reuses existing `dashboards/duckdb_pool.py`. |
| L14 | **`simpleeval` with whitelisted functions** is the formula evaluator — no `eval()`, no Python compile. | RFC 35 L14. |
| L15 | **`/api/v2/eac/*` is the canonical surface;** `/api/v1/validation/*` and `/api/v1/boq/qto/*` proxy to v2 for ≥6 months before sunset. | RFC 35 L15; spec §0.2. |

## 3. Stack additions (new dependencies)

| Package | Purpose | Justification |
|---|---|---|
| `celery[redis]` | Async job runner | L2. |
| `dramatiq` candidate is rejected — Celery has more battle-tested integrations with our other PaaS code. |
| `bge-m3` model + `sentence-transformers` (or `infinity` server) | Multilingual dense+sparse embeddings | L4. |
| `simpleeval` | Safe expression evaluation for computed validation constraints | Spec §3.6 — never `eval()`. |
| `pyclamd` (optional, gated by env) | Antivirus scan on uploads | Spec §1.2 #10. |
| `python-magic` | Magic-byte validation for upload MIME guarding | Spec §1.10 #5. |
| `lxml` (probably already present) | IDS XML round-trip, GAEB DA XML, BCF XML | Spec §3.8, §5.8. |
| `openpyxl` (already present) | GAEB / Excel BoQ export | Spec §5.8. |
| `pint` (already present) | Unit normalization in QTO + validation | Spec §0.6, §3.10 #7, §5.4. |
| `pdfplumber` or extension of existing `pymupdf` | Document-ingestion text extraction | Spec §6.4. |

**Removed / not adopted** (despite spec recommendation):
- `ifcopenshell`, `ifctester`, `web-ifc` — banned by ADR 002.
- `qdrant-client` — replaced by pgvector per L3.
- `dramatiq`, `arq` — replaced by Celery per L2.

## 4. Cross-cutting infrastructure (Wave 0, 3 weeks)

This is **the prerequisite** for everything in Waves 1–5. Nothing else can proceed until Wave 0 is green.

### W0.1 — Celery + Redis async job runner

- **Files**: `backend/app/core/jobs.py` (Celery app factory), `backend/app/core/job_run.py` (`JobRun` SQLAlchemy model), `backend/app/modules/jobs/router.py` (status endpoints), `docker-compose.yml` (add `worker` service).
- **Schema**: `oe_job_run` (id UUIDv7, tenant_id, kind, status, progress_percent, result_jsonb, error_jsonb, started_at, completed_at, retry_count, idempotency_key UNIQUE).
- **Tests written first**:
  - `tests/unit/test_jobs_idempotency.py` — same idempotency_key returns existing JobRun, never duplicates.
  - `tests/unit/test_jobs_progress.py` — `progress_callback(percent, message)` mutates `JobRun` in atomic update.
  - `tests/integration/test_jobs_celery_redis.py` — real Redis, real Celery worker (testcontainers), full happy-path + DLQ.
  - `tests/e2e/jobs-status.spec.ts` (Playwright) — submit job via API, poll status, screenshot the loading→complete UI.
- **Acceptance**: `make dev` brings up `worker` container; submitting a no-op task returns a `job_run_id`; polling shows progress 0→100; screenshot saved at `frontend/test-results/jobs-happy.png`.

### W0.2 — DDC adapter extension for spec parity

- **Files**: `backend/app/modules/bim_hub/ddc_extras.py` — new helpers that DDC's existing output already supports but isn't exposed: `geometry_signature(element) -> SignatureV1` (mesh_sha256, vertex_count, volume, surface_area, centroid, bbox), `property_set_diff(left, right) -> list[PropertyChange]`, `material_signature(element) -> str`.
- **Tests**: golden samples — one DWG, one RVT-converted IFC, one DGN canonical Parquet — assert per-element signatures are stable across re-conversions (idempotency) and tolerant to 0.1 mm rounding (no false-positive geometry diffs).
- **Acceptance**: `pytest backend/tests/unit/test_ddc_extras.py -v` passes; signature is stable between two conversions of the same source file (modulo `created_at`).

### W0.3 — pgvector standardization

- **Files**: Alembic migration to ensure `CREATE EXTENSION IF NOT EXISTS vector`. New `backend/app/core/vector.py` with a thin `VectorStore` Protocol that has two implementations: `PgVectorStore` (default), `QdrantVectorStore` (optional, gated). All existing call sites that import `qdrant_client` directly are routed through `VectorStore`.
- **Tests**: `tests/unit/test_vector_store.py` verifies the same suite passes for both backends (parametrized fixture); `tests/integration/test_pgvector_search.py` runs against real PG with the extension.
- **Acceptance**: `python -c "from app.core.vector import get_vector_store; print(get_vector_store().__class__.__name__)"` prints `PgVectorStore` by default; switching `OE_VECTOR_BACKEND=qdrant` and rerunning prints `QdrantVectorStore`.

### W0.4 — Multi-tenant RLS hardening

- **Files**: Alembic migration to enable RLS + create policies on all tables with `tenant_id`. App-level: `core/db.py` sets `app.current_tenant_id` on every connection from the request middleware (`set_config('app.current_tenant_id', :tenant, true)`).
- **Tests**: `tests/integration/test_rls_isolation.py` — open two sessions for different tenants, verify each can only see its own rows; raw SQL bypass (no `set_config`) fails by default.
- **Acceptance**: integration suite proves cross-tenant data leakage is impossible at the DB level. Adversarial test: a request with `tenant_id=A` that constructs a query for a `bim_element.id` known to belong to `tenant=B` returns 404, not the row.

### W0.5 — Storage abstraction completion

- **Files**: `core/storage.py` already exists; extend with `multipart_upload()` per spec §1.7 + `presigned_url(method='PUT')` for direct browser-to-S3 uploads of files >100 MB.
- **Tests**: golden 200 MB synthetic file uploaded in 5 MB chunks (concurrency 4), SHA-256 verified end-to-end. Local backend uses tempdir + `os.rename` to simulate atomic finalize.
- **Acceptance**: 1 GB upload finishes in <60 s on dev box; presigned URL works against MinIO.

### W0.6 — i18n message catalog wiring (validation messages, AI prompts)

- **Files**: extend existing `backend/app/modules/{module}/messages/{en,de,ru,es,fr}.json` to cover the new modules. New strings during implementation MUST land in catalogs in all five locales (the rest auto-resolve through fallback chains).
- **Acceptance**: CI gate — adding a `t("key")` call without a corresponding entry in `en.json` fails the linter.

**Wave 0 deliverable:** all five sub-tickets green, `make test-backend` passes, `make e2e` passes (jobs-happy, rls-isolation, vector-search, multipart-upload screenshots in `frontend/test-results/`).

## 5. Wave 1 — CDE complete (4 weeks)

Spec Module 1 is 75 % done. Wave 1 closes the gaps to ISO 19650-2 conformance.

### W1.1 — DAG version graph

- **Schema**: new `cde_version_edge(parent_version_id, child_version_id, edge_type)` table where `edge_type ∈ {'revision','branch','merge'}`. Cycle detection via recursive CTE.
- **Tests first**:
  - `tests/unit/test_version_dag.py` — adding edge that creates cycle raises `CycleDetected`; `ancestors_of(v)` returns correct set on a hand-built fixture (linear, branched, merged shapes).
  - `tests/integration/test_version_branch_merge.py` — full branch → diverge → merge round-trip.
- **Acceptance**: REST `GET /v1/cde/files/{id}/versions/graph` returns DAG; UI renders timeline with branches.
- **Visual**: `frontend/test-results/cde-version-dag.png`.

### W1.2 — Multipart upload pipeline (frontend + backend)

- **Spec ref**: §1.7.
- **Files**: `cde/router.py` `+` `upload-init`, `upload-part` (presigned URL hand-off), `upload-complete` (SHA-256 verification, `cde_file_version` row creation, side-jobs trigger).
- **Frontend**: `features/cde/UploadDialog.tsx` — chunked upload, progress bar per chunk + overall.
- **Tests first**:
  - `tests/integration/test_multipart_upload.py` — 200 MB synthetic file uploaded in chunks, integrity verified.
  - `tests/e2e/cde-upload-large.spec.ts` (Playwright) — drag-drop a 50 MB fixture, watch progress bar, screenshot at 0 %, 50 %, 100 %.
- **Acceptance**: 1 GB uploads work end-to-end; resumable across browser refresh (multipart session TTL 24 h).

### W1.3 — Naming validator (ISO 19650-2 §10.2.4)

- **Files**: `cde/naming_validator.py` — DSL for project/org templates (regex-based + field whitelists). Default ISO 19650-2 PAS-1192 template `{Project}-{Originator}-{Volume}-{Level}-{Type}-{Discipline}-{Number}`.
- **Tests first**: parameterised over 30 fixture filenames (valid + invalid in each field); auto-suggest works on near-miss filenames.
- **Acceptance**: bulk import of a folder with mixed naming → report of N valid, M invalid, K auto-corrected suggestions.
- **Visual**: `cde-naming-validator.png` (validation panel with traffic-light per file).

### W1.4 — Format extractor registry (50 formats)

- **Files**: `cde/extractors/registry.py` (Protocol-based registry); per-format adapters under `cde/extractors/{pdf,dwg,docx,xlsx,e57,ifc_canonical,…}.py`. Each adapter declares `supported_mime_types` and returns a JSON-serialisable metadata dict.
- **IFC adapter goes through DDC**, not IfcOpenShell — see ADR 002.
- **Tests first**: golden sample per format; metadata extraction is byte-stable.
- **Acceptance**: uploading a DWG, IFC, RVT, PDF, DOCX, XLSX, E57 each yields a populated `metadata_jsonb` field on the `cde_file_version` row.
- **Visual**: `cde-extractor-results.png`.

### W1.5 — Suitability codes lookup + state-transition audit log

- **Closes** RFC 33 R2 items #1 and #4.
- **Schema**: `cde_state_transition` table; suitability code lookup table populated per ISO 19650 Annex A.
- **Tests first**: every state transition emits exactly one `cde_state_transition` row + one event_bus event; UI dropdown for suitability shows codes filtered by current state.
- **Visual**: `cde-state-transition-history.png`.

### W1.6 — Lock & checkout

- **Schema**: `cde_file.locked_by`, `locked_at`, `lock_expires_at`. Optimistic locking via `version` column.
- **Tests first**: two-session concurrency — first lock wins, second gets HTTP 409. Lock auto-expires at TTL.
- **Acceptance**: editing an XLSX in the UI claims a lock; another user sees a lock indicator.

**Wave 1 deliverable:** CDE passes the spec's acceptance criterion: «загружается файл → автоматически создаётся версия с правильным state → можно перевести в SHARED и PUBLISHED → audit log пишет всё → preview работает для PDF и IFC».

## 6. Wave 2 — BIM Diff Engine (5 weeks)

Largest gap (25 % → 100 %). Pure greenfield engine on top of canonical format.

### W2.1 — Diff engine on canonical Parquet

- **Files**: `backend/app/modules/bim_hub/diff/engine.py`, `bim_hub/diff/categorize.py`, `bim_hub/diff/signatures.py` (uses W0.2 helpers).
- **Algorithm** (DDC-canonical version of spec §2.3):
  1. Load both versions' canonical Parquet via DuckDB.
  2. Build `stable_id` index (DDC's persistent element identity, replaces `GlobalId`).
  3. Set difference: `removed`, `added`, `common`.
  4. For each `common` element, compute property diff (JSONB delta), geometry signature compare (mesh_sha256, then bbox/centroid distance with 1 mm tolerance), classification compare, material compare, containment compare.
  5. Emit categorized `BIMModelDiffChange` rows.
- **Performance budget**: 1 M elements diffed in ≤ 5 min on 16-core. Parallelize per-element compare via Celery group of 100 batches.
- **Tests first**:
  - `tests/unit/test_diff_categorize.py` — 14 hand-crafted scenarios (one per change category) on synthetic canonical entities.
  - `tests/integration/test_diff_perf_50k.py` — 50 K elements complete in ≤ 30 s.
  - `tests/integration/test_diff_perf_1m.py` — runs nightly only; budget is 5 min.

### W2.2 — BCF 2.1 / 3.0 exporter

- **Files**: `bim_hub/diff/exporters/bcf.py`. Use `bcf-py` or hand-rolled XML — no IfcOpenShell dependency.
- **Output**: ZIP with `bcf.version`, per-topic folders with `markup.bcf`, `viewpoint.bcfv`, `snapshot.png`.
- **Snapshot**: rendered headless via the existing Three.js viewer (Puppeteer/Playwright). One topic = one screenshot of the changed element.
- **Tests first**: round-trip — generated BCF parses back into a known set of topics; opens cleanly in BIMcollab Zoom (manual smoke once, automated XSD validation always).
- **Visual**: `bim-diff-bcf-export.png` (UI flow + downloaded file size badge).

### W2.3 — SARIF + Excel + PDF + JSON exporters

- **Files**: `bim_hub/diff/exporters/{sarif,xlsx,pdf,json}.py`. SARIF is mandatory for CI/CD integration (spec §2.7).
- **Tests first**: each exporter has a golden output (snapshot test). SARIF validates against `sarif-2.1.0.json` schema.

### W2.4 — Requirements-impact analysis

- **Spec ref**: §2.3 step 5.
- **Files**: `bim_hub/diff/requirements_impact.py`. Hooks into `validation/` module — runs validation on `target_version` filtered to changed elements only, compares against pre-diff results.
- **Tests first**: synthetic diff where one wall's fire-rating drops below threshold → impact row with `impact_type='regression'`; opposite case → `improvement`.

### W2.5 — Side-by-side diff viewer (frontend)

- **Files**: `frontend/src/features/bim/DiffViewerPage.tsx`, `frontend/src/shared/ui/BIMViewer/SyncedCameras.tsx`.
- Two `<BIMViewer>` instances, camera sync via shared Zustand store. Colored overlay per spec §2.8 palette.
- Side panel: filterable change list, click → both viewers fly to element + highlight.
- **Tests first**:
  - `tests/e2e/bim-diff-side-by-side.spec.ts` — load fixture diff, screenshot at default zoom, after applying "PropertyModified" filter, after clicking a change row.
- **Visual**: `bim-diff-overview.png`, `bim-diff-property-filter.png`, `bim-diff-element-focus.png`.

### W2.6 — Variation propagation to QTO

- Subscribes to `ModelDiffCompleted` event, marks affected `boq_item` rows as `requires_review` (Wave 4 consumes; we wire the event now to avoid future migration churn).

**Wave 2 deliverable:** spec acceptance: «загружаются две версии IFC → diff за 5 минут → отчёт типизированный → BCF открывается в third-party». For us s/IFC/canonical/g.

## 7. Wave 3 — Validation EAC + Classification (5 weeks) — **superseded by RFC 35 (Wave EAC-1, EAC-2, EAC-3, EAC-5, EAC-7)**

> The sub-tickets W3.1–W3.6 below are kept for historical traceability. Their actual deep plan now lives in RFC 35 §5 (engine), §6 (aliases), §7 (block editor + IDS), §9 (composition) and §11 (migration). The RFC 35 layout is the source of truth; do not start any of the W3.* tickets directly — open the corresponding EAC-* ticket from RFC 35 instead.

### W3.1 — EAC schema migration

- **Spec ref**: §3.4.
- **Schema**: rename existing `validation_rule` columns to fit the EAC tuple (`entity_class`, `attribute_path`, `constraint_operator`, `constraint_value_jsonb`), add `facets_jsonb` for compound applicability, add `name_locale_jsonb` for i18n.
- **Tests first**: existing rule fixtures (DIN 276, GAEB, NRM, MasterFormat) migrate without behaviour change. Property test (Hypothesis): every constraint operator is covered by at least one rule and at least one passing/failing scenario.

### W3.2 — IDS XML round-trip

- **Files**: `validation/ids/{importer,exporter}.py`. Schema-driven: parse `IDS-1.0.xsd` once, generate dataclasses, map to/from EAC rules. **No `ifctester` runtime parsing of IFC** — only the IDS spec format itself.
- **Tests first**: import 5 published IDS files (buildingSMART samples), export back, byte-compare canonicalised output. Lossless property check.
- **Acceptance**: «импортируется IDS-файл → запускается валидация → результат корректен → экспорт в SARIF → SARIF загружается в standard CI/CD platforms».

### W3.3 — Computed constraints + safe expression evaluator

- **Files**: `validation/computed.py` using `simpleeval` with a strict whitelist (`length`, `max`, `min`, `abs`, `re.search`).
- **Tests first**: 30 expressions covering all operators, expected values, error paths (cyclic refs, syntax errors, undefined vars).

### W3.4 — Classification module (new)

- **Files**: new `backend/app/modules/classification/` (manifest, models, schemas, router, service, repository). New tables `classification_system`, `classification_code`, `cost_classification_bridge`, `element_classification`, `classification_rule`.
- **Pre-loaded data**: Uniformat II 2015, OmniClass headers, MasterFormat headers (Alembic data migrations).
- **Tests first**: import each classifier, assert tree integrity (parent codes resolve, depth correct), bilingual lookups work.

### W3.5 — Rule-based + ML auto-classify

- **Files**: `classification/auto_classify.py`. Rule-based first (uses Module 3 engine — DRY). ML pass via pgvector: each classification code has a 1024-dim `bge-m3` embedding; element representation is `entity_class + name + materials + properties` embedding; top-K nearest by cosine.
- **Confidence policy** per spec §4.7: ≥ 0.85 auto-apply, 0.65–0.85 suggest, < 0.65 skip.
- **Tests first**: golden samples — 50 elements with known correct codes. Recall@1 ≥ 0.80, recall@3 ≥ 0.95 for the auto-applied subset.

### W3.6 — Validation + Classification UI

- **Files**: extend `features/validation/ValidationPage.tsx` (rule editor with EAC fields), new `features/classification/AutoClassifyPage.tsx` (interactive grid with accept/reject/edit per element).
- **Tests first**:
  - `tests/e2e/validation-rule-editor.spec.ts` — author a rule via UI, save, verify row in DB, screenshot.
  - `tests/e2e/auto-classify.spec.ts` — run job on fixture, accept high-confidence, manually fix one, screenshot at each stage.
- **Visual**: `validation-rule-editor.png`, `classification-grid.png`.

**Wave 3 deliverable:** spec acceptance for Modules 3 and 4.

## 8. Wave 4 — QTO + BoQ formats (4 weeks) — **partially superseded by RFC 35 (Wave EAC-1 aggregate mode + EAC-5 composition)**

> The QTO engine itself becomes the `aggregate` output mode of the unified EAC engine (RFC 35 §5). What stays in Wave 4 below is **only the locale-export layer** (W4.2 — GAEB DA XML 3.3, AIA G703, RICS NRM2, etc.) and **progress billing** (W4.3, W4.5). Variation tracking (W4.4) is wired to `ModelDiffCompleted` from Wave 2 and consumes EAC `aggregate` runs. W4.1 (`QuantityExtractionRule` schema) is replaced by `EacRule` with `output_mode='aggregate'`.

### W4.1 — QuantityExtractionRule schema + engine

- **Spec ref**: §5.6, §5.7.
- **Schema**: `quantity_extraction_rule`, `boq_item_quantity_source` (already partially exists in `boq/`).
- **Engine** (DDC-canonical): per rule, query DuckDB on canonical Parquet for matching elements, sum the requested quantity (from `BIMElement.quantities` JSONB or computed from geometry signature), apply unit conversion via `pint`.
- **Tests first**: per quantity_type (length/area/volume/count/weight) — golden fixture, expected sum. Edge: mixed units (m + ft) normalise correctly.

### W4.2 — Locale adapters (9)

- **Files**: `boq/exporters/{gaeb_d83,gaeb_d81,aia_g703,rics_nrm2,kc_2,kc_3,stabu,dqe,fidic}.py`. Each adapter has matching `importers/{format}.py`. Round-trip mandatory.
- **Tests first**: per format — golden BoQ → export → import → byte-compare normalised output.

### W4.3 — Progress billing schema + workflow

- **Schema**: `boq_progress_period`, `boq_progress_entry`. Linked to `inspections` and `field_reports` for photo evidence.
- **Tests first**: full period lifecycle — create → fill entries → approve → export PDF + signed-XML → e-signature attached.

### W4.4 — Variation tracking from BIM diff

- Already wired in W2.6; Wave 4 implements consumer: receives `ModelDiffCompleted`, computes per-item delta, emits `BoQVariation` row when |delta| > project threshold (default 5 %).
- **Tests first**: integration — diff that adds 3 walls → variation rows for the 3 affected BoQ items.
- **Visual**: `boq-variation-from-diff.png`.

### W4.5 — Frontend — progress billing UI

- **Files**: `frontend/src/features/boq/ProgressBillingPage.tsx`.
- **Tests first**: E2E — open period, edit entries, approve → PDF download.

**Wave 4 deliverable:** BoQ exports validate against three industry XSDs (GAEB DA XML 3.3, AIA, RICS); progress billing produces signed PDFs.

## 9. Wave 5 — AI Copilot RAG (5 weeks)

### W5.1 — Document ingestion pipeline

- **Files**: `backend/app/modules/ai/ingestion/{pipeline,extractors,chunker}.py`. Subscribes to `FileUploaded` event from CDE. Per-format extractors via the W1.4 registry.
- **Chunking**: semantic, header-aware, 500 tokens with 50-token overlap. Each chunk stamped with `tenant_id`, `project_id`, `file_version_id`, `iso_state`, `language`.
- **Tests first**: golden PDFs in en/de/ru/es/zh — chunk count stable, language detection correct, header context preserved.

### W5.2 — Multilingual embeddings (`bge-m3`)

- **Files**: `ai/embeddings/{bge_m3,sparse}.py`. Dense via `sentence-transformers` (CPU-tolerant). Sparse via the same model's sparse mode.
- **Tests first**: encode 100 sentences across 10 languages, verify cosine similarity matches expected pairs (translations of the same sentence are top-1 nearest).

### W5.3 — Hybrid search with RRF

- **Files**: `ai/search/hybrid.py`. Dense via pgvector cosine, sparse via PostgreSQL `tsvector` GIN index, fused via Reciprocal Rank Fusion (`k=60`).
- **Tests first**: 50 golden Q&A pairs; recall@5 must improve over dense-only baseline by ≥ 10 %.

### W5.4 — Cross-encoder reranker

- **Files**: `ai/search/rerank.py`. Use `bge-reranker-v2-m3` (also multilingual, also open).
- **Tests first**: nDCG@10 improves over RRF-only by ≥ 5 % on the golden set.

### W5.5 — RAG conversation with citation post-validation

- **Files**: `ai/rag/conversation.py`, `ai/rag/citations.py`. System prompt requires inline `[ref:chunk_id]`. Post-generation: regex parses citations, validates each `chunk_id` exists in the retrieved context. Hallucinated citations stripped + warning logged.
- **Tests first**: adversarial test — model fabricates a chunk_id → post-validation strips it; happy path — every citation resolves to a real chunk.

### W5.6 — LLM provider abstraction

- **Files**: `ai/llm/{anthropic,openai,ollama,vllm}.py` + `ai/llm/router.py`. Switch via `OE_LLM_PROVIDER` env. Default `anthropic` for cloud, `ollama` for on-prem.
- **Tests first**: contract test runs against a stub HTTP server that mimics each provider's streaming SSE protocol.

### W5.7 — Auto-tasks

- **Issue auto-classification** — few-shot prompt, calibrated confidence.
- **Diff narrative** — subscribes to `ModelDiffCompleted`, generates human-readable summary.
- **Requirements extraction from EIR PDF** — proposes `ValidationRule` rows with `requires_review=true`, never auto-applies.
- **Tests first**: per task — golden input, expected output, regression-tested at every release (eval framework, spec §6.12).

### W5.8 — Frontend — copilot UI enhancement

- **Files**: extend existing `features/erp-chat/full-page/ChatFullPage.tsx`. Add citation pills (click → opens source document at the cited page).
- **Visual**: `copilot-citation-click.png`.

**Wave 5 deliverable:** spec acceptance: «загружается EIR PDF → задаётся вопрос на любом supported языке → ответ с цитированием 3+ источников → клик на цитату ведёт на нужную страницу».

## 9b. Wave 6 — 4D module (5 weeks; new — added by EAC v2 spec §6, deep plan in RFC 35 §10)

> Source-of-truth for sub-tickets: RFC 35 §10. Summary here for the dependency-graph view only.

- **EAC-6.1** PMXML / MSPDI / MS Project / CSV import.
- **EAC-6.2** `EacScheduleLink` schema — task ↔ EAC predicate.
- **EAC-6.3** AI auto-link (uses RFC 34 W5.6 LLM provider abstraction).
- **EAC-6.4** Simulation engine + 3D viewer integration + MP4/GIF export.
- **EAC-6.5** S-curve / SPI / CPI dashboard + EAC/ETC forecasting.
- **EAC-6.6** Mobile PWA — foreman view, offline queue, geolocation, photo evidence.

**Wave 6 deliverable:** spec §6 AC-6.1..AC-6.8 green; mobile PWA installs to home screen on iOS and Android; simulation runs at ≥30 fps on 100 k-element model.

## 10. Verification gates (every ticket)

Each ticket above is closed only when **all** of these are green:

1. **Unit tests** in `backend/tests/unit/` — written first, then code.
2. **Integration tests** in `backend/tests/integration/` — real PG (testcontainers), real Redis, real Celery worker. No mocks for infra.
3. **E2E test** in `frontend/e2e/` (Playwright) — full user flow.
4. **Visual screenshot** committed to `frontend/test-results/{ticket-slug}/{state}.png`. PR description includes thumbnails.
5. **OpenAPI** updated; auto-generated TypeScript client compiles with no manual edits.
6. **i18n** strings present in `en.json` + at least `de.json`, `ru.json`.
7. **Migration** is reversible: `alembic downgrade -1 && alembic upgrade head` round-trips with no data loss.
8. **Observability**: every endpoint emits OTel span; every Celery task records a `JobRun` row.
9. **CI gate**: `ruff check`, `mypy --strict` for new code, `pytest --cov=backend/app/modules/{module} --cov-fail-under=85`.
10. **Manual check**: open the feature in a browser locally, click through the golden path + at least two edge cases, capture screenshot. Compare with the Playwright snapshot.

## 11. Per-wave dependency graph

```
Wave 0 (foundation, RFC 34 §4)
   │
   ├─→ Wave 1 (CDE, RFC 34 §5)
   │     │
   │     ├─→ Wave 2 (BIM Diff, RFC 34 §6)
   │     │     │
   │     │     └─→ Wave 4 variation tracking (W4.4)
   │     │
   │     └─→ Wave 5.1 (ingestion subscribes to FileUploaded)
   │
   ├─→ Wave EAC (RFC 35 — supersedes Waves 3+4 engine layer)
   │     │
   │     ├─→ EAC-1 Engine ──┬─→ EAC-2 Aliases  (parallel)
   │     │                  ├─→ EAC-3 Block editor + IDS  (parallel)
   │     │                  ├─→ EAC-4 Excel import  (parallel)
   │     │                  ├─→ EAC-5 Composition  (after EAC-1+EAC-2)
   │     │                  └─→ EAC-6 4D module = Wave 6 (after EAC-1)
   │     │
   │     └─→ EAC-7 Migration v1→v2 (threaded)
   │
   ├─→ Wave 4 locale exporters (W4.2) + progress billing (W4.3, W4.5)
   │     └─→ depends on EAC-1 aggregate runs
   │
   └─→ Wave 5 (AI Copilot, RFC 34 §9) — uses W0.3 pgvector, W0.1 jobs
```

Wave 1 and Wave EAC can run in parallel after Wave 0 (different code paths). Wave 2 depends on Wave 1 (needs the version DAG). Wave 4 locale exporters depend on Wave EAC-1 (aggregate output). Wave 5 depends on Wave 0 only.

**Total calendar time** at a single-track pace: ~30 weeks (was 26; +5 for Wave 6 4D, –1 for collapsed engine layer in Wave EAC). Parallel-track (W1+EAC+W5 simultaneously after W0): ~18 weeks.

## 12. Risks + mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| DDC `cad2data` doesn't expose mesh-hash → Wave 2 blocked | Medium | High | W0.2 spike (1 day) verifies on real samples; if missing, escalate to DDC team for a small extension before Wave 2 starts. |
| `bge-m3` is too slow on CPU for on-prem deployments | Medium | Medium | Fallback: `multilingual-e5-large` (smaller). Worker pool can warm-cache embeddings. |
| GAEB DA XML 3.3 round-trip mismatch on edge cases | High | Medium | Use the official GAEB validator XSD as a fuzz seed; 100+ real-world fixtures from DACH partners. |
| Multi-tenant RLS regression breaks existing tenants | High | High | W0.4 staged: enable RLS in `audit-only` mode first; promote to `enforce` after one week of clean audit. |
| Playwright screenshot flakiness blocks merges | Medium | Medium | Visual snapshots only on stable widgets (no animations); `expect(page).toHaveScreenshot({maxDiffPixels: 100})` tolerance. |
| Spec drift — buildingSMART updates IDS spec mid-implementation | Low | Medium | Version-pin the IDS schema we target (`IDS-1.0`). Dedicated migration when next version lands. |

## 13. Out of scope (explicit)

- **Native Rust/C++ acceleration of any module.** Spec §"Финальные принципы" #1: "No premature optimization."
- **Air-gapped deployment automation.** On-prem mode (Wave 5) is supported via configuration; air-gapped install scripts are a separate RFC.
- **Mobile-first redesign.** Existing UIs are desktop-optimised; mobile will follow the existing PWA approach.
- **Multi-region GAEB extensions** (Austrian ÖNORM, Swiss SIA). Add as Wave 4.6+ after Germany is rock-solid.

## 14. Success metrics

After Wave 5 ships:

- BIM Diff: 1 M-element model diffs in ≤ 5 min (spec budget).
- Validation: importing a published IDS file and running it produces ≥ 95 % rule coverage match against the buildingSMART reference checker output.
- Classification: ≥ 80 % of elements auto-classified with confidence ≥ 0.85 across our 11 regional CWICR samples.
- QTO: BoQ exports validate against GAEB DA XML 3.3 XSD, AIA G703 schema, RICS NRM2 reference.
- AI Copilot: golden Q&A regression set scores ≥ 4.2 / 5 on LLM-as-judge eval; citation accuracy ≥ 95 %.

## 15. What I need to start

> The original 5 questions are kept below; questions 6–9 are added by the EAC v2 spec.

1. **Confirm wave priority** — strict L0→L5 sequential, or parallel after W0?
2. **Confirm new dependencies** — Celery (yes per L2), `bge-m3` (yes per L4), `simpleeval`, `python-magic`, `pyclamd` (gated). Any objections?
3. **Approve creating per-wave RFCs** — RFC 35 has now landed (EAC v2 platform — supersedes the planned RFC 38 + RFC 39 + adds Wave 6). Remaining: RFC 36 (Wave 0 foundation), RFC 37 (Wave 1 CDE close-out), RFC 38 (Wave 2 BIM Diff), RFC 40 (Wave 5 AI Copilot). Each lands at the start of its wave.
4. **Approve the verification-gate severity** — failing any of the 10 gates blocks merge. RFC 35 adds G11–G13 (schema parity, IDS round-trip parity, RLS-on-every-route).
5. **Decide demo path** — minimum-viable demo per spec §"Минимально жизнеспособная цепочка": Wave 0 + W2.1 + W2.2 = 9 weeks; full Wave 0 + Wave 2 = 11 weeks; **EAC-led demo path** (Wave 0 + EAC-1 + EAC-3 + EAC-4) = 11 weeks and shows the unified rule editor + Excel import end-to-end.
6. **Confirm EAC-1 replaces Wave 3 entirely** — formally retire RFC 34 W3.1–W3.6 in favor of RFC 35 EAC-1.1..EAC-1.7 (already documented in §7 above).
7. **Confirm Wave 6 (4D, +5 weeks)** — adds 4 weeks net to the parallel timeline (16 → 18 weeks). OK?
8. **Confirm `eac_issues` separate from `PunchItem`** — bridged via `linked_punch_item_id`, or merge into `PunchItem`?
9. **Confirm clash mode deferred to EAC-1.6 spike** — block editor hides clash option until spike completes.

Once confirmed, RFC 36 (Wave 0) opens and EAC-1.1 (schema migration) starts in parallel with W0.1 (Celery + Redis).
