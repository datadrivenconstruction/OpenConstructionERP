# SA-3: Pydantic Schema Validation Hardening Report

**Date**: 2026-04-09
**Scope**: All `*Create` and `*Update` schemas across `backend/app/modules/*/schemas.py`
**Result**: 760/760 unit tests pass after changes

---

## Summary

Audited 18 schema files. Added missing `min_length`, `max_length`, `ge`, `le`, and `pattern` constraints to string, numeric, and date fields on Create/Update schemas. No existing functionality was broken -- only additive validation constraints.

---

## Changes by Module

### 1. `boq/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `BOQCreate` | `description` | Added `max_length=5000` |
| `BOQUpdate` | `description` | Added `max_length=5000` via `Field(default=None, max_length=5000)` |
| `PositionCreate` | `description` | Added `max_length=5000` |
| `PositionUpdate` | `description` | Added `max_length=5000` |
| `SectionCreate` | `description` | Added `max_length=5000` |
| `SnapshotCreate` | `name` | Changed from bare `str = ""` to `Field(default="", max_length=255)` |

**Already well-validated**: `quantity` (ge=0.0), `unit_rate` (ge=0.0), `confidence` (ge=0.0, le=1.0), `percentage` (ge=0.0, le=100.0), `ordinal` (min_length=1, max_length=50), `name` (min_length=1, max_length=255), `source` (pattern enum), `status` (pattern enum).

### 2. `finance/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `InvoiceLineItemCreate` | `description` | Added `min_length=1` |
| `InvoiceLineItemCreate` | `sort_order` | Changed to `Field(default=0, ge=0)` |
| `InvoiceCreate` | `notes` | Added `max_length=5000` |
| `InvoiceCreate` | `invoice_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `InvoiceCreate` | `due_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `InvoiceUpdate` | `notes` | Added `max_length=5000` |
| `PaymentCreate` | `payment_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `EVMSnapshotCreate` | `snapshot_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |

**Already well-validated**: amount fields use `_validate_non_negative_decimal` validator, `invoice_direction` (pattern enum), all monetary fields have `max_length`.

### 3. `procurement/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `POItemCreate` | `description` | Added `min_length=1` |
| `POItemCreate` | `sort_order` | Changed to `Field(default=0, ge=0)` |
| `POCreate` | `notes` | Added `max_length=5000` |
| `POCreate` | `issue_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `POCreate` | `delivery_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `POUpdate` | `notes` | Added `max_length=5000` |
| `GRCreate` | `receipt_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `GRCreate` | `notes` | Added `max_length=5000` |

### 4. `tasks/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `TaskCreate` | `description` | Added `max_length=5000` |
| `TaskCreate` | `responsible_id` | Added `max_length=36` |
| `TaskCreate` | `milestone_id` | Added `max_length=36` |
| `TaskCreate` | `meeting_id` | Added `max_length=36` |
| `TaskCreate` | `result` | Added `max_length=5000` |
| `TaskUpdate` | `description` | Added `max_length=5000` |
| `TaskUpdate` | `responsible_id` | Added `max_length=36` |
| `TaskUpdate` | `milestone_id` | Added `max_length=36` |
| `TaskUpdate` | `meeting_id` | Added `max_length=36` |
| `TaskUpdate` | `result` | Added `max_length=5000` |

**Already well-validated**: `title` (min_length=1, max_length=500), `due_date` (pattern YYYY-MM-DD), `task_type`/`status`/`priority` (pattern enums).

### 5. `meetings/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `AgendaItemEntry` | `entity_id` | Added `max_length=36` |
| `AgendaItemEntry` | `notes` | Added `max_length=5000` |
| `ActionItemEntry` | `owner_id` | Added `max_length=36` |
| `ActionItemEntry` | `due_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `MeetingCreate` | `chairperson_id` | Added `max_length=36` |
| `MeetingCreate` | `minutes` | Added `max_length=50000` |
| `MeetingUpdate` | `chairperson_id` | Added `max_length=36` |
| `MeetingUpdate` | `minutes` | Added `max_length=50000` |

**Already well-validated**: `title` (min_length=1, max_length=500), `meeting_date` (pattern), `meeting_type`/`status` (pattern enums).

### 6. `rfi/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `RFICreate` | `question` | Added `max_length=10000` |
| `RFICreate` | `assigned_to` | Added `max_length=36` |
| `RFICreate` | `ball_in_court` | Added `max_length=100` |
| `RFICreate` | `change_order_id` | Added `max_length=36` |
| `RFIUpdate` | `question` | Added `max_length=10000` |
| `RFIUpdate` | `assigned_to` | Added `max_length=36` |
| `RFIUpdate` | `ball_in_court` | Added `max_length=100` |
| `RFIUpdate` | `change_order_id` | Added `max_length=36` |
| `RFIRespondRequest` | `official_response` | Added `max_length=10000` |

