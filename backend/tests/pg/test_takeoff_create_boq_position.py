# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: create a bill position from a takeoff measurement, in one go.

A wall drawn as a line on the plan, with a height and its openings typed in,
becomes a new bill position carrying the NET wall area, placed in the chosen
section with the next ordinal, and linked back to the measurement so the
takeoff row shows it as linked. These tests drive the service method the
router calls (``create_boq_position_from_measurement``) against real
PostgreSQL, because the position goes through the BOQ service's own create
path (lock check, parent validation, audit) and the link is written in the
same transaction.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement
from app.modules.takeoff.schemas import CreateBoqPositionFromMeasurementRequest
from app.modules.takeoff.service import TakeoffService
from app.modules.users.models import User

# 12.5 m of partition, 2.8 m high, one door 0.9 x 2.1 and three windows 1.2 x 1.5:
# 35.00 - 1.89 - 5.40 = 27.71 m2.
WALL_META = {
    "wall_height": 2.8,
    "openings": [{"width": 0.9, "height": 2.1, "count": 1}, {"width": 1.2, "height": 1.5, "count": 3}],
}


async def _project(session, name: str = "Partition takeoff") -> Project:
    owner = User(email=f"wall-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name=name, owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def _bill_with_section(session, project: Project, *, locked: bool = False) -> tuple[BOQ, Position]:
    boq = BOQ(project_id=project.id, name="Drywall bill", is_locked=locked)
    session.add(boq)
    await session.flush()
    section = Position(
        boq_id=boq.id,
        ordinal="01",
        description="Drywall",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=1,
    )
    session.add(section)
    await session.flush()
    return boq, section


async def _wall(session, project: Project, *, metadata: dict | None = None, **over) -> TakeoffMeasurement:
    fields = {
        "project_id": project.id,
        "document_id": f"doc-{uuid.uuid4().hex[:8]}",
        "page": 2,
        "type": "distance",
        "group_name": "Partitions",
        "annotation": "Plasterboard partition, axis B",
        "points": [{"x": 0.0, "y": 0.0}, {"x": 1250.0, "y": 0.0}],
        "measurement_value": 12.5,
        "measurement_unit": "m",
        "scale_pixels_per_unit": 100.0,
        "metadata_": dict(WALL_META if metadata is None else metadata),
        "created_by": "tester",
    }
    fields.update(over)
    row = TakeoffMeasurement(**fields)
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_creates_the_net_wall_area_in_the_section_and_links_it(pg_session) -> None:
    project = await _project(pg_session)
    boq, section = await _bill_with_section(pg_session, project)
    wall = await _wall(pg_session, project)

    position, quantity, unit = await TakeoffService(pg_session).create_boq_position_from_measurement(
        wall,
        CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id),
    )

    assert quantity == pytest.approx(27.71)
    assert unit == "m2"
    stored = await pg_session.get(Position, position.id)
    assert Decimal(str(stored.quantity)) == Decimal("27.71")
    assert stored.unit == "m2"
    assert stored.parent_id == section.id
    assert stored.ordinal == "01.10", "the BOQ editor's gap-of-10 scheme under the section"
    assert stored.description == "Plasterboard partition, axis B"
    assert stored.source == "takeoff"
    assert stored.metadata_["pdf_measurement_id"] == str(wall.id)

    # Linked like a normal link, and the badge keys survive a reload.
    await pg_session.refresh(wall)
    assert wall.linked_boq_position_id == str(position.id)
    assert wall.metadata_["linked_position_ordinal"] == "01.10"
    assert wall.metadata_["linked_boq_id"] == str(boq.id)
    # The quantity inputs are untouched by the link.
    assert wall.metadata_["wall_height"] == 2.8
    assert wall.measurement_value == pytest.approx(12.5), "the stored row stays the drawn length"


@pytest.mark.asyncio
async def test_the_bill_badge_links_back_by_the_drawing_name(pg_session) -> None:
    """The bill grid builds ``/takeoff?name=<pdf_document_id>``, so it needs the file name."""
    project = await _project(pg_session)
    boq, section = await _bill_with_section(pg_session, project)
    doc = TakeoffDocument(
        filename="A-201 partitions.pdf",
        pages=3,
        size_bytes=2048,
        project_id=project.id,
        owner_id=project.owner_id,
    )
    pg_session.add(doc)
    await pg_session.flush()
    wall = await _wall(pg_session, project, document_id=str(doc.id))

    position, _, _ = await TakeoffService(pg_session).create_boq_position_from_measurement(
        wall, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id)
    )

    assert position.metadata_["pdf_document_id"] == "A-201 partitions.pdf"
    assert position.metadata_["pdf_takeoff_document_id"] == str(doc.id)
    assert position.metadata_["pdf_page"] == 2


