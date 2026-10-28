# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the claims evidence-pack service (PostgreSQL, py3.12).

Seeds change-family records and checks that the assembled pack collects them
into the right sections, is deterministic across calls, and is fenced to one
project.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.claims_evidence.service import assemble_evidence
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from app.modules.variations.models import Notice
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"ev-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Ev",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Ev {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_pack_collects_change_records_into_sections(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            Notice(project_id=pid, code="NOT-1", title="Early warning"),
            ChangeOrder(project_id=pid, code="CO-1", title="Scope add", status="submitted"),
        ]
    )
    await session.flush()

    pack = await assemble_evidence(session, project_id=pid, subject_ref="CLAIM-1")

    assert pack.subject_ref == "CLAIM-1"
    assert pack.basis == "dispute"
    assert pack.entry_count == 2
    section_names = {s.name for s in pack.sections}
    assert "notices" in section_names
    assert "variations" in section_names  # change orders route into variations
    assert pack.content_digest


@pytest.mark.asyncio
async def test_pack_is_deterministic(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            Notice(project_id=pid, code="NOT-2", title="N"),
            ChangeOrder(project_id=pid, code="CO-2", title="C", status="submitted"),
        ]
    )
    await session.flush()

    first = await assemble_evidence(session, project_id=pid, subject_ref="CLAIM-2")
    second = await assemble_evidence(session, project_id=pid, subject_ref="CLAIM-2")
    assert first.content_digest == second.content_digest


@pytest.mark.asyncio
async def test_pack_is_fenced_to_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    mine = ChangeOrder(project_id=pid, code="CO-MINE", title="Mine", status="submitted")
    theirs = ChangeOrder(project_id=other, code="CO-THEIRS", title="Theirs", status="submitted")
    session.add_all([mine, theirs])
    await session.flush()

    pack = await assemble_evidence(session, project_id=pid, subject_ref="CLAIM-3")
    refs = {entry.ref_id for section in pack.sections for entry in section.entries}
    assert str(mine.id) in refs
    assert str(theirs.id) not in refs
