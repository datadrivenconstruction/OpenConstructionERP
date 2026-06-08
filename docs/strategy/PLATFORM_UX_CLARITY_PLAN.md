# Platform-wide UX clarity plan

Resumable plan. Goal (founder directive): every module on the whole platform is clear and easy to
use, fully translated in all 27 supported languages, and signed off only after thorough testing with
real clicks, screenshots, and screenshot review (3 to 4 deep passes). Not just a few modules.

## How to resume (read this first)

1. Read this whole file, then `docs/strategy/GUIDANCE_STANDARD.md` (the 8-item per-module checklist
   and the live per-module progress table). That table is the single source of truth for what is done.
2. Companion plans: `ERP_PLATFORM_BUILD_PLAN.md` (financial/ERP build) and
   `POINTCLOUD_AND_SPATIAL_PLAN.md` (reality capture). The clarity standard and the testing gate in
   this file apply to those builds too.
3. Reuse first. The shared components in section 3 already exist - rollout adds usages, it does not
   reinvent. The 5 new components are built once in Wave 0.
4. Every wave ends with the verification gate (section 6): the visual acceptance harness
   `frontend/qa-tests/ux-acceptance.mjs` (3 to 4 passes, screenshots reviewed by eye) plus
   `tsc --noEmit | grep TS1117` (i18n dup check) plus the 27-locale i18n sweep. Green unit tests are
   necessary but not sufficient.
5. Locales: source of truth is the file glob `frontend/src/app/locales/*.ts` (27 files: English source
   + 26 translation targets including `ru`). Never a hand-typed locale list. Verify each with
   `frontend/scripts/i18n-diff.cjs`; zero missing and zero English-equal for every new key.
6. Brand rule (strict): no competitor/vendor/product names anywhere in code, commits, or UI.
7. State: Wave 0 not started. Open questions in section 8 carry recommended defaults; the two marked
   FOUNDER are the only hard blockers (canonical glossary wording sign-off, IA duplicate-surface
   sequencing). Everything else proceeds on the recommended default.

## Why this plan (grounded, verified)

This was produced by a parallel audit (existing-infrastructure inventory + per-cluster module audits)
and an adversarial critique, with every load-bearing claim checked against the tree, and was then
corroborated by a real deep acceptance pass (boq/finance/ai-estimator across Latin/Cyrillic/CJK/RTL).

The big finding, confirmed both ways: the platform's intros, empty-states, and translations are
genuinely already strong (Arabic fully RTL-mirrored, Japanese fully translated including intro
banners; 100 `intro_title` + 113 `intro_more` keys; `DismissibleInfo` on 18+ pages; `ProductTour`
engine with 7 tours and real anti-nag). So the real gap is NOT intros/i18n/empty-states. It is:

- field-level "what's this?" help on jargon (finance: COA/committed/forecast/EVM/WIP; BIM: LOD/clash;
  HSE: JSA/PPE/CAPA; CDE: ISO 19650 codes) - `InfoHint` is used in only ~9 files, ~31 `_help` keys;
- a shared glossary so a term reads identically everywhere;
- guided tours beyond the 7 that exist;
- explanatory errors (most modules surface raw `e.message`);
- self-explaining AI (one shared confidence + suggestion pattern, not per-module copies).

The heavy work is therefore content authoring (plain-language English) + translation into 26 locales,
not engineering. Waves are cut by copy-budget, not route count. Translation is a gated step at the end
of each wave, never assumed free.

Verified prod defects to fix in-flight (not separate tickets):
- `features/boq/AISmartPanel.tsx:679` renders a raw lowercase enum (`high`/`medium`/`low`) as the
  visible confidence label - an untranslated-string leak already shipped. Fix when promoting the
  shared `ConfidenceBadge`.
- `/reporting` shows a perpetual grey `SkeletonLoader` with zero empty-state guidance, and
  `PMDashboard`/`SiteDashboard` print literal `'N/A'` instead of going through `fmt()`.
- 100 `intro_title` vs 113 `intro_more`: 13 pages have a "Show more" walkthrough with no base
  title/body. Reconcile during the owning wave.

## The standard: "every module page is self-explaining"

A page is DONE only when all 8 checks pass, each built from existing shared primitives.