**Already well-validated**: `subject` (min_length=1, max_length=500), `status` (pattern), `schedule_impact_days` (ge=0), date fields (pattern YYYY-MM-DD).

### 7. `ncr/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `NCRCreate` | `description` | Added `max_length=10000` |
| `NCRCreate` | `root_cause` | Added `max_length=5000` |
| `NCRCreate` | `corrective_action` | Added `max_length=5000` |
| `NCRCreate` | `preventive_action` | Added `max_length=5000` |
| `NCRCreate` | `linked_inspection_id` | Added `max_length=36` |
| `NCRCreate` | `change_order_id` | Added `max_length=36` |
| `NCRUpdate` | `description` | Added `max_length=10000` |
| `NCRUpdate` | `root_cause` | Added `max_length=5000` |
| `NCRUpdate` | `corrective_action` | Added `max_length=5000` |
| `NCRUpdate` | `preventive_action` | Added `max_length=5000` |
| `NCRUpdate` | `linked_inspection_id` | Added `max_length=36` |
| `NCRUpdate` | `change_order_id` | Added `max_length=36` |

### 8. `safety/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `IncidentCreate` | `description` | Added `max_length=10000` |
| `IncidentCreate` | `root_cause` | Added `max_length=5000` |
| `IncidentUpdate` | `description` | Added `max_length=10000` |
| `IncidentUpdate` | `root_cause` | Added `max_length=5000` |
| `ObservationCreate` | `description` | Added `max_length=10000` |
| `ObservationCreate` | `immediate_action` | Added `max_length=5000` |
| `ObservationCreate` | `corrective_action` | Added `max_length=5000` |
| `ObservationUpdate` | `description` | Added `max_length=10000` |
| `ObservationUpdate` | `immediate_action` | Added `max_length=5000` |
| `ObservationUpdate` | `corrective_action` | Added `max_length=5000` |

**Already well-validated**: `severity` (ge=1, le=5), `likelihood` (ge=1, le=5), `days_lost` (ge=0), `incident_date` (pattern), `incident_type`/`severity`/`status` (pattern enums).

### 9. `contacts/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `ContactCreate` | `notes` | Added `max_length=5000` |
| `ContactUpdate` | `notes` | Added `max_length=5000` |

**Already well-validated**: names (max_length=255), email (validator), phone (max_length=50), country_code (max_length=2), vat_number (max_length=50), `contact_type` (pattern enum).

### 10. `schedule/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `ScheduleCreate` | `description` | Added `max_length=5000` |
| `ScheduleCreate` | `start_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `ScheduleCreate` | `end_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `ScheduleUpdate` | `description` | Added `max_length=5000` |
| `ScheduleUpdate` | `start_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `ScheduleUpdate` | `end_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `ActivityCreate` | `description` | Added `max_length=5000` |
| `ActivityCreate` | `start_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `ActivityCreate` | `end_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `ActivityUpdate` | `description` | Added `max_length=5000` |
| `ActivityUpdate` | `start_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `ActivityUpdate` | `end_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `WorkOrderCreate` | `description` | Added `max_length=5000` |
| `WorkOrderUpdate` | `description` | Added `max_length=5000` |
| `ProgressUpdateCreate` | `notes` | Added `max_length=5000` |
| `ProgressUpdateEdit` | `notes` | Added `max_length=5000` |

**Already well-validated**: `duration_days` (ge=0), `progress_pct` (ge=0.0, le=100.0), `planned_cost`/`actual_cost` (ge=0.0), date range model validator.

### 11. `changeorders/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `ChangeOrderCreate` | `description` | Added `max_length=5000` |
| `ChangeOrderUpdate` | `description` | Added `max_length=5000` |
| `ChangeOrderItemCreate` | `description` | Added `max_length=5000` |
| `ChangeOrderItemUpdate` | `description` | Added `max_length=5000` |

### 12. `correspondence/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `CorrespondenceCreate` | `notes` | Added `max_length=5000` |
| `CorrespondenceUpdate` | `notes` | Added `max_length=5000` |

### 13. `inspections/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `ChecklistEntry` | `notes` | Added `max_length=2000` |
| `InspectionCreate` | `description` | Added `max_length=5000` |
| `InspectionCreate` | `wbs_id` | Added `max_length=36` |
| `InspectionCreate` | `inspector_id` | Added `max_length=36` |
| `InspectionUpdate` | `description` | Added `max_length=5000` |
| `InspectionUpdate` | `wbs_id` | Added `max_length=36` |
| `InspectionUpdate` | `inspector_id` | Added `max_length=36` |

