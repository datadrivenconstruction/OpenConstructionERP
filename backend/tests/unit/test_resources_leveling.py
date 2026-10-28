"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit + module tests for portfolio resource leveling (TOP-30 #5).

Scope:
    * build_leveling_suggestions (pure): shift vs spread, no-overflow, zero/negative
      capacity guard, deterministic target selection.
    * ResourcesService.portfolio_leveling (DB-backed via transactional_session):
        - aggregation correctness across buckets,
        - overload detection at / over / under a known capacity,
        - capacity-unknown path (never flagged overloaded),
        - multi-project scoping (portfolio vs project_id filter),
        - empty / inverted window handling,
        - suggestion attachment + summary counts,
        - sort order (overloaded resources first).

DB tests use the canonical function-scoped ``transactional_session`` fixture so
each test runs inside a rolled-back transaction on the shared unit database.
IDOR / cross-tenant access for the project-scoped endpoint is covered at the HTTP
layer in ``tests/integration/test_resources_idor.py`` (the router calls the same
``verify_project_access`` guard used there); these module tests assert the
service-level scoping behaviour that the endpoint relies on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.resources.models import Assignment, Resource
from app.modules.resources.service import (
    ResourcesService,
    build_leveling_suggestions,
)
from app.modules.users.models import User
from tests._pg import transactional_session

# A fixed anchor so bucket maths is deterministic regardless of when tests run.
ANCHOR = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


# ── Pure: build_leveling_suggestions ────────────────────────────────────────


def _booking(alloc: int, *, project_name: str = "P") -> dict:
    return {
        "assignment_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "project_name": project_name,
        "allocation_percent": alloc,
    }


def test_suggestion_none_when_within_capacity() -> None:
    bookings = [_booking(60), _booking(30)]  # total 90 <= 100
    assert build_leveling_suggestions(0, 100, bookings) == []


def test_suggestion_none_when_exactly_at_capacity() -> None:
    bookings = [_booking(70), _booking(30)]  # total 100 == 100
    assert build_leveling_suggestions(0, 100, bookings) == []


def test_suggestion_capacity_zero_or_negative_returns_empty() -> None:
    # Caller must route the "capacity unknown" path elsewhere; a 0 capacity
    # must never produce a suggestion (we never fabricate a ceiling).
    bookings = [_booking(50)]
    assert build_leveling_suggestions(0, 0, bookings) == []
    assert build_leveling_suggestions(0, -5, bookings) == []


def test_suggestion_empty_bookings_returns_empty() -> None:
    assert build_leveling_suggestions(0, 100, []) == []


def test_suggestion_shift_smallest_clears_overflow() -> None:
    # total 130, capacity 100, overflow 30. Smallest booking is 30 which alone
    # clears it -> shift action.
    small = _booking(30, project_name="Small")
    big = _booking(100, project_name="Big")
    out = build_leveling_suggestions(2, 100, [big, small])
    assert len(out) == 1
    s = out[0]
    assert s["action"] == "shift"
    assert s["bucket_index"] == 2
    assert s["target_assignment_id"] == small["assignment_id"]
    assert s["target_project_name"] == "Small"
    assert s["overflow_percent"] == 30
    assert s["suggested_allocation_percent"] == 0


def test_suggestion_spread_largest_when_shift_insufficient() -> None:
    # total 150, capacity 100, overflow 50. Smallest booking is 60 (>= overflow
    # too) -> actually shift would clear it. Make the smallest smaller than the
    # overflow so spread path is taken.
    a = _booking(40, project_name="A")  # smallest, 40 < overflow 50 -> can't shift
    b = _booking(110, project_name="B")  # largest
    out = build_leveling_suggestions(1, 100, [a, b])  # total 150, overflow 50
    assert len(out) == 1
    s = out[0]
    assert s["action"] == "spread"
    assert s["target_assignment_id"] == b["assignment_id"]  # largest
    assert s["overflow_percent"] == 50
    assert s["suggested_allocation_percent"] == 60  # 110 - 50


