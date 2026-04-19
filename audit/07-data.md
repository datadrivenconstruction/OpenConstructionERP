# 07 — Data Layer Audit

> Focus: decimal precision, currency rounding, timezone, JSONB schema drift, migration hygiene. Builds on Phase 0 finding C-01 (220 money columns stored as `String(50)`) — this file tracks the *consequences* of that choice, plus orthogonal integrity issues.

---

## Summary

| ID | Severity | Area | One-liner |
|----|---------:|------|-----------|
| D-01 | HIGH | Decimal | `str → float → total` path loses precision beyond 15-17 sig digits |
| D-02 | MED | Decimal | Empty / whitespace / non-numeric strings silently become `0.0` with no audit |
| D-03 | MED | Rounding | Inconsistent quantisation across modules (money.py uses HALF_UP; others default to banker's) |
| D-04 | HIGH | FE/BE drift | Backend HALF_UP vs browser `Intl.NumberFormat` (Safari < 16 is HALF_UP, modern Chrome/Edge is HALF_EVEN) |
| D-05 | MED | EVM | SPI / CPI quantised to 2 decimals before TCPI / ETC derives from them |
| D-06 | MED | Timezone | Schedule + Finance dates are `String(20)` ISO-only — no time, no TZ |
| D-08 | MED | JSONB | `metadata_` / `properties` / `bim_element_ids` consumed without `.get()` / shape validation |
| D-09 | MED | FK | ~15 modules store `project_id` as loose `String(36)` — orphans survive project delete (cross-ref C-01/H-05b) |
| D-11 | INFO | Alembic | 12 migration files, baseline `129188e46db8` is an intentional no-op placeholder (see C-02) |

---

## D-01 `str → float` round-trip precision loss
- **File**: `backend/app/modules/boq/service.py:706-726` — `_compute_total()` and `_str_to_float()`
- **Pattern**: `Decimal(str_val)` is constructed, but downstream math uses `float()` intermediaries. `"1.23456789012345678"` → `float` → `1.2345678901234567` — precision dropped.
- **Second hit**: `backend/app/modules/boq/service.py:1323` — resource metadata calculations bypass Decimal guards entirely.
- **Impact**: a BOQ line that was entered correctly at the API boundary (Decimal-validated) ends up with lossy floats in the computed totals, so `sum(totals)` drifts from `sum(quantity * unit_rate)` computed independently.
- **Fix path**: keep Decimal through the whole calculation; only format at the response boundary.

## D-02 Silent string → numeric coercion
- **File**: `backend/app/modules/boq/service.py:719-726`
- **Pattern**: `_str_to_float("")`, `_str_to_float(" ")`, `_str_to_float("abc")` → `0.0`. No `logger.warning`, no audit entry.
- **Also**: `backend/app/modules/costmodel/service.py` uses the same silent-coerce pattern.
- **Impact**: an invoice line with `unit_rate = ""` silently becomes €0; the user doesn't know the row was dropped from the total.
- **Fix path**: raise at the schema layer (Pydantic `field_validator` — partially already done in `procurement/schemas.py::_validate_non_negative_decimal`). Add the same pattern everywhere money flows.

## D-03 Rounding-policy mismatch
- **Canonical** (`backend/app/core/money.py:173`): `ROUND_HALF_UP` with a fixed 2-decimal quantum.
- **Diverging** call sites:
  - `backend/app/modules/bim_hub/service.py:1322` — relies on Python's default `Decimal` rounding context (`ROUND_HALF_EVEN` banker's).
  - `backend/app/modules/boq/service.py:1490` — quantises quantities to 4 decimals before storage, then downstream code re-quantises to 2. Double-round = occasional 1-cent drift.
- **Impact**: totals summed in `bim_hub` can be 1 cent off the same numbers summed in `boq`.
- **Fix path**: all money touchpoints MUST import from `core.money` — grep the backend for ad-hoc `Decimal(...).quantize(...)` to find and standardise.

