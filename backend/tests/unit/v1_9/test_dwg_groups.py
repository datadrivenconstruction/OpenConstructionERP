"""Unit tests for DWG entity group CRUD (RFC 11).

Scope:
    - Happy-path create: stores entity_ids + name, refuses empty lists.
    - Schema-level validation: Pydantic refuses empty ``entity_ids``.
    - Delete removes the row.

Repositories are stubbed so the suite doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.dwg_takeoff.schemas import DwgEntityGroupCreate
from app.modules.dwg_takeoff.service import DwgTakeoffService

# ── Stubs ─────────────────────────────────────────────────────────────────


class _StubGroupRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, group_id: uuid.UUID) -> Any:
        return self.rows.get(group_id)

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        now = datetime.now(UTC)
        item.created_at = now
        item.updated_at = now
        self.rows[item.id] = item
        return item

    async def list_for_drawing(
        self,
        drawing_id: uuid.UUID,
        *,
        offset: int = 0,  # noqa: ARG002
        limit: int = 200,  # noqa: ARG002
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.drawing_id == drawing_id]
        return rows, len(rows)

    async def delete(self, group_id: uuid.UUID) -> None:
        self.rows.pop(group_id, None)


class _StubDrawingRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, drawing_id: uuid.UUID) -> Any:
        return self.rows.get(drawing_id)


def _make_service() -> tuple[DwgTakeoffService, _StubDrawingRepo, _StubGroupRepo]:
    """Build a service with stub repos only (no DB)."""
    service = DwgTakeoffService.__new__(DwgTakeoffService)
    drawing_repo = _StubDrawingRepo()
    group_repo = _StubGroupRepo()
    service.session = None  # type: ignore[attr-defined]
    service.drawing_repo = drawing_repo  # type: ignore[attr-defined]
    service.group_repo = group_repo  # type: ignore[attr-defined]
    return service, drawing_repo, group_repo


def _register_drawing(drawing_repo: _StubDrawingRepo) -> uuid.UUID:
    drawing_id = uuid.uuid4()
    drawing_repo.rows[drawing_id] = SimpleNamespace(id=drawing_id)
    return drawing_id


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_group_happy_path() -> None:
    """Create stores entity_ids + name and round-trips through the service."""
    service, drawing_repo, group_repo = _make_service()
    drawing_id = _register_drawing(drawing_repo)

    payload = DwgEntityGroupCreate(
        drawing_id=drawing_id,
        entity_ids=["e_1", "e_7", "e_42"],
        name="Exterior walls",
        metadata={"source": "dwg-takeoff"},
    )
    item = await service.create_entity_group(payload, user_id="tester@example.com")

    assert item.id is not None
    assert item.drawing_id == drawing_id
    assert item.name == "Exterior walls"
    assert item.entity_ids == ["e_1", "e_7", "e_42"]
    assert item.metadata_ == {"source": "dwg-takeoff"}
    assert item.created_by == "tester@example.com"
    assert item.id in group_repo.rows


@pytest.mark.asyncio
async def test_create_group_missing_drawing_raises_404() -> None:
    """Creating a group for an unknown drawing is a 404, not a 500."""
    service, _drawing_repo, _group_repo = _make_service()

    payload = DwgEntityGroupCreate(
        drawing_id=uuid.uuid4(),
        entity_ids=["e_1"],
        name="Orphan",
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.create_entity_group(payload, user_id="tester@example.com")

    assert exc_info.value.status_code == 404


def test_create_group_empty_entity_ids_rejected_at_schema() -> None:
    """Pydantic enforces ``entity_ids`` min_length=1 (maps to 422 at the route)."""
    with pytest.raises(ValidationError):
        DwgEntityGroupCreate(
            drawing_id=uuid.uuid4(),
            entity_ids=[],
            name="Empty",
        )


def test_create_group_empty_name_rejected_at_schema() -> None:
    """Group name must be non-empty (whitespace is stripped first)."""
    with pytest.raises(ValidationError):
        DwgEntityGroupCreate(
            drawing_id=uuid.uuid4(),
            entity_ids=["e_1"],
            name="   ",
        )


@pytest.mark.asyncio
async def test_delete_group_happy_path() -> None:
    """Delete removes the stored row."""
    service, drawing_repo, group_repo = _make_service()
    drawing_id = _register_drawing(drawing_repo)

    payload = DwgEntityGroupCreate(
        drawing_id=drawing_id,
        entity_ids=["e_1"],
        name="Doomed",
    )
    item = await service.create_entity_group(payload, user_id="t@e.com")
    assert item.id in group_repo.rows

    await service.delete_entity_group(item.id)
    assert item.id not in group_repo.rows


@pytest.mark.asyncio
async def test_delete_missing_group_raises_404() -> None:
    """Deleting an unknown group is a 404."""
    service, _drawing_repo, _group_repo = _make_service()

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_entity_group(uuid.uuid4())

    assert exc_info.value.status_code == 404
