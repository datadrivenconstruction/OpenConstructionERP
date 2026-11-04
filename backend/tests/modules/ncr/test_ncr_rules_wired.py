"""The ncr rule set is enforced by NCRService at its write points."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.database import async_session_factory
from app.modules.ncr.schemas import NCRCreate, NCRUpdate
from app.modules.ncr.service import NCRService


def _data(project_id: str, **over) -> NCRCreate:
    base = {
        "project_id": uuid.UUID(project_id),
        "title": "Honeycombing",
        "description": "Voids on level 2 soffit",
        "ncr_type": "workmanship",
        "severity": "major",
    }
    base.update(over)
    return NCRCreate(**base)


def _rule_ids(exc: HTTPException) -> set[str]:
    return {e["rule_id"] for e in exc.detail["errors"]}


@pytest.mark.asyncio
async def test_blocking_rule_rejects_create_with_code(client, admin_auth, project_id):
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as err:
            await NCRService(session).create_ncr(_data(project_id, status="closed"))
    assert err.value.status_code == 422
    assert "ncr.closure_documented" in _rule_ids(err.value)


@pytest.mark.asyncio
async def test_close_without_root_cause_is_rejected_and_not_written(client, admin_auth, project_id):
    uid, _ = admin_auth
    async with async_session_factory() as session:
        svc = NCRService(session)
        ncr = await svc.create_ncr(_data(project_id, status="verification", corrective_action="Grout"))
        with pytest.raises(HTTPException) as err:
            await svc.close_ncr(ncr.id, verified_by=uid)
        assert err.value.status_code == 422
        assert "ncr.closure_documented" in _rule_ids(err.value)
        assert (await svc.get_ncr(ncr.id)).status == "verification"
        await session.rollback()


@pytest.mark.asyncio
async def test_warning_passes_and_is_reported(client, admin_auth, project_id):
    past = date.today() - timedelta(days=3)
    async with async_session_factory() as session:
        svc = NCRService(session)
        ncr = await svc.create_ncr(_data(project_id, due_date=past))
        assert ncr.due_date == past
        assert [w["rule_id"] for w in ncr.validation_warnings] == ["ncr.not_overdue"]
        await session.commit()


@pytest.mark.asyncio
async def test_close_without_verifier_warns_and_leaves_verifier_empty(client, admin_auth, project_id):
    async with async_session_factory() as session:
        svc = NCRService(session)
        ncr = await svc.create_ncr(
            _data(project_id, status="verification", corrective_action="Grout", root_cause="Vibration")
        )
        closed = await svc.close_ncr(ncr.id)
        assert closed.status == "closed"
        assert closed.verified_by is None
        assert [w["rule_id"] for w in closed.validation_warnings] == ["ncr.closure_verified"]
        await session.commit()


@pytest.mark.asyncio
async def test_valid_record_passes_clean_and_stamps_verifier(client, admin_auth, project_id):
    uid, _ = admin_auth
    async with async_session_factory() as session:
        svc = NCRService(session)
        ncr = await svc.create_ncr(
            _data(project_id, status="verification", corrective_action="Grout", root_cause="Vibration")
        )
        assert ncr.validation_warnings == []
        closed = await svc.close_ncr(ncr.id, verified_by=uid)
        assert closed.validation_warnings == []
        assert closed.verified_by == uid
        assert closed.verified_at is not None
        await session.commit()


@pytest.mark.asyncio
async def test_update_runs_the_rules_on_the_merged_record(client, admin_auth, project_id):
    async with async_session_factory() as session:
        svc = NCRService(session)
        ncr = await svc.create_ncr(_data(project_id, cost_impact="1500"))
        with pytest.raises(HTTPException) as err:
            await svc.update_ncr(ncr.id, NCRUpdate.model_construct(_fields_set={"description"}, description=" "))
        assert err.value.status_code == 422
        assert "ncr.cost_impact_described" in _rule_ids(err.value)
        await session.rollback()


@pytest.mark.asyncio
async def test_legacy_record_with_existing_violation_stays_editable(client, admin_auth, project_id):
    async with async_session_factory() as session:
        svc = NCRService(session)
        ncr = await svc.create_ncr(_data(project_id, cost_impact="1500"))
        await svc.repo.update_fields(ncr.id, description="")
        await session.refresh(ncr)
        updated = await svc.update_ncr(ncr.id, NCRUpdate.model_construct(_fields_set={"title"}, title="Renamed"))
        assert updated.title == "Renamed"
        await session.rollback()
