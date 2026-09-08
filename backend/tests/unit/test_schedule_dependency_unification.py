"""Unit tests for the unified schedule dependency graph (Lane B).

Scope:
    Pins the single-source-of-truth contract introduced for schedule
    dependency edges. ``ScheduleRelationship`` (the relational table) is the
    canonical store; ``Activity.dependencies`` (JSON) is a derived mirror.

    Covered behaviours:
        * Creating / updating an activity with a ``dependencies`` payload
          projects the edges into the canonical relationship store.
        * Deleting an edge from the canonical store removes it from CPM (no
          lingering JSON copy keeps blocking).
        * Completion is rejected (HTTP 409) while a predecessor is still open
          and allowed once the predecessor completes.
        * Round-trip JSON <-> table stays consistent (the derived mirror always
          equals the canonical rows).
        * ``reconcile_dependency_sources`` promotes orphan JSON edges into the
          table and resyncs the mirror, idempotently.

    Repositories, the relationship repo, and the event bus are stubbed; no
    database is booted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.schedule.schemas import (
    ActivityCreate,
    ActivityDependency,
    ActivityUpdate,
    ScheduleCreate,
)
from app.modules.schedule.service import ScheduleService

PROJECT_ID = uuid.uuid4()


# ── Stubs ──────────────────────────────────────────────────────────────────


class _StubScheduleRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, schedule: Any) -> Any:
        if getattr(schedule, "id", None) is None:
            schedule.id = uuid.uuid4()
        now = datetime.now(UTC)
        schedule.created_at = now
        schedule.updated_at = now
        self.rows[schedule.id] = schedule
        return schedule

    async def get_by_id(self, schedule_id: uuid.UUID) -> Any:
        return self.rows.get(schedule_id)

    async def update_fields(self, schedule_id: uuid.UUID, **kwargs: Any) -> None:
        s = self.rows.get(schedule_id)
        if s:
            for k, v in kwargs.items():
                setattr(s, k, v)


class _StubActivityRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, activity: Any) -> Any:
        if getattr(activity, "id", None) is None:
            activity.id = uuid.uuid4()
        now = datetime.now(UTC)
        activity.created_at = now
        activity.updated_at = now
        self.rows[activity.id] = activity
        return activity

    async def get_by_id(self, activity_id: uuid.UUID) -> Any:
        return self.rows.get(activity_id)

    async def list_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.schedule_id == schedule_id]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, activity_id: uuid.UUID, **kwargs: Any) -> None:
        a = self.rows.get(activity_id)
        if a:
            for k, v in kwargs.items():
                setattr(a, k, v)
            a.updated_at = datetime.now(UTC)

    async def bulk_update_fields(self, updates: list[dict[str, Any]]) -> None:
        for entry in updates:
            data = dict(entry)
            aid = data.pop("id")
            a = self.rows.get(aid)
            if a:
                for k, v in data.items():
                    setattr(a, k, v)
                a.updated_at = datetime.now(UTC)

    async def delete(self, activity_id: uuid.UUID) -> None:
        self.rows.pop(activity_id, None)

    async def get_max_sort_order(self, schedule_id: uuid.UUID) -> int:
        rows = [r for r in self.rows.values() if r.schedule_id == schedule_id]
        return max((r.sort_order for r in rows), default=0)

    async def get_max_activity_code_seq(self, schedule_id: uuid.UUID) -> int:
        return len([r for r in self.rows.values() if r.schedule_id == schedule_id])


class _StubRelationshipRepo:
    """In-memory canonical edge store mirroring RelationshipRepository."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_schedule(self, schedule_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.schedule_id == schedule_id]

    async def list_predecessors(self, successor_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.successor_id == successor_id]

    async def create(self, relationship: Any) -> Any:
        if getattr(relationship, "id", None) is None:
            relationship.id = uuid.uuid4()
        now = datetime.now(UTC)
        relationship.created_at = now
        relationship.updated_at = now
        self.rows[relationship.id] = relationship
        return relationship

    async def delete_by_id(self, relationship_id: uuid.UUID) -> None:
        self.rows.pop(relationship_id, None)

    async def delete_edges(self, successor_id: uuid.UUID, predecessor_ids: list[uuid.UUID]) -> None:
        if not predecessor_ids:
            return
        preds = set(predecessor_ids)
        doomed = [rid for rid, r in self.rows.items() if r.successor_id == successor_id and r.predecessor_id in preds]
        for rid in doomed:
            self.rows.pop(rid, None)

    async def update_edge(self, relationship_id: uuid.UUID, *, relationship_type: str, lag_days: int) -> None:
        r = self.rows.get(relationship_id)
        if r:
            r.relationship_type = relationship_type
            r.lag_days = lag_days


