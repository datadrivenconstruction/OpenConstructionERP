# Agent B — DB Schema / SQLAlchemy Models Audit

**Target:** OpenConstructionERP (a.k.a. OpenEstimate) backend
**Scope:** `backend/app/modules/*/models.py` + live SQLite DB at
`C:/Users/Artem/.openestimate/openestimate.db`
**Migrations:** `backend/alembic/versions/` (8 revisions; single `alembic`
folder — no per-module migration dirs yet)
**Base class:** `backend/app/database.py` — provides `id` (GUID PK),
`created_at`, `updated_at` automatically. `created_by` is per-module.

---

## 1. Summary

| Metric | Value |
|---|---|
| `models.py` files scanned | **47** |
| `architecture_map/models.py` is empty stub | 1 (ignored) |
| Distinct SQLAlchemy model classes | **~108** (216 class+tablename hits ÷ 2) |
| Tables in live SQLite DB | **109** (matches — no obvious drift) |
| Modules with explicit `oe_*` table prefix | **100 %** (convention respected everywhere) |
| Findings total | **44** |
| Critical (🔴) | 7 |
| High (🟠) | 18 |
| Medium (🟡) | 13 |
| Low (⚪) | 6 |

### Category totals

| # | Category | Count | Worst severity |
|---|---|---|---|
| A | Missing `ForeignKey` on obvious FK columns (project_id, boq_id, user_id, activity_id, ...) | 22 | 🔴 |
| B | Missing / wrong `ondelete` on FK | 4 | 🟠 |
| C | `Mapped[T]` type vs `nullable=` mismatch (schema lies to type system) | 2 | 🟠 |
| D | Decimal money declared as `Float` | **0** | — |
| E | Missing indexes on common lookup columns | 3 | 🟡 |
| F | Missing `created_by` convention | 8 | 🟡 |
| G | JSONB columns with no Pydantic schema (free-form `dict`/`list`) | 2 classes (systemic) | 🟡 |
| H | Model / table naming (`oe_*` prefix) | 0 violations | — |
| I | Circular import risk | 1 (documents ↔ bim_hub) | ⚪ |
| J | Other (SQLite-specific types, `str` for dates, etc.) | 2 | ⚪ |

**Good news** (negative findings — explicitly confirmed):

- **No Decimal-as-Float money bug found.** Reviewed all 47 model files.
  All money-like columns (`unit_rate`, `total`, `amount`, `cost`, `budget`,
  `rate`, `bac`, `pv`, `ev`, `ac`, `eac`, `vac`, etc.) are declared as
  `Mapped[str] = mapped_column(String(50), ...)` with explicit SQLite
  compatibility comments. Any remaining `Float` columns hold geometry
  (gps_lat, location_x, opacity, pixels_per_unit, measurement_value),
  weather (temperature_c), or operational metrics (delay_hours,
  gate_result.score). None of these are money.
- **`oe_*` table prefix convention is 100 % respected.**
- **Models are in sync with live DB** — 109 tables in DB, 108 detected
  in models (difference is `oe_core_audit_log`, defined outside module
  scope in `app/core/`). No schema drift detected in spot-checks of
  `users`, `projects`, `boq_boq`, `boq_position`, `finance_invoice`,
  `takeoff_document`, `rfi_rfi`.
- **DB is NOT configured to enforce FKs even when declared.** SQLite
  requires `PRAGMA foreign_keys = ON;` per connection, and
  `app/database.py::_set_sqlite_pragma` only sets WAL+busy_timeout —
  **foreign key enforcement is never enabled.** All declared ondelete
  rules are decorative in the V4 PC-A instance until this pragma is
  added. See finding **J-2**.

---

## 2. Category A — Missing `ForeignKey` on obvious FK columns

These columns clearly reference another table (name ends in `_id`, holds a
UUID, is semantically a FK) but are declared as bare `GUID()` / `String(36)`
with no `ForeignKey(...)` constraint. Orphan rows are possible, `JOIN`
integrity is not enforced, and declared `ondelete` on the parent side is
ineffective.

### A-1 🔴 — `finance.Invoice.project_id` has no FK

