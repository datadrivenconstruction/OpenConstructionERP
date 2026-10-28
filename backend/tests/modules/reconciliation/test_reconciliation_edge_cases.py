# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Edge-case integration tests for the reconciliation module (PostgreSQL, py3.12).

``test_thread_api.py`` already covers the confirm/reject round-trip, idempotent
upsert, the rejected-link cut, project scoping and the invalid-status guard. This
file adds the remaining boundaries a thin suite skips: the wrong-project /
access-denied 404 the router enforces, a garbage and a malformed seed key, a
blank decision status, and an empty link list for a fresh project.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import verify_project_access
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.reconciliation.models import STATUS_CONFIRMED
from app.modules.reconciliation.service import (
    TYPE_CHANGE_ORDER,
    TYPE_CORRESPONDENCE,
    build_event_thread,
    decide_record_link,
    list_record_links,
)
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, role: str = "admin") -> User:
    user = User(
        email=f"rec-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="REC",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User) -> uuid.UUID:
    proj = Project(name=f"REC {uuid.uuid4().hex[:6]}", owner_id=owner.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_access_denied_is_404_for_non_member(session: AsyncSession) -> None:
    """A stranger reading another project's thread is 404 (the router IDOR gate)."""
    owner = await _user(session, role="manager")
    pid = await _project(session, owner)
    stranger = await _user(session, role="manager")

    with pytest.raises(HTTPException) as exc:
        await verify_project_access(pid, str(stranger.id), session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_garbage_seed_key_yields_empty_thread(session: AsyncSession) -> None:
    """A free-text seed key that matches no subject yields an empty, valid thread."""
    owner = await _user(session)
    pid = await _project(session, owner)

    thread = await build_event_thread(session, pid, "this matches nothing at all")
    assert thread.records == []
    assert thread.links == []
    assert thread.seed_type is None
    assert thread.seed_id is None
    assert thread.confirmed_count == 0


@pytest.mark.asyncio
async def test_malformed_typed_seed_key_is_safe(session: AsyncSession) -> None:
    """A ``type:not-a-uuid`` seed key does not raise; it just resolves to nothing."""
    owner = await _user(session)
    pid = await _project(session, owner)

    thread = await build_event_thread(session, pid, f"{TYPE_CHANGE_ORDER}:not-a-uuid")
    assert thread.records == []
    assert thread.links == []


@pytest.mark.asyncio
async def test_blank_status_is_rejected(session: AsyncSession) -> None:
    """A blank decision status is rejected with ValueError (router -> 422)."""
    owner = await _user(session)
    pid = await _project(session, owner)

    with pytest.raises(ValueError):
        await decide_record_link(
            session,
            pid,
            left=(TYPE_CHANGE_ORDER, str(uuid.uuid4())),
            right=(TYPE_CORRESPONDENCE, str(uuid.uuid4())),
            relation="same_event",
            status="",
        )


@pytest.mark.asyncio
async def test_decide_tolerates_nonexistent_endpoints(session: AsyncSession) -> None:
    """A decision references endpoints by id; persisting one for ids that do not
    resolve to records is allowed (the link is the reviewer's assertion, scored
    independently of whether both rows still exist) and stays project-scoped."""
    owner = await _user(session)
    pid = await _project(session, owner)

    row = await decide_record_link(
        session,
        pid,
        left=(TYPE_CHANGE_ORDER, str(uuid.uuid4())),
        right=(TYPE_CORRESPONDENCE, str(uuid.uuid4())),
        relation="same_event",
        status=STATUS_CONFIRMED,
    )
    assert row.status == STATUS_CONFIRMED
    assert row.project_id == pid
    # It is recorded and scoped to this project.
    rows = await list_record_links(session, pid)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_links_empty_for_fresh_project(session: AsyncSession) -> None:
    """A project with no decisions lists no record links."""
    owner = await _user(session)
    pid = await _project(session, owner)
    assert await list_record_links(session, pid) == []
