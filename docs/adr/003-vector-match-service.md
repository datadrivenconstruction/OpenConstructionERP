# ADR 003 — Vector-based element-to-CWICR match service

**Status:** accepted
**Date:** 2026-05-03
**Versions:** Phase 0 v2.7.2 · Phase 1 v2.7.3 · Phase 2 v2.7.4 · Phase 3+4 in flight
**Related:** ADR 002 (DDC canonical format), `app/core/match_service/`, `tests/eval/`

## Context

OpenConstructionERP needed a way to take a CAD/BIM/PDF/photo element (Revit wall, IFC slab, takeoff measurement, photo of a brick wall) and surface ranked CWICR cost-position candidates so an estimator can link them with one click instead of searching the 55k-item catalog manually.

Constraints from the user / existing platform:
- Multilingual: CWICR ships per-region in 9 source languages (en, de, ru, lt, fr, es, it, pl, pt). Element data may be in a different language than the catalog the project targets.
- Same matcher must work across 4 element sources (BIM / PDF / DWG / photo) and produce the same `MatchCandidate` shape regardless.
- Project-level configurability: each project picks the catalog language, optional classifier (DIN276 / NRM / MasterFormat / none), auto-link threshold, and manual-vs-auto mode.
- Catalog stays in source language. Translation is one-way: element → catalog. We do not translate the 55k catalog rows.
- No new heavy dependencies. Use `intfloat/multilingual-e5-small` (already in the project's `[vector]` extra) for embeddings, LanceDB (already in base) for ANN search.
- Quality bar from the user: «максимально качественно ... не должно быть костылей или хардкода ... должно быть максимально рабочее и грамотный функционал который будет работать одинаково в разных модулях».

## Decision

A single shared service at `backend/app/core/match_service/` that all sources funnel into. Frontend mounts one shared `MatchSuggestionsPanel` component that all viewers (BIM/PDF/DWG/photo) embed.

### Pipeline

```
Source-specific raw data (BIM dict / PDF takeoff / DWG element / photo CV output)
    ↓ extractors/<source>.py
ElementEnvelope (universal Pydantic shape)
    ↓ ranker.rank()
1. Load MatchProjectSettings — target_language, classifier, threshold, mode
2. (optional) classifier_hint enrichment via classification_mapper (Phase 1)
3. Translation cascade: lookup (MUSE/IATE) → cache → LLM → fallback
4. Vector search: E5 query: prefix → LanceDB cosine top-K (over-fetched 3×)
5. Boost stack: classifier match · unit match · region match · lex fuzz
6. Sort by (-score, code) — deterministic tie-break
7. (opt-in) LLM rerank top-K with cost cap
8. Auto-link gate: if top score ≥ threshold AND auto_link_enabled
    ↓
MatchResponse (candidates + translation_used + auto_linked)
```

### Component map

| Layer | Module | Responsibility |
|---|---|---|
| Adapter | `app/modules/costs/vector_adapter.py` | Embed CostItem rows into `oe_cost_items` LanceDB collection (E5 `passage:` prefix); search with `query:` prefix |
| Adapter events | `app/modules/costs/events.py` | Subscribe to `costs.item.{created,updated,deleted,bulk_imported}` → reindex |
| Adapter admin | `POST /api/v1/admin/cost-vector-reindex` | Triple-gated forced reindex (env + token + non-prod) |
| Translation | `app/core/translation/` | 4-tier cascade (lookup TSV → SQLite cache → LLM via existing `ai_client` → fallback). MUSE + IATE downloaders behind SSRF allowlist |
| Settings | `app/modules/projects/MatchProjectSettings` | Per-project knobs; lazy init on first GET; audit-logged updates |
| Match core | `app/core/match_service/{ranker, envelope, boosts, extractors, reranker_ai, feedback, config}` | The pipeline + 4 extractors + 4 boosts + LLM rerank + audit-log feedback |
| Match HTTP | `app/modules/match/router.py` | `POST /match/element` · `POST /match/feedback` · `POST /match/accept` |
| Eval | `tests/eval/` | Golden-set + AI-as-judge + CI workflow |
| Frontend | `frontend/src/features/match/MatchSuggestionsPanel.tsx` | Shared React component used by every viewer |

### Why a single envelope

Each source (BIM/PDF/DWG/photo) has wildly different raw shapes — Revit hands you a dict with `category`, `Type Mark`, `Material`, geometry inside `geometry`; PDF takeoff hands you `{label, length, area, reading}`; photo gives you `{material_tags: [...], dimensions: {...}}`. Forcing them into one ranker surface needs a normalisation step. The universal `ElementEnvelope` (category · description · properties · quantities · classifier_hint · source_lang) means:
- One ranker, one set of boosts, one set of tests.
- A new source just needs a new `extractors/<source>.py`. The ranker doesn't change.
- The frontend panel is identical regardless of source — the viewer just builds the right `raw_element_data` dict.

### Translation policy: one-way, element → catalog

Catalog stays in its source language and is vectorised once. Element-side text gets translated to the project's `target_language` before embedding. Reasoning:
- Translating 55k catalog rows × N target languages is O(NM) work + storage churn; translating per-request is O(1) and uses the existing AI infra.
- E5 multilingual-small handles cross-lingual matching natively (recall ~50% lower than monolingual but still useful as a fallback when no translation is available).
- The cascade short-circuits at the cheapest tier that hits the threshold — most calls land on lookup tables (free) or cache (fast).

### Auto-link policy: opt-in per project

`auto_link_enabled` defaults to `false`. Even when true, only the top candidate is auto-linked, and only if it crossed the project's threshold. The user always sees the suggestion in the panel — auto-link is a write-on-accept shortcut, not a write-without-review.

## Trade-offs

**Accepted:** Cross-lingual matching is lower-recall than within-language. Mitigation: translation cascade tries lookup tables first (free, often as good as LLM for construction terms). LLM rerank tier is opt-in for hard cases.

**Accepted:** LanceDB schema is JSON-encoded payload (not first-class columns), so adding a column requires a destructive reindex. Trade-off: keeps the schema stable while we iterate. Reindex is gated, async, batched, and tracked via task_id.

**Accepted:** No real-time index updates are guaranteed. Cost catalog CRUD publishes events that trigger debounced re-embedding. Under load, events can be coalesced and processed slightly out of order. Eventual consistency is fine — searches against a partial index just return slightly stale candidates.

**Accepted:** The `oe_cost_items` collection is single-tenant globally (not per-tenant). Custom per-tenant catalogs live in `oe_costs_cost_item.source` and are filtered in Python after retrieval. If the platform goes serious multi-tenant, this becomes a per-tenant collection or a tenant_id payload column.

**Rejected:** A pre-translated catalog (every row in N languages). The 9× explosion in vector storage is not worth the marginal recall gain.

**Rejected:** Online LLM-based matching as the primary tier. Cost (LLM tokens × catalog size) and latency (network hops) are prohibitive. LLM is the rerank tier on the top-5 only, opt-in, with a per-call cost cap.

**Rejected:** Migrating existing CWICR data with backfilled DIN-276 codes per row. The user explicitly said no — Phase 1 enrichment only applies to *new* imports going forward. Rationale: backfilling 55k rows with possibly-wrong codes is worse than leaving them un-classified.

## Verification

| Quality Gate | Phase 0 | Phase 1 | Phase 2 |
|---|---|---|---|
| Backend tests | 118 + 70 edge + 6 region | + 77 (61 unit + 16 int) | (no change) |
| Frontend tests | n/a | n/a | + 21 (17 unit + 4 a11y) |
| Ruff strict | clean | clean | n/a |
| `tsc --noEmit` | n/a | n/a | clean |
| Live e2e | top score 0.772 against 599k-vector catalog | (regression suite) | mounted in BIMRightPanelTabs |
| Eval harness | functional (zero metrics due to test-fixture catalog vs golden_set codes — see `tests/eval/baseline.json` `_validation_note`) | (no regression) | (no regression) |

Verification surfaced 11 issues during deep architecture review; all 8 high-severity fixed:
- SSRF in IATE downloader → host allowlist + `follow_redirects=False`
- Cross-user task leakage in `/lookup-tables/status` → owner filter
- `region.py` returned bare string for fully-qualified codes → tuple of exact code
- Sentinel UUID FK violation in `match_element` → SimpleNamespace fallback
- Classifier reverse-substring fallback over-broad → forward-only, min 3 chars
- `source="bogus"` returned 500 → Pydantic Literal validator (422)
- SHA1 cache key flagged Bandit HIGH → `usedforsecurity=False`
- Non-deterministic auto-link winner on ties → `(-score, code)` sort

## Open follow-ups

- Concurrent latency hardening (issue tracked as task #73): 50× concurrent p95 = 9.9s vs target 2s. Embedder warm-pool + project lookup cache in flight.
- Phase 5 (DWG + photo extractors) blocked on the CV pipeline build — separate multi-week work.
- Real-CWICR vs golden-set code reconciliation so eval produces meaningful numbers.
- Per-user rate limit + cost cap on `/translation/translate` and `/match/element`.

## References

- `app/core/match_service/__init__.py` — public API surface
- `app/core/match_service/envelope.py` — universal types
- `tests/eval/golden_set.yaml` — 30 ground-truth pairs across 4 sources
- CHANGELOG `[2.7.2]` / `[2.7.3]` / `[2.7.4]` — Phase 0 / 1 / 2 release notes
- Memory `qa_crawler_built.md` — adjacent QA pipeline used for verification
