# RFC 36 — EAC Deep Features, Wave 1 (Simplified)

**Status:** proposed
**Date:** 2026-04-26
**Owners:** Artem (DDC), Claude (impl)
**Supersedes (extends):** RFC 35 (EAC v2 Platform), ADR 002 (No IfcOpenShell)
**Target releases:** v2.6.0 → v2.6.5 (incremental, 3-4 weeks total)

## 1. Executive summary

This RFC plans Wave 1 of the EAC deep-features programme described in
`NextTasks 26042026.txt` (sections 2.x and 4.x). It is intentionally
**simplified**: only items that need no new heavy dependencies and no
geometry-pipeline extensions are in scope. Geometry-heavy items (2.3, 2.6,
2.7, 2.8) move to Wave 2 once DDC `cad2data` adapter is extended with the
required signals; AI-heavy items (4.1, 4.3, 4.5) move to Wave 2/3.

**In scope (Wave 1, 6 items):**

| # | Item | Closes tasks |
|---|---|---|
| W1.1 | EAC engine finalize (executor + API completeness) | #220, #221 |
| W1.2 | 4-tier validation cascade (batch + incremental, no real-time) | (new) |
| W1.3 | IDS round-trip (importer + exporter) | #224 |
| W1.4 | BCF export from validation results | (new) |
| W1.5 | Classification engine — rule-based tier only | (new) |
| W1.6 | AI Reasoning Receipts (capture + storage, no UI) | (new, partial 4.14) |

**Explicitly out of scope (Wave 2+):**
2.3 Geometric Quantity Engine, 2.4 vector + LLM tiers, 2.6 Spatial Boundary,
2.7 Visual Data Layer, 2.8 Cost Intelligence pipeline, 2.9 DAG pipelines,
4.1, 4.3, 4.5, 4.6, 4.8, 4.13.

## 2. Architectural constraints (binding)

These are non-negotiable for Wave 1 (and the rest of the programme):

1. **ADR-002 holds**: no `ifcopenshell`, no `pythonocc-core`, no `web-ifc`
   on the backend. Where the spec depends on B-Rep Open Cascade
   geometry, we extend DDC `cad2data` (which Artem owns) instead.
2. **DDC is in-house**: extension PRs land in the DDC repo synchronously
   with backend changes that consume new fields.
3. **BCF is allowed** as I/O format (issues / viewpoints / validation
   reports). Hand-rolled XML or AGPL-compatible library, no IfcOpenShell
   dependency. Decision pivoted 2026-04-26.
4. **pgvector, not Qdrant**: vector search lives in PostgreSQL; one
   database, zero operational overhead. Qdrant remains an optional
   enterprise extra (not in base).
5. **Single `RuleRegistry` truth**: validation rules and EAC rules are
   two views of one rule registry; no parallel rule engines.

## 3. Wave 1 detailed plan

### W1.1 — EAC engine finalize → v2.6.0

**Why:** RFC 35 designed the EAC v2 engine; tasks #199, #206, #207 built
the scaffolding. #220 (executor) is `in_progress`; #221 (API
completeness) is `pending`. Without finishing these the rest of Wave 1
can't be wired.

**Scope:**
1. Alembic migration `eac_v2_initial` — creates the 9 EAC tables defined
   in `app/modules/eac/models.py` (`eac_rulesets`, `eac_rules`,
   `eac_runs`, `eac_run_result_items`, `eac_global_variables`,
   `eac_rule_versions`, `eac_parameter_aliases`, `eac_alias_synonyms`,
   `eac_alias_snapshots`).
2. Wire `executor.py` from in-memory dry-run to persisted runs:
   `POST /api/v2/eac/runs` enqueues a Celery task, writes
   `EacRun.status='running'`, persists per-element results into
   `eac_run_result_items` (paginated read on
   `GET /runs/{id}/results?cursor=...`).
3. Spool runs > 100k results to Parquet on local/S3 storage; API returns
   a presigned URL for bulk download.
