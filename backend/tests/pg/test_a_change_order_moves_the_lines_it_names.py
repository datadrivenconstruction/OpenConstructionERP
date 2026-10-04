# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An approved change order moves the schedule lines its items name.

It used to land as one pooled line whatever its items said, so the concrete
line a change added 20 m3 to kept its old scheduled value, and every claim
after that read percent complete on it against the wrong figure. The items
now say which line they change (by id, or through the bill position the item
was picked from), those lines move by their own items, and the rest share one
new line.

What these tests hold, against the database and through the same subscriber
the approval fires:

* the per-line deltas add up to the change order amount exactly, and the
  schedule adds up to the contract sum afterwards;
* a line no item names is identical, column for column, before and after;
* a replayed approval moves nothing;
* a line keeps quantity x rate equal to its total, so the claim generator,
  which prices off quantity x rate, bills the change;
* a deduction below what was already billed is posted and then blocks the
  next claim through ``pay_application.line_overbilled``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.notifications._wave5_cross_module_subscribers as w5
from app.core.events import Event
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, SovAdjustment
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

D = Decimal
BASE = D("110000")
LINE_COLUMNS = ("code", "description", "quantity", "unit_rate", "total_value", "order_index", "origin", "metadata_")


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(w5, "async_session_factory", factory)
        async with factory() as session:
            user, project, contract = await _parties(session, "lump_sum", BASE)
            position = uuid.uuid4()
            lines = {
                # A lump sum line.
                "A": ContractLine(
                    contract_id=contract.id,
                    code="A",
                    description="General conditions",
                    quantity=D("1"),
                    unit_rate=D("60000"),
                    total_value=D("60000"),
                    order_index=1,
                ),
                # A measured line linked to a bill position: 100 m3 at 400.
                "B": ContractLine(
                    contract_id=contract.id,
                    code="B",
                    description="Concrete",
                    unit="m3",
                    quantity=D("100"),
                    unit_rate=D("400"),
                    total_value=D("40000"),
                    order_index=2,
                    metadata_={"boq_position_id": str(position)},
                ),
                # A measured line at a rate no round change divides: 30 at 333.
                "C": ContractLine(
                    contract_id=contract.id,
                    code="C",
                    description="Masonry",
                    unit="m2",
                    quantity=D("30"),
                    unit_rate=D("333"),
                    total_value=D("9990"),
                    order_index=3,
                ),
                # A line no change order names.
                "E": ContractLine(
                    contract_id=contract.id,
                    code="E",
                    description="Electrical",
                    quantity=D("1"),
                    unit_rate=D("10"),
                    total_value=D("10"),
                    order_index=4,
                ),
            }
            session.add_all(lines.values())
            await session.commit()
            yield SimpleNamespace(
                engine=engine,
                factory=factory,
                project=project,
                contract=contract,
                user=user,
                lines=lines,
                position=position,
            )


MEASURED_BASE = D("15000")


@pytest_asyncio.fixture
async def measured(monkeypatch: pytest.MonkeyPatch):
    """A remeasurement contract: billed as measured quantity x unit rate."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(w5, "async_session_factory", factory)
        async with factory() as session:
            user, project, contract = await _parties(session, "remeasurement", MEASURED_BASE)
            lines = {
                # A provisional rate-only line: nothing scheduled yet.
                "R": ContractLine(
                    contract_id=contract.id,
                    code="R",
                    description="Rock excavation, provisional",
                    unit="m3",
                    quantity=D("0"),
                    unit_rate=D("80"),
                    total_value=D("0"),
                    order_index=1,
                ),
                "P": ContractLine(
                    contract_id=contract.id,
                    code="P",
                    description="Pump",
                    unit="pcs",
                    quantity=D("1"),
                    unit_rate=D("5000"),
                    total_value=D("5000"),
                    order_index=2,
                ),
                "X": ContractLine(
                    contract_id=contract.id,
                    code="X",
                    description="Excavation",
                    unit="m3",
                    quantity=D("100"),
                    unit_rate=D("50"),
                    total_value=D("5000"),
                    order_index=3,
                ),
                "G": ContractLine(
                    contract_id=contract.id,
                    code="G",
                    description="Site setup",
                    unit="LS",
                    quantity=D("1"),
                    unit_rate=D("5000"),
                    total_value=D("5000"),
                    order_index=4,
                ),
            }
            session.add_all(lines.values())
            await session.commit()
            yield SimpleNamespace(
                engine=engine, factory=factory, project=project, contract=contract, user=user, lines=lines
            )


async def _parties(session: AsyncSession, contract_type: str, base: Decimal):
    user = User(email=f"co-lines-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    session.add(user)
    await session.flush()
    project = Project(name="CO lines", owner_id=user.id, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
    contract = Contract(
        code=f"CT-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type=contract_type,
        status="active",
        currency="USD",
        total_value=base,
        original_contract_value=base,
        retention_percent=D("10"),
    )
    session.add(contract)
    await session.flush()
    return user, project, contract


def _qty(original_quantity: str, new_quantity: str, original_rate: str, new_rate: str, unit: str = "") -> dict:
    """An item's quantity columns, priced the way the change order service prices them."""
    return {
        "original_quantity": D(original_quantity),
        "new_quantity": D(new_quantity),
        "original_rate": D(original_rate),
        "new_rate": D(new_rate),
        "unit": unit,
    }


