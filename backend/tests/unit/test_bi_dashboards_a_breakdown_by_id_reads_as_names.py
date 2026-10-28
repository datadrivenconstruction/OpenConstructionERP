# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A breakdown keyed by an id has to say what each id is - issue #441.

Grouping a custom KPI by ``boq_id`` is how the reporter asked for a number
per bid, and it is the only way to ask: the group key is what the database
can group by. What comes back is then keyed by a uuid, and a column of
uuids is not an answer to "how does each of my estimates score". The name
was reachable - ``label_field: boq_name`` - but only by an author who
already knew the field existed, and the whole point of the whitelist is
that nobody should have to know that.

Three things are pinned here.

* The catalog declares which field names an id, and a spec that groups by
  that id and asks for no label gets that name written into it when the
  definition is created. Written at creation, not applied at compute: a
  definition already stored keeps whatever shape it was created with, and
  the author can read back what they got and change it.
* A name that is blank is not a name. ``boq_name`` is NOT NULL and still
  arrives empty, because ``BOQCreate`` checks ``min_length=1`` before the
  HTML sanitiser runs and a name of ``<script>x</script>`` sanitises to
  ``''``. An empty label renders as nothing at all, which reads as a
  broken row rather than as an estimate nobody named, so it takes the same
  reserved key as an absent group and the consumer localises it.
* The drill-down carries the name beside the id. Every custom KPI lands in
  the synthesised-record path - a spec has no registered record provider -
  so that path is the drill-down a custom KPI actually shows, and it was
  emitting the uuid as the record's key with the name buried inside its
  value.

Test isolation: a transaction-isolated PostgreSQL session on the shared
schema-loaded ``oe_test_unit`` database, rolled back on teardown.

Run:
    cd backend
    python -m pytest tests/unit/test_bi_dashboards_a_breakdown_by_id_reads_as_names.py -v --tb=short
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpi_spec, kpis
from app.modules.bi_dashboards.kpi_spec import NULL_GROUP_KEY
from app.modules.bi_dashboards.schemas import KPIDefinitionCreate
from app.modules.bi_dashboards.service import BIDashboardsService
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"kpi-label-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            ),
        )
        await s.flush()
        yield s


