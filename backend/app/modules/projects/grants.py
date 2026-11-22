# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who may decide that another company participates in a project, and what the decision writes.

ADR 006, stage 2. The table this module writes is
:class:`app.modules.projects.models.ProjectParticipantGrant`; the reasoning behind
its shape is in that model's docstring and in ``docs/adr/006-project-participant-grants.md``.
This file holds the four decisions the table cannot make for itself:

**One company may grant, and it is the owner.** Every write here starts from
:func:`resolve_grant_authority`, which answers the question before any row is
touched. The caller's organization has to be the project's
``organization_id``, the caller has to hold an *active* membership in it, and
that membership's role has to carry ``projects.grant``. There is deliberately no
platform-admin bypass: ``RequirePermission`` and ``_verify_project_owner`` both
let ``role=admin`` through because an instance administrator is trusted with the
instance, and handing a company's project to a different company is not an
instance decision. An administrator who needs to can change the project's owning
organization, which suspends every grant on it (owner decision 4) and puts the
decision back in front of the new owner.

**No sub-grants, and that is structural rather than a check.** A grantee's
organization is not the project's ``organization_id``, so authority resolution
refuses it before it can look at what it was given. There is no branch here that
asks whether the caller's access came from a grant, because no such caller gets
this far - and the test that pins it asserts the refusal rather than the absence
of the branch.

**Nothing is retroactive.** Revoking closes the read predicate from the moment
the row is written. It does not delete, re-stamp, hide or rewrite anything the
grantee produced, which stay the grantee's own rows under the grantee's own
``tenant_id`` (owner decision 3). There is no ``UPDATE`` in this file that
touches a table other than the grant table and the audit log.

**Every event leaves a row.** ``log_activity`` rather than this module's
neighbour :func:`app.modules.projects.service._safe_audit`, because that one
swallows failures: an authorization change whose trail did not land is worse
than no change at all, and the write shares the caller's transaction so the
grant and its audit row land together or not at all.

The module raises :class:`~fastapi.HTTPException` directly, which follows
:mod:`app.modules.projects.service` and keeps the router thin. The status codes
are the ones the IDOR policy in ``app.dependencies.verify_project_access`` sets:
a project the caller's company cannot see is 404 and never 403, so "missing" and
"denied" stay indistinguishable to somebody probing identifiers; a refusal that
presupposes the project exists is 403.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.permissions import permission_registry
from app.core.tenant_scope import MEMBERSHIP_ACTIVE
from app.modules.projects.models import (
    GRANT_SCOPE_RANK,
    GRANT_STATUSES,
    Project,
    ProjectParticipantGrant,
)
from app.modules.users.models import Membership, Organization

logger = logging.getLogger(__name__)

#: ``ActivityLog.entity_type`` for every row this module writes. A grant is its
#: own entity rather than a kind of ``project`` event, because the question an
#: operator asks is "who authorized this company", and filtering the project's
#: own history by entity type is what answers it.
GRANT_ENTITY_TYPE = "participant_grant"

#: The four events, one audit row each. Named after what happened to the grant
#: and not after the HTTP verb, so a reader of the log does not have to know
#: which endpoint wrote the row.
ACTION_GRANTED = "granted"
ACTION_SCOPE_CHANGED = "scope_changed"
ACTION_SUSPENDED = "suspended"
ACTION_REVOKED = "revoked"

#: The permission that carries the right to decide. Registered in
#: :func:`app.modules.projects.permissions.register_project_permissions` at
#: ``Role.MANAGER``, one step above the ``projects.update`` that edits a
#: project's own fields: inviting another company in is a different kind of
#: decision from renaming the project, and a role that can do the second should
#: not get the first for free.
GRANT_PERMISSION = "projects.grant"

_PROJECT_NOT_FOUND = "Project not found"


