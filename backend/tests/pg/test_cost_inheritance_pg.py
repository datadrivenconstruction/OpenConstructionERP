# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost lines inherited down the chain, on real PostgreSQL.

The bill position's cost line (and its split) travels to the scope line, the
award's contract line, the change order item, the supplier invoice line and
the invoice raised from a certified claim. Whatever is left on no cost line
shows in the suspense buckets of cost control, where one action fills what can
inherit and a hand choice off the inherited line needs a reason.

Every figure is read back through the paths the screens use (the committed
figures, the chain report), so a split counted twice shows as a wrong total.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.core.validation.engine import ValidationContext
from app.modules.bid_management.models import Bidder, BidPackage, BidPackageLineItem
from app.modules.bid_management.schemas import BidPackageLinesFromBOQ
from app.modules.bid_management.service import BidManagementService
from app.modules.boq.models import BOQ, Position
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.schemas import ChangeOrderItemCreate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.costmodel.chain_service import CostChainService
from app.modules.costmodel.cost_control_schemas import AssignRequest, AssignTarget
from app.modules.costmodel.cost_control_service import CostControlService
from app.modules.costmodel.inheritance import (
    SOURCE_BID_LINE,
    SOURCE_CONTRACT_LINE,
    SOURCE_INVOICE_LINE,
)
from app.modules.costmodel.inheritance_service import set_vector
from app.modules.costmodel.models import CostLine, LineAllocation, PositionAllocation
from app.modules.costmodel.repository import CostSpineRepository
from app.modules.costmodel.structure_rules import PAYLOAD_KEY as STRUCTURE_PAYLOAD_KEY
from app.modules.costmodel.structure_rules import VectorInheritedRule
from app.modules.costmodel.structure_service import CostStructureService
from app.modules.costmodel.validators import register_costmodel_validation_rules
from app.modules.finance.models import Invoice, InvoiceLineItem
from app.modules.finance.service import FinanceService
from app.modules.notifications import _wave5_cross_module_subscribers as w5
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal
OWNER_ID = uuid.uuid4()


