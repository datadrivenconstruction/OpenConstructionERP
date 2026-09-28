# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A finalized CVR report is not deleted.

The lines of a final report are refused for create, update and delete until the
report is set back to draft. Deleting the report itself had no status check, so
the same report went away with every one of its lines in one call. The delete
now holds the same line: set the report back to draft first.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cvr.schemas import CvrLineCreate, CvrReportCreate, CvrReportUpdate
from app.modules.cvr.service import CvrService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _report(session: AsyncSession) -> tuple[CvrService, uuid.UUID]:
    user = User(
        email=f"cvr-del-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CVR",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"CVR {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    svc = CvrService(session)
    report = await svc.create_report(CvrReportCreate(project_id=project.id, period="2026-08", currency="EUR"))
    await svc.create_line(report.id, CvrLineCreate(cost_code="100", description="Groundworks"))
    return svc, report.id


@pytest.mark.asyncio
async def test_a_final_report_is_not_deleted(session: AsyncSession) -> None:
    svc, report_id = await _report(session)
    await svc.finalize_report(report_id)

    with pytest.raises(HTTPException) as exc:
        await svc.delete_report(report_id)
    assert exc.value.status_code == 400
    report = await svc.get_report(report_id)
    assert report.status == "final"
    assert await svc.report_line_count(report_id) == 1


@pytest.mark.asyncio
async def test_a_report_set_back_to_draft_is_deleted(session: AsyncSession) -> None:
    svc, report_id = await _report(session)
    await svc.finalize_report(report_id)
    await svc.update_report(report_id, CvrReportUpdate(status="draft"))

    await svc.delete_report(report_id)
    with pytest.raises(HTTPException) as exc:
        await svc.get_report(report_id)
    assert exc.value.status_code == 404