@dataclass(frozen=True, slots=True)
class GrantAuthority:
    """The answer to "may this caller decide anything about this project's grants".

    Produced by :func:`resolve_grant_authority`, which raises instead of
    returning a refusal, so a value of this type always means yes. Carrying the
    project alongside the verdict is what keeps the callers from re-reading it -
    every operation needs the row it just authorized against.

    Attributes:
        project: the project the caller may grant on.
        organization_id: the caller's organization, which is the project's
            owning organization whenever this type exists. Recorded as a string
            because that is the form the ``tenant_id`` claim carries and the form
            the audit row stores, and converting it once here means no caller has
            to decide which form is right.
        user_id: the person deciding, for ``granted_by_user_id`` and the audit
            row's actor.
    """

    project: Project
    organization_id: str
    user_id: str | None


async def resolve_grant_authority(
    session: AsyncSession,
    project_id: uuid.UUID | str,
    *,
    caller_user_id: str | None,
    caller_organization_id: str | None,
    caller_role: str | None,
) -> GrantAuthority:
    """Establish that the caller's company owns the project and may decide for it.

    Args:
        session: the caller's session; nothing is committed here.
        project_id: the project to decide about.
        caller_user_id: the token's ``sub``.
        caller_organization_id: the token's ``tenant_id`` claim, which is an
            organization id and never a person's (ADR 005). ``None`` for a
            credential issued before organizations existed.
        caller_role: the membership role the token carries.

    Returns:
        A :class:`GrantAuthority` for the project.

    Raises:
        HTTPException: 404 when the project does not exist or the caller's
            company has no claim on it; 403 when the company owns the project but
            this person may not decide for it; 409 when the project has no owning
            company at all.
    """
    project = await _load_project(session, project_id)

    # No owning company means nobody can grant, and the reason is stated rather
    # than folded into a 404: this is the one refusal that is not about the
    # caller, and an operator reading it has to know the project needs its
    # ``organization_id`` backfilled before anybody can invite a participant.
    owning = project.organization_id
    if owning is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This project has no owning organization, so nobody can grant access to it. "
                "Its owner has to be resolved to a company first."
            ),
        )

    # 404 and not 403, so that "this project is not yours" and "there is no such
    # project" stay the same answer to somebody holding a list of identifiers.
    # This is also the only place a grantee's organization is refused: it is not
    # the owner, so it does not reach the person-level checks below, which is
    # what makes sub-granting impossible rather than merely forbidden.
    if caller_organization_id is None or str(owning) != caller_organization_id:
        logger.info(
            "Grant authority refused: project %s belongs to organization %s, caller named %s",
            project_id,
            owning,
            caller_organization_id,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_PROJECT_NOT_FOUND)

    if caller_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Grants are decided by a person acting for their organization.",
        )

    membership = await _active_membership(session, user_id=caller_user_id, organization_id=caller_organization_id)
    if membership is None:
        # A person who has left the company cannot decide for it. The membership
        # is checked against the database rather than taken from the token,
        # because a token outlives the membership that minted it and a suspended
        # person still holds one until it expires.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not hold an active membership in the organization that owns this project.",
        )

    role = caller_role or membership.role
    if not permission_registry.role_has_permission(role, GRANT_PERMISSION):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {GRANT_PERMISSION}",
        )

    return GrantAuthority(project=project, organization_id=caller_organization_id, user_id=caller_user_id)


