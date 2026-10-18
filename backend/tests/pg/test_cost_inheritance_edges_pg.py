# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Edges of cost line inheritance, on real PostgreSQL.

The companion of ``test_cost_inheritance_pg``: what happens to a split when
a row is put on another line by the older link path, a reference that points
into another project, a direct cost on an invoice that already bills a
contract, the number of queries the chain panel makes as change items grow,
and the five columns and the table of ``v93`` on an install that heals its
schema at boot instead of running alembic.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text

from app.modules.bid_management.models import BidPackage, BidPackageLineItem
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.costmodel.chain_service import CostChainService
from app.modules.costmodel.inheritance import (
    SOURCE_CONTRACT_LINE,
    SOURCE_PO_ITEM,
    Vector,
    write_split,
)
from app.modules.costmodel.inheritance_service import inherit_contract_lines
from app.modules.costmodel.repository import CostSpineRepository
from app.modules.costmodel.service import CostSpineService
from app.modules.finance.models import InvoiceLineItem
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from tests.pg.test_cost_inheritance_pg import (  # noqa: F401 - ``session`` is a fixture
    _contract,
    _contract_line,
    _invoice,
    _lines,
    _project,
    _shares,
    session,
)

pytestmark = pytest.mark.asyncio

D = Decimal


async def _split_line(session, project, line, shares: list[tuple[object, str]], source_type: str) -> None:
    """Put an existing row on a stored split, the way the award writes it."""
    vector = Vector(
        main=str(shares[0][0].id),
        shares=tuple((str(cl.id), D(pct) / 100) for cl, pct in shares),
    )
    line.cost_line_id = await write_split(
        session, project_id=project.id, source_type=source_type, source_id=line.id, vector=vector
    )
    await session.flush()


# ── Re-pointing a split row through the cost spine link ──────────────────────


async def test_linking_a_split_contract_line_to_another_line_moves_all_its_money(session) -> None:
    """The link path of the cost spine re-points the row; the split it had must not outlive that."""
    project = await _project(session)
    walls, floors, roof = await _lines(session, project, "331", "352", "361")
    contract = await _contract(session, project, value="1000")
    line = await _contract_line(session, contract, value="1000")
    await _split_line(session, project, line, [(walls, "60"), (floors, "40")], SOURCE_CONTRACT_LINE)

    before = await CostSpineRepository(session).contract_value_by_cost_line(project.id)
    assert (before[str(walls.id)], before[str(floors.id)]) == (D("600.00"), D("400.00"))

    # The link expires the session; keep the ids.
    project_id, line_id, roof_id, walls_id, floors_id = project.id, line.id, roof.id, walls.id, floors.id
    await CostSpineService(session).link_target(roof_id, "contract_line", line_id)

    after = await CostSpineRepository(session).contract_value_by_cost_line(project_id)
    assert after.get(str(roof_id)) == D("1000")
    assert str(walls_id) not in after and str(floors_id) not in after
    assert await _shares(session, SOURCE_CONTRACT_LINE, line_id) == {}


async def test_linking_a_split_order_item_to_one_of_its_own_lines_puts_it_there_whole(session) -> None:
    """Re-pointed at a line the split already has, the item still goes there whole."""
    project = await _project(session)
    walls, floors = await _lines(session, project, "331", "352")
    po = PurchaseOrder(
        project_id=project.id,
        po_number=f"PO-{uuid.uuid4().hex[:6]}",
        currency_code="EUR",
        status="issued",
        amount_subtotal="500",
        amount_total="500",
    )
    session.add(po)
    await session.flush()
    item = PurchaseOrderItem(po_id=po.id, description="Rebar", quantity="1", unit_rate="500", amount="500")
    session.add(item)
    await session.flush()
    await _split_line(session, project, item, [(walls, "70"), (floors, "30")], SOURCE_PO_ITEM)

    project_id, item_id, walls_id, floors_id = project.id, item.id, walls.id, floors.id
    await CostSpineService(session).link_target(floors_id, "po_item", item_id)

    committed = await CostSpineRepository(session).po_committed_by_cost_line(project_id)
    assert committed.get(str(floors_id)) == D("500")
    assert str(walls_id) not in committed


