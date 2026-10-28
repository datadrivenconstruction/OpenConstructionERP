"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: an unreviewed detector proposal is never counted as a quantity.

Proposals became durable rows in the takeoff table, which means every read
path that used to see only hand-drawn work now sees suggestions too. That is
fine on the canvas, where they render translucent and dashed, and wrong
everywhere a number is totalled, exported or priced: nobody has agreed to a
proposal yet, and a rejected row is a record of a decision, not a measurement.

These tests pin the boundary on the paths where the number reaches a person:
the project summary, the CSV export, the AI estimator's element extraction and
the project dashboard tile. The estimator is the sharpest of the four - it
turns each row into a priced element, so a leak there invents money.

``review_status`` defaults to ``'confirmed'`` in the column, so the guard is an
allowlist and pre-existing rows are unaffected. Real PostgreSQL because the
predicate rides along with the aggregation SQL.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.ai_estimator.extractors import extract_takeoff
from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffMeasurement
from app.modules.takeoff.repository import MeasurementRepository
from app.modules.takeoff.service import TakeoffService
from app.modules.users.models import User

# A 10x10 square at 1 pixel per unit: area 100, unambiguous by hand.
SQUARE = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}, {"x": 0.0, "y": 10.0}]


async def _seed_project(session) -> Project:
    """Insert an owner and one project."""
    owner = User(email=f"quantities-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Proposal isolation", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


def _measurement(project_id, *, review_status: str, annotation: str) -> TakeoffMeasurement:
    """One 100 m2 area row in the given review state."""
    return TakeoffMeasurement(
        project_id=project_id,
        document_id=f"doc-{uuid.uuid4().hex[:8]}",
        page=1,
        type="area",
        group_name="Slabs",
        annotation=annotation,
        points=SQUARE,
        measurement_value=100.0,
        measurement_unit="m2",
        review_status=review_status,
        created_by="tester",
    )


async def _seed_one_of_each(session) -> Project:
    """A project holding one confirmed, one proposed and one rejected row."""
    project = await _seed_project(session)
    session.add_all(
        [
            _measurement(project.id, review_status="confirmed", annotation="Agreed slab"),
            _measurement(project.id, review_status="proposed", annotation="Detector guess"),
            _measurement(project.id, review_status="rejected", annotation="Turned down"),
        ]
    )
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_summary_counts_only_confirmed_rows(pg_session) -> None:
    """The project total is what a human agreed to, not what a detector offered."""
    project = await _seed_one_of_each(pg_session)

    summary = await TakeoffService(pg_session).get_measurement_summary(project.id)

    assert summary["total_measurements"] == 1, "one confirmed row, not three"
    assert summary["by_group"] == {"Slabs": 1}
    assert summary["by_page"] == {1: 1}


@pytest.mark.asyncio
async def test_export_omits_unreviewed_and_rejected_rows(pg_session) -> None:
    """A spreadsheet leaving the platform carries agreed quantities only."""
    project = await _seed_one_of_each(pg_session)

    rows = await TakeoffService(pg_session).export_measurements(project.id, fmt="csv")

    assert [r["annotation"] for r in rows] == ["Agreed slab"]


@pytest.mark.asyncio
async def test_estimator_does_not_price_an_unreviewed_proposal(pg_session) -> None:
    """The highest-stakes path: a proposal must never become a priced element."""
    project = await _seed_one_of_each(pg_session)

    result = await extract_takeoff(pg_session, project.id)

    descriptions = [e["description"] for e in result.envelopes]
    assert descriptions == ["Agreed slab"]
    assert result.scanned == 1, "the skipped rows are not even inspected"


@pytest.mark.asyncio
async def test_dashboard_tile_counts_only_confirmed_rows(pg_session) -> None:
    """Exercises the method the dashboard calls, not a copy of its SQL."""
    project = await _seed_one_of_each(pg_session)

    count = await MeasurementRepository(pg_session).count_confirmed_for_project(project.id)

    assert count == 1


@pytest.mark.asyncio
async def test_confirming_a_proposal_brings_it_into_the_totals(pg_session) -> None:
    """The guard hides unreviewed work, it does not lose it."""
    project = await _seed_project(pg_session)
    proposal = _measurement(project.id, review_status="proposed", annotation="Detector guess")
    pg_session.add(proposal)
    await pg_session.flush()
    # Hoisted: ``update_fields`` expires every cached instance, so reading an
    # attribute off ``proposal`` afterwards would trigger a lazy refresh.
    project_id, proposal_id = project.id, proposal.id
    svc = TakeoffService(pg_session)
    assert (await svc.get_measurement_summary(project_id))["total_measurements"] == 0

    await svc.measurement_repo.update_fields(proposal_id, review_status="confirmed")

    summary = await svc.get_measurement_summary(project_id)
    assert summary["total_measurements"] == 1, "accepting it makes it count"


@pytest.mark.asyncio
async def test_a_caller_can_still_ask_for_everything(pg_session) -> None:
    """The review queue and usage telemetry need the unfiltered view."""
    project = await _seed_one_of_each(pg_session)

    rows = await TakeoffService(pg_session).measurement_repo.all_for_project(project.id, confirmed_only=False)

    assert len(rows) == 3