async def create_grant(
    session: AsyncSession,
    authority: GrantAuthority,
    *,
    grantee_organization_id: uuid.UUID | str,
    scope: str,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProjectParticipantGrant:
    """Grant one company participation in one project, and write the audit row.

    The grantee is an organization and never a user (owner decision 8): the
    parameter is named for what it holds, and a person's id in it is refused here
    and again by the foreign key, which points at ``oe_users_organization``.

    Args:
        session: the caller's session; nothing is committed here.
        authority: the verdict from :func:`resolve_grant_authority`.
        grantee_organization_id: the company being invited in.
        scope: ``view``, ``contribute`` or ``manage``.
        valid_from: when the grant starts, or ``None`` for immediately.
        valid_until: when it stops on its own, or ``None`` for open-ended.
        reason: the human explanation, stored on the audit row rather than on the
            grant, because it describes the decision and not the access.
        metadata: free-form context for the audit row and the grant's own
            ``metadata`` column.

    Returns:
        The inserted grant, with its ``id`` populated.

    Raises:
        HTTPException: 422 for a grantee that does not exist, is the owner
            itself, or names a window that ends before it starts; 409 when a live
            grant already covers this company and project.
    """
    grantee = await _organization_or_none(session, grantee_organization_id)
    if grantee is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The organization to grant access to does not exist.",
        )

    # An owner cannot grant to itself. Not a corner case to be polite about: a
    # self-grant is a row that says the company participates in its own project,
    # which the predicate already answers from the ownership arm, and letting it
    # exist would put a row in the live set that means nothing and could not be
    # revoked without pretending something had been taken away.
    if str(grantee.id) == authority.organization_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An organization already owns this project; it cannot be granted access to its own project.",
        )

    _reject_closed_window(valid_from, valid_until)

    existing = await _live_grant(session, project_id=authority.project.id, grantee_organization_id=grantee.id)
    if existing is not None:
        # 409 and not a silent update of the row that is there: widening a scope
        # is a decision somebody has to make and see recorded, and quietly
        # turning a suspended grant into an active one would revive access that
        # was withdrawn pending review.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This organization already holds a {existing.status} grant on this project with scope "
                f"'{existing.scope}'. Change its scope or revoke it before granting again."
            ),
        )

    grant = ProjectParticipantGrant(
        project_id=authority.project.id,
        grantee_organization_id=grantee.id,
        granted_by_user_id=authority.user_id,
        granted_on_behalf_of_organization_id=authority.organization_id,
        scope=scope,
        status="active",
        valid_from=valid_from,
        valid_until=valid_until,
        metadata_=dict(metadata or {}),
    )
    session.add(grant)
    # Flushed before the audit row so the row can name the grant's id, and
    # inside the caller's transaction so neither lands without the other.
    await session.flush()

    await _audit(
        session,
        action=ACTION_GRANTED,
        grant=grant,
        actor_id=authority.user_id,
        tenant_id=authority.organization_id,
        reason=reason,
        to_status=grant.status,
        details={
            "grantee_organization_id": str(grantee.id),
            "grantee_organization_name": grantee.name,
            "scope": scope,
            "valid_from": _iso(valid_from),
            "valid_until": _iso(valid_until),
        },
    )
    logger.info(
        "Participant grant %s created: project %s -> organization %s (%s) by %s",
        grant.id,
        grant.project_id,
        grantee.id,
        scope,
        authority.user_id,
    )
    return grant


async def list_grants(
    session: AsyncSession,
    authority: GrantAuthority,
    *,
    include_revoked: bool = False,
) -> Sequence[ProjectParticipantGrant]:
    """Every grant on the project, oldest first, for the company that owns it.

    Only the owning organization can list them. A grantee cannot see the other
    participants on a project it was invited to, because who else is in the room
    is the owner's information and not a consequence of being invited.

    Args:
        session: the caller's session.
        authority: the verdict from :func:`resolve_grant_authority`.
        include_revoked: whether to return withdrawn grants as well. The default
            hides them; the rows are kept either way, so the full history is one
            query parameter away rather than a different endpoint.

    Returns:
        The grants, ordered by creation and then by id so a page of them is
        stable between two reads of an unchanged table.
    """
    stmt = (
        select(ProjectParticipantGrant)
        .where(ProjectParticipantGrant.project_id == authority.project.id)
        .order_by(ProjectParticipantGrant.created_at, ProjectParticipantGrant.id)
    )
    if not include_revoked:
        stmt = stmt.where(ProjectParticipantGrant.status != "revoked")
    return (await session.execute(stmt)).scalars().all()


