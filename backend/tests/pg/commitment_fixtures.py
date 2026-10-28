# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the commitment release PostgreSQL tests.

A world is a throwaway database with real users, an EUR project whose own
``fx_rates`` know GBP (1 GBP = 1.20 EUR) and nothing else, team membership, the
shipped ``neutral`` authority schedule pinned (project manager <= 50,000,
sponsor <= 500,000, board <= 5,000,000), one holder per tier and the tier
routes the module generates from them. Everything commits for real, so row
locks and the approval subscriber behave as in production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.commitment_release.events import handle_route_event
from app.modules.commitment_release.service import CommitmentService
from tests.pg.governance_fixtures import add_user


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    pm: uuid.UUID
    sponsor: uuid.UUID
    board: uuid.UUID
    requester: uuid.UUID
    outsider: uuid.UUID


async def add_project(session: AsyncSession, owner: uuid.UUID, members: list[uuid.UUID]) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership

    pid = uuid.uuid4()
    session.add(
        Project(
            id=pid,
            name=f"Cmt {pid.hex[:6]}",
            currency="EUR",
            status="active",
            owner_id=owner,
            metadata_={},
            fx_rates=[{"code": "GBP", "rate": "1.20"}],
        )
    )
    await session.flush()
    team = Team(project_id=pid, name="Owner team")
    session.add(team)
    await session.flush()
    for m in members:
        session.add(TeamMembership(team_id=team.id, user_id=m))
    await session.flush()
    return pid


async def build_world(factory: async_sessionmaker[AsyncSession], today: date = date(2026, 10, 11)) -> World:
    from app.modules.commitment_release.catalogue import register_kinds

    register_kinds()
    async with factory() as s:
        manager = await add_user(s, "manager")
        pm = await add_user(s, "manager")
        sponsor = await add_user(s, "manager")
        board = await add_user(s, "manager")
        requester = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [pm, sponsor, board, requester])
        svc = CommitmentService(s)
        await svc.set_matrix(pid, actor_id=manager, tenant_id=str(manager), schedule_id="neutral")
        await svc.put_assignments(
            pid,
            [
                {"project_role": "owner_pm", "user_id": pm},
                {"project_role": "owner_sponsor", "user_id": sponsor},
                {"project_role": "owner_board_member", "user_id": board},
            ],
            actor_id=manager,
            today=today,
        )
        await s.commit()
    return World(factory, pid, manager, pm, sponsor, board, requester, outsider)


async def item(w: World, code: str = "CR-1", amount: str = "400000", ctype: str = "design", **kw: Any) -> uuid.UUID:
    async with w.factory() as s:
        data = {
            "code": code,
            "title": f"Item {code}",
            "commitment_type": ctype,
            "planned_source": "manual",
            "planned_manual_amount": amount,
            "currency": kw.pop("currency", "EUR"),
            **kw,
        }
        row = await CommitmentService(s).create_item(w.project_id, data, actor_id=w.requester)
        await s.commit()
        return row.id


async def request(
    w: World,
    item_id: uuid.UUID,
    amount: str,
    *,
    actor: uuid.UUID | None = None,
    today: date = date(2026, 10, 11),
    **kw: Any,
):
    async with w.factory() as s:
        d = await CommitmentService(s).request_release(
            w.project_id,
            item_id,
            amount=amount,
            currency=kw.pop("currency", None),
            tranche_note=kw.pop("tranche_note", ""),
            external_approval_ref=kw.pop("external_approval_ref", ""),
            actor_id=actor or w.requester,
            today=today,
            manage=kw.pop("manage", False),
        )
        await s.commit()
        return d


async def decide(w: World, release: Any, decider: uuid.UUID, verdict: str = "approved", comment: str | None = None):
    """Decide the current step in approval_routes, then deliver the terminal event as the subscriber would."""
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService

    async with w.factory() as s:
        svc = ApprovalRouteService(s)
        instance = await svc.get_instance(release.approval_instance_id)
        steps = [
            st for st in await svc.repo.list_steps(instance.route_id) if st.ordinal == instance.current_step_ordinal
        ]
        await svc.submit_decision(
            instance.id,
            DecisionSubmit(step_id=steps[0].id, decision=verdict, comment=comment),
            approver_id=decider,
            caller_role="manager",
        )
        await s.commit()
        instance = await svc.get_instance(release.approval_instance_id)
        status = instance.status
    if status in ("approved", "rejected"):
        await handle_route_event(
            {
                "target_kind": "commitment_release",
                "target_id": str(release.id),
                "instance_id": str(release.approval_instance_id),
                "decided_by": str(decider),
                "comment": comment,
            },
            verdict="approved" if status == "approved" else "rejected",
            session_factory=w.factory,
        )
    return status


