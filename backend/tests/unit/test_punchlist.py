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

    async def summary_aggregates(self, project_id: uuid.UUID) -> dict[str, Any]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for r in rows:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            by_priority[r.priority] = by_priority.get(r.priority, 0) + 1
        closed = [
            (r.created_at, r.verified_at, r.resolved_at, r.updated_at)
            for r in rows
            if r.status in ("closed", "verified")
        ]
        return {
            "total": len(rows),
            "by_status": by_status,
            "by_priority": by_priority,
            "closed_timestamps": closed,
        }

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


# ── Photo upload size-cap (CodeQL D9 regression) ──────────────────────────


class _StubUploadFile:
    """Minimal UploadFile substitute for direct-call tests of upload_photo.

    Starlette's UploadFile is heavyweight (SpooledTemporaryFile-backed);
    for cap-check tests we just need an awaitable read() and the few
    attributes the handler reads.
    """

    def __init__(self, content: bytes, content_type: str = "image/jpeg",
                 filename: str = "photo.jpg") -> None:
        self._content = content
        self.content_type = content_type
        self.filename = filename

    async def read(self) -> bytes:
        return self._content


@pytest.mark.asyncio
async def test_upload_photo_rejects_oversize_via_content_length() -> None:
    """Content-Length above 25MB cap must 413 BEFORE the body is read."""
    from fastapi import HTTPException
    from app.modules.punchlist.router import MAX_PUNCHLIST_PHOTO_BYTES, upload_photo

    # Sentinel content; should never be reached because Content-Length
    # check fires first.
    fake_file = _StubUploadFile(b"unused")

    with pytest.raises(HTTPException) as exc_info:
        await upload_photo(
            item_id=uuid.uuid4(),
            file=fake_file,  # type: ignore[arg-type]
            content_length=MAX_PUNCHLIST_PHOTO_BYTES + 1,
            user_id="u1",
            _perm=None,
            service=_make_service(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 413
    assert "25 MB" in exc_info.value.detail


@pytest.mark.asyncio
async def test_upload_photo_rejects_oversize_body_when_content_length_lies() -> None:
    """If Content-Length is missing/lying, the post-read length check still fires."""
    from fastapi import HTTPException
    from app.modules.punchlist.router import MAX_PUNCHLIST_PHOTO_BYTES, upload_photo

    # 25 MB + 1 byte payload, sent without a Content-Length header.
    fake_file = _StubUploadFile(b"x" * (MAX_PUNCHLIST_PHOTO_BYTES + 1))

    with pytest.raises(HTTPException) as exc_info:
        await upload_photo(
            item_id=uuid.uuid4(),
            file=fake_file,  # type: ignore[arg-type]
            content_length=None,
            user_id="u1",
            _perm=None,
            service=_make_service(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_upload_photo_constant_is_25mb() -> None:
    """Pin the cap to 25 MB exactly — protects against accidental drift."""
    from app.modules.punchlist.router import MAX_PUNCHLIST_PHOTO_BYTES

    assert MAX_PUNCHLIST_PHOTO_BYTES == 25 * 1024 * 1024
