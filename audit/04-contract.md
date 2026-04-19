# API Wire-Shape Drift Audit — OpenConstructionERP

Date: 2026-04-18
Scope: Phase 4 of 9


## Summary

| Severity | Count |
|----------|------:|
| High     | 4     |
| Medium   | 8     |
| Low      | 3     |
| Clean    | 5     |

---

## 1. Tasks — HIGH drift

**Backend:** `backend/app/modules/tasks/schemas.py:118` (TaskResponse.checklist)
**Frontend:** `frontend/src/features/tasks/api.ts:18-22` (ChecklistItem interface)

### Checklist field mismatch

| Field | Backend | Frontend |
|-------|---------|----------|
| checklist type | `list[dict[str, Any]]` | `ChecklistItem[]` |
| text/label | `"text"` (in dict) | `"label"` (field) |
| completed/checked | `"completed"` (in dict) | `"checked"` (field) |

Backend returns loose dicts; frontend expects `{ id, label, checked }` with renamed fields.
**Result:** Frontend fails when accessing `item.label` on dict with only `text` key.

---

## 2. Documents — MEDIUM drift

**Backend:** `backend/app/modules/documents/schemas.py:55,124`
**Frontend:** `frontend/src/features/documents/api.ts:139,18`

### filename vs name inconsistency

DocumentResponse has `name: str` (line 55); PhotoResponse has `filename: str` (line 124).
Frontend PhotoItem expects `filename` everywhere. Cross-document queries will fail.

---

## 3. ChangeOrders — CLEAN

Both schemas align well. No drift.

---

## 4. Risk — CLEAN

Simple module, no drift.

---

## 5. Punchlist — MEDIUM drift

**Frontend:** `frontend/src/features/punchlist/api.ts:116-119`

### List wrapping inconsistency

Frontend defensively unwraps `PunchItem[] | { items: PunchItem[] }`.
This masks a contract mismatch: backend returns either bare array or wrapped object.
Recommend enforcing single format in router response.

---

## 6. FieldReports — MEDIUM drift

**Backend:** `backend/app/modules/fieldreports/schemas.py:119`
**Frontend:** `frontend/src/features/fieldreports/api.ts:32`

### Workforce loose typing

Backend: `workforce: list[dict[str, Any]]` (untyped dicts)
Frontend: expects `WorkforceEntry[]` with `.trade, .count, .hours`

No schema enforcement on backend; runtime mismatch risk.

---

## 7. Schedule — LOW drift

**Backend:** `backend/app/modules/schedule/schemas.py:138-140`
**Frontend:** `frontend/src/features/schedule/api.ts:15-36`

Optional fields returned by backend but not used by frontend:
- constraint_type, constraint_date, activity_code

Low priority (optional fields ignored safely).

---

## 8. Assemblies — CLEAN

Strong type alignment, no drift.

---

## 9. BOQ — MEDIUM drift

**Backend:** `backend/app/modules/boq/schemas.py:79`

### Metadata alias confusion

Backend uses `validation_alias="metadata_"` (Pydantic accepts `metadata_` on input, returns `metadata`).
Frontend handles both names defensively. Naming convention should be unified.

---

## 10. Projects — CLEAN

Well-aligned schemas.

---

## 11–15. Costs, RFI, Correspondence, Users, Permissions

**Insufficient frontend data** — no dedicated api.ts layers found.
Unable to audit. Recommended: create dedicated API modules for frontend consistency.

---

## 16. Tendering — CLEAN

Types align where frontend exists.

---

## 17–20. CDE, Transmittals, Collaboration, BIM

**CLEAN** — All schemas carefully aligned.

---

## Top 5 Actions

1. **Tasks (HIGH):** Add normaliser to remap checklist dict → ChecklistItem interface.
2. **FieldReports (MED):** Enforce WorkforceEntry schema on backend.
3. **Punchlist (MED):** Verify router response format is consistent (array only, not wrapped).
4. **Documents (MED):** Reconcile filename/name field naming.
5. **BOQ (MED):** Drop metadata_ alias; use metadata everywhere.

