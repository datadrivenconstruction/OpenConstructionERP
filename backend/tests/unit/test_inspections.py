"""Unit tests for :class:`InspectionService`.

Scope:
    CRUD, status transitions, complete_inspection with pass/fail/partial,
    checklist validation, and edit guards on terminal statuses.
    Repositories are stubbed so the suite doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.inspections.schemas import (
    ChecklistEntry,
    InspectionCreate,
    InspectionUpdate,
)
from app.modules.inspections.service import InspectionService, _validate_checklist_structure

# ── Helpers / stubs ───────────────────────────────────────────────────────


def _make_service() -> InspectionService:
    service = InspectionService.__new__(InspectionService)
    service.session = _StubSession()
    service.repo = _StubInspectionRepo()
    return service


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass


class _StubInspectionRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, inspection: Any) -> Any:
        if getattr(inspection, "id", None) is None:
            inspection.id = uuid.uuid4()
        now = datetime.now(UTC)
        inspection.created_at = now
        inspection.updated_at = now
        self.rows[inspection.id] = inspection
        return inspection

    async def get_by_id(self, inspection_id: uuid.UUID) -> Any:
        return self.rows.get(inspection_id)

    async def next_inspection_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"INS-{self._counter:03d}"

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        inspection_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if inspection_type is not None:
            rows = [r for r in rows if r.inspection_type == inspection_type]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, inspection_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(inspection_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, inspection_id: uuid.UUID) -> None:
        self.rows.pop(inspection_id, None)


# ── Checklist validation (sync helper) ───────────────────────────────────


def test_validate_checklist_valid_structure() -> None:
    """Valid checklist items should not raise."""
    checklist = [
        {"question": "Is rebar placed correctly?", "response_type": "yes_no"},
        {"question": "Concrete temperature OK?", "response_type": "numeric"},
    ]
    _validate_checklist_structure(checklist)  # should not raise


def test_validate_checklist_missing_question_raises_422() -> None:
    from fastapi import HTTPException

    checklist = [{"response_type": "yes_no"}]
    with pytest.raises(HTTPException) as exc_info:
        _validate_checklist_structure(checklist)
    assert exc_info.value.status_code == 422
    assert "question" in exc_info.value.detail.lower()


def test_validate_checklist_invalid_response_type_raises_422() -> None:
    from fastapi import HTTPException

    checklist = [{"question": "Check item", "response_type": "invalid_type"}]
    with pytest.raises(HTTPException) as exc_info:
        _validate_checklist_structure(checklist)
    assert exc_info.value.status_code == 422
    assert "response_type" in exc_info.value.detail.lower()


# ── Create ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_inspection_assigns_number_and_stores_checklist() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    data = InspectionCreate(
        project_id=pid,
        inspection_type="concrete_pour",
        title="Foundation Pour Inspection",
        checklist_data=[
            ChecklistEntry(question="Rebar placement correct?", response_type="yes_no"),
            ChecklistEntry(question="Concrete temp (C)?", response_type="numeric"),
        ],
    )
    inspection = await service.create_inspection(data, user_id="insp-1")

    assert inspection.id is not None
    assert inspection.inspection_number == "INS-001"
    assert inspection.status == "scheduled"
    assert len(inspection.checklist_data) == 2


@pytest.mark.asyncio
async def test_create_inspection_empty_checklist_ok() -> None:
    service = _make_service()
    data = InspectionCreate(
        project_id=uuid.uuid4(),
        inspection_type="general",
        title="General Walk-through",
    )
    inspection = await service.create_inspection(data)
    assert inspection.checklist_data == []


# ── List ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_inspections_project_scoped() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    await service.create_inspection(
        InspectionCreate(project_id=pid, inspection_type="mep", title="MEP Check")
    )
    await service.create_inspection(
        InspectionCreate(project_id=uuid.uuid4(), inspection_type="mep", title="Other")
    )

    rows, total = await service.list_inspections(pid)
    assert total == 1


# ── Complete ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_inspection_pass() -> None:
    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="structural",
            title="Beam Inspection",
        )
    )
    inspection.status = "in_progress"
    inspection.checklist_data = []

    result = await service.complete_inspection(inspection.id, "pass")
    assert result.status == "completed"
    assert result.result == "pass"


@pytest.mark.asyncio
async def test_complete_inspection_fail_with_checklist_items() -> None:
    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="fire_safety",
            title="Fire Stopping Check",
        )
    )
    inspection.status = "in_progress"
    inspection.checklist_data = [
        {"question": "Fire stopping intact?", "response": "fail"},
        {"question": "Sealant applied?", "response": "pass"},
    ]

    result = await service.complete_inspection(inspection.id, "fail")
    assert result.status == "completed"
    assert result.result == "fail"


@pytest.mark.asyncio
async def test_complete_inspection_invalid_result_raises_422() -> None:
    from fastapi import HTTPException

    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="General",
        )
    )
    inspection.status = "in_progress"

    with pytest.raises(HTTPException) as exc_info:
        await service.complete_inspection(inspection.id, "unknown")
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_complete_already_completed_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="Already Done",
        )
    )
    inspection.status = "completed"

    with pytest.raises(HTTPException) as exc_info:
        await service.complete_inspection(inspection.id, "pass")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_complete_cancelled_inspection_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="Cancelled",
        )
    )
    inspection.status = "cancelled"

    with pytest.raises(HTTPException) as exc_info:
        await service.complete_inspection(inspection.id, "pass")
    assert exc_info.value.status_code == 400


# ── Update guards ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_completed_inspection_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="Locked",
        )
    )
    inspection.status = "completed"

    with pytest.raises(HTTPException) as exc_info:
        await service.update_inspection(
            inspection.id, InspectionUpdate(title="New Title")
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_invalid_status_transition_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="Scheduled",
        )
    )
    # scheduled -> completed is NOT allowed (must go through in_progress)
    with pytest.raises(HTTPException) as exc_info:
        await service.update_inspection(
            inspection.id, InspectionUpdate(status="completed")
        )
    assert exc_info.value.status_code == 400


# ── Delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_inspection_removes_from_repo() -> None:
    from fastapi import HTTPException

    service = _make_service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="plumbing",
            title="Plumbing Check",
        )
    )
    await service.delete_inspection(inspection.id)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_inspection(inspection.id)
    assert exc_info.value.status_code == 404
