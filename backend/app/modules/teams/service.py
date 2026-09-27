# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Teams service - business logic for team management.

Stateless service layer. Handles:

- Team CRUD within projects
- Membership management (add / remove / change role / list)
- Record-level visibility restrictions and the reports built on them

Authorisation model
~~~~~~~~~~~~~~~~~~~
Two distinct gates, and the difference between them matters:

``_assert_project_access``
    Can the caller reach this project at all? Owner, system admin, or anyone
    holding a membership row on one of its teams. Denial is 404, so a project
    id cannot be walked to learn whether it exists. Used for every READ.

``_assert_project_admin``
    May the caller change who is on this project? Owner or system admin only.
    Denial is 403 when the caller can already see the project (they know it
    exists, so there is nothing left to leak) and 404 when they cannot. Used
    for every WRITE.

The second gate is the one that keeps the invariant. A membership row is what
:func:`app.dependencies.verify_project_access` reads to grant project access,
so anyone who can write memberships can hand out project access. Gating writes
on mere project access would therefore let a plain team member add an outsider
and give them a project they could not previously see - the exact escalation
this module exists to prevent. ``projects/router.py`` already gates its own
member endpoints on ownership (``_verify_project_owner``); this brings the
teams module in line with it instead of leaving a second, laxer door.

Elevated team roles (``owner`` / ``project_manager``) additionally carry
manager rights in other modules (``erp_chat`` reads them as such), so they stay
restricted to project owners and system admins even inside the admin gate.

