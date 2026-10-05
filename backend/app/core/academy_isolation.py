# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Isolation gates for an academy install.

On an academy box (``OE_ACADEMY_MODE=true``) every learner holds the manager
role, because the course modules need it. Manager is enough to list users, and
several write paths take a user id from the request body: an assignee, a
reviewer, a subscriber, an ``@mention``. On a normal install those people are
colleagues. On an academy box they are other paying learners, and one learner
must not be able to read another learner's name and email or push a
notification at them.

Every function here is a no-op when the flag is off, so a normal install
behaves exactly as before: nothing is queried, nothing is raised, and the
input comes back unchanged.

Who counts as being in a project
--------------------------------
The same people :func:`app.dependencies.verify_project_access` lets in: the
project owner, anyone with a team membership on the project, and any system
admin. A project that does not exist has nobody in it, admins included, which
is also what that guard answers (404 before the admin bypass). The answer is
computed for a whole set of ids in three queries rather than one guard call per
id, and ``tests/pg/academy_isolation`` holds a parity test against
``verify_project_access`` so the two definitions cannot drift apart.

A lookup that fails counts as "not in the project". These are access gates,
and a gate that cannot read its data must not answer "everyone is allowed".
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

USER_NOT_IN_PROJECT = "user_not_in_project"
USER_NOT_IN_PROJECT_MESSAGE = "Everyone you name here must be a member of this project."
ADMIN_ADDS_MEMBERS = "academy_admin_adds_members"
ADMIN_ADDS_MEMBERS_MESSAGE = "On the academy only an administrator adds people to a project."
ROUTE_NEEDS_PROJECT = "academy_needs_project"
ROUTE_NEEDS_PROJECT_MESSAGE = "On the academy this has to belong to one of your projects."
EMAIL_NOT_OWN = "academy_email_not_own"
EMAIL_NOT_OWN_MESSAGE = "On the academy you can only email this to your own address."


def academy_mode_enabled() -> bool:
    """Whether this install runs as an academy box.

    Read per call from ``get_settings()``, never cached here, so a test can
    flip the flag and exercise both states in one run.
    """
    return bool(get_settings().academy_mode)


def _as_uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


async def _members_among(
    session: AsyncSession,
    project_id: uuid.UUID | str,
    user_ids: set[uuid.UUID],
) -> set[uuid.UUID]:
    """The subset of ``user_ids`` that can access ``project_id``.

    Owner, team members and system admins, as in ``verify_project_access``.
    Empty when the project does not exist or a lookup fails.
    """
    if not user_ids:
        return set()
    pid = _as_uuid(project_id)
    if pid is None:
        return set()

    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    try:
        row = (await session.execute(select(Project.owner_id).where(Project.id == pid))).first()
        if row is None:
            return set()
        allowed: set[uuid.UUID] = set()
        owner = _as_uuid(row[0]) if row[0] is not None else None
        if owner is not None and owner in user_ids:
            allowed.add(owner)
        admins = await session.execute(select(User.id).where(User.id.in_(user_ids), User.role == "admin"))
        allowed.update(_as_uuid(r) for r in admins.scalars().all())
        members = await session.execute(
            select(TeamMembership.user_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.project_id == pid, TeamMembership.user_id.in_(user_ids))
        )
        allowed.update(_as_uuid(r) for r in members.scalars().all())
    except Exception:
        logger.exception("academy isolation: membership lookup failed for project %s", project_id)
        return set()
    allowed.discard(None)  # type: ignore[arg-type]
    return allowed


async def assert_users_can_access_project(
    session: AsyncSession,
    project_id: uuid.UUID | str,
    user_ids: Iterable[uuid.UUID | str | None],
) -> None:
    """Refuse a write that names someone outside the project.

    ``None`` and empty entries are skipped, since they name nobody. An entry
    that is not a valid id cannot be a member and is refused like an outsider.
    The answer does not say whether the outsider exists, so it cannot be used
    to probe for accounts.

    Raises:
        HTTPException: 422 with ``{"error": "user_not_in_project"}`` in academy
            mode when any named user cannot access the project.
    """
    if not academy_mode_enabled():
        return
    named = [u for u in user_ids if u is not None and str(u).strip() != ""]
    if not named:
        return
    parsed = {_as_uuid(u) for u in named}
    valid = {u for u in parsed if u is not None}
    if None in parsed or valid - await _members_among(session, project_id, valid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": USER_NOT_IN_PROJECT, "message": USER_NOT_IN_PROJECT_MESSAGE},
        )


