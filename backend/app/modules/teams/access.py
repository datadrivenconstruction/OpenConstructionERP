# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reusable project-membership and record-restriction access helpers.

Every module that needs to gate access behind team membership (projects,
BOQ, HSE, Carbon, Variations, …) should route through these helpers rather
than inlining a fresh copy of the TeamMembership query.

Project-level membership:

* :func:`is_project_member` - async boolean check used in route guards.
* :func:`member_project_ids_subquery` - synchronous scalar subquery used
  in ORM ``WHERE … IN (…)`` clauses for list/aggregate endpoints.

Record-level restriction:

* :func:`hidden_entity_ids` - the subset of ids the caller must NOT see.
* :func:`assert_entity_not_hidden` - the same answer as a 404.
* :func:`hidden_entity_ids_subquery` - the SQL form for a list endpoint.

Why the restriction helpers are subtractive
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
They answer "which of the ids you already decided this user may see must now
be taken away", never "which ids may this user see". The signature is what
enforces the invariant: a consumer physically cannot use them to add an id to
a result set, so no arrangement of teams and restrictions can hand anyone
visibility of a project or a record they could not already reach. The team
layer is only ever allowed to narrow.

The correct call order in a consumer is therefore always:

    1. establish project access (``verify_project_access`` - 404 on denial),
    2. build the result set the caller is entitled to,
    3. subtract :func:`hidden_entity_ids` from it.

Skipping step 1 and relying on step 3 would be an access-control bug: an
unrestricted record is hidden from nobody, which is correct behaviour for a
narrowing filter and useless as a gate.

Failure policy
~~~~~~~~~~~~~~
These helpers fail CLOSED. If the restriction lookup raises - a dropped
connection, a malformed id - every candidate id is reported as hidden. An
access-control resolver that cannot reach its data must not answer "nothing is
restricted", which is what a fail-open default would say. That mirrors
:func:`is_project_member`, which answers "not a member" when its query fails.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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


def member_project_ids_subquery(user_id: uuid.UUID, *, live_only: bool = False):
    """Return a SQLAlchemy scalar subquery of project_ids where *user_id* is a member.

    Intended for use in ORM ``WHERE`` clauses::

        Project.id.in_(member_project_ids_subquery(user_id))

    This is a *synchronous* factory - it returns a subquery object, not a
    coroutine.  The actual DB round-trip happens when the parent query executes.

    ``live_only=True`` leaves out archived (deleted) projects. Use it when the
    subquery scopes a listing of child rows by ``project_id``; an access check
    keeps the default, which reaches archived projects as it always has.
    """
    from app.modules.teams.models import Team, TeamMembership

    stmt = (
        select(Team.project_id)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(TeamMembership.user_id == user_id)
    )
    if live_only:
        from app.modules.projects.models import Project

        stmt = stmt.join(Project, Project.id == Team.project_id).where(Project.status != "archived")
    return stmt.scalar_subquery()


# ── Record-level restriction ─────────────────────────────────────────────────


async def hidden_entity_ids(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    entity_type: str,
    entity_ids: list[str],
    user_id: uuid.UUID | str | None,
    is_project_owner: bool = False,
    is_system_admin: bool = False,
) -> set[str]:
    """The subset of *entity_ids* this user must not be shown.

    Subtract the result from a set the caller has ALREADY established the user
    is entitled to. The answer is only ever a subset of the input, so it cannot
    add anything.

    An id is hidden when a restriction row exists for it inside *project_id*
    and the user belongs to none of the teams those rows name. An id with no
    restriction row is never hidden, which is what keeps the feature opt-in
    per record.

    The project owner and system admins are never locked out of their own
    project: a restriction is a "who else may look at this" control, not a way
    to hide a record from the people accountable for it. Callers pass those two
    flags because they have already resolved them while checking project access.

    Args:
        session: Async session.
        project_id: The project the records belong to. Restriction rows written
            against teams of any other project are ignored, so a row cannot
            reach across a project boundary.
        entity_type: A key from :mod:`app.modules.teams.entity_types`.
        entity_ids: The candidate ids, as the strings they are stored under.
        user_id: The caller. ``None`` (a system/background call) hides nothing.
        is_project_owner: Caller owns the project.
        is_system_admin: Caller has the system admin role.

    Returns:
        The ids to remove from the caller's result set. Empty when nothing is
        restricted; the whole input on a lookup failure (fail closed).
    """
    if not entity_ids:
        return set()
    if user_id is None or is_project_owner or is_system_admin:
        return set()

    from app.modules.teams.repository import VisibilityRepository

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        # A caller id we cannot resolve is not a member of anything, so every
        # restricted record is hidden from it.
        logger.warning("hidden_entity_ids: unparsable user id, hiding all restricted records")
        uid = None

    try:
        repo = VisibilityRepository(session)
        candidates = list(dict.fromkeys(entity_ids))
        restricted = await repo.restricted_entity_ids(project_id, entity_type, entity_ids=candidates)
        if not restricted:
            return set()
        if uid is None:
            return restricted
        allowed = await repo.entity_ids_visible_to_user(
            project_id,
            entity_type,
            uid,
            entity_ids=candidates,
        )
        return restricted - allowed
    except Exception:  # noqa: BLE001 - fail closed, never fail open
        logger.exception(
            "restriction lookup failed for %s in project %s; hiding every candidate",
            entity_type,
            project_id,
        )
        return set(entity_ids)


async def assert_entity_not_hidden(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
    user_id: uuid.UUID | str | None,
    is_project_owner: bool = False,
    is_system_admin: bool = False,
) -> None:
    """Raise 404 when one record is restricted away from the caller.

    The detail-endpoint companion to :func:`hidden_entity_ids`. 404 rather than
    403 for the same reason every other guard in the platform uses it: a 403
    would confirm the record exists to someone who is not allowed to know.

    Call this AFTER the endpoint's normal project-access check, never instead
    of it.
    """
    hidden = await hidden_entity_ids(
        session,
        project_id=project_id,
        entity_type=entity_type,
        entity_ids=[entity_id],
        user_id=user_id,
        is_project_owner=is_project_owner,
        is_system_admin=is_system_admin,
    )
    if entity_id in hidden:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def hidden_entity_ids_subquery(
    project_id: uuid.UUID,
    entity_type: str,
    user_id: uuid.UUID,
):
    """Scalar subquery of the entity ids *user_id* is restricted away from.

    The SQL form of :func:`hidden_entity_ids`, for a list endpoint that must
    not round-trip its candidate ids into Python. Use it negated, so it can
    only ever remove rows::

        stmt = stmt.where(
            ~cast(Model.id, String).in_(
                hidden_entity_ids_subquery(project_id, "document", user_id)
            )
        )

    Unlike the async helper this cannot fail closed - a broken query raises
    rather than returning a value - which is the right shape here: the
    statement fails and the endpoint 500s instead of quietly listing
    everything.
    """
    from app.modules.teams.models import EntityVisibility, Team, TeamMembership

    restricted = (
        select(EntityVisibility.entity_id)
        .join(Team, Team.id == EntityVisibility.team_id)
        .where(Team.project_id == project_id, EntityVisibility.entity_type == entity_type)
    )
    allowed = (
        select(EntityVisibility.entity_id)
        .join(Team, Team.id == EntityVisibility.team_id)
        .join(TeamMembership, TeamMembership.team_id == EntityVisibility.team_id)
        .where(
            Team.project_id == project_id,
            EntityVisibility.entity_type == entity_type,
            TeamMembership.user_id == user_id,
        )
    )
    return restricted.except_(allowed).scalar_subquery()
