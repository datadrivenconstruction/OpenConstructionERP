"""‌⁠‍Project-member service.

The Team Strip surfaces "who is on this project" at the project level. We
implement it as a thin wrapper over the existing team-membership tables —
each project gets a "Default Team" on creation (see
``ProjectService.create_project``), so project-membership = membership in that
default team. If for some reason no default team exists yet (legacy projects
created before that auto-create logic shipped) we lazily create one on the
first add.

Why not introduce a brand-new ``oe_projects_member`` table?
    * Avoids a duplicate join-table + migration for what is conceptually the
      same thing.
    * Existing visibility rules (entity → team mapping) already key off
      ``team_id``, so reusing the default team keeps visibility consistent.
    * The Team module already has ``add_member`` / ``remove_member`` /
      ``list_members`` plumbing we can delegate to.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.projects.member_schemas import (
    AddProjectMemberRequest,
    ProjectMemberResponse,
)
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User


async def _get_or_create_default_team(session: AsyncSession, project_id: uuid.UUID) -> Team:
    """‌⁠‍Fetch the project's default team, lazily creating one if missing."""
    stmt = select(Team).where(Team.project_id == project_id, Team.is_default.is_(True)).limit(1)
    team = (await session.execute(stmt)).scalar_one_or_none()
    if team is not None:
        return team

    # Fallback: any team for the project, otherwise create a fresh default.
    any_stmt = select(Team).where(Team.project_id == project_id).limit(1)
    team = (await session.execute(any_stmt)).scalar_one_or_none()
    if team is not None:
        return team

    team = Team(project_id=project_id, name="Default Team", is_default=True)
    session.add(team)
    await session.flush()
    return team


async def _load_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("errors.project_not_found", locale=get_locale()),
        )
    return project


async def list_project_members(session: AsyncSession, project_id: uuid.UUID) -> list[ProjectMemberResponse]:
    """‌⁠‍Return all members of the project's default team, joined to User.

    The project owner is always included, even if for some reason the owner
    membership row was never created (e.g. data imported from an older dump).
    """
    project = await _load_project(session, project_id)
    team = await _get_or_create_default_team(session, project_id)

    # Join membership → user so we can return email + name in one shot.
    stmt = (
        select(TeamMembership, User)
        .join(User, User.id == TeamMembership.user_id)
        .where(TeamMembership.team_id == team.id)
        .order_by(TeamMembership.created_at)
    )
    rows = (await session.execute(stmt)).all()

    members: list[ProjectMemberResponse] = []
    seen: set[uuid.UUID] = set()
    for membership, user in rows:
        members.append(
            ProjectMemberResponse(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name or "",
                role=membership.role,
                is_owner=(user.id == project.owner_id),
                created_at=membership.created_at,
            )
        )
        seen.add(user.id)

    # Ensure the owner is always represented even if no row exists yet.
    if project.owner_id not in seen:
        owner = (await session.execute(select(User).where(User.id == project.owner_id))).scalar_one_or_none()
        if owner is not None:
            members.insert(
                0,
                ProjectMemberResponse(
                    user_id=owner.id,
                    email=owner.email,
                    full_name=owner.full_name or "",
                    role="owner",
                    is_owner=True,
                ),
            )

    return members


async def add_project_member(
    session: AsyncSession,
    project_id: uuid.UUID,
    data: AddProjectMemberRequest,
) -> ProjectMemberResponse:
    """Add a user to the project's default team. 409 on duplicates."""
    await _load_project(session, project_id)
    team = await _get_or_create_default_team(session, project_id)

    # Reject duplicates so the UI can show a meaningful "already on team"
    # error instead of a generic 500 from the unique constraint.
    existing = (
        await session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == data.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this project",
        )

    # Validate the user actually exists.
    user = (await session.execute(select(User).where(User.id == data.user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Inactive (deactivated / soft-deleted) users must never be re-added
    # to a project — they can't log in anyway, and silently adding them
    # creates dangling membership rows the admin UI then has to clean up.
    if not getattr(user, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add a deactivated user to a project",
        )

    membership = TeamMembership(team_id=team.id, user_id=data.user_id, role=data.role)
    session.add(membership)
    await session.flush()

    project = await _load_project(session, project_id)
    return ProjectMemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name or "",
        role=membership.role,
        is_owner=(user.id == project.owner_id),
        created_at=membership.created_at,
    )


async def remove_project_member(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Remove a user from the project's default team.

    Refuses to remove the project owner — that has to go through the
    project-transfer flow (out of scope for the Team Strip).
    """
    project = await _load_project(session, project_id)
    if project.owner_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the project owner. Transfer ownership first.",
        )

    team = await _get_or_create_default_team(session, project_id)
    membership = (
        await session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found",
        )
    await session.delete(membership)
    await session.flush()
