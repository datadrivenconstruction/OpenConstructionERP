"""Crew rows are owner scoped: an admin can delete any crew, nobody writes into another owner's crew."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.labor_rates.schemas import CrewMemberIn, CrewSaveRequest
from app.modules.labor_rates.service import LaborRateService


class _Result:
    def __init__(self, row=None):
        self._row = row
        self.rowcount = 2

    def first(self):
        return self._row


class _Session:
    def __init__(self, foreign_row=None):
        self.stmts: list[str] = []
        self.foreign_row = foreign_row

    async def execute(self, stmt):
        self.stmts.append(str(stmt))
        return _Result(self.foreign_row)

    async def flush(self):
        return None

    def add(self, _obj):
        raise AssertionError("must not write into another owner's crew")


def _svc(session) -> LaborRateService:
    svc = LaborRateService.__new__(LaborRateService)
    svc.session = session
    return svc


@pytest.mark.asyncio
async def test_unscoped_delete_does_not_filter_on_a_null_owner():
    session = _Session()
    removed = await _svc(session).delete_crew(uuid.uuid4(), None)
    assert removed == 2
    assert "owner_id" not in session.stmts[0].split("WHERE")[1]


@pytest.mark.asyncio
async def test_scoped_delete_still_filters_on_owner():
    session = _Session()
    await _svc(session).delete_crew(uuid.uuid4(), uuid.uuid4())
    assert "owner_id" in session.stmts[0].split("WHERE")[1]


@pytest.mark.asyncio
async def test_save_into_a_crew_owned_by_someone_else_is_a_404():
    session = _Session(foreign_row=SimpleNamespace(id=1))
    req = CrewSaveRequest(
        crew_id=uuid.uuid4(), currency="EUR", members=[CrewMemberIn(trade="Mason", count=1, all_in_rate="30")]
    )
    with pytest.raises(HTTPException) as exc:
        await _svc(session).save_crew(req, uuid.uuid4())
    assert exc.value.status_code == 404