async def _change_order(
    world, cost_impact: str, items: list[tuple], *, mirrors: uuid.UUID | None = None
) -> ChangeOrder:
    """Items are ``(cost_delta, metadata)`` or ``(cost_delta, metadata, quantity columns)``."""
    async with world.factory() as session:
        meta = {"contract_id": str(world.contract.id)}
        if mirrors is not None:
            meta["variation_order_id"] = str(mirrors)
        order = ChangeOrder(
            project_id=world.project.id,
            code=f"CO-{uuid.uuid4().hex[:4]}",
            title="Owner change",
            status="approved",
            cost_impact=D(cost_impact),
            currency="USD",
            metadata_=meta,
        )
        session.add(order)
        await session.flush()
        for index, item in enumerate(items):
            cost, item_meta = item[0], item[1]
            columns = item[2] if len(item) > 2 else {}
            if columns:
                stated = columns["new_quantity"] * columns["new_rate"] - (
                    columns["original_quantity"] * columns["original_rate"]
                )
                assert stated == D(cost), "a fixture item must be priced like the service prices it"
            session.add(
                ChangeOrderItem(
                    change_order_id=order.id,
                    description=f"Item {index + 1}",
                    cost_delta=D(cost),
                    sort_order=index,
                    metadata_=item_meta,
                    **columns,
                )
            )
        await session.commit()
        return order


async def _approve(world, order: ChangeOrder, *, mirrors: uuid.UUID | None = None) -> None:
    data = {
        "change_order_id": str(order.id),
        "project_id": str(world.project.id),
        "code": order.code,
        "cost_impact": str(order.cost_impact),
        "currency": "USD",
        "contract_id": str(world.contract.id),
        "variation_order_id": str(mirrors) if mirrors else None,
    }
    await w5._on_changeorder_approved_contract(Event(name="changeorder.approved", data=data))


async def _state(world):
    async with world.factory() as session:
        contract = await session.get(Contract, world.contract.id)
        lines = (
            (await session.execute(select(ContractLine).where(ContractLine.contract_id == world.contract.id)))
            .scalars()
            .all()
        )
        adjustments = (
            (await session.execute(select(SovAdjustment).where(SovAdjustment.contract_id == world.contract.id)))
            .scalars()
            .all()
        )
        return D(str(contract.total_value)), {ln.id: ln for ln in lines}, list(adjustments)


def _snapshot(line: ContractLine) -> tuple:
    return tuple(getattr(line, column) for column in LINE_COLUMNS)


