"""Teams service — business logic for team management.

Stateless service layer. Handles:
- Team CRUD within projects
- Membership management (add / remove / list)
- Entity visibility grants
"""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.teams.models import EntityVisibility, Team, TeamMembership
from app.modules.teams.repository import MembershipRepository, TeamRepository, VisibilityRepository
from app.modules.teams.schemas import AddMemberRequest, TeamCreate, TeamUpdate

logger = logging.getLogger(__name__)


class TeamService:
    """Business logic for team operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.team_repo = TeamRepository(session)
        self.membership_repo = MembershipRepository(session)
        self.visibility_repo = VisibilityRepository(session)

    # ── Teams ────────────────────────────────────────────────────────────

    async def create_team(self, data: TeamCreate) -> Team:
        """Create a new team within a project.

        After insert we *re-fetch via ``get()``* instead of returning the
        ``session.add``-ed instance directly. ``get()`` uses
        ``selectinload(memberships)`` so Pydantic's ``model_validate`` can
        access ``team.memberships`` (an empty list at this point) without
        triggering a lazy load on the detached / expired ORM object, which
        is what caused :bug:`247` (``MissingGreenlet`` under async).
        """
        team = Team(
            project_id=data.project_id,
            name=data.name,
            name_translations=data.name_translations,
            sort_order=data.sort_order,
            is_default=data.is_default,
            metadata_=data.metadata,
        )
        team = await self.team_repo.create(team)
        # Re-fetch with memberships eager-loaded so serialization is safe.
        fresh = await self.team_repo.get(team.id)
        logger.info("Team created: %s in project %s", data.name, data.project_id)
        return fresh or team

    async def get_team(self, team_id: uuid.UUID) -> Team:
        """Get team by ID. Raises 404 if not found."""
        team = await self.team_repo.get(team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found",
            )
        return team

    async def list_teams(
        self,
        project_id: uuid.UUID,
        *,
        include_inactive: bool = False,
    ) -> list[Team]:
        """List teams for a project."""
        return await self.team_repo.list_for_project(
            project_id,
            include_inactive=include_inactive,
        )

    async def update_team(
        self,
        team_id: uuid.UUID,
        data: TeamUpdate,
    ) -> Team:
        """Update team fields."""
        team = await self.get_team(team_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return team

        await self.team_repo.update_fields(team_id, **fields)
        updated = await self.team_repo.get(team_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found",
            )

        logger.info("Team updated: %s (fields=%s)", team_id, list(fields.keys()))
        return updated

    async def delete_team(self, team_id: uuid.UUID) -> None:
        """Delete a team. Cascades to memberships and visibility grants."""
        await self.get_team(team_id)  # Raises 404 if not found
        await self.team_repo.delete(team_id)
        logger.info("Team deleted: %s", team_id)

    # ── Memberships ──────────────────────────────────────────────────────

    async def add_member(
        self,
        team_id: uuid.UUID,
        data: AddMemberRequest,
    ) -> TeamMembership:
        """Add a user to a team."""
        await self.get_team(team_id)  # Raises 404 if team not found

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
        logger.info("Member added: user %s to team %s (%s)", data.user_id, team_id, data.role)
        return membership

    async def remove_member(
        self,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Remove a user from a team."""
        await self.get_team(team_id)  # Raises 404 if team not found
        removed = await self.membership_repo.remove(team_id, user_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membership not found",
            )
        logger.info("Member removed: user %s from team %s", user_id, team_id)

    async def list_members(self, team_id: uuid.UUID) -> list[TeamMembership]:
        """List members of a team."""
        await self.get_team(team_id)  # Raises 404 if team not found
        return await self.membership_repo.list_for_team(team_id)

    # ── Visibility ───────────────────────────────────────────────────────

    async def grant_visibility(
        self,
        entity_type: str,
        entity_id: str,
        team_id: uuid.UUID,
    ) -> EntityVisibility:
        """Grant visibility of an entity to a team."""
        await self.get_team(team_id)  # Raises 404 if team not found
        visibility = EntityVisibility(
            entity_type=entity_type,
            entity_id=entity_id,
            team_id=team_id,
        )
        visibility = await self.visibility_repo.grant(visibility)
        logger.info(
            "Visibility granted: %s/%s → team %s",
            entity_type,
            entity_id,
            team_id,
        )
        return visibility

    async def list_entity_visibility(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[EntityVisibility]:
        """List visibility grants for an entity."""
        return await self.visibility_repo.list_for_entity(entity_type, entity_id)
