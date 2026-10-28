# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the permits PostgreSQL tests.

A world is a throwaway database with real users and a DE project in North
Rhine-Westphalia whose roadmap pins the shipped ``de_nw`` catalogue (it extends
``de``): a Bauvoranfrage, the Baugenehmigung depending on it, the BImSchG
permit with its 7-month clock and the early start under BImSchG §8a. A
confirmed route assessment says ``full_permit``. Everything commits for real.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.permits.service import PermitService
from tests.pg.governance_fixtures import add_user


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    owner_user: uuid.UUID
    verifier: uuid.UUID
    editor: uuid.UUID
    outsider: uuid.UUID
    assessment_id: uuid.UUID


async def add_project(
    session: AsyncSession, owner: uuid.UUID, members: list[uuid.UUID], country: str = "DE"
) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership

    pid = uuid.uuid4()
    session.add(
        Project(
            id=pid,
            name=f"Permits {pid.hex[:6]}",
            currency="EUR",
            status="active",
            owner_id=owner,
            metadata_={},
            country_code=country,
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


async def add_assessment(session: AsyncSession, pid: uuid.UUID, route: str = "full_permit") -> uuid.UUID:
    from app.modules.project_route.models import RouteAssessment

    row = RouteAssessment(
        project_id=pid, work_type="new_build", criteria={}, determined_route=route, rationale="", status="confirmed"
    )
    session.add(row)
    await session.flush()
    return row.id


async def build_world(factory: async_sessionmaker[AsyncSession], route: str = "full_permit") -> World:
    import app.modules.permits.models  # noqa: F401  (register the tables)

    async with factory() as s:
        manager = await add_user(s, "manager")
        owner_user = await add_user(s, "editor")
        verifier = await add_user(s, "manager")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [owner_user, verifier, editor])
        aid = await add_assessment(s, pid, route)
        await PermitService(s).set_roadmap(pid, tenant_id=None, actor_id=manager, jurisdiction="DE-NW")
        await s.commit()
    return World(factory, pid, manager, owner_user, verifier, editor, outsider, aid)


async def requirement(w: World, code: str, **kw: Any) -> uuid.UUID:
    async with w.factory() as s:
        row = await PermitService(s).create_requirement(
            w.project_id, {"permit_type_code": code, "responsible_user_id": w.manager, **kw}, actor_id=w.manager
        )
        await s.commit()
        return row.id


async def depend(w: World, rid: uuid.UUID, on: uuid.UUID, typ: str = "granted") -> None:
    async with w.factory() as s:
        await PermitService(s).set_dependencies(
            w.project_id, rid, [{"depends_on_id": on, "on": typ}], actor_id=w.manager
        )
        await s.commit()


async def application(w: World, rid: uuid.UUID, **kw: Any) -> uuid.UUID:
    async with w.factory() as s:
        row = await PermitService(s).create_application(
            w.project_id, {"requirement_id": rid, "authority_reference": "AZ-1", **kw}, actor_id=w.manager
        )
        await s.commit()
        return row.id


async def move(
    w: World,
    aid: uuid.UUID,
    target: str,
    on: date | None = None,
    can_manage: bool = True,
    today: date = date(2026, 10, 11),
) -> Any:
    async with w.factory() as s:
        row = await PermitService(s).transition_application(
            w.project_id, aid, target, actor_id=w.manager, can_manage=can_manage, on_date=on, today=today
        )
        await s.commit()
        return row


async def file(
    w: World, rid: uuid.UUID, on: date | None = None, today: date = date(2026, 10, 11), **kw: Any
) -> uuid.UUID:
    aid = await application(w, rid, **kw)
    await move(w, aid, "preparing")
    await move(w, aid, "submitted", on or today - timedelta(days=60), today=today)
    return aid


async def decide(w: World, aid: uuid.UUID, outcome: str, today: date = date(2026, 10, 11), **kw: Any) -> dict[str, Any]:
    async with w.factory() as s:
        out = await PermitService(s).record_decision(
            w.project_id,
            aid,
            {"outcome": outcome, "decision_date": kw.pop("decision_date", today - timedelta(days=10)), **kw},
            actor_id=w.manager,
            today=today,
        )
        await s.commit()
        return out


def cond(number: str, kind: str = "obligation", trigger: str = "before_start", **kw: Any) -> dict[str, Any]:
    return {"number": number, "text": f"Condition {number} text.", "kind": kind, "trigger": trigger, **kw}


async def state(w: World, rid: uuid.UUID) -> str | None:
    async with w.factory() as s:
        return await PermitService(s).requirement_state(w.project_id, rid)