async def test_items_that_name_lines_move_those_lines_and_the_rest_share_a_new_line(world) -> None:
    lines = world.lines
    _, before, _ = await _state(world)
    order = await _change_order(
        world,
        "14500",
        [
            ("5000", {"contract_line_id": str(lines["A"].id)}),
            # 20 m3 at 400, picked from the bill position the concrete line bills.
            ("8000", {"boq_position_id": str(world.position)}, _qty("100", "120", "400", "400", "m3")),
            ("1500", {}),
        ],
    )
    await _approve(world, order)

    total, after, adjustments = await _state(world)
    assert total == BASE + D("14500")
    a, b = after[lines["A"].id], after[lines["B"].id]
    assert (a.quantity, a.unit_rate, a.total_value) == (D("1"), D("65000"), D("65000"))
    assert (b.quantity, b.unit_rate, b.total_value) == (D("120"), D("400"), D("48000"))
    [new_line] = [ln for ln in after.values() if ln.id not in before]
    assert new_line.origin == "change_order"
    assert new_line.total_value == D("1500")
    assert new_line.source_key == f"change_order:{order.id}"

    by_line = {adj.contract_line_id: adj for adj in adjustments}
    assert sum((adj.delta_value for adj in adjustments), D("0")) == D("14500")
    assert by_line[a.id].delta_value == D("5000") and by_line[a.id].created_line is False
    assert by_line[b.id].delta_value == D("8000") and by_line[b.id].delta_quantity == D("20")
    assert by_line[new_line.id].created_line is True
    assert {adj.metadata_["allocation"] for adj in adjustments} == {"itemized"}
    assert {adj.source_key for adj in adjustments} == {f"change_order:{order.id}"}

    # Lines nobody named are exactly as they were.
    for code in ("C", "E"):
        assert _snapshot(after[lines[code].id]) == _snapshot(before[lines[code].id])
    # Column C adds up to the contract sum again, and every line prices off
    # quantity x rate, which is what the claim generator bills.
    assert sum((ln.total_value for ln in after.values()), D("0")) == total
    for ln in after.values():
        assert ln.quantity * ln.unit_rate == ln.total_value


async def test_a_replayed_approval_moves_nothing(world) -> None:
    order = await _change_order(world, "5000", [("5000", {"contract_line_id": str(world.lines["A"].id)})])
    await _approve(world, order)
    first_total, first_lines, first_adjustments = await _state(world)
    await _approve(world, order)
    total, lines, adjustments = await _state(world)
    assert total == first_total == BASE + D("5000")
    assert {k: _snapshot(v) for k, v in lines.items()} == {k: _snapshot(v) for k, v in first_lines.items()}
    assert [adj.id for adj in adjustments] == [adj.id for adj in first_adjustments]


async def test_an_amount_other_than_the_items_is_split_pro_rata_and_still_adds_up(world) -> None:
    lines = world.lines
    _, before, _ = await _state(world)
    # Priced at 10,000, approved at 9,000: each line takes 90% of its items.
    order = await _change_order(
        world,
        "9000",
        [
            ("6000", {"contract_line_id": str(lines["A"].id)}),
            ("4000", {"contract_line_id": str(lines["B"].id)}, _qty("100", "110", "400", "400", "m3")),
        ],
    )
    await _approve(world, order)
    total, after, adjustments = await _state(world)
    assert total == BASE + D("9000")
    assert after[lines["A"].id].total_value == D("65400")
    # The item adds 10 m3. 3,600 is 9 m3 at the contract rate, a quantity
    # nobody stated or built, so the concrete line keeps its 100 m3 and the
    # 3,600 sits beside it.
    assert _snapshot(after[lines["B"].id]) == _snapshot(before[lines["B"].id])
    [beside] = [ln for ln in after.values() if ln.id not in before]
    assert beside.total_value == D("3600")
    assert beside.metadata_["adjusts_line_id"] == str(lines["B"].id)
    assert sum((adj.delta_value for adj in adjustments), D("0")) == D("9000")
    assert {adj.metadata_["allocation"] for adj in adjustments} == {"pro_rata"}
    assert sum((ln.total_value for ln in after.values()), D("0")) == total


async def test_a_measured_line_the_change_does_not_divide_gets_a_line_beside_it(world) -> None:
    lines = world.lines
    _, before, _ = await _state(world)
    order = await _change_order(world, "1000", [("1000", {"contract_line_id": str(lines["C"].id)})])
    await _approve(world, order)
    total, after, adjustments = await _state(world)
    # Masonry is not repriced at some rate nobody agreed.
    assert _snapshot(after[lines["C"].id]) == _snapshot(before[lines["C"].id])
    [beside] = [ln for ln in after.values() if ln.id not in before]
    assert beside.total_value == D("1000")
    assert beside.metadata_["adjusts_line_id"] == str(lines["C"].id)
    assert beside.parent_line_id is None
    [adjustment] = adjustments
    assert adjustment.contract_line_id == beside.id
    assert adjustment.metadata_["placement"] == "linked_line"
    assert sum((ln.total_value for ln in after.values()), D("0")) == total


