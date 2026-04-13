"""Unit tests for :class:`NCRService`.

Scope:
    Covers NCR CRUD, severity validation, status transition enforcement,
    corrective action requirements for closing, and update restrictions
    on terminal statuses. Repositories and event bus are stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.ncr.schemas import NCRCreate, NCRUpdate
from app.modules.ncr.service import NCRService, _NCR_STATUS_TRANSITIONS

# ── Helpers / stubs ───────────────────────────────────────────────────────

PROJECT_ID = uuid.uuid4()


def _make_service() -> NCRService:
    service = NCRService.__new__(NCRService)
    service.session = _StubSession()
    service.repo = _StubNCRRepo()
    return service


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        """Return empty result for notification queries."""
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class _StubNCRRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, ncr: Any) -> Any:
        if getattr(ncr, "id", None) is None:
            ncr.id = uuid.uuid4()
        now = datetime.now(UTC)
        ncr.created_at = now
        ncr.updated_at = now
        self.rows[ncr.id] = ncr
        return ncr

    async def get_by_id(self, ncr_id: uuid.UUID) -> Any:
        return self.rows.get(ncr_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        ncr_type: str | None = None,
        status: str | None = None,
        severity: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if ncr_type:
            rows = [r for r in rows if r.ncr_type == ncr_type]
        if status:
            rows = [r for r in rows if r.status == status]
        if severity:
            rows = [r for r in rows if r.severity == severity]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, ncr_id: uuid.UUID, **kwargs: Any) -> None:
        ncr = self.rows.get(ncr_id)
        if ncr:
            for k, v in kwargs.items():
                setattr(ncr, k, v)
            ncr.updated_at = datetime.now(UTC)

    async def delete(self, ncr_id: uuid.UUID) -> None:
        self.rows.pop(ncr_id, None)

    async def next_ncr_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"NCR-{self._counter:04d}"


def _create_data(**overrides: Any) -> NCRCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "title": "Concrete strength below spec",
        "description": "Cube test results 25MPa vs required 30MPa",
        "ncr_type": "material",
        "severity": "major",
    }
    defaults.update(overrides)
    return NCRCreate(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_ncr() -> None:
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(_create_data(), user_id="inspector-1")

    assert ncr.id is not None
    assert ncr.ncr_number == "NCR-0001"
    assert ncr.ncr_type == "material"
    assert ncr.severity == "major"
    assert ncr.status == "identified"
    assert ncr.created_by == "inspector-1"


@pytest.mark.asyncio
async def test_get_ncr_not_found() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_ncr(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_ncrs_with_filters() -> None:
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        await svc.create_ncr(_create_data(severity="critical"), user_id="u1")
        await svc.create_ncr(_create_data(severity="minor"), user_id="u1")

    rows, total = await svc.list_ncrs(PROJECT_ID, severity="critical")
    assert total == 1
    assert rows[0].severity == "critical"


@pytest.mark.asyncio
async def test_update_ncr_fields() -> None:
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(_create_data(), user_id="u1")

    updated = await svc.update_ncr(
        ncr.id,
        NCRUpdate(root_cause="Supplier delivered wrong grade"),
    )
    assert updated.root_cause == "Supplier delivered wrong grade"


@pytest.mark.asyncio
async def test_update_closed_ncr_blocked() -> None:
    """Cannot edit an NCR once it is closed."""
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(
            _create_data(corrective_action="Replace concrete"),
            user_id="u1",
        )
    # Force to closed
    svc.repo.rows[ncr.id].status = "closed"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_ncr(ncr.id, NCRUpdate(title="Attempt edit"))
    assert exc_info.value.status_code == 400
    assert "closed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_voided_ncr_blocked() -> None:
    """Cannot edit a voided NCR."""
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(_create_data(), user_id="u1")
    svc.repo.rows[ncr.id].status = "void"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_ncr(ncr.id, NCRUpdate(title="Attempt"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_status_transition_valid() -> None:
    """Test valid transition: identified -> under_review."""
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(_create_data(), user_id="u1")

    assert ncr.status == "identified"
    updated = await svc.update_ncr(ncr.id, NCRUpdate(status="under_review"))
    assert updated.status == "under_review"


@pytest.mark.asyncio
async def test_status_transition_invalid() -> None:
    """identified -> closed is not allowed (must go through the workflow)."""
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(_create_data(), user_id="u1")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_ncr(ncr.id, NCRUpdate(status="closed"))
    assert exc_info.value.status_code == 400
    assert "Cannot transition" in exc_info.value.detail


@pytest.mark.asyncio
async def test_close_ncr_requires_corrective_action() -> None:
    """Cannot close an NCR without a corrective action recorded."""
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(_create_data(), user_id="u1")

    # Move to verification status (skip workflow for unit test)
    svc.repo.rows[ncr.id].status = "verification"
    svc.repo.rows[ncr.id].corrective_action = None

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.close_ncr(ncr.id)
    assert exc_info.value.status_code == 400
    assert "corrective action" in exc_info.value.detail


@pytest.mark.asyncio
async def test_close_ncr_success() -> None:
    """Close an NCR that has a corrective action."""
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(
            _create_data(corrective_action="Replace all affected concrete"),
            user_id="u1",
        )

    # Move to verification
    svc.repo.rows[ncr.id].status = "verification"

    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        closed = await svc.close_ncr(ncr.id)
    assert closed.status == "closed"


@pytest.mark.asyncio
async def test_close_already_closed_ncr() -> None:
    svc = _make_service()
    with patch("app.modules.ncr.service.event_bus.publish", new_callable=AsyncMock):
        ncr = await svc.create_ncr(
            _create_data(corrective_action="Fix applied"),
            user_id="u1",
        )
    svc.repo.rows[ncr.id].status = "closed"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.close_ncr(ncr.id)
    assert exc_info.value.status_code == 400
    assert "already closed" in exc_info.value.detail
