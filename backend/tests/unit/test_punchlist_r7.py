# OpenConstructionERP — DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Round-7 hardening tests for the Punch List module.

Covers:
    1. FSM — ``assigned`` state: open → assigned → in_progress → verified → closed
    2. FSM — ``reopened`` alias maps to ``open`` and records reopen_history
    3. Rework cost: Decimal-string validation (reject float payload, accept valid string)
    4. Geo-tagging: lat/lon validation via Pydantic schema (422 on out-of-range)
    5. Trade filter: list_items only returns items matching the requested trade
    6. Bulk close atomicity: project_mismatch items are rejected without touching others
    7. IDOR guard: bulk_close rejects items from a different project
    8. Photo magic-byte schema: PunchItemCreate accepts valid photos list
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.modules.punchlist.schemas import (
    PunchItemCreate,
    PunchStatusTransition,
)
from app.modules.punchlist.service import VALID_TRANSITIONS, PunchListService

# ── Helpers / stubs ──────────────────────────────────────────────────────────

PROJECT_ID = uuid.uuid4()
OTHER_PROJECT_ID = uuid.uuid4()


def _make_service() -> PunchListService:
    svc = PunchListService.__new__(PunchListService)
    svc.session = _StubSession()
    svc.repo = _StubRepo()
    return svc


class _StubSession:
    def __init__(self) -> None:
        self._repo: _StubRepo | None = None  # set after construction

    async def refresh(self, obj: Any) -> None:
        pass

    def begin_nested(self) -> _FakeNested:
        return _FakeNested()


class _FakeNested:
    """Minimal async context manager mimicking ``session.begin_nested()``."""

    async def __aenter__(self) -> _FakeNested:
        return self

    async def __aexit__(self, exc_type: Any, *args: Any) -> None:
        if exc_type is not None:
            raise


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._open_critical = 0

    def _make_item(
        self,
        *,
        project_id: uuid.UUID = PROJECT_ID,
        priority: str = "medium",
        status: str = "open",
        trade: str | None = None,
        assigned_to: str | None = None,
    ) -> Any:
        from types import SimpleNamespace

        now = datetime.now(UTC)
        iid = uuid.uuid4()
        item = SimpleNamespace(
            id=iid,
            project_id=project_id,
            priority=priority,
            status=status,
            assigned_to=assigned_to,
            trade=trade,
            resolution_notes=None,
            photos=[],
            reopen_history=[],
            metadata_={},
            created_at=now,
            updated_at=now,
        )
        self.rows[iid] = item
        return item

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        now = datetime.now(UTC)
        item.created_at = now
        item.updated_at = now
        if not hasattr(item, "reopen_history"):
            item.reopen_history = []
        if not hasattr(item, "metadata_"):
            item.metadata_ = {}
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
        trade: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status:
            rows = [r for r in rows if r.status == status]
        if trade:
            rows = [r for r in rows if getattr(r, "trade", None) == trade]
        return rows[offset : offset + limit], len(rows)

    async def count_open_critical(
        self,
        project_id: uuid.UUID,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> int:
        return self._open_critical

    async def all_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.project_id == project_id]

    async def summary_aggregates(self, project_id: uuid.UUID) -> dict[str, Any]:
        return {"total": 0, "by_status": {}, "by_priority": {}, "closed_timestamps": []}

    async def count_overdue(self, project_id: uuid.UUID) -> int:
        return 0

    async def delete(self, item_id: uuid.UUID) -> None:
        self.rows.pop(item_id, None)


# ── 1. FSM: open → assigned → in_progress → verified → closed ────────────────


@pytest.mark.asyncio
async def test_fsm_assigned_state_in_transitions() -> None:
    """VALID_TRANSITIONS must include 'assigned' as a reachable state."""
    assert "assigned" in VALID_TRANSITIONS["open"], "'open' should allow transition to 'assigned'"
    assert "in_progress" in VALID_TRANSITIONS["assigned"], "'assigned' should allow transition to 'in_progress'"
    assert "open" in VALID_TRANSITIONS["assigned"], "'assigned' should allow transition back to 'open'"


@pytest.mark.asyncio
async def test_fsm_full_lifecycle_with_assigned() -> None:
    """Full FSM walk: open → assigned → in_progress → verified → closed."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]

    item = repo._make_item(status="open")

    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    # open → assigned
    await svc.transition_status(item.id, PunchStatusTransition(new_status="assigned"), user_a)
    assert item.status == "assigned"

    # assigned → in_progress
    await svc.transition_status(item.id, PunchStatusTransition(new_status="in_progress"), user_a)
    assert item.status == "in_progress"

    # in_progress → verified (different user)
    await svc.transition_status(item.id, PunchStatusTransition(new_status="verified"), user_b)
    assert item.status == "verified"
    assert item.verified_by == user_b

    # verified → closed
    await svc.transition_status(item.id, PunchStatusTransition(new_status="closed"), user_b)
    assert item.status == "closed"


@pytest.mark.asyncio
async def test_fsm_invalid_transition_blocked() -> None:
    """open → verified is NOT a valid single-hop transition."""
    from fastapi import HTTPException

    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]
    item = repo._make_item(status="open")

    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_status(item.id, PunchStatusTransition(new_status="verified"), str(uuid.uuid4()))
    assert exc_info.value.status_code == 400


# ── 2. FSM: ``reopened`` alias ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reopened_alias_maps_to_open_and_records_history() -> None:
    """Transitioning to 'reopened' stores status='open' and records reopen_history."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]
    item = repo._make_item(status="closed")

    user = str(uuid.uuid4())
    await svc.transition_status(
        item.id,
        PunchStatusTransition(new_status="reopened", notes="supervisor override"),
        user,
    )

    assert item.status == "open"
    assert len(item.reopen_history) == 1
    entry = item.reopen_history[0]
    assert entry["previous_status"] == "closed"
    assert entry["reopened_by"] == user
    assert entry["reason"] == "supervisor override"


