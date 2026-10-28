# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the staffing PostgreSQL tests.

A world is a throwaway database with real users and a project that runs
governance on the shipped ``elf_module_framework`` model, a demo roster from
the teams seed, and a staffing plan pinned to the requested shipped catalogue.
Everything commits for real, so row locks behave as in production.

The shipped governance model says by tag where staffing lives and which phase
enables the start of construction; the module reads that through the
governance port. The codes those tags resolve to are written here, in test
data, so the tests can assert the resolution, and nowhere in the module.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.project_governance.service import GovernanceService
from app.modules.staffing.service import Actor, StaffingService
from tests.pg.governance_fixtures import World, add_container, add_project, add_route, add_user

GATE = "development_to_execution"
PERSONNEL_AREA = "m05_personnel"
PERSONNEL_FRAME = "m05_personnel_frame"
CONSTRUCTION_PHASE = "execution"
# Relative to the run day: a fill must be running today for the derived status to read ``filled``.
START = date.today() - timedelta(days=30)
COMMISSIONING = date.today() + timedelta(days=600)
KEY_ROLES_BEFORE_CONSTRUCTION = (
    "project_director",
    "project_manager",
    "design_manager",
    "cost_manager",
    "contract_manager",
    "hse_manager",
    "site_manager",
)


def admin(w: World) -> Actor:
    """Every staffing permission, and still no relationship to anybody."""
    return Actor(
        w.manager, personnel_read=True, personnel_edit=True, personnel_erase=True, assign_owner=True, manage=True
    )


def hr(user_id: uuid.UUID) -> Actor:
    """The personnel tier a manager holds: read and edit, nothing that sets who is related."""
    return Actor(user_id, personnel_read=True, personnel_edit=True)


async def drop_frame_document(w: World) -> None:
    """Remove the project's document row of the type that hosts staffing: a project pinned before its
    model gained that document type looks like this."""
    from app.modules.project_governance.models import GovernanceDocument

    async with w.factory() as s:
        rows = await s.execute(
            select(GovernanceDocument).where(
                GovernanceDocument.project_id == w.project_id, GovernanceDocument.doc_type == PERSONNEL_FRAME
            )
        )
        for row in rows.scalars():
            await s.delete(row)
        await s.commit()


async def build_world(
    factory: async_sessionmaker[AsyncSession], *, catalogue_id: str = "neutral", governance: bool = True
) -> World:
    from app.modules.staffing.catalogue import register_kinds
    from app.modules.teams.seed import seed_teams_roster

    register_kinds()
    async with factory() as s:
        manager = await add_user(s, "manager")
        decider = await add_user(s, "manager")
        owner = await add_user(s, "manager")
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
            # Governance reads only a pinned route; nothing is found by project or kind.
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
        await seed_teams_roster(s, project_id=pid)
        await StaffingService(s).set_plan(
            pid,
            actor_id=manager,
            tenant_id=str(manager),
            catalogue_id=catalogue_id,
            commissioning_date=COMMISSIONING,
        )
        await s.commit()
    return w


async def call(w: World, fn: str, *args: Any, **kw: Any) -> Any:
    """Run one service method in its own committed session."""
    async with w.factory() as s:
        out = await getattr(StaffingService(s), fn)(w.project_id, *args, **kw)
        await s.commit()
        return out


async def members(w: World) -> list[Any]:
    from app.modules.teams.models import RosterMember

    async with w.factory() as s:
        stmt = (
            select(RosterMember)
            .where(RosterMember.project_id == w.project_id)
            .order_by(RosterMember.created_at, RosterMember.id)
        )
        return list((await s.execute(stmt)).scalars())


async def position(w: World, role_code: str, phase: str = "execution", **extra: Any) -> uuid.UUID:
    """A position whose line manager is the world's manager, unless ``owner_user_id`` says otherwise."""
    data = {"role_code": role_code, "phase": phase, "entry_date": START, "owner_user_id": w.manager, **extra}
    row = await call(w, "create_position", data, admin(w))
    return row.id


async def fill(w: World, position_id: uuid.UUID, member_id: uuid.UUID, share: str = "1", **extra: Any) -> uuid.UUID:
    data = {"roster_member_id": member_id, "fte_share": share, "from_date": START, **extra}
    row = await call(w, "create_fill", position_id, data, w.manager)
    return row.id


async def confirm(w: World, fill_id: uuid.UUID) -> Any:
    return await call(w, "confirm_fill", fill_id, admin(w))


async def staffed(w: World, member_id: uuid.UUID, role_code: str = "document_controller", share: str = "0.10") -> None:
    """Put the person on a confirmed fill of a position the world's manager owns: the relationship of rule 13."""
    pid = await position(w, role_code, fte=share)
    await confirm(w, await fill(w, pid, member_id, share))


async def personnel_file(w: World, member_id: uuid.UUID, *, actor: Actor | None = None, **extra: Any) -> uuid.UUID:
    """The person's file, opened by ``actor`` or by the world's manager as line manager of one of their fills."""
    if actor is None:
        async with w.factory() as s:
            owners = await StaffingService(s)._position_owners_of(w.project_id, member_id)
        if w.manager not in owners:
            await staffed(w, member_id)
        actor = admin(w)
    row = await call(w, "create_file", {"roster_member_id": member_id, **extra}, actor)
    return row.id


async def record(
    w: World,
    file_id: uuid.UUID,
    kind: str,
    valid_until: date | None = None,
    *,
    actor: Actor | None = None,
    **extra: Any,
) -> Any:
    """Record a document on the file; the credential behind it is created by the service."""
    data = {"document_kind": kind, "valid_until": valid_until, **extra}
    return await call(w, "record_document", file_id, data, actor or admin(w))


async def submittable_plan(w: World, *, fill_key_roles: bool = False) -> dict[str, uuid.UUID]:
    """Every key role of the neutral catalogue planned, operation roles before commissioning, handovers linked.

    With ``fill_key_roles`` every role required before construction is also filled today (a tenth of an
    FTE each, shared by two people), which is what the gate asks of the personnel area.
    """
    ids: dict[str, uuid.UUID] = {}
    for code in (*KEY_ROLES_BEFORE_CONSTRUCTION, "commissioning_manager"):
        ids[code] = await position(w, code, fte="0.10")
    ids["operator_plant_manager"] = await position(w, "operator_plant_manager", "operation")
    people = await members(w)
    fills: dict[str, uuid.UUID] = {}
    for index, code in enumerate(KEY_ROLES_BEFORE_CONSTRUCTION):
        if fill_key_roles or code in ("project_manager", "design_manager"):
            fills[code] = await fill(w, ids[code], people[index % 2].id, "0.10")
            if fill_key_roles:
                await confirm(w, fills[code])
    for giver, receiver in (("project_manager", "operator_plant_manager"), ("design_manager", "commissioning_manager")):
        await call(
            w,
            "create_handover",
            {"from_fill_id": fills[giver], "to_position_id": ids[receiver], "overlap_days": 30, "scope": ""},
            w.manager,
        )
    return ids


def days(n: int) -> date:
    return date.today() + timedelta(days=n)