async def test_a_reference_to_another_contracts_line_is_not_followed(world) -> None:
    order = await _change_order(world, "700", [("700", {"contract_line_id": str(uuid.uuid4())})])
    await _approve(world, order)
    total, after, adjustments = await _state(world)
    [adjustment] = adjustments
    assert adjustment.created_line is True
    assert adjustment.delta_value == D("700")
    assert list(adjustment.metadata_["unresolved_items"].values()) == ["line_not_on_contract"]
    assert sum((ln.total_value for ln in after.values()), D("0")) == total


async def test_a_mirrored_change_order_moves_its_lines_once_and_its_variation_posts_nothing(world) -> None:
    vo_id = uuid.uuid4()
    order = await _change_order(world, "5000", [("5000", {"contract_line_id": str(world.lines["A"].id)})])
    await _approve(world, order, mirrors=vo_id)
    data = {
        "project_id": str(world.project.id),
        "vo_id": str(vo_id),
        "contract_id": str(world.contract.id),
        "code": "VO-001",
        "delta_amount": "5000",
        "currency": "USD",
    }
    await w5._on_variation_completed(Event(name="variations.contract_sum.updated", data=data))

    total, after, adjustments = await _state(world)
    assert total == BASE + D("5000")
    [adjustment] = adjustments
    assert adjustment.source_key == f"variation_order:{vo_id}"
    assert adjustment.created_line is False
    assert after[world.lines["A"].id].total_value == D("65000")
    assert len(after) == len(world.lines)


async def test_a_change_order_without_items_still_posts_one_pooled_line(world) -> None:
    order = await _change_order(world, "2500", [])
    await _approve(world, order)
    _, _, adjustments = await _state(world)
    [adjustment] = adjustments
    assert adjustment.created_line is True
    assert adjustment.metadata_["allocation"] == "pooled"


async def test_the_certificate_adds_up_after_a_change_moved_lines(world) -> None:
    register_contracts_validation_rules()
    lines = world.lines
    order = await _change_order(
        world,
        "14500",
        [
            ("5000", {"contract_line_id": str(lines["A"].id)}),
            ("8000", {"boq_position_id": str(world.position)}, _qty("100", "120", "400", "400", "m3")),
            ("1500", {}),
        ],
    )
    await _approve(world, order)
    async with world.factory() as session:
        svc = ContractsService(session)
        claim = ProgressClaim(
            contract_id=world.contract.id,
            claim_number="PC-1",
            currency="USD",
            status="draft",
            period_start="2026-05-01",
            period_end="2026-05-31",
            period_from=date(2026, 5, 1),
            period_to=date(2026, 5, 31),
        )
        session.add(claim)
        await session.flush()
        claim = await svc.auto_generate_claim_lines(
            claim.id, AutoGenerateClaimRequest(completion={str(lines["B"].id): D("50")})
        )
        # Half of the concrete line as the change left it: 120 m3 x 400 / 2.
        assert claim.gross_amount == D("24000")
        application = await svc.build_aia_application(claim.id)
        summary = application["summary"]
        assert summary["change_orders_net"] == D("14500.00")
        scheduled = sum((D(str(row["scheduled_value"])) for row in application["lines"]), D("0"))
        assert scheduled == summary["contract_sum_to_date"] == D("124500.00")
        report = await svc.validate_claim(claim.id)
        assert report["errors"] == []
        assert not [w for w in report["warnings"] if w["rule_id"] == "pay_application.sov_reconciles_contract_sum"]
        await session.rollback()


async def test_a_deduction_below_what_was_billed_blocks_the_next_claim(world) -> None:
    register_contracts_validation_rules()
    line_a = world.lines["A"]
    async with world.factory() as session:
        svc = ContractsService(session)
        march = ProgressClaim(
            contract_id=world.contract.id,
            claim_number="PC-1",
            currency="USD",
            status="draft",
            period_start="2026-03-01",
            period_end="2026-03-31",
            period_from=date(2026, 3, 1),
            period_to=date(2026, 3, 31),
        )
        session.add(march)
        await session.flush()
        await svc.auto_generate_claim_lines(march.id, AutoGenerateClaimRequest(completion={str(line_a.id): D("100")}))
        await svc.transition_claim(march.id, "submitted")
        await session.commit()

    # The owner takes 5,000 off general conditions that were billed in full.
    order = await _change_order(world, "-5000", [("-5000", {"contract_line_id": str(line_a.id)})])
    await _approve(world, order)
    _, after, _ = await _state(world)
    assert after[line_a.id].total_value == D("55000")

    async with world.factory() as session:
        svc = ContractsService(session)
        april = ProgressClaim(
            contract_id=world.contract.id,
            claim_number="PC-2",
            currency="USD",
            status="draft",
            period_start="2026-04-01",
            period_end="2026-04-30",
            period_from=date(2026, 4, 1),
            period_to=date(2026, 4, 30),
        )
        session.add(april)
        await session.flush()
        await svc.auto_generate_claim_lines(april.id, AutoGenerateClaimRequest(completion={str(line_a.id): D("100")}))
        report = await svc.validate_claim(april.id)
        assert [e for e in report["errors"] if e["rule_id"] == "pay_application.line_overbilled"]
        await session.rollback()


