# AI Estimator v3 - Conversational Groups and Multi-Pass Mapping (Design)

Status: design, implementation-ready. This document changes no source code. It is
written so a team of parallel agents can build from it without re-reading the
originating prompt.

Author context: the founder vision (translated): a user who simply writes "make me
a kitchen estimate" or "house renovation 120 m2" must be guided by the AI through
(1) a layperson-friendly but professionally-grounded conversation that collects the
few high-value parameters the AI itself decides it needs, (2) AI-derived volumetric
WORK GROUPS the user can see, add to, delete and edit, (3) confirmation, then
(4) grounded mapping of those groups against our vector cost database "in several
passes" so the estimate is realistic, with works decomposed into stages like a
professional estimator-foreman. Rates are never invented; the AI proposes and the
human confirms.

This is v3. It does NOT start from zero. Most of the founder vision is ALREADY
built as "intake v2" (see docs/initiative-ai-estimator/INTAKE_V2_DESIGN.md). v3 is
mostly (a) UNIFYING the two estimator surfaces so the conversational flow is the
front door of the route the founder names (/ai-estimator), and (b) turning the
implicit single-shot matcher into an EXPLICIT, observable multi-pass mapping
pipeline. The bulk of v3 is reuse plus two genuinely new pieces.

No em-dashes are used in this document by request.

---

## 0. Founder-locked decisions (carried from intake v2, not reopened)

1. Max 3 clarification rounds in the AI dialogue (a hard ceiling).
2. No AI key maps to curated parameter questionnaires per project type (the
   offline path runs through the same state machine).
3. Hybrid checklists: curated work-package checklists PLUS vector-DB-grounded
   group shaping. Probe the vector DB hard, maximise recall of real DB positions.
4. AI proposes, human confirms: element groups are visible, editable, deletable
   and addable by the user before any rate is matched.
5. Works decompose into stages like a professional estimator/foreman.

v3 adds one decision, consistent with the above:

6. Mapping runs as an explicit, observable multi-pass pipeline (semantic
   candidates, unit/scale reconcile, rate-sanity vs benchmarks). Each pass is
   logged to the run timeline. No pass ever fabricates a rate; later passes can
   only re-rank, rescale or flag, never invent.

---

## 1. What exists today (grounded, file-by-file)

The estimator is split across two frontend surfaces that share one backend
module. This split is the single biggest source of "the founder feature looks
missing" even though most of it is built.

### 1.1 Backend module backend/app/modules/ai_estimator/ (mature)

- models.py - four tables: oe_ai_estimator_run, oe_ai_estimator_group,
  oe_ai_estimator_step, oe_ai_estimator_intake (1:1 with run, models.py:417,
  __tablename__ at :436). AiEstimatorGroup carries quantities, envelope,
  chosen_unit, trade, status, candidates, resources, sort_order (:346) and a free
  metadata_ JSON (:352) already used by the composer for package_key,
  foreman_stage, probe, coverage, classification.
- schemas.py - the full contract INCLUDING intake v2: SourceKind (text, excel,
  gaeb, bim, dwg, pdf, photo, documents, takeoff, boq), RunStatus (includes
  "intake"), IntakePhase, IntakeMode, CoverageBand, IntakeQuestion,
  IntakeQuestionOption, ComposedPackage, IntakeState, IntakeCreate,
  IntakeAnswerRequest, ConfirmParametersRequest, IntakePackagesRequest,
  WorkPackageSelection, ProjectTypeOut, ProjectParamOut, WorkPackageOut, plus the
  run/group/match/preview/apply schemas. DEFAULT_MATCH_GROUP_CAP = 25 (:112).
- project_types.py - ten curated project types (kitchen_reno, bathroom_reno,
  apartment_reno, house_new, roof, facade, extension, commercial_fitout,
  landscaping, mep_retrofit), each with EN/RU/DE detection synonyms, a per-round
  parameter questionnaire (ProjectParam with unlocks + round_group), and a
  work-package checklist (WorkPackage with stages, vector probes, qty_formula,
  trade, unit). Also FOREMAN_STAGES (demo, structure, rough, close, finish,
  commission), FOREMAN_STAGE_TO_OMNICLASS onto the 12 ConstructionStage values,
  detect_project_type, params_for_round, default_packages, and the advisory
  STAGE_DEPENDENCIES DAG + dependency_warnings.
- quantities.py - pure deterministic qty_formula functions (floor_area, ceiling,
  wall_net, wall_full, partition, fixtures, points, slope, facade_net,
  facade_gross, paving, planting, fencing, debris, site_area, earthworks, lump).
  compute_quantity returns QtyResult(quantity, unit, estimated). Proxy-derived
  quantities flagged estimated=True. Offline and AI paths compute identical numbers.