class _StubResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _StubResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)


class _StubSession:
    """Resolves the single ``select(Activity).where(id.in_(...))`` issued by the
    completion guard against the in-memory activity repo, by predecessor ids
    captured on the service.
    """

    def __init__(self, activity_repo: _StubActivityRepo) -> None:
        self._activity_repo = activity_repo
        self._pred_ids: set[uuid.UUID] = set()

    async def execute(self, _stmt: Any) -> _StubResult:
        matched = [a for aid, a in self._activity_repo.rows.items() if aid in self._pred_ids]
        return _StubResult(matched)

    async def get(self, *_args: Any, **_kwargs: Any) -> None:
        """The project lookup behind the regional working week; no project here
        means the DEFAULT Monday-to-Friday week, which these tests do not measure."""


def _make_service() -> ScheduleService:
    service = ScheduleService.__new__(ScheduleService)
    service.schedule_repo = _StubScheduleRepo()
    service.activity_repo = _StubActivityRepo()
    service.relationship_repo = _StubRelationshipRepo()
    service.session = _StubSession(service.activity_repo)
    return service


async def _create_schedule(svc: ScheduleService) -> Any:
    return await svc.create_schedule(
        ScheduleCreate(
            project_id=PROJECT_ID,
            name="Master Schedule",
            start_date="2026-05-01",
            end_date="2027-03-31",
        )
    )


async def _create_activity(svc: ScheduleService, schedule_id: uuid.UUID, **overrides: Any) -> Any:
    defaults = {
        "schedule_id": schedule_id,
        "name": "Activity",
        "start_date": "2026-05-01",
        "end_date": "2026-06-01",
        "activity_type": "task",
    }
    defaults.update(overrides)
    return await svc.create_activity(ActivityCreate(**defaults))


# ── Projection: activity payload -> canonical table ────────────────────────


@pytest.mark.asyncio
async def test_create_activity_with_deps_writes_canonical_table() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="Predecessor")

    succ = await _create_activity(
        svc,
        sched.id,
        name="Successor",
        dependencies=[ActivityDependency(activity_id=pred.id, type="FS", lag_days=2)],
    )

    rows = await svc.relationship_repo.list_predecessors(succ.id)
    assert len(rows) == 1
    assert rows[0].predecessor_id == pred.id
    assert rows[0].successor_id == succ.id
    assert rows[0].relationship_type == "FS"
    assert rows[0].lag_days == 2

    # Derived JSON mirror equals the canonical row.
    assert succ.dependencies == [{"activity_id": str(pred.id), "type": "FS", "lag_days": 2}]


@pytest.mark.asyncio
async def test_update_activity_deps_projects_and_replaces_edges() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    p1 = await _create_activity(svc, sched.id, name="P1")
    p2 = await _create_activity(svc, sched.id, name="P2")
    succ = await _create_activity(svc, sched.id, name="S")

    # First set: depend on P1.
    await svc.update_activity(
        succ.id,
        ActivityUpdate(dependencies=[ActivityDependency(activity_id=p1.id, type="FS", lag_days=0)]),
    )
    rows = await svc.relationship_repo.list_predecessors(succ.id)
    assert {r.predecessor_id for r in rows} == {p1.id}

    # Replace with P2 only — P1 edge must be removed from the canonical store.
    updated = await svc.update_activity(
        succ.id,
        ActivityUpdate(dependencies=[ActivityDependency(activity_id=p2.id, type="SS", lag_days=1)]),
    )
    rows = await svc.relationship_repo.list_predecessors(succ.id)
    assert {r.predecessor_id for r in rows} == {p2.id}
    assert rows[0].relationship_type == "SS"
    assert rows[0].lag_days == 1
    assert updated.dependencies == [{"activity_id": str(p2.id), "type": "SS", "lag_days": 1}]


@pytest.mark.asyncio
async def test_update_activity_empty_deps_clears_edges() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="P")
    succ = await _create_activity(
        svc,
        sched.id,
        name="S",
        dependencies=[ActivityDependency(activity_id=pred.id)],
    )
    assert len(await svc.relationship_repo.list_predecessors(succ.id)) == 1

    cleared = await svc.update_activity(succ.id, ActivityUpdate(dependencies=[]))
    assert await svc.relationship_repo.list_predecessors(succ.id) == []
    assert cleared.dependencies == []


# ── Deleted edge disappears from CPM ───────────────────────────────────────