async def test_a_split_left_behind_by_another_writer_does_not_override_the_rows_own_line(session) -> None:
    """A row whose own pointer is outside its stored split reads as its pointer: the split is stale."""
    project = await _project(session)
    walls, floors, roof = await _lines(session, project, "331", "352", "361")
    contract = await _contract(session, project, value="800")
    line = await _contract_line(session, contract, value="800")
    await _split_line(session, project, line, [(walls, "50"), (floors, "50")], SOURCE_CONTRACT_LINE)
    # Any writer that sets the column without knowing about splits.
    line.cost_line_id = roof.id
    await session.flush()

    values = await CostSpineRepository(session).contract_value_by_cost_line(project.id)
    assert values == {str(roof.id): D("800")}


# ── References into another project ──────────────────────────────────────────


async def test_a_contract_line_never_inherits_a_cost_line_of_another_project(session) -> None:
    """A scope line named in a line's metadata from another project gives it nothing."""
    project = await _project(session)
    other = await _project(session)
    [foreign_line] = await _lines(session, other, "331")
    package = BidPackage(project_id=other.id, code=f"BP-{uuid.uuid4().hex[:6]}", title="Other", currency="EUR")
    session.add(package)
    await session.flush()
    scope = BidPackageLineItem(
        package_id=package.id, code="1", description="Walls", quantity="1", unit="m3", cost_line_id=foreign_line.id
    )
    session.add(scope)
    await session.flush()

    contract = await _contract(session, project, value="100")
    line = await _contract_line(session, contract, value="100", bid_package_line_id=str(scope.id))
    assert await inherit_contract_lines(session, contract, [line]) == 0
    assert line.cost_line_id is None


async def test_a_contract_whose_account_is_in_another_project_gives_its_lines_nothing(session) -> None:
    project = await _project(session)
    other = await _project(session)
    [foreign_line] = await _lines(session, other, "331")
    contract = await _contract(session, project, value="100", cost_line_id=foreign_line.id)
    line = await _contract_line(session, contract, value="100")
    assert await inherit_contract_lines(session, contract, [line]) == 0
    assert line.cost_line_id is None


# ── Direct cost on an invoice that already bills a contract ──────────────────


async def test_direct_cost_refuses_an_invoice_whose_lines_bill_a_contract_line(session) -> None:
    """Re-pointing billed lines at a new contract would move money off the contract they bill."""
    project = await _project(session)
    [walls, general] = await _lines(session, project, "331", "390")
    contract = await _contract(session, project, value="300")
    schedule = await _contract_line(session, contract, value="300", cost_line=walls)
    invoice = await _invoice(session, project, number="SUP-881", net="300")
    session.add(
        InvoiceLineItem(
            invoice_id=invoice.id,
            description="Walls",
            amount=D("300"),
            contract_line_id=schedule.id,
            cost_line_id=walls.id,
        )
    )
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await CostChainService(session).direct_cost_contract(project.id, invoice.id, general.id, None)
    assert exc.value.status_code == 409
    [item] = (await session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id))).scalars()
    assert (item.contract_line_id, item.cost_line_id) == (schedule.id, walls.id)


# ── The chain panel does not query per change item ───────────────────────────


async def _orders_with_items(session, project, contract, schedule, count: int) -> None:
    order = ChangeOrder(
        project_id=project.id,
        code=f"CO-{uuid.uuid4().hex[:5]}",
        title="Changes",
        status="submitted",
        currency="EUR",
        metadata_={"contract_id": str(contract.id)},
    )
    session.add(order)
    await session.flush()
    for n in range(count):
        session.add(
            ChangeOrderItem(
                change_order_id=order.id,
                description=f"Change {n}",
                change_type="added",
                original_quantity=D("0"),
                new_quantity=D("1"),
                original_rate=D("0"),
                new_rate=D("10"),
                cost_delta=D("10"),
                unit="m3",
                sort_order=n,
                metadata_={"contract_line_id": str(schedule.id)},
            )
        )
    await session.flush()