@pytest.mark.asyncio
async def test_an_unaccepted_suggestion_is_not_put_into_a_bill(pg_session) -> None:
    """A detector proposal is not a quantity until a person accepts it."""
    project = await _project(pg_session)
    boq, section = await _bill_with_section(pg_session, project)
    for state in ("proposed", "rejected"):
        guess = await _wall(pg_session, project, review_status=state)
        with pytest.raises(HTTPException) as exc:
            await TakeoffService(pg_session).create_boq_position_from_measurement(
                guess, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id)
            )
        assert exc.value.status_code == 422, state
        await pg_session.refresh(guess)
        assert guess.linked_boq_position_id is None, state

    from sqlalchemy import func, select

    count = (await pg_session.execute(select(func.count()).where(Position.boq_id == boq.id))).scalar_one()
    assert count == 1, "only the section, no line from a suggestion"


@pytest.mark.asyncio
async def test_the_next_position_in_the_section_numbers_after_it(pg_session) -> None:
    project = await _project(pg_session)
    boq, section = await _bill_with_section(pg_session, project)
    service = TakeoffService(pg_session)
    first = await _wall(pg_session, project)
    second = await _wall(pg_session, project, metadata={"wall_height": 3.0}, annotation="Shaft wall")

    p1, _, _ = await service.create_boq_position_from_measurement(
        first, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id)
    )
    p2, q2, _ = await service.create_boq_position_from_measurement(
        second,
        CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id, description="Shaft wall, EI 90"),
    )

    assert (p1.ordinal, p2.ordinal) == ("01.10", "01.20")
    assert q2 == pytest.approx(37.5)
    assert p2.description == "Shaft wall, EI 90", "the estimator's edited text wins over the annotation"


@pytest.mark.asyncio
async def test_top_level_and_wastage_and_multiplier(pg_session) -> None:
    project = await _project(pg_session)
    boq, _section = await _bill_with_section(pg_session, project)
    wall = await _wall(pg_session, project, metadata={**WALL_META, "wastage_pct": 10, "multiplier": 3})

    position, quantity, _ = await TakeoffService(pg_session).create_boq_position_from_measurement(
        wall, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id)
    )

    assert quantity == pytest.approx(91.443)
    assert position.parent_id is None
    assert position.ordinal == "0010", "top level takes the editor's four-digit gap-of-10 ordinal"


@pytest.mark.asyncio
async def test_an_imperial_bill_gets_square_feet(pg_session) -> None:
    project = await _project(pg_session)
    boq, section = await _bill_with_section(pg_session, project)
    wall = await _wall(pg_session, project, metadata={"wall_height": 2.5}, measurement_value=10.0)

    position, quantity, unit = await TakeoffService(pg_session).create_boq_position_from_measurement(
        wall, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id, unit="ft2")
    )

    # 25 m2 = 269.0975 ft2
    assert unit == "ft2"
    assert quantity == pytest.approx(269.0975, abs=1e-3)
    assert position.unit == "ft2"


@pytest.mark.asyncio
async def test_a_bill_in_another_project_is_refused_and_nothing_is_created(pg_session) -> None:
    project = await _project(pg_session)
    other = await _project(pg_session, name="Someone else's project")
    foreign_boq, foreign_section = await _bill_with_section(pg_session, other)
    wall = await _wall(pg_session, project)

    with pytest.raises(HTTPException) as exc:
        await TakeoffService(pg_session).create_boq_position_from_measurement(
            wall, CreateBoqPositionFromMeasurementRequest(boq_id=foreign_boq.id, parent_id=foreign_section.id)
        )

    assert exc.value.status_code == 404
    from sqlalchemy import func, select

    count = (await pg_session.execute(select(func.count()).where(Position.boq_id == foreign_boq.id))).scalar_one()
    assert count == 1, "only the section, no new line"
    await pg_session.refresh(wall)
    assert wall.linked_boq_position_id is None


@pytest.mark.asyncio
async def test_a_section_from_another_bill_is_refused(pg_session) -> None:
    project = await _project(pg_session)
    boq, _ = await _bill_with_section(pg_session, project)
    _other_boq, other_section = await _bill_with_section(pg_session, project)
    wall = await _wall(pg_session, project)

    with pytest.raises(HTTPException) as exc:
        await TakeoffService(pg_session).create_boq_position_from_measurement(
            wall, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=other_section.id)
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_opening_deduction_is_not_a_position(pg_session) -> None:
    project = await _project(pg_session)
    boq, section = await _bill_with_section(pg_session, project)
    hole = await _wall(
        pg_session,
        project,
        type="area",
        measurement_value=2.0,
        measurement_unit="m2",
        is_deduction=True,
        metadata={},
        points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}],
    )

    with pytest.raises(HTTPException) as exc:
        await TakeoffService(pg_session).create_boq_position_from_measurement(
            hole, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id)
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_locked_bill_takes_no_new_line(pg_session) -> None:
    project = await _project(pg_session)
    boq, section = await _bill_with_section(pg_session, project, locked=True)
    wall = await _wall(pg_session, project)

    with pytest.raises(HTTPException) as exc:
        await TakeoffService(pg_session).create_boq_position_from_measurement(
            wall, CreateBoqPositionFromMeasurementRequest(boq_id=boq.id, parent_id=section.id)
        )
    assert exc.value.status_code == 409
    await pg_session.refresh(wall)
    assert wall.linked_boq_position_id is None
