# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project access facts for route guards, read in one statement.

A route guard needs three facts about a project before it can answer: does the
project exist and is it live, who owns it, and is the caller a team member of
it. The guards used to read them one at a time, a project load and then a
membership lookup for every non-owner, so every guarded request paid two or
three round trips before doing any work, and a request that guarded two
resources paid that twice.

This module reads all three for any number of projects in a single statement:
the project columns plus a correlated ``EXISTS`` on the team membership. It
decides nothing. The rules (an archived project is refused, an admin bypasses,
the owner and a member are let in, and which status a refusal carries) stay in
each guard, because they differ between guards on purpose and a shared decision
would quietly change what some caller sees.

The membership half is the same rule as :func:`app.modules.teams.access.is_project_member`:
any ``TeamMembership`` row on a team of the project. It also mirrors that
helper's handling of a caller id that is not a UUID, which is a member of
nothing, and it never binds such an id into SQL.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import false, select

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """What a guard needs to know about one project for one caller.

    Attributes:
        project_id: The project.
        owner_id: Its owner, as stored.
        status: Its lifecycle status; ``"archived"`` means deleted.
        is_member: Whether the caller has a team membership on it.
    """

    project_id: uuid.UUID
    owner_id: Any
    status: str
    is_member: bool

    @property
    def is_archived(self) -> bool:
        """Whether the project was deleted (projects are archived, never removed)."""
        return self.status == "archived"

    def is_owned_by(self, user_id: str) -> bool:
        """Whether *user_id* owns the project, compared as the guards always have, by string."""
        return str(self.owner_id) == user_id


def caller_uuid(user_id: object) -> uuid.UUID | None:
    """The caller's id as a UUID, or ``None`` when it is not one.

    A caller whose id is not a UUID cannot be a member of anything. Returning
    ``None`` rather than raising lets a guard fall through to its refusal, the
    way ``is_project_member`` answered "not a member" for such an id.
    """
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        return None


def membership_exists(project_id_column: ColumnElement[Any], user_id: uuid.UUID | None) -> ColumnElement[bool]:
    """A boolean column: does *user_id* hold a team membership on the project in *project_id_column*.

    Correlated to the enclosing statement through *project_id_column*, so it can
    sit in the select list of a query over projects, or over anything joined to
    a project. A ``None`` caller is a constant false and binds nothing.

    Args:
        project_id_column: The project id column of the enclosing statement.
        user_id: The caller, already parsed by :func:`caller_uuid`.

    Returns:
        A boolean expression to label and select.
    """
    if user_id is None:
        return false()
    from app.modules.teams.models import Team, TeamMembership

    # ``correlate_except`` rather than relying on auto-correlation: if the
    # project table were ever pulled into the subquery's own FROM, the test
    # would become "is a member of ANY project", which lets a member of one
    # project into every other one.
    return (
        select(TeamMembership.id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id == project_id_column, TeamMembership.user_id == user_id)
        .correlate_except(Team, TeamMembership)
        .exists()
    )


async def project_access(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
    user_id: object,
) -> dict[uuid.UUID, ProjectAccess]:
    """Read the access facts of every project in *project_ids* for *user_id*, in one statement.

    Args:
        session: The request's session.
        project_ids: The projects to read. Repeats are read once.
        user_id: The caller, as the token names it.

    Returns:
        The facts by project id. A project that does not exist has no entry,
        so a guard tells "missing" from "refused" by the key alone.
    """
    from app.modules.projects.models import Project

    ids = list(dict.fromkeys(project_ids))
    if not ids:
        return {}
    uid = caller_uuid(user_id)
    rows = (
        await session.execute(
            select(
                Project.id,
                Project.owner_id,
                Project.status,
                membership_exists(Project.id, uid).label("is_member"),
            ).where(Project.id.in_(ids))
        )
    ).all()
    return {
        row[0]: ProjectAccess(project_id=row[0], owner_id=row[1], status=row[2], is_member=bool(row[3])) for row in rows
    }
