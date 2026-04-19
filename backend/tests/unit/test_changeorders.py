"""Unit tests for :class:`ChangeOrderService` + schemas.

Covers the bug fixes bundled in v1.9.7 Phase 1:

* BUG-351 — reject writes ``rejected_by`` / ``rejected_at``, not ``approved_*``
* BUG-352 — items frozen outside ``draft``
* BUG-353 — four-eyes: submitter cannot approve or reject their own CO
* BUG-354 — unique ``(project_id, code)`` + retry-on-integrity-error
* BUG-385 — ``cost_impact`` accepted on create; PATCH of ``status`` rejected
* BUG-120 / 376 — approved cost_impact propagates to ``project.budget_estimate``
* ENH-095 — approving an already-approved CO is a no-op

Repositories and the project model are stubbed so the suite runs without a DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.changeorders.schemas import (
    ChangeOrderCreate,
    ChangeOrderItemCreate,
    ChangeOrderUpdate,
)
from app.modules.changeorders.service import ChangeOrderService


# ── Schema tests (BUG-385) ──────────────────────────────────────────────────


def test_change_order_create_accepts_cost_impact() -> None:
    """BUG-385: ``cost_impact`` on POST must not be silently dropped."""
    payload = ChangeOrderCreate(
        project_id=uuid.uuid4(),
        title="Scope change",
        description="Add 2 extra floors",
        cost_impact="1250.50",
    )
    assert payload.cost_impact == "1250.50"


def test_change_order_create_without_cost_impact_defaults_none() -> None:
    payload = ChangeOrderCreate(project_id=uuid.uuid4(), title="Scope change")
    assert payload.cost_impact is None


def test_change_order_update_rejects_status_field() -> None:
    """BUG-385: PATCH with ``status`` must raise instead of being ignored."""
    with pytest.raises(ValidationError) as exc_info:
        ChangeOrderUpdate(status="approved")
    # Error message must steer the caller to the action endpoints.
    msg = str(exc_info.value)
    assert "submit" in msg.lower()
    assert "approve" in msg.lower()
    assert "reject" in msg.lower()


def test_change_order_update_accepts_cost_impact() -> None:
    payload = ChangeOrderUpdate(cost_impact="9999.00")
    assert payload.cost_impact == "9999.00"


def test_change_order_update_bare_payload_does_not_error() -> None:
    """A PATCH that does not touch status must not trip the status validator."""
    payload = ChangeOrderUpdate(title="Renamed CO")
    assert payload.title == "Renamed CO"
    assert payload.status is None


# ── Stubs ───────────────────────────────────────────────────────────────────


class _StubSession:
    """Minimal ``AsyncSession`` replacement for service unit tests."""

    def __init__(self) -> None:
        self.projects: dict[uuid.UUID, SimpleNamespace] = {}
        self.flushed = False

    async def refresh(self, obj: Any) -> None:
        pass

    async def flush(self) -> None:
        self.flushed = True

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        """Satisfy ``select(Project).where(...)`` from :meth:`approve_order`."""
        try:
            project_id = stmt.whereclause.right.value  # type: ignore[attr-defined]
        except AttributeError:
            project_id = None
        project = self.projects.get(project_id) if project_id else None

        class _Result:
            def __init__(self, value: Any) -> None:
                self._value = value

            def scalar_one_or_none(self) -> Any:
                return self._value

        return _Result(project)


class _StubRepo:
    """In-memory ``ChangeOrderRepository`` drop-in."""

    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, SimpleNamespace] = {}
        self.items: dict[uuid.UUID, SimpleNamespace] = {}
        self.integrity_strikes = 0
        self._counter = 0

    async def get_by_id(self, order_id: uuid.UUID) -> SimpleNamespace | None:
        return self.orders.get(order_id)

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        return sum(1 for o in self.orders.values() if o.project_id == project_id)

    async def create(self, order: SimpleNamespace) -> SimpleNamespace:
        # Simulate a unique-constraint violation for the first N attempts.
        if self.integrity_strikes > 0:
            self.integrity_strikes -= 1
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("INSERT", {}, Exception("uq_changeorders_project_code"))

        if getattr(order, "id", None) is None:
            order.id = uuid.uuid4()
        now = datetime.now(UTC)
        order.created_at = now
        order.updated_at = now
        self.orders[order.id] = order
        return order

    async def update_fields(self, order_id: uuid.UUID, **fields: Any) -> None:
        obj = self.orders.get(order_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)


def _make_service() -> tuple[ChangeOrderService, _StubSession, _StubRepo]:
    session = _StubSession()
    repo = _StubRepo()
    service = ChangeOrderService.__new__(ChangeOrderService)
    service.session = session  # type: ignore[attr-defined]
    service.repo = repo  # type: ignore[attr-defined]
    return service, session, repo


def _make_order(
    *,
    project_id: uuid.UUID,
    status: str = "draft",
    submitted_by: str | None = None,
    cost_impact: str = "0",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        code="CO-001",
        title="t",
        description="",
        reason_category="client_request",
        status=status,
        submitted_by=submitted_by,
        approved_by=None,
        rejected_by=None,
        submitted_at=None,
        approved_at=None,
        rejected_at=None,
        cost_impact=cost_impact,
        schedule_impact_days=0,
        currency="EUR",
        metadata_={},
    )


# ── BUG-354: unique code generation retries ─────────────────────────────────


@pytest.mark.asyncio
async def test_create_order_retries_on_integrity_error() -> None:
    """First two inserts collide; third must succeed with bumped ordinal."""
    service, _, repo = _make_service()
    repo.integrity_strikes = 2  # first two attempts raise IntegrityError

    data = ChangeOrderCreate(project_id=uuid.uuid4(), title="Contingency")
    order = await service.create_order(data)

    assert order.code == "CO-003"  # count=0, attempts 0,1,2 → ordinal 3


@pytest.mark.asyncio
async def test_create_order_gives_up_after_max_retries() -> None:
    service, _, repo = _make_service()
    repo.integrity_strikes = 99  # always collide

    data = ChangeOrderCreate(project_id=uuid.uuid4(), title="Doomed")
    with pytest.raises(HTTPException) as exc_info:
        await service.create_order(data)
    assert exc_info.value.status_code == 503
    assert "unique" in exc_info.value.detail.lower()


# ── BUG-351: reject writes rejected_by / rejected_at ─────────────────────────


@pytest.mark.asyncio
async def test_reject_order_populates_rejected_fields() -> None:
    service, _, repo = _make_service()
    pid = uuid.uuid4()
    submitter = str(uuid.uuid4())
    rejector = str(uuid.uuid4())

    order = _make_order(project_id=pid, status="submitted", submitted_by=submitter)
    repo.orders[order.id] = order

    result = await service.reject_order(order.id, user_id=rejector)

    assert result.status == "rejected"
    assert result.rejected_by == rejector
    assert result.rejected_at is not None
    # approved_by must stay untouched — this was the whole point of BUG-351.
    assert result.approved_by is None


# ── BUG-353: four-eyes principle ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submitter_cannot_approve_their_own_order() -> None:
    service, _, repo = _make_service()
    pid = uuid.uuid4()
    submitter = str(uuid.uuid4())

    order = _make_order(project_id=pid, status="submitted", submitted_by=submitter)
    repo.orders[order.id] = order

    with pytest.raises(HTTPException) as exc_info:
        await service.approve_order(order.id, user_id=submitter)
    assert exc_info.value.status_code == 403
    assert "four-eyes" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_submitter_cannot_reject_their_own_order() -> None:
    service, _, repo = _make_service()
    pid = uuid.uuid4()
    submitter = str(uuid.uuid4())

    order = _make_order(project_id=pid, status="submitted", submitted_by=submitter)
    repo.orders[order.id] = order

    with pytest.raises(HTTPException) as exc_info:
        await service.reject_order(order.id, user_id=submitter)
    assert exc_info.value.status_code == 403


# ── BUG-352: items frozen outside draft ─────────────────────────────────────


@pytest.mark.asyncio
async def test_add_item_blocked_when_submitted() -> None:
    service, _, repo = _make_service()
    order = _make_order(project_id=uuid.uuid4(), status="submitted")
    repo.orders[order.id] = order

    data = ChangeOrderItemCreate(description="extra rebar", unit="kg")
    with pytest.raises(HTTPException) as exc_info:
        await service.add_item(order.id, data)
    assert exc_info.value.status_code == 400
    assert "draft" in exc_info.value.detail.lower()


# ── BUG-120 / 376: approve propagates cost_impact to project budget ─────────


@pytest.mark.asyncio
async def test_approve_propagates_cost_impact_to_project_budget() -> None:
    service, session, repo = _make_service()
    pid = uuid.uuid4()
    submitter = str(uuid.uuid4())
    approver = str(uuid.uuid4())

    project = SimpleNamespace(id=pid, budget_estimate="100000.00")
    session.projects[pid] = project

    order = _make_order(
        project_id=pid,
        status="submitted",
        submitted_by=submitter,
        cost_impact="2500.75",
    )
    repo.orders[order.id] = order

    await service.approve_order(order.id, user_id=approver)

    # 100000.00 + 2500.75 = 102500.75
    assert project.budget_estimate == "102500.75"


@pytest.mark.asyncio
async def test_approve_is_idempotent() -> None:
    """ENH-095: re-approving an already-approved CO is a no-op, not a 400."""
    service, session, repo = _make_service()
    pid = uuid.uuid4()

    project = SimpleNamespace(id=pid, budget_estimate="50000")
    session.projects[pid] = project

    order = _make_order(
        project_id=pid,
        status="approved",
        submitted_by=str(uuid.uuid4()),
        cost_impact="500",
    )
    order.approved_by = str(uuid.uuid4())
    repo.orders[order.id] = order

    result = await service.approve_order(order.id, user_id=str(uuid.uuid4()))
    assert result.status == "approved"
    # No second writeback.
    assert project.budget_estimate == "50000"
