"""Reusable project-membership access helpers.

Every module that needs to gate access behind team membership (projects,
BOQ, HSE, Carbon, Variations, …) should route through these helpers rather
than inlining a fresh copy of the TeamMembership query.

Two helpers are provided:

* :func:`is_project_member` — async boolean check used in route guards.
* :func:`member_project_ids_subquery` — synchronous scalar subquery used
  in ORM ``WHERE … IN (…)`` clauses for list/aggregate endpoints.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def is_project_member(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Return ``True`` if *user_id* has a :class:`TeamMembership` row for *project_id*.

    Failures (DB errors, bad UUIDs that slipped through) are caught and
    treated as *not a member* so callers never see an unexpected 500.
    """
    from app.modules.teams.models import Team, TeamMembership

    try:
        row = (
            await session.execute(
                select(TeamMembership.id)
                .join(Team, Team.id == TeamMembership.team_id)
                .where(
                    Team.project_id == project_id,
                    TeamMembership.user_id == user_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def member_project_ids_subquery(user_id: uuid.UUID):
    """Return a SQLAlchemy scalar subquery of project_ids where *user_id* is a member.

    Intended for use in ORM ``WHERE`` clauses::

        Project.id.in_(member_project_ids_subquery(user_id))

    This is a *synchronous* factory — it returns a subquery object, not a
    coroutine.  The actual DB round-trip happens when the parent query executes.
    """
    from app.modules.teams.models import Team, TeamMembership

    return (
        select(Team.project_id)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(TeamMembership.user_id == user_id)
        .scalar_subquery()
    )