4. Idempotency keys on `POST /runs` — same `(ruleset_id, input_hash)`
   replays the prior run; no double execution.

**Tests:**
- `tests/integration/eac/test_run_persistence.py` — smoke: 1k-element
  fixture, run, paginate results, assert determinism (run twice → same
  output hash).
- `tests/integration/eac/test_run_spool.py` — 200k synthetic results,
  verify Parquet spool path.
- Migration round-trip: `alembic upgrade head; alembic downgrade -1;
  alembic upgrade head` leaves DB byte-identical (per RFC 35 EAC-7
  inspiration).

**Performance budget:** 1000 elements, 50 rules → end-to-end < 5 s. Fail
PR if exceeded.

### W1.2 — 4-tier validation cascade → v2.6.1

**Why:** Spec 2.5 requires Completeness / Consistency / Coverage /
Compliance categorisation. Today `RuleCategory` has different labels
(STRUCTURE, COMPLETENESS, CONSISTENCY, COMPLIANCE, QUALITY, CUSTOM).
We re-label to match the spec and add **batch** + **incremental** modes.

**Scope:**
1. `RuleCategory` enum migration: STRUCTURE → COMPLETENESS,
   QUALITY+COMPLIANCE → COMPLIANCE, add COVERAGE. Backwards-compat
   alias map at API boundary so v1 callers don't break.
2. `ValidationEngine.run(target, mode='batch'|'incremental', since=...)`
   — incremental mode pulls only `target` rows touched since `since`
   timestamp.
3. `ValidationContext.attribute_index` — precomputed map
   `{attribute_path: list[rule_id]}` so incremental mode runs only
   relevant rules.
4. New rules to fill Coverage (allowed-values list checks): one per
   classifier (DIN276, NRM, MasterFormat) — `*ValueInWhitelist` rule
   class. Source-of-truth lists in
   `data/classifications/{din276,nrm,masterformat}-allowed.json`.

**Tests:**
- `tests/unit/validation/test_categories.py` — every existing rule maps
  to exactly one of the 4 categories; no orphans.
- `tests/integration/validation/test_incremental_mode.py` — 1000-element
  BOQ, edit one row, incremental run touches < 5% of rules,
  full-equivalent results.
- Coverage rules: golden fixtures with allowed/disallowed values, expect
  pass/fail accordingly.

**Backwards-compat:** v1 API responses include both old and new category
field for one minor cycle (`category` = new, `legacy_category` = old).
Drop `legacy_category` in v2.7.

### W1.3 — IDS round-trip → v2.6.2

**Why:** Spec 2.5 deep insight #1 calls for two-way IDS bridge. RFC 35
designed it; #224 is the build task. IDS (buildingSMART, v1.0 approved
2024) is the open standard for declarative model requirements.

**Scope:**
1. `app/modules/eac/ids/exporter.py` — EAC ruleset → `.ids` XML
   conforming to `ids.xsd`. Maps EAC predicates onto IDS facets
   (entity, attribute, classification, property, material, partOf).
2. `app/modules/eac/ids/importer.py` — `.ids` → EAC rules. Operations
   that have no IDS facet equivalent (custom formulas) are flagged in
   import report as "imported as note, manual review needed".
3. Round-trip test: every IDS spec fixture from
   `IDS-tools/Documentation/Examples/` (buildingSMART repo) must pass
   `import → export → import → equal AST`.
4. CLI: `oce ids export <ruleset_id>` and `oce ids import <file.ids>`.
5. Docs: `docs/user-guide/ids-roundtrip.md` with one-screen quickstart.

**Tests:**
- `tests/golden/ids/` — 20+ IDS fixtures from buildingSMART, plus 3 of
  our own (DIN-276 minimal, NRM minimal, GAEB minimal).
- Round-trip fidelity: AST equality after import-export-import.
- Schema validation: every export validates against `ids.xsd` (lxml +
  `defusedxml.lxml`).