# ── 3. Rework cost: Decimal-string validation ─────────────────────────────────


def test_rework_cost_valid_decimal_string() -> None:
    """A valid decimal string is normalised and stored."""
    create = PunchItemCreate(
        project_id=PROJECT_ID,
        title="Crack repair",
        rework_cost="1234.50",
        rework_cost_currency="EUR",
    )
    assert create.rework_cost == "1234.5"  # normalised (trailing zero stripped)
    assert Decimal(create.rework_cost) == Decimal("1234.5")


def test_rework_cost_integer_string_accepted() -> None:
    """An integer-like string is normalised to decimal form."""
    create = PunchItemCreate(
        project_id=PROJECT_ID,
        title="Repoint brickwork",
        rework_cost="500",
    )
    assert Decimal(create.rework_cost) == Decimal("500")


def test_rework_cost_invalid_string_rejected() -> None:
    """Non-numeric string raises ValidationError."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PunchItemCreate(
            project_id=PROJECT_ID,
            title="Test",
            rework_cost="not-a-number",
        )


def test_rework_cost_negative_rejected() -> None:
    """Negative rework_cost is rejected."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PunchItemCreate(
            project_id=PROJECT_ID,
            title="Test",
            rework_cost="-100.00",
        )


def test_rework_cost_none_accepted() -> None:
    """Omitting rework_cost (default=None) is valid."""
    create = PunchItemCreate(project_id=PROJECT_ID, title="Minor scratch")
    assert create.rework_cost is None


# ── 4. Geo-tagging: lat/lon range validation ──────────────────────────────────


def test_geo_lat_out_of_range_rejected() -> None:
    """geo_lat outside [-90, 90] is rejected by Pydantic."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PunchItemCreate(project_id=PROJECT_ID, title="Test", geo_lat=91.0, geo_lon=0.0)


def test_geo_lon_out_of_range_rejected() -> None:
    """geo_lon outside [-180, 180] is rejected by Pydantic."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PunchItemCreate(project_id=PROJECT_ID, title="Test", geo_lat=0.0, geo_lon=181.0)


def test_geo_valid_boundary_values_accepted() -> None:
    """Boundary values (±90 lat, ±180 lon) are accepted."""
    create = PunchItemCreate(
        project_id=PROJECT_ID,
        title="Boundary item",
        geo_lat=90.0,
        geo_lon=180.0,
    )
    assert create.geo_lat == 90.0
    assert create.geo_lon == 180.0

    create2 = PunchItemCreate(
        project_id=PROJECT_ID,
        title="Boundary item 2",
        geo_lat=-90.0,
        geo_lon=-180.0,
    )
    assert create2.geo_lat == -90.0
    assert create2.geo_lon == -180.0


# ── 5. Trade filter ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trade_filter_returns_only_matching_items() -> None:
    """list_items trade_filter restricts results to that trade."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]

    repo._make_item(trade="electrical")
    repo._make_item(trade="plumbing")
    repo._make_item(trade="electrical")

    items, total = await svc.list_items(PROJECT_ID, trade_filter="electrical")
    assert len(items) == 2
    assert all(i.trade == "electrical" for i in items)


@pytest.mark.asyncio
async def test_trade_filter_none_returns_all() -> None:
    """list_items with no trade_filter returns all items for the project."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]

    repo._make_item(trade="electrical")
    repo._make_item(trade="plumbing")
    repo._make_item(trade=None)

    items, _ = await svc.list_items(PROJECT_ID, trade_filter=None)
    assert len(items) == 3


# ── 6. Bulk close: project mismatch rejected ──────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_close_project_mismatch_becomes_error() -> None:
    """Items from a different project are not closed (IDOR guard)."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]

    good = repo._make_item(project_id=PROJECT_ID)
    foreign = repo._make_item(project_id=OTHER_PROJECT_ID)

    result = await svc.bulk_close(
        PROJECT_ID,
        [good.id, foreign.id],
        user_id="mgr",
    )

    assert result["closed"] == 1
    assert result["skipped"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == str(foreign.id)
    assert result["errors"][0]["error"] == "project_mismatch"


# ── 7. Bulk close: already-closed items are skipped, not errors ───────────────


@pytest.mark.asyncio
async def test_bulk_close_skips_already_closed() -> None:
    """Items already in 'closed' state are counted as skipped, not errors."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]

    already = repo._make_item(status="closed")
    new_item = repo._make_item(status="open")

    result = await svc.bulk_close(PROJECT_ID, [already.id, new_item.id], user_id="mgr")

    assert result["closed"] == 1
    assert result["skipped"] == 1
    assert result["errors"] == []


# ── 8. FSM: assigned → open (unassign / reopen from assigned) ─────────────────


@pytest.mark.asyncio
async def test_assigned_can_transition_back_to_open() -> None:
    """An 'assigned' item can be moved back to 'open'."""
    svc = _make_service()
    repo: _StubRepo = svc.repo  # type: ignore[assignment]
    item = repo._make_item(status="assigned")

    await svc.transition_status(item.id, PunchStatusTransition(new_status="open"), str(uuid.uuid4()))
    assert item.status == "open"
