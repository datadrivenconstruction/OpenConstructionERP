"""A closed quality or safety record is kept: the edit locks now hold against delete.

Each of these registers already froze a record once it was closed, verified or
approved: ``update_inventory`` refuses an archived carbon inventory,
``update_jsa`` an approved JSA, the CAPA patch a completed CAPA,
``update_inspection`` a completed inspection, ``update_minutes`` issued minutes,
``update_ncr`` a closed NCR and ``update_submittal`` a closed submittal. The
delete next to each lock looked at nothing, so a manager could remove outright
the record the lock was protecting, which rewrites more than any edit.

Each group pairs the refusal with the same delete on a record that is still
open, which must keep working.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.carbon.service import CarbonService
from app.modules.inspections.service import InspectionService
from app.modules.meetings.service import MeetingService
from app.modules.ncr.service import NCRService
from app.modules.submittals.service import SubmittalService
from tests.unit.test_hse_advanced import _make_service as _make_hse  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


class _Repo:
    def __init__(self) -> None:
        self.deleted: list[uuid.UUID] = []

    async def delete(self, item_id: uuid.UUID) -> None:
        self.deleted.append(item_id)


class _Session:
    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(rowcount=0)


def _service(cls: type, getter: str, repo_attr: str, row: Any) -> Any:
    svc = cls.__new__(cls)
    svc.session = _Session()
    setattr(svc, repo_attr, _Repo())

    async def _get(_id: uuid.UUID) -> Any:
        return row

    setattr(svc, getter, _get)
    return svc


def _row(status: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), status=status)


async def _refused(call: Any) -> str:
    with pytest.raises(HTTPException) as exc:
        await call
    assert exc.value.status_code == 409
    return str(exc.value.detail)


# ── Carbon inventory (C057) ─────────────────────────────────────────────────


async def test_an_archived_carbon_inventory_is_not_deleted() -> None:
    row = _row("archived")
    svc = _service(CarbonService, "get_inventory", "inventory_repo", row)
    await _refused(svc.delete_inventory(row.id))
    assert svc.inventory_repo.deleted == []


@pytest.mark.parametrize("status", ["draft", "baseline", "current"])
async def test_a_live_carbon_inventory_can_still_be_deleted(status: str) -> None:
    row = _row(status)
    svc = _service(CarbonService, "get_inventory", "inventory_repo", row)
    await svc.delete_inventory(row.id)
    assert svc.inventory_repo.deleted == [row.id]


# ── HSE: JSA (C297) and CAPA (C305) ─────────────────────────────────────────


async def _seed(repo: Any, status: str) -> SimpleNamespace:
    row = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), status=status, task_description="", title="")
    repo.rows[row.id] = row
    return row


@pytest.mark.parametrize(
    ("status", "remedy"),
    [("approved", "Archive it"), ("active", "Archive it"), ("archived", "kept as the record")],
)
async def test_a_signed_jsa_is_not_deleted(status: str, remedy: str) -> None:
    svc = _make_hse()
    jsa = await _seed(svc.jsa_repo, status)
    detail = await _refused(svc.delete_jsa(jsa.id))
    assert remedy in detail
    assert jsa.id in svc.jsa_repo.rows


@pytest.mark.parametrize("status", ["draft", "under_review"])
async def test_an_unsigned_jsa_can_still_be_deleted(status: str) -> None:
    svc = _make_hse()
    jsa = await _seed(svc.jsa_repo, status)
    await svc.delete_jsa(jsa.id)
    assert jsa.id not in svc.jsa_repo.rows


@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_a_closed_capa_is_not_deleted(status: str) -> None:
    svc = _make_hse()
    capa = await _seed(svc.capa_repo, status)
    await _refused(svc.delete_capa(capa.id))
    assert capa.id in svc.capa_repo.rows


@pytest.mark.parametrize("status", ["open", "in_progress", "overdue"])
async def test_an_open_capa_can_still_be_deleted(status: str) -> None:
    svc = _make_hse()
    capa = await _seed(svc.capa_repo, status)
    await svc.delete_capa(capa.id)
    assert capa.id not in svc.capa_repo.rows


# ── Inspection (C311) ───────────────────────────────────────────────────────


async def test_a_completed_inspection_is_not_deleted() -> None:
    row = _row("completed")
    svc = _service(InspectionService, "get_inspection", "repo", row)
    await _refused(svc.delete_inspection(row.id))
    assert svc.repo.deleted == []


@pytest.mark.parametrize("status", ["scheduled", "in_progress", "failed", "cancelled"])
async def test_an_uncompleted_inspection_can_still_be_deleted(status: str) -> None:
    row = _row(status)
    svc = _service(InspectionService, "get_inspection", "repo", row)
    await svc.delete_inspection(row.id)
    assert svc.repo.deleted == [row.id]


# ── Meeting (C318, C315) ────────────────────────────────────────────────────


def _meeting_service(status: str, minutes_status: str | None) -> tuple[Any, SimpleNamespace]:
    row = _row(status)
    svc = _service(MeetingService, "get_meeting", "repo", row)

    async def _minutes(_id: uuid.UUID) -> Any:
        return None if minutes_status is None else SimpleNamespace(status=minutes_status)

    svc.get_minutes_row = _minutes
    return svc, row


async def test_a_completed_meeting_is_not_deleted() -> None:
    svc, row = _meeting_service("completed", None)
    await _refused(svc.delete_meeting(row.id))
    assert svc.repo.deleted == []


@pytest.mark.parametrize(("status", "offers_cancel"), [("in_progress", True), ("cancelled", False)])
async def test_a_meeting_with_issued_minutes_is_not_deleted(status: str, offers_cancel: bool) -> None:
    svc, row = _meeting_service(status, "issued")
    detail = await _refused(svc.delete_meeting(row.id))
    assert ("Cancel the meeting" in detail) is offers_cancel
    assert svc.repo.deleted == []


@pytest.mark.parametrize(("status", "minutes_status"), [("draft", None), ("scheduled", "draft"), ("cancelled", None)])
async def test_a_meeting_without_a_record_can_still_be_deleted(status: str, minutes_status: str | None) -> None:
    svc, row = _meeting_service(status, minutes_status)
    await svc.delete_meeting(row.id)
    assert svc.repo.deleted == [row.id]


# ── NCR (C331) ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["closed", "void"])
async def test_a_closed_or_void_ncr_is_not_deleted(status: str) -> None:
    row = _row(status)
    svc = _service(NCRService, "get_ncr", "repo", row)
    await _refused(svc.delete_ncr(row.id))
    assert svc.repo.deleted == []


@pytest.mark.parametrize("status", ["identified", "under_review", "corrective_action", "verification"])
async def test_an_open_ncr_can_still_be_deleted(status: str) -> None:
    row = _row(status)
    svc = _service(NCRService, "get_ncr", "repo", row)
    await svc.delete_ncr(row.id)
    assert svc.repo.deleted == [row.id]


# ── Submittal (C491, C494) ──────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["approved", "approved_as_noted", "closed"])
async def test_a_decided_submittal_is_not_deleted(status: str) -> None:
    row = _row(status)
    svc = _service(SubmittalService, "get_submittal", "repo", row)
    await _refused(svc.delete_submittal(row.id))
    assert svc.repo.deleted == []


@pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "revise_and_resubmit", "rejected"])
async def test_an_undecided_submittal_can_still_be_deleted(status: str) -> None:
    row = _row(status)
    svc = _service(SubmittalService, "get_submittal", "repo", row)
    await svc.delete_submittal(row.id)
    assert svc.repo.deleted == [row.id]
