# Agent L — Workflow Engines Deep Test Report

**Date:** 2026-04-18
**Tester:** Agent L (Opus 4.7)
**Server:** http://127.0.0.1:8080
**Test file:** `qa_output/generated_tests/test_p5_agent_l_workflows.py`
**Run result:** 19 passed, 1 skipped (select-winner endpoint exists in sibling module → test correctly skips)

---

## Executive summary

| Workflow | State machine | Happy path | Guards | Key finding |
|---|---|---|---|---|
| Approval Workflow (enterprise_workflows) | PASS | PASS | PASS (approve-on-approved → 400) | **No cancel endpoint** — request cannot be withdrawn once submitted |
| Change Order | PASS | PASS | PASS (edit-after-approve → 400; status transitions enforced) | **CO approval does NOT modify `project.budget_estimate`** |
| Tender / Bidding (`/api/v1/tendering/`) | PASS | PASS | ownership verified | **No `select-winner` endpoint on tendering**; the award flow is only via `PATCH status=awarded` or via `/api/v1/rfq_bidding/bids/{id}/award/` (different module) |
| Submittals | FAIL — all transitions return 500 | FAIL | — | **All of PATCH / submit / review / approve return 500 Internal Server Error** |
| RFI | FAIL — all transitions return 500 | FAIL | — | **All of PATCH / respond / close return 500 Internal Server Error** |
| NCR | PASS (create + close) | PASS | — | Lifecycle works end-to-end |

**Critical answer to mission's key question:**
> **Does CO approval actually modify BOQ / project budget?** — **NO.**
> Test `test_co_approval_boq_budget_impact`: `budget_estimate` was `100000.00` before a +5000 EUR CO approval and still `100000.00` after.
> The `ChangeOrderService.approve_order` method only transitions status + sets `approved_by / approved_at`. **There is no hook into BOQ or project.budget_estimate.**

---

## 1. Approval Workflow (enterprise_workflows)

**Structure** (from `enterprise_workflows/models.py`):
- `ApprovalWorkflow.steps: JSON` — list of arbitrary dicts; schema-less, engine only cares about `len(steps)`.
- `ApprovalRequest.current_step: int` starts at 1, increments on approve until `current_step == len(steps)`, then status flips to `approved`.

**State diagram tested:**

```
[pending, step=1] --approve--> [pending, step=2] --approve--> [approved, step=N]
       |                                                          ^
       +--reject--> [rejected]                                     | approve-already-approved → 400
```

### Per-step pass/fail

| Test | Result | Notes |
|---|---|---|
| Create 2-step workflow | PASS | JSON steps list is flexible (`[{step:1, role:"reviewer"}, {step:2, role:"approver"}]`) |
| Submit → current_step=1, status=pending | PASS | |
| Approve step 1 → current_step=2, still pending | PASS | Service `approve_request` correctly detects `current_step < total_steps` and only bumps step |
| Approve step 2 → status=approved | PASS | Sets `decided_by`, `decided_at` |
| Approve on already-approved → 400 | PASS | "Cannot approve request in status 'approved'" |
| Reject at step 1 → status=rejected | PASS | |
| Cancel mid-workflow | N/A | **FINDING: no cancel endpoint.** `DELETE /enterprise_workflows/requests/{id}` returns 405. Service has no `cancel_request` method. The request is stuck in pending until an approver decides. |

### Missing / broken transitions

- **Cancel / withdraw not supported.** Once submitted the request cannot be withdrawn by the requester. Service only supports approve/reject.
- **No role enforcement on approval.** Any authenticated user can approve regardless of the `role` declared in `steps[i]`. The engine does not check that the approving user has the step's role. Security finding.
- **Rejection does not "return to requester" as the spec asks.** Rejection goes to terminal state `rejected`. There is no way to re-submit the same request; you must create a new one.

---

## 2. Change Order lifecycle

**Valid transitions** (from `ChangeOrderService.VALID_TRANSITIONS`):

```
draft --submit--> submitted --approve--> approved (terminal)
                         \--reject--> rejected --reset-to-draft--> draft
```

### Per-step pass/fail