async def change_scope(
    session: AsyncSession,
    authority: GrantAuthority,
    *,
    grant_id: uuid.UUID | str,
    scope: str,
    reason: str | None = None,
) -> ProjectParticipantGrant:
    """Widen or narrow what an existing grant allows, and write the audit row.

    A scope change is not a new grant: the row keeps its identity, so the
    sequence of what this company was allowed to do is readable from the audit
    log against one grant id rather than being spread across rows that each look
    like a fresh decision.

    Args:
        session: the caller's session; nothing is committed here.
        authority: the verdict from :func:`resolve_grant_authority`.
        grant_id: the grant to change.
        scope: the new scope.
        reason: the human explanation, stored on the audit row.

    Returns:
        The grant, with its new scope.

    Raises:
        HTTPException: 404 when no grant with that id belongs to this project;
            409 when the grant is revoked, because a revoked grant is history and
            changing its scope would edit the record of what was withdrawn.
    """
    grant = await _grant_on_project_or_none(session, project_id=authority.project.id, grant_id=grant_id)
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found")
    if grant.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A revoked grant is history and cannot be changed. Grant this organization access again instead.",
        )

    previous = grant.scope
    if previous == scope:
        # Not an error and not a no-op that stays silent: the row is returned
        # unchanged and nothing is written, because an audit row saying the scope
        # changed to what it already was is noise in the one log an operator
        # reads to reconstruct a decision.
        return grant

    grant.scope = scope
    await session.flush()
    await _audit(
        session,
        action=ACTION_SCOPE_CHANGED,
        grant=grant,
        actor_id=authority.user_id,
        tenant_id=authority.organization_id,
        reason=reason,
        from_status=previous,
        to_status=scope,
        details={
            "grantee_organization_id": str(grant.grantee_organization_id),
            "previous_scope": previous,
            "previous_rank": GRANT_SCOPE_RANK.get(previous),
            "scope": scope,
            "rank": GRANT_SCOPE_RANK.get(scope),
        },
    )
    logger.info("Participant grant %s scope changed: %s -> %s", grant.id, previous, scope)
    return grant


async def revoke_grant(
    session: AsyncSession,
    authority: GrantAuthority,
    *,
    grant_id: uuid.UUID | str,
    reason: str | None = None,
) -> ProjectParticipantGrant:
    """Close a company's access to a project, keeping the row and the reason.

    Revocation closes access and nothing else (owner decision 3). The rows the
    grantee wrote under the grant keep the grantee's own ``tenant_id`` and stay
    theirs: this function issues no ``UPDATE`` against any table but the grant
    table and the audit log, and the test that pins that counts the writes.

    Args:
        session: the caller's session; nothing is committed here.
        authority: the verdict from :func:`resolve_grant_authority`.
        grant_id: the grant to revoke.
        reason: the human explanation. Optional because a revocation is valid
            without one, and refusing to close access over a missing sentence
            would leave the more dangerous state - access that should have been
            withdrawn - in place.

    Returns:
        The revoked grant.

    Raises:
        HTTPException: 404 when no grant with that id belongs to this project;
            409 when it is already revoked.
    """
    grant = await _grant_on_project_or_none(session, project_id=authority.project.id, grant_id=grant_id)
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found")
    if grant.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This grant is already revoked.",
        )

    previous = grant.status
    grant.status = "revoked"
    grant.revoked_at = datetime.now(UTC)
    grant.revoked_by_user_id = authority.user_id
    grant.revocation_reason = reason
    await session.flush()
    await _audit(
        session,
        action=ACTION_REVOKED,
        grant=grant,
        actor_id=authority.user_id,
        tenant_id=authority.organization_id,
        reason=reason,
        from_status=previous,
        to_status=grant.status,
        details={
            "grantee_organization_id": str(grant.grantee_organization_id),
            "scope_at_revocation": grant.scope,
            "revoked_at": _iso(grant.revoked_at),
        },
    )
    logger.info("Participant grant %s revoked by %s", grant.id, authority.user_id)
    return grant


