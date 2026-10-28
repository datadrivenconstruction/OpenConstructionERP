# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the economics PostgreSQL tests.

A world is a throwaway database with real users and a project that runs
governance on the shipped ``elf_module_framework`` model (one gate
``development_to_execution`` at which every area's frame document is required,
including the commercial area ``m09_commercial``), and a bill of quantities
classified by DIN 276 whose figures the tests know by heart:

    KG 300  330.1  1 000 000
    KG 300  350.1    500 000
    KG 400  410.1    250 000
    (uncoded)         10 000

so the direct cost is 1 760 000 and the bill carries one 10 percent markup.
Everything commits for real, so row locks behave as in production.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.economics.service import EconomicsService
from app.modules.project_governance.service import GovernanceService
from tests.pg.governance_fixtures import World, add_container, add_project, add_route, add_user

GATE = "development_to_execution"
COMMERCIAL_DOC = "m09_commercial_frame"

# (ordinal, description, quantity, unit_rate, din276 code or None)
BILL = [
    ("330.1", "Outer walls", "1000", "1000", "331"),
    ("350.1", "Floor slabs", "500", "1000", "351"),
    ("410.1", "Sanitary installation", "250", "1000", "411"),
    ("990.1", "Site allowance without a code", "10", "1000", None),
]
DIRECT = Decimal("1760000")


async def add_bill(session: AsyncSession, project_id: uuid.UUID, *, name: str = "Cost calculation") -> uuid.UUID:
    from app.modules.boq.models import BOQ, BOQMarkup, Position

    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name=name, status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    for i, (ordinal, text, qty, rate, code) in enumerate(BILL):
        total = Decimal(qty) * Decimal(rate)
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq.id,
                ordinal=ordinal,
                description=text,
                unit="lsum",
                quantity=qty,
                unit_rate=rate,
                total=str(total),
                classification={"din276": code} if code else {},
                sort_order=i,
            )
        )
    session.add(
        BOQMarkup(
            id=uuid.uuid4(),
            boq_id=boq.id,
            name="Project reserve",
            markup_type="percentage",
            category="contingency",
            percentage="10",
            fixed_amount="0",
            apply_to="direct_cost",
            sort_order=0,
            is_active=True,
        )
    )
    await session.flush()
    return boq.id


async def add_commitment(session: AsyncSession, project_id: uuid.UUID, code: str, amount: str) -> None:
    """A purchase order, issued, on a cost line whose control account carries ``code``."""
    from app.modules.costmodel.models import ControlAccount, CostLine
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    account = ControlAccount(project_id=project_id, code=code, name=f"Account {code}", classification_standard="din276")
    session.add(account)
    await session.flush()
    line = CostLine(project_id=project_id, control_account_id=account.id, code=f"CL-{code}", currency="EUR")
    session.add(line)
    po = PurchaseOrder(
        project_id=project_id, po_number=f"PO-{code}", currency_code="EUR", status="issued", metadata_={}
    )
    session.add(po)
    await session.flush()
    session.add(
        PurchaseOrderItem(
            po_id=po.id, description="Supply", quantity="1", unit_rate=amount, amount=amount, cost_line_id=line.id
        )
    )
    await session.flush()


async def build_world(
    factory: async_sessionmaker[AsyncSession], *, governance: bool = True, bill: bool = True
) -> World:
    async with factory() as s:
        manager = await add_user(s, "manager")
        decider = await add_user(s, "manager")
        owner = await add_user(s, "editor")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [decider, owner, editor])
        w = World(factory, pid, manager, decider, owner, editor, outsider)
        if governance:
            w.gate_route_id = await add_route(s, pid, "phase_gate", decider)
            w.change_route_id = await add_route(s, pid, "frame_change", decider)
            await GovernanceService(s).set_model(
                pid,
                source="shipped",
                catalogue_id="elf_module_framework",
                version=None,
                four_eyes=True,
                actor_id=manager,
                tenant_id=str(manager),
            )
            await GovernanceService(s).update_settings(
                pid,
                four_eyes=None,
                decision_route_id=w.gate_route_id,
                change_route_id=w.change_route_id,
                fields_set={"decision_route_id", "change_route_id"},
                actor_id=manager,
            )
            for d in await GovernanceService(s).repo.list_documents(pid):
                w.containers[d.doc_type] = await add_container(s, pid, d.doc_type)
        if bill:
            await add_bill(s, pid)
        await EconomicsService(s).start(pid, manager)
        await s.commit()
    return w


