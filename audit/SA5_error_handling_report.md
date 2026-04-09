# SA-5: Error Handling Audit Report

**Date**: 2026-04-09
**Scope**: All `router.py`, `service.py` files (backend), all `useMutation` hooks (frontend)

---

## Summary

| Category | Found | Fixed | Remaining (acceptable) |
|----------|-------|-------|------------------------|
| Backend: silent `except Exception: pass` | 39 | 39 | 0 |
| Backend: silent `except (ValueError,TypeError): pass` | 32 | 0 | 32 (type conversion guards) |
| Backend: `except ImportError: pass` | 8 | 0 | 8 (optional module checks) |
| Frontend: `useMutation` missing `onError` | 29 | 29 | 0 |
| **Total** | **108** | **68** | **40** |

---

## Backend Fixes

### 1. projects/router.py -- Dashboard endpoint (20 fixes)

The `GET /{project_id}/dashboard` endpoint had ~20 `except Exception: pass` blocks
that silently swallowed errors when querying optional modules (punchlist, inspections,
NCR, risk, documents, transmittals, RFIs, submittals, tasks, meetings, procurement,
requirements, markups, field reports, photos, takeoff, change orders, and activity feed).

**Fix**: All replaced with `logger.debug("Dashboard: <module> query failed", exc_info=True)`.
These are intentional graceful degradation (module may not be installed), but now
failures are visible in debug logs.

**Files changed**: `backend/app/modules/projects/router.py`

### 2. reporting/service.py -- KPI snapshot aggregation (7 fixes)

The KPI snapshot recalculation silently swallowed errors when fetching data from
finance, cost model, safety, RFI, submittals, schedule, and risk modules.

**Fix**: All replaced with `logger.debug("KPI snapshot: <data source> unavailable", exc_info=True)`.

**Files changed**: `backend/app/modules/reporting/service.py`

### 3. ai/router.py -- Project context lookup (1 fix)

The AI advisor endpoint silently swallowed errors when looking up project context
for the chat prompt.

**Fix**: `logger.debug("AI advisor: project context lookup failed", exc_info=True)`

**Files changed**: `backend/app/modules/ai/router.py`

### 4. costs/router.py -- Vector search fallback (4 fixes)

Multiple silent failures in vector search, component lookups, and LanceDB table access.

**Fix**: Added `logger.debug(...)` for each catch block describing the specific failure.

**Files changed**: `backend/app/modules/costs/router.py`

### 5. boq/router.py -- Activity log, parsing, assembly (5 fixes)

- Activity log project_id resolution: silent failure when resolving BOQ -> project
- Smart import Excel/CSV parsing: silent failure when structured parsing fails
- Assembly component lookup by cost code: silent failure on JSON parsing

**Fix**: Added `logger.debug(...)` for each catch block.

**Files changed**: `backend/app/modules/boq/router.py`

### 6. takeoff/service.py -- PDF extraction fallback (1 fix)

When both pdfplumber and pymupdf fail to extract PDF content, the error was completely
silenced, returning an empty list with no indication of failure.

**Fix**: `logger.warning("PDF extraction failed with both pdfplumber and pymupdf")`
(warning level because this is a real data loss scenario).

**Files changed**: `backend/app/modules/takeoff/service.py`

### 7. backup/router.py -- Duplicate check during restore (1 fix)

Silent failure when checking for duplicate records during backup restore.

**Fix**: `logger.debug("Duplicate check failed for %s, attempting insert", backup_key)`

**Files changed**: `backend/app/modules/backup/router.py`

### 8. boq/cad_import.py -- DDC converter discovery (1 fix)

Silent failure when discovering DDC converter binaries via importlib.

**Fix**: `logger.debug("DDC converter discovery via importlib failed", exc_info=True)`

**Files changed**: `backend/app/modules/boq/cad_import.py`

---

## Frontend Fixes

### 9. useMutation hooks missing onError (29 fixes)

All 166 `useMutation` hooks across the frontend were audited. 29 were missing
`onError` handlers, meaning API failures would be completely invisible to users.

**Fixed mutations by file**:

| File | Mutations fixed | Error handling added |
|------|----------------|---------------------|
| `BOQEditorPage.tsx` | 4 | addToast with error type |
| `MarkupPanel.tsx` | 4 | addToast with error type |
| `CommentThread.tsx` | 3 | addToast (added useToastStore import) |
| `NotificationBell.tsx` | 2 | console.warn (low-severity) |
| `DashboardPage.tsx` | 2 | addToast with error type |
| `FieldReportsPage.tsx` | 3 | addToast with error type |
| `CadDataExplorerPage.tsx` | 1 | console.error |
| `CostModelPage.tsx` | 4 | addToast / console.error |
| `ValidationPage.tsx` | 1 | addToast with error type |
| `SustainabilityPage.tsx` | 2 | alert / console.error |
| `IntegrationsPage.tsx` | 1 | addToast with error type |
| `OnboardingWizard.tsx` | 1 | addToast with error type |
| `CreateAssemblyPage.tsx` | 1 | addToast (added useToastStore import) |

---

## Not Fixed (Acceptable Patterns)

### Type conversion guards (32 instances)

Pattern: `except (ValueError, TypeError): pass` after `float(x)`, `int(x)`, `Decimal(x)`

These are safe data-cleaning patterns where a variable keeps its default value on
conversion failure. Found in: assemblies, boq, catalog, costmodel, documents,
fieldreports, punchlist, rfi, risk, safety, schedule, takeoff, tasks.

### Optional module imports (8 instances)

Pattern: `except ImportError: pass` in `projects/service.py`

These check whether optional modules (schedule, finance, etc.) are installed.
By design, missing modules should not cause errors.

### Cell formatting (1 instance)

Pattern: `except Exception: pass` in `takeoff/router.py:1127`

A benign `len(str(cell.value))` guard during Excel column auto-fit. No data impact.

---

## Verification

After all fixes:
- **0** `useMutation` hooks without `onError` (was 29)
- **1** `except Exception: pass` remaining in router/service files (takeoff Excel formatting -- benign)
- **0** `except Exception: pass` in business logic paths (was 39)
- All remaining silent catches are type conversion guards (`ValueError`/`TypeError`) or optional import checks

### Files modified (backend -- 8 files)
- `backend/app/modules/projects/router.py`
- `backend/app/modules/reporting/service.py`
- `backend/app/modules/ai/router.py`
- `backend/app/modules/costs/router.py`
- `backend/app/modules/boq/router.py`
- `backend/app/modules/boq/cad_import.py`
- `backend/app/modules/takeoff/service.py`
- `backend/app/modules/backup/router.py`

### Files modified (frontend -- 12 files)
- `frontend/src/features/boq/BOQEditorPage.tsx`
- `frontend/src/features/boq/MarkupPanel.tsx`
- `frontend/src/shared/ui/CommentThread.tsx`
- `frontend/src/shared/ui/NotificationBell.tsx`
- `frontend/src/features/dashboard/DashboardPage.tsx`
- `frontend/src/features/fieldreports/FieldReportsPage.tsx`
- `frontend/src/features/cad-explorer/CadDataExplorerPage.tsx`
- `frontend/src/features/costmodel/CostModelPage.tsx`
- `frontend/src/features/validation/ValidationPage.tsx`
- `frontend/src/features/sustainability/SustainabilityPage.tsx`
- `frontend/src/features/integrations/IntegrationsPage.tsx`
- `frontend/src/features/onboarding/OnboardingWizard.tsx`
- `frontend/src/features/assemblies/CreateAssemblyPage.tsx`