async def filter_users_to_project[T](
    session: AsyncSession | None,
    project_id: uuid.UUID | str,
    user_ids: Iterable[T],
) -> list[T]:
    """Keep only the ids of users who can access the project.

    Order and element types are preserved. With the flag off the input comes
    back as a list, unchanged, and ``session`` is never touched.
    """
    items = list(user_ids)
    if not academy_mode_enabled():
        return items
    if session is None:
        return []
    candidates = {u for u in (_as_uuid(i) for i in items if i is not None) if u is not None}
    allowed = await _members_among(session, project_id, candidates)
    return [i for i in items if i is not None and _as_uuid(i) in allowed]


def _is_admin(current_user: Mapping[str, Any]) -> bool:
    # ``role`` in the auth payload is re-read from the database on every
    # request (see ``get_current_user_payload``), never trusted from the token.
    return current_user.get("role") == "admin"


def limits_users_to_self(current_user: Mapping[str, Any]) -> bool:
    """Whether a user listing must show the caller only: academy mode, not an admin."""
    return academy_mode_enabled() and not _is_admin(current_user)


async def assert_self_or_admin(user_id: uuid.UUID | str, current_user: Mapping[str, Any]) -> None:
    """Refuse to show another user's record to a non-admin in academy mode.

    Raises:
        HTTPException: 404 ``User not found``, the same answer as a missing
            user, so the response does not confirm that the id exists.
    """
    if not limits_users_to_self(current_user):
        return
    if str(user_id) != str(current_user.get("sub")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


async def _is_admin_user(session: AsyncSession, user_id: uuid.UUID | str) -> bool:
    uid = _as_uuid(user_id)
    if uid is None:
        return False
    from app.modules.users.models import User

    try:
        role = (await session.execute(select(User.role).where(User.id == uid))).scalar_one_or_none()
    except Exception:
        logger.exception("academy isolation: role lookup failed for user %s", user_id)
        return False
    return role == "admin"


async def assert_admin_adds_members(session: AsyncSession, actor_id: uuid.UUID | str | None) -> None:
    """Refuse a non-admin who adds someone to a project in academy mode.

    A membership row is what every other gate here counts as "in the project",
    so a learner who could add another learner to their own project would open
    all of them at once. Learners never share a project, so on an academy box
    adding people is an admin's job. Call it before the target is looked up, so
    the answer does not depend on whether the target exists.

    ``actor_id=None`` is a system call (a seeder, a migration helper), as in
    the teams service, and is let through.

    Raises:
        HTTPException: 403 with ``{"error": "academy_admin_adds_members"}``.
    """
    if not academy_mode_enabled() or actor_id is None:
        return
    if await _is_admin_user(session, actor_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": ADMIN_ADDS_MEMBERS, "message": ADMIN_ADDS_MEMBERS_MESSAGE},
    )


async def assert_parties_in_project(
    session: AsyncSession,
    project_id: uuid.UUID | str,
    values: Iterable[str | uuid.UUID | None],
    actor_id: uuid.UUID | str | None,
) -> None:
    """Refuse a free party field that names someone outside the project.

    Some columns (a punch item's ``assigned_to``, an inspection's
    ``inspector_id``) hold a user id, a contact id or a typed-in name, and the
    party-name resolver turns any id on the install into a name. In academy
    mode an id must be a project member or a contact in the actor's own address
    book; a value that is not an id is a typed name and passes. With no actor
    (a system call) contacts are not judged, only users.

    Raises:
        HTTPException: 422 ``user_not_in_project``, the same answer for an
            outsider and for an id that names nothing.
    """
    if not academy_mode_enabled():
        return
    ids = {u for u in (_as_uuid(v) for v in values if v is not None and str(v).strip()) if u is not None}
    # ``_as_uuid`` also parses a typed name that happens to be id-shaped; it is
    # judged as an id, which is what the resolver would do with it too.
    if not ids:
        return
    outside = ids - await _members_among(session, project_id, ids)
    if outside and actor_id is not None:
        outside -= await _own_contacts_among(session, outside, actor_id)
    elif outside:
        outside -= await _contacts_among(session, outside)
    if outside:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": USER_NOT_IN_PROJECT, "message": USER_NOT_IN_PROJECT_MESSAGE},
        )