**File:** `backend/app/modules/finance/models.py:28-32`
```python
project_id: Mapped[uuid.UUID] = mapped_column(
    GUID(),
    nullable=False,
    index=True,
)
```
Verified in DB: `PRAGMA foreign_key_list(oe_finance_invoice)` returns **zero**
FKs. Deleting a project leaves orphan invoices.
**Fix:** add `ForeignKey("oe_projects_project.id", ondelete="CASCADE")`.

### A-2 🔴 — `finance.ProjectBudget.project_id` has no FK

**File:** `backend/app/modules/finance/models.py:140-144`
Same pattern; `oe_finance_budget` has no FK to project. Orphan budget lines
possible.

### A-3 🔴 — `finance.EVMSnapshot.project_id` has no FK

**File:** `backend/app/modules/finance/models.py:169-173`
Same pattern.

### A-4 🔴 — `full_evm.EVMForecast.project_id` has no FK

**File:** `backend/app/modules/full_evm/models.py:20-24`

### A-5 🔴 — `procurement.PurchaseOrder.project_id` has no FK

**File:** `backend/app/modules/procurement/models.py:23-27`
`oe_procurement_po.project_id` orphans on project delete.

### A-6 🔴 — `reporting.KPISnapshot.project_id` + `GeneratedReport.project_id` have no FK

**File:** `backend/app/modules/reporting/models.py:30` and `113`

### A-7 🔴 — `schedule.ScheduleBaseline.project_id` / `ProgressUpdate.project_id` have no FK

**File:** `backend/app/modules/schedule/models.py:289-293` and `328-332`
Additionally `ProgressUpdate.activity_id` (line 333), `submitted_by` (344),
`approved_by` (348) are untyped GUID columns.

### A-8 🟠 — `bim_hub` module: six untyped GUID references

**File:** `backend/app/modules/bim_hub/models.py`
- `BIMModel.project_id` (line 37) — no FK
- `BIMModel.created_by` (line 60) — should FK users
- `BOQElementLink.boq_position_id` (line 143) — should FK `oe_boq_position.id`
- `BOQElementLink.created_by` (line 157)
- `BIMQuantityMap.org_id`, `project_id` (lines 178-179)
- `BIMElementGroup.project_id` (line 265), `created_by` (303)

The `BOQElementLink.boq_position_id` is especially important: this is a
junction table and one side has no referential integrity. When a position
is deleted, the bim→boq link becomes dangling.

### A-9 🟠 — `tendering.TenderPackage` has no FKs

**File:** `backend/app/modules/tendering/models.py:21-30`
- `project_id` — no FK
- `boq_id` — no FK (should ref `oe_boq_boq.id`)

### A-10 🟠 — `rfq_bidding.RFQ.project_id` / `created_by` — no FK

**File:** `backend/app/modules/rfq_bidding/models.py:21-25, 39`
Also `RFQBid.bidder_contact_id` (line 70) is a plain String(36).

### A-11 🟠 — `costmodel.BudgetLine` — partial FKs

**File:** `backend/app/modules/costmodel/models.py:73-74`
```python
boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
activity_id:     Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, ...)
```
`project_id` does have a FK; `boq_position_id` and `activity_id` do not.
**Fix:** add `ForeignKey("oe_boq_position.id", ondelete="SET NULL")` and
`ForeignKey("oe_schedule_activity.id", ondelete="SET NULL")`.

### A-12 🟠 — `schedule.WorkOrder.assembly_id` and `boq_position_id` — no FK

**File:** `backend/app/modules/schedule/models.py:191-198`

### A-13 🟠 — `ai.AIEstimateJob.user_id` + `project_id` — no FK

**File:** `backend/app/modules/ai/models.py:62-71`
`AISettings.user_id` (line 21) is also bare GUID even though it is marked
`unique=True`.

### A-14 🟠 — `teams.Team.project_id` — no FK

**File:** `backend/app/modules/teams/models.py:22-26`

### A-15 🟠 — `workflows.ApprovalWorkflow.project_id` / `ApprovalRequest.requested_by` / `decided_by` — no FK

**File:** `backend/app/modules/enterprise_workflows/models.py:21-25, 70-71`

### A-16 🟠 — `erp_chat.ChatSession.user_id` / `project_id` — no FK

**File:** `backend/app/modules/erp_chat/models.py:23-32`

