"""Cost-item usage ledger is written when a position is added from /costs.

Founder bug (2026-06-06): the Cost Database "used in an estimate" indicator
never flipped because nothing ever wrote a ``CostItemUsage`` row. Adding a
cost item to a BOQ now records a usage-ledger entry server-side (best
effort), which both flips the new "used in N estimates" badge and feeds the
certainty frequency.

These tests pin:

* ``BOQService.add_position`` with a ``cost_item_id`` writes exactly one
  ledger row carrying the project, the unit_rate at use, and context "boq".
* ``add_position`` WITHOUT a ``cost_item_id`` writes no ledger row (plain
  manual positions must not pollute the usage stats).
* The grouped usage-count query that backs ``POST /v1/costs/usage-counts``
  returns ``{id: count}`` and omits ids with zero uses.

Isolation uses the shared PostgreSQL transactional session
(``tests._pg.transactional_session``): each test runs inside an outer
transaction rolled back on teardown, so the real database is never touched.

Run:
    cd backend
    python -m pytest tests/unit/test_cost_item_usage_on_add.py -v --tb=short
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.boq.models import BOQ
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.costs.models import CostItem, CostItemUsage
from app.modules.projects.models import Project
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"usage-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="Usage Tester",
            )
        )
        await s.flush()
        await s.commit()
        yield s


async def _make_project_boq_item(session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create a project, a BOQ, and an active cost item. Returns their ids."""
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=f"UsageProj {uuid.uuid4().hex[:6]}",
            owner_id=OWNER_ID,
            currency="EUR",
        )
    )
    await session.flush()

    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="Usage BOQ")
    session.add(boq)
    await session.flush()

    item = CostItem(
        id=uuid.uuid4(),
        code=f"USE-{uuid.uuid4().hex[:6]}",
        description="Concrete C30/37 wall",
        unit="m3",
        rate="185.00",
        currency="EUR",
        source="cwicr",
        classification={"collection": "Concrete"},
        components=[],
        tags=[],
        region="DE_BERLIN",
        is_active=True,
        metadata_={},
    )
    session.add(item)
    await session.commit()
    return project_id, boq.id, item.id


# ── add_position records usage ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_position_with_cost_item_records_usage(session):
    """Adding a position linked to a cost item writes one ledger row."""
    project_id, boq_id, item_id = await _make_project_boq_item(session)
    service = BOQService(session)

    await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="01.001",
            description="Concrete C30/37 wall",
            unit="m3",
            quantity="1",
            unit_rate="185.00",
            source="cost_database",
            cost_item_id=item_id,
            metadata={"currency": "EUR"},
        )
    )
    await session.commit()

    rows = (await session.execute(select(CostItemUsage).where(CostItemUsage.cost_item_id == item_id))).scalars().all()
    assert len(rows) == 1, "exactly one usage row expected"
    row = rows[0]
    assert row.project_id == project_id
    assert row.context == "boq"
    assert str(row.unit_rate_at_use) in {"185.0000", "185", "185.00"}


@pytest.mark.asyncio
async def test_add_two_positions_records_two_usages(session):
    """Two adds of the same item => count 2 (the badge shows '2')."""
    _project_id, boq_id, item_id = await _make_project_boq_item(session)
    service = BOQService(session)

    for ordn in ("01.001", "01.002"):
        await service.add_position(
            PositionCreate(
                boq_id=boq_id,
                ordinal=ordn,
                description="Concrete C30/37 wall",
                unit="m3",
                quantity="1",
                unit_rate="185.00",
                source="cost_database",
                cost_item_id=item_id,
                metadata={"currency": "EUR"},
            )
        )
    await session.commit()

    count = (
        await session.execute(select(func.count(CostItemUsage.id)).where(CostItemUsage.cost_item_id == item_id))
    ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_add_position_without_cost_item_records_no_usage(session):
    """Plain manual positions must not write a usage-ledger row."""
    _project_id, boq_id, item_id = await _make_project_boq_item(session)
    service = BOQService(session)

    await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="01.001",
            description="Manual line",
            unit="m3",
            quantity="1",
            unit_rate="100.00",
            source="manual",
        )
    )
    await session.commit()

    count = (
        await session.execute(select(func.count(CostItemUsage.id)).where(CostItemUsage.cost_item_id == item_id))
    ).scalar_one()
    assert count == 0


# ── usage-count grouped query (backs POST /v1/costs/usage-counts) ──────────