1. INTRO / EMPTY STATE - mandatory `<DismissibleInfo storageKey={routeSlug}>` directly under
   `PageHeader`; `title=<feature>.intro_title` (framed by the user's goal, not the module name),
   `body=<feature>.intro_body`, optional `more={<IntroRichText text={t('<feature>.intro_more')} />}`.
   Lists/grids ALWAYS render `<EmptyState>` via `standardEmptyCopy(t, entity)` with one primary CTA.
   Never a perpetual `SkeletonLoader` - resolve to data or to `EmptyState` inside the query lifecycle.
2. FIELD-LEVEL HELP (bounded) - a curated 10 to 20 terms per module, not every field. Each
   non-obvious term gets `<InfoHint inline text={t('glossary.<term>')} />` next to its label, reading
   the SHARED glossary key. Labels read "Plain language (jargon term)". In AG Grid headers use the new
   `GridHeaderHelp` header component (plain everyday terms are skipped - target jargon only, no wall of
   (i) icons).
3. GUIDED FIRST RUN - full per-module tour registered in `TOUR_REGISTRY` only for ~6 to 8 complex core
   flows (estimating/BOQ, BIM, takeoff, finance, governance/validation, AI estimator). The long tail
   gets a `DismissibleInfo` "more" walkthrough via `IntroRichText` instead. Auto-start once,
   re-launchable from `ModuleHelpButton` + Help, never nags (the engine already enforces this).
4. EXPLANATORY ERRORS - new shared `<ErrorState>` rendering WHY + the fix + Retry; Toast carries a
   short title that opens the same block; form validation is field-level reason+fix. Depends on the
   backend error envelope (section 8 Q5): generic `error_explain.*` fallback until a stable code exists.
5. AI EXPLAINS ITSELF - new shared `<ConfidenceBadge>` + `<SuggestionCard>` {icon, title, confidence,
   plain reason, Accept/Edit/Reject}. Never auto-applies. Retire the per-module copies.
6. SENSIBLE DEFAULTS / PRESETS - create flows pre-fill from `useProjectContextStore`
   (currency/region/classification/units) and offer presets/examples; never a blank form; restore the
   last selection.
7. PROGRESSIVE DISCLOSURE - simple by default, advanced behind a toggle; long-form via `IntroRichText`
   "Show more"; honour `useViewModeStore` (Simple/Advanced).
8. CONSISTENCY - one concept = one term = one i18n key = one icon. Fixed header anatomy:
   `Breadcrumb -> PageHeader -> DismissibleInfo -> KPI strip -> content`. Theme tokens only; every
   string through `t()`; currency never defaulted.

Definition-of-done per page: a brand-new user with no external docs understands what the screen does
and completes the primary task from on-screen guidance alone, in their language, verified by the
testing gate.

## Components (reuse first, 5 new in Wave 0)

Reuse as-is (rollout only adds usages, API frozen): `DismissibleInfo`, `IntroRichText`, `EmptyState` +
`standardEmptyCopy`, `InfoHint`, `ProductTour` + `TOUR_REGISTRY` + `TourId`, `ModuleHelpButton`,
`PageHeader`, `Breadcrumb`, `Toast` + `useToastStore`, `CertaintyBadge` (visual basis for confidence),
`WhatsNewCard`, `useProjectContextStore`, `useModuleInfoStore`, `useViewModeStore`.

New in Wave 0 (all reuse clsx + lucide-react + existing primitives, no heavy deps):
- `ConfidenceBadge` (`shared/ui/ConfidenceBadge.tsx`) - token-based (`semantic-success/warning/error`),
  labels `confidence_badge.high|medium|low`. Accepts EITHER a pre-resolved `band`/`level` OR a `score`,
  and never re-thresholds a score whose banding the backend already owns (costs certainty passes the
  server band through unchanged). Score cutoffs are frozen only after Wave 0 signs off the real AI-match
  distribution.
- `SuggestionCard` (`shared/ui/SuggestionCard.tsx`) - `{icon, title, reason, confidence, onAccept,
  onEdit, onReject, learnMore?}`; reason/title pre-translated; actions optional (read-only review);
  never auto-applies.
- `ErrorState` (`shared/ui/ErrorState.tsx`) - `{title=whyKey, hint=fixKey, onRetry?, supportHref?}`;
  pairs with a Toast. Gated on the backend error envelope; generic fallback until then.
- `GlossaryTerm` (`shared/ui/GlossaryTerm.tsx`) - thin wrapper over `InfoHint` reading `glossary.<term>`
  (+ `glossary.<term>_example`). Does not grow its own popover/positioning lib.
- `GridHeaderHelp` (AG Grid `headerComponent`) - renders the header text + an (i) trigger with the
  glossary/help popover, so check 2 reaches grid headers (BOQ/estimating, where the densest jargon
  lives; `BOQGrid.tsx` uses plain-string `headerName` today).

Extend (data only, no engine change): `TourId` union + `TOUR_REGISTRY` for the ~6 to 8 core-flow tours.
Optional, Wave 5: `GlossaryBrowser` at `/help/glossary`, lazy-loaded.

## Glossary + i18n conventions

Glossary is a data problem, not copy duplication. One flat `glossary.*` family in `en.ts`:
`glossary.<term>` = plain-language definition (~20 words max, plain first then jargon in parentheses);
finance/measurement terms add `glossary.<term>_example` = one-line worked example. Surfaced only via
`GlossaryTerm` and `InfoHint` (and `GridHeaderHelp` in grids) - all reading the same key, so wording is
identical across modules and all 26 locales.

Seed (~40 P0 terms from the audits): retention, variance, CPI, SPI, EVM, committed, forecast, payable,
receivable, float, makespan, crew_flow, LOD, IDS, COBie, clearance, penetration, set_a_b,
suitability_code, wip_shared_published, datum, coordinate_system, anchor_drift, capa, jsa, ppe, ncr,
snag, escrow, noc, spa, price_matrix, din276, nrm, gaeb, masterformat, unit_rate, assembly, takeoff.

New key families: `glossary.<term>` / `glossary.<term>_example`; `confidence_badge.high|medium|low`
(+ `.score`); `suggestion.accept|edit|reject|why|learn_more`; `error_explain.retry|contact_support`
(generic) + per-module `<feature>.err_<case>_why`/`_fix`; per-module `<feature>.<field>_help`;
per-module `<feature>.intro_title|intro_body|intro_more`; per-module `tour.<module>.step.N.title|body`.

Rules: zero hardcoded user strings; double-quote keys only (run `tsc --noEmit | grep TS1117` after
edits); `defaultValue` mandatory so a missing key never shows a raw key; one i18n sweep per wave so new
keys land in all 26 locales before merge; canonical English glossary wording is founder-signed in Wave 0
before translation (the ×27 multiplier makes re-wording expensive). Existing hardcoded-English debt
(status enums in subcontractors/variations/service/equipment/changeorders/assets, benchmark labels,
/reports error strings, DIN 276 literal in QuickEstimate, regional-exchange trade sections) folds into
each module's check-8 sweep.

## Verification & testing gate (per wave, mandatory - the founder's top bar)

"The main thing is very thorough testing through real clicks, screenshots, and screenshot analysis,
3 to 4 deep passes." Every wave ends here; no module is done until it passes and the screenshots are
actually looked at.

Harness: `frontend/qa-tests/ux-acceptance.mjs` (logs in through the real demo UI, screenshots to
`qa-tests/ux-acceptance/<module>/`, machine report to `report.json`). The 4 passes:
1. SMOKE - every route: screenshot, console + page errors, no login redirect, no error-boundary crash,
   not empty.
2. INTERACT - real non-destructive clicks through the core flow (help/"what's this", empty-state CTA,
   primary panel/drawer, tabs); screenshot each state; zero new console errors.
3. I18N - reload across a Latin/Cyrillic/CJK/RTL locale spread plus the lowest-coverage locales; scan
   for raw-key and English-equal leaks; the RTL pass must show a mirrored layout. Confirms the 27-locale
   gate visually, not just by key count.
4. GUIDANCE - detect which of the 8 items are present; screenshot the help/tour open state.

Plus, per wave: `tsc --noEmit | grep TS1117` (zero dup keys) and `i18n-diff.cjs` per locale (zero
missing / English-equal on new keys). Sign-off rule: a human (or the agent on the founder's behalf)
reads the screenshots from all passes and confirms the screen is clear, correct, and fully translated.
No green-checkmark-only sign-off. Run order: `tsc -b` -> unit/component tests -> visual gate -> commit.

## Wave rollout (cut by copy-budget, parallel within a wave)

### Wave 0 - Foundation (blocks all later waves; build first)
- [x] `ConfidenceBadge`, `SuggestionCard`, `ErrorState`, `GlossaryTerm`, `GridHeaderHelp` (new) + tests
      (24 component tests green; all in `shared/ui`, exported from the barrel)
- [x] Generic key families `confidence_badge.*` + `suggestion.*` + `error_explain.*` +
      `glossary.example_prefix` in `en.ts`; one i18n sweep -> all 26 locales (11 keys x 26 = 286,
      verified present + non-English, `{{pct}}` placeholder preserved)
- [~] Seed `glossary.*` (~40 P0) - canonical English DRAFTED in `GLOSSARY_DRAFT_v0.md`, awaiting the
      founder sign-off (Q1) before the x27 translation; `GlossaryTerm`/`GridHeaderHelp` already read the
      keys and degrade gracefully (label-only) until the definitions land
- [ ] Extend `TourId` union - DEFERRED: `TOUR_REGISTRY` is `Record<TourId, Step[]>`, so a new id needs
      real (translated) step content; folded into Wave 2 where the BOQ/BIM/takeoff tours are authored
- [x] Retire the local `ConfidenceBadge` in `AISmartPanel` + fix the raw-enum label leak (line 679)
- [x] Backend error envelope (Q5) - decided: `{reason_key, fix_key, retryable}` with generic
      `error_explain.*` fallback; `ErrorState` accepts pre-resolved why/fix strings so call sites can
      wire the envelope incrementally
- [~] `ConfidenceBadge` banding (Q2) - provisional cutoffs live in `bandForScore` (single source);
      marked provisional in code, freeze after the real AI-match distribution is reviewed
- [x] `docs/strategy/GUIDANCE_STANDARD.md` with the 8-item checklist + per-module progress table
- [x] Locale list locked as the `locales/*.ts` glob (26 incl. ru); collapse-to-topbar re-show final (Q7)
- [ ] IA duplicate-surface merge decision (Q3 - FOUNDER) before guiding the AI-estimate trio / documents
- [ ] Visual gate on a sample - runs in Wave 1 when the components hit routed pages (the new
      components are unit-tested + tsc-clean; the AISmartPanel integration is the first live surface)

### Wave 1 - Broken / highest-traffic (worst offenders, parallel)
- [x] `reporting` - ALREADY DONE (the audit's defect list was stale): the perpetual skeleton is gated on
      the fast `projects.list()` only, `'N/A'` is gone (a shared `EMPTY` placeholder via `fmt()`/`fmtNum()`/
      `toMoneyNum()`), `EmptyState` + error+retry blocks (`StatsErrorBlock`, `loadError`) and the intro
      `DismissibleInfo` are all present. OPEN: the empty placeholder is a literal em-dash glyph
      (`EMPTY = '-'` uses U+2014) - confirm whether the strict no-em-dash-in-user-text rule should swap it
      for a hyphen. Remaining gated items below are unchanged.
- [ ] `documents`/`files` - intro (only flagship with none); resolve IA naming first
- [ ] `validation` - persist last BOQ/report (check 6); shorten the 4-click path
- [ ] `match-elements` - intro + SuggestionCard/ConfidenceBadge (only if IA decision = keep)
- [ ] `ai-estimator` - intro + field help + SuggestionCard + full tour (only if IA decision = keep)
- [ ] `dashboard`/`finance` - glossary: variance/CPI/SPI/EVM/payable/receivable
- [ ] Verification gate + translation

### Wave 2 - AI + estimating/spatial core
- [ ] ai-estimate, project-intelligence, takeoff, dwg-takeoff, geo-hub, coordination, clash,
      bim-requirements, requirements, costs, costmodel, bim
- SuggestionCard on all AI surfaces; field help + glossary (LOD/clash Set A-B/clearance/datum); full
  tour only for BOQ/BIM/takeoff core, the rest get DismissibleInfo "more"
- [ ] Verification gate + translation

### Wave 3 - Field + Quality + Safety + Communication + Documents
- [ ] daily-diary, field-reports, service, inspections, ncr, punchlist, closeout, safety, hse-advanced,
      rfi, meetings, contacts, correspondence, cde, submittals, transmittals, markups, photos
- Focus checks 2/3/4 (intro baseline already 16/18); DismissibleInfo "more" instead of 18 tours;
  explanatory errors on half-built workflows; glossary HSE (JSA/PPE/CAPA) + CDE ISO 19650; enum i18n
  sweep; resolve UUID->name; remove "Coming Soon" cards
- [ ] Verification gate + translation

### Wave 4 - Controls / Governance / Real-estate / Admin
- [ ] project-controls, bi-dashboards, dashboards (de-hardcode en-US), property-dev (16 tabs,
      GlossaryTerm + persist dev context), governance, settings (setup tour), users, modules,
      integrations, audit-log, about
- Intros on the zero-guidance admin pages (users/modules/audit-log); glossary reused from earlier waves
- [ ] Verification gate + translation

### Wave 5 - Polish + GlossaryBrowser + full verification
- [ ] `/help/glossary` `GlossaryBrowser` (lazy-loaded) over existing keys
- [ ] Full i18n sweep verification (raw-key + verbatim-English crawl, 26 locales)
- [ ] qa-crawler: every route passes the 8-item checklist
- [ ] Backfill anything missed in Waves 1-4

## Open questions and decisions

Recommended defaults stand unless the founder overrides. Only the two marked FOUNDER block Wave 0.

1. Glossary scope (FOUNDER, sign-off): the ~40 seed terms above are the proposed P0 set. Worked-example
   line on the densest finance terms first (EVM/CPI/SPI/variance/retention/committed/forecast), extended
   to the rest as a fast-follow. Founder signs the canonical English definitions before translation.
2. ConfidenceBadge banding (decided, verify in Wave 0): band/level passthrough; thresholds only where
   the backend does not already band. Confirm proposed score cutoffs against the real (not synthetic)
   AI-match distribution before freezing.
3. IA duplicate-surface sequencing (FOUNDER): merge/relabel the AI-estimate trio
   (ai-estimate/ai-estimator/match-elements), the 3 Monte-Carlo entry points, Carbon/Sustainability,
   Bid/Tendering, and documents/files BEFORE guiding them, to avoid paying translation twice. Wave 1
   AI routes are gated on this. Recommended: decide naming first, guide once.
4. Tour budget (decided): full 8-step tours capped at ~6 to 8 core flows; long tail gets DismissibleInfo
   "more".
5. ErrorState backend contract (decided, build in Wave 0): standardize `{reason_key, fix_key,
   retryable}`; generic `error_explain.*` fallback on raw-message endpoints until a stable code exists.
6. advancedOnly (decided): move the backbone money pages (/finance, /analytics, /reports, /cde) out of
   Simple-only so they are discoverable by default; confirm per page during its wave.
7. DismissibleInfo re-show (closed): collapse-to-topbar is final; no permanent-dismiss. Do not reopen.

## Progress log (append-only)
- 2026-06-08: Wave 0 core built. The 5 shared guidance components (`ConfidenceBadge`, `SuggestionCard`,
  `ErrorState`, `GlossaryTerm`, `GridHeaderHelp`) landed in `shared/ui` with 24 passing component tests
  and barrel exports, grounded on the existing design system (`Badge`/`Button`/`InfoHint`/semantic
  tokens). The 11 generic guidance keys were added to `en.ts` and translated into all 26 locales (one
  agent per locale, deterministic insertion, verified present + non-English with `{{pct}}` preserved).
  The local `ConfidenceBadge` in `features/boq/AISmartPanel` was retired in favour of the shared one,
  closing the shipped raw-enum (`high`/`medium`/`low`) label leak at line 679. tsc clean. The ~40-term
  glossary English is drafted in `GLOSSARY_DRAFT_v0.md` and is the one open Wave-0 blocker (founder
  sign-off, Q1); Q3 (IA merge) still gates the Wave 1 AI routes. TourId extension deferred to Wave 2
  (it needs real translated tour steps). Next: founder signs the glossary, then Wave 1 rollout.
- 2026-06-08: Plan created from the platform-wide UX audit (8-agent workflow + adversarial critique,
  every claim tree-verified) and corroborated by a real deep acceptance pass (boq/finance/ai-estimator,
  Latin/Cyrillic/CJK/RTL). Standard, components, glossary, waves, and the testing gate locked. The
  cluster-2 audit agent (scheduling/cost-control/commercial/procurement) failed to return structured
  output; that cluster's per-module gaps are filled from the broad acceptance sweep instead. No
  rollout code written yet. Next: Wave 0 components + glossary seed + GUIDANCE_STANDARD.md.