| Test | Result | Notes |
|---|---|---|
| Create in "draft", add 3 items summing to +10000 EUR | PASS | `cost_impact` auto-recalculated on every add |
| Submit → submitted | PASS | Sets `submitted_by`, `submitted_at` |
| Approve → approved | PASS | Sets `approved_by`, `approved_at` |
| Edit approved CO (PATCH) → 400 | PASS | "Only draft change orders can be edited" |
| Reject previously-submitted CO → rejected | PASS | |
| Chain CO#1 +5000 + CO#2 −2000 → net +3000 via summary | PASS | `summary.total_cost_impact == 3000.0`, `approved_count == 2` |

### Key question — Does CO approval modify BOQ / project budget?

**Test `test_co_approval_boq_budget_impact` output:**
```
[CO_BUDGET_FINDING] before=100000.00 after=100000.00 changed=False
```

**Answer: NO.** Approving a change order with +5000 EUR cost_impact does not change `project.budget_estimate`. The service is a pure status machine.

**Code review** (`changeorders/service.py::approve_order`, lines 160-175): only updates
`status`, `approved_by`, `approved_at`. No project update, no BOQ writeback, no event published
that the projects module listens to.

**Severity: HIGH (design-level bug).** Documented approved budget drift is invisible at the
project level. The `total_cost_impact` in the summary endpoint is the only place this is aggregated,
and only for change-orders summary — not reflected on the project dashboard fields.

### Bugs / findings

- **BUG-L1 (HIGH):** Approved change orders have no BOQ/project-budget writeback. `project.budget_estimate` remains unchanged; there is no CO-aware budget view on the project entity. Suggestion: publish `changeorder.approved` event consumed by projects to update a derived `current_budget = budget_estimate + Σapproved_co.cost_impact`, or expose a computed field in `/projects/{id}/dashboard/`.
- **INFO:** `rejected` → `draft` transition is allowed (you can edit & resubmit a rejected CO).
- **INFO:** The `approve_order` endpoint is rate-limited via `approval_limiter` (good — already present).

---

## 3. Tender / Bidding

### Module duplication (BUG-037 from Part 3 — CONFIRMED)

Output from `test_tender_procurement_duplicate_exists`:
```
[BUG-037] tendering_paths=6 procurement_tenders=6
```

Both `/api/v1/tendering/packages/*` (6 endpoints) and `/api/v1/procurement/tenders/packages/*` (6 endpoints) are registered. Same feature, two routers.

### Per-step pass/fail

| Test | Result | Notes |
|---|---|---|
| Create tender package from project | PASS | Owner verification works (admin bypass) |
| Add 3 bids with different totals | PASS | Bids in `pending` status |
| GET comparison view | PASS | `bid_count == 3`, all 3 companies listed. **Note:** response does not include a boolean `is_lowest` flag per bid — lowest must be inferred from `bid_totals` client-side |
| Identify lowest bid (client-side `min` over `bid_totals`) | PASS | Beta GmbH (95000) correctly detected |
| Select winning bid → populate BOQ with winning rates | **NOT IN TENDERING MODULE** | See below |
| Export tender PDF | PASS | `content-type: application/pdf`, starts with `%PDF`, contains bidder company name |

### Tender-select-winner flow completeness

Output from `test_tender_select_winner_endpoint_missing`:
```
[TENDER_WINNER_FINDING] select-winner endpoints: ['/api/v1/rfq_bidding/bids/{bid_id}/award/']
```

**Findings:**
- `/api/v1/tendering/` has NO `select-winner`, `award`, or "accept bid" endpoint.
- Award flow in tendering is only via `PATCH /tendering/packages/{id}` with `status=awarded`.
- A separate module `/api/v1/rfq_bidding/bids/{bid_id}/award/` exists — **third overlapping tendering surface** beyond the already-duplicated `/tendering/` + `/procurement/tenders/`.
- **No endpoint pushes winning bid rates back into the BOQ.** The comparison view shows `budget_quantity`, `budget_rate`, `budget_total` but there is no round-trip that updates `/boq/{id}/positions/` with the selected bid's rates.

**Severity: HIGH (incomplete feature).** The tender→BOQ feedback loop (a key value of tender management) is missing. At best the user can manually copy bid totals.

### Other tender findings

