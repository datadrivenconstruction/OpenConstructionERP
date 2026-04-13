# Performance Audit Report

**Date**: 2026-04-09
**Scope**: Backend modules — boq, tasks, meetings, finance, contacts, projects (+ all models.py for index audit)
**Auditor**: Claude Opus 4.6

---

## Summary

| Category | Found | Fixed | Documented |
|----------|-------|-------|------------|
| Missing FK indexes | 9 | 9 | Yes |
| N+1 query patterns | 2 | 0 (documented) | Yes |
| Unbounded queries | 4 | 0 (documented) | Yes |
| Sequential DB queries (parallelizable) | 2 | 0 (documented) | Yes |

---

## 1. Missing Indexes on Foreign Key Fields (FIXED)

All 9 FK fields that were missing `index=True` have been fixed. Without these indexes, any `WHERE` clause filtering on these columns triggers a full table scan.

### Fixed Fields

| Table | Column | FK Target | File |
|-------|--------|-----------|------|
| `oe_bim_model` | `parent_model_id` | `oe_bim_model.id` | `backend/app/modules/bim_hub/models.py` |
| `oe_bim_model_diff` | `old_model_id` | `oe_bim_model.id` | `backend/app/modules/bim_hub/models.py` |
| `oe_bim_model_diff` | `new_model_id` | `oe_bim_model.id` | `backend/app/modules/bim_hub/models.py` |
| `oe_boq_boq` | `parent_estimate_id` | `oe_boq_boq.id` | `backend/app/modules/boq/models.py` |
| `oe_boq_snapshot` | `created_by` | `oe_users_user.id` | `backend/app/modules/boq/models.py` |
| `oe_documents_document` | `parent_document_id` | `oe_documents_document.id` | `backend/app/modules/documents/models.py` |
| `oe_markups_markup` | `stamp_template_id` | `oe_markups_stamp_template.id` | `backend/app/modules/markups/models.py` |
| `oe_procurement_gr_item` | `po_item_id` | `oe_procurement_po_item.id` | `backend/app/modules/procurement/models.py` |
| `oe_projects_project` | `parent_project_id` | `oe_projects_project.id` | `backend/app/modules/projects/models.py` |

> **Note**: A new Alembic migration should be generated to materialize these indexes in the database: `alembic revision --autogenerate -m "add missing FK indexes"`

### Already Correct (no action needed)

All other FK fields across all modules already had `index=True`. Notably well-indexed:
- `project_id` on all module tables (boq, tasks, meetings, finance, etc.)
- `boq_id` on positions and markups
- `invoice_id` on line items and payments
- `user_id` / `owner_id` on projects and activity logs

---

## 2. N+1 Query Patterns (DOCUMENTED)

### 2.1 PositionRepository.reorder() -- N sequential UPDATEs

**File**: `backend/app/modules/boq/repository.py:191-199`
**Severity**: Medium (triggered on manual reorder, not on every request)

```python
async def reorder(self, position_ids: list[uuid.UUID]) -> None:
    for index, pid in enumerate(position_ids):
        stmt = update(Position).where(Position.id == pid).values(sort_order=index)
        await self.session.execute(stmt)  # N separate UPDATE statements
```

**Impact**: For a BOQ with 500 positions, this issues 500 individual UPDATE statements. Each UPDATE round-trips to the database.

**Recommended fix**: Use a single bulk UPDATE with a CASE expression:
```python
from sqlalchemy import case

async def reorder(self, position_ids: list[uuid.UUID]) -> None:
    if not position_ids:
        return
    stmt = (
        update(Position)
        .where(Position.id.in_(position_ids))
        .values(
            sort_order=case(
                {pid: idx for idx, pid in enumerate(position_ids)},
                value=Position.id,
            )
        )
    )
    await self.session.execute(stmt)
```

### 2.2 PositionRepository.bulk_create() -- N sequential refreshes

**File**: `backend/app/modules/boq/repository.py:170-176`
**Severity**: Low (refresh is in-session, not a new query per se, but avoidable)

```python
async def bulk_create(self, positions: list[Position]) -> list[Position]:
    self.session.add_all(positions)
    await self.session.flush()
    for pos in positions:
        await self.session.refresh(pos)  # N refreshes
    return positions
```

**Impact**: Minor -- refresh after flush re-reads server-generated defaults. Could be eliminated if the caller doesn't need refreshed data immediately.

---

## 3. Unbounded Queries (DOCUMENTED)

### 3.1 MeetingRepository.all_for_project() -- loads ALL meetings

**File**: `backend/app/modules/meetings/repository.py:147-160`
**Severity**: Medium

```python
async def all_for_project(self, project_id: uuid.UUID) -> list[Meeting]:
    stmt = (
        select(Meeting)
        .where(Meeting.project_id == project_id)
        .where(Meeting.status.notin_(("cancelled",)))
        .order_by(Meeting.meeting_date.desc())
    )
    # No .limit() -- loads ALL non-cancelled meetings
```

**Callers**: `MeetingService.get_stats()` and `MeetingService.get_open_actions()` both call this to scan JSON `action_items` columns in Python.

**Impact**: A project with 500+ meetings loads all of them just to count open action items. The JSON scanning is also O(meetings * action_items).

**Recommended fix**: For `get_stats()`, move the open action count to SQL using JSON functions, or add a denormalized `open_action_count` column on meetings. For `get_open_actions()`, add pagination.