def test_suggestion_spread_floors_at_zero() -> None:
    # Largest booking smaller than overflow -> suggested allocation floored at 0.
    a = _booking(10, project_name="A")
    b = _booking(20, project_name="B")
    # capacity 5, total 30, overflow 25. smallest 10 < 25 -> spread.
    out = build_leveling_suggestions(0, 5, [a, b])
    assert out[0]["action"] == "spread"
    assert out[0]["suggested_allocation_percent"] == 0


# ── DB-backed service: fixtures ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _mk_resource(
    s: AsyncSession,
    *,
    code: str,
    capacity_percent: int | None,
    home_project_id: uuid.UUID | None = None,
    resource_type: str = "person",
) -> Resource:
    r = Resource(
        id=uuid.uuid4(),
        code=code,
        name=f"Res {code}",
        resource_type=resource_type,
        capacity_percent=capacity_percent,
        home_project_id=home_project_id,
        status="active",
    )
    s.add(r)
    await s.flush()
    return r


async def _mk_owner(s: AsyncSession) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"owner-{uuid.uuid4().hex[:10]}@leveling.test",
        hashed_password="x",
        full_name="Leveling Owner",
        role="admin",
        is_active=True,
    )
    s.add(u)
    await s.flush()
    return u


async def _mk_project(s: AsyncSession, name: str) -> Project:
    # Project.owner_id is NOT NULL with a real FK to oe_users_user, so each
    # project needs an owner row. Created inline; the whole transaction is
    # rolled back at teardown.
    owner = await _mk_owner(s)
    p = Project(id=uuid.uuid4(), name=name, owner_id=owner.id)
    s.add(p)
    await s.flush()
    return p


async def _mk_assignment(
    s: AsyncSession,
    *,
    resource_id: uuid.UUID,
    project_id: uuid.UUID | None,
    day_start: int,
    day_end: int,
    alloc: int,
    status: str = "confirmed",
) -> Assignment:
    a = Assignment(
        id=uuid.uuid4(),
        resource_id=resource_id,
        project_id=project_id,
        start_at=ANCHOR + timedelta(days=day_start),
        end_at=ANCHOR + timedelta(days=day_end),
        allocation_percent=alloc,
        status=status,
    )
    s.add(a)
    await s.flush()
    return a


def _row_for(payload: dict, resource_id: uuid.UUID) -> dict | None:
    for r in payload["resources"]:
        if r["resource_id"] == resource_id:
            return r
    return None


# ── DB-backed service: aggregation + overload detection ─────────────────────


async def test_aggregation_sums_concurrent_bookings_in_bucket(session: AsyncSession) -> None:
    """Two overlapping bookings in week 0 sum into one cell total."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="AGG-1", capacity_percent=100)
    p1 = await _mk_project(session, "P1")
    p2 = await _mk_project(session, "P2")
    # Both inside week 0 (days 1-3 and 2-4).
    await _mk_assignment(session, resource_id=r.id, project_id=p1.id, day_start=1, day_end=3, alloc=60)
    await _mk_assignment(session, resource_id=r.id, project_id=p2.id, day_start=2, day_end=4, alloc=70)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=14), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 130  # 60 + 70
    assert cell0["over_allocated"] is True  # 130 > capacity 100
    assert cell0["cross_project"] is True  # two distinct projects
    assert cell0["capacity_unknown"] is False


async def test_overload_at_capacity_not_flagged(session: AsyncSession) -> None:
    """total == capacity is NOT over-allocated (boundary)."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="AT-CAP", capacity_percent=100)
    p = await _mk_project(session, "P")
    await _mk_assignment(session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=100)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    assert row["has_overload"] is False
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 100
    assert cell0["over_allocated"] is False
    assert row["suggestions"] == []


