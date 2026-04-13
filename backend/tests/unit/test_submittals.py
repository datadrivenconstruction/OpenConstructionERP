"""Unit tests for :class:`SubmittalService`.

Scope:
    CRUD operations, status transition validation, submit/review/approve
    workflow, and ball-in-court logic.  Repositories are stubbed so the
    suite doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.submittals.schemas import SubmittalCreate, SubmittalUpdate
from app.modules.submittals.service import SubmittalService

# ── Helpers / stubs ───────────────────────────────────────────────────────


def _make_service() -> SubmittalService:
    service = SubmittalService.__new__(SubmittalService)
    service.session = _StubSession()
    service.repo = _StubSubmittalRepo()
    return service


class _StubSession:
    """Minimal session stub that supports refresh()."""

    async def refresh(self, obj: Any) -> None:
        pass


class _StubSubmittalRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, submittal: Any) -> Any:
        if getattr(submittal, "id", None) is None:
            submittal.id = uuid.uuid4()
        now = datetime.now(UTC)
        submittal.created_at = now
        submittal.updated_at = now
        self.rows[submittal.id] = submittal
        return submittal

    async def get_by_id(self, submittal_id: uuid.UUID) -> Any:
        return self.rows.get(submittal_id)

    async def next_submittal_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"SUB-{self._counter:03d}"

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        submittal_type: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if submittal_type is not None:
            rows = [r for r in rows if r.submittal_type == submittal_type]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, submittal_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(submittal_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, submittal_id: uuid.UUID) -> None:
        self.rows.pop(submittal_id, None)


# ── Create ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_submittal_assigns_number_and_defaults() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    data = SubmittalCreate(
        project_id=pid,
        title="Shop Drawing - Structural Steel",
        submittal_type="shop_drawing",
    )
    submittal = await service.create_submittal(data, user_id="user-1")

    assert submittal.id is not None
    assert submittal.submittal_number == "SUB-001"
    assert submittal.status == "draft"
    assert submittal.ball_in_court == "user-1"
    assert submittal.project_id == pid


@pytest.mark.asyncio
async def test_create_submittal_ball_in_court_goes_to_reviewer_when_submitted() -> None:
    """When initial status is 'submitted' and reviewer_id is set,
    ball_in_court defaults to the reviewer."""
    service = _make_service()
    reviewer = "reviewer-42"
    data = SubmittalCreate(
        project_id=uuid.uuid4(),
        title="Product Data - Waterproofing",
        submittal_type="product_data",
        status="submitted",
        reviewer_id=reviewer,
    )
    submittal = await service.create_submittal(data, user_id="user-1")
    assert submittal.ball_in_court == reviewer


# ── List ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_submittals_filters_by_project() -> None:
    service = _make_service()
    pid1 = uuid.uuid4()
    pid2 = uuid.uuid4()
    await service.create_submittal(
        SubmittalCreate(project_id=pid1, title="A", submittal_type="sample")
    )
    await service.create_submittal(
        SubmittalCreate(project_id=pid2, title="B", submittal_type="sample")
    )

    rows, total = await service.list_submittals(pid1)
    assert total == 1
    assert rows[0].title == "A"


# ── Status transitions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_draft_moves_to_submitted_and_sets_revision() -> None:
    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="Test Report",
            submittal_type="test_report",
            current_revision=1,
            reviewer_id="reviewer-1",
        )
    )
    # Force draft status (default)
    submittal.status = "draft"
    submittal.current_revision = 0

    result = await service.submit_submittal(submittal.id)
    assert result.status == "submitted"
    assert result.current_revision == 1
    assert result.ball_in_court == "reviewer-1"


@pytest.mark.asyncio
async def test_submit_from_revise_and_resubmit_increments_revision() -> None:
    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="Mock Up",
            submittal_type="mock_up",
            reviewer_id="rev-1",
        )
    )
    submittal.status = "revise_and_resubmit"
    submittal.current_revision = 2

    result = await service.submit_submittal(submittal.id)
    assert result.status == "submitted"
    assert result.current_revision == 3


@pytest.mark.asyncio
async def test_submit_from_invalid_status_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="Certificate",
            submittal_type="certificate",
        )
    )
    submittal.status = "approved"

    with pytest.raises(HTTPException) as exc_info:
        await service.submit_submittal(submittal.id)
    assert exc_info.value.status_code == 400


# ── Review ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_submittal_approved_keeps_ball_with_reviewer() -> None:
    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="Warranty Doc",
            submittal_type="warranty",
        ),
        user_id="creator-1",
    )
    submittal.status = "submitted"

    result = await service.review_submittal(submittal.id, "approved", "reviewer-1")
    assert result.status == "approved"
    assert result.ball_in_court == "reviewer-1"


@pytest.mark.asyncio
async def test_review_submittal_revise_returns_ball_to_creator() -> None:
    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="Shop Drawing - HVAC",
            submittal_type="shop_drawing",
        ),
        user_id="creator-1",
    )
    submittal.status = "submitted"

    result = await service.review_submittal(
        submittal.id, "revise_and_resubmit", "reviewer-1"
    )
    assert result.status == "revise_and_resubmit"
    assert result.ball_in_court == "creator-1"


# ── Update with invalid transition ──────────────────────────────────────


@pytest.mark.asyncio
async def test_update_closed_submittal_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="Closed Item",
            submittal_type="sample",
        )
    )
    submittal.status = "closed"

    with pytest.raises(HTTPException) as exc_info:
        await service.update_submittal(
            submittal.id, SubmittalUpdate(title="New Title")
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_invalid_status_transition_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="Draft item",
            submittal_type="product_data",
        )
    )
    # draft -> approved is NOT allowed (must go through submitted first)
    with pytest.raises(HTTPException) as exc_info:
        await service.update_submittal(
            submittal.id, SubmittalUpdate(status="approved")
        )
    assert exc_info.value.status_code == 400


# ── Delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_submittal_removes_from_repo() -> None:
    service = _make_service()
    submittal = await service.create_submittal(
        SubmittalCreate(
            project_id=uuid.uuid4(),
            title="To Delete",
            submittal_type="sample",
        )
    )
    await service.delete_submittal(submittal.id)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.get_submittal(submittal.id)
    assert exc_info.value.status_code == 404