### 3.2 TaskService.get_stats() -- loads ALL tasks into Python

**File**: `backend/app/modules/tasks/service.py:313-327`
**Severity**: Medium

```python
result = await self.session.execute(base)
tasks = list(result.scalars().all())  # ALL tasks for the project

total = len(tasks)
by_status: dict[str, int] = defaultdict(int)
# ... iterates in Python to compute stats
```

**Impact**: For a project with 1000+ tasks, all rows are loaded into memory for Python-level aggregation that could be done in SQL.

**Recommended fix**: Use SQL `GROUP BY` aggregation (like the finance dashboard already does):
```python
# Count by status
stmt = select(Task.status, func.count()).where(...).group_by(Task.status)
# Count by type
stmt = select(Task.task_type, func.count()).where(...).group_by(Task.task_type)
# Overdue count
stmt = select(func.count()).where(Task.due_date < today, Task.status != "completed")
```

### 3.3 BudgetRepository.list() -- no limit on data fetch

**File**: `backend/app/modules/finance/repository.py:263-281`
**Severity**: Low (budgets per project are typically few)

```python
stmt = base.order_by(ProjectBudget.created_at.desc())
result = await self.session.execute(stmt)
items = list(result.scalars().all())  # No .limit()
```

**Recommended fix**: Add `.limit(500)` as a safety net.

### 3.4 EVMSnapshotRepository.list() -- no limit on data fetch

**File**: `backend/app/modules/finance/repository.py:335-350`
**Severity**: Low (EVM snapshots grow slowly)

```python
stmt = base.order_by(EVMSnapshot.snapshot_date.desc())
result = await self.session.execute(stmt)
items = list(result.scalars().all())  # No .limit()
```

**Recommended fix**: Add `.limit(500)` as a safety net.

---

## 4. Sequential DB Queries That Could Be Parallelized

### 4.1 MeetingService.get_stats() -- stats + all_for_project sequentially

**File**: `backend/app/modules/meetings/service.py:311-333`
**Severity**: Low

```python
raw = await self.repo.stats_for_project(project_id)       # Query 1: 4 SQL statements
meetings = await self.repo.all_for_project(project_id)     # Query 2: loads all meetings
```

`stats_for_project()` itself issues 4 separate queries (total count, by_status, by_type, next_meeting). These could be combined into a single query or parallelized with `asyncio.gather()`.

**Recommended fix**:
```python
raw, meetings = await asyncio.gather(
    self.repo.stats_for_project(project_id),
    self.repo.all_for_project(project_id),
)
```

> **Caveat**: This requires the two coroutines to use separate sessions or the DB driver to support concurrent queries on the same connection. With SQLAlchemy async and a single session, `asyncio.gather()` is NOT safe. This optimization requires session-per-query or separate connection handling.

### 4.2 FinanceService.get_dashboard() -- sequential aggregations

**File**: `backend/app/modules/finance/service.py:514-550`
**Severity**: Low (already uses SQL aggregation, just sequential)

```python
inv_agg = await self.invoices.aggregate_for_dashboard(project_id=project_id)
budget_agg = await self.budgets.aggregate_for_dashboard(project_id=project_id)
total_payments = await self.payments_repo.aggregate_total()
```

Same caveat as above -- parallelization requires separate sessions.

---

## 5. Positive Findings (Already Well-Optimized)

The codebase already follows several performance best practices:

1. **BOQ list uses `noload()`** for positions and markups, avoiding eager loading of potentially large child collections (`backend/app/modules/boq/repository.py:46`).

2. **Project list uses `noload()`** for wbs_nodes, milestones, children (`backend/app/modules/projects/repository.py:55-59`).

3. **Grand totals computed via SQL aggregation** -- `BOQRepository.grand_totals_for_boqs()` uses `SUM()` and `GROUP BY` instead of loading all positions.

4. **Finance dashboard uses SQL aggregation** -- `InvoiceRepository.aggregate_for_dashboard()` and `BudgetRepository.aggregate_for_dashboard()` compute KPIs in the database.

5. **All list endpoints are paginated** with `offset`/`limit` parameters and return `(items, total)` tuples.

6. **Composite indexes exist** where needed: `ix_task_project_status`, `ix_task_responsible_status`, `ix_invoice_project_direction`, `ix_invoice_project_status`, `ix_boq_activity_user_created`, `ix_boq_activity_target`.

7. **Export endpoints have safety limits** -- `limit(50000)` on invoice and budget exports.

---

## 6. Action Items

### Immediate (do now)
- [x] Add `index=True` to all 9 FK fields
- [ ] Generate Alembic migration: `alembic revision --autogenerate -m "add missing FK indexes"`
- [ ] Apply migration to dev/staging databases

### Short-term (next sprint)
- [ ] Refactor `PositionRepository.reorder()` to use bulk CASE UPDATE
- [ ] Refactor `TaskService.get_stats()` to use SQL aggregation
- [ ] Add `.limit()` safety nets to `BudgetRepository.list()` and `EVMSnapshotRepository.list()`

### Medium-term (backlog)
- [ ] Refactor `MeetingRepository.all_for_project()` to avoid loading all meetings for action item scanning
- [ ] Consider denormalizing open action item counts on the meeting model
- [ ] Profile `MeetingRepository.stats_for_project()` -- consolidate its 4 separate queries into 1-2
