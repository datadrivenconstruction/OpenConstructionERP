# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the stakeholders PostgreSQL tests.

A world is a throwaway database with real users, a project with team
membership, and a shipped stakeholder framework pinned. Everything commits
for real, so locks and subscribers behave as in production.

The clock is the real one: write routes and the service's mandate checks use
the server date, so the tests place validity windows around today.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.stakeholders.service import StakeholderService
from tests.pg.governance_fixtures import add_project, add_route, add_user

TODAY = datetime.now(UTC).date()


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    manager2: uuid.UUID
    editor: uuid.UUID
    viewer: uuid.UUID
    outsider: uuid.UUID
    route_id: uuid.UUID | None = None


async def build_world(
    factory: async_sessionmaker[AsyncSession], *, framework_id: str = "neutral", route: bool = False
) -> World:
    async with factory() as s:
        manager = await add_user(s, "manager")
        manager2 = await add_user(s, "manager")
        editor = await add_user(s, "editor")
        viewer = await add_user(s, "viewer")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [manager2, editor, viewer])
        data: dict = {"framework_source": "shipped", "framework_id": framework_id}
        route_id = None
        if route:
            route_id = await add_route(s, pid, "stakeholder_commitment", manager2)
            data["commitment_route_id"] = str(route_id)
        await StakeholderService(s).put_settings(pid, data, actor_id=manager)
        await s.commit()
    return World(factory, pid, manager, manager2, editor, viewer, outsider, route_id)


async def stakeholder(w: World, name: str, category: str = "neighbour", **extra) -> uuid.UUID:
    async with w.factory() as s:
        row = await StakeholderService(s).create_stakeholder(
            w.project_id, {"display_name": name, "category": category, **extra}, actor_id=w.editor
        )
        await s.commit()
        return row.id


async def roster(w: World, user_id: uuid.UUID | None, name: str = "Team member") -> uuid.UUID:
    from sqlalchemy import select

    from app.modules.teams.models import RosterMember

    async with w.factory() as s:
        if user_id is not None:
            # The roster holds a user once per project.
            found = (
                await s.execute(
                    select(RosterMember.id).where(
                        RosterMember.project_id == w.project_id, RosterMember.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            if found is not None:
                return found
        row = RosterMember(project_id=w.project_id, user_id=user_id, display_name=name)
        s.add(row)
        await s.commit()
        return row.id


async def seat(
    w: World,
    role_code: str,
    user_id: uuid.UUID,
    *,
    valid_from: date | None = None,
    valid_to: date | None = None,
    rationale: str = "",
) -> None:
    """Make ``user_id`` the holder of a project role."""
    member = await roster(w, user_id)
    async with w.factory() as s:
        await StakeholderService(s).put_role_holders(
            w.project_id,
            role_code,
            [
                {
                    "roster_member_id": member,
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "conflict_rationale": rationale,
                }
            ],
            actor_id=w.manager,
            today=TODAY,
        )
        await s.commit()


async def contact(w: World, creator: uuid.UUID, first: str, last: str) -> uuid.UUID:
    from app.modules.contacts.models import Contact

    async with w.factory() as s:
        row = Contact(
            contact_type="person",
            first_name=first,
            last_name=last,
            tenant_id=str(creator),
            created_by=str(creator),
            is_active=True,
        )
        s.add(row)
        await s.commit()
        return row.id


async def commitment(w: World, stakeholder_id: uuid.UUID, *, owner: uuid.UUID | None = None, **extra) -> uuid.UUID:
    async with w.factory() as s:
        row = await StakeholderService(s).create_commitment(
            w.project_id,
            {
                "stakeholder_ids": [stakeholder_id],
                "text": "No deliveries before 07:00",
                "category": "working_hours",
                "owner_user_id": owner or w.editor,
                "due_date": TODAY + timedelta(days=30),
                **extra,
            },
            actor_id=w.editor,
        )
        await s.commit()
        return row.id


async def move(w: World, cid: uuid.UUID, target: str, actor: uuid.UUID, **kw):
    async with w.factory() as s:
        row, warnings = await StakeholderService(s).transition_commitment(
            w.project_id, cid, target, actor_id=actor, today=TODAY, **kw
        )
        await s.commit()
        return row, warnings
