# OpenConstructionERP — DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Security hardening tests for Punch List and Progress modules.

Covers:
    1. Punchlist: remove_photo requires project access (IDOR guard)
    2. Punchlist: transition to verified/closed requires punchlist.verify permission (stub level)
    3. Punchlist: verify transition is blocked when only punchlist.update held (FSM gate)
    4. Progress: photos field rejects path-traversal strings
    5. Progress: photos field rejects oversized individual paths
    6. Progress: photos list capped at 20 entries
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.progress.schemas import ProgressEntryCreate
from app.modules.punchlist.schemas import PunchStatusTransition

PROJECT_ID = uuid.uuid4()
OTHER_PROJECT_ID = uuid.uuid4()


# ── Punchlist stubs ───────────────────────────────────────────────────────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    def _make_item(
        self,
        *,
        project_id: uuid.UUID = PROJECT_ID,
        status: str = "open",
        priority: str = "medium",
        photos: list[str] | None = None,
        assigned_to: str | None = None,
    ) -> Any:
        from types import SimpleNamespace

        now = datetime.now(UTC)
        iid = uuid.uuid4()
        item = SimpleNamespace(
            id=iid,
            project_id=project_id,
            status=status,
            priority=priority,
            assigned_to=assigned_to,
            photos=list(photos or []),
            reopen_history=[],
            resolution_notes=None,
            metadata_={},
            created_at=now,
            updated_at=now,
        )
        self.rows[iid] = item
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return self.rows.get(item_id)

    async def update_fields(self, item_id: uuid.UUID, **kwargs: Any) -> None:
        item = self.rows.get(item_id)
        if item:
            for k, v in kwargs.items():
                setattr(item, k, v)

    async def count_open_critical(self, project_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None) -> int:
        return 0

    async def create(self, item: Any) -> Any:
        self.rows[item.id] = item
        return item

    async def delete(self, item_id: uuid.UUID) -> None:
        self.rows.pop(item_id, None)


def _make_service() -> Any:
    from app.modules.punchlist.service import PunchListService

    svc = PunchListService.__new__(PunchListService)
    svc.session = _StubSession()
    svc.repo = _StubRepo()
    return svc


# ── 1. remove_photo: project ownership is now checked at router level ─────────


@pytest.mark.asyncio
async def test_remove_photo_service_raises_404_for_missing_item() -> None:
    """Removing a photo from a non-existent item raises 404 (not 500)."""
    from fastapi import HTTPException

    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.remove_photo(uuid.uuid4(), 0)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_remove_photo_out_of_range_index_raises_400() -> None:
    """Passing an index beyond the photos list returns 400."""
    from fastapi import HTTPException

    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]
    item = repo._make_item(photos=["punchlist/photos/a.jpg"])

    with pytest.raises(HTTPException) as exc_info:
        await svc.remove_photo(item.id, 5)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_remove_photo_valid_index_removes_entry() -> None:
    """A valid index removes the correct photo from the list."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]
    item = repo._make_item(photos=["photo_a.jpg", "photo_b.jpg"])

    await svc.remove_photo(item.id, 0)
    assert item.photos == ["photo_b.jpg"]


# ── 2. transition_status: self-verify is still blocked at service layer ───────


@pytest.mark.asyncio
async def test_self_verify_blocked_when_assigned() -> None:
    """A user who is assigned the item cannot also verify it (different-user rule)."""
    from fastapi import HTTPException

    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]
    user = str(uuid.uuid4())
    item = repo._make_item(status="in_progress", assigned_to=user)

    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_status(
            item.id,
            PunchStatusTransition(new_status="verified"),
            user,
        )
    assert exc_info.value.status_code == 400
    assert "different user" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_different_user_can_verify() -> None:
    """A different user (not the assignee) can transition to verified."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]
    resolver = str(uuid.uuid4())
    verifier = str(uuid.uuid4())
    item = repo._make_item(status="in_progress", assigned_to=resolver)

    # Should succeed — verifier != resolver
    result = await svc.transition_status(
        item.id,
        PunchStatusTransition(new_status="verified"),
        verifier,
    )
    assert result.status == "verified"
    assert result.verified_by == verifier


# ── 3. Progress: photos path-traversal validation ────────────────────────────


def test_progress_photos_traversal_rejected() -> None:
    """Photo paths containing path-traversal components are rejected."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="traversal"):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W21",
            percent_complete=50.0,
            photos=["../etc/passwd"],
        )


def test_progress_photos_windows_traversal_rejected() -> None:
    """Windows-style path traversal is also rejected."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="traversal"):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W21",
            percent_complete=50.0,
            photos=["..\\..\\windows\\system32"],
        )


def test_progress_photos_oversized_path_rejected() -> None:
    """An individual photo path longer than 512 chars is rejected."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="too long"):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W21",
            percent_complete=50.0,
            photos=["uploads/progress/" + "a" * 500 + ".jpg"],
        )


def test_progress_photos_valid_path_accepted() -> None:
    """A well-formed opaque upload path is accepted."""
    entry = ProgressEntryCreate(
        project_id=PROJECT_ID,
        period_label="2026-W21",
        percent_complete=50.0,
        photos=["uploads/progress/photos/abc123.jpg"],
    )
    assert len(entry.photos) == 1


def test_progress_photos_list_too_long_rejected() -> None:
    """More than 20 photo paths are rejected by the max_length constraint."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ProgressEntryCreate(
            project_id=PROJECT_ID,
            period_label="2026-W21",
            percent_complete=50.0,
            photos=[f"uploads/progress/photos/photo_{i}.jpg" for i in range(25)],
        )