## D-04 Frontend vs backend rounding drift
- **Backend**: `backend/app/core/money.py:173` — explicit `ROUND_HALF_UP`.
- **Frontend**: `frontend/src/stores/usePreferencesStore.ts:92-99` and formatters call `Intl.NumberFormat(...).format(value)`, which uses the browser's rounding policy:
  - Chrome / Edge / modern Firefox: `HALF_EVEN` (banker's).
  - Safari < 16 and some embedded webviews: `HALF_UP`.
- **Scenario**: amount `1.235` → backend stores `1.24`, Safari-16+ displays `1.24`, Chrome displays `1.24` (same), but `1.2345` → backend `1.23`, Safari `1.23`, Chrome `1.23` (also same, banker's rounds to even). The edge case hits at exactly-half values — 1¢ per transaction where it lands.
- **Impact**: reconciliation against an externally-printed invoice (backend format) vs what the user sees in the UI can diverge.
- **Fix path**: do all rounding server-side. Frontend should format pre-rounded Decimals as strings, not re-round.

## D-05 EVM intermediate precision
- **File**: `backend/app/modules/full_evm/service.py:110-117`
- **Pattern**: SPI / CPI stored at 2-decimal precision (`0.00`), then TCPI and ETC derive from those rounded values. For `spi = 1.005`, `cpi = 1.003` the product `1.005 * 1.003 ≈ 1.008` but with quantisation the inputs round to `1.01` each → `1.01 * 1.01 = 1.0201`. Compound drift.
- **Impact**: small EVM metric drift — not visible on one project, noticeable when aggregating a portfolio.
- **Fix path**: keep intermediates at 4-6 decimals, quantise only at the output boundary.

## D-06 Date-only fields for schedule + finance
- **Timezone-aware** (good): `backend/app/database.py:78, 83` — `DateTime(timezone=True)` for the `created_at` / `updated_at` audit columns inherited by every model via `Base`.
- **Timezone-naïve strings** (bad):
  - `backend/app/modules/schedule/models.py:85-86` — `start_date` / `end_date` as `String(20)` ISO `YYYY-MM-DD`. No time, no TZ — "due today" in EN-US and RU diverge.
  - `backend/app/modules/finance/models.py:36-37, 110` — `invoice_date`, `due_date` same pattern.
  - `backend/app/scripts/seed_demo_4d5d.py:203` — `datetime.now()` (naïve local) for seed fixtures.
  - `frontend/src/shared/lib/formatters.ts:78` — `toLocaleString()` renders in the browser's TZ, so a user in UTC-8 viewing a Berlin-set due-date sees a different calendar day.
- **Impact**: a project due Thursday in Berlin shows as Wednesday in San Francisco; activities crossing a DST boundary drift by an hour.
- **Fix path**: decide per field — most construction deadlines are date-granular, so just be consistent. If time matters (meeting start), upgrade to `DateTime(timezone=True)` with UTC storage.

## D-08 JSONB schema drift
- **Affected tables**: `oe_boq_position.metadata_`, `oe_bim_element.properties`, `oe_schedule_activity.bim_element_ids`, `oe_validation_result.details`, + ~11 others.
- **Unsafe reads**:
  - `backend/app/modules/boq/service.py:1323` — `for r in metadata_["resources"]` assumes the key exists and is a list. A legacy row with no `resources` key → KeyError.
  - `backend/app/modules/bim_hub/...` — assigns `properties[k] = sval` and later reads `properties[k]` with no shape guard.
  - `Activity.bim_element_ids` annotation says `list | None`, but line 148 comment suggests legacy dict-shaped payloads exist.
- **Impact**: runtime crash on a legacy row that the app created before a feature was added.
- **Fix path**: Pydantic schema per JSONB column, validated on write; all reads through `.get(key, default)` with a documented fallback.

## D-09 Orphan rows from loose project_id strings
- Cross-references Phase 0 H-05b. Re-verified here: `bim_hub`, `finance`, `validation`, `tendering`, `rfq_bidding`, `procurement`, `reporting`, `ai`, `erp_chat`, `transmittals`, schedule `baselines` + `progress`, integrations configs, `enterprise_workflows` all store `project_id` as `String(36)` without a FK constraint.
- **Orphan query path**: `backend/app/modules/bim_hub/repository.py:45` — `select(BIMModel).where(BIMModel.project_id == deleted_id)` will still return rows after the parent project is deleted.
- **Impact**: DB grows with unreachable rows; undelete isn't safe because orphans may refer to the wrong (recycled) project_id.
- **Fix path**: add `ForeignKey("oe_projects_project.id", ondelete="CASCADE")` on each. Small migration per module.

## D-11 Migration hygiene — INFO (pass with notes)
- 12 Alembic migrations total.
- `129188e46db8_init_create_all_tables.py` is a deliberate no-op placeholder — `create_all()` at startup does the heavy lifting. See ERRORS.md C-02 for the structural issue this hides.
- No data migrations (all are schema-only).
- Hybrid auto-create + alembic coexists; new models land on dev via auto-create but need a migration before prod.