async def state(w: World, item_id: uuid.UUID) -> Any:
    from app.modules.commitment_release.models import CommitmentItem

    async with w.factory() as s:
        return await s.get(CommitmentItem, item_id)


async def add_contract(
    w: World,
    value: str,
    *,
    status: str = "active",
    currency: str = "EUR",
    cost_line_id: uuid.UUID | None = None,
    meta: dict | None = None,
) -> uuid.UUID:
    from app.modules.contracts.models import Contract, ContractLine

    async with w.factory() as s:
        c = Contract(
            project_id=w.project_id,
            code=f"SC-{uuid.uuid4().hex[:6]}",
            title="Subcontract",
            counterparty_type="subcontractor",
            total_value=Decimal(value),
            currency=currency,
            status=status,
            metadata_=meta or {},
        )
        s.add(c)
        await s.flush()
        s.add(
            ContractLine(
                # A lump-sum line, so the signing compliance gate sees a complete position.
                contract_id=c.id,
                code="1",
                description="Works",
                unit="lsum",
                quantity=Decimal("1"),
                unit_rate=Decimal(value),
                total_value=Decimal(value),
                cost_line_id=cost_line_id,
            )
        )
        await s.commit()
        return c.id


async def set_contract_value(w: World, contract_id: uuid.UUID, value: str) -> None:
    from sqlalchemy import select

    from app.modules.contracts.models import Contract, ContractLine

    async with w.factory() as s:
        c = await s.get(Contract, contract_id)
        c.total_value = Decimal(value)
        line = (await s.execute(select(ContractLine).where(ContractLine.contract_id == contract_id))).scalar_one()
        line.unit_rate = Decimal(value)
        line.total_value = Decimal(value)
        await s.commit()


async def add_po(
    w: World,
    amount: str,
    *,
    status: str = "issued",
    currency: str = "EUR",
    cost_line_id: uuid.UUID | None = None,
    meta: dict | None = None,
) -> uuid.UUID:
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

    async with w.factory() as s:
        po = PurchaseOrder(
            project_id=w.project_id,
            po_number=f"PO-{uuid.uuid4().hex[:6]}",
            currency_code=currency,
            amount_subtotal=amount,
            amount_total=str(Decimal(amount) * Decimal("1.19")),
            status=status,
            metadata_=meta or {},
        )
        s.add(po)
        await s.flush()
        s.add(PurchaseOrderItem(po_id=po.id, description="Supply", amount=amount, cost_line_id=cost_line_id))
        await s.commit()
        return po.id


async def add_cost_line(w: World, code: str) -> uuid.UUID:
    from app.modules.costmodel.models import CostLine

    async with w.factory() as s:
        cl = CostLine(project_id=w.project_id, code=code, currency="EUR")
        s.add(cl)
        await s.commit()
        return cl.id


async def link(w: World, item_id: uuid.UUID, kind: str, document_id: uuid.UUID) -> None:
    async with w.factory() as s:
        await CommitmentService(s).add_link(w.project_id, item_id, kind, document_id, actor_id=w.requester)
        await s.commit()


async def guard_rows(w: World, document_id: uuid.UUID) -> list[str]:
    """Actions of the guard's audit rows for one document, oldest first."""
    from sqlalchemy import select

    from app.core.audit_log import ActivityLog

    async with w.factory() as s:
        rows = await s.execute(
            select(ActivityLog.action)
            .where(ActivityLog.entity_type == "commitment_guard", ActivityLog.entity_id == str(document_id))
            .order_by(ActivityLog.created_at)
        )
        return list(rows.scalars().all())


async def set_enforcement(w: World, mode: str) -> None:
    async with w.factory() as s:
        await CommitmentService(s).set_matrix(
            w.project_id, actor_id=w.manager, tenant_id=str(w.manager), enforcement=mode
        )
        await s.commit()


async def released_item(w: World, amount: str, *, code: str = "CR-G", ctype: str = "works") -> uuid.UUID:
    """An item released in full by the project manager tier (amounts up to 50,000)."""
    iid = await item(w, code=code, amount=amount, ctype=ctype)
    d = await request(w, iid, amount)
    await decide(w, d, w.pm)
    return iid