- intake.py - IntakeService, the conversational FSM. start, answer (3-round cap +
  confidence-driven skip at threshold 0.9), confirm_parameters (checkpoint A, runs
  the composer), edit_packages (checkpoint B, re-probes), finish (bridges to the
  run FSM with metadata_.intake_composed=True so grouping is not re-derived). The
  composer _compose probes the live ranker per (package x stage) cell via
  _probe_score calling app.core.match_service.ranker_qdrant.rank, keeps the best
  phrasing, classifies coverage (grounded >= 0.62, weak >= 0.30 floor, else gap),
  persists one AiEstimatorGroup per cell. AI and offline run the SAME machine.
- service.py - AiEstimatorService four-stage orchestrator. analyze (:244, stage 1
  + LLM refinement that degrades), confirm_stage (:607, four checkpoints; skips
  _build_groups when intake_composed), _build_groups (:665, deterministic
  signature grouping for measured sources), run_matching (:810, the matcher),
  build_preview (:1493, FX-correct never-blend rollup + core validation), apply
  (:1701, Position rows source ai_precise_estimate). Bands HIGH 0.78, MEDIUM 0.62.
- router.py - all endpoints under /api/v1/ai-estimator/ (+ legacy mirror). Intake:
  POST /intake, GET /runs/{id}/intake, POST .../intake/answer,
  .../intake/confirm-parameters, .../intake/packages, .../intake/finish,
  GET /project-types. Run: /runs, /runs/{id}, /analyze, /confirm, /progress,
  /steps, /match, /bulk-confirm, /groups..., /preview, /apply, /meta, /catalogues,
  /qdrant/health. Every route: verify_project_access (404 on deny) + RequirePermission.
- prompts.py - SOURCE_CLASSIFY, GROUP_REFINE, MATCH_REASONING,
  INTAKE_EXTRACT_SYSTEM, INTAKE_QUESTIONS_SYSTEM, build_match_reasoning_input.
- extractors.py (parse_text_scope, BIM/takeoff/BOQ/photo extractors), taxonomy.py
  (classify_trade, TRADE_KEYWORDS), tools.py (PRECISE_MATCH_AGENT), repository.py,
  events.py, validators.py.

### 1.2 The grounded retrieval stack (reused unchanged)

run_matching and the composer both build an ElementEnvelope
(backend/app/core/match_service/envelope.py) and call rank(MatchRequest, db) from
backend/app/core/match_service/ranker_qdrant.py. That ranker loads
MatchProjectSettings and the bound CWICR catalogue, builds a SearchPlan
(backend/app/modules/costs/query_builder.py) with a dense query, hard filters
(unit_type, ifc_class, construction_stage that fire only when the bound collection
carries the field), one hybrid Qdrant call (dense + sparse fused by RRF), a narrow
classifier/unit/region boost stack, and an optional BGE-M3 rerank. The CWICR
vector DB is US/civil-heavy; residential trades exist but are thin, and the
catalogue's embedded text is a "keyword salad" of classification axes, not natural
sentences. That is why the composer probes multiple curated phrasings per package
and keeps the best by SCORE. After rank, service._enrich_candidates_from_costdb
(service.py:978) backfills the real stored rate/currency/unit/components from the
SQL oe_costs_item table for the grounded code, so even a snapshot-only install
gets the real priced row. A group with no grounded candidate becomes needs_human.

### 1.3 Frontend - TWO surfaces sharing the backend

- frontend/src/features/ai-estimator/AiEstimatorPage.tsx (route /ai-estimator, the
  surface the founder references). A run-based 4-stage wizard: source -> grouping
  -> matching -> assembly, with a StageRail, RunMonitor, and stage panels
  Stage1Source.tsx (Stage1Intake text/files/BIM/documents + Stage1Confirm),
  Stage2Groups.tsx, Stage3Match.tsx, Stage4Review.tsx. This page does NOT mount
  the conversational intake panel. Its "Free text" tab starts a run via
  createRun({source:'text', text_input}) which runs the old parse_text_scope path,
  NOT the intake dialogue.
- frontend/src/features/ai/intake/ (the conversational intake v2 UI): IntakePanel,
  useIntake, api, types, GroupBoard, ParameterSheet, QuestionControl,
  DependencyWarnings, helpers. Fully built: collect-request -> rounds -> parameter
  sheet (checkpoint A) -> editable group board with coverage badges (checkpoint B)
  -> finish bridges to a run.