async def _seed_bid(session: AsyncSession, *, name: str) -> tuple[uuid.UUID, uuid.UUID]:
    """One project with one named bid carrying one priced position.

    Args:
        session: The test session.
        name: The bid's name, which is what the breakdown has to read as.

    Returns:
        ``(project_id, boq_id)``.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(Project(id=project_id, name="Breakdown label project", owner_id=OWNER_ID, currency="EUR"))
    await session.flush()

    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name=name)
    session.add(boq)
    await session.flush()

    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq.id,
            ordinal="001",
            description="Excavation",
            unit="m3",
            quantity="100",
            unit_rate="10",
            total="1000",
            confidence="0.9",
            sort_order=1,
        ),
    )
    await session.flush()
    return project_id, boq.id


def _amount_per_bid(code: str) -> KPIDefinitionCreate:
    """Sum of amount per bid, with no label asked for."""
    return KPIDefinitionCreate(
        code=code,
        name="Amount per bid",
        unit="currency",
        category="financial",
        spec={
            "entity": "boq_position",
            "aggregation": "sum",
            "field": "amount",
            "group_by": "boq_id",
        },
    )


def test_the_catalog_declares_which_field_names_an_id() -> None:
    """The pairing is data, not a suffix somebody strips off ``boq_id``.

    It is served too, so the form can offer the same answer the server
    would rather than silently disagreeing with it.
    """
    entity = kpi_spec.ENTITY_CATALOG["boq_position"]
    assert entity.display_name_for.get("boq_id") == "boq_name"

    served = {e["name"]: e for e in kpi_spec.catalog_as_dict()}
    assert served["boq_position"]["display_name_for"] == {"boq_id": "boq_name"}


def test_a_declared_display_name_points_at_a_field_that_can_be_a_label() -> None:
    """A name that is not a declared field makes the default do nothing.

    A numeric one is worse: the label rule rejects it, so the server would
    be generating a spec it then refuses.
    """
    report = kpi_spec.check_catalog_binding_parity()
    offenders = {name: diff["bad_display_name"] for name, diff in report.items() if diff.get("bad_display_name")}
    assert offenders == {}, f"a declared display name does not resolve to a labellable field: {offenders}"


def test_a_spec_grouped_by_an_id_is_stored_with_the_name_that_reads_it() -> None:
    """The default is written into the spec, so the author can see it."""
    spec = kpi_spec.validate_spec(
        {
            "entity": "boq_position",
            "aggregation": "sum",
            "field": "amount",
            "group_by": "boq_id",
        },
    )
    assert spec["label_field"] == "boq_name"


def test_a_group_with_no_declared_name_is_left_alone() -> None:
    """Nothing to default to is not the same as a default of nothing.

    ``unit`` is its own label, and inventing one for it would put every
    breakdown into the ``{label, value}`` shape whether or not the shape
    bought the reader anything.
    """
    spec = kpi_spec.validate_spec(
        {
            "entity": "boq_position",
            "aggregation": "sum",
            "field": "amount",
            "group_by": "unit",
        },
    )
    assert "label_field" not in spec


def test_an_author_who_names_a_label_keeps_it() -> None:
    """The default fills a gap; it does not overrule a choice."""
    spec = kpi_spec.validate_spec(
        {
            "entity": "boq_position",
            "aggregation": "top_by",
            "field": "amount",
            "group_by": "boq_id",
            "label_field": "description",
        },
    )
    assert spec["label_field"] == "description"


@pytest.mark.asyncio
async def test_a_breakdown_per_bid_comes_back_named_without_being_asked(session: AsyncSession) -> None:
    """The reporter's shape, with nothing in the spec about labels."""
    project_id, boq_id = await _seed_bid(session, name="Warehouse extension")
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_amount_per_bid("amount_per_bid_default_label"))

    result = await kpis.compute("amount_per_bid_default_label", session, project_id=project_id)

    group = result.breakdown[str(boq_id)]
    assert group["label"] == "Warehouse extension", (
        f"a breakdown grouped by boq_id came back as {group!r}, so the reader sees the uuid "
        f"{boq_id} where the estimate's name belongs"
    )


@pytest.mark.asyncio
async def test_a_bid_nobody_named_reads_as_the_reserved_key_not_as_nothing(session: AsyncSession) -> None:
    """An empty name is not a name, and blank is the worst way to say so.

    The row exists and has an amount; what it lacks is something to call
    it. Rendering that as an empty string loses the row visually, so it
    takes the key a consumer localises, exactly as an absent group does.
    """
    project_id, boq_id = await _seed_bid(session, name="   ")
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_amount_per_bid("amount_per_bid_blank_name"))

    result = await kpis.compute("amount_per_bid_blank_name", session, project_id=project_id)

    label = result.breakdown[str(boq_id)]["label"]
    assert label == NULL_GROUP_KEY, (
        f"a bid whose name is whitespace labelled its group {label!r}, which renders as an empty cell "
        f"rather than as something a reader can recognise"
    )


@pytest.mark.asyncio
async def test_the_drill_down_puts_the_name_beside_the_id_not_under_it(session: AsyncSession) -> None:
    """A custom KPI has no record provider, so this path is its drill-down.

    The name was inside the record's ``value``; a reader scanning the
    records saw a column of keys, and every one of them was a uuid.
    """
    project_id, boq_id = await _seed_bid(session, name="Warehouse extension")
    service = BIDashboardsService(session)
    await service.create_custom_kpi(_amount_per_bid("amount_per_bid_drill"))

    payload = await service.drill_down("amount_per_bid_drill", project_id=project_id)
    groups = [r for r in payload["records"] if r.get("kind") == "breakdown"]

    assert len(groups) == 1
    record: dict[str, Any] = groups[0]
    assert record["key"] == str(boq_id)
    assert record["label"] == "Warehouse extension", (
        f"the drill-down record for a bid is {record!r}, so the drawer renders the uuid and the name "
        f"is not a field of the record at all"
    )
    # The value stays the number it was, rather than the record that used
    # to carry the label. A reader of ``value`` gets an amount.
    assert record["value"] == "1000.00" or record["value"].startswith("1000")