async def test_the_reconcile_preview_shows_the_split_the_apply_posts(world) -> None:
    lines = world.lines
    order = await _change_order(
        world,
        "6500",
        [("5000", {"contract_line_id": str(lines["A"].id)}), ("1500", {})],
    )
    # Approved before the poster existed: the sum moved, no line did.
    async with world.factory() as session:
        contract = await session.get(Contract, world.contract.id)
        contract.total_value = BASE + D("6500")
        contract.metadata_ = {"change_order_ids": [str(order.id)], "change_order_total": "6500"}
        await session.commit()

    async with world.factory() as session:
        svc = ContractsService(session)
        preview = await svc.sov_reconcile_preview(world.contract.id)
        [item] = preview["items"]
        assert item["allocation_method"] == "itemized"
        shown = {row["contract_line_id"]: (D(row["delta"]), row["placement"]) for row in item["allocation"]}
        assert shown == {str(lines["A"].id): (D("5000"), "lump_sum"), None: (D("1500"), "new_line")}

        result = await svc.sov_reconcile_apply(world.contract.id, [item["source_key"]], actor_id=str(world.user.id))
        assert result["posted"] == 1
        await session.commit()

    total, after, adjustments = await _state(world)
    posted = {(str(adj.contract_line_id) if not adj.created_line else None): adj.delta_value for adj in adjustments}
    assert posted == {str(lines["A"].id): D("5000"), None: D("1500")}
    assert after[lines["A"].id].total_value == D("65000")
    assert all("reconciled_at" in adj.metadata_ and "allocation" in adj.metadata_ for adj in adjustments)
    assert sum((ln.total_value for ln in after.values()), D("0")) == total


async def _legacy(world, orders: list[ChangeOrder]) -> None:
    """Changes approved before the poster existed: the sum moved, no line did."""
    added = sum((D(str(order.cost_impact)) for order in orders), D("0"))
    async with world.factory() as session:
        contract = await session.get(Contract, world.contract.id)
        contract.total_value = BASE + added
        contract.metadata_ = {
            "change_order_ids": [str(order.id) for order in orders],
            "change_order_total": str(added),
        }
        await session.commit()


async def test_two_changes_on_one_line_preview_the_figures_the_apply_writes(world) -> None:
    line_a = world.lines["A"]
    first = await _change_order(world, "5000", [("5000", {"contract_line_id": str(line_a.id)})])
    second = await _change_order(world, "3000", [("3000", {"contract_line_id": str(line_a.id)})])
    await _legacy(world, [first, second])

    async with world.factory() as session:
        svc = ContractsService(session)
        preview = await svc.sov_reconcile_preview(world.contract.id)
        # The apply posts in the order the preview lists, each against the
        # line the ones before it moved.
        shown = [
            (D(row["total_before"]), D(row["total_after"]))
            for item in preview["items"]
            for row in item["allocation"]
            if row["contract_line_id"] == str(line_a.id)
        ]
        # Which change comes first follows the source key; either way the
        # second starts where the first ended and ends where the apply does.
        assert len(shown) == 2
        assert shown[0][0] == D("60000")
        assert shown[0][1] in (D("65000"), D("63000"))
        assert shown[1][0] == shown[0][1]
        last_shown = shown[1][1]
        keys = [item["source_key"] for item in preview["items"]]
        await svc.sov_reconcile_apply(world.contract.id, keys, actor_id=str(world.user.id))
        await session.commit()

    total, after, adjustments = await _state(world)
    assert after[line_a.id].total_value == last_shown == D("68000")
    assert sum((adj.delta_value for adj in adjustments), D("0")) == D("8000")
    assert sum((ln.total_value for ln in after.values()), D("0")) == total