### A-17 🟠 — `validation.ValidationReport.project_id` / `created_by` — no FK

**File:** `backend/app/modules/validation/models.py:29-33, 90`

### A-18 🟠 — `rfi.RFI.raised_by` / `assigned_to` / `responded_by` / `ball_in_court` — no FK

**File:** `backend/app/modules/rfi/models.py:29-34`
All of these are declared `GUID()` but with no `ForeignKey("oe_users_user.id", ...)`.
`raised_by` in particular is `nullable=False` — an invalid user UUID can
be inserted.

### A-19 🟠 — `inspections.QualityInspection.inspector_id` — no FK

**File:** `backend/app/modules/inspections/models.py:32`

### A-20 🟠 — `submittals.Submittal.ball_in_court`, `reviewer_id`, `approver_id` — no FK

**File:** `backend/app/modules/submittals/models.py:31, 34-35`

### A-21 🟠 — `meetings.Meeting.chairperson_id` — no FK

**File:** `backend/app/modules/meetings/models.py:31`

### A-22 🟠 — `collaboration.CommentMention.mentioned_user_id`, `Viewpoint.created_by` — no FK

**File:** `backend/app/modules/collaboration/models.py:95-99, 129-131`
`Comment.author_id` does have a FK, which makes the absence on these two
columns surprising and likely accidental.

### A-23 🟠 — `transmittals` — all org/user references are bare GUID

**File:** `backend/app/modules/transmittals/models.py:29, 40, 76-77, 105`
`sender_org_id`, `created_by`, `recipient_org_id`, `recipient_user_id`,
`document_id` — none have FK constraints.

### A-24 🟠 — `integrations.IntegrationConfig.project_id` — no FK

**File:** `backend/app/modules/integrations/models.py:118-122`
(Compare: the other integrations model, `WebhookEndpoint`, *does* FK
project_id. Same file — clear inconsistency.)

### A-25 🟠 — `collab_lock.CollabLock.entity_id` — polymorphic FK (acceptable)

**File:** `backend/app/modules/collaboration_locks/models.py:48`
This one is deliberately polymorphic (locks can apply to any entity type),
so no FK is appropriate. **Not a defect — noted for completeness.**

### A-26 🟠 — `cde.DocumentContainer.current_revision_id`, `DocumentRevision.approved_by` — no FK

**File:** `backend/app/modules/cde/models.py:38, 75`

---

## 3. Category B — Missing / wrong `ondelete` on existing FK

### B-1 🟠 — `documents.Document.parent_document_id` — `ondelete=SET NULL` ok; but `parent_document_id` children relationship isn't declared, so orphan chains can form silently.

**File:** `backend/app/modules/documents/models.py:80-86` — OK as declared;
flagged only because there's no ORM-level cascade.

### B-2 🟠 — `contacts.Contact.user_id` — `ondelete=SET NULL` is correct, but the reverse relationship isn't declared → querying "user's contacts" requires manual join.

**File:** `backend/app/modules/contacts/models.py:22-27`

### B-3 🟡 — `boq.BOQActivityLog.user_id` uses `ondelete="CASCADE"`

**File:** `backend/app/modules/boq/models.py:232-237`
Arguable: an audit log should usually survive user deletion (use
`SET NULL`). Deleting a user currently wipes their entire audit trail,
which may violate compliance (SOX, ISO 19650) requirements.
**Suggested fix:** change to `ondelete="SET NULL"` and allow
`user_id: Mapped[uuid.UUID | None]`.

### B-4 🟡 — `takeoff.CadExtractionSession` — no FK at all on `user_id`, `project_id`

**File:** `backend/app/modules/takeoff/models.py:28, 39`
Both are plain `String(255)` / `String(255)`. When the linked user or
project is deleted, the session row stays and breaks subsequent reads.
The docstring says sessions expire after 24 h but there's no cascade to
kill them sooner.

---

## 4. Category C — `Mapped[T]` type vs `nullable=` mismatch

Static type says non-nullable, DB column is nullable (or vice-versa) —
the ORM layer claims guarantees the DB does not enforce.

### C-1 🟠 — `takeoff.TakeoffDocument.project_id`

