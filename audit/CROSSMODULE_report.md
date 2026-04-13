# Cross-Module Integration Audit Report

**Date**: 2026-04-09
**Tester**: Automated (Claude Code)
**Backend**: v1.1.0, SQLite, 55 modules loaded
**Auth**: demo@openestimator.io (admin role)

---

## Summary

| # | Connection | Status | Notes |
|---|-----------|--------|-------|
| 1 | BOQ -> Schedule | **PASS** | 7 activities generated from 5 BOQ positions |
| 2 | BOQ -> 5D Budget | **PASS** | 3 budget lines created from locked BOQ |
| 3 | Safety -> Notifications | **PASS (FIXED)** | Was broken: events fired but no DB writes due to SQLite lock contention |
| 4 | NCR -> Change Order | **PASS** | CO-001 created from NCR-001 with full traceability |
| 5 | Meeting -> Tasks | **PASS** | 3 tasks auto-created from action items on meeting completion |
| 6 | Finance -> Budget | **PASS (FIXED)** | Was broken: pay_invoice had no budget recalculation logic |
| 7 | Document Hub | **PASS** | Document + photo upload both work and appear in listings |
| 8 | Project Intelligence | **PASS** | PCI reads from BOQ, Schedule, Documents; returns accurate scores |

**Overall: 8/8 PASS** (2 required code fixes, applied in this session)

---

## Test 1: BOQ -> Schedule (generate-from-boq)

**Endpoint**: `POST /api/v1/schedule/schedules/{id}/generate-from-boq/`
**Result**: **PASS** (HTTP 201)

### Steps
1. Created BOQ with 5 positions (2 sections, 3 work items) totaling EUR 54,000
2. Created schedule for the project
3. Called `generate-from-boq` with `total_project_days=90`

### Verification
- 7 activities generated: 2 milestones (start/completion), 2 summary activities (per section), 3 task activities
- Activities have correct `boq_position_ids` linking back to BOQ positions
- Dependencies auto-generated: FS (finish-to-start) between positions within sections, SS (start-to-start) with lag between sections
- Duration calculated via cost-proportional method: Excavation=29d, Concrete=40d, Steel=21d
- WBS codes match BOQ ordinals (01, 01.001, 01.002, 02, 02.001)

---

## Test 2: BOQ -> 5D Cost Model (create-budget)

**Endpoint**: `POST /api/v1/boq/boqs/{id}/create-budget/`
**Result**: **PASS** (HTTP 201)

### Steps
1. Locked the BOQ (required precondition)
2. Called `create-budget`

### Verification
- 3 budget lines created (one per parent_id group)
- Budget amounts: 0.00 (section header), 41500.00 (foundations), 12500.00 (structural)
- Budget IDs returned in response, verifiable via `GET /api/v1/finance/budgets/`
- BOQ must be locked before budget creation (enforced with 400 error)

---

## Test 3: Safety -> Notifications

**Endpoint**: `POST /api/v1/safety/incidents/` -> Notification created
**Result**: **PASS (after fix)**

### Bug Found
The safety module's `create_incident()` method had **no event emission and no notification creation**. Only observations with `risk_score > 15` emitted events via `event_bus.publish()`.

Even for observations, notifications were never created because:
1. The event handler `_handle_safety_observation_high_risk` in `event_handlers.py` checked `notify_user_ids` and returned early when empty
2. The safety service always passed `notify_user_ids: []` with a comment "Populated by handler from project team" -- but neither the service nor the handler actually populated it
3. Additionally, SQLite's single-writer constraint caused the event handler (which opens a **separate** DB session) to deadlock/timeout, since the main request session still holds the write lock

### Fix Applied
- **`backend/app/modules/safety/service.py`**: Added inline notification creation in `create_incident()` using the **same session** (avoids SQLite lock contention). Also added inline notification for high-risk observations.
- **`backend/app/core/event_handlers.py`**: Updated `_handle_safety_observation_high_risk` and `_notify_ncr_created` to fall back to project owner when `notify_user_ids` is empty. Added new `_handle_safety_incident_created` handler and registered it.

### Post-Fix Verification
- Incident INC-008 created -> notification appeared with `title_key: "notifications.safety.incident_created"`, correct `entity_id`, and `body_context` containing incident_number, severity, description

---

## Test 4: NCR -> Change Order

**Endpoint**: `POST /api/v1/ncr/{id}/create-variation/`
**Result**: **PASS** (HTTP 201)

### Steps
1. Created NCR with `cost_impact: "15000.00"` and `schedule_impact_days: 7`
2. Called `create-variation` on the NCR

### Verification
- Change order CO-001 created with:
  - `title: "Variation: Concrete strength below spec"`
  - `reason_category: "non_conformance"`
  - `cost_impact: "15000.00"` (from NCR)
  - `schedule_impact_days: 7` (from NCR)
  - `description` includes NCR description, corrective action, and root cause
  - `metadata_.source: "ncr"`, `metadata_.ncr_id` set