async def test_the_reconcile_preview_reads_the_same_number_of_times_for_one_change_or_three(world) -> None:
    line_a = world.lines["A"]
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    async def preview_reads() -> tuple[int, int]:
        statements.clear()
        event.listen(world.engine.sync_engine, "before_cursor_execute", count)
        try:
            async with world.factory() as session:
                preview = await ContractsService(session).sov_reconcile_preview(world.contract.id)
        finally:
            event.remove(world.engine.sync_engine, "before_cursor_execute", count)
        return len(statements), len(preview["items"])

    orders = [await _change_order(world, "1000", [("1000", {"contract_line_id": str(line_a.id)})])]
    await _legacy(world, orders)
    one, offered = await preview_reads()
    assert offered == 1

    for _ in range(2):
        orders.append(
            await _change_order(
                world,
                "2000",
                [("1500", {"contract_line_id": str(line_a.id)}), ("500", {})],
            )
        )
    await _legacy(world, orders)
    three, offered = await preview_reads()
    assert offered == 3
    assert three == one


async def test_a_variation_completed_before_its_mirror_moves_the_same_lines(world) -> None:
    # The other order of test_a_mirrored_change_order_moves_its_lines_once...:
    # the variation completes first and the mirror is approved afterwards.
    # The schedule must come out the same either way.
    vo_id = uuid.uuid4()
    line_a = world.lines["A"]
    order = await _change_order(world, "5000", [("5000", {"contract_line_id": str(line_a.id)})], mirrors=vo_id)
    data = {
        "project_id": str(world.project.id),
        "vo_id": str(vo_id),
        "contract_id": str(world.contract.id),
        "code": "VO-001",
        "delta_amount": "5000",
        "currency": "USD",
    }
    await w5._on_variation_completed(Event(name="variations.contract_sum.updated", data=data))
    await _approve(world, order, mirrors=vo_id)

    total, after, adjustments = await _state(world)
    assert total == BASE + D("5000")
    [adjustment] = adjustments
    assert adjustment.source_key == f"variation_order:{vo_id}"
    assert adjustment.source_kind == "variation_order"
    assert adjustment.created_line is False
    assert adjustment.metadata_["allocation"] == "itemized"
    assert after[line_a.id].total_value == D("65000")
    # No pooled "VO-001" line.
    assert len(after) == len(world.lines)


async def test_a_variation_whose_mirror_lives_in_another_project_is_pooled(world) -> None:
    vo_id = uuid.uuid4()
    async with world.factory() as session:
        other = Project(name="Elsewhere", owner_id=world.user.id, currency="USD", country_code="US")
        session.add(other)
        await session.flush()
        stray = ChangeOrder(
            project_id=other.id,
            code="CO-X",
            title="Stray",
            status="approved",
            cost_impact=D("5000"),
            currency="USD",
            metadata_={"variation_order_id": str(vo_id)},
        )
        session.add(stray)
        await session.flush()
        session.add(
            ChangeOrderItem(
                change_order_id=stray.id,
                description="Names our line",
                cost_delta=D("5000"),
                metadata_={"contract_line_id": str(world.lines["A"].id)},
            )
        )
        await session.commit()
    data = {
        "project_id": str(world.project.id),
        "vo_id": str(vo_id),
        "contract_id": str(world.contract.id),
        "code": "VO-002",
        "delta_amount": "5000",
        "currency": "USD",
    }
    await w5._on_variation_completed(Event(name="variations.contract_sum.updated", data=data))
    _, after, adjustments = await _state(world)
    [adjustment] = adjustments
    assert adjustment.created_line is True
    assert adjustment.metadata_["allocation"] == "pooled"
    assert after[world.lines["A"].id].total_value == D("60000")


# ── A measured contract bills quantity x rate: the rate must not move ─────


async def _bill(world, measurements: dict) -> Decimal:
    async with world.factory() as session:
        svc = ContractsService(session)
        claim = ProgressClaim(
            contract_id=world.contract.id,
            claim_number=f"PC-{uuid.uuid4().hex[:4]}",
            currency="USD",
            status="draft",
            period_start="2026-05-01",
            period_end="2026-05-31",
            period_from=date(2026, 5, 1),
            period_to=date(2026, 5, 31),
        )
        session.add(claim)
        await session.flush()
        claim = await svc.auto_generate_claim_lines(
            claim.id, AutoGenerateClaimRequest(measurements={str(key): D(value) for key, value in measurements.items()})
        )
        gross = D(str(claim.gross_amount))
        await session.rollback()
        return gross


