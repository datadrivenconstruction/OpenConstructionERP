# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Listing project members is a read: it must not create a team, the read-only demo refuses the write."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.demo_read_only import ALLOWED_ENDPOINTS
from app.modules.projects.member_service import list_project_members
from app.modules.projects.models import Project
from app.modules.teams.models import Team
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


async def test_listing_members_of_a_project_without_a_team_writes_nothing() -> None:
    async with transactional_session() as session:
        owner = User(email=f"own-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="editor")
        session.add(owner)
        await session.flush()
        project = Project(name="No team yet", owner_id=owner.id, currency="SAR")
        session.add(project)
        await session.flush()

        members = await list_project_members(session, project.id)

        assert [(m.user_id, m.is_owner) for m in members] == [(owner.id, True)]
        teams = (
            await session.execute(select(func.count()).select_from(Team).where(Team.project_id == project.id))
        ).scalar()
        assert teams == 0


def test_client_error_reports_stay_open_on_the_read_only_demo() -> None:
    assert "app.modules.client_errors.router:submit_client_error" in ALLOWED_ENDPOINTS
