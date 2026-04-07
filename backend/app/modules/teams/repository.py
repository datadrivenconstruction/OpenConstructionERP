"""Teams data access layer.

All database queries for teams, memberships, and visibility live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.teams.models import EntityVisibility, Team, TeamMembership


class TeamRepository:
    """Data access for Team model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, team_id: uuid.UUID) -> Team | None:
        """Get team by ID."""
        return await self.session.get(Team, team_id)

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
        self.session.expire_all()

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
        stmt = (
            select(TeamMembership)
            .where(TeamMembership.team_id == team_id)
            .order_by(TeamMembership.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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


class VisibilityRepository:
    """Data access for EntityVisibility model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[EntityVisibility]:
        """List visibility grants for an entity."""
        stmt = select(EntityVisibility).where(
            EntityVisibility.entity_type == entity_type,
            EntityVisibility.entity_id == entity_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def grant(self, visibility: EntityVisibility) -> EntityVisibility:
        """Create a visibility grant."""
        self.session.add(visibility)
        await self.session.flush()
        return visibility

    async def revoke(
        self,
        entity_type: str,
        entity_id: str,
        team_id: uuid.UUID,
    ) -> bool:
        """Revoke a visibility grant. Returns True if it existed."""
        stmt = delete(EntityVisibility).where(
            EntityVisibility.entity_type == entity_type,
            EntityVisibility.entity_id == entity_id,
            EntityVisibility.team_id == team_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]
