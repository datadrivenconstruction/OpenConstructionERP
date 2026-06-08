# Guidance standard + per-module progress

Single source of truth for how clear every module is and what is left. Companion to
`PLATFORM_UX_CLARITY_PLAN.md` (the why and the waves). Update the table below as each page passes the
checklist and the verification gate.

## The 8-item checklist (a page is DONE only when all pass)

1. INTRO / EMPTY STATE - `DismissibleInfo` under `PageHeader` (goal-framed title/body); lists render
   `EmptyState` via `standardEmptyCopy` with one CTA; never a perpetual `SkeletonLoader`.
2. FIELD-LEVEL HELP - curated 10 to 20 jargon terms get `InfoHint`/`GlossaryTerm` reading shared
   `glossary.<term>`; grid headers use `GridHeaderHelp`; everyday terms skipped.
3. GUIDED FIRST RUN - full tour only for the ~6 to 8 core flows; long tail gets a `DismissibleInfo`
   "more" walkthrough; auto-start once, re-launchable, never nags.
4. EXPLANATORY ERRORS - `ErrorState` (WHY + fix + Retry) inline; Toast opens the same; form validation
   field-level reason+fix; no raw `e.message`, no silent failure.
5. AI EXPLAINS ITSELF - `SuggestionCard` + `ConfidenceBadge` (plain reason + confidence +
   Accept/Edit/Reject); never auto-applies.
6. SENSIBLE DEFAULTS / PRESETS - pre-fill from project context; presets/examples; restore last choice;
   never a blank form.
7. PROGRESSIVE DISCLOSURE - simple by default, advanced behind a toggle; honour `useViewModeStore`.
8. CONSISTENCY - one concept = one term = one key = one icon; fixed header anatomy; theme tokens only;
   every string via `t()`; currency never defaulted.

A page is signed off only after the verification gate in `PLATFORM_UX_CLARITY_PLAN.md`: the 4-pass
visual acceptance harness with screenshots reviewed by eye, `tsc --noEmit | grep TS1117`, and
`i18n-diff.cjs` clean for new keys across all 26 translation locales.

## Status legend

`ok` pass - `~` partial - `todo` not started - `n/a` not applicable - `gate` screenshots reviewed and
signed off. A row is DONE when all 8 are `ok`/`n/a` and `gate` is set.

## Baseline (from the platform audit + first acceptance pass)

Known platform-wide today, before rollout:
- C1 intro: broadly present (100 `intro_title` keys, `DismissibleInfo` on 18+ pages). Gaps:
  documents, users, modules, audit-log, and the 13 pages with `intro_more` but no base title/body.
- C1 empty/loading: `/reporting` ships a perpetual skeleton (broken); others mostly ok.
- C2 field help: near zero (`InfoHint` in ~9 files, ~31 `_help` keys). This is the main platform gap.
- C3 tours: 7 exist (global, boq, accommodation, bim, geo, propdev, dashboard); everything else todo.
- C4 errors: most modules surface raw `e.message`.
- C5 AI: per-module copies; `AISmartPanel` leaks a raw enum label (line 679).
- i18n: strong (95 to 99% per locale, RTL + CJK visually complete); new keys must keep it at 100%.

## Per-module progress

Wave 0 components and glossary unblock C2/C4/C5 everywhere, so those columns stay `todo` until Wave 0
lands. `gate` is set per row only after the harness screenshots are reviewed.