async def _contacts_among(session: AsyncSession, ids: set[uuid.UUID], owner: str | None = None) -> set[uuid.UUID]:
    try:
        from app.modules.contacts.models import Contact
        from app.modules.contacts.repository import _tenant_scope

        stmt = select(Contact.id).where(Contact.id.in_(ids))
        if owner is not None:
            stmt = stmt.where(_tenant_scope(owner))
        return {_as_uuid(r) for r in (await session.execute(stmt)).scalars().all()} - {None}  # type: ignore[return-value]
    except Exception:
        logger.exception("academy isolation: contact lookup failed")
        return set()


async def _own_contacts_among(session: AsyncSession, ids: set[uuid.UUID], actor_id: uuid.UUID | str) -> set[uuid.UUID]:
    """Contacts among ``ids`` in the actor's address book; any contact for an admin."""
    from app.core.tenant_scope import tenant_scope_owner

    try:
        owner = await tenant_scope_owner(session, str(actor_id))
    except Exception:
        logger.exception("academy isolation: tenant lookup failed for %s", actor_id)
        return set()
    return await _contacts_among(session, ids, owner)


async def is_academy_learner(session: AsyncSession, user_id: uuid.UUID | str | None) -> bool:
    """Academy mode is on and ``user_id`` is a learner, not an admin or a system call."""
    if not academy_mode_enabled() or user_id is None:
        return False
    return not await _is_admin_user(session, user_id)


async def assert_learner_names_a_project(
    session: AsyncSession,
    user_id: uuid.UUID | str | None,
    project_id: uuid.UUID | str | None,
) -> None:
    """Refuse a learner's install-wide record in academy mode.

    Some records may be created without a project (an approval route template,
    an out-of-office hand-off) and then apply to, or are listed in, every
    project on the install. On an academy box that is every learner's course,
    so a learner's record must name one of their projects; an admin's may not.

    Raises:
        HTTPException: 422 with ``{"error": "academy_needs_project"}``.
    """
    if project_id is not None or not await is_academy_learner(session, user_id):
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": ROUTE_NEEDS_PROJECT, "message": ROUTE_NEEDS_PROJECT_MESSAGE},
    )


async def assert_own_email(session: AsyncSession, user_id: uuid.UUID | str | None, email: str) -> None:
    """Refuse a learner who mails a document to anyone but themselves in academy mode.

    A send-by-email endpoint that takes the recipient from the request body is
    an open relay on an academy box: the platform's mail server carries a
    learner's attachment and note to any inbox. A learner may send only to
    their own address; an admin and a system call are not limited.

    Raises:
        HTTPException: 422 with ``{"error": "academy_email_not_own"}``.
    """
    if not await is_academy_learner(session, user_id):
        return
    from app.modules.users.models import User

    own = (await session.execute(select(User.email).where(User.id == _as_uuid(user_id)))).scalar_one_or_none()
    if own and own.strip().lower() == (email or "").strip().lower():
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": EMAIL_NOT_OWN, "message": EMAIL_NOT_OWN_MESSAGE},
    )


async def academy_directory_owner(session: AsyncSession, user_id: uuid.UUID | str | None) -> str | None:
    """The owner a learner's directory links must stay with in academy mode.

    ``None`` means nothing limits the caller: the flag is off, the caller is an
    admin, or there is no caller (a system call or a seeder).
    """
    if not academy_mode_enabled() or user_id is None:
        return None
    from app.core.tenant_scope import tenant_scope_owner

    return await tenant_scope_owner(session, str(user_id))


async def foreign_directory_link(
    session: AsyncSession,
    actor_id: uuid.UUID | str | None,
    *,
    subcontractor_id: uuid.UUID | str | None = None,
    contact_id: uuid.UUID | str | None = None,
) -> str | None:
    """Which named directory link belongs to someone else, in academy mode.

    A subcontractor is the learner's when they created it (the directory has
    no tenant column), and a contact when it is in their own address book.
    Returns ``"subcontractor"``, ``"contact"`` or ``None``; the caller answers
    with its own "not found", so another learner's row reads like a missing
    one.
    """
    owner = await academy_directory_owner(session, actor_id)
    if owner is None:
        return None
    if subcontractor_id is not None:
        from app.modules.subcontractors.models import Subcontractor

        sub_id = _as_uuid(subcontractor_id)
        created_by = (
            (
                await session.execute(select(Subcontractor.created_by).where(Subcontractor.id == sub_id))
            ).scalar_one_or_none()
            if sub_id is not None
            else None
        )
        if str(created_by or "") != owner:
            return "subcontractor"
    if contact_id is not None:
        cid = _as_uuid(contact_id)
        if cid is None or cid not in await _contacts_among(session, {cid}, owner):
            return "contact"
    return None