**Quality bar:** Both directions must work on the official buildingSMART
test corpus. Any failure that cannot be auto-fixed gets a documented
limitation in `docs/limitations.md`.

### W1.4 — BCF export from validation results → v2.6.3

**Why:** Spec 2.5 deep insight #2: validation results as BCF issues
makes them actionable in any BIM-coord tool (Solibri, BIMcollab,
Revizto). Now that BCF is allowed (decision 2026-04-26), this lands
naturally on top of W1.2.

**Scope:**
1. `app/modules/eac/bcf/exporter.py` — `ValidationReport` → `.bcfzip`
   (BCF 3.0). One BCF topic per failing rule result, viewpoint
   constructed from element bbox (centred camera, element highlighted).
2. Hand-rolled XML (BCF schema is small — `markup.bcf`,
   `viewpoint.bcfv`, `extensions.xml`); no IfcOpenShell dependency.
3. Endpoint: `GET /api/v1/validation/reports/{id}.bcf` streams a zip.
4. Round-trip not required for Wave 1 (export only); BCF import is
   v2.7+.

**Tests:**
- `tests/integration/bcf/test_bcf_export.py` — golden report → BCF zip,
  unzip, validate against BCF 3.0 schema, assert one topic per failing
  rule.
- Open exported BCF in Solibri Anywhere / BIMcollab ZOOM (manual smoke
  test, documented in `docs/qa/bcf-validation.md`).

### W1.5 — Classification engine, rule-based tier → v2.6.4

**Why:** Spec 2.4 has three tiers (rule-based, value partitioning, LLM
fallback). Wave 1 ships only the rule-based tier — it's deterministic,
free, and covers ~80% of cases. Vector search + LLM tiers are Wave 2.

