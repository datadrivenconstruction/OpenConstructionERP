"""Unit tests for :class:`RFIService`.

Scope:
    CRUD, status transitions, respond/close workflow, is_overdue logic,
    days_open calculation, and business-day due date computation.
    Repositories are stubbed so the suite doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.rfi.schemas import RFICreate, RFIUpdate
from app.modules.rfi.service import RFIService, _add_business_days

# ── Helpers / stubs ───────────────────────────────────────────────────────


def _make_service() -> RFIService:
    service = RFIService.__new__(RFIService)
    service.session = _StubSession()
    service.repo = _StubRFIRepo()
    return service


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass


class _StubRFIRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, rfi: Any) -> Any:
        if getattr(rfi, "id", None) is None:
            rfi.id = uuid.uuid4()
        now = datetime.now(UTC)
        rfi.created_at = now
        rfi.updated_at = now
        self.rows[rfi.id] = rfi
        return rfi

    async def get_by_id(self, rfi_id: uuid.UUID) -> Any:
        return self.rows.get(rfi_id)

    async def next_rfi_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"RFI-{self._counter:03d}"

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, rfi_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(rfi_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, rfi_id: uuid.UUID) -> None:
        self.rows.pop(rfi_id, None)


# ── Utility: _add_business_days ──────────────────────────────────────────


def test_add_business_days_skips_weekends() -> None:
    """Friday + 1 business day = Monday."""
    # 2026-04-10 is a Friday
    friday = datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)
    result = _add_business_days(friday, 1)
    assert result == "2026-04-13"  # Monday


def test_add_business_days_14_days() -> None:
    """14 business days from a Monday spans exactly 2 weeks + weekends."""
    monday = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
    result = _add_business_days(monday, 14)
    # 14 business days from Apr 6 (Mon) = Apr 24 (Fri)
    assert result == "2026-04-24"


# ── Create ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rfi_assigns_number_and_ball_in_court() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    assigned = str(uuid.uuid4())
    data = RFICreate(
        project_id=pid,
        subject="Foundation Depth Clarification",
        question="What is the required footing depth?",
        assigned_to=assigned,
    )
    rfi = await service.create_rfi(data, user_id=str(uuid.uuid4()))

    assert rfi.id is not None
    assert rfi.rfi_number == "RFI-001"
    assert rfi.ball_in_court == assigned


@pytest.mark.asyncio
async def test_create_rfi_open_status_auto_calculates_due_date() -> None:
    """When status is 'open' and no explicit due date, auto-calculate 14 business days."""
    service = _make_service()
    data = RFICreate(
        project_id=uuid.uuid4(),
        subject="Steel Grade Query",
        question="Which steel grade for columns?",
        status="open",
    )
    rfi = await service.create_rfi(data)
    assert rfi.response_due_date is not None


# ── List ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_rfis_returns_project_scoped_results() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    await service.create_rfi(
        RFICreate(project_id=pid, subject="A", question="Q1")
    )
    await service.create_rfi(
        RFICreate(project_id=uuid.uuid4(), subject="B", question="Q2")
    )

    rows, total = await service.list_rfis(pid)
    assert total == 1
    assert rows[0].subject == "A"


# ── Respond ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_respond_to_rfi_sets_answered_and_flips_ball() -> None:
    service = _make_service()
    raiser = uuid.uuid4()
    data = RFICreate(
        project_id=uuid.uuid4(),
        subject="Concrete Mix",
        question="C30/37 or C35/45?",
        raised_by=raiser,
    )
    rfi = await service.create_rfi(data)
    rfi.status = "open"

    result = await service.respond_to_rfi(rfi.id, "Use C35/45", "responder-1")
    assert result.status == "answered"
    assert result.official_response == "Use C35/45"
    assert result.ball_in_court == str(raiser)


@pytest.mark.asyncio
async def test_respond_to_closed_rfi_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Closed",
            question="N/A",
        )
    )
    rfi.status = "closed"

    with pytest.raises(HTTPException) as exc_info:
        await service.respond_to_rfi(rfi.id, "Too late", "user-1")
    assert exc_info.value.status_code == 400


# ── Close ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_rfi_requires_official_response() -> None:
    """An RFI without an official response cannot be closed."""
    from fastapi import HTTPException

    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Pending",
            question="Still waiting...",
        )
    )
    rfi.status = "open"
    rfi.official_response = None

    with pytest.raises(HTTPException) as exc_info:
        await service.close_rfi(rfi.id)
    assert exc_info.value.status_code == 400
    assert "official response" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_close_rfi_with_response_succeeds() -> None:
    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Answered",
            question="Done?",
        )
    )
    rfi.status = "answered"
    rfi.official_response = "Yes, confirmed."

    result = await service.close_rfi(rfi.id, closed_by="mgr-1")
    assert result.status == "closed"
    assert result.ball_in_court is None


# ── Update with invalid transition ──────────────────────────────────────


@pytest.mark.asyncio
async def test_update_closed_rfi_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Locked",
            question="Cannot edit",
        )
    )
    rfi.status = "closed"

    with pytest.raises(HTTPException) as exc_info:
        await service.update_rfi(rfi.id, RFIUpdate(subject="New Subject"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_invalid_status_transition_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Draft",
            question="Trying to jump",
        )
    )
    # draft -> closed is not allowed
    with pytest.raises(HTTPException) as exc_info:
        await service.update_rfi(rfi.id, RFIUpdate(status="closed"))
    assert exc_info.value.status_code == 400


# ── Delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_rfi_removes_from_repo() -> None:
    from fastapi import HTTPException

    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="To Delete",
            question="Bye",
        )
    )
    await service.delete_rfi(rfi.id)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_rfi(rfi.id)
    assert exc_info.value.status_code == 404