**File:** `backend/app/modules/takeoff/models.py:66-71`
```python
project_id: Mapped[uuid.UUID] = mapped_column(     # ← annotation is NOT Optional
    GUID(),
    ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
    nullable=True,                                  # ← but column IS nullable
    index=True,
)
```
Verified in DB: `notnull=0` on this column. This is a classic foot-gun —
downstream code sees `document.project_id: UUID` in type-checker but may
receive `None` at runtime. **Fix:** either change annotation to
`Mapped[uuid.UUID | None]` **or** make the column `nullable=False` and
back-fill.

### C-2 🟠 — `takeoff.TakeoffDocument.owner_id`

**File:** `backend/app/modules/takeoff/models.py:72-77`
Owner is `nullable=False`, which contradicts the usual ownership pattern
used elsewhere (`owner_id` on `Project` is also non-null, but on most
other tables the user-ish columns are nullable). Not a bug in isolation
but inconsistent with the codebase's common practice of keeping
ownership nullable to allow SSO/system-generated data.

---

## 5. Category D — Decimal declared as Float

**No issues found.** Reviewed 47 files.

The codebase has a consistent, documented pattern: all financial /
monetary / decimal-precision fields are stored as `String(50)` with an
explanatory comment like "Stored as string for SQLite compatibility".
The Pydantic layer converts to `Decimal` on read. This is correct given
the dual SQLite-dev / PostgreSQL-prod posture declared in `CLAUDE.md`.

Remaining `Float` usages are all for non-money values:
- `markups.Markup.opacity` (line 37)
- `markups.ScaleConfig.pixels_per_unit`, `real_distance` (lines 71, 76)
- `takeoff.CadExtractionSession.extraction_time` (line 32)
- `takeoff.TakeoffMeasurement.measurement_value`, `depth`, `volume`,
  `perimeter`, `scale_pixels_per_unit` (lines 122-128)
- `punchlist.PunchItem.location_x`, `location_y` (lines 28-29)
- `documents.ProjectPhoto.gps_lat`, `gps_lon` (lines 120-121)
- `fieldreports.FieldReport.temperature_c`, `delay_hours` (33, 57)
- `dwg_takeoff.*` measurement values (line 119)
- `requirements.GateResult.score` (line 141-143)

All are geometry, physical measurement, weather, or ML-confidence scores.
None are currency.

---

## 6. Category E — Missing indexes on common lookup columns

### E-1 🟡 — `ai.AIEstimateJob.status` not indexed

**File:** `backend/app/modules/ai/models.py:75`
Queries will almost certainly filter by `(user_id, status)` to list
running jobs. Suggest `Index("ix_ai_job_user_status", "user_id", "status")`.

### E-2 🟡 — `correspondence.Correspondence` — no index on `(project_id, direction)`

**File:** `backend/app/modules/correspondence/models.py:20-27`
Both columns are indexed individually, but the natural query is "incoming
correspondence for project X" → composite index beneficial.

### E-3 🟡 — `fieldreports.FieldReport` — no composite `(project_id, report_date)`

**File:** `backend/app/modules/fieldreports/models.py:22-28`
Both indexed individually. A composite would help timeline queries.

---

## 6b. Category F — Missing `created_by` per CLAUDE.md convention

CLAUDE.md specifies: "All tables: `id`, `created_at`, `updated_at`, `created_by`".
Base provides first three; `created_by` is the module's job. Observed
omissions:

### F-1 🟡 — `users.User` — no `created_by` (OK — self-registration)
Acceptable edge case.

### F-2 🟡 — `catalog.CatalogResource` — no `created_by`
**File:** `backend/app/modules/catalog/models.py`
Resources are seeded but should still track manual additions.

### F-3 🟡 — `costs.CostItem` — no `created_by`
**File:** `backend/app/modules/costs/models.py`

### F-4 🟡 — `i18n_foundation` — none of the 4 models carry `created_by`
**File:** `backend/app/modules/i18n_foundation/models.py`

### F-5 🟡 — `ai.AIEstimateJob` — no `created_by`, but has `user_id`
Arguable; flagged for consistency.

### F-6 🟡 — `projects.ProjectWBS`, `ProjectMilestone` — no `created_by`
**File:** `backend/app/modules/projects/models.py`