**Scope:**
1. New module `app/modules/classification/`:
   - `models.py` — `ClassificationRule`, `ClassificationDefinition`
     tables.
   - `service.py` — runs YAML rule packs against EAC facts, writes
     classification back as `Pset_OCE_Cost.{system}_Code` properties.
   - `rules/dsl.py` — small DSL parser (paths
     `Pset_WallCommon.IsExternal AND material.layers contains
     "concrete"`). Reuses EAC `safe_eval.py` for expressions.
   - `bridge.py` — writes classification result as a property fact in
     EAC store (the "classification-to-property bridge", deep insight
     #1 from spec 2.4).
2. Built-in rule packs in `data/classification-packs/`:
   `revit-to-din276.yaml`, `revit-to-nrm.yaml`, `revit-to-masterformat.yaml`
   (port the static lookup from
   `cad/classification_mapper.py`).
3. Endpoint:
   `POST /api/v1/classification/runs?model_id=...&pack=revit-to-din276`.
4. UI surface (deferred): for now, only API + classification appears as
   a column in the Data Explorer. Full review queue UI is Wave 2.

**Tests:**
- `tests/unit/classification/test_dsl.py` — DSL parses and evaluates
  expressions correctly; rejects unsafe input.
- `tests/integration/classification/test_revit_din276.py` — 200
  pre-classified Revit elements (golden fixture from
  `data/cwicr/golden_revit_classified.parquet`), assert ≥ 95% match
  against expected DIN-276 codes after running `revit-to-din276` pack.
- `tests/unit/classification/test_bridge.py` — classification result
  becomes a queryable EAC property in the same transaction.

**Quality bar:** Migration path from `cad/classification_mapper.py`
static dict — every existing mapping must be reproducible by the new
rule engine; no regression. Old function stays as
`@deprecated` shim for one minor cycle.

### W1.6 — AI Reasoning Receipts → v2.6.5

**Why:** Spec 4.14 mandates that every AI result carries a structured
reasoning trace. This is non-negotiable for high-stakes decisions
(tender BoQs, compliance checks). Wave 1 ships **storage + capture
only**; UI surfacing is Wave 2.

**Scope:**
1. Migration `ai_receipts` table: `(id, run_id, model, prompt_hash,
   input_hash, response_hash, thinking, response, tokens_in,
   tokens_out, cost_usd, created_at, metadata: JSONB)`.
2. `ai_client.py` extended:
   `call(..., capture_thinking=True, receipt_kind='cost-match' | 'classification' | 'compliance')`.
3. Anthropic extended-thinking: `budget_tokens` parameter wired (Claude
   Opus 4.7 / Sonnet 4.6). When provider doesn't support extended
   thinking (OpenAI, Gemini), fall back to capturing the visible
   response only.
4. **No UI in Wave 1.** Receipts are stored but not displayed. Wave 2
   adds the "🧠 reasoning" button in BoQ rows, classification results,
   and compliance checks.

**Tests:**
- `tests/unit/ai/test_receipt_capture.py` — every `ai_client.call()`
  with `capture_thinking=True` writes one `AIReceipt` row before
  returning. If receipt write fails, the call fails (atomic).
- `tests/integration/ai/test_extended_thinking.py` — real Anthropic
  call (gated on `ANTHROPIC_API_KEY` env var), assert thinking captured
  and is non-empty.

**Quality bar:** Receipts are append-only, content-addressed by
`prompt_hash + input_hash` so the same prompt+input never doubles up.

## 4. Cross-cutting concerns (Часть 7 of NextTasks)

These rules apply to every Wave 1 (and beyond) PR:

1. **Unit tests on every calculator and rule.** No new validation /
   classification / EAC rule lands without a green unit test.
2. **Idempotent steps.** Anything that mutates state (run, classify,
   ingest) must be safely re-runnable; deterministic input → identical
   output.
3. **Mandatory unit metrics on numeric values.** Pydantic validator
   `Quantity { value: float, unit: str }` rejects unitless. EAC
   constraint values that are numeric-without-unit fail validation.
4. **Reasoning over confidence.** AI results without a stored receipt
   are rejected at the service layer; the receipt is part of the
   contract.
5. **Reproducibility.** Wave 3 will add `manifest.json` content-addressed
   audit (4.4); Wave 1 already enforces idempotency keys on EAC runs.
6. **Documentation as deliverable.** Every Wave 1 PR includes a doc
   update (README section, user-guide page, or limitations entry).
7. **Performance budgets** are PR-blocking. `pytest-benchmark` regressions
   fail CI.
8. **AGPL audit.** `pip-licenses --fail-on AGPL-3.0-only` on every
   release. Plugin authors warned in marketplace.

## 5. Release plan

| Version | Content | Target |
|---|---|---|
| v2.6.0 | W1.1 (EAC engine finalize) | week 1 |
| v2.6.1 | W1.2 (4-tier validation cascade) | week 2 |
| v2.6.2 | W1.3 (IDS round-trip) | week 2-3 |
| v2.6.3 | W1.4 (BCF export) | week 3 |
| v2.6.4 | W1.5 (classification rule-based) | week 3-4 |
| v2.6.5 | W1.6 (AI receipts) | week 4 |

Each release ships with: tag, GitHub Release notes (extracted from
CHANGELOG.md), PyPI publish, VPS deploy, README badge bump,
docs/docs.html badge bump.

## 6. Open questions (non-blocking)

These are tracked but resolution can lag the implementation:

- **Q-1**: which IDS conformance test corpus do we treat as canon? (Wave
  1 default: buildingSMART `IDS-tools/Documentation/Examples/`.)
- **Q-2**: when DDC adapter ships geometry signatures (Wave 2 prep), do
  we backfill old uploaded models or only forward-process new ones? (Soft
  default: forward-only; backfill on demand via CLI.)
- **Q-3**: receipt retention — keep forever or rotate after N days?
  (Wave 1 default: keep forever; revisit after Wave 3 audit-trail
  ships.)

## 7. Appendix — file map

New files (Wave 1):

```
backend/
  alembic/versions/<rev>_eac_v2_initial.py
  alembic/versions/<rev>_ai_receipts.py
  alembic/versions/<rev>_classification.py
  app/modules/eac/ids/__init__.py
  app/modules/eac/ids/exporter.py
  app/modules/eac/ids/importer.py
  app/modules/eac/bcf/__init__.py
  app/modules/eac/bcf/exporter.py
  app/modules/classification/__init__.py
  app/modules/classification/manifest.py
  app/modules/classification/models.py
  app/modules/classification/schemas.py
  app/modules/classification/router.py
  app/modules/classification/service.py
  app/modules/classification/repository.py
  app/modules/classification/bridge.py
  app/modules/classification/rules/dsl.py
  app/modules/ai/receipts.py
  tests/golden/ids/*.ids
  tests/golden/classification/golden_revit_classified.parquet
  tests/integration/eac/test_run_persistence.py
  tests/integration/eac/test_run_spool.py
  tests/integration/validation/test_incremental_mode.py
  tests/integration/bcf/test_bcf_export.py
  tests/integration/classification/test_revit_din276.py
  tests/unit/classification/test_dsl.py
  tests/unit/classification/test_bridge.py
  tests/unit/ai/test_receipt_capture.py
data/classification-packs/revit-to-din276.yaml
data/classification-packs/revit-to-nrm.yaml
data/classification-packs/revit-to-masterformat.yaml
data/classifications/din276-allowed.json
data/classifications/nrm-allowed.json
data/classifications/masterformat-allowed.json
docs/user-guide/ids-roundtrip.md
docs/qa/bcf-validation.md
```

Modified (Wave 1):

```
backend/app/modules/eac/router.py        # POST /runs persistence
backend/app/modules/eac/engine/executor.py  # Celery wiring
backend/app/core/validation/engine.py    # batch | incremental modes
backend/app/core/validation/rules/__init__.py  # category remapping
backend/app/modules/ai/ai_client.py      # capture_thinking parameter
backend/app/modules/cad/classification_mapper.py  # @deprecated shim
README.md                                 # version + badge
docs/docs.html                            # version + badge
CHANGELOG.md                              # one entry per release
```

## 8. Out-of-scope for Wave 1 (parking lot)

Documented here so they don't get lost:

- 2.3 Geometric Quantity Engine (7 calculators) — Wave 2, requires DDC
  geometry_signature extension.
- 2.4 vector + LLM classification tiers — Wave 2, requires pgvector
  embeddings on classifier catalogue.
- 2.5 real-time validation gate — Wave 2, requires WebSocket
  infrastructure.
- 2.6 Spatial Boundary Resolution — Wave 2, requires DDC IfcSpace boundary
  emission.
- 2.7 Visual Data Layer (palettes, IFC bake) — Wave 2/3.
- 2.8 Cost Intelligence pipeline (full E2E) — Wave 2.
- 2.9 DAG composable workflows — Wave 3.
- 4.1 Multi-modal element matching — Wave 4 (pre-rendered thumbnails).
- 4.3 Generative Specifications (PDF → EAC) — Wave 3.
- 4.4 Reproducible Audit Trail (manifest.json + sigstore) — Wave 3.
- 4.5 Carbon-Aware Estimation — Wave 2 (EU CSRD lever).
- 4.6 Real-Time Collaborative Wrangling (Yjs) — Wave 4, opt-in v2.8 →
  default v3.0.
- 4.8 Time-Aware Versioning (Git for BIM) — Wave 4, 7 sub-phases over
  8-10 weeks.
- 4.9 Plugin Marketplace — Wave 5.
- 4.13 Ambient Validation — Wave 3 (rides on 2.9 DAG + 2.5 real-time).
- 4.14 Reasoning Receipts UI — Wave 2 (storage in Wave 1 already).
- 4.2 Federated Learning Loop — v3.x, gated on GPU infra + user demand.
