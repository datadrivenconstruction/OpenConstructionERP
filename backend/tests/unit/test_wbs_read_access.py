"""The WBS list is readable by a project member, not only by the owner."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from tests._pg import transactional_session

OWNER, MEMBER, STRANGER, PROJECT = (uuid.uuid4() for _ in range(4))


@pytest.mark.asyncio
async def test_member_reads_the_wbs_and_outsider_gets_404() -> None:
    from app.config import get_settings
    from app.modules.projects.models import Project
    from app.modules.projects.router import list_wbs_nodes
    from app.modules.projects.service import ProjectService
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    async with transactional_session() as s:
        for uid in (OWNER, MEMBER, STRANGER):
            s.add(User(id=uid, email=f"wbs-{uid.hex[:8]}@test.io", hashed_password="x", full_name="x"))
        await s.flush()
        s.add(Project(id=PROJECT, name="p", owner_id=OWNER, currency="USD"))
        await s.flush()
        team = Team(project_id=PROJECT, name="site team")
        s.add(team)
        await s.flush()
        s.add(TeamMembership(team_id=team.id, user_id=MEMBER, role="member"))
        await s.commit()
        service = ProjectService(s, get_settings())

        assert await list_wbs_nodes(PROJECT, str(MEMBER), {"role": "manager"}, s, service) == []
        with pytest.raises(HTTPException) as exc:
            await list_wbs_nodes(PROJECT, str(STRANGER), {"role": "manager"}, s, service)
        assert exc.value.status_code == 404
