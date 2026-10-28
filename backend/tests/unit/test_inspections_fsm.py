"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FSM lifecycle tests for ``InspectionService.complete_inspection``.

The inspection lifecycle is:

    scheduled → in_progress → completed (terminal)
                            \\
                             → failed → (re-)scheduled

``complete_inspection`` is the capstone transition and must reject
attempts to complete from any state other than ``scheduled`` or
``in_progress``. Before this hardening pass it silently allowed
re-completing from ``failed``, which broke the failed→scheduled
re-inspection contract documented in
``_INSPECTION_STATUS_TRANSITIONS``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.inspections.schemas import InspectionCreate
from app.modules.inspections.service import InspectionService


class _StubSession:
    async def refresh(self, obj: Any) -> None:  # pragma: no cover - trivial
        pass


class _StubRepo:
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

    async def update_fields(self, inspection_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(inspection_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)


def _service() -> InspectionService:
    s = InspectionService.__new__(InspectionService)
    s.session = _StubSession()
    s.repo = _StubRepo()
    return s


@pytest.mark.asyncio
async def test_complete_from_failed_state_rejected() -> None:
    """``failed`` is not a launchpad for ``complete`` — must reschedule first.

    Pre-fix this returned a 200 and silently flipped the inspection
    back to ``completed`` even though the FSM dict says ``failed`` can
    only transition to ``scheduled`` (re-inspection).
    """
    service = _service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="Previously failed inspection",
        )
    )
    inspection.status = "failed"

    with pytest.raises(HTTPException) as exc_info:
        await service.complete_inspection(inspection.id, "pass")
    assert exc_info.value.status_code == 400
    detail = (exc_info.value.detail or "").lower()
    assert "failed" in detail or "reschedule" in detail


@pytest.mark.asyncio
async def test_complete_from_scheduled_allowed_shortcut() -> None:
    """Short inspections may shortcut scheduled → completed.

    The FSM dict allows scheduled → in_progress only, but the complete
    endpoint deliberately accepts ``scheduled`` as a one-step
    convenience for inspections that don't need an explicit start tick.
    """
    service = _service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="Shortcut path",
        )
    )
    assert inspection.status == "scheduled"

    result = await service.complete_inspection(inspection.id, "pass")
    assert result.status == "completed"
    assert result.result == "pass"


@pytest.mark.asyncio
async def test_complete_from_in_progress_allowed_canonical() -> None:
    """The canonical scheduled → in_progress → completed path works."""
    service = _service()
    inspection = await service.create_inspection(
        InspectionCreate(
            project_id=uuid.uuid4(),
            inspection_type="general",
            title="Canonical path",
        )
    )
    inspection.status = "in_progress"

    result = await service.complete_inspection(inspection.id, "fail")
    assert result.status == "completed"
    assert result.result == "fail"
