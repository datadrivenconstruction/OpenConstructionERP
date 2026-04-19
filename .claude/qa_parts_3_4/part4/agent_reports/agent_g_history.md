# Agent G — History / Changelog / TODO Audit

Date: 2026-04-18 · Server: http://127.0.0.1:8080

## 1. CHANGELOG timeline (brief)

- **v1.9.0** (2026-04-17) — R1 critical bug fixes (8/33 items from ROADMAP_v1.9: #2, #5, #6, #8, #18, #23, #27, #33). #9 moved to R3, #13 to R2.
- **v1.8.0 → v1.8.3** (2026-04-17) — BOQ↔Takeoff/DWG/BIM linking, Documents cross-link, filmstrips, decorative backgrounds, Dashboard quick upload.
- **v1.7.0** (2026-04-15) — 35-task sprint: Tasks Kanban, Assemblies JSON, 5D editable, Finance cards, Schedule start date, Chat onboarding, unified padding.
- **v1.6.0/1.6.1** (2026-04-11 era) — BIM integration, polyline takeoff, BIM↔BOQ linked panel.
- **v1.5.x** — BOQ description editor, unit dropdown, ezdxf in Docker, Z_UP auto-rotation, tendering String(20)→100.
- **v1.4.x → v1.0** — collaboration locks (L1), security hardening, IDEAS, quality audits.

## 2. Tag vs CHANGELOG mismatch (critical/minor)

`git tag -l` returns v0.2.0, v0.2.1, v0.4.0, v0.7.0, v0.8.0, v0.9.0, v0.9.1, v1.0.0, v1.5.0–v1.5.2, v1.6.0, v1.8.0–v1.8.3, v1.9.0.

CHANGELOG declares these without git tags (**minor / process**):
**v1.1.0, v1.2.0, v1.3.22–1.3.32, v1.4.0–1.4.8, v1.5.3, v1.6.1, v1.7.0, v1.7.1, v1.7.2.** Also: ~30 changelog entries, 19 tags — AGENT_START.md's Version Bump Checklist step 6 (`git tag -a`) is routinely skipped.

Secondary: **AGENT_START.md says current version v0.8.0, phase 0** — completely stale; actual code is v1.9.0 with 20+ modules live.

## 3. Open items still outstanding

TASK_PROGRESS.md Wave 1 — **all 6 items still marked 🔲 TODO** (file never updated despite fixes in v1.7.0 changelog claiming "Contacts country_code, RFI field sync, 4 modals"). Confirmed below.

ROADMAP_v1.9.md open rounds: **R2 (7 items), R3 (14 items), R4 (4 items), R5 deploy** — 25 items not yet released.

## 4. Verification of TASK_PROGRESS Wave 1

**#31 Contacts country_code ≤ 2 chars — STILL OPEN (CRITICAL).**
`POST /api/v1/contacts/` with `country_code:"USA"` → 422 `string_too_long, max_length: 2`. Pydantic schema still enforces 2-char ISO. Also: `contact_type` now a required field (undocumented).

**#35 RFI creates but not visible — STILL OPEN (HIGH).**
`POST /api/v1/rfi/` → 200, returns valid RFI ID. `GET /api/v1/rfi/` (no filter) → `[]` (empty). `GET /api/v1/rfi/?project_id=<pid>` → returns the RFI. Backend list endpoint requires `project_id`; frontend calling the unfiltered list sees nothing.

Modals #29/30/33/34 (too-tall) — not verifiable via API; no changelog evidence of modal-height fixes in v1.7–1.9.

## 5. RECOMMENDATIONS.md — 5 verified (3 FIXED, 2 OPEN)

- **#1 PDF Export crash — FIXED.** `GET /boq/boqs/{id}/export/pdf/` → 200, 4271 bytes, no crash.
- **#2 Change Password 500 — FIXED.** `POST /users/me/change-password/` with `current_password/new_password` → 200 + new token.
- **#5 Tour persistence (onboarding state) — FIXED at API level.** `GET /users/me/onboarding/` returns `{completed, company_type, enabled_modules, interface_mode}`.
- **#3 CPM crash — NOT VERIFIED this run.** Requires seeded schedule. Remains listed as P1 open.
- **#6 BOQ duplicates / bulk delete — DESIGN OPEN.** No `/boq/boqs/batch/delete` endpoint in OpenAPI; dedup still a UI concern.

**NEW CRITICAL FINDING (regression):** After a valid `change-password` call where `new_password == current_password`, the subsequent `POST /users/auth/login` with the exact same credentials returns `HTTP 500 Internal Server Error` (reproduced twice, 3-second gap). Either the hash rotation broke the stored credential or the endpoint bypasses bcrypt verify-and-hash coupling. Demo account is now locked out until reseed.

## 6. TODO / FIXME / XXX / HACK hotspots

Backend `app/`: **16 occurrences across 7 files** — but only **5 are genuine TODOs** (the rest are regex `XX.XX.XXXX` patterns or `VTODO` iCal tokens):

1. `backend/app/modules/contacts/router.py` — 2× `TODO(v1.4-tenancy)` (no tenant_id column)
2. `backend/app/modules/costmodel/service.py:612` — `TODO (v1.4): time-phased PV`
3. `backend/app/modules/risk/service.py:63` — `TODO (v1.4): proper enum migration` for `impact_severity`
4. `backend/app/modules/users/service.py:348` — `TODO: send reset token via email`
5. `backend/app/core/plugin_manager.py:206` — `TODO: compare installed versions with registry`

Frontend `src/`: **0 real TODOs** (sole match is a regex-format literal in `ValidationPage.tsx`). Very clean.

## 7. Confirmed bugs still present

- **BUG-G1 (CRITICAL regression):** Change-password with identical new password breaks login → HTTP 500.
- **BUG-G2 (CRITICAL):** Contacts `country_code` still capped at 2 chars (#31 never fixed; v1.7 changelog claim misleading).
- **BUG-G3 (HIGH):** RFI list endpoint invisibly requires `project_id`; unfiltered list returns `[]` even when RFIs exist.
- **BUG-G4 (PROCESS):** TASK_PROGRESS.md Wave 1 never updated (6 items still 🔲); AGENT_START.md shows v0.8.0 while live is v1.9.0.
- **BUG-G5 (PROCESS):** 10+ minor versions in CHANGELOG have no matching `git tag` (v1.1, 1.2, 1.3.x, 1.4.x, 1.5.3, 1.6.1, 1.7.x).
