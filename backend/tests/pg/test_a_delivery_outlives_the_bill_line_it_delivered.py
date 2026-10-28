"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A delivery record survives the deletion of the bill position it delivered.

This is the site-logistics module's orphan discipline, and it is enforced by the
database rather than by a sweep: ``oe_site_logistics_delivery_line`` holds a
real foreign key to ``oe_boq_position`` declared ``ON DELETE SET NULL``. The
schedule module, whose links live in a JSON array, needs
``BOQService._scrub_activity_position_refs`` to walk the activities and remove
dead ids by hand; a foreign key is maintained inside the delete transaction.

An untested ``SET NULL`` is an assumption, not a discipline - so this exercises
the real DDL on real PostgreSQL:

* the delivery and its line survive a deleted position,
* the line keeps the snapshot that says what arrived,
* the line no longer counts as covering anything, and is reported as detached.

PG lane only (``OE_TEST_DB=pg``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


async def _seed_bill(pg_session) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a project with one priced position; return ``(project_id, position_id)``."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"logistics-{uuid.uuid4().hex[:8]}@site.example",
        hashed_password="x",
        full_name="Site Manager",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()

    project = Project(id=uuid.uuid4(), name="Delivery orphan discipline", owner_id=owner.id, currency="EUR")
    pg_session.add(project)
    await pg_session.flush()

    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Main bill", status="draft")
    pg_session.add(boq)
    await pg_session.flush()

    position = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="03.10.020",
        description="C30/37 in-situ concrete to slabs",
        unit="m3",
        quantity="450",
        unit_rate="118.40",
        total="53280",
    )
    pg_session.add(position)
    await pg_session.flush()
    return project.id, position.id


async def _book_delivery(pg_session, project_id: uuid.UUID, position_id: uuid.UUID | None) -> uuid.UUID:
    """Book one delivery carrying 200 m3 of the given position; return its id."""
    from app.modules.site_logistics.models import DeliveryBooking, DeliveryLine

    start = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
    delivery = DeliveryBooking(
        id=uuid.uuid4(),
        project_id=project_id,
        supplier_name="Readymix Rhein",
        window_start=start,
        window_end=start + timedelta(hours=1),
        status="completed",
        lines=[
            DeliveryLine(
                id=uuid.uuid4(),
                boq_position_id=position_id,
                position_ordinal="03.10.020",
                description="C30/37 in-situ concrete to slabs",
                quantity=Decimal("200"),
                unit="m3",
                sort_order=0,
            )
        ],
    )
    pg_session.add(delivery)
    await pg_session.flush()
    return delivery.id


async def test_deleting_the_position_detaches_the_line_and_keeps_the_record(pg_session) -> None:
    from sqlalchemy import select

    from app.modules.boq.models import Position
    from app.modules.site_logistics.models import DeliveryBooking, DeliveryLine

    project_id, position_id = await _seed_bill(pg_session)
    delivery_id = await _book_delivery(pg_session, project_id, position_id)

    position = await pg_session.get(Position, position_id)
    await pg_session.delete(position)
    await pg_session.flush()
    # The line was written before the delete; re-read it from the database
    # rather than trusting the copy in the identity map.
    pg_session.expire_all()

    lines = (
        (await pg_session.execute(select(DeliveryLine).where(DeliveryLine.delivery_id == delivery_id))).scalars().all()
    )
    assert len(lines) == 1, "the delivery line must survive the deletion of its bill position"
    line = lines[0]
    assert line.boq_position_id is None, "the foreign key must be nulled, not left dangling"
    # The physical record still says what arrived.
    assert line.quantity == Decimal("200.0000")
    assert line.unit == "m3"
    assert line.position_ordinal == "03.10.020"
    assert line.description == "C30/37 in-situ concrete to slabs"

    delivery = await pg_session.get(DeliveryBooking, delivery_id)
    assert delivery is not None, "deleting an estimate line must not delete the delivery"


async def test_a_detached_line_covers_nothing_and_is_counted_as_detached(pg_session) -> None:
    from app.modules.boq.models import Position
    from app.modules.site_logistics.repository import DeliveryLineRepository

    project_id, position_id = await _seed_bill(pg_session)
    await _book_delivery(pg_session, project_id, position_id)
    repo = DeliveryLineRepository(pg_session)

    assert len(await repo.list_project_line_facts(project_id)) == 1
    assert await repo.count_detached_lines(project_id) == 0

    await pg_session.delete(await pg_session.get(Position, position_id))
    await pg_session.flush()
    pg_session.expire_all()

    # It no longer covers a bill line...
    assert await repo.list_project_line_facts(project_id) == []
    # ...and it is reported rather than silently disappearing.
    assert await repo.count_detached_lines(project_id) == 1


