# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The release guard at every guard point outside tendering (SPEC rule 3, INTEGRATION 7).

One item is released at 40,000 EUR (tolerance 2%, ceiling 40,800). Each guard
point then tries to bind 60,000 EUR on a document linked to that item, or, for
a change order and a variation order that are not linked themselves, 5,000 on
top of the item's 40,000 contract. Under ``warn`` the write goes through and a
``guard_warn`` row is on the audit trail; under ``block`` it is refused with
409, nothing moves, and the ``guard_block`` row survives the rollback.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import commitment_guard
from app.modules.commitment_release import guard
from app.modules.commitment_release.guard import check_document, enforcement_of
from tests._pg import isolated_engine
from tests.pg.commitment_fixtures import (
    World,
    add_contract,
    build_world,
    guard_rows,
    link,
    released_item,
    set_enforcement,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    commitment_guard.register_commitment_guard(check_document, enforcement_of)
    try:
        async with isolated_engine() as engine:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            monkeypatch.setattr(guard, "session_factory", factory)
            yield await build_world(factory)
    finally:
        commitment_guard.unregister_commitment_guard()


def _n() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Site:
    """``build`` makes the document and links it; ``act`` runs the guarded write; ``state`` reads its status."""

    build: Callable[[World, uuid.UUID], Awaitable[uuid.UUID]]
    act: Callable[[World, uuid.UUID], Awaitable[None]]
    state: Callable[[World, uuid.UUID], Awaitable[str]]
    before: str
    after: str


async def _get_status(w: World, model: type, doc: uuid.UUID) -> str:
    async with w.factory() as s:
        return (await s.get(model, doc)).status


# ── contract signing ───────────────────────────────────────────────────────


async def _contract_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    cid = await add_contract(w, "60000", status="draft")
    await link(w, iid, "contract", cid)
    return cid


async def _contract_act(w: World, doc: uuid.UUID) -> None:
    from app.modules.contracts.service import ContractsService
    from app.modules.contracts.validators import register_contracts_validation_rules

    register_contracts_validation_rules()
    async with w.factory() as s:
        await ContractsService(s).transition_contract(doc, "active", actor_id=str(w.manager))
        await s.commit()


async def _contract_state(w: World, doc: uuid.UUID) -> str:
    from app.modules.contracts.models import Contract

    return await _get_status(w, Contract, doc)


# ── purchase order approve / issue ─────────────────────────────────────────


async def _po_row(w: World, status: str) -> uuid.UUID:
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    async with w.factory() as s:
        po = PurchaseOrder(
            project_id=w.project_id,
            vendor_contact_id=str(uuid.uuid4()),
            po_number=f"PO-{_n()}",
            po_type="standard",
            issue_date="2026-10-11",
            delivery_date="2026-12-31",
            currency_code="EUR",
            amount_subtotal="60000.00",
            tax_amount="0.00",
            amount_total="60000.00",
            status=status,
        )
        s.add(po)
        await s.flush()
        s.add(
            PurchaseOrderItem(
                po_id=po.id, description="Steel", quantity="600", unit="t", unit_rate="100.00", amount="60000.00"
            )
        )
        await s.commit()
        return po.id


async def _po_draft_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    po = await _po_row(w, "draft")
    await link(w, iid, "purchase_order", po)
    return po


async def _po_approved_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    po = await _po_row(w, "approved")
    await link(w, iid, "purchase_order", po)
    return po


async def _po_approve(w: World, doc: uuid.UUID) -> None:
    from app.modules.procurement.service import ProcurementService

    async with w.factory() as s:
        await ProcurementService(s).approve_po(doc, str(w.manager))
        await s.commit()


async def _po_issue(w: World, doc: uuid.UUID) -> None:
    from app.modules.procurement.service import ProcurementService

    async with w.factory() as s:
        await ProcurementService(s).issue_po(doc)
        await s.commit()


async def _po_state(w: World, doc: uuid.UUID) -> str:
    from app.modules.procurement.models import PurchaseOrder

    return await _get_status(w, PurchaseOrder, doc)


# ── change order approve (unlinked, adds to its contract's item) ───────────


async def _parent_contract(w: World, iid: uuid.UUID) -> uuid.UUID:
    cid = await add_contract(w, "40000", status="active")
    await link(w, iid, "contract", cid)
    return cid


async def _co_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    from app.modules.changeorders.schemas import ChangeOrderCreate
    from app.modules.changeorders.service import ChangeOrderService

    cid = await _parent_contract(w, iid)
    async with w.factory() as s:
        svc = ChangeOrderService(s)
        o = await svc.create_order(
            ChangeOrderCreate(
                project_id=w.project_id,
                title="Extra piling",
                description="",
                cost_impact="5000",
                currency="EUR",
                metadata={"contract_id": str(cid)},
            )
        )
        await svc.submit_order(o.id, str(w.requester))
        await s.commit()
        return o.id


async def _co_act(w: World, doc: uuid.UUID) -> None:
    from app.modules.changeorders.service import ChangeOrderService

    async with w.factory() as s:
        await ChangeOrderService(s).approve_order(doc, str(w.manager))
        await s.commit()


async def _co_state(w: World, doc: uuid.UUID) -> str:
    from app.modules.changeorders.models import ChangeOrder

    return await _get_status(w, ChangeOrder, doc)


# ── variation order complete (unlinked, adds to its contract's item) ───────


async def _vo_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    from app.modules.variations.models import VariationOrder

    cid = await _parent_contract(w, iid)
    async with w.factory() as s:
        vo = VariationOrder(
            project_id=w.project_id,
            code=f"VO-{_n()}",
            title="Revised facade",
            final_cost_impact=Decimal("5000"),
            currency="EUR",
            status="in_progress",
            affected_contract_id=cid,
        )
        s.add(vo)
        await s.commit()
        return vo.id


async def _vo_act(w: World, doc: uuid.UUID) -> None:
    from app.modules.variations.service import VariationsService

    async with w.factory() as s:
        await VariationsService(s).transition_variation_order(doc, "completed", str(w.manager))
        await s.commit()


async def _vo_state(w: World, doc: uuid.UUID) -> str:
    from app.modules.variations.models import VariationOrder

    return await _get_status(w, VariationOrder, doc)


# ── bid management award ───────────────────────────────────────────────────


async def _bid_package_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    from app.modules.bid_management.models import Bidder, BidInvitation, BidPackage, BidSubmission

    async with w.factory() as s:
        pkg = BidPackage(project_id=w.project_id, code=f"BP-{_n()}", currency="EUR", status="closed")
        s.add(pkg)
        await s.flush()
        inv = BidInvitation(package_id=pkg.id, invitee_company_name="Acme")
        bidder = Bidder(package_id=pkg.id, company_name="Acme")
        s.add_all([inv, bidder])
        await s.flush()
        s.add(
            BidSubmission(
                invitation_id=inv.id, bidder_id=bidder.id, total_amount="60000.00", currency="EUR", is_valid=True
            )
        )
        await s.commit()
        pkg_id = pkg.id
    await link(w, iid, "bid_package", pkg_id)
    return pkg_id


async def _bid_package_act(w: World, doc: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.modules.bid_management.models import Bidder
    from app.modules.bid_management.schemas import BidAwardCreate
    from app.modules.bid_management.service import BidManagementService

    async with w.factory() as s:
        bidder = (await s.execute(select(Bidder).where(Bidder.package_id == doc))).scalar_one()
        await BidManagementService(s).award_package(
            doc,
            BidAwardCreate(
                package_id=doc, awarded_bidder_id=bidder.id, awarded_amount=Decimal("60000"), currency="EUR"
            ),
            str(w.manager),
        )
        await s.commit()


async def _bid_package_state(w: World, doc: uuid.UUID) -> str:
    from app.modules.bid_management.models import BidPackage

    return await _get_status(w, BidPackage, doc)


# ── RFQ award ──────────────────────────────────────────────────────────────


async def _rfq_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    from app.modules.rfq_bidding.models import RFQ, RFQBid

    async with w.factory() as s:
        rfq = RFQ(
            project_id=w.project_id,
            rfq_number=f"RFQ-{_n()}",
            title="Formwork",
            currency_code="EUR",
            status="bids_received",
        )
        s.add(rfq)
        await s.flush()
        s.add(
            RFQBid(
                rfq_id=rfq.id,
                bidder_contact_id=str(uuid.uuid4()),
                bid_amount="60000.00",
                currency_code="EUR",
                is_awarded=False,
            )
        )
        await s.commit()
        rfq_id = rfq.id
    await link(w, iid, "rfq", rfq_id)
    return rfq_id


async def _rfq_act(w: World, doc: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.modules.rfq_bidding.models import RFQBid
    from app.modules.rfq_bidding.service import RFQService

    async with w.factory() as s:
        bid = (await s.execute(select(RFQBid).where(RFQBid.rfq_id == doc))).scalar_one()
        await RFQService(s).award_bid(bid.id, actor_id=str(w.manager), actor_role="manager")
        await s.commit()


async def _rfq_state(w: World, doc: uuid.UUID) -> str:
    from app.modules.rfq_bidding.models import RFQ

    return await _get_status(w, RFQ, doc)


# ── variation request converted into an order on a contract ───────────────


async def _vr_build(w: World, iid: uuid.UUID) -> uuid.UUID:
    from app.modules.variations.models import VariationRequest

    await _parent_contract(w, iid)
    async with w.factory() as s:
        vr = VariationRequest(
            project_id=w.project_id,
            code=f"VR-{_n()}",
            title="Revised facade",
            estimated_cost_impact=Decimal("5000"),
            agreed_cost_impact=Decimal("5000"),
            currency="EUR",
            status="approved",
        )
        s.add(vr)
        await s.commit()
        return vr.id


async def _vr_act(w: World, doc: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.modules.commitment_release.models import CommitmentLink
    from app.modules.variations.schemas import VariationOrderCreate
    from app.modules.variations.service import VariationsService

    async with w.factory() as s:
        cid = (
            await s.execute(
                select(CommitmentLink.target_id).where(
                    CommitmentLink.project_id == w.project_id, CommitmentLink.kind == "contract"
                )
            )
        ).scalar_one()
        await VariationsService(s).convert_vr_to_vo(
            doc, VariationOrderCreate(project_id=w.project_id, affected_contract_id=cid), user_id=str(w.manager)
        )
        await s.commit()


async def _vr_state(w: World, doc: uuid.UUID) -> str:
    from app.modules.variations.models import VariationRequest

    return await _get_status(w, VariationRequest, doc)


SITES: dict[str, Site] = {
    "variation_convert": Site(_vr_build, _vr_act, _vr_state, "approved", "converted_to_vo"),
    "contract_sign": Site(_contract_build, _contract_act, _contract_state, "draft", "active"),
    "po_approve": Site(_po_draft_build, _po_approve, _po_state, "draft", "approved"),
    "po_issue": Site(_po_approved_build, _po_issue, _po_state, "approved", "issued"),
    "change_order_approve": Site(_co_build, _co_act, _co_state, "submitted", "approved"),
    "variation_order_complete": Site(_vo_build, _vo_act, _vo_state, "in_progress", "completed"),
    "bid_package_award": Site(_bid_package_build, _bid_package_act, _bid_package_state, "closed", "awarded"),
    "rfq_award": Site(_rfq_build, _rfq_act, _rfq_state, "bids_received", "awarded"),
}


@pytest.mark.parametrize("site", sorted(SITES))
async def test_over_release_is_warned_and_written_under_warn(world: World, site: str) -> None:
    s = SITES[site]
    iid = await released_item(world, "40000")
    doc = await s.build(world, iid)
    await set_enforcement(world, "warn")
    await s.act(world, doc)
    assert await s.state(world, doc) == s.after
    assert await guard_rows(world, doc) == ["guard_warn"]


@pytest.mark.parametrize("site", sorted(SITES))
async def test_over_release_is_refused_under_block_and_the_refusal_is_on_record(world: World, site: str) -> None:
    s = SITES[site]
    iid = await released_item(world, "40000")
    doc = await s.build(world, iid)
    await set_enforcement(world, "block")
    with pytest.raises(HTTPException) as exc:
        await s.act(world, doc)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "commitment_not_released"
    assert await s.state(world, doc) == s.before
    assert await guard_rows(world, doc) == ["guard_block"]


async def test_a_mirrored_change_order_is_left_to_its_variation(world: World) -> None:
    """The variation is the guard point for a mirror; checking the mirror too would count the money twice."""
    from app.modules.changeorders.models import ChangeOrder

    iid = await released_item(world, "40000")
    co = await _co_build(world, iid)
    async with world.factory() as s:
        row = await s.get(ChangeOrder, co)
        row.metadata_ = {**(row.metadata_ or {}), "variation_order_id": str(uuid.uuid4())}
        await s.commit()
    await set_enforcement(world, "block")
    await _co_act(world, co)
    assert await _co_state(world, co) == "approved"
    assert await guard_rows(world, co) == []


async def test_a_client_contract_is_not_a_commitment(world: World) -> None:
    from app.modules.contracts.models import Contract

    iid = await released_item(world, "40000")
    cid = await _contract_build(world, iid)
    async with world.factory() as s:
        (await s.get(Contract, cid)).counterparty_type = "client"
        await s.commit()
    await set_enforcement(world, "block")
    await _contract_act(world, cid)
    assert await _contract_state(world, cid) == "active"
    assert await guard_rows(world, cid) == []


# ── contingency drawdown confirmed for a risk ──────────────────────────────


async def _risk_with_drawdown_item(w: World, released: str) -> tuple[uuid.UUID, uuid.UUID]:
    """An occurred risk, one contingency line of 100,000 and a drawdown item naming the risk, released."""
    from app.modules.finance.models import ProjectBudget
    from app.modules.risk.models import RiskItem
    from tests.pg.commitment_fixtures import decide, item, request

    async with w.factory() as s:
        line = ProjectBudget(
            project_id=w.project_id,
            category="contingency",
            currency_code="EUR",
            original_budget=Decimal("100000"),
            revised_budget=Decimal("100000"),
            metadata_={},
        )
        risk = RiskItem(project_id=w.project_id, code=f"R-{_n()}", title="Ground water", status="occurred")
        s.add_all([line, risk])
        await s.commit()
        line_id, risk_id = line.id, risk.id
    iid = await item(w, code="CR-D", amount=released, ctype="contingency_drawdown", risk_id=risk_id)
    await decide(w, await request(w, iid, released), w.pm)
    return risk_id, line_id


async def _confirm(w: World, risk_id: uuid.UUID, amount: str) -> None:
    from app.modules.risk.schemas import ContingencyDrawdownRequest
    from app.modules.risk.service import RiskService

    async with w.factory() as s:
        await RiskService(s).confirm_contingency_drawdown(
            w.project_id, risk_id, ContingencyDrawdownRequest(amount=Decimal(amount)), user_id=str(w.manager)
        )
        await s.commit()


async def _risk_draw(w: World, line_id: uuid.UUID, risk_id: uuid.UUID) -> str | None:
    from app.modules.finance.models import ProjectBudget

    async with w.factory() as s:
        meta = (await s.get(ProjectBudget, line_id)).metadata_ or {}
    record = meta.get(f"contingency_drawdown:risk:{risk_id}")
    return None if record is None else record["amount"]


async def test_a_risk_drawdown_above_the_release_is_refused_under_block(world: World) -> None:
    """Review finding 15, guard point 7: the drawdown write asked nobody."""
    risk_id, line_id = await _risk_with_drawdown_item(world, "10000")
    await set_enforcement(world, "block")
    with pytest.raises(HTTPException) as exc:
        await _confirm(world, risk_id, "30000")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "commitment_not_released"
    # The approved release already drew its 10,000 for this risk; the refused 30,000 changed nothing.
    assert Decimal(await _risk_draw(world, line_id, risk_id)) == Decimal("10000")
    assert await guard_rows(world, risk_id) == ["guard_block"]


async def test_a_risk_drawdown_within_the_release_is_written(world: World) -> None:
    risk_id, line_id = await _risk_with_drawdown_item(world, "10000")
    await set_enforcement(world, "block")
    await _confirm(world, risk_id, "10000")
    assert Decimal(await _risk_draw(world, line_id, risk_id)) == Decimal("10000")
    assert await guard_rows(world, risk_id) == []
    # The release and the risk's own confirmation are the same money: one record, drawn once.
    assert await _drawn(world, line_id) == {f"contingency_drawdown:risk:{risk_id}": Decimal("10000")}
    await _confirm(world, risk_id, "4000")
    assert await _drawn(world, line_id) == {f"contingency_drawdown:risk:{risk_id}": Decimal("4000")}


async def _drawn(w: World, line_id: uuid.UUID) -> dict[str, Decimal]:
    """Every drawdown record on one contingency line, by its key."""
    from app.modules.finance.models import ProjectBudget

    async with w.factory() as s:
        meta = (await s.get(ProjectBudget, line_id)).metadata_ or {}
    return {k: Decimal(v["amount"]) for k, v in meta.items() if k.startswith("contingency_drawdown:")}


async def test_a_checker_that_breaks_refuses_the_write_on_a_blocking_project(world: World, monkeypatch) -> None:
    """Review finding 15: ``block`` failed open when the check itself raised."""

    async def broken(session, **kw):
        raise RuntimeError("checker broke")

    iid = await released_item(world, "40000")
    cid = await _contract_build(world, iid)
    await set_enforcement(world, "block")
    commitment_guard.register_commitment_guard(broken, enforcement_of)
    with pytest.raises(HTTPException) as exc:
        await _contract_act(world, cid)
    assert exc.value.detail["code"] == "commitment_guard_unavailable"
    assert await _contract_state(world, cid) == "draft"


async def test_a_risk_cannot_reverse_the_drawdown_a_released_item_wrote(world: World) -> None:
    """The record under the risk is the released money; reversing it would leave a release that drew nothing."""
    from sqlalchemy import select

    from app.modules.commitment_release.models import CommitmentItem
    from app.modules.risk.service import RiskService

    risk_id, line_id = await _risk_with_drawdown_item(world, "10000")

    async def reverse() -> None:
        async with world.factory() as s:
            await RiskService(s).reverse_contingency_drawdown(world.project_id, risk_id, user_id=str(world.manager))
            await s.commit()

    with pytest.raises(HTTPException) as exc:
        await reverse()
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "drawdown_released_by_commitment"
    assert exc.value.detail["item_code"] == "CR-D"
    assert await _drawn(world, line_id) == {f"contingency_drawdown:risk:{risk_id}": Decimal("10000")}

    # Once the item no longer stands on a release, the risk takes its record back as before.
    async with world.factory() as s:
        row = (
            await s.execute(select(CommitmentItem).where(CommitmentItem.project_id == world.project_id))
        ).scalar_one()
        row.status = "aborted"
        await s.commit()
    await reverse()
    assert await _drawn(world, line_id) == {}
