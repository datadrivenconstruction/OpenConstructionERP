"""Unit tests for :class:`PunchListService`.

Scope:
    Covers punch item CRUD, status transition workflow
    (open -> in_progress -> resolved -> verified -> closed),
    photo management, and summary aggregation.
    Repositories are stubbed so the suite doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.punchlist.schemas import PunchItemCreate, PunchItemUpdate, PunchStatusTransition
from app.modules.punchlist.service import PunchListService, VALID_TRANSITIONS

# ── Helpers / stubs ───────────────────────────────────────────────────────

PROJECT_ID = uuid.uuid4()


def _make_service() -> PunchListService:
    service = PunchListService.__new__(PunchListService)
    service.session = _StubSession()
    service.repo = _StubPunchRepo()
    return service


class _StubSession:
    """Minimal async session stub that supports refresh()."""

    async def refresh(self, obj: Any) -> None:
        pass


class _StubPunchRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._open_critical_count = 0

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        now = datetime.now(UTC)
        item.created_at = now
        item.updated_at = now
        if not hasattr(item, "photos") or item.photos is None:
            item.photos = []
        if not hasattr(item, "resolution_notes"):
            item.resolution_notes = None
        if not hasattr(item, "resolved_at"):
            item.resolved_at = None
        if not hasattr(item, "verified_at"):
            item.verified_at = None
        if not hasattr(item, "verified_by"):
            item.verified_by = None
        self.rows[item.id] = item
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return self.rows.get(item_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        category: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status:
            rows = [r for r in rows if r.status == status]
        if priority:
            rows = [r for r in rows if r.priority == priority]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, item_id: uuid.UUID, **kwargs: Any) -> None:
        item = self.rows.get(item_id)
        if item:
            for k, v in kwargs.items():
                setattr(item, k, v)
            item.updated_at = datetime.now(UTC)

    async def delete(self, item_id: uuid.UUID) -> None:
        self.rows.pop(item_id, None)

    async def all_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.project_id == project_id]

    async def count_overdue(self, project_id: uuid.UUID) -> int:
        return 0

    async def count_open_critical(
        self, project_id: uuid.UUID, exclude_id: uuid.UUID | None = None,
    ) -> int:
        return self._open_critical_count


def _create_data(**overrides: Any) -> PunchItemCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "title": "Fix cracked wall",
        "description": "Crack found in sector B",
        "priority": "high",
    }
    defaults.update(overrides)
    return PunchItemCreate(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_item() -> None:
    svc = _make_service()
    data = _create_data()
    item = await svc.create_item(data, user_id="user-1")

    assert item.id is not None
    assert item.project_id == PROJECT_ID
    assert item.title == "Fix cracked wall"
    assert item.status == "open"
    assert item.priority == "high"
    assert item.created_by == "user-1"


@pytest.mark.asyncio
async def test_get_item_not_found() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_item(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_items_filters_by_project() -> None:
    svc = _make_service()
    other_project = uuid.uuid4()
    await svc.create_item(_create_data(), user_id="u1")
    await svc.create_item(_create_data(project_id=other_project, title="Other"), user_id="u1")

    items, total = await svc.list_items(PROJECT_ID)
    assert total == 1
    assert items[0].project_id == PROJECT_ID


@pytest.mark.asyncio
async def test_update_item() -> None:
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="u1")

    updated = await svc.update_item(
        item.id,
        PunchItemUpdate(title="Updated title", priority="critical"),
    )
    assert updated.title == "Updated title"
    assert updated.priority == "critical"


@pytest.mark.asyncio
async def test_delete_item() -> None:
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="u1")
    await svc.delete_item(item.id)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_item(item.id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_status_transition_open_to_in_progress() -> None:
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="u1")
    assert item.status == "open"

    transition = PunchStatusTransition(new_status="in_progress")
    updated = await svc.transition_status(item.id, transition, user_id="u1")
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_status_transition_invalid_blocked() -> None:
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="u1")
    assert item.status == "open"

    from fastapi import HTTPException

    # open -> resolved is not allowed (must go through in_progress first)
    transition = PunchStatusTransition(new_status="resolved")
    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_status(item.id, transition, user_id="u1")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_full_status_workflow() -> None:
    """Test the complete lifecycle: open -> in_progress -> resolved -> verified -> closed."""
    svc = _make_service()
    item = await svc.create_item(
        _create_data(priority="medium", assigned_to="resolver-user"),
        user_id="creator",
    )

    # open -> in_progress
    item = await svc.transition_status(
        item.id, PunchStatusTransition(new_status="in_progress"), user_id="resolver-user",
    )
    assert item.status == "in_progress"

    # in_progress -> resolved
    item = await svc.transition_status(
        item.id,
        PunchStatusTransition(new_status="resolved", notes="Wall patched"),
        user_id="resolver-user",
    )
    assert item.status == "resolved"
    assert item.resolved_at is not None

    # resolved -> verified (must be different user than assigned_to)
    item = await svc.transition_status(
        item.id, PunchStatusTransition(new_status="verified"), user_id="verifier-user",
    )
    assert item.status == "verified"
    assert item.verified_by == "verifier-user"

    # verified -> closed
    item = await svc.transition_status(
        item.id, PunchStatusTransition(new_status="closed"), user_id="admin",
    )
    assert item.status == "closed"


@pytest.mark.asyncio
async def test_verification_same_user_blocked() -> None:
    """Verification by the assigned user should be rejected."""
    svc = _make_service()
    item = await svc.create_item(
        _create_data(assigned_to="user-A"),
        user_id="creator",
    )

    # Move to resolved
    await svc.transition_status(
        item.id, PunchStatusTransition(new_status="in_progress"), user_id="user-A",
    )
    await svc.transition_status(
        item.id, PunchStatusTransition(new_status="resolved"), user_id="user-A",
    )

    from fastapi import HTTPException

    # Verify by same assigned user should fail
    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_status(
            item.id, PunchStatusTransition(new_status="verified"), user_id="user-A",
        )
    assert exc_info.value.status_code == 400
    assert "different user" in exc_info.value.detail


@pytest.mark.asyncio
async def test_add_and_remove_photo() -> None:
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="u1")
    assert item.photos == []

    item = await svc.add_photo(item.id, "/uploads/crack1.jpg")
    assert item.photos == ["/uploads/crack1.jpg"]

    item = await svc.add_photo(item.id, "/uploads/crack2.jpg")
    assert len(item.photos) == 2

    item = await svc.remove_photo(item.id, 0)
    assert item.photos == ["/uploads/crack2.jpg"]


@pytest.mark.asyncio
async def test_remove_photo_invalid_index() -> None:
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="u1")
    await svc.add_photo(item.id, "/uploads/photo.jpg")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.remove_photo(item.id, 5)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_summary_aggregation() -> None:
    svc = _make_service()
    await svc.create_item(_create_data(priority="high"), user_id="u1")
    await svc.create_item(_create_data(priority="low"), user_id="u1")

    summary = await svc.get_summary(PROJECT_ID)
    assert summary["total"] == 2
    assert summary["by_status"]["open"] == 2
    assert summary["by_priority"]["high"] == 1
    assert summary["by_priority"]["low"] == 1
