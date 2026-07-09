# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""ACAP per-project authorization policy (Phase 8) — the pure guard functions.

Proves app.modules.acap.authz enforces the SAME policy as the fork's native
project routes: writes need owner/admin (403 otherwise), reads need
owner/member/admin (404 otherwise — IDOR-hiding). The endpoint WIRING (that
every ACAP route actually calls these) is proved over HTTP in
test_tenant_isolation.py.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.acap.authz import require_project_access, require_project_owner
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    from app.modules.projects.models import Project

    project = Project(name=f"P {uuid.uuid4().hex[:6]}", currency="IDR", owner_id=owner_id)
    session.add(project)
    await session.flush()
    return project.id


@pytest.mark.asyncio
async def test_owner_may_read_and_write(session):
    owner = uuid.uuid4()
    pid = await _make_project(session, owner)
    payload = {"sub": str(owner)}
    await require_project_owner(session, pid, payload)  # neither raises
    await require_project_access(session, pid, payload)


@pytest.mark.asyncio
async def test_other_user_denied_write_403(session):
    owner, intruder = uuid.uuid4(), uuid.uuid4()
    pid = await _make_project(session, owner)
    with pytest.raises(HTTPException) as exc:
        await require_project_owner(session, pid, {"sub": str(intruder)})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_other_user_denied_read_404(session):
    """Read denial is 404, not 403 — no existence oracle for outsiders."""
    owner, intruder = uuid.uuid4(), uuid.uuid4()
    pid = await _make_project(session, owner)
    with pytest.raises(HTTPException) as exc:
        await require_project_access(session, pid, {"sub": str(intruder)})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_bypasses_both(session):
    owner, admin = uuid.uuid4(), uuid.uuid4()
    pid = await _make_project(session, owner)
    payload = {"sub": str(admin), "role": "admin"}
    await require_project_owner(session, pid, payload)
    await require_project_access(session, pid, payload)


@pytest.mark.asyncio
async def test_missing_project_is_404_for_both(session):
    ghost = uuid.uuid4()
    for guard in (require_project_owner, require_project_access):
        with pytest.raises(HTTPException) as exc:
            await guard(session, ghost, {"sub": str(uuid.uuid4())})
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_team_member_may_read_not_write(session):
    """A team member gets read access (via the fork's is_project_member) but
    not write access."""
    from app.modules.teams.models import Team, TeamMembership

    owner, member = uuid.uuid4(), uuid.uuid4()
    pid = await _make_project(session, owner)
    team = Team(project_id=pid, name="crew")
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=member))
    await session.flush()

    payload = {"sub": str(member)}
    await require_project_access(session, pid, payload)  # read OK
    with pytest.raises(HTTPException) as exc:
        await require_project_owner(session, pid, payload)  # write denied
    assert exc.value.status_code == 403