async def test_a_change_on_a_remeasurement_contract_is_billed_at_the_agreed_rates(measured) -> None:
    lines = measured.lines
    _, before, _ = await _state(measured)
    order = await _change_order(
        measured,
        "10000",
        [
            # 50 m3 of provisional rock at its rate of 80.
            ("4000", {"contract_line_id": str(lines["R"].id)}, _qty("0", "50", "0", "80", "m3")),
            # One more pump.
            ("5000", {"contract_line_id": str(lines["P"].id)}, _qty("1", "2", "5000", "5000", "pcs")),
            # Excavation repriced from 50 to 60 a m3, quantity unchanged.
            ("1000", {"contract_line_id": str(lines["X"].id)}, _qty("100", "100", "50", "60", "m3")),
        ],
    )
    await _approve(measured, order)
    total, after, adjustments = await _state(measured)
    assert total == MEASURED_BASE + D("10000")
    assert sum((adj.delta_value for adj in adjustments), D("0")) == D("10000")
    assert sum((ln.total_value for ln in after.values()), D("0")) == total

    rock, pump, dig = after[lines["R"].id], after[lines["P"].id], after[lines["X"].id]
    assert (rock.quantity, rock.unit_rate, rock.total_value) == (D("50"), D("80"), D("4000"))
    assert (pump.quantity, pump.unit_rate, pump.total_value) == (D("2"), D("5000"), D("10000"))
    # The rate change is not 20 m3 nobody dug: excavation keeps 100 m3 at 50.
    assert _snapshot(dig) == _snapshot(before[lines["X"].id])
    [uplift] = [ln for ln in after.values() if ln.id not in before]
    assert uplift.total_value == D("1000")
    assert uplift.metadata_["adjusts_line_id"] == str(lines["X"].id)
    assert _snapshot(after[lines["G"].id]) == _snapshot(before[lines["G"].id])

    # 50 m3 of rock at 80, not at 4,000 a m3.
    assert await _bill(measured, {lines["R"].id: "50"}) == D("4000")
    # Two pumps at 5,000, not at 10,000 each.
    assert await _bill(measured, {lines["P"].id: "2"}) == D("10000")
    # The 100 m3 dug at 50, plus the uplift billed once on its own line.
    assert await _bill(measured, {lines["X"].id: "100", uplift.id: "1"}) == D("6000")


async def test_a_change_without_quantities_never_restates_a_measured_rate(measured) -> None:
    lines = measured.lines
    _, before, _ = await _state(measured)
    order = await _change_order(
        measured,
        "9000",
        [
            ("4000", {"contract_line_id": str(lines["R"].id)}),
            ("5000", {"contract_line_id": str(lines["P"].id)}),
        ],
    )
    await _approve(measured, order)
    _, after, adjustments = await _state(measured)
    # Neither becomes "1 unit at the change amount": measuring 50 m3 of rock
    # would bill 200,000, and measuring two pumps 20,000.
    for code in ("R", "P"):
        assert _snapshot(after[lines[code].id]) == _snapshot(before[lines[code].id])
    beside = {ln.metadata_["adjusts_line_id"]: ln.total_value for ln in after.values() if ln.id not in before}
    assert beside == {str(lines["R"].id): D("4000"), str(lines["P"].id): D("5000")}
    assert {adj.metadata_["placement"] for adj in adjustments} == {"linked_line"}
    assert await _bill(measured, {lines["R"].id: "50"}) == D("4000")


async def test_a_lump_sum_line_on_a_remeasurement_contract_moves_in_money(measured) -> None:
    line_g = measured.lines["G"]
    order = await _change_order(measured, "2000", [("2000", {"contract_line_id": str(line_g.id)})])
    await _approve(measured, order)
    _, after, _ = await _state(measured)
    site = after[line_g.id]
    assert (site.quantity, site.unit_rate, site.total_value) == (D("1"), D("7000"), D("7000"))
    assert await _bill(measured, {line_g.id: "1"}) == D("7000")