- frontend/src/features/ai/QuickEstimatePage.tsx (route /ai-estimate). This is
  where IntakePanel is actually mounted (:2842). On finish it navigates to
  /ai-estimator?run=<id> (:2858), dropping the user into the run wizard at matching.

### 1.4 The gap, stated precisely

The founder vision is built but FRAGMENTED across /ai-estimate and /ai-estimator,
and the matching is a single grounded pass dressed as one step rather than the
explicit several-pass mapping the founder asked for. A user who lands on
/ai-estimator (the named route) and types "make me a kitchen estimate" gets the
OLD parse_text_scope behaviour (one meaningless envelope), NOT the conversational
intake. v3 fixes exactly this.

---

## 2. UX FLOW (the founder four stages, unified on /ai-estimator)

Target: /ai-estimator "New estimate" opens with the conversational intake as the
FIRST thing the text path does, and the existing 4-stage wizard becomes stages
3-4 of the same continuous flow. Files/BIM/CAD/documents keep their direct path
(they already carry real quantities and need no questionnaire).

### Stage A - Conversational intake (free text to parameters)

1. The user types a single line ("kitchen estimate please", "house renovation
   120 m2", "new house 2 storeys", "bathroom refurb 5 m2 turnkey"). The same path
   handles Russian and German free text (the type detector carries EN/RU/DE synonyms).
2. POST /intake runs extract: intent classification picks the project type (LLM
   extraction degrading to the deterministic synonym detector). The detected type
   is a chip with a real confidence badge (or "selected" when deterministic, never
   a fake percentage).
3. The AI proposes a SMALL set of high-value parameters as interactive chips and
   inputs INSIDE the chat (round 1 = the few questions that unlock the most
   quantity: floor area, ceiling height, finish level, demolition yes/no, wall
   construction for new build, scope boundaries). Each question carries a layperson
   prompt plus a "why we ask" justification derived from ProjectParam.unlocks (for
   example ceiling height to "compute wall area for tiling and painting"). Rounds 2
   and 3 ask only still-unresolved or refinement params.
4. The machine iterates until "enough to estimate": confidence-driven skipping
   jumps to the parameter sheet the moment required coverage reaches 0.9, with a
   hard ceiling of 3 rounds. A fully-specified request reaches the sheet in one round.
5. Checkpoint A: the user reviews the parameter sheet (right column), edits any
   value, confirms. Estimated/proxy values are shown dashed and editable.

No API key: the same machine renders the curated questionnaire as a plain form
instead of chat (section 6).

### Stage B - Group formation (volumetric work groups)

On confirm-parameters the composer derives VOLUMETRIC WORK GROUPS: one
AiEstimatorGroup per (work package x foreman stage) cell that has work. Each group
shows its derived quantity + unit, an estimated flag when a proxy was used, the
foreman stage it belongs to, and a real coverage badge from the live vector probe
(grounded / weak / gap). Groups are ordered by foreman stage so the board reads
top-to-bottom in build order. Demolition, structure, first fix, close-up, finishes
and commissioning each become a section.

### Stage C - Group editing board (human confirms)

The user adds packages (curated picker for the type non-default packages, or a
free-text "add custom work" box the composer probes immediately), removes packages
(deletes their groups), toggles inclusion, and edits quantities/units on the
existing per-group edit path. Advisory foreman-sequence warnings appear (for
example "tiling scheduled before its plaster substrate") but never block. Footer:
"N work packages, K grounded, P weak, Q gap". Checkpoint B ("Confirm group board")
bridges to the run pipeline.

### Stage D - Multi-pass mapping (rates with confidence) and apply

The composed groups flow into the multi-pass mapping pipeline (section 4.3):
- Pass 1 (semantic candidates): the existing grounded rank over the DB-friendly
  query the composer already shaped, top-K real candidates per group.
- Pass 2 (unit/scale reconcile): align each candidate catalogue unit and any
  numeric unit multiplier ("100 CY") with the group measured unit, rescaling the
  per-base-unit rate; demote dimensionally incompatible candidates.
- Pass 3 (rate sanity vs benchmarks): compare each surviving candidate unit rate
  against a per-trade/per-unit benchmark band; flag outliers as low confidence for
  human review, never silently drop a real DB rate.
The user reviews per-group candidates with confidence bands, accepts/overrides
(override id must already be in the candidate list), bulk-confirms above a
threshold, then reviews the assembled preview (FX-correct, per-currency subtotals,
validation report) and explicitly applies to a BOQ. Nothing auto-writes.

---

## 3. DATA CONTRACTS

### 3.1 WorkGroup (already AiEstimatorGroup + ComposedPackage; v3 standardises)

The founder WorkGroup maps to the existing pair: ComposedPackage is the
board-level package, AiEstimatorGroup is the per-(package x stage) row that is
matched. v3 does not add a new table. It standardises the named fields onto the
existing rows, all of which exist or fit in metadata_:

    WorkGroup (= AiEstimatorGroup row)
      id            uuid
      title         description (string)
      trade         trade (taxonomy key)
      quantity+unit quantities{} + chosen_unit
      derivation    metadata_.qty_formula + metadata_.derivation
                    (NEW: formula id + a short human "perimeter x height" string)
      assumptions[] metadata_.assumptions (NEW: e.g. "perimeter inferred from
                    area, aspect 1.4"; today only implied by the estimated flag)
      confidence    confidence (real float or null)
      source        metadata_.source (NEW enum: dialogue | file | cad | photo)
      coverage      metadata_.coverage (grounded | weak | gap)
      foreman_stage metadata_.foreman_stage
      package_key   metadata_.package_key

Board-level (ComposedPackage, already in schemas.py): package_key, trade,
selected, stages[], group_ids[], coverage, best_score, quantity, unit, estimated.
v3 leaves this schema unchanged.

v3 action: add derivation, assumptions[], source into the group metadata_ at
compose time (one change in IntakeService._persist_group), and surface them
read-only in GroupDetail. No DB migration (free JSON column).

### 3.2 Parameter-elicitation message schema (already IntakeQuestion)

The founder chips/options/inputs embedded in chat is exactly the existing
IntakeQuestion rendered by QuestionControl.tsx:

    IntakeQuestion
      param_key     string
      kind          number | choice | bool | length  (choice -> chips/segmented)
      unit          string | null                     (suffix on number/length)
      required      bool
      options[]     IntakeQuestionOption{value, label_key}   (the chips)
      prompt        string   (layperson question, LLM- or curated-phrased)
      why           string   (i18n key; the professional justification)
      current_value any|null (prefilled when known from the free text)

A round is a list[IntakeQuestion] on IntakeState.questions. No structural change;
v3 only enriches the why copy so the professional reason is always shown.

### 3.3 Mapping-pass result schema (NEW, additive)

The current single match stores candidates[], score, confidence, confidence_band,
match_method, resources[] on the group. v3 keeps all of that and adds a per-group
mapping trace so the multi-pass is observable. It lives in metadata_.mapping_trace
(free JSON, no migration) and is serialised on GroupDetail so the UI can show
"why this rate":

    MappingTrace (metadata_.mapping_trace)
      passes: [
        { pass: "semantic" | "unit_scale" | "rate_sanity",
          kept: int, dropped: int, notes: str,
          benchmark: { trade, unit, band_low, band_high, outliers } | null
        }, ... ]
      final_method: "vector" | "unit_scale" | "llm" | "manual"

Each pass also writes an AiEstimatorStep (role observation, stage matching) so the
existing run timeline renders the multi-pass for free.

### 3.4 Benchmark bands (NEW small curated data, like project_types.py)

backend/app/modules/ai_estimator/benchmarks.py: a pure-data table of plausible
unit-rate bands keyed by (trade, unit), expressed as ratios relative to the
catalogue own median for that trade/unit at runtime (currency- and
catalogue-agnostic). Pass 3 computes the per-run median rate per (trade, unit)
across the candidates actually retrieved, then flags any candidate more than the
band factor away from that median (default 8x, configurable on /meta). This is a
SANITY flag, not a price book: it never replaces a real DB rate, it only lowers
confidence and surfaces the outlier for human review. Keeps "rates only from DB".

### 3.5 Persistence summary

- Reuse: oe_ai_estimator_run, oe_ai_estimator_group, oe_ai_estimator_step,
  oe_ai_estimator_intake. All four exist and migrated.
- New columns: NONE. derivation, assumptions, source, mapping_trace all live in
  the existing free metadata_ JSON on the group; the per-pass log uses existing
  AiEstimatorStep rows. v3 is single-DB, additive, migration-free.
- New pure-data module: benchmarks.py (no DB).

---

## 4. THE PIPELINE, END TO END

### 4.1 Source-agnostic ingestion (founder: from any source)

The same WorkGroup pipeline is fed from every source through a thin adapter that
produces either composed groups (the conversational path) or signature groups (the
measured-source path). Both converge on the same AiEstimatorGroup rows, then the
same multi-pass mapping.

- Dialogue (free text): IntakeService + quantities.py + composer produce composed
  groups (package x stage) with derived quantities + coverage. source=dialogue.
  The founder headline path.
- Uploaded Excel / GAEB BOQ: RunCreate.rows -> _normalise_sources ->
  _build_groups signature grouping; one group per line item, quantity from the
  row. source=file. Already works; v3 routes it through multi-pass mapping unchanged.
- CAD / BIM canonical JSON: extractors.extract_bim over the converted model ->
  envelopes -> _build_groups; groups by signature carrying ifc_class/material_class
  hard filters. source=cad. Already works.
- PDF + DWG takeoff: extractors.extract_takeoff; measured items as envelopes.
  source=file. Already works.
- Existing BOQ (re-estimate): extractors.extract_boq; one group per position.
  source=file. Already works.
- Photos: extractors.extract_photos (presence signals); element suggestions.
  source=photo. Present but weakest; a future LLM-vision pass can seed a dialogue
  from a photo then run the standard intake. Out of v3 scope beyond what exists.

Adapter contract (the seam every source meets): each adapter emits groups with
description (a DB-friendly query string), quantities{}, chosen_unit, trade, and an
envelope carrying project_currency/project_region and any hard-filter signal it
has (ifc_class, construction_stage_hint). The composer satisfies this by probing
for the best phrasing; the measured-source path satisfies it via _group_envelope.
After this seam, ALL sources are identical.

### 4.2 Group formation detail

- Dialogue path: IntakeService._compose expands default_packages(pt) (or the
  user-selected subset), computes compute_quantity per package, probes the live
  ranker per (package x stage) cell, keeps the best phrasing, classifies coverage,
  persists one group per cell ordered by FOREMAN_STAGES. v3 adds derivation,
  assumptions, source=dialogue to each persisted group metadata_.
- Measured path: _build_groups buckets envelopes by signature, sums canonical
  quantities, classifies trade. v3 tags source=file|cad from the envelope source.

### 4.3 Multi-pass mapping (the new explicit pipeline)

Today run_matching does, per group: rank -> _enrich_candidates_from_costdb ->
optional agent rerank -> top-1. v3 refactors this single block into three NAMED
passes inside run_matching, each logged, each reflected in metadata_.mapping_trace.
This is a refactor of existing code plus two new helper methods; it does not change
the public match endpoints or their shapes.

Pass 1 - Semantic candidates (REUSE rank):
  For each group, build the ElementEnvelope (already done), call rank, get top-K
  real candidates, enrich from the cost DB. Exactly todays behaviour, now
  explicitly labelled pass 1 and logged ("pass=semantic, kept=K").

Pass 2 - Unit/scale reconcile (NEW helper _reconcile_units):
  For each candidate, peel any leading numeric multiplier off the catalogue unit
  (the existing _split_unit_multiplier already does "100 CY" -> (100, "CY")), map
  the catalogue unit type to the group chosen_unit dimension (Area/Volume/Linear/
  Mass/Count, reusing the unit_type logic in query_builder.py), rescale the
  per-base-unit rate (already done by _candidate_unit_rate), and DEMOTE (not
  delete) any candidate whose dimension is incompatible with the group quantity
  dimension (e.g. an m3 rate for an m2 tiling group). The demotion lowers that
  candidate effective score so the dimensionally-correct candidate rises to top-1.
  Logged ("pass=unit_scale, dropped=D").

Pass 3 - Rate sanity vs benchmarks (NEW helper _rate_sanity):
  Compute the median per-base-unit rate across the surviving candidates for the
  group (trade, unit). Flag any candidate more than the band factor away from that
  median (using benchmarks.py); cap the flagged candidate confidence at the LOW
  band and annotate it. The chosen top-1 is the highest-scoring candidate that is
  NOT a flagged outlier; if every candidate is an outlier, keep the highest score
  but mark the group needs_human with the reason in the trace. Logged
  ("pass=rate_sanity, outliers=O, band=[low,high]").

Invariants across all passes: no rate is invented; passes 2 and 3 only re-rank,
rescale or flag candidates that pass 1 retrieved from the DB; confidence stays a
real float or null; a group with no compatible candidate is needs_human, never a
fabricated number. When the user-selected agent is present it still reasons over
the survivors of pass 3 (the agent can only pick an id the tools returned),
recorded as final_method=llm.

"In several passes to add realistic estimates" (founder) is thus literal and
observable: three named passes, each on the timeline, each in the trace.

### 4.4 Apply

Unchanged. build_preview (FX-correct, never-blend, per-currency subtotals, core
validation) then apply writes Position rows with source=ai_precise_estimate, real
confidence (or empty), cad_element_ids, scaled resource breakdown, and the
grounded classification. Gated on the assembly checkpoint and a clean validation
report.

---

## 5. GAP ANALYSIS (file-by-file, reuse-first)

Legend: BUILT (use as-is), EXTEND (small change), NEW (create).

Backend:
- intake.py - BUILT. EXTEND _persist_group to write derivation, assumptions,
  source into metadata_. EXTEND _compose / _compose_custom to carry source=dialogue.
- service.py run_matching - EXTEND: split the per-group block into the three named
  passes; add _reconcile_units and _rate_sanity; write metadata_.mapping_trace and
  per-pass AiEstimatorStep rows. Selection logic, caps, catalogue binding and
  enrichment reused unchanged.
- service.py _build_groups - EXTEND: tag metadata_.source from the envelope source.
- benchmarks.py - NEW pure-data module (trade/unit band factors + median logic).
- schemas.py - EXTEND GroupDetail to expose mapping_trace, derivation, assumptions,
  source (read from metadata_); EXTEND MetaResponse with the benchmark band factor.
  No new tables.
- router.py - BUILT. No new endpoints; the multi-pass is internal to /match. The
  GroupDetail schema change already surfaces mapping_trace on the existing endpoint.
- models.py, project_types.py, quantities.py, extractors.py, prompts.py,
  taxonomy.py, repository.py - BUILT, no change.

Frontend:
- frontend/src/features/ai/intake/* (IntakePanel, GroupBoard, ParameterSheet,
  QuestionControl, useIntake, api, types, helpers) - BUILT. Reused as Stage A+B+C.
- frontend/src/features/ai-estimator/AiEstimatorPage.tsx - EXTEND: when the source
  tab is "Free text", render IntakePanel (from @/features/ai/intake) as the first
  step instead of starting a parse_text_scope run; on onFinished(runId) set the
  page runId and jump the wizard to the matching stage. Files/BIM/documents keep
  the existing Stage1Intake path. This is the unification that puts the founder
  flow on the named route.
- frontend/src/features/ai-estimator/components/Stage3Match.tsx - EXTEND: show the
  three-pass mapping trace per group (a "why this rate" expander reading
  GroupDetail.mapping_trace) and a rate-sanity outlier badge.
- frontend/src/features/ai/intake/index.ts - BUILT (exports IntakePanel).
- frontend/src/features/ai/QuickEstimatePage.tsx - BUILT. Keep as the lightweight
  quick path; its finish-bridge already lands on /ai-estimator?run=. No change
  required; its IntakePanel mount becomes the second consumer of the shared panel.
- i18n - EXTEND: enrich aiest.why.* copy, add aiest.map.pass_*, aiest.map.outlier,
  aiest.group.derivation/assumptions across the 26 locales (the i18n-sweep skill).

Tests:
- BUILT: intake FSM, quantity formulas, type detection, integrity (every unlocks/
  qty_formula resolves), offline-parity (per the intake v2 plan section 10).
- NEW: multi-pass mapping tests; a unified-route test (a /ai-estimator free-text
  start renders the intake, not the old parse path); benchmark band tests.

---

## 6. NO-API-KEY MODE (degraded but fully functional)

Already implemented end to end; v3 keeps it and ensures the unified route honours
it.

- Intent + parameters: extract degrades from LLM to the deterministic synonym
  detector (detect_project_type) seeded by parse_text_scope for any explicit
  quantities. Type confidence is null (honest "selected", not a fake number). If
  detection is ambiguous the UI shows the ten project-type tiles for a manual pick
  (the registry comes from GET /project-types).
- Conversation: IntakePanel renders the SAME curated questions (params_for_round)
  as a plain form (mode=offline), with the same right-hand parameter sheet. A
  DegradedBanner explains "AI conversation is off; using the guided form. Grounded
  matching still works."
- Quantities: identical (pure quantities.py formulas), so the offline estimate is
  numerically identical to the AI one for the same answers.
- Group composition + coverage: the composer vector probes use the embedding model
  + Qdrant, independent of the LLM key, so groups are still DB-grounded offline.
- Multi-pass mapping: passes 1-3 are deterministic (vector rank + unit reconcile +
  benchmark sanity); the only thing missing without a key is the optional pass-3
  agent reasoning over survivors. Offline gets the full multi-pass minus LLM rerank.
- No vectors / wrong-currency catalogue: groups land as honest gap / needs_human,
  never a fabricated rate. The deterministic parameter templates per detected
  object type still produce a complete, editable, staged group board the user can
  price manually or after switching catalogue.

Degradation reasons surfaced are the existing no_ai_key | no_vectors | no_catalogue
on IntakeState.degraded_reason and ProgressResponse.degraded_reason.

---

## 7. IMPLEMENTATION PLAN (ordered work packages for parallel agents)

Sizing: S = under half a day, M = about a day, L = two-plus days. WP1 and WP2 are
backend-contract-first and unblock the UI. WP3-WP5 can run in parallel after WP1.
WP6 (UI unification) depends on WP1 only. WP7 depends on WP4.

WP1 (M) - WorkGroup metadata standardisation. Backend.
  Files: intake.py (_persist_group, _compose, _compose_custom), service.py
  (_build_groups), schemas.py (GroupDetail add derivation, assumptions, source,
  mapping_trace read-through from metadata_).
  Tests: a composed group carries derivation, assumptions, source; a measured
  group carries source in {file, cad}.
  Live verification: POST /intake for "kitchen renovation 8 m2", confirm
  parameters, GET a group detail, see derivation "perimeter x height" and source=dialogue.

WP2 (S) - Benchmark band data + meta exposure. Backend.
  Files: benchmarks.py (NEW), schemas.py (MetaResponse add rate_sanity_band_factor),
  router.py (/meta returns it).
  Tests: every benchmark key is a real (trade, unit); band factor default 8x;
  median helper handles empty/one-candidate sets.
  Live verification: GET /api/v1/ai-estimator/meta returns rate_sanity_band_factor.

WP3 (L) - Multi-pass mapping refactor. Backend. Depends: WP1, WP2.
  Files: service.py (run_matching split into _pass_semantic / _reconcile_units /
  _rate_sanity; write mapping_trace; log per-pass AiEstimatorStep).
  Tests: unit reconcile demotes an m3 candidate for an m2 group; rate-sanity flags
  an injected 100x outlier and caps its confidence at LOW without dropping the real
  top candidate; the trace has exactly three passes; no-key path runs all three
  deterministic passes.
  Live verification: run a kitchen intake to matching, open the run timeline, see
  three observation steps (semantic / unit_scale / rate_sanity) per matched batch.

WP4 (S) - GroupDetail mapping-trace serialisation. Backend. Depends: WP3.
  Files: schemas.py (GroupDetail.mapping_trace), service.py (group_to_detail reads
  metadata_.mapping_trace).
  Tests: a matched group detail includes the three-pass trace.
  Live verification: GET /runs/{id}/groups/{gid} returns mapping_trace.passes.

WP5 (M) - Mapping recall/sanity harness. Backend tests. Depends: WP3.
  Files: backend/tests/.../test_mapping_passes.py (NEW), reuse the intake golden
  fixtures from the v2 plan.
  Live verification: run the harness in-process against the live ranker; assert the
  gap-disclosure-correctness metric is 1.0 (every flagged outlier is surfaced).

WP6 (L) - Frontend route unification. Frontend. Depends: WP1.
  Files: AiEstimatorPage.tsx (render IntakePanel for the text tab; wire onFinished
  to set runId and jump to matching), reuse @/features/ai/intake. Keep files/BIM/
  documents on the existing path.
  Tests: a /ai-estimator free-text "New estimate" shows the guided dialogue, not a
  parse_text_scope run; finishing the board lands on the matching stage of the same page.
  Live verification: open /ai-estimator, New estimate, Free text, type a kitchen
  request, answer the chips, confirm the sheet, edit the board, confirm, see
  grounded rates with the three-pass trace.

WP7 (M) - Stage3 mapping-trace UI + outlier badge. Frontend. Depends: WP4, WP6.
  Files: Stage3Match.tsx (a "why this rate" expander reading mapping_trace; a
  rate-sanity outlier badge; coverage carried from the group).
  Tests: a group with a flagged outlier shows the badge; the expander lists three passes.
  Live verification: in matching, expand a group and read its semantic ->
  unit_scale -> rate_sanity story.

WP8 (M) - i18n sweep. Cross-cutting. Depends: WP6, WP7.
  Files: locale files via the i18n-sweep skill. New keys: aiest.map.pass_semantic,
  aiest.map.pass_unit_scale, aiest.map.pass_rate_sanity, aiest.map.outlier,
  aiest.group.derivation, aiest.group.assumptions, enriched aiest.why.*.
  Live verification: switch to RU/DE, confirm no raw keys leak on the dialogue,
  board, or matching trace.

Every work package is additive. The existing four-stage pipeline, its endpoints,
its tests, the QuickEstimate surface, and the measured-source paths are untouched
in behaviour; v3 only unifies the entry point and makes the mapping explicit.

---

## 8. TEST MATRIX (diverse sources, expected groups)

Run on the live backend with the bound catalogue (USA_USD on the reference
install). Expected groups are the curated default packages for the detected type
(grounded coverage varies because the catalogue is US/civil-heavy; the floor is
that the groups EXIST and are correctly staged, not that every one grounds green).

1. "kitchen estimate please" (dialogue) -> kitchen_reno; ask 1-2 rounds (area,
   finish, demo, plumbing/electrical). Groups: demo_strip, debris_removal (demo);
   floor_screed, plumbing_first_fix, electrical_points (rough); wall_plaster
   (close); wall_tiling, floor_tiling, painting_walls, painting_ceiling,
   sanitary_install (finish); commissioning.
2. "house renovation 120 m2" (dialogue) -> house_new or apartment_reno (ambiguous;
   if ambiguous show tiles); seed area=120; ask wall_construction / roof_type /
   finish. Groups (house_new): excavation, foundation, superstructure_walls
   (structure); floor_screed, plumbing_first_fix, electrical_points (rough);
   wall_plaster, roof_structure (close); painting_walls, ventilation (finish);
   commissioning.
3. "new house 2 storeys" (dialogue) -> house_new; seed storeys=2; ask
   gross_floor_area, wall_construction, roof_type. Groups: as case 2 house_new.
4. "bathroom refurb 5 m2 turnkey" (dialogue) -> bathroom_reno; reach sheet in <=1
   round (highly specified). Groups: demo_strip, debris_removal (demo);
   floor_screed, waterproofing, plumbing_first_fix (rough); wall_plaster (close);
   wall_tiling, floor_tiling, sanitary_install (finish); commissioning.
5. Uploaded Excel BOQ rows ("120 m2 brick wall", "30 m3 C25/30 foundation",
   "2 pcs steel door") (file; direct run, no dialogue). Groups: one per line: brick
   wall (m2, masonry), foundation (m3, foundations/concrete), steel door (pcs).
   Multi-pass maps each to a grounded rate or needs_human.
6. CAD/BIM import (converted model: walls + slabs + doors) (cad; direct run).
   Groups: signature groups by ifc_class: IfcWall (m2), IfcSlab (m2/m3), IfcDoor
   (pcs), each carrying the ifc_class hard filter into pass 1.

Per-case assertions:
- Cases 1-4: detected type matches; round count never exceeds 3; the staged group
  set is a superset of the type default_packages; every group has a quantity
  (estimated flagged where proxy-derived); coverage is the REAL probe band.
- Cases 5-6: groups map 1:1 (BOQ) or by signature (CAD); each group runs the three
  mapping passes; dimensionally incompatible candidates are demoted in pass 2;
  outliers flagged in pass 3.
- All cases: no fabricated rate anywhere; gaps disclosed; preview rolls up
  per-currency; apply is gated on the assembly checkpoint.

---

## 9. INVARIANTS PRESERVED (non-negotiable)

- AI proposes, human confirms. Two explicit checkpoints (parameter sheet, group
  board) before any rate is matched; groups stay editable/deletable/addable; the
  apply checkpoint gates the BOQ write.
- Rates never invented. The dialogue and composer shape only the QUERY; every rate
  comes from ranker_qdrant.rank over the cost DB and is backfilled from the SQL
  cost table. Passes 2 and 3 re-rank, rescale or flag, never invent. A group with
  no compatible candidate is an honest needs_human / gap.
- Confidence is real. Type confidence, coverage, candidate score and band are real
  probe/model floats or null, never a placeholder.
- Currencies never blended; per-currency subtotals; FX rollup in the project base
  currency (reused from match_elements.apply_to_boq).
- Graceful degradation. No AI key -> curated questionnaire + deterministic passes;
  no vectors / wrong catalogue -> honest gaps; the flow never 500s.
- Max 3 clarification rounds, enforced in the machine and the API.
- Single-DB, lightweight, additive. No new tables, no new heavy dependency; new
  fields ride existing metadata_ JSON; new data is pure Python.

---

## 10. OPEN QUESTIONS AND CHOSEN DEFAULTS

1. Surface unification: make the conversational intake the front door of
   /ai-estimator (the founder named route) and KEEP /ai-estimate (QuickEstimatePage)
   as a lightweight quick path, or fold the quick path into /ai-estimator entirely?
   Default chosen: keep both, mount the SHARED IntakePanel on both, unify on
   /ai-estimator as primary. Reversible.
2. Rate-sanity benchmark source: real curated price bands per region (heavier,
   needs maintenance) vs the per-run catalogue-relative median + band factor
   (self-calibrating, currency-agnostic). Default chosen: catalogue-relative median
   with an 8x band factor exposed on /meta, because it keeps the "rates only from
   the DB" invariant and needs no price-book maintenance.
3. Ambiguous type detection (case 2, "house" can be new-build or renovation):
   auto-pick the longest-synonym match or always show tiles on ambiguity? Default
   chosen: follow the existing detect_project_type rule (longest distinct synonym
   wins, otherwise show the ten tiles for a one-click pick), matching shipped behaviour.
