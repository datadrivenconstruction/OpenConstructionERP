# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Portfolio capacity-planning heatmap (Wave 2, item #5).

``ResourcesService.portfolio_capacity`` aggregates resource assignments across
every project into a week/month-bucketed utilization heatmap, flagging
over-allocation (>100% in a bucket) and cross-project competition (more than one
project drawing on the same resource in a bucket) — the signal portfolio
leveling exists to resolve.

Runs against an isolated throwaway PostgreSQL (``tests._pg``). ``disable_fks``
lets us seed a Resource plus assignments with synthetic project ids without
seeding full Project rows; the aggregation reads the assignment/resource tables
directly, so FK enforcement is irrelevant to what is under test (project *names*
default to a placeholder, which the test does not assert on).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.resources.models import Assignment, Resource
from app.modules.resources.service import ResourcesService
from tests._pg import transactional_session


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


@pytest.mark.asyncio
async def test_portfolio_capacity_flags_cross_project_overallocation() -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ResourcesService(session)

        carpenter = Resource(
            id=uuid.uuid4(),
            code=f"CARP-{uuid.uuid4().hex[:6]}",
            name="Carpenter One",
            resource_type="person",
            home_project_id=None,  # floating / shared across the org
        )
        session.add(carpenter)
        await session.flush()

        project_a = uuid.uuid4()
        project_b = uuid.uuid4()
        # Two confirmed assignments overlap the week of Jul 13-20: 80% on
        # project A and 60% on project B = 140% from two distinct projects.
        session.add_all(
            [
                Assignment(
                    id=uuid.uuid4(),
                    resource_id=carpenter.id,
                    project_id=project_a,
                    start_at=_dt(2026, 7, 1),
                    end_at=_dt(2026, 7, 31),
                    allocation_percent=80,
                    status="confirmed",
                ),
                Assignment(
                    id=uuid.uuid4(),
                    resource_id=carpenter.id,
                    project_id=project_b,
                    start_at=_dt(2026, 7, 13),
                    end_at=_dt(2026, 7, 20),
                    allocation_percent=60,
                    status="confirmed",
                ),
            ]
        )
        await session.flush()

        result = await service.portfolio_capacity(_dt(2026, 7, 1), _dt(2026, 8, 1), bucket="week")

        assert result["total_resources"] == 1
        assert result["floating_resources"] == 1
        assert result["conflict_resources"] == 1
        assert len(result["resources"]) == 1

        row = result["resources"][0]
        assert row["resource_id"] == carpenter.id
        assert row["is_floating"] is True
        assert row["has_conflict"] is True
        assert row["peak_allocation_percent"] == 140

        # Find the bucket where both projects overlap.
        cross = [c for c in row["cells"] if c["cross_project"]]
        assert cross, "expected at least one cross-project bucket"
        peak_cell = max(cross, key=lambda c: c["allocation_percent"])
        assert peak_cell["allocation_percent"] == 140
        assert peak_cell["over_allocated"] is True
        assert {p["allocation_percent"] for p in peak_cell["projects"]} == {80, 60}
        assert {str(p["project_id"]) for p in peak_cell["projects"]} == {
            str(project_a),
            str(project_b),
        }


@pytest.mark.asyncio
async def test_portfolio_capacity_single_project_not_cross() -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ResourcesService(session)
        crane = Resource(
            id=uuid.uuid4(),
            code=f"CRANE-{uuid.uuid4().hex[:6]}",
            name="Tower Crane",
            resource_type="equipment",
            home_project_id=uuid.uuid4(),  # project-local
        )
        session.add(crane)
        await session.flush()
        session.add(
            Assignment(
                id=uuid.uuid4(),
                resource_id=crane.id,
                project_id=uuid.uuid4(),
                start_at=_dt(2026, 7, 1),
                end_at=_dt(2026, 7, 15),
                allocation_percent=50,
                status="confirmed",
            )
        )
        await session.flush()

        result = await service.portfolio_capacity(_dt(2026, 7, 1), _dt(2026, 8, 1), bucket="week")
        assert result["conflict_resources"] == 0
        assert result["floating_resources"] == 0
        row = result["resources"][0]
        assert row["has_conflict"] is False
        assert all(not c["cross_project"] for c in row["cells"])
        assert all(not c["over_allocated"] for c in row["cells"])


@pytest.mark.asyncio
async def test_portfolio_capacity_ignores_cancelled_and_completed() -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ResourcesService(session)
        res = Resource(
            id=uuid.uuid4(),
            code=f"LAB-{uuid.uuid4().hex[:6]}",
            name="Labourer",
            resource_type="person",
            home_project_id=None,
        )
        session.add(res)
        await session.flush()
        session.add_all(
            [
                Assignment(
                    id=uuid.uuid4(),
                    resource_id=res.id,
                    project_id=uuid.uuid4(),
                    start_at=_dt(2026, 7, 1),
                    end_at=_dt(2026, 7, 31),
                    allocation_percent=100,
                    status="cancelled",
                ),
                Assignment(
                    id=uuid.uuid4(),
                    resource_id=res.id,
                    project_id=uuid.uuid4(),
                    start_at=_dt(2026, 7, 1),
                    end_at=_dt(2026, 7, 31),
                    allocation_percent=100,
                    status="completed",
                ),
            ]
        )
        await session.flush()

        result = await service.portfolio_capacity(_dt(2026, 7, 1), _dt(2026, 8, 1), bucket="week")
        # Both assignments are inactive, so the resource has no live rows.
        assert result["total_resources"] == 0
        assert result["resources"] == []
