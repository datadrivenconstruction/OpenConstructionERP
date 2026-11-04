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


@pytest.mark.asyncio
async def test_legacy_record_with_existing_violation_stays_editable(client, admin_auth, project_id):
    async with async_session_factory() as session:
        svc = InspectionService(session)
        insp = await svc.create_inspection(_data(project_id))
        await svc.repo.update_fields(
            insp.id, result="pass", checklist_data=[{"id": "1", "question": "Level?", "response": "fail"}]
        )
        await session.refresh(insp)
        updated = await svc.update_inspection(
            insp.id, InspectionUpdate.model_construct(_fields_set={"title"}, title="Renamed")
        )
        assert updated.title == "Renamed"
        await session.rollback()


async def _merge(client, header, insp: dict, fields: dict):
    return await client.post(
        f"/api/v1/inspections/{insp['id']}/merge/",
        json={"base_version": insp["version"], "against_version": insp["version"], "fields": fields},
        headers=header,
    )


@pytest.mark.asyncio
async def test_offline_merge_runs_the_rules_and_blocks_a_new_error(client, admin_auth, project_id):
    _, header = admin_auth
    resp = await client.post(
        "/api/v1/inspections/",
        json={
            "project_id": project_id,
            "inspection_type": "concrete_pour",
            "title": "Merge pour",
            "result": "pass",
            "checklist_data": [{"id": "1", "question": "Level?", "response": "pass"}],
        },
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    insp = resp.json()
    bad = await _merge(
        client, header, insp, {"checklist_data": [{"id": "1", "question": "Level?", "response": "fail"}]}
    )
    assert bad.status_code == 422, bad.text
    assert "inspections.result_matches_checklist" in {e["rule_id"] for e in bad.json()["detail"]["errors"]}
    ok = await _merge(client, header, insp, {"title": "Merge pour renamed"})
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_offline_merge_does_not_freeze_a_legacy_violation(client, admin_auth, project_id):
    _, header = admin_auth
    resp = await client.post(
        "/api/v1/inspections/",
        json={"project_id": project_id, "inspection_type": "concrete_pour", "title": "Legacy merge", "result": "pass"},
        headers=header,
    )
    insp = resp.json()
    async with async_session_factory() as session:
        svc = InspectionService(session)
        await svc.repo.update_fields(
            uuid.UUID(insp["id"]), checklist_data=[{"id": "1", "question": "Level?", "response": "fail"}]
        )
        await session.commit()
    ok = await _merge(client, header, insp, {"description": "edited offline"})
    assert ok.status_code == 200, ok.text
