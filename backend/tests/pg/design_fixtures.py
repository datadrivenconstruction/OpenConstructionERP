# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the design management PostgreSQL tests.

A world is the governance world (users, project, team, pinned governance model)
plus a design setup on the ``simple_sequential`` scheme, so a number needs only
a discipline, and one design role per discipline. Everything commits for real.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.design_management.service import DesignService
from tests.pg.governance_fixtures import build_world


@dataclass
class DesignWorld:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    approver: uuid.UUID
    editor: uuid.UUID
    outsider: uuid.UUID
    roles: dict[str, uuid.UUID] = field(default_factory=dict)


async def build_design_world(
    factory: async_sessionmaker[AsyncSession], *, governance: str | None = "neutral"
) -> DesignWorld:
    """``governance`` picks the pinned governance catalogue; only ``elf_module_framework`` has the m07 design area.

    ``None`` pins no phase model at all: a project that does not use gates.
    """
    if governance == "neutral":
        gov = await build_world(factory, routes=False)
        w = DesignWorld(factory, gov.project_id, gov.manager, gov.decider, gov.editor, gov.outsider)
    else:
        from app.modules.project_governance.service import GovernanceService
        from tests.pg.governance_fixtures import add_project, add_user

        async with factory() as s:
            manager, approver = await add_user(s, "manager"), await add_user(s, "manager")
            editor, outsider = await add_user(s, "editor"), await add_user(s, "manager")
            pid = await add_project(s, manager, [approver, editor])
            if governance is not None:
                await GovernanceService(s).set_model(
                    pid,
                    source="shipped",
                    catalogue_id=governance,
                    version=None,
                    four_eyes=True,
                    actor_id=manager,
                    tenant_id=str(manager),
                )
            await s.commit()
        w = DesignWorld(factory, pid, manager, approver, editor, outsider)
    async with factory() as s:
        svc = DesignService(s)
        await svc.set_setup(w.project_id, actor_id=w.manager, tenant_id=str(w.manager), scheme_id="simple_sequential")
        for code, discipline in (("ARCH", "A"), ("STRU", "S")):
            role = await svc.create_role(
                w.project_id,
                {
                    "code": code,
                    "title": code,
                    "party_kind": "discipline_designer",
                    "discipline_code": discipline,
                    "originator_code": f"OR{discipline}",
                },
                actor_id=w.manager,
            )
            w.roles[code] = role.id
        await s.commit()
    return w


async def drawing_with_revision(
    w: DesignWorld, role: str, suitability: str = "S2", **extra: object
) -> tuple[uuid.UUID, uuid.UUID]:
    """A register drawing with one revision at ``suitability``; returns (drawing id, revision id).

    The container carries the same suitability and is ``shared`` (``wip`` for S0),
    as CDE leaves it after a revision is shared. ``extra`` goes to ``create_drawing``.
    """
    from app.modules.cde.models import DocumentContainer
    from tests.pg.governance_fixtures import add_revision

    async with w.factory() as s:
        drawing, container = await DesignService(s).create_drawing(
            w.project_id, {"role_id": str(w.roles[role]), "title": f"{role} plan", **extra}, actor_id=w.editor
        )
        rev_id = await add_revision(s, container.id, 1, f"{container.container_code}-1")
        c = await s.get(DocumentContainer, container.id)
        c.suitability_code = suitability
        c.cde_state = "wip" if suitability == "S0" else "shared"
        await s.commit()
        return drawing.id, rev_id


async def approved_release(w: DesignWorld, revision_ids: list[uuid.UUID], **data: object) -> uuid.UUID:
    """A release prepared by the editor and approved by the approver on the ``design_release`` route."""
    from sqlalchemy import select

    from app.modules.approval_routes.models import Route
    from tests.pg.governance_fixtures import add_route

    async with w.factory() as s:
        known = select(Route.id).where(Route.project_id == w.project_id, Route.target_kind == "design_release")
        if (await s.execute(known)).first() is None:
            await add_route(s, w.project_id, "design_release", w.approver)
        svc = DesignService(s)
        rel = await svc.create_release(
            w.project_id, {"revision_ids": [str(r) for r in revision_ids], **data}, actor_id=w.editor
        )
        ready = await svc.release_transition(w.project_id, rel.id, "ready", actor_id=w.editor)
        await decide_instance(s, ready.approval_instance_id, w.approver)
        assert await svc.catch_up_approvals(w.project_id) == 1
        assert ready.approval_status == "approved"
        await s.commit()
        return rel.id


async def decide_instance(
    session: AsyncSession, instance_id: uuid.UUID, approver: uuid.UUID, decision: str = "approved"
) -> None:
    """Decide the instance's current step through approval_routes, as its own screen does."""
    from sqlalchemy import select

    from app.modules.approval_routes.models import Instance, Step
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService

    inst = await session.get(Instance, instance_id)
    step = (
        await session.execute(
            select(Step).where(Step.route_id == inst.route_id, Step.ordinal == inst.current_step_ordinal)
        )
    ).scalar_one()
    await ApprovalRouteService(session).submit_decision(
        instance_id, DecisionSubmit(step_id=step.id, decision=decision), approver_id=approver, caller_role="manager"
    )


async def new_revision(w: DesignWorld, drawing_id: uuid.UUID, number: int) -> uuid.UUID:
    """Supersede a drawing's current revision with a new one."""
    from app.modules.design_management.models import DesignDrawing
    from tests.pg.governance_fixtures import add_revision

    async with w.factory() as s:
        d = await s.get(DesignDrawing, drawing_id)
        rev = await add_revision(s, d.container_id, number, f"{d.container_id}-{number}")
        await s.commit()
        return rev