async def suspend_grants_on_ownership_change(
    session: AsyncSession,
    project_id: uuid.UUID | str,
    *,
    new_organization_id: str | None,
    changed_by: str | None,
    reason: str,
) -> list[ProjectParticipantGrant]:
    """Suspend every live grant on a project that has stopped belonging to its grantor.

    Owner decision 4: when a project changes hands the grants do not survive the
    change silently and are not deleted either. They are suspended, which closes
    the read predicate exactly as revocation does but keeps the row reversible,
    so the new owner reviews a list of decisions somebody else made rather than
    reconstructing them from a log.

    Grants made on behalf of the *new* owner are left alone. That is not a
    courtesy: a grant the incoming company itself wrote is a decision it has
    already made, and suspending it would ask the same person to approve their
    own signature twice.

    Args:
        session: the caller's session; nothing is committed here.
        project_id: the project whose owner changed.
        new_organization_id: the organization the project now belongs to, or
            ``None`` when it belongs to nobody - which suspends every live grant,
            because there is then nobody left who made them.
        changed_by: the person or job that made the change, for the audit row.
            ``None`` for a boot repair, which has no actor.
        reason: the human explanation recorded on every audit row written.

    Returns:
        The grants that were suspended, in the order they were created. Empty
        when there was nothing live to suspend.
    """
    stmt = (
        select(ProjectParticipantGrant)
        .where(ProjectParticipantGrant.project_id == project_id)
        # Only ``active`` ones. A grant already suspended by an earlier ownership
        # change is suspended, and re-suspending it would write a second audit
        # row for a decision that was made once - in a log whose whole purpose is
        # to say how many times something happened.
        .where(ProjectParticipantGrant.status == "active")
        .order_by(ProjectParticipantGrant.created_at, ProjectParticipantGrant.id)
    )
    grants = list((await session.execute(stmt)).scalars().all())
    if new_organization_id is not None:
        grants = [g for g in grants if str(g.granted_on_behalf_of_organization_id) != new_organization_id]
    if not grants:
        return []

    now = datetime.now(UTC)
    for grant in grants:
        previous = grant.status
        grant.status = "suspended"
        # ``revoked_at`` and ``revoked_by_user_id`` are left alone on purpose:
        # nothing was revoked, and a suspension that stamped the revocation
        # columns would make the two indistinguishable in the table that has to
        # tell them apart.
        await _audit(
            session,
            action=ACTION_SUSPENDED,
            grant=grant,
            actor_id=changed_by,
            tenant_id=str(grant.granted_on_behalf_of_organization_id),
            reason=reason,
            from_status=previous,
            to_status=grant.status,
            details={
                "grantee_organization_id": str(grant.grantee_organization_id),
                "scope": grant.scope,
                "new_organization_id": new_organization_id,
                "suspended_at": _iso(now),
            },
        )
    await session.flush()
    logger.info(
        "Suspended %d participant grant(s) on project %s: %s",
        len(grants),
        project_id,
        reason,
    )
    return grants


# ── internals ───────────────────────────────────────────────────────────────


async def _load_project(session: AsyncSession, project_id: uuid.UUID | str) -> Project:
    """The project, or a 404 that does not distinguish missing from denied."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_PROJECT_NOT_FOUND)
    return project


async def _active_membership(
    session: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
) -> Membership | None:
    """The caller's active membership in the organization they claim to act for."""
    stmt = select(Membership).where(
        Membership.user_id == user_id,
        Membership.organization_id == organization_id,
        Membership.status == MEMBERSHIP_ACTIVE,
    )
    return (await session.execute(stmt)).scalars().first()


async def _organization_or_none(session: AsyncSession, organization_id: uuid.UUID | str) -> Organization | None:
    """The grantee organization, or ``None`` when no such company exists."""
    return await session.get(Organization, organization_id)


