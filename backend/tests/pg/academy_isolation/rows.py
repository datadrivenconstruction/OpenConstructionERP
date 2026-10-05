# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rows for the academy isolation gate tests: learners, admins, projects, teams."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User


async def make_user(
    session,
    *,
    role: str = "manager",
    name: str | None = None,
    email: str | None = None,
) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=email or f"learner-{tag}@academy.example",
        hashed_password="x",
        full_name=name if name is not None else f"Learner {tag}",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(session, owner: User, name: str = "Course project") -> Project:
    project = Project(name=name, owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def add_member(session, project: Project, user: User) -> None:
    team = Team(project_id=project.id, name=f"Team {uuid.uuid4().hex[:6]}")
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id))
    await session.flush()


def payload_of(user: User) -> dict[str, Any]:
    """The auth payload a router receives for ``user`` (role re-read from the row)."""
    return {"sub": str(user.id), "role": user.role}