@pytest.mark.asyncio
async def test_cpm_ignores_stale_json_when_canonical_has_other_edges() -> None:
    """When the canonical store holds at least one edge it is the SOLE
    authority: a stale JSON-only edge on another activity is ignored, so a
    deleted relationship truly disappears from CPM."""
    svc = _make_service()
    sched = await _create_schedule(svc)
    a = await _create_activity(svc, sched.id, name="A", start_date="2026-05-01", end_date="2026-05-06")
    b = await _create_activity(svc, sched.id, name="B", start_date="2026-05-01", end_date="2026-05-06")
    c = await _create_activity(svc, sched.id, name="C", start_date="2026-05-01", end_date="2026-05-06")

    # Canonical edge A -> B (kept).
    await svc.update_activity(b.id, ActivityUpdate(dependencies=[ActivityDependency(activity_id=a.id, type="FS")]))
    # Stale JSON-only edge A -> C: write JSON directly, leave canonical empty
    # for C (simulating a relationship row that was deleted but whose JSON copy
    # lingered).
    c_row = svc.activity_repo.rows[c.id]
    c_row.dependencies = [{"activity_id": str(a.id), "type": "FS", "lag_days": 0}]

    cpm = await svc.calculate_critical_path(sched.id)

    # B should have early_start after A finishes (edge honoured); C should start
    # at 0 because its only edge is the ignored stale JSON copy.
    by_id = {str(r.activity_id): r for r in cpm.all_activities}
    assert by_id[str(b.id)].early_start > 0, "Canonical A->B edge must shift B"
    assert by_id[str(c.id)].early_start == 0, "Stale JSON A->C edge must be ignored"


# ── Completion guard ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_blocked_when_predecessor_open_update_progress() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="Predecessor")
    succ = await _create_activity(
        svc, sched.id, name="Successor", dependencies=[ActivityDependency(activity_id=pred.id)]
    )

    # Feed the completion guard the predecessor ids via the stub session.
    rows = await svc.relationship_repo.list_predecessors(succ.id)
    svc.session._pred_ids = {r.predecessor_id for r in rows}  # type: ignore[attr-defined]

    with pytest.raises(HTTPException) as exc:
        await svc.update_progress(succ.id, 100.0)
    assert exc.value.status_code == 409
    assert "Predecessor" in exc.value.detail


@pytest.mark.asyncio
async def test_complete_allowed_once_predecessor_completed_update_progress() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="Predecessor")
    succ = await _create_activity(
        svc, sched.id, name="Successor", dependencies=[ActivityDependency(activity_id=pred.id)]
    )

    # Complete the predecessor (it has no predecessors of its own).
    svc.session._pred_ids = set()  # type: ignore[attr-defined]
    await svc.update_progress(pred.id, 100.0)
    assert svc.activity_repo.rows[pred.id].status == "completed"

    # Now the successor may complete.
    rows = await svc.relationship_repo.list_predecessors(succ.id)
    svc.session._pred_ids = {r.predecessor_id for r in rows}  # type: ignore[attr-defined]
    done = await svc.update_progress(succ.id, 100.0)
    assert done.status == "completed"


