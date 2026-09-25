# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An approved change moves the schedule of values with the contract sum.

The wave-5 subscribers used to move ``Contract.total_value`` and nothing else,
so the lines the claims bill against stopped adding up to G702 line 3 with the
first approval. They now post one pooled line and one adjustment per change,
in the same transaction and under the same source key as the money, so a
replay or the mirrored half of a variation posts nothing.

Changes approved before that are reconciled by a person: the preview lists
them, and the apply posts exactly what the person confirmed.

The handlers are driven directly against a throwaway database, because they
open and commit their own session, as in
``tests/integration/test_variation_mirror_contract_double_post.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.notifications._wave5_cross_module_subscribers as w5
from app.core.events import Event
from app.modules.changeorders.models import ChangeOrder
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, SovAdjustment
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

BASE = Decimal("100000")


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(w5, "async_session_factory", factory)
        async with factory() as session:
            user = User(email=f"sov-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
            session.add(user)
            await session.flush()
            project = Project(name="SoV posting", owner_id=user.id, currency="USD", country_code="US")
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
                retention_percent=Decimal("10"),
            )
            session.add(contract)
            await session.flush()
            session.add(
                ContractLine(
                    contract_id=contract.id,
                    code="A",
                    description="Structure",
                    quantity=Decimal("1"),
                    unit_rate=BASE,
                    total_value=BASE,
                    original_value=BASE,
                )
            )
            await session.commit()
            yield SimpleNamespace(factory=factory, project=project, contract=contract, user=user)


async def _approve_co(world, co_id: uuid.UUID, amount: str, *, currency: str = "USD", mirrors=None) -> None:
    data = {
        "change_order_id": str(co_id),
        "project_id": str(world.project.id),
        "code": "CO-001",
        "cost_impact": amount,
        "currency": currency,
        "contract_id": str(world.contract.id),
        "variation_order_id": str(mirrors) if mirrors else None,
    }
    await w5._on_changeorder_approved_contract(Event(name="changeorder.approved", data=data))


async def _complete_vo(world, vo_id: uuid.UUID, amount: str) -> None:
    data = {
        "project_id": str(world.project.id),
        "vo_id": str(vo_id),
        "contract_id": str(world.contract.id),
        "code": "VO-001",
        "delta_amount": amount,
        "currency": "USD",
    }
    await w5._on_variation_completed(Event(name="variations.contract_sum.updated", data=data))


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
        return Decimal(str(contract.total_value)), lines, adjustments


async def test_an_approved_change_order_posts_one_line_and_a_replay_posts_none(world) -> None:
    co_id = uuid.uuid4()
    await _approve_co(world, co_id, "12500")
    await _approve_co(world, co_id, "12500")

    total, lines, adjustments = await _state(world)
    assert total == BASE + Decimal("12500")
    [adjustment] = adjustments
    assert adjustment.source_key == f"change_order:{co_id}"
    assert adjustment.delta_value == Decimal("12500")
    assert adjustment.created_line is True
    [added] = [ln for ln in lines if ln.origin == "change_order"]
    assert added.id == adjustment.contract_line_id
    assert added.total_value == Decimal("12500")
    assert added.source_key == adjustment.source_key
    # Column C adds up to line 3 again.
    assert sum((ln.total_value for ln in lines), Decimal("0")) == total


async def test_a_completed_variation_posts_once_and_its_mirror_posts_nothing(world) -> None:
    vo_id = uuid.uuid4()
    await _complete_vo(world, vo_id, "8000")
    await _complete_vo(world, vo_id, "8000")
    # The change order that mirrors it is the same commercial change.
    await _approve_co(world, uuid.uuid4(), "8000", mirrors=vo_id)

    total, lines, adjustments = await _state(world)
    assert total == BASE + Decimal("8000")
    [adjustment] = adjustments
    assert adjustment.source_key == f"variation_order:{vo_id}"
    assert [ln.origin for ln in lines if ln.origin != "original"] == ["variation"]


async def test_a_change_in_another_currency_moves_neither_the_sum_nor_the_schedule(world) -> None:
    await _approve_co(world, uuid.uuid4(), "5000", currency="EUR")
    total, lines, adjustments = await _state(world)
    assert total == BASE
    assert len(lines) == 1
    assert adjustments == []


async def test_a_contract_without_a_schedule_gets_no_line_from_a_change(world) -> None:
    # Cost-plus and T&M bill without schedule lines. A lone change order line
    # would become the whole schedule and every claim would be read against it.
    async with world.factory() as session:
        for line in (
            (await session.execute(select(ContractLine).where(ContractLine.contract_id == world.contract.id)))
            .scalars()
            .all()
        ):
            await session.delete(line)
        await session.commit()
    await _approve_co(world, uuid.uuid4(), "4000")

    total, lines, adjustments = await _state(world)
    assert total == BASE + Decimal("4000")
    assert lines == []
    assert adjustments == []
    async with world.factory() as session:
        assert (await ContractsService(session).sov_reconcile_preview(world.contract.id))["items"] == []


