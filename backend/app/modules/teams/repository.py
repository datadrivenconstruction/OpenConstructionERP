# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Teams data access layer.

All database queries for teams, memberships, and visibility restrictions live
here. No business logic - pure data access.

Every restriction query is scoped by ``project_id`` through a join on
``Team.project_id``. That is not an optimisation: it is what stops a row
written against a team in one project from changing what anyone sees in
another. A caller that hands this layer an ``entity_id`` without the project it
belongs to cannot get a restriction answer, by design.
"""

import uuid

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.teams.models import EntityVisibility, RosterMember, Team, TeamMembership
from app.modules.users.models import User


class TeamRepository:
    """Data access for Team model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, team_id: uuid.UUID) -> Team | None:
        """Get team by ID (with memberships eager-loaded)."""
        stmt = select(Team).where(Team.id == team_id).options(selectinload(Team.memberships))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        include_inactive: bool = False,
    ) -> list[Team]:
        """List teams for a project, ordered by sort_order."""
        stmt = select(Team).where(Team.project_id == project_id)
        if not include_inactive:
            stmt = stmt.where(Team.is_active.is_(True))
        stmt = stmt.order_by(Team.sort_order, Team.name)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_in_project(
        self,
        project_id: uuid.UUID,
        team_ids: list[uuid.UUID],
    ) -> list[Team]:
        """The subset of ``team_ids`` that actually belongs to ``project_id``.

        A caller compares the length of the result against its input to detect
        an id that names a team in some other project (or no team at all) and
        answer 404 without ever revealing which of the two it was.
        """
        if not team_ids:
            return []
        stmt = select(Team).where(Team.project_id == project_id, Team.id.in_(team_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_default_for_project(self, project_id: uuid.UUID) -> int:
        """How many active teams in the project are flagged as the default one."""
        stmt = select(func.count()).select_from(
            select(Team.id)
            .where(
                Team.project_id == project_id,
                Team.is_default.is_(True),
                Team.is_active.is_(True),
            )
            .subquery()
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def clear_default_flag(self, project_id: uuid.UUID, keep_team_id: uuid.UUID) -> None:
        """Drop ``is_default`` from every team of the project except ``keep_team_id``.

        A project resolves "add a member" through its one default team, so two
        defaults make that resolution arbitrary. Promoting a team demotes the
        incumbent in the same transaction rather than leaving a rule to
        complain about it afterwards.

        Written through the ORM objects rather than as a bulk UPDATE plus
        ``expire_all()``. A blanket expire would also invalidate the caller's
        own ``Team`` instance, and the next attribute read on it fires a
        refresh from async context, which surfaces as ``MissingGreenlet`` some
        distance from here.
        """
        stmt = select(Team).where(
            Team.project_id == project_id,
            Team.id != keep_team_id,
            Team.is_default.is_(True),
        )
        for team in (await self.session.execute(stmt)).scalars().all():
            team.is_default = False
        await self.session.flush()

    async def create(self, team: Team) -> Team:
        """Insert a new team."""
        self.session.add(team)
        await self.session.flush()
        return team

    async def update_fields(self, team_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a team."""
        stmt = update(Team).where(Team.id == team_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(Team, team_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, team_id: uuid.UUID) -> None:
        """Hard delete a team (cascades to memberships and visibility)."""
        team = await self.get(team_id)
        if team is not None:
            await self.session.delete(team)
            await self.session.flush()


class MembershipRepository:
    """Data access for TeamMembership model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_team(self, team_id: uuid.UUID) -> list[TeamMembership]:
        """List all memberships for a team."""
        stmt = select(TeamMembership).where(TeamMembership.team_id == team_id).order_by(TeamMembership.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_team_with_users(
        self,
        team_id: uuid.UUID,
    ) -> list[tuple[TeamMembership, User | None]]:
        """Memberships joined to their user rows, for a member list with names.

        An OUTER join: a membership whose user row was hard-deleted must still
        appear so an operations lead can see and clear the dangling row rather
        than have it silently vanish from the list.
        """
        stmt = (
            select(TeamMembership, User)
            .outerjoin(User, User.id == TeamMembership.user_id)
            .where(TeamMembership.team_id == team_id)
            .order_by(TeamMembership.created_at)
        )
        return [(m, u) for m, u in (await self.session.execute(stmt)).all()]

    async def list_for_project_with_users(
        self,
        project_id: uuid.UUID,
    ) -> list[tuple[TeamMembership, Team, User | None]]:
        """Every membership in a project, with its team and user rows."""
        stmt = (
            select(TeamMembership, Team, User)
            .join(Team, Team.id == TeamMembership.team_id)
            .outerjoin(User, User.id == TeamMembership.user_id)
            .where(Team.project_id == project_id)
            .order_by(Team.sort_order, Team.name, TeamMembership.created_at)
        )
        return [(m, t, u) for m, t, u in (await self.session.execute(stmt)).all()]

    async def get_membership(
        self,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> TeamMembership | None:
        """Get a specific membership."""
        stmt = select(TeamMembership).where(
            TeamMembership.team_id == team_id,
            TeamMembership.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, membership: TeamMembership) -> TeamMembership:
        """Insert a new membership."""
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def set_role(
        self,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
    ) -> bool:
        """Change a membership's role. Returns True if the row existed.

        Assigns on the ORM instance rather than issuing a bulk UPDATE. The row
        is very likely already in the identity map behind an eager
        ``Team.memberships`` load, and a bulk UPDATE would leave that copy
        stale; the alternative fix, ``expire_all()``, invalidates the caller's
        own objects too and turns their next attribute read into a
        ``MissingGreenlet``.
        """
        membership = await self.get_membership(team_id, user_id)
        if membership is None:
            return False
        membership.role = role
        await self.session.flush()
        return True

    async def remove(self, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Remove a membership. Returns True if it existed."""
        stmt = delete(TeamMembership).where(
            TeamMembership.team_id == team_id,
            TeamMembership.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def count_for_team(self, team_id: uuid.UUID) -> int:
        """Count members in a team."""
        stmt = select(func.count()).select_from(
            select(TeamMembership).where(TeamMembership.team_id == team_id).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_by_team_for_project(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Member counts for every team of a project, in one round trip."""
        stmt = (
            select(TeamMembership.team_id, func.count(TeamMembership.id))
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.project_id == project_id)
            .group_by(TeamMembership.team_id)
        )
        return {team_id: int(count) for team_id, count in (await self.session.execute(stmt)).all()}

    async def team_ids_for_user(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        """The teams of ``project_id`` that ``user_id`` belongs to."""
        stmt = (
            select(TeamMembership.team_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.project_id == project_id, TeamMembership.user_id == user_id)
        )
        return {row for (row,) in (await self.session.execute(stmt)).all()}

    async def distinct_user_ids_for_teams(self, team_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """The distinct users reachable through any of ``team_ids``."""
        if not team_ids:
            return set()
        stmt = select(TeamMembership.user_id).where(TeamMembership.team_id.in_(team_ids)).distinct()
        return {row for (row,) in (await self.session.execute(stmt)).all()}


class VisibilityRepository:
    """Data access for EntityVisibility model.

    Every read here is subtractive: it answers "which records are restricted"
    and "which of those may this user still open". Nothing in this class can
    report a record as reachable that carries no restriction row, so it can
    never be used to widen access.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reads scoped to a project ────────────────────────────────────────

    def _project_scoped(self, project_id: uuid.UUID) -> Select:
        """Base select over restriction rows whose team belongs to the project."""
        return (
            select(EntityVisibility)
            .join(Team, Team.id == EntityVisibility.team_id)
            .where(Team.project_id == project_id)
        )

    async def list_for_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        project_id: uuid.UUID | None = None,
    ) -> list[EntityVisibility]:
        """Restriction rows on one record.

        ``project_id`` scopes the answer to teams of that project. Callers on
        an access path must always pass it; the unscoped form exists only for
        the cross-project consistency rule, which needs to see the rows a
        scoped query would filter out.
        """
        stmt = self._project_scoped(project_id) if project_id is not None else select(EntityVisibility)
        stmt = stmt.where(
            EntityVisibility.entity_type == entity_type,
            EntityVisibility.entity_id == entity_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_team(self, team_id: uuid.UUID) -> list[EntityVisibility]:
        """Every record restricted to one team."""
        stmt = (
            select(EntityVisibility)
            .where(EntityVisibility.team_id == team_id)
            .order_by(EntityVisibility.entity_type, EntityVisibility.entity_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        entity_type: str | None = None,
    ) -> list[tuple[EntityVisibility, Team]]:
        """Every restriction in a project, with the team it names."""
        stmt = (
            select(EntityVisibility, Team)
            .join(Team, Team.id == EntityVisibility.team_id)
            .where(Team.project_id == project_id)
        )
        if entity_type is not None:
            stmt = stmt.where(EntityVisibility.entity_type == entity_type)
        stmt = stmt.order_by(EntityVisibility.entity_type, EntityVisibility.entity_id)
        return [(v, t) for v, t in (await self.session.execute(stmt)).all()]

    async def count_by_team_for_project(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Restriction counts per team, in one round trip."""
        stmt = (
            select(EntityVisibility.team_id, func.count(EntityVisibility.id))
            .join(Team, Team.id == EntityVisibility.team_id)
            .where(Team.project_id == project_id)
            .group_by(EntityVisibility.team_id)
        )
        return {team_id: int(count) for team_id, count in (await self.session.execute(stmt)).all()}

    async def restricted_entity_ids(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        *,
        entity_ids: list[str] | None = None,
    ) -> set[str]:
        """The ids of ``entity_type`` records in the project that carry a restriction."""
        stmt = (
            select(EntityVisibility.entity_id)
            .join(Team, Team.id == EntityVisibility.team_id)
            .where(Team.project_id == project_id, EntityVisibility.entity_type == entity_type)
        )
        if entity_ids is not None:
            if not entity_ids:
                return set()
            stmt = stmt.where(EntityVisibility.entity_id.in_(entity_ids))
        return {row for (row,) in (await self.session.execute(stmt.distinct())).all()}

    async def entity_ids_visible_to_user(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        user_id: uuid.UUID,
        *,
        entity_ids: list[str] | None = None,
    ) -> set[str]:
        """Restricted ids this user is still allowed to open, via team membership.

        Only meaningful when subtracted from
        :meth:`restricted_entity_ids`: an id absent from this set is either
        unrestricted (so freely visible) or restricted away from the user. The
        two are told apart by the caller, never by this query alone.
        """
        stmt = (
            select(EntityVisibility.entity_id)
            .join(Team, Team.id == EntityVisibility.team_id)
            .join(TeamMembership, TeamMembership.team_id == EntityVisibility.team_id)
            .where(
                Team.project_id == project_id,
                EntityVisibility.entity_type == entity_type,
                TeamMembership.user_id == user_id,
            )
        )
        if entity_ids is not None:
            if not entity_ids:
                return set()
            stmt = stmt.where(EntityVisibility.entity_id.in_(entity_ids))
        return {row for (row,) in (await self.session.execute(stmt.distinct())).all()}

    # ── Writes ───────────────────────────────────────────────────────────

    async def grant(self, visibility: EntityVisibility) -> EntityVisibility:
        """Create a restriction row."""
        self.session.add(visibility)
        await self.session.flush()
        return visibility

    async def revoke(
        self,
        entity_type: str,
        entity_id: str,
        team_id: uuid.UUID,
    ) -> bool:
        """Drop one restriction row. Returns True if it existed."""
        stmt = delete(EntityVisibility).where(
            EntityVisibility.entity_type == entity_type,
            EntityVisibility.entity_id == entity_id,
            EntityVisibility.team_id == team_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def revoke_all_in_project(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: str,
    ) -> int:
        """Drop every restriction on one record, within one project.

        Scoped by project so lifting a restriction can never reach a row a
        different project wrote against the same ``entity_id`` string.
        """
        team_ids = select(Team.id).where(Team.project_id == project_id).scalar_subquery()
        stmt = delete(EntityVisibility).where(
            EntityVisibility.entity_type == entity_type,
            EntityVisibility.entity_id == entity_id,
            EntityVisibility.team_id.in_(team_ids),
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)  # type: ignore[union-attr]


class RosterRepository:
    """Data access for the project roster.

    Scoped by ``project_id`` on every read and every write. A roster line is
    reached through the project it belongs to and never through its id alone,
    so an id from another project cannot be edited by guessing it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        include_inactive: bool = True,
    ) -> list[tuple[RosterMember, Team | None, User | None]]:
        """The whole roster, with each line's team and linked user row.

        Both joins are OUTER. A line for somebody with no login has no user
        row, and a line whose team was deleted has no team row; either one
        disappearing from the list would hide a person who is still on site.

        Ordered so the screen reads like a roster and not like a table: teams
        in their configured order, unassigned people last, and inside a team
        the supervisory roles first is left to the service, which knows the
        role ranking.
        """
        stmt = (
            select(RosterMember, Team, User)
            .outerjoin(Team, Team.id == RosterMember.team_id)
            .outerjoin(User, User.id == RosterMember.user_id)
            .where(RosterMember.project_id == project_id)
        )
        if not include_inactive:
            stmt = stmt.where(RosterMember.is_active.is_(True))
        stmt = stmt.order_by(RosterMember.display_name)
        return [(m, t, u) for m, t, u in (await self.session.execute(stmt)).all()]

    async def get_in_project(
        self,
        project_id: uuid.UUID,
        member_id: uuid.UUID,
    ) -> RosterMember | None:
        """One roster line, only if it belongs to ``project_id``."""
        stmt = select(RosterMember).where(
            RosterMember.id == member_id,
            RosterMember.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def linked_ids(self, project_id: uuid.UUID) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        """The user ids and contact ids already on this project's roster.

        Read before an add so the candidate list can mark who is already there,
        and so a bulk add can skip a duplicate instead of failing the whole
        request on one unique-index violation.
        """
        stmt = select(RosterMember.user_id, RosterMember.contact_id).where(RosterMember.project_id == project_id)
        user_ids: set[uuid.UUID] = set()
        contact_ids: set[uuid.UUID] = set()
        for user_id, contact_id in (await self.session.execute(stmt)).all():
            if user_id is not None:
                user_ids.add(user_id)
            if contact_id is not None:
                contact_ids.add(contact_id)
        return user_ids, contact_ids

    async def add(self, member: RosterMember) -> RosterMember:
        """Insert one roster line."""
        self.session.add(member)
        await self.session.flush()
        return member

    async def add_all(self, members: list[RosterMember]) -> list[RosterMember]:
        """Insert several roster lines in one flush."""
        if not members:
            return []
        self.session.add_all(members)
        await self.session.flush()
        return members

    async def update_fields(self, member: RosterMember, fields: dict[str, object]) -> RosterMember:
        """Write the named columns onto an already-loaded roster line.

        Assigns on the instance rather than issuing a bulk UPDATE: the row was
        just read through :meth:`get_in_project`, so a bulk statement would
        leave that copy stale, and the blanket ``expire_all`` that would fix it
        turns the caller's next attribute read into a ``MissingGreenlet``.
        """
        for name, value in fields.items():
            setattr(member, name, value)
        await self.session.flush()
        return member

    async def delete(self, member: RosterMember) -> None:
        """Remove one roster line."""
        await self.session.delete(member)
        await self.session.flush()

    async def clear_team(self, team_id: uuid.UUID) -> int:
        """Detach every roster line from a team that is about to be deleted.

        Deleting a team must not delete the people: they are still on the
        project, just no longer grouped. The column is cleared here, in the
        same transaction as the delete, rather than left to a database-level
        ``ON DELETE SET NULL`` that only fires where foreign keys are actually
        enforced.
        """
        stmt = update(RosterMember).where(RosterMember.team_id == team_id).values(team_id=None)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)  # type: ignore[union-attr]

    async def count_by_team(self, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Active roster headcount per team, in one round trip."""
        stmt = (
            select(RosterMember.team_id, func.count(RosterMember.id))
            .where(
                RosterMember.project_id == project_id,
                RosterMember.team_id.is_not(None),
                RosterMember.is_active.is_(True),
            )
            .group_by(RosterMember.team_id)
        )
        return {team_id: int(count) for team_id, count in (await self.session.execute(stmt)).all()}