async def _live_grant(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | str,
    grantee_organization_id: uuid.UUID | str,
) -> ProjectParticipantGrant | None:
    """The grant that the partial unique index says there is at most one of.

    Asking before inserting rather than catching the collision, because the
    answer has to name the scope and status that are already there: "this
    company is already suspended on this project" is actionable and a unique
    violation is not.
    """
    stmt = select(ProjectParticipantGrant).where(
        ProjectParticipantGrant.project_id == project_id,
        ProjectParticipantGrant.grantee_organization_id == grantee_organization_id,
        ProjectParticipantGrant.status != "revoked",
    )
    return (await session.execute(stmt)).scalars().first()


async def _grant_on_project_or_none(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | str,
    grant_id: uuid.UUID | str,
) -> ProjectParticipantGrant | None:
    """The grant, only when it belongs to this project.

    Scoped by project as well as by id: a grant id from another project has to
    produce the same 404 as one that does not exist, or the endpoint becomes a
    way to change a grant on a project the caller's company cannot see.
    """
    stmt = select(ProjectParticipantGrant).where(
        ProjectParticipantGrant.id == grant_id,
        ProjectParticipantGrant.project_id == project_id,
    )
    return (await session.execute(stmt)).scalars().first()


def _reject_closed_window(valid_from: datetime | None, valid_until: datetime | None) -> None:
    """Refuse a window that ends before it starts, before the database has to.

    The table has a check constraint for this and it would refuse the insert
    too; the difference is that an ``IntegrityError`` from a constraint surfaces
    as a 500 unless something translates it, and the caller did something wrong
    rather than something unfortunate. Naive and aware datetimes are compared by
    normalising first, because ``datetime`` refuses to order a naive value
    against an aware one and a client is free to send either.
    """
    if valid_from is None or valid_until is None:
        return
    start = valid_from if valid_from.tzinfo is not None else valid_from.replace(tzinfo=UTC)
    end = valid_until if valid_until.tzinfo is not None else valid_until.replace(tzinfo=UTC)
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="valid_until has to be later than valid_from.",
        )


def _iso(value: datetime | None) -> str | None:
    """A datetime as an ISO string for an audit row, or ``None``."""
    return value.isoformat() if value is not None else None


async def _audit(
    session: AsyncSession,
    *,
    action: str,
    grant: ProjectParticipantGrant,
    actor_id: str | None,
    tenant_id: str,
    reason: str | None,
    from_status: str | None = None,
    to_status: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """One audit row per grant event, in the caller's transaction.

    ``log_activity`` flushes and does not commit, and does not swallow its own
    errors, which is the contract this module needs: the grant and the row that
    explains it land together or the caller's transaction rolls both back.

    ``tenant_id`` is the organization that *decided*, not the one that received
    access. The audit log's tenant column says whose history this is, and a
    revocation written under the grantee's tenant would put the record of the
    decision in the ledger of the company that had no part in making it.
    """
    payload: dict[str, Any] = {
        "project_id": str(grant.project_id),
        "granted_on_behalf_of_organization_id": str(grant.granted_on_behalf_of_organization_id),
    }
    if details:
        payload.update(details)
    await log_activity(
        session,
        actor_id=actor_id,
        entity_type=GRANT_ENTITY_TYPE,
        entity_id=str(grant.id),
        action=action,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        metadata=payload,
        tenant_id=tenant_id,
        module="projects",
        parent_entity_type="project",
        parent_entity_id=str(grant.project_id),
    )


__all__ = [
    "ACTION_GRANTED",
    "ACTION_REVOKED",
    "ACTION_SCOPE_CHANGED",
    "ACTION_SUSPENDED",
    "GRANT_ENTITY_TYPE",
    "GRANT_PERMISSION",
    "GRANT_STATUSES",
    "GrantAuthority",
    "change_scope",
    "create_grant",
    "list_grants",
    "resolve_grant_authority",
    "revoke_grant",
    "suspend_grants_on_ownership_change",
]