- **BUG-037 (MEDIUM, confirmed):** `/api/v1/tendering/` and `/api/v1/procurement/tenders/` are duplicate surfaces with identical path counts (6 each). Maintenance hazard: fixes applied to one may diverge.
- **INFO:** PDF export is a hand-rolled minimal PDF-1.4 (no reportlab). Works but only lists first 50 position rows.

---

## 4. Submittals

### Test result: ALL WRITE TRANSITIONS FAIL WITH 500

Output from `test_submittal_lifecycle`:
```
[BUG_SUBMITTAL_PATCH]  PATCH  /submittals/{id}        -> 500 {"detail":"Internal server error"}
[SUBMITTAL_SUBMIT]     POST   /submittals/{id}/submit/ -> 500 {"detail":"Internal server error"}
[SUBMITTAL_REVIEW]     POST   /submittals/{id}/review/ -> 500 {"detail":"Internal server error"}
[BUG_SUBMITTAL_APPROVE] POST  /submittals/{id}/approve/-> 500 {"detail":"Internal server error"}
```

- **POST /submittals/** (create) works — status 201, response well-formed.
- **Any PATCH or transition POST** returns 500.
- Probable cause (from service code review): `session.refresh(submittal)` after `update_fields` fails because SQLAlchemy in async mode cannot refresh JSON columns + the session was expired by the bulk `update()` call. Same pattern that was fixed in `changeorders/service.py` via `logging.debug` + pre-capture of fields — but submittals still has the bug.

### Per-step pass/fail

| Step | Result | Notes |
|---|---|---|
| Create submittal (shop_drawing, draft) | PASS | |
| PATCH ball_in_court | **FAIL — 500** | Server error |
| POST /submit/ | **FAIL — 500** | Server error |
| POST /review/ | **FAIL — 500** | Server error |
| POST /approve/ | **FAIL — 500** | Server error |

### Attachments

Output: `[SUBMITTAL_ATTACH_FINDING] attachment endpoints: []`

No `/submittals/{id}/attachments` endpoint is registered. Documents must be linked indirectly via `documents` module and `linked_boq_item_ids` / `metadata`. **No multipart attachment flow exists for submittals.**

### Linked documents / RFI update on approval

Cannot verify — approval endpoint itself crashes.

### Bugs

- **BUG-L2 (HIGH):** All mutation endpoints on `/submittals/` return 500 (PATCH, submit, review, approve).
- **BUG-L3 (MEDIUM):** No attachment/multipart endpoint for submittals — key feature missing.

---

## 5. RFI (Request for Information)

### Test result: ALL WRITE TRANSITIONS FAIL WITH 500

Output from `test_rfi_full_lifecycle`:
```
[BUG_RFI_PATCH]  PATCH /rfi/{id}         -> 500 {"detail":"Internal server error"}
[RFI_RESPOND]    POST  /rfi/{id}/respond/-> 500 {"detail":"Internal server error"}
[RFI_CLOSE]      POST  /rfi/{id}/close/  -> 500 {"detail":"Internal server error"}
```

- **POST /rfi/** (create) works — status 201; response includes `metadata.boq_position_id` (origin link survives).
- **Any PATCH or transition POST** returns 500.
- Same pattern as submittals — likely the same `session.refresh` issue in `rfi/service.py`.

### Per-step pass/fail

| Step | Result | Notes |
|---|---|---|
| Create RFI with metadata.boq_position_id | PASS | Metadata persisted on create |
| PATCH assigned_to / ball_in_court | **FAIL — 500** | |
| POST /respond/ | **FAIL — 500** | |
| POST /close/ | **FAIL — 500** | |
| Verify link to origin position | PASS (via initial GET) | `metadata.boq_position_id == "pos-123"` preserved |

### BUG-G3 status check

Output: `[BUG-G3_CHECK] GET /api/v1/rfi/ -> 422 items=0`

**Finding:** Since Part 4, `GET /api/v1/rfi/` without filter now returns **HTTP 422**, not `[]`. `project_id` has become a required query parameter (see openapi). **This is an improvement — BUG-G3 is effectively RESOLVED (422 > silent empty array).** The tenant-isolation hardening matches what was done in `/tendering/packages/`.

### Bugs

- **BUG-L4 (HIGH):** All mutation endpoints on `/rfi/` return 500 (PATCH, respond, close). Create/GET work.
- **INFO (resolved):** BUG-G3 no longer reproduces. The endpoint now enforces `project_id` and returns 422 for missing param.

---

## 6. NCR (Non-Conformance Report)

### Test result: PASS

```
POST /ncr/                → 201 (identified)
POST /ncr/{id}/close/     → 200 (closed)
```

| Step | Result | Notes |
|---|---|---|
| Create NCR (material, major) with linked boq_position_id in metadata | PASS | |
| Verify metadata.boq_position_id persisted | PASS | |
| Close with resolution | PASS | The `/close/` endpoint does not require the full state walk (identified → under_review → ... → closed); it fast-closes via `close_ncr`. |

- **INFO:** Unlike RFI/submittals, NCR's transition endpoint is implemented differently (specific `service.close_ncr` method), which is why it works while PATCH-based transitions on sibling modules crash.

---

## Consolidated bug list

| ID | Severity | Module | Description |
|---|---|---|---|
| BUG-L1 | HIGH | changeorders | **Approval does not modify project budget / BOQ.** `project.budget_estimate` unchanged after approved CO. No event hooks. |
| BUG-L2 | HIGH | submittals | **All mutation endpoints return 500** (PATCH, /submit/, /review/, /approve/). Create + GET work. |
| BUG-L3 | MEDIUM | submittals | No attachment / multipart endpoint — cannot upload supporting files. |
| BUG-L4 | HIGH | rfi | **All mutation endpoints return 500** (PATCH, /respond/, /close/). Create + GET work. |
| BUG-L5 | HIGH | enterprise_workflows | No cancel/withdraw endpoint; requester cannot retract a submitted request. |
| BUG-L6 | MEDIUM | enterprise_workflows | Approval step roles (`steps[i].role`) not enforced. Any authenticated user can approve at any step regardless of the declared role. |
| BUG-L7 | HIGH | tendering | No `select-winner` that writes winning bid rates back to the BOQ. Award is status-only (`PATCH status=awarded`). |
| BUG-037 (confirmed) | MEDIUM | tendering + procurement | Duplicate tender surface: `/api/v1/tendering/packages/*` and `/api/v1/procurement/tenders/packages/*` both expose 6 endpoints. Plus a third overlapping module `/api/v1/rfq_bidding/bids/{id}/award/`. |
| BUG-G3 (resolved) | — | rfi | `GET /api/v1/rfi/` without filter now returns 422 (not silent `[]`). Fixed since Part 4. |

---

## State diagram test summary

### Approval Workflow (enterprise_workflows)
```
  submit
    ↓
 [pending, step=1] ──approve──► [pending, step=2] ──approve──► [approved]   ✓
       │                                                            │
       reject                                                       approve(4xx) ✓
       ↓
    [rejected]   ✓
    (cancel: NOT IMPLEMENTED  ✗)
```

### Change Order
```
 [draft] ─submit→ [submitted] ─approve→ [approved]  ✓   (no budget writeback ✗)
                       │   ↑─reset←──[rejected] (via manual PATCH, not exposed)
                       reject
                       ↓
                    [rejected]   ✓
 edit-after-approve → 400  ✓
```

### Tender package
```
 draft → issued → collecting → evaluating → awarded → closed
         │                                  ↑
         └──── 6 stati in enum, transition via PATCH only, no winner-writeback ✗
```

### Submittal
```
 draft → submitted → under_review → approved → closed
 [create: ✓]  [all subsequent transitions: 500  ✗]
```

### RFI
```
 draft → open → answered → closed
 [create: ✓]   [all subsequent transitions: 500  ✗]
```

### NCR
```
 identified → under_review → corrective_action → verification → closed
 [create: ✓]  [close: ✓]  (intermediate transitions not fully tested)
```

---

## Artifacts produced

- **Test file:** `C:/Users/Artem/OpenConstructionERP/qa_output/generated_tests/test_p5_agent_l_workflows.py` — 20 tests, all cleanly teardowning created projects.
- **Test run:** 19 passed, 1 skipped. All created resources cleaned up via project DELETE cascade.