@pytest.mark.asyncio
async def test_usage_count_grouped_query_omits_zero(session):
    """The grouped count returns only ids with >=1 use."""
    _project_id, boq_id, used_id = await _make_project_boq_item(session)

    # A second, never-used cost item.
    unused_id = uuid.uuid4()
    session.add(
        CostItem(
            id=unused_id,
            code=f"IDLE-{uuid.uuid4().hex[:6]}",
            description="Untouched rebar",
            unit="kg",
            rate="1.50",
            currency="EUR",
            source="cwicr",
            classification={},
            components=[],
            tags=[],
            region="DE_BERLIN",
            is_active=True,
            metadata_={},
        )
    )
    await session.commit()

    service = BOQService(session)
    await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="01.001",
            description="Concrete",
            unit="m3",
            quantity="1",
            unit_rate="185.00",
            source="cost_database",
            cost_item_id=used_id,
            metadata={"currency": "EUR"},
        )
    )
    await session.commit()

    ids = [used_id, unused_id]
    rows = await session.execute(
        select(CostItemUsage.cost_item_id, func.count(CostItemUsage.id))
        .where(CostItemUsage.cost_item_id.in_(ids))
        .group_by(CostItemUsage.cost_item_id)
    )
    counts = {str(r[0]): int(r[1]) for r in rows.all()}
    assert counts == {str(used_id): 1}
    # The unused id is absent (client treats a missing id as 0).
    assert str(unused_id) not in counts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,expected", [({}, "EUR"), ({"currency": " gbp "}, "GBP"), ({"position_currency": "JPY"}, "JPY")]
)
async def test_usage_snapshots_applied_position_currency_not_current_catalog(session, metadata, expected):
    project_id, boq_id, item_id = await _make_project_boq_item(session)
    await BOQService(session).add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="snapshot",
            description="Applied rate",
            unit="m3",
            quantity="1",
            unit_rate="123.45678",
            cost_item_id=item_id,
            metadata=metadata,
        )
    )
    row = (await session.execute(select(CostItemUsage).where(CostItemUsage.cost_item_id == item_id))).scalar_one()
    assert row.currency_at_use == expected
    from decimal import Decimal

    assert row.unit_rate_at_use == Decimal("123.4568")
    item = await session.get(CostItem, item_id)
    project = await session.get(Project, project_id)
    item.currency = "USD"
    project.currency = "KWD"
    await session.flush()
    await session.refresh(row)
    assert row.currency_at_use == expected
    assert row.unit_rate_at_use == Decimal("123.4568")


@pytest.mark.asyncio
async def test_usage_endpoint_preserves_explicit_currency_and_keeps_omitted_currency_unknown(session):
    from app.modules.costs.router import record_cost_item_usage
    from app.modules.costs.schemas import RecordUsageRequest

    project_id, _boq_id, item_id = await _make_project_boq_item(session)
    for currency in (" kwd ", None):
        result = await record_cost_item_usage(
            item_id,
            RecordUsageRequest(
                project_id=project_id,
                unit_rate_at_use="17.125",
                currency_at_use=currency,
            ),
            session,
            {"sub": str(OWNER_ID)},
        )
        row = await session.get(CostItemUsage, uuid.UUID(result["id"]))
        assert row.currency_at_use == ("KWD" if currency else None)
        assert result["currency_at_use"] == row.currency_at_use
    item = await session.get(CostItem, item_id)
    item.currency = "JPY"
    await session.flush()
    snapshots = (
        (await session.execute(select(CostItemUsage.currency_at_use).where(CostItemUsage.cost_item_id == item_id)))
        .scalars()
        .all()
    )
    assert set(snapshots) == {"KWD", None}


@pytest.mark.asyncio
async def test_direct_recorder_uses_only_supplied_currency(session):
    from app.modules.costs.intelligence import CostUsageRecorder

    project_id, _boq_id, item_id = await _make_project_boq_item(session)
    recorder = CostUsageRecorder(session)
    explicit = await recorder.record(item_id, project_id=project_id, unit_rate_at_use="12", currency_at_use=" usd ")
    unknown = await recorder.record(item_id, project_id=project_id, unit_rate_at_use="12")
    assert explicit.currency_at_use == "USD"
    assert unknown.currency_at_use is None


@pytest.mark.asyncio
@pytest.mark.parametrize("applied_currency,applied_rate", [("EUR", "100"), ("USD", "110")])
async def test_fx_applied_rate_snapshot_matches_storage_and_rollup(session, applied_currency, applied_rate):
    from decimal import Decimal

    project_id, boq_id, item_id = await _make_project_boq_item(session)
    project = await session.get(Project, project_id)
    project.currency = "USD"
    project.fx_rates = [{"code": "EUR", "rate": "1.10", "label": "Euro"}]
    item = await session.get(CostItem, item_id)
    item.rate = "100"
    item.currency = "EUR"
    await session.flush()
    service = BOQService(session)
    position = await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="fx",
            description="EUR catalogue rate",
            unit="m3",
            quantity="1",
            unit_rate=applied_rate,
            cost_item_id=item_id,
            metadata={"currency": applied_currency},
        )
    )
    row = (await session.execute(select(CostItemUsage).where(CostItemUsage.cost_item_id == item_id))).scalar_one()
    assert Decimal(position.unit_rate) == Decimal(applied_rate)
    assert row.unit_rate_at_use == Decimal(applied_rate)
    assert row.currency_at_use == applied_currency
    assert (await service.get_boq_structured(boq_id)).direct_cost == Decimal("110")
    item.currency = "JPY"
    project.currency = "KWD"
    await session.flush()
    await session.refresh(row)
    assert row.currency_at_use == applied_currency
    assert row.unit_rate_at_use == Decimal(applied_rate)