Visibility restrictions
~~~~~~~~~~~~~~~~~~~~~~~
An ``EntityVisibility`` row narrows a record from "every project member" to
"the named teams, plus the project owner and system admins". It never widens.
Consumers subtract :func:`app.modules.teams.access.hidden_entity_ids` from a
set they have already decided the caller may see.
"""

import logging
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.demo_privacy import anonymize_email, should_redact
from app.core.events import event_bus
from app.modules.teams.entity_types import enforced_entity_type_keys, is_known_entity_type
from app.modules.teams.models import EntityVisibility, Team, TeamMembership
from app.modules.teams.repository import (
    MembershipRepository,
    RosterRepository,
    TeamRepository,
    VisibilityRepository,
)
from app.modules.teams.schemas import (
    ELEVATED_TEAM_ROLES,
    AccessMatrixMember,
    AccessMatrixResponse,
    AddMemberRequest,
    EntityVisibilityState,
    MembershipResponse,
    RestrictedEntityRow,
    TeamCreate,
    TeamResponse,
    TeamsValidationReport,
    TeamUpdate,
    VisibilityTeamRef,
)

logger = logging.getLogger(__name__)


@dataclass
class ActorContext:
    """What one caller is, relative to one project.

    Resolved once per request and threaded through the read paths so the
    owner / admin bypass is decided in a single place instead of being
    re-derived (and possibly re-derived differently) by each consumer.
    """

    actor_id: str | uuid.UUID | None
    is_system_admin: bool = False
    is_project_owner: bool = False
    #: Set only for a resolvable caller; ``None`` for a system call.
    user_uuid: uuid.UUID | None = None
    team_ids: set[uuid.UUID] = field(default_factory=set)

    @property
    def bypasses_restrictions(self) -> bool:
        """True when no record-level restriction applies to this caller."""
        return self.actor_id is None or self.is_system_admin or self.is_project_owner


class TeamService:
    """Business logic for team operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.team_repo = TeamRepository(session)
        self.membership_repo = MembershipRepository(session)
        self.visibility_repo = VisibilityRepository(session)
        self.roster_repo = RosterRepository(session)

    # ── RBAC helpers ─────────────────────────────────────────────────────

    async def _assert_project_access(
        self,
        project_id: uuid.UUID,
        actor_id: str | uuid.UUID | None,
    ) -> None:
        """Gate a read on project access (owner / system admin / member).

        Delegates to :func:`app.dependencies.verify_project_access`, which
        raises 404 for both "no such project" and "not yours" so an id cannot
        be walked. Centralising the call here means service-layer callers
        (cron jobs, tests, future internal modules) get the same guard as the
        HTTP router - defence in depth against routes that forget to gate.

        ``actor_id is None`` is treated as a SYSTEM call and skipped (only
        background jobs / migration helpers should pass ``None``).
        """
        if actor_id is None:
            return
        # Late-import: app.dependencies imports a lot of FastAPI machinery
        # that we don't want pulled into module-load order for tests.
        from app.dependencies import verify_project_access

        await verify_project_access(project_id, str(actor_id), self.session)

    async def _assert_project_admin(
        self,
        project_id: uuid.UUID,
        actor_id: str | uuid.UUID | None,
    ) -> None:
        """Gate a write on project ownership or system-admin status.

        Every mutation in this module goes through here. Writing a membership
        row is equivalent to granting project access, so "can already see the
        project" is not a sufficient bar - see the module docstring.

        Order matters: the access check runs first so a caller who cannot see
        the project gets 404 and learns nothing, and only a caller who can
        already see it gets the more informative 403.
        """
        if actor_id is None:
            return
        await self._assert_project_access(project_id, actor_id)
        if not await self._is_project_owner_or_admin(project_id, actor_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the project owner or a system admin may change teams on this project",
            )

    async def _assert_team_access(
        self,
        team: Team,
        actor_id: str | uuid.UUID | None,
        *,
        admin: bool = False,
    ) -> None:
        """Gate a team-scoped call, and normalise the 404 it may produce.

        The team lookup and the project check are two different steps that can
        both fail with 404, and they used to fail with two different bodies:
        "Team not found" for an id that names nothing, "Project not found" for
        an id that names a team in someone else's project. Same status, two
        answers - which is an existence oracle for team ids across the whole
        deployment. Both now answer "Team not found".

        403 is passed through untouched. It is only reachable once the caller
        has already proved they can see the project, so it discloses nothing.
        """
        try:
            if admin:
                await self._assert_project_admin(team.project_id, actor_id)
            else:
                await self._assert_project_access(team.project_id, actor_id)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team not found",
                ) from exc
            raise

    async def _is_project_owner_or_admin(
        self,
        project_id: uuid.UUID,
        actor_id: str | uuid.UUID,
    ) -> bool:
        """True iff ``actor_id`` is system admin or owner of ``project_id``.

        Returns False for ordinary project members (anyone whose access passes
        :func:`verify_project_access` only because they're already in a team) -
        we deliberately don't propagate elevation through team-membership to
        avoid infinite-bootstrap of `owner`.
        """
        from app.modules.projects.repository import ProjectRepository
        from app.modules.users.repository import UserRepository

        try:
            user_repo = UserRepository(self.session)
            user = await user_repo.get_by_id(uuid.UUID(str(actor_id)))
            if user is not None and getattr(user, "role", "") == "admin":
                return True
        except Exception:
            logger.exception("admin lookup failed during elevated-role check")

        proj_repo = ProjectRepository(self.session)
        project = await proj_repo.get_by_id(project_id)
        if project is None:
            return False
        return str(getattr(project, "owner_id", "")) == str(actor_id)

    async def resolve_actor(
        self,
        project_id: uuid.UUID,
        actor_id: str | uuid.UUID | None,
    ) -> ActorContext:
        """Classify a caller against a project after their access is confirmed.

        Never call this instead of :meth:`_assert_project_access`; call it
        after. It reports what the caller is, it does not decide whether they
        may be here.
        """
        ctx = ActorContext(actor_id=actor_id)
        if actor_id is None:
            return ctx
        try:
            ctx.user_uuid = uuid.UUID(str(actor_id))
        except (ValueError, TypeError, AttributeError):
            # Unresolvable caller: no bypass, no team memberships, so every
            # restriction applies. Fail closed.
            return ctx

        from app.modules.projects.repository import ProjectRepository
        from app.modules.users.repository import UserRepository

        try:
            user = await UserRepository(self.session).get_by_id(ctx.user_uuid)
            ctx.is_system_admin = user is not None and getattr(user, "role", "") == "admin"
        except Exception:
            logger.exception("admin lookup failed while resolving actor context")

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is not None:
            ctx.is_project_owner = str(getattr(project, "owner_id", "")) == str(actor_id)
        ctx.team_ids = await self.membership_repo.team_ids_for_user(project_id, ctx.user_uuid)
        return ctx

    # ── Teams ────────────────────────────────────────────────────────────

    async def create_team(
        self,
        data: TeamCreate,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> Team:
        """Create a new team within a project.

        After insert we *re-fetch via ``get()``* instead of returning the
        ``session.add``-ed instance directly. ``get()`` uses
        ``selectinload(memberships)`` so Pydantic's ``model_validate`` can
        access ``team.memberships`` (an empty list at this point) without
        triggering a lazy load on the detached / expired ORM object, which
        is what caused :bug:`247` (``MissingGreenlet`` under async).
        """
        await self._assert_project_admin(data.project_id, actor_id)
        team = Team(
            project_id=data.project_id,
            name=data.name,
            name_translations=data.name_translations,
            sort_order=data.sort_order,
            is_default=data.is_default,
            metadata_=data.storage_metadata(),
        )
        team = await self.team_repo.create(team)
        if data.is_default:
            # One default per project: promoting this one demotes the
            # incumbent in the same transaction.
            await self.team_repo.clear_default_flag(data.project_id, team.id)
        # Re-fetch with memberships eager-loaded so serialization is safe.
        fresh = await self.team_repo.get(team.id)
        await self._record_audit(
            actor_id=actor_id,
            team_id=team.id,
            action="created",
            metadata={"project_id": str(data.project_id), "name": data.name, "kind": data.kind},
        )
        await self._publish_event(
            "teams.team.created",
            {
                "team_id": str(team.id),
                "project_id": str(data.project_id),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Team created: %s in project %s", data.name, data.project_id)
        return fresh or team

    async def get_team(self, team_id: uuid.UUID) -> Team:
        """Get team by ID. Raises 404 if not found.

        Deliberately ungated: every caller pairs it with a project check on
        the returned ``project_id``. Keeping the lookup and the gate separate
        is what lets a router answer 404 for "team in another project" using
        the same code path as "no such team".
        """
        team = await self.team_repo.get(team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found",
            )
        return team

    async def get_team_in_project(
        self,
        team_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> Team:
        """Load a team the caller is allowed to see, or raise 404.

        The single funnel every team-scoped route uses. A team belonging to a
        project the caller cannot reach is indistinguishable from a team that
        does not exist, so ids cannot be walked to discover what exists.
        """
        team = await self.get_team(team_id)
        await self._assert_team_access(team, actor_id)
        return team

    async def list_teams(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
        include_inactive: bool = False,
    ) -> list[Team]:
        """List teams for a project.

        Gated on project access: team structure reveals who is on a project, so
        a caller must own / admin / belong to the parent project.
        ``actor_id is None`` is a SYSTEM call and skips the check, so existing
        internal callers keep working.
        """
        await self._assert_project_access(project_id, actor_id)
        return await self.team_repo.list_for_project(
            project_id,
            include_inactive=include_inactive,
        )

    async def list_teams_detailed(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
        include_inactive: bool = False,
    ) -> list[TeamResponse]:
        """Teams for a project with member and restriction counts filled in.

        Two grouped queries rather than one per team, so a project with thirty
        teams still costs three round trips.
        """
        teams = await self.list_teams(project_id, actor_id=actor_id, include_inactive=include_inactive)
        member_counts = await self.membership_repo.count_by_team_for_project(project_id)
        restriction_counts = await self.visibility_repo.count_by_team_for_project(project_id)
        out: list[TeamResponse] = []
        for team in teams:
            response = TeamResponse.model_validate(team)
            response.member_count = member_counts.get(team.id, 0)
            response.restricted_record_count = restriction_counts.get(team.id, 0)
            out.append(response)
        return out

    async def update_team(
        self,
        team_id: uuid.UUID,
        data: TeamUpdate,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> Team:
        """Update team fields."""
        team = await self.get_team(team_id)
        await self._assert_team_access(team, actor_id, admin=True)

        fields = data.model_dump(exclude_unset=True, exclude={"kind", "description", "metadata"})
        if data.touches_metadata():
            fields["metadata_"] = data.merged_metadata(team.metadata_)

        if not fields:
            return team

        await self.team_repo.update_fields(team_id, **fields)
        if fields.get("is_default") is True:
            await self.team_repo.clear_default_flag(team.project_id, team_id)
        updated = await self.team_repo.get(team_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found",
            )

        await self._record_audit(
            actor_id=actor_id,
            team_id=team_id,
            action="updated",
            metadata={"fields": list(fields.keys())},
        )
        await self._publish_event(
            "teams.team.updated",
            {
                "team_id": str(team_id),
                "project_id": str(team.project_id),
                "fields": list(fields.keys()),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Team updated: %s (fields=%s)", team_id, list(fields.keys()))
        return updated

    async def delete_team(
        self,
        team_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> None:
        """Delete a team. Cascades to memberships and visibility grants.

        Cascade is enforced at the ORM level by ``cascade='all, delete-orphan'``
        on ``Team.memberships`` and ``Team.visibility_grants``, and by
        ``ondelete='CASCADE'`` on the ``oe_teams_membership.team_id`` +
        ``oe_teams_visibility.team_id`` FKs, so no row in either child table is
        orphaned when a team disappears.

        Deleting a team that held restrictions WIDENS the records it named,
        back to "every project member", because a record with no rows left is
        unrestricted. That direction is safe by construction (nobody outside
        the project gains anything) but it is a real change, so the count goes
        into the audit row and the event payload.
        """
        team = await self.get_team(team_id)
        await self._assert_team_access(team, actor_id, admin=True)
        # Snapshot member IDs BEFORE deletion so downstream subscribers can
        # invalidate any per-user permission cache they keep.
        member_ids = [str(m.user_id) for m in (team.memberships or [])]
        restriction_count = len(await self.visibility_repo.list_for_team(team_id))
        # The roster is NOT cascaded. Those people are still on the project;
        # they have merely stopped being grouped, so their lines are detached
        # here rather than left to a database-level SET NULL that only fires
        # where foreign keys are enforced.
        released_roster = await self.roster_repo.clear_team(team_id)
        await self.team_repo.delete(team_id)
        await self._record_audit(
            actor_id=actor_id,
            team_id=team_id,
            action="deleted",
            metadata={
                "project_id": str(team.project_id),
                "member_count": len(member_ids),
                "released_restrictions": restriction_count,
                "detached_roster_lines": released_roster,
            },
        )
        await self._publish_event(
            "teams.team.deleted",
            {
                "team_id": str(team_id),
                "project_id": str(team.project_id),
                "affected_user_ids": member_ids,
                "released_restrictions": restriction_count,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Team deleted: %s (released %d restrictions)", team_id, restriction_count)

    # ── Memberships ──────────────────────────────────────────────────────

    async def _assert_assignable_role(
        self,
        project_id: uuid.UUID,
        role: str,
        actor_id: str | uuid.UUID | None,
    ) -> None:
        """Block a non-owner from handing out an ELEVATED role.

        Redundant today, because every membership write already passes the
        owner-or-admin gate. Kept as a separate, explicit check so that if the
        write gate is ever relaxed back to project access, elevation still
        cannot ride through - and so the reason for the restriction stays
        attached to the roles rather than to the caller.
        """
        if actor_id is None or role not in ELEVATED_TEAM_ROLES:
            return
        if not await self._is_project_owner_or_admin(project_id, actor_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only project owner or system admin may grant this role",
            )

    async def add_member(
        self,
        team_id: uuid.UUID,
        data: AddMemberRequest,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> TeamMembership:
        """Add a user to a team.

        RBAC: project owner or system admin only. A membership row is what
        grants project access platform-wide, so this is the escalation-critical
        write in the module - a plain team member must not be able to make one.

        The user must exist and be active. Adding a deactivated user leaves a
        dangling row that reads as project access nobody can audit back to a
        real person.
        """
        team = await self.get_team(team_id)  # Raises 404 if team not found
        await self._assert_team_access(team, actor_id, admin=True)
        await self._assert_assignable_role(team.project_id, data.role, actor_id)
        await self._assert_user_addable(data.user_id)

        # Check if already a member
        existing = await self.membership_repo.get_membership(team_id, data.user_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a member of this team",
            )

        membership = TeamMembership(
            team_id=team_id,
            user_id=data.user_id,
            role=data.role,
        )
        membership = await self.membership_repo.add(membership)
        await self._record_audit(
            actor_id=actor_id,
            team_id=team_id,
            action="member_added",
            metadata={
                "user_id": str(data.user_id),
                "role": data.role,
                "project_id": str(team.project_id),
            },
        )
        await self._publish_event(
            "teams.membership.added",
            {
                "team_id": str(team_id),
                "user_id": str(data.user_id),
                "role": data.role,
                "project_id": str(team.project_id),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Member added: user %s to team %s (%s)", data.user_id, team_id, data.role)
        return membership

    async def _assert_user_addable(self, user_id: uuid.UUID) -> None:
        """404 for an unknown user, 400 for a deactivated one.

        Mirrors ``projects.member_service.add_project_member`` so both doors
        into the same table apply the same rule.
        """
        from app.modules.users.repository import UserRepository

        user = await UserRepository(self.session).get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if not getattr(user, "is_active", True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add a deactivated user to a team",
            )

    async def update_member_role(
        self,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> TeamMembership:
        """Change the role a user holds inside a team.

        Same gate as adding one: an in-place promotion into an ELEVATED role
        would otherwise be a way around the add-time check.
        """
        team = await self.get_team(team_id)
        await self._assert_team_access(team, actor_id, admin=True)
        await self._assert_assignable_role(team.project_id, role, actor_id)

        existing = await self.membership_repo.get_membership(team_id, user_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membership not found",
            )
        previous_role = existing.role
        if previous_role == role:
            return existing

        await self.membership_repo.set_role(team_id, user_id, role)
        updated = await self.membership_repo.get_membership(team_id, user_id)
        if updated is None:  # pragma: no cover - row vanished mid-transaction
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membership not found",
            )
        await self._record_audit(
            actor_id=actor_id,
            team_id=team_id,
            action="member_role_changed",
            metadata={
                "user_id": str(user_id),
                "from_role": previous_role,
                "to_role": role,
                "project_id": str(team.project_id),
            },
        )
        await self._publish_event(
            "teams.membership.role_changed",
            {
                "team_id": str(team_id),
                "user_id": str(user_id),
                "from_role": previous_role,
                "to_role": role,
                "project_id": str(team.project_id),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Member role changed: user %s on team %s (%s -> %s)", user_id, team_id, previous_role, role)
        return updated

    async def remove_member(
        self,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> None:
        """Remove a user from a team."""
        team = await self.get_team(team_id)  # Raises 404 if team not found
        await self._assert_team_access(team, actor_id, admin=True)
        removed = await self.membership_repo.remove(team_id, user_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membership not found",
            )
        await self._record_audit(
            actor_id=actor_id,
            team_id=team_id,
            action="member_removed",
            metadata={
                "user_id": str(user_id),
                "project_id": str(team.project_id),
            },
        )
        # Publish so any per-user permission cache can drop ``user_id``'s
        # entry - they no longer inherit this team's grants.
        await self._publish_event(
            "teams.membership.removed",
            {
                "team_id": str(team_id),
                "user_id": str(user_id),
                "project_id": str(team.project_id),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Member removed: user %s from team %s", user_id, team_id)

    async def list_members(
        self,
        team_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> list[TeamMembership]:
        """List members of a team.

        Gated on project access: team membership is sensitive (it reveals who
        is on a project), so a caller must own / admin / belong to the parent
        project. ``actor_id is None`` is a SYSTEM call and skips the check.
        """
        await self.get_team_in_project(team_id, actor_id=actor_id)
        return await self.membership_repo.list_for_team(team_id)

    async def list_members_detailed(
        self,
        team_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> list[MembershipResponse]:
        """Members of a team with their email and display name resolved."""
        await self.get_team_in_project(team_id, actor_id=actor_id)
        rows = await self.membership_repo.list_for_team_with_users(team_id)
        out: list[MembershipResponse] = []
        for membership, user in rows:
            response = MembershipResponse.model_validate(membership)
            if user is not None:
                if should_redact(user.id, actor_id):
                    # Public hosted demo: other people's identity stays hidden.
                    response.email = anonymize_email(user.email)
                    response.full_name = ""
                else:
                    response.email = user.email or ""
                    response.full_name = user.full_name or ""
                response.is_active = bool(getattr(user, "is_active", True))
            else:
                # The user row is gone but the membership survived; surface it
                # so the dangling grant can be cleared rather than hidden.
                response.is_active = False
            out.append(response)
        return out

    # ── Visibility restrictions ──────────────────────────────────────────

    def _assert_known_entity_type(self, entity_type: str) -> None:
        """422 for a record kind outside the catalogue.

        A restriction on an unrecognised kind is enforced by nobody, so it
        reads as protection that is not there. Rejecting at the edge is the
        only point where that is still fixable by the person typing it.
        """
        if not is_known_entity_type(entity_type):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"'{entity_type}' is not a record kind that can be restricted",
            )

    async def grant_visibility(
        self,
        entity_type: str,
        entity_id: str,
        team_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> EntityVisibility:
        """Restrict a record to a team.

        The first row on a record turns it from open-to-the-project into
        restricted; later rows add another team to the list that may see it.
        Neither direction can reach a user who has no access to the project,
        because a restriction is only ever consulted after project access has
        already been established.
        """
        self._assert_known_entity_type(entity_type)
        team = await self.get_team(team_id)  # Raises 404 if team not found
        await self._assert_team_access(team, actor_id, admin=True)

        existing = await self.visibility_repo.list_for_entity(
            entity_type,
            entity_id,
            project_id=team.project_id,
        )
        if any(row.team_id == team_id for row in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This record is already restricted to that team",
            )

        visibility = EntityVisibility(
            entity_type=entity_type,
            entity_id=entity_id,
            team_id=team_id,
        )
        visibility = await self.visibility_repo.grant(visibility)
        await self._record_audit(
            actor_id=actor_id,
            team_id=team_id,
            action="visibility_granted",
            metadata={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": str(team.project_id),
                "first_restriction": not existing,
            },
        )
        await self._publish_event(
            "teams.visibility.granted",
            {
                "team_id": str(team_id),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": str(team.project_id),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Record restricted: %s/%s to team %s", entity_type, entity_id, team_id)
        return visibility

    async def revoke_visibility(
        self,
        entity_type: str,
        entity_id: str,
        team_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> None:
        """Drop one team from a record's restriction list.

        Removing the last row lifts the restriction entirely and returns the
        record to every project member.
        """
        self._assert_known_entity_type(entity_type)
        team = await self.get_team(team_id)
        await self._assert_team_access(team, actor_id, admin=True)
        removed = await self.visibility_repo.revoke(entity_type, entity_id, team_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Restriction not found",
            )
        remaining = await self.visibility_repo.list_for_entity(
            entity_type,
            entity_id,
            project_id=team.project_id,
        )
        await self._record_audit(
            actor_id=actor_id,
            team_id=team_id,
            action="visibility_revoked",
            metadata={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": str(team.project_id),
                "now_unrestricted": not remaining,
            },
        )
        await self._publish_event(
            "teams.visibility.revoked",
            {
                "team_id": str(team_id),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": str(team.project_id),
                "now_unrestricted": not remaining,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info("Restriction lifted: %s/%s from team %s", entity_type, entity_id, team_id)

    async def set_entity_visibility(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: str,
        team_ids: list[uuid.UUID],
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> EntityVisibilityState:
        """Replace the whole set of teams a record is restricted to.

        The operation the UI performs: tick the teams, save once. An empty list
        lifts the restriction. Every id must name a team of ``project_id`` -
        one that does not answers 404, which is also the answer for a team that
        does not exist, so the endpoint cannot be used to probe another
        project's team ids.
        """
        self._assert_known_entity_type(entity_type)
        await self._assert_project_admin(project_id, actor_id)

        resolved = await self.team_repo.list_in_project(project_id, team_ids)
        if len(resolved) != len(set(team_ids)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        previous = await self.visibility_repo.list_for_entity(entity_type, entity_id, project_id=project_id)
        previous_ids = {row.team_id for row in previous}
        wanted = {team.id for team in resolved}
        if previous_ids == wanted:
            return await self.describe_entity_visibility(
                project_id,
                entity_type,
                entity_id,
                actor_id=actor_id,
            )

        await self.visibility_repo.revoke_all_in_project(project_id, entity_type, entity_id)
        for team_id in wanted:
            await self.visibility_repo.grant(
                EntityVisibility(entity_type=entity_type, entity_id=entity_id, team_id=team_id)
            )

        await self._record_audit(
            actor_id=actor_id,
            team_id=next(iter(wanted)) if wanted else next(iter(previous_ids), uuid.UUID(int=0)),
            action="visibility_set",
            metadata={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": str(project_id),
                "from_team_ids": sorted(str(t) for t in previous_ids),
                "to_team_ids": sorted(str(t) for t in wanted),
            },
        )
        await self._publish_event(
            "teams.visibility.set",
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": str(project_id),
                "team_ids": sorted(str(t) for t in wanted),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        logger.info(
            "Restriction set: %s/%s now visible to %d team(s)",
            entity_type,
            entity_id,
            len(wanted),
        )
        return await self.describe_entity_visibility(project_id, entity_type, entity_id, actor_id=actor_id)

    async def list_entity_visibility(
        self,
        entity_type: str,
        entity_id: str,
        *,
        project_id: uuid.UUID | None = None,
    ) -> list[EntityVisibility]:
        """Raw restriction rows for a record.

        Kept as the low-level accessor for internal callers.
        :meth:`describe_entity_visibility` is the gated, display-ready form
        every HTTP route should use instead.
        """
        return await self.visibility_repo.list_for_entity(entity_type, entity_id, project_id=project_id)

    async def describe_entity_visibility(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: str,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> EntityVisibilityState:
        """Who can see one record, for the visibility panel.

        Read-gated on project access only: knowing that a record you can
        already reach is restricted, and to whom, is part of working on a
        shared project. It does not reveal the record's contents.
        """
        self._assert_known_entity_type(entity_type)
        await self._assert_project_access(project_id, actor_id)
        rows = await self.visibility_repo.list_for_entity(entity_type, entity_id, project_id=project_id)
        team_ids = [row.team_id for row in rows]
        teams = await self.team_repo.list_in_project(project_id, team_ids)
        member_counts = await self.membership_repo.count_by_team_for_project(project_id)
        viewers = await self.membership_repo.distinct_user_ids_for_teams(team_ids)
        # Whether the caller themselves survives the current restriction. Read
        # off the same team membership the resolver uses, so the panel's warning
        # and the actual filter cannot disagree.
        actor = await self.resolve_actor(project_id, actor_id)
        caller_can_see = True if not rows or actor.bypasses_restrictions else bool(actor.team_ids & set(team_ids))
        return EntityVisibilityState(
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            restricted=bool(rows),
            teams=[
                VisibilityTeamRef(
                    team_id=team.id,
                    name=team.name,
                    kind=str((team.metadata_ or {}).get("kind") or "internal"),
                    is_active=team.is_active,
                    member_count=member_counts.get(team.id, 0),
                )
                for team in sorted(teams, key=lambda t: (t.sort_order, t.name))
            ],
            viewer_count=len(viewers),
            enforced=entity_type in enforced_entity_type_keys(),
            caller_can_see=caller_can_see,
        )

    async def list_team_visibility(
        self,
        team_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> list[EntityVisibility]:
        """Every record restricted to one team."""
        await self.get_team_in_project(team_id, actor_id=actor_id)
        return await self.visibility_repo.list_for_team(team_id)

    async def list_restricted_entities(
        self,
        project_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        actor_id: str | uuid.UUID | None = None,
    ) -> list[RestrictedEntityRow]:
        """The project's restriction register: every record that is not open.

        The screen an operations lead opens to answer "what have we locked
        down, and can anyone still read it".
        """
        if entity_type is not None:
            self._assert_known_entity_type(entity_type)
        await self._assert_project_access(project_id, actor_id)
        rows = await self.visibility_repo.list_for_project(project_id, entity_type=entity_type)
        enforced = enforced_entity_type_keys()
        # One pass over the project's memberships, then set arithmetic per
        # record. Querying the viewer count per record would be one round trip
        # per restricted record, which on a locked-down project is thousands.
        members_by_team = await self._members_by_team(project_id)

        grouped: dict[tuple[str, str], list[Team]] = {}
        for visibility, team in rows:
            grouped.setdefault((visibility.entity_type, visibility.entity_id), []).append(team)

        register: list[RestrictedEntityRow] = []
        for (kind, entity_id), teams in sorted(grouped.items()):
            ordered = sorted(teams, key=lambda t: (t.sort_order, t.name))
            viewers: set[uuid.UUID] = set()
            for team in ordered:
                viewers |= members_by_team.get(team.id, set())
            register.append(
                RestrictedEntityRow(
                    entity_type=kind,
                    entity_id=entity_id,
                    team_ids=[t.id for t in ordered],
                    team_names=[t.name for t in ordered],
                    viewer_count=len(viewers),
                    enforced=kind in enforced,
                )
            )
        return register

    async def _members_by_team(self, project_id: uuid.UUID) -> dict[uuid.UUID, set[uuid.UUID]]:
        """team id -> the users on it, for every team of the project."""
        out: dict[uuid.UUID, set[uuid.UUID]] = {}
        for membership, team, _user in await self.membership_repo.list_for_project_with_users(project_id):
            out.setdefault(team.id, set()).add(membership.user_id)
        return out

    async def build_access_matrix(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> AccessMatrixResponse:
        """Per-person reach across the project's restricted records.

        Answers "who on this project can still open the restricted records"
        in one payload, which is the question an operations lead actually asks
        before a client walkthrough or a subcontractor handover.

        Read-gated on project access. It reports on people who are already
        visible to the caller through the member list, and on restriction rows
        the caller can already list, so it discloses nothing new.
        """
        await self._assert_project_access(project_id, actor_id)

        rows = await self.visibility_repo.list_for_project(project_id)
        # (entity_type, entity_id) -> the teams allowed to see it
        by_entity: dict[tuple[str, str], set[uuid.UUID]] = {}
        for visibility, team in rows:
            by_entity.setdefault((visibility.entity_type, visibility.entity_id), set()).add(team.id)
        total_restricted = len(by_entity)

        memberships = await self.membership_repo.list_for_project_with_users(project_id)
        owner_id = await self._project_owner_id(project_id)

        # user -> (teams, roles, display fields)
        people: dict[uuid.UUID, AccessMatrixMember] = {}
        for membership, team, user in memberships:
            person = people.get(membership.user_id)
            if person is None:
                email = (user.email or "") if user is not None else ""
                full_name = (user.full_name or "") if user is not None else ""
                if should_redact(membership.user_id, actor_id):
                    # Public hosted demo: other people's identity stays hidden.
                    email, full_name = anonymize_email(email), ""
                person = AccessMatrixMember(
                    user_id=membership.user_id,
                    email=email,
                    full_name=full_name,
                    is_project_owner=owner_id is not None and membership.user_id == owner_id,
                    is_system_admin=(getattr(user, "role", "") == "admin") if user is not None else False,
                )
                people[membership.user_id] = person
            person.team_ids.append(team.id)
            person.team_names.append(team.name)
            if membership.role not in person.roles:
                person.roles.append(membership.role)

        for person in people.values():
            if person.is_project_owner or person.is_system_admin:
                person.visible_restricted_count = total_restricted
                person.hidden_restricted_count = 0
                continue
            held = set(person.team_ids)
            visible = sum(1 for allowed in by_entity.values() if held & allowed)
            person.visible_restricted_count = visible
            person.hidden_restricted_count = total_restricted - visible

        return AccessMatrixResponse(
            project_id=project_id,
            restricted_record_count=total_restricted,
            members=sorted(people.values(), key=lambda m: m.full_name or m.email or str(m.user_id)),
        )

    # ── Validation ───────────────────────────────────────────────────────

    async def validate_project(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> TeamsValidationReport:
        """Run the ``teams`` rule set over one project's access configuration.

        Gated on project access before anything is read, so the report can
        never be used to learn about a project the caller cannot reach.
        """
        from app.modules.teams.validators import evaluate_project_teams

        await self._assert_project_access(project_id, actor_id)
        return await evaluate_project_teams(self.session, project_id)

    async def _project_owner_id(self, project_id: uuid.UUID) -> uuid.UUID | None:
        """The project's owner id, or ``None`` when the project is gone."""
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None:
            return None
        owner_id = getattr(project, "owner_id", None)
        return owner_id if isinstance(owner_id, uuid.UUID) else None

    # ── Audit + events (best-effort) ─────────────────────────────────────

    async def _record_audit(
        self,
        *,
        actor_id: str | uuid.UUID | None,
        team_id: uuid.UUID,
        action: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Write a single audit row; never let a logging failure abort the
        business write. Team modifications change RBAC outcomes, so they
        MUST land in the activity log for compliance trails.
        """
        try:
            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="team",
                entity_id=str(team_id),
                action=action,
                metadata=metadata,
            )
        except Exception:  # pragma: no cover - best-effort audit
            logger.exception("audit write failed for team=%s action=%s", team_id, action)

    async def _publish_event(self, name: str, payload: dict[str, object]) -> None:
        """Publish a teams.* event so permission caches / notifications /
        analytics subscribers can react. Failures are swallowed because the
        business write has already committed and event delivery is an
        eventual-consistency concern.
        """
        try:
            publish_detached = getattr(event_bus, "publish_detached", None)
            if publish_detached is not None:
                publish_detached(name, payload, source_module="oe_teams")
            else:
                await event_bus.publish(name, payload, source_module="oe_teams")
        except Exception:  # pragma: no cover - best-effort fanout
            logger.exception("event publish failed: %s", name)