async def test_overload_over_capacity_flagged_with_suggestion(session: AsyncSession) -> None:
    """total > capacity flags over-allocation and attaches a suggestion."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="OVER", capacity_percent=100)
    p1 = await _mk_project(session, "P1")
    p2 = await _mk_project(session, "P2")
    await _mk_assignment(session, resource_id=r.id, project_id=p1.id, day_start=1, day_end=3, alloc=100)
    await _mk_assignment(session, resource_id=r.id, project_id=p2.id, day_start=1, day_end=3, alloc=40)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    assert row["has_overload"] is True
    assert row["overload_bucket_count"] == 1
    assert len(row["suggestions"]) == 1
    sug = row["suggestions"][0]
    # Smallest booking (40) >= overflow (40) -> shift.
    assert sug["action"] == "shift"
    assert sug["overflow_percent"] == 40
    assert payload["overloaded_resources"] == 1
    assert payload["total_suggestions"] == 1


async def test_under_capacity_no_overload(session: AsyncSession) -> None:
    """total < capacity is clean."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="UNDER", capacity_percent=200)
    p = await _mk_project(session, "P")
    await _mk_assignment(session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=120)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    assert row["has_overload"] is False
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 120
    assert cell0["over_allocated"] is False


async def test_capacity_unknown_never_overloaded(session: AsyncSession) -> None:
    """A resource with NULL capacity is surfaced as unknown, never overloaded,
    even when its bookings far exceed 100%."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="UNKNOWN", capacity_percent=None)
    p1 = await _mk_project(session, "P1")
    p2 = await _mk_project(session, "P2")
    await _mk_assignment(session, resource_id=r.id, project_id=p1.id, day_start=1, day_end=3, alloc=100)
    await _mk_assignment(session, resource_id=r.id, project_id=p2.id, day_start=1, day_end=3, alloc=100)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    assert row["capacity_unknown"] is True
    assert row["capacity_percent"] is None
    assert row["has_overload"] is False
    assert row["suggestions"] == []
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 200  # aggregation still correct
    assert cell0["over_allocated"] is False
    assert cell0["capacity_unknown"] is True
    assert payload["capacity_unknown_resources"] == 1
    assert payload["overloaded_resources"] == 0


# ── DB-backed service: state filtering ──────────────────────────────────────


async def test_cancelled_and_completed_excluded(session: AsyncSession) -> None:
    """Cancelled / completed bookings consume no capacity for leveling."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="STATES", capacity_percent=100)
    p = await _mk_project(session, "P")
    await _mk_assignment(
        session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=80, status="cancelled"
    )
    await _mk_assignment(
        session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=80, status="completed"
    )
    await _mk_assignment(
        session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=50, status="confirmed"
    )

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 50  # only the confirmed one
    assert cell0["over_allocated"] is False


async def test_proposed_and_in_progress_counted(session: AsyncSession) -> None:
    """Proposed + in_progress both consume capacity (forward-looking)."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="ACTIVE", capacity_percent=100)
    p = await _mk_project(session, "P")
    await _mk_assignment(
        session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=70, status="proposed"
    )
    await _mk_assignment(
        session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=60, status="in_progress"
    )

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 130
    assert cell0["over_allocated"] is True


# ── DB-backed service: multi-bucket spread ──────────────────────────────────


async def test_bookings_in_different_buckets_are_separate_cells(session: AsyncSession) -> None:
    """A booking in week 0 and another in week 1 produce two distinct cells."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="MULTIBUCKET", capacity_percent=100)
    p = await _mk_project(session, "P")
    await _mk_assignment(session, resource_id=r.id, project_id=p.id, day_start=1, day_end=3, alloc=120)
    await _mk_assignment(session, resource_id=r.id, project_id=p.id, day_start=8, day_end=10, alloc=50)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=21), bucket="week")
    row = _row_for(payload, r.id)
    assert row is not None
    by_idx = {c["bucket_index"]: c for c in row["cells"]}
    assert by_idx[0]["allocation_percent"] == 120
    assert by_idx[0]["over_allocated"] is True
    assert by_idx[1]["allocation_percent"] == 50
    assert by_idx[1]["over_allocated"] is False
    assert row["overload_bucket_count"] == 1


# ── DB-backed service: multi-project scoping ────────────────────────────────