### 14. `punchlist/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `PunchItemCreate` | `description` | Added `max_length=5000` |
| `PunchItemCreate` | `document_id` | Added `max_length=36` |
| `PunchItemCreate` | `assigned_to` | Added `max_length=36` |
| `PunchItemUpdate` | `description` | Added `max_length=5000` |
| `PunchItemUpdate` | `document_id` | Added `max_length=36` |
| `PunchItemUpdate` | `assigned_to` | Added `max_length=36` |
| `PunchItemUpdate` | `resolution_notes` | Added `max_length=5000` |
| `PunchStatusTransition` | `notes` | Added `max_length=5000` |

### 15. `fieldreports/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `FieldReportCreate` | `work_performed` | Added `max_length=10000` |
| `FieldReportCreate` | `delays` | Added `max_length=5000` |
| `FieldReportCreate` | `visitors` | Added `max_length=2000` |
| `FieldReportCreate` | `deliveries` | Added `max_length=5000` |
| `FieldReportCreate` | `safety_incidents` | Added `max_length=5000` |
| `FieldReportCreate` | `notes` | Added `max_length=5000` |
| `FieldReportUpdate` | `work_performed` | Added `max_length=10000` |
| `FieldReportUpdate` | `delays` | Added `max_length=5000` |
| `FieldReportUpdate` | `visitors` | Added `max_length=2000` |
| `FieldReportUpdate` | `deliveries` | Added `max_length=5000` |
| `FieldReportUpdate` | `safety_incidents` | Added `max_length=5000` |
| `FieldReportUpdate` | `notes` | Added `max_length=5000` |

### 16. `risk/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `RiskCreate` | `description` | Added `max_length=5000` |
| `RiskCreate` | `mitigation_strategy` | Added `max_length=5000` |
| `RiskCreate` | `contingency_plan` | Added `max_length=5000` |
| `RiskUpdate` | `description` | Added `max_length=5000` |
| `RiskUpdate` | `mitigation_strategy` | Added `max_length=5000` |
| `RiskUpdate` | `contingency_plan` | Added `max_length=5000` |

### 17. `transmittals/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `TransmittalCreate` | `issued_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `TransmittalCreate` | `response_due_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `TransmittalCreate` | `cover_note` | Added `max_length=5000` |
| `TransmittalUpdate` | `issued_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `TransmittalUpdate` | `response_due_date` | Added `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `TransmittalUpdate` | `cover_note` | Added `max_length=5000` |
| `ItemCreate` | `notes` | Added `max_length=5000` |

### 18. `submittals/schemas.py`

| Schema | Field | Change |
|--------|-------|--------|
| `SubmittalCreate` | `ball_in_court` | Added `max_length=100` |
| `SubmittalCreate` | `submitted_by_org` | Added `max_length=255` |
| `SubmittalCreate` | `reviewer_id` | Added `max_length=36` |
| `SubmittalCreate` | `approver_id` | Added `max_length=36` |
| `SubmittalUpdate` | `ball_in_court` | Added `max_length=100` |
| `SubmittalUpdate` | `submitted_by_org` | Added `max_length=255` |
| `SubmittalUpdate` | `reviewer_id` | Added `max_length=36` |
| `SubmittalUpdate` | `approver_id` | Added `max_length=36` |
| `SubmittalReviewRequest` | `notes` | Added `max_length=5000` |

---

## Validation Conventions Applied

| Field type | Constraint | Limit |
|------------|-----------|-------|
| `title` / `name` / `subject` | `min_length` + `max_length` | 1 / 255-500 |
| `description` (short) | `max_length` | 5000 |
| `description` (long-form, e.g. NCR, safety) | `max_length` | 10000 |
| `notes` / `corrective_action` / `root_cause` | `max_length` | 5000 |
| `minutes` (meeting) | `max_length` | 50000 |
| `work_performed` (field report) | `max_length` | 10000 |
| `code` / `number` / `ordinal` | `max_length` | 50-100 |
| UUID-style string IDs | `max_length` | 36 |
| `quantity` / `unit_rate` / `amount` (float) | `ge=0.0` | -- |
| `quantity` / `unit_rate` / `amount` (string) | decimal validator | non-negative |
| `percentage` | `ge=0.0, le=100.0` | -- |
| `confidence` | `ge=0.0, le=1.0` | -- |
| `days_lost` / `schedule_impact_days` | `ge=0` | -- |
| `sort_order` | `ge=0` | -- |
| Date strings (YYYY-MM-DD) | `pattern=r"^\d{4}-\d{2}-\d{2}$"` | -- |

---

## Modules NOT Changed (already well-validated)

- `projects/schemas.py` -- already has full validation including HTML stripping, date validation, max_length on all fields
- `costs/schemas.py` -- internal data, no user-facing Create schemas needing hardening
- `documents/schemas.py` -- no DocumentCreate schema (file upload), Update already has pattern/max_length

---

## Test Results

- **760 unit tests**: ALL PASSED
- **Integration tests**: 2 pre-existing failures (auth-related, unrelated to schema changes)
- **Import check**: All 18 modified schema modules import cleanly
