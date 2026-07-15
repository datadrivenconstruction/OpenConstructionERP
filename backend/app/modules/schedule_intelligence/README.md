# oe_schedule_intelligence

A **thin orchestration + governance layer** over the existing
`schedule_advanced` / `risk` / `variations` / `contracts` / `full_evm` modules.
It flags delay risk early, attributes cause/responsibility, quantifies
critical-path impact, and presents human-approved **claim-vs-accelerate**
decisions — with commercially-sensitive figures locked and a uniform confidence
framework gating every insight.

It does **not** re-implement CPM, delay quantification, Monte-Carlo risk, rate
tables, or the approval/audit machinery — those already exist and are reused.
Rows that live elsewhere (a `delay_event`, a `constraint`, a look-ahead
activity) are referenced by **string ref**, never copied: one source of truth.

## Status — Phase 0 (governance foundation) ✅

Phase 0 builds the trust guarantees the spec (`docs/business.md`) puts first,
before any apply flow:

| Area | What's here |
|---|---|
| **E5.2 locked-figure guard** | `locked_guard.py` — pure policy-as-code. Once a figure is locked, no flow may change it; byte-identical re-writes pass, mutations raise `LockedFigureViolation`. Backing store: `locked_figure` table. |
| **E5.3 confidence framework** | `confidence.py` — one uniform `score / band / rationale` for every insight. Corroboration bonuses first, caps last (hard ceiling); a degraded feed's reduced confidence is always explained, never silent. Config-as-data: `confidence_config` table (versioned). |
| **Data model** | `models.py` — `confidence_config`, `locked_figure`, plus the insight tables the later phases fill: `readiness_result` (E1), `risk_score` + `risk_factor` (E2), `decision` (E4). |
| **RBAC** | `permissions.py` — `schedule_intelligence.{read,watch,score,attribute,quantify,decide,apply,configure,lock}`, registered in `__init__.on_startup()`. Apply flows reuse the `app/core` approval gate + audit — no new gate. |
| **API** | `router.py` — governance surface: lock / list / unlock / dry-run-verify locked figures; get / versioned-upsert / preview confidence config. Mounted at `/api/v1/schedule-intelligence/`. |

Every project-scoped endpoint is gated twice: `RequirePermission(...)` (RBAC)
+ `verify_project_access(...)` (404-on-deny IDOR defence).

## Status — Phase 1 (E1 Readiness / "Watch") ✅

Turns `schedule_advanced`'s binary ready/not-ready into a deterministic
**Ready / At-risk / Blocked** classification per look-ahead activity, persisted
as `readiness_result` snapshots.

| Area | What's here |
|---|---|
| **Engine** | `readiness_engine.py` — a **pure** classifier (no I/O, no clock). `classify_activity` / `evaluate_look_ahead` apply a hardcoded truth table over raw constraints + optional CPM float; `run_digest` hashes the canonical inputs into the `evaluation_run_id` so a re-run is idempotent (E1.1-AC6). Each verdict carries a `binding_constraint_ref`, traceable `drivers[]` (P4), a `float_burn` delta vs the prior snapshot, and a uniform E5.3 confidence. |
| **Correctness catch** | Consumes **raw** constraint rows: `cannot_clear → BLOCKED` is handled here, because `schedule_advanced.constraint_ready_state` treats `cannot_clear` as *not open* and would call a permanently-blocked activity "ready". Open-blocker subset is exactly `{open, in_progress, escalated}`. |
| **Service** | `service.evaluate_readiness` derives the look-ahead's project (IDOR 404), pulls constraints via `schedule_advanced`, resolves best-effort CPM float (one swappable `_resolve_float` against `oe_schedule_activity`), runs the engine under the project's confidence policy, and snapshots one idempotent run. `list_readiness` returns the latest run. |
| **API** | `POST …/projects/{id}/look-aheads/{la}/readiness/evaluate` (gated `.watch`) and `GET …/projects/{id}/readiness` (gated `.read`). |

The `task_ref ↔ schedule-activity` float join is intentionally best-effort for
the MVP: unresolved float degrades confidence (never silently), and `_resolve_float`
is the single swap-point when a richer task↔activity mapping lands.

## What comes next

- **Phase 2 — E2 Risk (Score):** `risk_scoring.py`, a weighted-factor forward
  score behind a pluggable `Scorer` interface (ML out of MVP).
- **Phase 3–4 — E3/E4 (Attribute → Quantify → Decide):** attribution over the
  existing `delay_event`, quantification via `delay_engine.impacted_as_planned`,
  and the priced claim-vs-accelerate `decision_engine.py`.
- **Phase 5 (post-MVP) — E5.5:** governed P6 write-back (read-only until then).

## Migration note

`migrations/v0001_initial.py` holds the full inspector-guarded DDL for all six
tables but is **inert** — Alembic only runs `backend/alembic/versions/`. In dev
the tables materialise via boot-time `metadata.create_all` (the models are
imported in `backend/alembic/env.py`). To fold the migration into the live
chain, either autogenerate (`make migrate-new MSG="schedule_intelligence
initial"`, then delete the draft) or move it into `alembic/versions/` and set
`down_revision` to the current head — after the repo's multi-head Alembic graph
is consolidated.

## Tests

- `backend/tests/unit/test_oe_schedule_intelligence_*` — pure guard/confidence
  units (incl. the E5.2 negative-injection suite) + manifest/schema/permission
  checks.
- `backend/tests/integration/test_oe_schedule_intelligence_*` — full governance
  stack round-tripped on real PostgreSQL, plus an app-boot + endpoint-mount
  check.

Run just this module's suite: `make module-test NAME=oe_schedule_intelligence`.
