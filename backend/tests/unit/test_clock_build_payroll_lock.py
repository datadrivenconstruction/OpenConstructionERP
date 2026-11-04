"""Rebuilding a clock draft rewrites its lines, so a locked payroll period must refuse it."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.field_time.clock_service import ClockService
from app.modules.field_time.service import FieldTimeService

DAY = date(2026, 6, 15)


class _Line:
    pass


class _Session:
    def __init__(self):
        self.deleted: list = []

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        return None


class _Repo:
    async def list_events(self, *_a, **_k):
        return [], 0

    async def list_geofences(self, _pid):
        return []


@pytest.mark.asyncio
async def test_rebuild_of_a_draft_in_a_locked_period_is_refused(monkeypatch):
    async def _locked(_self, _project_id, _day):
        raise HTTPException(status_code=409, detail="locked")

    monkeypatch.setattr(FieldTimeService, "_assert_payroll_open", _locked)
    svc = ClockService.__new__(ClockService)
    svc.session = _Session()
    svc.repo = _Repo()
    draft = SimpleNamespace(id=uuid.uuid4(), status="draft", lines=[_Line()])

    async def _settings(_pid):
        return SimpleNamespace(default_break_minutes=0)

    async def _existing(_pid, _day):
        return draft

    svc.get_settings = _settings  # type: ignore[method-assign]
    svc._clock_timesheet = _existing  # type: ignore[method-assign]
    with pytest.raises(HTTPException) as exc:
        await svc.build_timesheet(uuid.uuid4(), DAY, None)
    assert exc.value.status_code == 409
    assert svc.session.deleted == []