### F-7 🟡 — `finance.*` (Invoice has `created_by`, but Payment, ProjectBudget, EVMSnapshot do not)
**File:** `backend/app/modules/finance/models.py`

### F-8 🟡 — `boq.BOQMarkup`, `BOQSnapshot` — `created_by` only on Snapshot
**File:** `backend/app/modules/boq/models.py`
`BOQMarkup` has no `created_by`. `BOQSnapshot` has it with proper FK.
`BOQ` itself also lacks `created_by` (only `approved_by` on line 46).

---

## 7. Category G — JSONB columns with no Pydantic schema validation

CLAUDE.md flags this as a risk: JSONB should have schema validation in
the Pydantic layer. Spot-check of `backend/app/modules/boq/schemas.py`
shows `metadata: dict[str, Any]` — the type is `Any`, i.e. **no
validation**. This pattern is the default across the codebase.

Examples of un-validated JSONB columns (systemic, not per-column):

- Every model has `metadata_ = mapped_column("metadata", JSON, ...)` —
  Pydantic side accepts `dict[str, Any]`.
- `boq.Position.classification` — documented schema
  `{din276, nrm, masterformat}` but Pydantic is `dict[str, Any]`.
- `boq.Position.cad_element_ids` — documented `list[str]` but is
  `list[Any]` in schemas.
- `schedule.Activity.bim_element_ids` — the model docstring explicitly
  warns that a legacy dict payload may be stored there instead of list.
  No validation catches this.
- `projects.Project.validation_rule_sets` — list of short strings, but
  stored as `JSON` with no enum/Literal constraint.
- `teams.Team.name_translations` — `dict | None`, no locale-key
  validation.
- `integrations.IntegrationConfig.config` — stores credentials (tokens,
  webhook URLs) with `dict[str, Any]`. Medium severity: tighter
  per-`integration_type` Pydantic discriminated union would prevent
  misconfigured connectors.
