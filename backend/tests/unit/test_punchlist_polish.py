"""Wave 1 / T2 — Punch list polish tests.

Covers:
    * Reopen audit lifecycle (closed -> open writes a reopen_history entry).
    * Bulk-close summary (closed / skipped / errors accounting).
    * PDF smoke (export_pdf returns valid ``application/pdf`` bytes for a
      non-empty punch list).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.punchlist.schemas import (
    PunchItemCreate,
    PunchStatusTransition,
)
from app.modules.punchlist.service import PunchListService

PROJECT_ID = uuid.uuid4()


# ── Stubs (mirror tests/unit/test_punchlist.py shape) ─────────────────────


class _FakeNested:
    """Async context manager mimicking ``session.begin_nested()``."""

    async def __aenter__(self) -> object:
        return self

    async def __aexit__(self, exc_type: Any, *args: Any) -> None:
        if exc_type is not None:
            raise


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        # Mirror behaviour: items already carry mutations applied via
        # ``update_fields`` so refresh is a no-op for the stub.
        pass

    def begin_nested(self) -> _FakeNested:
        return _FakeNested()


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
        for attr, default in (
            ("photos", []),
            ("resolution_notes", None),
            ("resolved_at", None),
            ("verified_at", None),
            ("verified_by", None),
            ("reopen_history", []),
            ("document_id", None),
            ("page", None),
            ("location_x", None),
            ("location_y", None),
            ("category", None),
            ("trade", None),
            ("assigned_to", None),
            ("due_date", None),
            ("metadata_", {}),
        ):
            if not hasattr(item, attr) or getattr(item, attr) is None:
                setattr(item, attr, default if not isinstance(default, list | dict) else type(default)(default))
        self.rows[item.id] = item
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return self.rows.get(item_id)

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

    async def count_open_critical(
        self,
        project_id: uuid.UUID,
        exclude_id: uuid.UUID | None = None,
    ) -> int:
        return self._open_critical_count

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        **kwargs: Any,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        return rows, len(rows)

    async def summary_aggregates(self, project_id: uuid.UUID) -> dict[str, Any]:
        return {
            "total": 0,
            "by_status": {},
            "by_priority": {},
            "closed_timestamps": [],
        }

    async def count_overdue(self, project_id: uuid.UUID) -> int:
        return 0


def _make_service() -> PunchListService:
    service = PunchListService.__new__(PunchListService)
    service.session = _StubSession()
    service.repo = _StubPunchRepo()
    return service


def _create_data(**overrides: Any) -> PunchItemCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "title": "Fix cracked wall",
        "description": "Crack found in sector B",
        "priority": "medium",
    }
    defaults.update(overrides)
    return PunchItemCreate(**defaults)


# ── Reopen audit lifecycle ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reopen_history_records_terminal_to_active() -> None:
    """closed -> open appends a reopen_history entry with the right shape."""
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="creator")

    # Walk the item all the way to closed using the regular transition flow.
    # open -> in_progress
    await svc.transition_status(item.id, PunchStatusTransition(new_status="in_progress"), user_id="worker")
    # in_progress -> resolved
    await svc.transition_status(item.id, PunchStatusTransition(new_status="resolved"), user_id="worker")
    # resolved -> verified (must be a different user)
    await svc.transition_status(item.id, PunchStatusTransition(new_status="verified"), user_id="inspector")
    # verified -> closed
    await svc.transition_status(item.id, PunchStatusTransition(new_status="closed"), user_id="manager")

    # Sanity — no reopen yet
    assert getattr(item, "reopen_history", []) == []

    # Reopen: closed -> open
    await svc.transition_status(
        item.id,
        PunchStatusTransition(new_status="open", notes="defect re-observed"),
        user_id="qa",
    )

    history = list(item.reopen_history)
    assert len(history) == 1
    entry = history[0]
    assert entry["previous_status"] == "closed"
    assert entry["reopened_by"] == "qa"
    assert entry["reason"] == "defect re-observed"
    # ISO8601 string with a UTC offset
    assert "T" in entry["reopened_at"]
    assert entry["reopened_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_reopen_history_unchanged_for_normal_forward_transitions() -> None:
    """Forward transitions (open -> in_progress) must NOT append to history."""
    svc = _make_service()
    item = await svc.create_item(_create_data(), user_id="creator")

    await svc.transition_status(item.id, PunchStatusTransition(new_status="in_progress"), user_id="worker")

    assert list(item.reopen_history) == []


# ── Bulk close ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_close_summary_split() -> None:
    """5 items, 1 already-closed -> 4 closed + 1 skipped, 0 errors."""
    svc = _make_service()

    items = []
    for i in range(5):
        item = await svc.create_item(
            _create_data(title=f"Item {i}", priority="low"),
            user_id="creator",
        )
        items.append(item)

    # Walk item 0 all the way to closed via the regular pipeline.
    target = items[0]
    await svc.transition_status(target.id, PunchStatusTransition(new_status="in_progress"), user_id="w")
    await svc.transition_status(target.id, PunchStatusTransition(new_status="resolved"), user_id="w")
    await svc.transition_status(target.id, PunchStatusTransition(new_status="verified"), user_id="i")
    await svc.transition_status(target.id, PunchStatusTransition(new_status="closed"), user_id="m")

    assert target.status == "closed"

    result = await svc.bulk_close(
        PROJECT_ID,
        [it.id for it in items],
        user_id="m",
        comment="end-of-project sweep",
    )

    assert result["closed"] == 4
    assert result["skipped"] == 1
    assert result["errors"] == []

    # All items should now be closed
    for it in items:
        assert it.status == "closed"


@pytest.mark.asyncio
async def test_bulk_close_project_mismatch_returns_error() -> None:
    """Items belonging to a different project surface as an explicit error."""
    svc = _make_service()
    other_project = uuid.uuid4()

    a = await svc.create_item(_create_data(title="A"), user_id="u1")
    b = await svc.create_item(
        _create_data(project_id=other_project, title="B"),
        user_id="u1",
    )

    result = await svc.bulk_close(PROJECT_ID, [a.id, b.id], user_id="m")

    assert result["closed"] == 1
    assert result["skipped"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == str(b.id)
    assert result["errors"][0]["error"] == "project_mismatch"


# ── PDF export smoke ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_pdf_smoke_returns_valid_pdf() -> None:
    """Exporting a 3-item punch list returns valid PDF bytes."""
    svc = _make_service()
    for i in range(3):
        await svc.create_item(
            _create_data(title=f"Punch {i}", priority="high"),
            user_id="u",
        )

    pdf_bytes = await svc.export_pdf(PROJECT_ID)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF"), "expected PDF magic header"
    assert b"%%EOF" in pdf_bytes[-1024:], "expected PDF trailer near EOF"
    # Size sanity — even an empty ReportLab PDF is > 500 bytes.
    assert len(pdf_bytes) > 500