@pytest.mark.asyncio
async def test_complete_blocked_via_update_activity_status() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="Predecessor")
    succ = await _create_activity(
        svc, sched.id, name="Successor", dependencies=[ActivityDependency(activity_id=pred.id)]
    )

    rows = await svc.relationship_repo.list_predecessors(succ.id)
    svc.session._pred_ids = {r.predecessor_id for r in rows}  # type: ignore[attr-defined]

    with pytest.raises(HTTPException) as exc:
        await svc.update_activity(succ.id, ActivityUpdate(status="completed"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_complete_no_predecessors_allowed() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    solo = await _create_activity(svc, sched.id, name="Solo")

    svc.session._pred_ids = set()  # type: ignore[attr-defined]
    done = await svc.update_progress(solo.id, 100.0)
    assert done.status == "completed"


# ── Round-trip JSON <-> table consistency ──────────────────────────────────


@pytest.mark.asyncio
async def test_round_trip_json_table_stays_consistent() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    p1 = await _create_activity(svc, sched.id, name="P1")
    p2 = await _create_activity(svc, sched.id, name="P2")
    succ = await _create_activity(
        svc,
        sched.id,
        name="S",
        dependencies=[
            ActivityDependency(activity_id=p1.id, type="FS", lag_days=0),
            ActivityDependency(activity_id=p2.id, type="SS", lag_days=3),
        ],
    )

    canonical = {
        (r.predecessor_id, r.relationship_type, r.lag_days)
        for r in await svc.relationship_repo.list_predecessors(succ.id)
    }
    mirror = {
        (uuid.UUID(d["activity_id"]), d["type"], d["lag_days"]) for d in svc.activity_repo.rows[succ.id].dependencies
    }
    assert canonical == mirror


# ── Reconciliation (backfill) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_promotes_orphan_json_edges() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="P")
    succ = await _create_activity(svc, sched.id, name="S")

    # Simulate legacy data: JSON edge with no canonical row.
    svc.activity_repo.rows[succ.id].dependencies = [{"activity_id": str(pred.id), "type": "FF", "lag_days": 5}]

    stats = await svc.reconcile_dependency_sources(sched.id)
    assert stats["edges_created"] == 1

    rows = await svc.relationship_repo.list_predecessors(succ.id)
    assert len(rows) == 1
    assert rows[0].relationship_type == "FF"
    assert rows[0].lag_days == 5
    # Mirror rebuilt from canonical.
    assert svc.activity_repo.rows[succ.id].dependencies == [{"activity_id": str(pred.id), "type": "FF", "lag_days": 5}]


@pytest.mark.asyncio
async def test_reconcile_drops_dangling_json_edges() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    succ = await _create_activity(svc, sched.id, name="S")

    # JSON edge pointing at a non-existent predecessor — must be dropped.
    ghost = uuid.uuid4()
    svc.activity_repo.rows[succ.id].dependencies = [{"activity_id": str(ghost), "type": "FS", "lag_days": 0}]

    stats = await svc.reconcile_dependency_sources(sched.id)
    assert stats["edges_created"] == 0
    assert await svc.relationship_repo.list_predecessors(succ.id) == []
    assert svc.activity_repo.rows[succ.id].dependencies == []


@pytest.mark.asyncio
async def test_delete_activity_prunes_successor_json_mirror() -> None:
    """Deleting a predecessor must strip it from every successor's JSON
    dependency mirror so ``get_gantt_data`` never returns an edge pointing at
    a node that no longer exists (the canonical row is gone via FK CASCADE; the
    derived mirror must follow)."""
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="Predecessor")
    succ = await _create_activity(
        svc,
        sched.id,
        name="Successor",
        dependencies=[ActivityDependency(activity_id=pred.id, type="FS", lag_days=2)],
    )
    # Sanity: the mirror references the predecessor.
    assert any(d["activity_id"] == str(pred.id) for d in svc.activity_repo.rows[succ.id].dependencies)

    await svc.delete_activity(pred.id)

    # Successor survives but no longer lists the deleted predecessor.
    assert succ.id in svc.activity_repo.rows
    assert svc.activity_repo.rows[succ.id].dependencies == []


@pytest.mark.asyncio
async def test_delete_activity_keeps_unrelated_successor_edges() -> None:
    """Pruning on delete must only drop edges to the deleted activity, leaving
    a successor's other predecessor edges intact."""
    svc = _make_service()
    sched = await _create_schedule(svc)
    p1 = await _create_activity(svc, sched.id, name="P1")
    p2 = await _create_activity(svc, sched.id, name="P2")
    succ = await _create_activity(
        svc,
        sched.id,
        name="S",
        dependencies=[
            ActivityDependency(activity_id=p1.id, type="FS", lag_days=0),
            ActivityDependency(activity_id=p2.id, type="SS", lag_days=1),
        ],
    )

    await svc.delete_activity(p1.id)

    remaining = svc.activity_repo.rows[succ.id].dependencies
    assert [d["activity_id"] for d in remaining] == [str(p2.id)]


@pytest.mark.asyncio
async def test_reconcile_is_idempotent() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    pred = await _create_activity(svc, sched.id, name="P")
    succ = await _create_activity(svc, sched.id, name="S", dependencies=[ActivityDependency(activity_id=pred.id)])

    # Already projected at create time; reconcile must be a no-op.
    first = await svc.reconcile_dependency_sources(sched.id)
    second = await svc.reconcile_dependency_sources(sched.id)
    assert first == {"edges_created": 0, "activities_resynced": 0}
    assert second == {"edges_created": 0, "activities_resynced": 0}
    assert len(await svc.relationship_repo.list_predecessors(succ.id)) == 1


# ── Edge-payload helper ────────────────────────────────────────────────────


def test_edge_payload_dedups_last_wins() -> None:
    pred = uuid.uuid4()
    payload = [
        {"activity_id": str(pred), "type": "FS", "lag_days": 0},
        {"activity_id": str(pred), "type": "SS", "lag_days": 4},
    ]
    edges = ScheduleService._edge_payload_from_json(payload)
    assert edges == {pred: ("SS", 4)}


def test_edge_payload_skips_invalid_uuids() -> None:
    edges = ScheduleService._edge_payload_from_json([{"activity_id": "not-a-uuid", "type": "FS", "lag_days": 0}])
    assert edges == {}
