"""A closed audit and an ITP plan past active keep what they recorded.

Both records already refuse the neighbouring writes: ``add_finding`` refuses a
closed audit, and ``add_itp_item`` / ``link_itp_item_to_spec`` refuse a plan
outside draft/active. The plain PATCH routes did not, so a closed audit could
have its rating and dates rewritten, an audit could be completed without the
``complete`` action (and without its ``qms.audit.completed`` event), and a
closed plan could be renamed or re-versioned after the work it controlled.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qms.schemas import (
    AuditCreate,
    AuditUpdate,
    ITPItemCreate,
    ITPPlanCreate,
    ITPPlanUpdate,
)
from app.modules.qms.service import QMSService
from tests._pg import transactional_session

_PROJECT_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def svc() -> AsyncIterator[QMSService]:
    session: AsyncSession
    async with transactional_session() as session:
        yield QMSService(session)


async def _closed_audit(svc: QMSService):
    audit = await svc.plan_audit(AuditCreate(project_id=_PROJECT_ID))
    await svc.start_audit(audit.id)
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        await svc.complete_audit(audit.id, overall_rating=2)
    return await svc.update_audit(audit.id, AuditUpdate(status="closed"))


@pytest.mark.asyncio
async def test_a_closed_audit_keeps_its_rating(svc: QMSService) -> None:
    audit = await _closed_audit(svc)
    with pytest.raises(ValueError, match="closed audit"):
        await svc.update_audit(audit.id, AuditUpdate(overall_rating=5))
    assert audit.overall_rating == 2


@pytest.mark.asyncio
async def test_an_audit_is_completed_only_through_its_action(svc: QMSService) -> None:
    audit = await svc.plan_audit(AuditCreate(project_id=_PROJECT_ID))
    await svc.start_audit(audit.id)
    with pytest.raises(ValueError, match="'complete' action"):
        await svc.update_audit(audit.id, AuditUpdate(status="completed"))
    assert audit.status == "in_progress"


@pytest.mark.asyncio
async def test_an_open_audit_can_still_be_edited_and_closed(svc: QMSService) -> None:
    audit = await svc.plan_audit(AuditCreate(project_id=_PROJECT_ID))
    audit = await svc.update_audit(audit.id, AuditUpdate(audit_scope="Formwork"))
    assert audit.audit_scope == "Formwork"
    audit = await svc.update_audit(audit.id, AuditUpdate(status="closed"))
    assert audit.status == "closed"


async def _active_plan(svc: QMSService):
    plan = await svc.create_itp_plan(ITPPlanCreate(project_id=_PROJECT_ID, name="Slab", work_type="concrete"))
    await svc.add_itp_item(plan.id, ITPItemCreate(control_point_name="Rebar", hold_witness_point="hold"))
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        return await svc.activate_itp_plan(plan.id)


@pytest.mark.asyncio
async def test_a_closed_plan_keeps_its_name(svc: QMSService) -> None:
    plan = await _active_plan(svc)
    plan = await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="closed"))
    with pytest.raises(ValueError, match="status 'closed'"):
        await svc.update_itp_plan(plan.id, ITPPlanUpdate(name="Renamed"))
    assert plan.name == "Slab"


@pytest.mark.asyncio
async def test_a_superseded_plan_can_still_be_closed(svc: QMSService) -> None:
    plan = await _active_plan(svc)
    plan = await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="superseded"))
    with pytest.raises(ValueError, match="status 'superseded'"):
        await svc.update_itp_plan(plan.id, ITPPlanUpdate(version=2))
    plan = await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="closed"))
    assert plan.status == "closed"


@pytest.mark.asyncio
async def test_an_active_plan_can_still_be_renamed(svc: QMSService) -> None:
    plan = await _active_plan(svc)
    plan = await svc.update_itp_plan(plan.id, ITPPlanUpdate(name="Slab L2"))
    assert plan.name == "Slab L2"
