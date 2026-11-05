"""A draft timesheet must not be moved, rewritten or withdrawn across a locked payroll period."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.field_time.schemas import FieldTimesheetUpdate
from app.modules.field_time.service import FieldTimeService

LOCKED = date(2026, 6, 15)
OPEN = date(2026, 7, 15)


class _Repo:
    def __init__(self, sheet):
        self.sheet = sheet
        self.updated: dict | None = None
        self.deleted = False

    async def get_by_id(self, _id):
        return self.sheet

    async def update_fields(self, _id, **fields):
        self.updated = fields

    async def delete(self, _id):
        self.deleted = True


class _Session:
    async def refresh(self, _obj):
        return None


def _service(sheet) -> tuple[FieldTimeService, _Repo]:
    svc = FieldTimeService.__new__(FieldTimeService)
    svc.session = _Session()
    svc.repo = _Repo(sheet)

    async def _assert_open(project_id, day):
        if day == LOCKED:
            raise HTTPException(status_code=409, detail="locked")

    svc._assert_payroll_open = _assert_open  # type: ignore[method-assign]
    return svc, svc.repo


def _sheet(day: date):
    return SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), date=day, status="draft", metadata_={}, lines=[])


@pytest.mark.asyncio
async def test_update_cannot_move_a_draft_into_a_locked_period():
    svc, repo = _service(_sheet(OPEN))
    with pytest.raises(HTTPException) as exc:
        await svc.update_timesheet(uuid.uuid4(), FieldTimesheetUpdate(date=LOCKED))
    assert exc.value.status_code == 409
    assert repo.updated is None


@pytest.mark.asyncio
async def test_update_to_an_open_day_still_works():
    svc, repo = _service(_sheet(OPEN))
    await svc.update_timesheet(uuid.uuid4(), FieldTimesheetUpdate(date=date(2026, 7, 16)))
    assert repo.updated == {"date": date(2026, 7, 16)}


@pytest.mark.asyncio
async def test_offline_withdraw_cannot_delete_a_draft_in_a_locked_period(monkeypatch):
    sheet = _sheet(LOCKED)
    svc, repo = _service(sheet)
    ledger = SimpleNamespace(result_type="created", result_id=sheet.id)

    class _Ledger:
        def __init__(self, _session):
            pass

        async def get_by_client_op_id(self, _key, _project_id):
            return ledger

    monkeypatch.setattr("app.modules.field_time.service.FieldSyncLedgerRepository", _Ledger)
    monkeypatch.setattr(FieldTimeService, "_assert_offline_key_is_ours", lambda *a, **k: None)
    data = SimpleNamespace(entry_key="k", project_id=sheet.project_id)
    with pytest.raises(HTTPException) as exc:
        await svc.withdraw_offline_entry(data, None)
    assert exc.value.status_code == 409
    assert repo.deleted is False