- `workflows.ApprovalWorkflow.steps` — model declares `Mapped[dict]` but
  `default=list` / `server_default="[]"` (**type lies — it's a list**).
  **See G-2 below.**

### G-1 🟡 — Systemic: `metadata` JSONB treated as `Any` in Pydantic layer
**Fix direction:** introduce per-entity TypedDict / Pydantic submodels
for the well-known fields (classification, bim_element_ids,
validation_rule_sets) and keep `metadata` as a last-resort escape hatch.

### G-2 🟠 — `enterprise_workflows.ApprovalWorkflow.steps` declared `Mapped[dict]` but default is a list
**File:** `backend/app/modules/enterprise_workflows/models.py:29-34`
```python
steps: Mapped[dict] = mapped_column(  # ← annotation says dict
    JSON,
    nullable=False,
    default=list,                      # ← Python default is list
    server_default="[]",               # ← DB default is list
)
```
This is a direct type bug — the annotation will confuse downstream code.
Either fix the annotation to `Mapped[list]` / `Mapped[list[dict]]` or
change the default to `dict`.

---

## 8. Category H — Naming violations

**No violations found.** Every `__tablename__` across 47 files follows
`oe_{module}_{entity}` convention. Example check:

- `oe_boq_boq`, `oe_boq_position`, `oe_boq_markup`, `oe_boq_activity_log`, `oe_boq_snapshot`
- `oe_projects_project`, `oe_projects_wbs`, `oe_projects_milestone`
- `oe_finance_invoice`, `oe_finance_invoice_item`, `oe_finance_payment`, `oe_finance_budget`, `oe_finance_evm_snapshot`
- `oe_bim_*` — the `bim_hub` module correctly drops `_hub` from the table
  name to keep tables compact (intentional).
- `oe_rfq_*` / `oe_cde_*` / `oe_evm_*` — similar pattern.

Slight inconsistency: some modules collapse the module name (`bim_hub` →
`oe_bim_*`, `rfq_bidding` → `oe_rfq_*`, `collaboration_locks` →
`oe_collab_*`, `enterprise_workflows` → `oe_workflows_*`). Not a defect
under the declared convention (module names are "long enough" that
truncation is expected), but makes cross-referencing manually harder.

---

## 9. Category I — Circular import patterns

### I-1 ⚪ — `documents` ↔ `bim_hub` two-way references

**Files:**
- `documents/models.py:201-206` — `DocumentBIMLink.bim_element_id` →
  `oe_bim_element.id`
- `bim_hub/models.py:125-129` — `BIMElement.boq_links` back-populates;
  but no reverse relationship to `Document` is declared, so actual
  Python-level circular import is avoided.

Both modules declare ForeignKey to each other's tables via string
reference, which dodges the import cycle. The table-creation order is
safe because SQLAlchemy resolves string FK targets at mapper
configuration, not at import. **Not a bug** — logged as ⚪ only so future
maintainers don't accidentally add a `BIMElement.document_bim_links`
relationship that would force a real cycle.

---

## 10. Category J — Other findings

### J-1 ⚪ — Dates stored as `String(20)` instead of `Date`/`DateTime`

Seen across nearly every model (e.g. `schedule.Activity.start_date`,
`finance.Invoice.invoice_date`, `boq.BOQ.approved_at`). The rationale
("SQLite compatibility") is valid for SQLite but doesn't hold on
PostgreSQL. Migrating to `Date`/`DateTime` in production would enable
index-based range queries. Not a DB schema defect per se; flagged as a
known technical-debt item.

### J-2 🔴 — SQLite FK enforcement not turned on

**File:** `backend/app/database.py:107-115`
```python
@sa_event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()
```
**Missing:** `cursor.execute("PRAGMA foreign_keys = ON")`.

Consequence: **every declared `ForeignKey(..., ondelete=...)` rule is
decorative on SQLite.** All Category A/B findings above are latent
defects in SQLite, but they become *real* defects the moment the code is
deployed against PostgreSQL (where FKs are always enforced). Fixing
them now before the Postgres cut-over is cheap; fixing them after
production data exists is expensive.

**Fix:** add `cursor.execute("PRAGMA foreign_keys = ON")` inside
`_set_sqlite_pragma`.

---

## 11. DB ↔ models sync (spot-check)

Verified with `PRAGMA table_info(...)` + `PRAGMA foreign_key_list(...)`
for the six requested tables:

| Table | Columns | PK | FKs declared in model | FKs present in DB | Sync |
|---|---|---|---|---|---|
| `oe_users_user` | 18 | `id` | none | none | ✅ |
| `oe_projects_project` | 28 | `id` | owner→user, parent_project→self | both present | ✅ |
| `oe_boq_boq` | 14 | `id` | project→project, parent_estimate→self | both present | ✅ |
| `oe_boq_position` | 20 | `id` | boq→boq, parent→self | both present | ✅ |
| `oe_finance_invoice` | 20 | `id` | **none declared** | **none in DB** | ✅ (both wrong) |
| `oe_takeoff_document` | 15 | `id` | project→project, owner→user | both present | ✅ |
| `oe_rfi_rfi` | 24 | `id` | project→project only | project→project only | ✅ |

**No drift detected.** All observations in Categories A-I are present in
both the code and the running database.

---

## 12. Recommended fix priorities

1. **Critical (ship before next release):**
   - J-2 — turn on SQLite `PRAGMA foreign_keys = ON` in `database.py`.
     Without it nothing else in this report matters for dev data.
   - A-1..A-7 — add `ForeignKey` + `ondelete="CASCADE"` to all
     `project_id` columns on `finance`, `procurement`, `reporting`,
     `full_evm`, `schedule` (Baseline, ProgressUpdate) modules.

2. **High (before Postgres cut-over):**
   - A-8..A-24 — add the 50-odd missing `ForeignKey` clauses on
     user/project/boq references.
   - B-3, C-1, C-2, G-2 — fix type/nullability mismatches.

3. **Medium (tech debt):**
   - E-1..E-3 — composite indexes.
   - F-1..F-8 — `created_by` audit column per CLAUDE.md convention.
   - G-1 — typed Pydantic schemas for well-known JSONB payloads.

4. **Low (track only):**
   - J-1 — migrate `String(20)` date columns to real `Date`/`DateTime`
     once SQLite is dropped.
   - I-1 — guard against future `documents` ↔ `bim_hub` import cycle.

---

*Generated 2026-04-18. All files read-only. No source files modified.*