| Module (route) | Wave | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | gate |
|---|---|---|---|---|---|---|---|---|---|---|
| reporting (/reporting) | 1 | todo | todo | n/a | todo | n/a | ~ | ~ | todo | |
| documents/files (/documents,/files) | 1 | todo | todo | n/a | todo | n/a | ~ | ~ | todo | |
| validation (/validation) | 1 | ~ | todo | n/a | todo | n/a | todo | ~ | ~ | |
| match-elements (/match-elements) | 1 | todo | todo | n/a | todo | todo | ~ | ~ | todo | |
| ai-estimator (/ai-estimator) | 1 | ~ | todo | todo | todo | todo | ~ | ~ | todo | |
| dashboard (/dashboard) | 1 | ~ | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| finance (/finance) | 1 | ~ | todo | todo | todo | n/a | ~ | todo | ~ | |
| ai-estimate (/ai-estimate) | 2 | todo | todo | n/a | todo | todo | ~ | ~ | todo | |
| project-intelligence | 2 | todo | todo | n/a | todo | todo | ~ | ~ | todo | |
| takeoff (/takeoff) | 2 | ~ | todo | todo | todo | n/a | ~ | ~ | ~ | |
| dwg-takeoff | 2 | ~ | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| geo-hub (/geo) | 2 | ok | todo | ok | todo | n/a | ~ | ~ | ~ | |
| coordination | 2 | ~ | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| clash | 2 | ~ | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| bim-requirements | 2 | todo | todo | n/a | todo | n/a | ~ | ~ | todo | |
| requirements | 2 | todo | todo | n/a | todo | n/a | ~ | ~ | todo | |
| costs (/costs) | 2 | ~ | todo | n/a | todo | ~ | ~ | ~ | ~ | |
| costmodel | 2 | ~ | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| bim (/bim) | 2 | ok | todo | ok | todo | n/a | ~ | ~ | ~ | |
| boq (/boq) | 2 | ok | todo | ok | todo | ~ | ~ | ~ | ~ | |
| daily-diary | 3 | ok | todo | todo | todo | n/a | ~ | ~ | ~ | |
| field-reports | 3 | ok | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| service | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| inspections | 3 | ok | todo | todo | todo | n/a | ~ | ~ | ~ | |
| ncr | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| punchlist | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| closeout | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| safety/hse (/hse) | 3 | ok | todo | todo | todo | n/a | ~ | ~ | ~ | |
| hse-advanced | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| rfi (/rfi) | 3 | ok | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| meetings | 3 | ok | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| contacts | 3 | ok | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| correspondence | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| cde (/cde) | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| submittals (/submittals) | 3 | ok | todo | n/a | todo | n/a | ~ | ~ | ~ | |
| transmittals | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| markups | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| photos | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| scheduling (/scheduling) | 3 | ~ | todo | todo | todo | n/a | ~ | ~ | ~ | |
| project-controls | 4 | ~ | todo | n/a | todo | n/a | ~ | todo | todo | |
| bi-dashboards | 4 | ~ | todo | n/a | todo | n/a | ~ | todo | todo | |
| dashboards | 4 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| property-dev | 4 | ~ | todo | todo | todo | n/a | ~ | ~ | todo | |
| governance | 4 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| settings (/settings) | 4 | ~ | todo | todo | todo | n/a | ~ | ~ | ~ | |
| users | 4 | todo | todo | n/a | todo | n/a | ~ | ~ | todo | |
| modules | 4 | todo | todo | n/a | todo | n/a | ~ | ~ | todo | |
| integrations | 4 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| audit-log | 4 | todo | todo | n/a | todo | n/a | ~ | ~ | todo | |
| about | 4 | ~ | n/a | n/a | n/a | n/a | n/a | n/a | ~ | |
| contracts (/contracts) | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |
| procurement (/procurement) | 3 | ~ | todo | n/a | todo | n/a | ~ | ~ | todo | |

The Wave-2-and-later rows reflect the audit's read of current state; each is re-confirmed by the
acceptance harness when its wave starts (the cluster-2 commercial/procurement/scheduling rows are
refined from the broad acceptance sweep, since the cluster-2 audit agent did not return structured
output). Add rows as routes are discovered; the table is not yet exhaustive of all 110+ modules.

## Change log
- 2026-06-08: Standard and baseline seeded from the platform UX audit + first acceptance pass.