async def call(w: World, fn: str, *args: Any, **kw: Any) -> Any:
    """Run one service method in its own committed session."""
    async with w.factory() as s:
        out = await getattr(EconomicsService(s), fn)(w.project_id, *args, **kw)
        await s.commit()
        return out


async def fill(w: World, *, frame_amounts: tuple[str, str] = ("2000000", "400000")) -> None:
    """A complete, consistent plan: a frame, a business case, and financing that covers it."""
    plan = await call(
        w,
        "patch_plan",
        {"discount_rate_pct": Decimal("4"), "horizon_years": 10, "markup_allowance": Decimal("200000")},
        w.manager,
    )
    assert plan.discount_rate_pct == Decimal("4")
    await call(
        w,
        "add_frame_line",
        {"code": "300", "title": "Building construction", "amount": Decimal(frame_amounts[0])},
        w.manager,
    )
    await call(
        w,
        "add_frame_line",
        {"code": "400", "title": "Building services", "amount": Decimal(frame_amounts[1])},
        w.manager,
    )
    total = Decimal(frame_amounts[0]) + Decimal(frame_amounts[1]) + Decimal("200000")
    await call(
        w,
        "add_flow_line",
        {"kind": "investment", "label": "Construction", "source": "cost_frame", "year_from": 0, "year_to": 2},
        w.manager,
    )
    await call(
        w,
        "add_flow_line",
        {"kind": "revenue", "label": "Rent", "amount": Decimal("400000"), "year_from": 3, "year_to": 10},
        w.manager,
    )
    await call(
        w,
        "add_flow_line",
        {"kind": "operating_cost", "label": "Operation", "amount": Decimal("60000"), "year_from": 3, "year_to": 10},
        w.manager,
    )
    await call(
        w,
        "add_flow_line",
        {"kind": "residual", "label": "Residual value", "amount": Decimal("1500000"), "year_from": 10, "year_to": 10},
        w.manager,
    )
    src = await call(w, "add_source", {"kind": "equity", "name": "Own funds", "amount": total / 2}, w.manager)
    await call(w, "add_tranche", src.id, {"due_on": "2027-01-15", "amount": total / 2}, w.manager)
    loan = await call(
        w,
        "add_source",
        {"kind": "bank_loan", "name": "Construction loan", "amount": total / 2, "interest_rate_pct": Decimal("3.9")},
        w.manager,
    )
    await call(w, "add_tranche", loan.id, {"due_on": "2027-06-30", "amount": total / 2}, w.manager)


async def fill_registers(w: World) -> None:
    """Every register the gate asks about, in place: what a gate needs before it can decide."""
    mgr = w.manager
    await call(
        w,
        "add_security",
        {
            "kind": "performance",
            "description": "Performance guarantee",
            "status": "in_place",
            "valid_until": "2099-12-31",
        },
        mgr,
    )
    await call(
        w,
        "add_insurance",
        {"kind": "liability", "insurer": "Insurer", "status": "in_place", "period_to": "2099-12-31"},
        mgr,
    )
    await call(w, "put_tax", {"vat_treatment": "standard", "input_tax_deduction": True, "confirm": True}, mgr)
    for area in ("receivables", "payables", "administration"):
        await call(w, "put_process", area, {"status": "set_up"}, mgr)
