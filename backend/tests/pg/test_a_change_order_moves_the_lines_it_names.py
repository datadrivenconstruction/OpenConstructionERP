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
from sqlalchemy import select
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
                contract_type="lump_sum",
                status="active",
                currency="USD",
                total_value=BASE,
                original_contract_value=BASE,
                retention_percent=D("10"),
            )
            session.add(contract)
            await session.flush()
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
                factory=factory, project=project, contract=contract, user=user, lines=lines, position=position
            )


async def _change_order(world, cost_impact: str, items: list[tuple[str, dict]]) -> ChangeOrder:
    async with world.factory() as session:
        order = ChangeOrder(
            project_id=world.project.id,
            code=f"CO-{uuid.uuid4().hex[:4]}",
            title="Owner change",
            status="approved",
            cost_impact=D(cost_impact),
            currency="USD",
            metadata_={"contract_id": str(world.contract.id)},
        )
        session.add(order)
        await session.flush()
        for index, (cost, meta) in enumerate(items):
            session.add(
                ChangeOrderItem(
                    change_order_id=order.id,
                    description=f"Item {index + 1}",
                    cost_delta=D(cost),
                    sort_order=index,
                    metadata_=meta,
                )
            )
        await session.commit()
        return order


async def _approve(world, order: ChangeOrder) -> None:
    data = {
        "change_order_id": str(order.id),
        "project_id": str(world.project.id),
        "code": order.code,
        "cost_impact": str(order.cost_impact),
        "currency": "USD",
        "contract_id": str(world.contract.id),
        "variation_order_id": None,
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
            ("8000", {"boq_position_id": str(world.position)}),
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
    # Priced at 10,000, approved at 9,000: each line takes 90% of its items.
    order = await _change_order(
        world,
        "9000",
        [("6000", {"contract_line_id": str(lines["A"].id)}), ("4000", {"contract_line_id": str(lines["B"].id)})],
    )
    await _approve(world, order)
    total, after, adjustments = await _state(world)
    assert total == BASE + D("9000")
    assert after[lines["A"].id].total_value == D("65400")
    # 3,600 is 9 m3 at the contract rate of 400.
    assert (after[lines["B"].id].quantity, after[lines["B"].id].total_value) == (D("109"), D("43600"))
    assert sum((adj.delta_value for adj in adjustments), D("0")) == D("9000")
    assert {adj.metadata_["allocation"] for adj in adjustments} == {"pro_rata"}
    assert len(after) == len(lines)


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
            ("8000", {"boq_position_id": str(world.position)}),
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