async def _legacy_change(world) -> ChangeOrder:
    """A change order approved before the poster: the sum moved, no line did."""
    async with world.factory() as session:
        order = ChangeOrder(
            project_id=world.project.id,
            code="CO-007",
            title="Extra basement waterproofing",
            status="approved",
            cost_impact=Decimal("15000"),
            currency="USD",
            approved_at="2026-05-04T10:00:00+00:00",
            metadata_={"contract_id": str(world.contract.id)},
        )
        session.add(order)
        variation = VariationOrder(
            project_id=world.project.id,
            code="VO-003",
            title="Revised stair core",
            final_cost_impact=Decimal("-2500"),
            currency="USD",
            status="completed",
        )
        session.add(variation)
        await session.flush()
        contract = await session.get(Contract, world.contract.id)
        contract.total_value = BASE + Decimal("12500")
        contract.metadata_ = {
            "change_order_ids": [str(order.id)],
            "change_order_total": "15000",
            "variation_ids": [str(variation.id)],
            "variation_total": "-2500",
        }
        await session.commit()
        return order, variation


async def test_the_reconcile_posts_exactly_what_its_preview_showed(world) -> None:
    order, variation = await _legacy_change(world)
    async with world.factory() as session:
        svc = ContractsService(session)
        preview = await svc.sov_reconcile_preview(world.contract.id)
        assert preview["can_apply"] is True
        assert Decimal(preview["scheduled_total"]) == BASE
        assert Decimal(preview["scheduled_total_after"]) == Decimal(preview["contract_sum"]) == BASE + Decimal("12500")
        keys = [item["source_key"] for item in preview["items"]]
        assert sorted(keys) == sorted([f"change_order:{order.id}", f"variation_order:{variation.id}"])

        # A list that is not the preview posts nothing.
        with pytest.raises(HTTPException) as stale:
            await svc.sov_reconcile_apply(world.contract.id, keys[:1], actor_id=str(world.user.id))
        assert stale.value.status_code == 409
        assert stale.value.detail["error"] == "reconcile_preview_stale"

        after = await svc.sov_reconcile_apply(world.contract.id, keys, actor_id=str(world.user.id))
        assert after["posted"] == 2
        assert after["items"] == []
        await session.commit()

    total, lines, adjustments = await _state(world)
    posted = {a.source_key: a for a in adjustments}
    for item in preview["items"]:
        assert posted[item["source_key"]].delta_value == Decimal(item["amount"])
    assert posted[f"change_order:{order.id}"].approved_on == date(2026, 5, 4)
    assert sum((ln.total_value for ln in lines), Decimal("0")) == total

    # Nothing is posted twice: the change order is already on the schedule.
    async with world.factory() as session:
        again = await ContractsService(session).sov_reconcile_preview(world.contract.id)
        assert again["items"] == [] and again["can_apply"] is False


async def test_a_claim_on_a_schedule_short_of_the_contract_sum_warns_and_points_at_the_reconcile(world) -> None:
    register_contracts_validation_rules()
    await _legacy_change(world)
    async with world.factory() as session:
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
        svc = ContractsService(session)
        report = await svc.validate_claim(claim.id)
        [finding] = [w for w in report["warnings"] if w["rule_id"] == "pay_application.sov_reconciles_contract_sum"]
        assert "Reconcile change orders" in finding["suggestion"]

        keys = [item["source_key"] for item in (await svc.sov_reconcile_preview(world.contract.id))["items"]]
        await svc.sov_reconcile_apply(world.contract.id, keys)
        report = await svc.validate_claim(claim.id)
        assert not [w for w in report["warnings"] if w["rule_id"] == "pay_application.sov_reconciles_contract_sum"]
        await session.rollback()


async def test_a_claim_bills_on_a_schedule_that_carries_a_deductive_change(world) -> None:
    """A deductive variation becomes a negative line; the claim still adds up."""
    register_contracts_validation_rules()
    await _legacy_change(world)
    async with world.factory() as session:
        svc = ContractsService(session)
        keys = [item["source_key"] for item in (await svc.sov_reconcile_preview(world.contract.id))["items"]]
        await svc.sov_reconcile_apply(world.contract.id, keys)
        lines = {
            ln.code: ln
            for ln in (await session.execute(select(ContractLine).where(ContractLine.contract_id == world.contract.id)))
            .scalars()
            .all()
        }
        assert lines["VO-003"].total_value == Decimal("-2500")
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
            claim.id,
            AutoGenerateClaimRequest(
                completion={str(lines["A"].id): Decimal("50"), str(lines["VO-003"].id): Decimal("100")}
            ),
        )
        # Half of the structure, less the deduction taken in full.
        assert claim.gross_amount == Decimal("47500")
        application = await svc.build_aia_application(claim.id)
        assert application["summary"]["current_payment_due"] == Decimal(str(claim.net_due)).quantize(Decimal("0.01"))
        report = await svc.validate_claim(claim.id)
        assert report["errors"] == []
        assert not [w for w in report["warnings"] if w["rule_id"] == "pay_application.sov_reconciles_contract_sum"]
        await session.rollback()


async def test_a_contract_that_is_not_active_is_not_reconciled(world) -> None:
    await _legacy_change(world)
    async with world.factory() as session:
        contract = await session.get(Contract, world.contract.id)
        contract.status = "suspended"
        await session.flush()
        svc = ContractsService(session)
        assert (await svc.sov_reconcile_preview(world.contract.id))["can_apply"] is False
        with pytest.raises(HTTPException) as refused:
            await svc.sov_reconcile_apply(world.contract.id, [])
        assert refused.value.detail["error"] == "contract_not_reconcilable"
        await session.rollback()