async def test_a_line_that_never_had_a_position_is_not_reported_as_detached(pg_session) -> None:
    """A skip or a welfare unit carries no bill position and never had one."""
    from app.modules.site_logistics.models import DeliveryBooking, DeliveryLine
    from app.modules.site_logistics.repository import DeliveryLineRepository

    project_id, _ = await _seed_bill(pg_session)
    start = datetime.now(UTC).replace(hour=14, minute=0, second=0, microsecond=0)
    pg_session.add(
        DeliveryBooking(
            id=uuid.uuid4(),
            project_id=project_id,
            supplier_name="Skip hire",
            window_start=start,
            window_end=start + timedelta(hours=1),
            status="completed",
            lines=[
                DeliveryLine(
                    id=uuid.uuid4(),
                    boq_position_id=None,
                    position_ordinal=None,
                    description="Skip exchange",
                    quantity=Decimal("1"),
                    unit="pcs",
                    sort_order=0,
                )
            ],
        )
    )
    await pg_session.flush()

    assert await DeliveryLineRepository(pg_session).count_detached_lines(project_id) == 0


async def test_coverage_reads_the_leaf_lines_and_skips_the_headings(pg_session) -> None:
    """The picker offers lines a lorry can deliver, not the sections above them."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.site_logistics.service import SiteLogisticsService
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"coverage-{uuid.uuid4().hex[:8]}@site.example",
        hashed_password="x",
        full_name="Quantity Surveyor",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(id=uuid.uuid4(), name="Coverage shape", owner_id=owner.id, currency="EUR")
    pg_session.add(project)
    await pg_session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Main bill", status="draft")
    pg_session.add(boq)
    await pg_session.flush()

    # A heading written the way the service writes one...
    typed_section = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="03",
        description="Concrete",
        unit="section",
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=0,
    )
    # ...and a heading written the way an import writes one: blank unit, but it
    # owns children, which is what actually makes it structural.
    parent_section = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="03.10",
        description="In-situ concrete",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=1,
    )
    pg_session.add_all([typed_section, parent_section])
    await pg_session.flush()

    leaf = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        parent_id=parent_section.id,
        ordinal="03.10.020",
        description="C30/37 in-situ concrete to slabs",
        unit="m3",
        quantity="450",
        unit_rate="118.40",
        total="53280",
        sort_order=2,
    )
    pg_session.add(leaf)
    await pg_session.flush()

    await _book_delivery(pg_session, project.id, leaf.id)

    coverage = await SiteLogisticsService(pg_session).get_bill_coverage(project.id)
    assert [row.ordinal for row in coverage.rows] == ["03.10.020"]
    assert coverage.total == 1
    assert coverage.truncated is False
    assert coverage.currency == "EUR"
    assert coverage.linked_position_count == 1

    row = coverage.rows[0]
    assert row.bill_quantity == "450"
    assert row.delivered_quantity == "200.0000"
    assert row.outstanding_quantity == "250.0000"
    # 200 m3 on site at the bill's own rate.
    assert Decimal(row.delivered_value) == Decimal("200") * Decimal("118.40")
    assert Decimal(coverage.delivered_value_total) == Decimal("23680.000000")
    assert row.over_delivered is False


async def test_the_demo_seed_books_against_the_projects_own_bill(pg_session) -> None:
    """The demo board opens with deliveries linked to real estimate lines.

    Without this the founder's demo page shows an empty board and the bill
    link, which is the whole point of the module's estimate integration, is
    invisible. The seeded data must also satisfy the module's own rules, so
    the same helpers the service uses are run over it here.
    """
    from app.modules.site_logistics.demo import seed_demo_site_logistics
    from app.modules.site_logistics.repository import DeliveryRepository, GateRepository, LaydownZoneRepository
    from app.modules.site_logistics.service import SiteLogisticsService
    from app.modules.site_logistics.validators import delivery_within_gate_hours, find_first_overlap

    project_id, _ = await _seed_bill(pg_session)

    written = await seed_demo_site_logistics(
        pg_session,
        project_id=project_id,
        created_by="demo-owner",
        suppliers=["Verdanko Hochbau AG"],
    )
    assert written > 0, "a demo project with a priced bill must get demo deliveries"

    gates = await GateRepository(pg_session).list_for_project(project_id)
    zones = await LaydownZoneRepository(pg_session).list_for_project(project_id)
    deliveries = await DeliveryRepository(pg_session).list_for_project(project_id)
    assert len(gates) == 2
    assert len(zones) == 2
    assert len(deliveries) == written

    gate_by_id = {gate.id: gate for gate in gates}
    approved_by_gate: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {}
    for delivery in deliveries:
        assert delivery.lines, "every seeded delivery carries a bill line"
        for line in delivery.lines:
            assert line.boq_position_id is not None
            assert line.quantity > 0
            assert line.unit

        gate = gate_by_id[delivery.gate_id]
        # The demo project has no site time zone; its windows are seeded on the UTC clock.
        ok, reason = delivery_within_gate_hours(
            gate.open_time, gate.close_time, delivery.window_start, delivery.window_end, UTC
        )
        assert ok, f"seeded delivery breaks its own gate hours: {reason}"

        if delivery.status == "approved":
            seen = approved_by_gate.setdefault(gate.id, [])
            assert find_first_overlap(delivery.window_start, delivery.window_end, seen) is None, (
                "two seeded approved deliveries clash on one gate"
            )
            seen.append((delivery.window_start, delivery.window_end))

    # And the coverage table has something to show.
    coverage = await SiteLogisticsService(pg_session).get_bill_coverage(project_id)
    assert coverage.linked_position_count >= 1
    assert Decimal(coverage.delivered_value_total) > 0


async def test_deleting_the_delivery_takes_its_lines_with_it(pg_session) -> None:
    from sqlalchemy import func, select

    from app.modules.site_logistics.models import DeliveryBooking, DeliveryLine

    project_id, position_id = await _seed_bill(pg_session)
    delivery_id = await _book_delivery(pg_session, project_id, position_id)

    await pg_session.delete(await pg_session.get(DeliveryBooking, delivery_id))
    await pg_session.flush()

    remaining = (
        await pg_session.execute(
            select(func.count()).select_from(DeliveryLine).where(DeliveryLine.delivery_id == delivery_id)
        )
    ).scalar_one()
    assert remaining == 0, "a cancelled booking must not leave its lines behind"


async def test_the_enrichment_seed_fills_an_existing_project_once(pg_session) -> None:
    """The path that reaches an estate that already exists, and reaches it once.

    The installer seeds a project as it is created, so on its own it fills new
    installations only - including none of the demo estates people actually
    open. ``demo_enrichment`` is the path that re-runs over existing projects,
    and it is the one this asserts: rows appear, every one of them is booked
    against the bill, and a second boot adds nothing.
    """
    from sqlalchemy import func, select

    from app.modules.site_logistics.demo import seed_site_logistics_demo
    from app.modules.site_logistics.models import DeliveryBooking, DeliveryLine

    project_id, _ = await _seed_bill(pg_session)

    first = await seed_site_logistics_demo(pg_session, [project_id])
    assert first.get("projects") == 1
    assert first.get("deliveries", 0) > 0

    linked = (
        await pg_session.execute(
            select(func.count())
            .select_from(DeliveryLine)
            .join(DeliveryBooking, DeliveryLine.delivery_id == DeliveryBooking.id)
            .where(
                DeliveryBooking.project_id == project_id,
                DeliveryLine.boq_position_id.is_not(None),
            )
        )
    ).scalar_one()
    assert linked == first["deliveries"], "every seeded delivery carries a line booked against the bill"

    second = await seed_site_logistics_demo(pg_session, [project_id])
    assert second == {}, "a second boot must not add to a board that already has one"

    total = (
        await pg_session.execute(
            select(func.count()).select_from(DeliveryBooking).where(DeliveryBooking.project_id == project_id)
        )
    ).scalar_one()
    assert total == first["deliveries"]


async def test_a_project_without_a_priced_bill_gets_no_board(pg_session) -> None:
    """No bill, no deliveries - not a board of deliveries of nothing."""
    from sqlalchemy import func, select

    from app.modules.projects.models import Project
    from app.modules.site_logistics.demo import seed_site_logistics_demo
    from app.modules.site_logistics.models import DeliveryBooking, Gate
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"nobill-{uuid.uuid4().hex[:8]}@site.example",
        hashed_password="x",
        full_name="Estimator",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(id=uuid.uuid4(), name="No bill yet", owner_id=owner.id, currency="EUR")
    pg_session.add(project)
    await pg_session.flush()

    # The logistics plan is seeded for every demo project; the deliveries need a priced bill.
    assert await seed_site_logistics_demo(pg_session, [project.id]) == {
        "projects": 0,
        "deliveries": 0,
        "plan_projects": 1,
    }

    for model in (Gate, DeliveryBooking):
        count = (
            await pg_session.execute(select(func.count()).select_from(model).where(model.project_id == project.id))
        ).scalar_one()
        assert count == 0, f"{model.__name__} written for a project with nothing to deliver"


async def test_editing_a_delivery_does_not_forget_that_a_line_was_detached(pg_session) -> None:
    """A detached line stays detached when the booking is edited for another reason.

    The ordinal snapshot is the only thing that tells a line whose position was
    deleted apart from a line that was never in the bill. The page saves the
    whole booking every time, so an edit to the driver's phone number rewrites
    every line; if the ordinal did not travel with the payload the line would
    come back as never-billed and drop out of the detached count, which is what
    puts it in front of a quantity surveyor.
    """
    from app.modules.boq.models import Position
    from app.modules.site_logistics.repository import DeliveryLineRepository
    from app.modules.site_logistics.schemas import DeliveryLineInput, DeliveryUpdate
    from app.modules.site_logistics.service import SiteLogisticsService

    project_id, position_id = await _seed_bill(pg_session)
    delivery_id = await _book_delivery(pg_session, project_id, position_id)
    repo = DeliveryLineRepository(pg_session)

    await pg_session.delete(await pg_session.get(Position, position_id))
    await pg_session.flush()
    pg_session.expire_all()
    assert await repo.count_detached_lines(project_id) == 1

    # What the page sends back after the user changes something unrelated: the
    # lines are round-tripped from the delivery it just read.
    service = SiteLogisticsService(pg_session)
    delivery = await service.get_delivery(delivery_id)
    payload = DeliveryUpdate(
        notes="Driver called ahead",
        lines=[
            DeliveryLineInput(
                boq_position_id=line.boq_position_id,
                position_ordinal=line.position_ordinal,
                description=line.description,
                quantity=str(line.quantity),
                unit=line.unit,
            )
            for line in delivery.lines
        ],
    )
    await service.update_delivery(delivery_id, payload)
    pg_session.expire_all()

    assert await repo.count_detached_lines(project_id) == 1, "an ordinary edit must not un-detach the line"
    saved = await service.get_delivery(delivery_id)
    assert saved.notes == "Driver called ahead"
    assert [line.position_ordinal for line in saved.lines] == ["03.10.020"]
    assert [line.boq_position_id for line in saved.lines] == [None]


async def test_the_bill_still_owns_the_ordinal_of_a_line_it_prices(pg_session) -> None:
    """A caller cannot rewrite the ordinal of a line that is linked to the bill.

    The ordinal travels in the payload only so a detached line keeps its own.
    For a linked line the position remains the source of truth, exactly as it
    already is for the description and the unit.
    """
    from app.modules.site_logistics.repository import DeliveryLineRepository
    from app.modules.site_logistics.schemas import DeliveryLineInput, DeliveryUpdate
    from app.modules.site_logistics.service import SiteLogisticsService

    project_id, position_id = await _seed_bill(pg_session)
    delivery_id = await _book_delivery(pg_session, project_id, position_id)

    service = SiteLogisticsService(pg_session)
    await service.update_delivery(
        delivery_id,
        DeliveryUpdate(
            lines=[
                DeliveryLineInput(
                    boq_position_id=position_id,
                    position_ordinal="99.99.999",
                    description="whatever the caller felt like",
                    quantity="200",
                    unit="t",
                )
            ]
        ),
    )
    pg_session.expire_all()

    saved = await service.get_delivery(delivery_id)
    assert [line.position_ordinal for line in saved.lines] == ["03.10.020"]
    assert [line.unit for line in saved.lines] == ["m3"]
    assert [line.description for line in saved.lines] == ["C30/37 in-situ concrete to slabs"]
    assert await DeliveryLineRepository(pg_session).count_detached_lines(project_id) == 0
