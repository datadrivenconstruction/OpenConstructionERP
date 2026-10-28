# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The people a demo project has besides its owner.

A demo project is installed with one person on it, its owner. Stories that
show a decision need a second one: under four-eyes whoever owns an area cannot
decide its gate.

The cast is the product's own demo logins and nothing else. Where the
installation has them (the boot seeder creates them when the demo is enabled)
this module puts them on the team of each demo project. Where it does not,
because the operator declined the demo accounts or a pack was installed on a
workspace of real people, the cast is empty and stays empty: **this module
never creates a user.** A demo is not worth a new account with a role on
somebody's workspace. A seeder then tells the story one person can tell.

The one exception is not part of the cast: the pack demo file may list invented ``people`` who own the
areas of its filmed projects. They are rows nobody can sign in as (inactive, a hash of a thrown-away secret),
made by ``project_governance.seed_people`` for those projects only, and they take no part in any story.

What a seeder may count on, on a demo project, before the first module seeder
runs:

* the owner (``Project.owner_id``), always;
* ``cost``, when present: the second person of every four-eyes step. It is
  the FIRST team membership of the project that is not the owner, by
  ``created_at``, so a seeder that looks for "another member" finds this one;
* ``decider``, when present: decides and owns nothing; the second such
  membership.

:func:`find_cast` may return an empty dict. That is a legal state, not an
error, and a seeder that meets it logs nothing above info.

The memberships are rows of the project's team and leave with the project
through the existing cascade; nothing here has to be cleaned up.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The demo login behind each part. Both are in ``demo_accounts.DEMO_ACCOUNT_EMAILS``.
CAST: dict[str, str] = {
    "decider": "manager@openconstructionerp.com",
    "cost": "estimator@openconstructionerp.com",
}

#: The project team the cast is put on when it is not on the project yet.
TEAM_NAME = "Governance board"

#: The order the cast joins a project in. ``cost`` first: see the module docstring.
JOIN_ORDER: tuple[str, ...] = ("cost", "decider")


async def find_cast(session: AsyncSession) -> dict[str, uuid.UUID]:
    """The parts that are played on this installation, by word. Reads only.

    Args:
        session: Open session.

    Returns:
        ``{"decider": user id, "cost": user id}`` with a key missing for a
        demo login that does not exist or is not active. Empty on an
        installation without the demo logins.
    """
    from app.modules.users.models import User

    found: dict[str, uuid.UUID] = {}
    for word, email in CAST.items():
        user_id = (
            await session.execute(select(User.id).where(func.lower(User.email) == email, User.is_active.is_(True)))
        ).scalar_one_or_none()
        if user_id is not None:
            found[word] = user_id
    return found


async def join_project(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Put the cast on the team of one demo project, in :data:`JOIN_ORDER`. Idempotent.

    Memberships go through ``TeamService`` as the project owner, the way a
    user would add a colleague. A player who is the owner, or already a member
    of any team of the project, is left as found. With an empty cast nothing
    is written, not even the team.

    Args:
        session: Open session; the caller commits.
        project_id: A demo project.

    Returns:
        The number of memberships written.
    """
    from app.modules.projects.models import Project
    from app.modules.teams.access import is_project_member
    from app.modules.teams.models import Team
    from app.modules.teams.schemas import AddMemberRequest, TeamCreate
    from app.modules.teams.service import TeamService

    project = await session.get(Project, project_id)
    if project is None or project.owner_id is None:
        return 0
    players = await find_cast(session)
    missing = [
        players[word]
        for word in JOIN_ORDER
        if word in players
        and players[word] != project.owner_id
        and not await is_project_member(session, project_id, players[word])
    ]
    if not missing:
        return 0
    teams = TeamService(session)
    team = (
        await session.execute(select(Team).where(Team.project_id == project_id, Team.name == TEAM_NAME))
    ).scalar_one_or_none()
    if team is None:
        team = await teams.create_team(TeamCreate(project_id=project_id, name=TEAM_NAME), actor_id=project.owner_id)
    for user_id in missing:
        await teams.add_member(team.id, AddMemberRequest(user_id=user_id), actor_id=project.owner_id)
    return len(missing)


async def ensure_demo_cast(session: AsyncSession, project_ids: list[uuid.UUID] | None = None) -> dict[str, Any]:
    """Put the demo logins the installation has on the team of each demo project.

    Creates no user. Idempotent; the caller commits. A project the cast could
    not join is reported and does not stop the others.

    Args:
        session: Open session.
        project_ids: The demo projects whose team the cast joins.

    Returns:
        ``{"present": [...], "absent": [...], "memberships": n, "not_joined":
        [project ids], "ok": bool}``. ``present`` and ``absent`` list the words
        of the parts. An absent part is a legal state and leaves ``ok`` true;
        ``ok`` is false only when a project could not be joined.
    """
    players = await find_cast(session)
    result: dict[str, Any] = {
        "present": [word for word in CAST if word in players],
        "absent": [word for word in CAST if word not in players],
        "memberships": 0,
        "not_joined": [],
    }
    for project_id in (project_ids or []) if players else []:
        try:
            async with session.begin_nested():
                result["memberships"] += await join_project(session, project_id)
        except Exception:
            logger.warning("demo cast: could not join project %s", project_id, exc_info=True)
            result["not_joined"].append(str(project_id))
    result["ok"] = not result["not_joined"]
    if result["absent"]:
        logger.info("demo cast: no demo login for %s; demo projects keep their owner only", ", ".join(result["absent"]))
    return result
