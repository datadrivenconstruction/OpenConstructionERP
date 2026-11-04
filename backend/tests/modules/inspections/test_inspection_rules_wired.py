"""The inspections rule set is enforced by InspectionService at its write points."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.database import async_session_factory
from app.modules.inspections.schemas import InspectionCreate, InspectionUpdate
from app.modules.inspections.service import InspectionService


def _data(project_id: str, **over) -> InspectionCreate:
    base = {"project_id": uuid.UUID(project_id), "inspection_type": "concrete_pour", "title": "Level 2 pour"}
    base.update(over)
    return InspectionCreate(**base)


def _rule_ids(exc: HTTPException) -> set[str]:
    return {e["rule_id"] for e in exc.detail["errors"]}


@pytest.mark.asyncio
async def test_blocking_rule_rejects_complete_with_code(client, admin_auth, project_id):
    async with async_session_factory() as session:
        svc = InspectionService(session)
        insp = await svc.create_inspection(_data(project_id))
        with pytest.raises(HTTPException) as err:
            await svc.complete_inspection(insp.id, "pass")
        assert err.value.status_code == 422
        assert "inspections.completed_has_inspector" in _rule_ids(err.value)
        assert (await svc.get_inspection(insp.id)).status == "scheduled"
        await session.rollback()


@pytest.mark.asyncio
async def test_pass_over_failed_checklist_is_rejected(client, admin_auth, project_id):
    uid, _ = admin_auth
    checklist = [{"question": "Cover depth ok?", "response_type": "pass_fail", "response": "fail"}]
    async with async_session_factory() as session:
        svc = InspectionService(session)
        insp = await svc.create_inspection(_data(project_id, inspector_id=uid, checklist_data=checklist))
        with pytest.raises(HTTPException) as err:
            await svc.complete_inspection(insp.id, "pass")
        assert "inspections.result_matches_checklist" in _rule_ids(err.value)
        await session.rollback()


@pytest.mark.asyncio
async def test_create_with_contradictory_result_is_rejected(client, admin_auth, project_id):
    checklist = [{"question": "Cover depth ok?", "response_type": "pass_fail", "response": "no"}]
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as err:
            await InspectionService(session).create_inspection(
                _data(project_id, result="pass", checklist_data=checklist)
            )
    assert err.value.status_code == 422
    assert "inspections.result_matches_checklist" in _rule_ids(err.value)


@pytest.mark.asyncio
async def test_overdue_warning_passes_and_is_reported(client, admin_auth, project_id):
    past = (date.today() - timedelta(days=5)).isoformat()
    async with async_session_factory() as session:
        svc = InspectionService(session)
        insp = await svc.create_inspection(_data(project_id, inspection_date=past))
        assert [w["rule_id"] for w in insp.validation_warnings] == ["inspections.not_overdue"]
        moved = await svc.update_inspection(
            insp.id, InspectionUpdate(inspection_date=(date.today() + timedelta(days=2)).isoformat())
        )
        assert moved.validation_warnings == []
        await session.commit()


@pytest.mark.asyncio
async def test_valid_inspection_completes_clean(client, admin_auth, project_id):
    uid, _ = admin_auth
    async with async_session_factory() as session:
        svc = InspectionService(session)
        insp = await svc.create_inspection(_data(project_id, inspector_id=uid))
        assert insp.validation_warnings == []
        done = await svc.complete_inspection(insp.id, "pass")
        assert done.status == "completed"
        assert done.validation_warnings == []
        await session.commit()