async def test_portfolio_view_spans_all_projects(session: AsyncSession) -> None:
    """Unscoped portfolio view aggregates a resource's bookings across projects."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="SCOPE-ALL", capacity_percent=100)
    p1 = await _mk_project(session, "Alpha")
    p2 = await _mk_project(session, "Beta")
    await _mk_assignment(session, resource_id=r.id, project_id=p1.id, day_start=1, day_end=3, alloc=70)
    await _mk_assignment(session, resource_id=r.id, project_id=p2.id, day_start=1, day_end=3, alloc=60)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    assert payload["project_id"] is None
    row = _row_for(payload, r.id)
    assert row is not None
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 130  # both projects
    names = {b["project_name"] for b in cell0["bookings"]}
    assert names == {"Alpha", "Beta"}


async def test_project_scoped_view_filters_to_one_project(session: AsyncSession) -> None:
    """project_id filter shows only that project's bookings; the same resource's
    bookings on other projects are excluded, so no false overload."""
    svc = ResourcesService(session)
    r = await _mk_resource(session, code="SCOPE-ONE", capacity_percent=100)
    p1 = await _mk_project(session, "Alpha")
    p2 = await _mk_project(session, "Beta")
    await _mk_assignment(session, resource_id=r.id, project_id=p1.id, day_start=1, day_end=3, alloc=70)
    await _mk_assignment(session, resource_id=r.id, project_id=p2.id, day_start=1, day_end=3, alloc=60)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week", project_id=p1.id)
    assert payload["project_id"] == p1.id
    row = _row_for(payload, r.id)
    assert row is not None
    cell0 = next(c for c in row["cells"] if c["bucket_index"] == 0)
    assert cell0["allocation_percent"] == 70  # only Alpha
    assert cell0["over_allocated"] is False
    assert {b["project_name"] for b in cell0["bookings"]} == {"Alpha"}


# ── DB-backed service: window + sort + summary ──────────────────────────────


async def test_inverted_window_returns_empty(session: AsyncSession) -> None:
    svc = ResourcesService(session)
    payload = await svc.portfolio_leveling(ANCHOR + timedelta(days=7), ANCHOR, bucket="week")
    assert payload["resources"] == []
    assert payload["total_resources"] == 0
    assert payload["overloaded_resources"] == 0


async def test_no_assignments_returns_empty_grid(session: AsyncSession) -> None:
    svc = ResourcesService(session)
    await _mk_resource(session, code="IDLE", capacity_percent=100)
    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    # Resource has no bookings in window -> not returned (mirrors capacity view).
    assert payload["resources"] == []
    assert payload["total_resources"] == 0


async def test_overloaded_resources_sort_first(session: AsyncSession) -> None:
    """The grid lists overloaded resources before clean ones."""
    svc = ResourcesService(session)
    clean = await _mk_resource(session, code="A-CLEAN", capacity_percent=100)
    overloaded = await _mk_resource(session, code="Z-OVER", capacity_percent=100)
    p = await _mk_project(session, "P")
    await _mk_assignment(session, resource_id=clean.id, project_id=p.id, day_start=1, day_end=3, alloc=50)
    await _mk_assignment(session, resource_id=overloaded.id, project_id=p.id, day_start=1, day_end=3, alloc=150)

    payload = await svc.portfolio_leveling(ANCHOR, ANCHOR + timedelta(days=7), bucket="week")
    assert len(payload["resources"]) == 2
    # Overloaded resource (Z- code, would sort last alphabetically) must be first.
    assert payload["resources"][0]["resource_id"] == overloaded.id
    assert payload["resources"][0]["has_overload"] is True
    assert payload["resources"][1]["resource_id"] == clean.id


async def test_capacity_persisted_on_resource(session: AsyncSession) -> None:
    """The new capacity_percent column round-trips through the ORM."""
    r = await _mk_resource(session, code="CAP-RT", capacity_percent=250)
    fetched = await session.get(Resource, r.id)
    assert fetched is not None
    assert fetched.capacity_percent == 250
    # And NULL is honoured (not coerced to 0).
    r2 = await _mk_resource(session, code="CAP-NULL", capacity_percent=None)
    fetched2 = await session.get(Resource, r2.id)
    assert fetched2 is not None
    assert fetched2.capacity_percent is None


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