async def _count_queries(session, coro_factory) -> int:
    conn = await session.connection()
    engine = conn.sync_connection.engine
    seen: list[str] = []

    def _on(_conn, _cursor, statement, *_args) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _on)
    try:
        await coro_factory()
    finally:
        event.remove(engine, "before_cursor_execute", _on)
    return len(seen)


async def test_suspense_and_inherit_make_the_same_number_of_queries_for_three_or_thirty_change_items(
    session,
) -> None:
    counts = {}
    for size in (3, 30):
        project = await _project(session)
        [walls] = await _lines(session, project, "331")
        contract = await _contract(session, project, value="1000")
        schedule = await _contract_line(session, contract, value="1000", cost_line=walls)
        await _orders_with_items(session, project, contract, schedule, size)
        chain = CostChainService(session)
        suspense = await _count_queries(session, lambda chain=chain, p=project.id: chain.suspense(p))
        buckets = await chain.suspense(project.id)
        [items] = [b for b in buckets if b["kind"] == "change_order_item"]
        assert (items["count"], items["inheritable"]) == (size, size)
        inherit = await _count_queries(session, lambda chain=chain, p=project.id: chain.inherit_missing(p))
        counts[size] = (suspense, inherit)
        rows = (
            await session.execute(
                select(ChangeOrderItem.cost_line_id, ChangeOrderItem.cost_line_source)
                .join(ChangeOrder, ChangeOrder.id == ChangeOrderItem.change_order_id)
                .where(ChangeOrder.project_id == project.id)
            )
        ).all()
        assert {tuple(r) for r in rows} == {(walls.id, "contract_line")}
    assert counts[30] == counts[3], counts


# ── v93 on an install that heals its schema at boot ──────────────────────────

_V93_COLUMNS = (
    ("oe_bid_management_line_item", "cost_line_id"),
    ("oe_contracts_contract", "cost_line_id"),
    ("oe_changeorders_item", "cost_line_id"),
    ("oe_changeorders_item", "cost_line_source"),
    ("oe_finance_invoice_item", "contract_line_id"),
)
_V93_TABLE = "oe_costmodel_line_allocation"


async def _v93_shape(conn) -> tuple[set[tuple[str, str]], bool]:
    present = set()
    for table, column in _V93_COLUMNS:
        found = (
            await conn.execute(
                text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
                {"t": table, "c": column},
            )
        ).scalar()
        if found:
            present.add((table, column))
    table = (await conn.execute(text("SELECT to_regclass(:t)"), {"t": _V93_TABLE})).scalar()
    return present, table is not None


async def test_an_install_upgraded_without_alembic_gets_the_v93_columns_and_table(pg_engine) -> None:
    """Pip and desktop installs heal the schema at boot and stamp head; v93 must arrive that way too."""
    from app.core.postgres_migrator import postgres_auto_migrate
    from app.database import Base

    async with pg_engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {_V93_TABLE} CASCADE"))
        for table, column in _V93_COLUMNS:
            await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column} CASCADE"))
        gone = await _v93_shape(conn)
    assert gone == (set(), False), "precondition: the database must look like 18.6"

    try:
        await postgres_auto_migrate(pg_engine, Base)
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        async with pg_engine.connect() as conn:
            healed = await _v93_shape(conn)
            indexes = {
                name
                for (name,) in (
                    await conn.execute(
                        text("SELECT indexname FROM pg_indexes WHERE tablename = ANY(:t)"),
                        {"t": [t for t, _c in _V93_COLUMNS]},
                    )
                ).all()
            }
        assert healed == (set(_V93_COLUMNS), True)
        for name in (
            "ix_oe_bid_management_line_item_cost_line_id",
            "ix_oe_contracts_contract_cost_line_id",
            "ix_oe_changeorders_item_cost_line_id",
            "ix_oe_finance_invoice_item_contract_line_id",
        ):
            assert name in indexes, f"{name} was not created by the heal"
    finally:
        # Leave the shared schema whole for whatever runs next, whatever the heal did.
        async with pg_engine.begin() as conn:
            for table, column in _V93_COLUMNS:
                kind = "VARCHAR(20)" if column == "cost_line_source" else "UUID"
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind}"))
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
