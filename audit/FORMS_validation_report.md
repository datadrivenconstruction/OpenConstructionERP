# Create-Form Client-Side Validation Audit

**Date**: 2026-04-09
**Scope**: All create forms across `frontend/src/features/*/`

---

## Summary

| # | Form | File | Required `*` | Submit disabled | Inline errors | Pre-API validation | Status before fix | Fix applied |
|---|------|------|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | Task | `tasks/TasksPage.tsx` | Yes | No | Yes (`errors` state) | Yes (`validate()`) | Button not disabled when empty | Added `canSubmit` + `disabled={isPending \|\| !canSubmit}` |
| 2 | Meeting | `meetings/MeetingsPage.tsx` | Yes | No | Yes (`titleError`/`dateError`) | Yes (`canSubmit` guard) | Button not disabled when empty | Added `!canSubmit` to disabled |
| 3 | RFI | `rfi/RFIPage.tsx` | Yes | No | Yes (`errors` state) | Yes (`validate()`) | Button not disabled when empty | Added `canSubmit` + `disabled={isPending \|\| !canSubmit}` |
| 4 | NCR | `ncr/NCRPage.tsx` | Yes | No | Yes (`titleError`/`descError`) | Yes (`canSubmit` guard) | Button not disabled when empty | Added `!canSubmit` to disabled |
| 5 | Submittal | `submittals/SubmittalsPage.tsx` | Yes | No | Yes (`titleError`/`specError`) | Yes (`canSubmit` guard) | Button not disabled when empty | Added `!canSubmit` to disabled |
| 6 | Inspection | `inspections/InspectionsPage.tsx` | Yes | No | Yes (`titleError`/`dateError`) | Yes (`canSubmit` guard) | Button not disabled when empty | Added `!canSubmit` to disabled |
| 7 | Correspondence | `correspondence/CorrespondencePage.tsx` | Yes | No | Yes (`subjectError`/`fromError`) | Yes (`canSubmit` guard) | Button not disabled when empty | Added `!canSubmit` to disabled |
| 8 | Contact | `contacts/ContactsPage.tsx` | Yes | No | Yes (`errors` state) | Yes (`validate()`) | Button not disabled when empty | Added `canSubmit` + `disabled={isPending \|\| !canSubmit}` |
| 9 | Budget (Finance) | `finance/FinancePage.tsx` | Yes | No | Yes (`budgetErrors` state) | Yes (`validateBudget()`) | Button not disabled when empty | Added `canSubmitBudget` + wired to disabled |
| 10 | Invoice (Finance) | `finance/FinancePage.tsx` | Yes | No | Yes (`invoiceErrors` state) | Yes (`validateInvoice()`) | Button not disabled when empty | Added `canSubmitInvoice` + wired to disabled |
| 11 | PO (Procurement) | `procurement/ProcurementPage.tsx` | No (missing) | No | Yes (`poErrors` state) | Yes (`validatePO()`) | Button not disabled + no `*` on items | Added `canSubmitPO` + disabled + `*` on Items section |
| 12 | Incident (Safety) | `safety/SafetyPage.tsx` | Yes | No | Yes (`incidentErrors` state) | Yes (`validateIncident()`) | Button not disabled when empty | Added `canSubmitIncident` + wired to disabled |
| 13 | Observation (Safety) | `safety/SafetyPage.tsx` | Yes (description) | Partial | No (no error state) | No (only inline disable check) | No validate fn, no inline errors | Added `obsErrors` state + `validateObs()` + inline error on description + `canSubmitObs` |
| 14 | Transmittal | `transmittals/TransmittalsPage.tsx` | Yes | No | Yes (`subjectError`) | Yes (`canSubmit` guard) | Button not disabled when empty | Added `!canSubmit` to disabled |

---

## Issues Found and Fixed

### Issue 1: Submit buttons only disabled during API pending (ALL 14 forms)

**Problem**: Every form's submit button had `disabled={isPending}` (or `disabled={createXxxMut.isPending}`), which only disables during the network call. Users could click the submit button when required fields were empty. While most forms did prevent the API call via a `validate()` or `canSubmit` guard in the click handler, the button appeared enabled and clickable -- poor UX and accessibility.

**Fix**: Added validation-based disable to all submit buttons: `disabled={isPending || !canSubmit}`.

**Files changed**:
- `frontend/src/features/tasks/TasksPage.tsx`
- `frontend/src/features/meetings/MeetingsPage.tsx`
- `frontend/src/features/rfi/RFIPage.tsx`
- `frontend/src/features/ncr/NCRPage.tsx`
- `frontend/src/features/submittals/SubmittalsPage.tsx`
- `frontend/src/features/inspections/InspectionsPage.tsx`
- `frontend/src/features/correspondence/CorrespondencePage.tsx`
- `frontend/src/features/contacts/ContactsPage.tsx`
- `frontend/src/features/finance/FinancePage.tsx` (budget + invoice)
- `frontend/src/features/procurement/ProcurementPage.tsx`
- `frontend/src/features/safety/SafetyPage.tsx` (incident + observation)
- `frontend/src/features/transmittals/TransmittalsPage.tsx`

### Issue 2: Safety Observation form lacked proper validation (1 form)

**Problem**: The observation create form had no `validate()` function, no error state, and no inline error messages. It only had an inline `!obsForm.description.trim()` check on the button disabled prop.

**Fix**: Added `obsErrors` state, `validateObs()` function, `canSubmitObs` computed flag, inline error display under the description textarea with red border highlight, and updated the submit button to call `validateObs()` before `createObsMut.mutate()`.

**File changed**: `frontend/src/features/safety/SafetyPage.tsx`

### Issue 3: Procurement PO form missing required field marker (1 form)

**Problem**: The Items section (which requires at least one line item with a description) had no `*` asterisk to indicate it is required.

**Fix**: Added `<span className="text-semantic-error">*</span>` to the Items section heading.

**File changed**: `frontend/src/features/procurement/ProcurementPage.tsx`

---

## Validation Patterns Used

The codebase uses two validation patterns, both now properly connected to the submit button:

### Pattern A: `validate()` + `errors` state (Tasks, RFI, Contacts, Finance, Procurement, Safety Incident/Observation)
- `errors` state object with field-keyed error messages
- `validate()` function populates errors and returns boolean
- `handleSubmit()` calls `validate()` and returns early on failure
- Inline error `<p>` tags conditionally rendered per field
- Field inputs get red border via `clsx(..., errors.field && 'border-semantic-error ...')`
- Errors clear on field change via `if (errors[key]) setErrors(...)`

### Pattern B: `canSubmit` + `touched` + computed error flags (Meetings, NCR, Submittals, Inspections, Correspondence, Transmittals)
- `touched` state boolean, set true on first submit attempt
- `canSubmit` computed boolean from required field values
- Individual `xxxError` computed booleans (`touched && field.length === 0`)
- `handleSubmit()` sets `touched=true`, then checks `canSubmit`
- Inline error `<p>` tags rendered when `xxxError` is true
- Field inputs get red border via `clsx(..., xxxError && 'border-semantic-error ...')`

---

## TypeScript Verification

All changes pass `tsc --noEmit` with zero errors.