- NCR's `change_order_id` field updated to point back to the CO

---

## Test 5: Meeting -> Tasks

**Endpoint**: `POST /api/v1/meetings/{id}/complete/`
**Result**: **PASS** (HTTP 200)

### Steps
1. Created meeting with 3 open action items (each with description and due_date)
2. Meeting created in `scheduled` status
3. Called `complete`

### Verification
- Meeting status changed to `completed`
- 3 tasks created automatically:
  - `title` = action item description (truncated to 500 chars)
  - `description` = "Auto-created from meeting MTG-002: Weekly Progress Review"
  - `due_date` preserved from action item
  - `meeting_id` linked back to source meeting
  - `metadata.source: "meeting_action_item"`
  - `status: "open"`, `priority: "normal"`
- Event `meeting.action_items_created` emitted

---

## Test 6: Finance -> Budget Actuals

**Endpoint**: `POST /api/v1/finance/{id}/pay/` -> Budget actuals updated
**Result**: **PASS (after fix)**

### Bug Found
The `pay_invoice()` method in `finance/service.py` only changed the invoice status to "paid" but **did not update budget actuals**. An event handler `_handle_invoice_paid` existed in `event_handlers.py` and was registered, but:
1. The `pay_invoice()` method never emitted the `invoice.paid` event
2. Even with the event, the handler's separate session would deadlock on SQLite

### Fix Applied
- **`backend/app/modules/finance/service.py`**: Added inline budget recalculation in `pay_invoice()` using the same session. Sums `amount_total` of all paid invoices for the project, then updates all budget lines' `actual` field. Also emits `invoice.paid` event for additional handlers.

### Post-Fix Verification
- Invoice created with `amount_subtotal=5000, tax=950` -> `amount_total=5950`
- After approve -> pay: budget `actual` updated to `5950.00`
- Log confirms: "Updated budget actuals for project ... total_actual=5950.00"

---

## Test 7: Document Hub

**Endpoints**: `POST /api/v1/documents/upload/`, `POST /api/v1/documents/photos/upload/`
**Result**: **PASS**

### Verification
- Text file uploaded: appeared in document list with `category: "other"`, correct file_size
- JPEG uploaded via photos endpoint: appeared in both document list (as `category: "photo"`) and photos list
- Photos have separate gallery/timeline endpoints
- Note: `project_id` must be passed as **query parameter**, not form field

---

## Test 8: Project Intelligence (PCI)

**Endpoint**: `GET /api/v1/project_intelligence/score/?project_id=X`
**Result**: **PASS** (HTTP 200)

### Verification
PCI correctly aggregated data from multiple modules:

| Domain | Score | Data Source |
|--------|-------|------------|
| BOQ | 100.0 | 5 positions, 2 sections, export-ready |
| Schedule | 80.0 | 7 activities, has critical path, 70-day duration |
| Documents | 50.0 | 2 files, categories: other + photo |
| Validation | 0.0 | No validation runs yet |
| Cost Model | 0.0 | No 5D cost model configured |
| Takeoff | 0.0 | No takeoff data |
| Risk | 0.0 | No risk register entries |
| Tendering | 0.0 | No tenders |
| Reports | 0.0 | No reports generated |

- **Overall score**: 43.5 (Grade D)
- Critical gaps identified: validation, risk, tendering
- Achievements recognized: BOQ complete, schedule generated, documents uploaded

---

## Files Modified

| File | Change |
|------|--------|
| `backend/app/modules/safety/service.py` | Added notification creation in `create_incident()` and `create_observation()` using same session |
| `backend/app/modules/finance/service.py` | Added event_bus import, budget actuals recalculation in `pay_invoice()`, `invoice.paid` event emission |
| `backend/app/modules/ncr/service.py` | Added notification creation in `create_ncr()`, `ncr.created` event emission |
| `backend/app/core/event_handlers.py` | Added `_handle_safety_incident_created` handler; fixed `_handle_safety_observation_high_risk` and `_notify_ncr_created` to fall back to project owner when `notify_user_ids` is empty; registered new handler |

---

## Architectural Finding: Event Bus + SQLite Deadlocks

The event_bus pattern of creating a **new session** in handlers (`async_session_factory()`) fails on SQLite because:
- The main request session holds a write lock
- The handler's separate session attempts to write (notification creation)
- SQLite allows only one concurrent writer -> deadlock or 5s timeout

**Workaround applied**: Critical cross-module writes (notifications, budget updates) are now performed inline in the service methods using the **same session** as the request. The event_bus `publish()` calls are retained for non-SQLite deployments and for handlers that only read data.

**Recommendation**: For PostgreSQL deployments, the event_bus handler approach will work correctly. For SQLite, all write operations should use the request session directly.
