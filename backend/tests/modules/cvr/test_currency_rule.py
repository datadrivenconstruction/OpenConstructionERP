# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""A CVR line in another currency than its report is a coded 422; blank or equal currency passes."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import rule_registry
from app.modules.cvr.schemas import CvrLineCreate, CvrReportCreate
from app.modules.cvr.service import CvrService
from app.modules.cvr.validators import CVR_RULE_SET, register_cvr_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    register_cvr_validation_rules()
    async with transactional_session() as s:
        yield s


async def _report(session: AsyncSession) -> tuple[CvrService, uuid.UUID]:
    user = User(email=f"cvr-cur-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    session.add(user)
    await session.flush()
    project = Project(name=f"CVR {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    svc = CvrService(session)
    report = await svc.create_report(CvrReportCreate(project_id=project.id, period="2026-08", currency="EUR"))
    return svc, report.id


def test_rule_is_registered_under_the_cvr_set() -> None:
    register_cvr_validation_rules()
    assert "cvr.currency_consistent" in {r.rule_id for r in rule_registry.get_rules_for_sets([CVR_RULE_SET])}


@pytest.mark.asyncio
async def test_matching_and_blank_currency_pass_and_mismatch_is_coded(session: AsyncSession) -> None:
    svc, report_id = await _report(session)
    await svc.create_line(report_id, CvrLineCreate(cost_code="100", description="Same", currency="eur"))
    await svc.create_line(report_id, CvrLineCreate(cost_code="200", description="Blank"))
    with pytest.raises(HTTPException) as exc:
        await svc.create_line(report_id, CvrLineCreate(cost_code="300", description="Other", currency="USD"))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "cvr.currency_consistent"
    assert "EUR" in str(exc.value.detail) and "USD" in str(exc.value.detail)