class _NonCommittingSession:
    """The test session with ``commit`` demoted to ``flush``, for the award subscribers."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self) -> None:
        await self._inner.flush()

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _NonCommittingSession:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    register_costmodel_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"inherit-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(session) -> Project:
    project = Project(id=uuid.uuid4(), name="Inheritance", owner_id=OWNER_ID, currency="EUR", fx_rates=[])
    session.add(project)
    await session.flush()
    return project


async def _lines(session, project, *codes: str) -> list[CostLine]:
    made = [CostLine(project_id=project.id, code=code, description=f"Account {code}", currency="EUR") for code in codes]
    session.add_all(made)
    await session.flush()
    return made


async def _bill(session, project, specs: list[tuple[str, str, str, CostLine | None]]) -> list[Position]:
    """Positions ``(ordinal, unit, quantity, cost line)`` in one bill."""
    boq = BOQ(project_id=project.id, name="Bill")
    session.add(boq)
    await session.flush()
    made = []
    for n, (ordinal, unit, qty, line) in enumerate(specs):
        pos = Position(
            boq_id=boq.id,
            ordinal=ordinal,
            description=f"Item {ordinal}",
            unit=unit,
            quantity=qty,
            unit_rate="10",
            total=str(D(qty) * 10),
            sort_order=n,
            cost_line_id=line.id if line else None,
        )
        session.add(pos)
        made.append(pos)
    await session.flush()
    return made


async def _split(session, project, position: Position, shares: list[tuple[CostLine, str]]) -> None:
    for line, share in shares:
        session.add(
            PositionAllocation(
                project_id=project.id,
                boq_id=position.boq_id,
                position_id=position.id,
                cost_line_id=line.id,
                mode="percent",
                share=D(share),
            )
        )
    await session.flush()


async def _shares(session, source_type: str, source_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    rows = await session.execute(
        select(LineAllocation.cost_line_id, LineAllocation.share).where(
            LineAllocation.source_type == source_type, LineAllocation.source_id == source_id
        )
    )
    return {lid: D(str(share)) for lid, share in rows.all()}


async def _contract(session, project, *, value: str = "0", status: str = "active", **kw) -> Contract:
    contract = Contract(
        id=uuid.uuid4(),
        code=f"SC-{uuid.uuid4().hex[:6]}",
        title="Shell works",
        project_id=project.id,
        contract_type=kw.pop("contract_type", "lump_sum"),
        counterparty_type=kw.pop("counterparty_type", "subcontractor"),
        currency="EUR",
        total_value=D(value),
        original_contract_value=D(value),
        retention_percent=D(kw.pop("retention", "0")),
        status=status,
        terms={},
        **kw,
    )
    session.add(contract)
    await session.flush()
    return contract


async def _contract_line(session, contract, *, value: str, cost_line=None, **meta) -> ContractLine:
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code=f"L{uuid.uuid4().hex[:4]}",
        description="Schedule line",
        unit="m3",
        quantity=D("10"),
        unit_rate=D(value) / 10,
        total_value=D(value),
        cost_line_id=cost_line.id if cost_line else None,
        metadata_=dict(meta),
    )
    session.add(line)
    await session.flush()
    return line


def _bucket(report: dict, kind: str) -> dict:
    return next(b for b in report["buckets"] if b["kind"] == kind)


# ── The award carries the position's split to the scope line and the contract line ──


async def test_scope_lines_and_the_award_contract_take_the_positions_split(session, monkeypatch) -> None:
    project = await _project(session)
    walls, floors, roofs = await _lines(session, project, "331", "352", "361")
    wall, slab = await _bill(session, project, [("01.001", "m3", "10", walls), ("01.002", "m2", "5", roofs)])
    await _split(session, project, wall, [(walls, "60"), (floors, "40")])

    package = BidPackage(project_id=project.id, code=f"BP-{uuid.uuid4().hex[:6]}", title="Shell", currency="EUR")
    session.add(package)
    await session.flush()
    scope = await BidManagementService(session).add_lines_from_boq(
        package.id, BidPackageLinesFromBOQ(position_ids=[wall.id, slab.id])
    )
    by_pos = {ln.boq_position_id: ln for ln in scope}
    assert by_pos[wall.id].cost_line_id == walls.id, "the main line is the largest share"
    assert await _shares(session, SOURCE_BID_LINE, by_pos[wall.id].id) == {walls.id: D("60"), floors.id: D("40")}
    assert by_pos[slab.id].cost_line_id == roofs.id
    assert await _shares(session, SOURCE_BID_LINE, by_pos[slab.id].id) == {}

    bidder = Bidder(package_id=package.id, company_name="Sample Builders Ltd", status="active")
    session.add(bidder)
    await session.flush()
    monkeypatch.setattr(w5, "async_session_factory", lambda: _NonCommittingSession(session))
    await w5._on_bid_package_awarded(
        w5.Event(
            name="bid_management.package.awarded",
            data={
                "package_id": str(package.id),
                "project_id": str(project.id),
                "awarded_bidder_id": str(bidder.id),
                "awarded_amount": "1500.00",
                "currency": "EUR",
            },
            source_module="bid_management",
        )
    )
    [contract] = (await session.execute(select(Contract).where(Contract.project_id == project.id))).scalars().all()
    lines = {
        (ln.metadata_ or {}).get("boq_position_id"): ln
        for ln in (await session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id))).scalars()
    }
    wall_line, slab_line = lines[str(wall.id)], lines[str(slab.id)]
    assert (wall_line.cost_line_id, slab_line.cost_line_id) == (walls.id, roofs.id)
    assert wall_line.metadata_["cost_line_source"] == "bid_line"
    assert await _shares(session, SOURCE_CONTRACT_LINE, wall_line.id) == {walls.id: D("60"), floors.id: D("40")}

    # Bound and priced, the commitment lands on each line of the split, exactly once.
    contract.status = "active"
    wall_line.total_value = D("1000.01")
    slab_line.total_value = D("500.00")
    await session.flush()
    committed = await CostSpineRepository(session).committed_by_cost_line(project.id)
    assert committed[str(walls.id)] + committed[str(floors.id)] == D("1000.01")
    assert committed[str(floors.id)] == D("400.00")
    assert committed[str(roofs.id)] == D("500.00")

    # V5 reads the split itself: the frozen shares sit on the position's vector, so the line passes,
    # and once a share is moved to a line the position is not allocated to, it is caught.
    async def v5_refs() -> list[str]:
        payload = await CostStructureService(session).validation_payload(project.id)
        context = ValidationContext(data={STRUCTURE_PAYLOAD_KEY: payload}, metadata={"locale": "en"})
        return [r.element_ref for r in await VectorInheritedRule().validate(context) if not r.passed]

    assert await v5_refs() == []
    moved = (
        await session.execute(
            select(LineAllocation).where(
                LineAllocation.source_type == SOURCE_CONTRACT_LINE,
                LineAllocation.source_id == wall_line.id,
                LineAllocation.cost_line_id == floors.id,
            )
        )
    ).scalar_one()
    moved.cost_line_id = roofs.id
    await session.flush()
    assert await v5_refs() == [str(wall_line.id)]


async def test_a_new_schedule_line_from_the_bill_inherits_and_a_set_line_is_kept(session) -> None:
    project = await _project(session)
    walls, other = await _lines(session, project, "331", "399")
    [wall] = await _bill(session, project, [("02.001", "m3", "4", walls)])
    contract = await _contract(session, project, value="400", status="draft")
    from app.modules.contracts.schemas import ContractLineCreate

    svc = ContractsService(session)
    inherited = await svc.create_line(
        ContractLineCreate(
            contract_id=contract.id,
            code="A",
            description="Walls",
            quantity=D("4"),
            unit_rate=D("100"),
            total_value=D("400"),
            metadata={"boq_position_id": str(wall.id)},
        )
    )
    assert inherited.cost_line_id == walls.id
    assert inherited.metadata_["cost_line_source"] == "position"

    chosen = ContractLine(
        contract_id=contract.id, code="B", description="Extra", total_value=D("50"), cost_line_id=other.id
    )
    session.add(chosen)
    await session.flush()
    from app.modules.costmodel.inheritance_service import inherit_contract_lines

    assert await inherit_contract_lines(session, contract) == 0
    assert chosen.cost_line_id == other.id


# ── Change order items ─────────────────────────────────────────────────


async def test_a_change_item_inherits_and_an_override_needs_a_reason(session) -> None:
    project = await _project(session)
    walls, contingency = await _lines(session, project, "331", "900")
    contract = await _contract(session, project, value="1000")
    line = await _contract_line(session, contract, value="1000", cost_line=walls)
    order = ChangeOrder(
        project_id=project.id,
        code="CO-001",
        title="Thicker walls",
        status="draft",
        currency="EUR",
        metadata_={"contract_id": str(contract.id)},
    )
    session.add(order)
    await session.flush()
    svc = ChangeOrderService(session)

    named = await svc.add_item(
        order.id,
        ChangeOrderItemCreate(
            description="Wall +5 cm", new_quantity="2", new_rate="100", metadata={"contract_line_id": str(line.id)}
        ),
    )
    assert (named.cost_line_id, named.cost_line_source) == (walls.id, "contract_line")

    # No reference at all: the contract's one costed line is the default.
    loose = await svc.add_item(order.id, ChangeOrderItemCreate(description="Site cleaning", new_quantity="1"))
    assert (loose.cost_line_id, loose.cost_line_source) == (walls.id, "contract")

    with pytest.raises(HTTPException) as exc:
        await svc.add_item(
            order.id,
            ChangeOrderItemCreate(description="Risk", new_quantity="1", new_rate="10", cost_line_id=contingency.id),
            actor_id=str(OWNER_ID),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["problem"] == "override_reason_required"

    moved = await svc.add_item(
        order.id,
        ChangeOrderItemCreate(
            description="Risk",
            new_quantity="1",
            new_rate="10",
            cost_line_id=contingency.id,
            cost_line_reason="Client asked to carry it as contingency",
        ),
        actor_id=str(OWNER_ID),
    )
    assert (moved.cost_line_id, moved.cost_line_source) == (contingency.id, "manual")
    audit = moved.metadata_["cost_line_override"]
    assert audit["inherited"] == str(walls.id) and audit["by"] == str(OWNER_ID)
    assert audit["reason"].startswith("Client asked")

    # Back to what it inherits, and the audit goes with the override.
    back = await set_vector(
        session,
        project.id,
        kind="change_order_item",
        target_id=moved.id,
        mode="inherit",
        cost_line_id=None,
        reason=None,
        user_id=str(OWNER_ID),
    )
    assert back["cost_line_id"] == str(walls.id)


# ── Invoice lines ──────────────────────────────────────────────────────


async def _invoice(session, project, *, number: str = "SUP-100", net: str = "300", **kw) -> Invoice:
    invoice = Invoice(
        project_id=project.id,
        invoice_direction="payable",
        invoice_number=number,
        invoice_date="2026-04-01",
        currency_code="EUR",
        amount_subtotal=D(net),
        amount_total=D(net),
        status=kw.pop("status", "pending"),
        **kw,
    )
    session.add(invoice)
    await session.flush()
    return invoice


async def test_a_supplier_invoice_line_takes_the_schedule_lines_split_and_refuses_a_conflict(session) -> None:
    from app.modules.costmodel.inheritance_service import resolve_invoice_contract_lines, split_invoice_lines
    from app.modules.finance.schemas import InvoiceLineItemCreate

    project = await _project(session)
    walls, floors, other = await _lines(session, project, "331", "352", "399")
    [wall] = await _bill(session, project, [("03.001", "m3", "10", walls)])
    await _split(session, project, wall, [(walls, "75"), (floors, "25")])
    contract = await _contract(session, project, value="1000")
    line = await _contract_line(session, contract, value="1000", boq_position_id=str(wall.id))
    from app.modules.costmodel.inheritance_service import inherit_contract_lines

    await inherit_contract_lines(session, contract)

    data = InvoiceLineItemCreate(description="Walls, first part", amount="300", contract_line_id=line.id)
    await resolve_invoice_contract_lines(session, project.id, [data])
    assert data.cost_line_id == walls.id

    clash = InvoiceLineItemCreate(description="Walls", amount="1", contract_line_id=line.id, cost_line_id=other.id)
    with pytest.raises(HTTPException) as exc:
        await resolve_invoice_contract_lines(session, project.id, [clash])
    assert exc.value.detail["problem"] == "cost_line_conflicts_with_contract_line"

    foreign_project = await _project(session)
    with pytest.raises(HTTPException) as exc:
        await resolve_invoice_contract_lines(
            session, foreign_project.id, [InvoiceLineItemCreate(description="x", contract_line_id=line.id)]
        )
    assert exc.value.detail["problem"] == "contract_line_not_in_project"

    invoice = await _invoice(session, project, metadata_={"contract_id": str(contract.id)})
    item = InvoiceLineItem(
        invoice_id=invoice.id, description="Walls", amount=D("300"), cost_line_id=walls.id, contract_line_id=line.id
    )
    session.add(item)
    await session.flush()
    assert await split_invoice_lines(session, project.id, invoice.id) == 1
    assert await _shares(session, SOURCE_INVOICE_LINE, item.id) == {walls.id: D("75"), floors.id: D("25")}


async def test_the_invoice_from_a_certified_claim_lands_on_the_schedule_lines_account(session) -> None:
    project = await _project(session)
    [walls] = await _lines(session, project, "331")
    contract = await _contract(session, project, value="60000", counterparty_type="client", retention="10")
    line = await _contract_line(session, contract, value="60000", cost_line=walls)
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-1",
        period_start="2026-03-01",
        period_end="2026-03-28",
        period_from=date(2026, 3, 1),
        period_to=date(2026, 3, 28),
        status="draft",
        currency="EUR",
    )
    session.add(claim)
    await session.flush()
    svc = ContractsService(session)
    claim = await svc.auto_generate_claim_lines(
        claim.id, AutoGenerateClaimRequest(completion={str(line.id): Decimal("40")})
    )
    for target in ("submitted", "approved", "certified"):
        claim = await svc.transition_claim(claim.id, target, actor_id=str(OWNER_ID))

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    items = (
        (await session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id))).scalars().all()
    )
    billed = [i for i in items if i.contract_line_id == line.id]
    assert billed, "the claim line's schedule line is on the invoice line"
    assert {i.cost_line_id for i in billed} == {walls.id}


# ── Suspense, inherit all, lump sum account, direct cost ───────────────


async def test_suspense_lists_what_is_unassigned_and_inherit_fills_what_it_can(session) -> None:
    project = await _project(session)
    walls, roofs = await _lines(session, project, "331", "361")
    [wall] = await _bill(session, project, [("04.001", "m3", "10", walls)])
    contract = await _contract(session, project, value="700")
    # Written straight to the table, the way rows from before this release look.
    can = await _contract_line(session, contract, value="500", boq_position_id=str(wall.id))
    cannot = await _contract_line(session, contract, value="200")

    chain = CostChainService(session)
    report = await chain.report(project.id, locale="en")
    bucket = _bucket(report, "contract_line")
    assert (bucket["count"], bucket["amount"], bucket["inheritable"], bucket["in_report"]) == (2, D("700"), 1, True)
    assert {(i["id"], i["can_inherit"]) for i in bucket["items"]} == {(str(can.id), True), (str(cannot.id), False)}

    assert (await chain.inherit_missing(project.id))["contract_line"] == 1
    await session.refresh(can)
    assert can.cost_line_id == walls.id

    # The last one by hand: nothing above it names a line, so no reason is asked.
    await CostControlService(session).assign(
        project.id,
        AssignRequest(cost_line_id=roofs.id, items=[AssignTarget(kind="contract_line", id=cannot.id)]),
        str(OWNER_ID),
    )
    report = await chain.report(project.id, locale="en")
    assert _bucket(report, "contract_line")["count"] == 0

    # Moving the inherited one off its position's line is an override.
    with pytest.raises(HTTPException) as exc:
        await CostControlService(session).assign(
            project.id,
            AssignRequest(cost_line_id=roofs.id, items=[AssignTarget(kind="contract_line", id=can.id)]),
            str(OWNER_ID),
        )
    assert exc.value.detail["problem"] == "override_reason_required"


async def test_a_lump_sum_contract_without_a_schedule_gets_one_account(session) -> None:
    project = await _project(session)
    [general] = await _lines(session, project, "390")
    contract = await _contract(session, project, value="5000")

    chain = CostChainService(session)
    before = await chain.report(project.id, locale="en")
    assert _bucket(before, "contract")["amount"] == D("5000")
    assert any(f.details.get("problem") == "contract_without_schedule" for f in before["findings"])

    result = await set_vector(
        session,
        project.id,
        kind="contract",
        target_id=contract.id,
        mode="set",
        cost_line_id=general.id,
        reason=None,
        user_id=str(OWNER_ID),
    )
    assert result["lines_created"] == 1
    [line] = (await session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id))).scalars()
    assert (line.cost_line_id, line.total_value, line.unit) == (general.id, D("5000"), "LS")
    assert (await CostSpineRepository(session).committed_by_cost_line(project.id))[str(general.id)] == D("5000")

    after = await chain.report(project.id, locale="en")
    assert _bucket(after, "contract")["count"] == 0
    assert not any(f.details.get("problem") == "contract_without_schedule" for f in after["findings"])


async def test_a_supplier_invoice_without_a_contract_is_recorded_as_a_direct_cost(session) -> None:
    project = await _project(session)
    [general] = await _lines(session, project, "390")
    invoice = await _invoice(session, project, number="SUP-777", net="250.40")
    session.add(InvoiceLineItem(invoice_id=invoice.id, description="Skip hire", amount=D("250.40")))
    await session.flush()

    chain = CostChainService(session)
    before = await chain.report(project.id, locale="en")
    [v15] = [f for f in before["findings"] if f.rule_id == "cost_chain.invoice_has_contract"]
    assert v15.severity == "error" and "SUP-777" in v15.message
    assert _bucket(before, "invoice_line")["in_report"] is False

    made = await chain.direct_cost_contract(project.id, invoice.id, general.id, str(OWNER_ID))
    assert made["contract_code"] == "DC-SUP-777"
    contract = await session.get(Contract, uuid.UUID(made["contract_id"]))
    assert (contract.status, contract.contract_type, contract.total_value) == ("active", "lump_sum", D("250.40"))
    [item] = (await session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id))).scalars()
    assert (str(item.contract_line_id), item.cost_line_id) == (made["contract_line_id"], general.id)

    after = await chain.report(project.id, locale="en")
    assert not any(f.rule_id == "cost_chain.invoice_has_contract" for f in after["findings"])
    assert _bucket(after, "invoice_line")["count"] == 0

    with pytest.raises(HTTPException) as exc:
        await chain.direct_cost_contract(project.id, invoice.id, general.id, str(OWNER_ID))
    assert exc.value.status_code == 409


async def test_rows_of_another_project_are_not_found(session) -> None:
    project = await _project(session)
    other = await _project(session)
    [line_here] = await _lines(session, project, "331")
    contract = await _contract(session, other, value="10")
    with pytest.raises(HTTPException) as exc:
        await set_vector(
            session,
            project.id,
            kind="contract",
            target_id=contract.id,
            mode="set",
            cost_line_id=line_here.id,
            reason=None,
            user_id=None,
        )
    assert exc.value.status_code == 404
    # And a cost line of another project is not a target either.
    [line_there] = await _lines(session, other, "331")
    with pytest.raises(HTTPException) as exc:
        await set_vector(
            session,
            other.id,
            kind="contract",
            target_id=contract.id,
            mode="set",
            cost_line_id=line_here.id,
            reason=None,
            user_id=None,
        )
    assert exc.value.status_code == 404
    assert line_there.project_id == other.id


async def test_scope_line_ids_survive_the_round_trip(session) -> None:
    """The scope line response names its cost line, so the bid screen can show it."""
    from app.modules.bid_management.schemas import BidPackageLineItemResponse

    project = await _project(session)
    [walls] = await _lines(session, project, "331")
    [wall] = await _bill(session, project, [("05.001", "m3", "1", walls)])
    package = BidPackage(project_id=project.id, code=f"BP-{uuid.uuid4().hex[:6]}", title="Shell", currency="EUR")
    session.add(package)
    await session.flush()
    [scope] = await BidManagementService(session).add_lines_from_boq(
        package.id, BidPackageLinesFromBOQ(position_ids=[wall.id])
    )
    row = await session.get(BidPackageLineItem, scope.id)
    assert BidPackageLineItemResponse.model_validate(row).cost_line_id == walls.id
