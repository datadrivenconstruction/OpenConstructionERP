"""Teams API routes.

Endpoints:
    GET    /project/{project_id}        — List teams for project
    POST   /                            — Create team (auth required)
    PATCH  /{team_id}                   — Update team
    DELETE /{team_id}                   — Delete team
    POST   /{team_id}/members           — Add member
    DELETE /{team_id}/members/{user_id} — Remove member
    GET    /{team_id}/members           — List members
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.teams.schemas import (
    AddMemberRequest,
    MembershipResponse,
    TeamCreate,
    TeamResponse,
    TeamUpdate,
)
from app.modules.teams.service import TeamService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> TeamService:
    return TeamService(session)


# ── Teams ────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[TeamResponse])
async def list_teams_by_query(
    project_id: uuid.UUID = Query(...),
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TeamService = Depends(_get_service),
) -> list[TeamResponse]:
    """List teams for a project (query-param style)."""
    teams = await service.list_teams(project_id)
    return [TeamResponse.model_validate(t) for t in teams]


@router.get("/project/{project_id}", response_model=list[TeamResponse])
async def list_teams(
    project_id: uuid.UUID,
    service: TeamService = Depends(_get_service),
) -> list[TeamResponse]:
    """List teams for a project."""
    teams = await service.list_teams(project_id)
    return [TeamResponse.model_validate(t) for t in teams]


@router.post("/", response_model=TeamResponse, status_code=201)
async def create_team(
    data: TeamCreate,
    _user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> TeamResponse:
    """Create a new team within a project."""
    try:
        team = await service.create_team(data)
        return TeamResponse.model_validate(team)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create team")
        raise HTTPException(status_code=500, detail="Failed to create team")


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: uuid.UUID,
    data: TeamUpdate,
    _user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> TeamResponse:
    """Update team fields."""
    team = await service.update_team(team_id, data)
    return TeamResponse.model_validate(team)


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> None:
    """Delete a team and all its memberships."""
    await service.delete_team(team_id)


# ── Members ──────────────────────────────────────────────────────────────


@router.get("/{team_id}/members/", response_model=list[MembershipResponse])
async def list_members(
    team_id: uuid.UUID,
    service: TeamService = Depends(_get_service),
) -> list[MembershipResponse]:
    """List members of a team."""
    members = await service.list_members(team_id)
    return [MembershipResponse.model_validate(m) for m in members]


@router.post("/{team_id}/members/", response_model=MembershipResponse, status_code=201)
async def add_member(
    team_id: uuid.UUID,
    data: AddMemberRequest,
    _user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> MembershipResponse:
    """Add a user to a team."""
    try:
        membership = await service.add_member(team_id, data)
        return MembershipResponse.model_validate(membership)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to add member to team")
        raise HTTPException(status_code=500, detail="Failed to add member")


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: TeamService = Depends(_get_service),
) -> None:
    """Remove a user from a team."""
    await service.remove_member(team_id, user_id)
