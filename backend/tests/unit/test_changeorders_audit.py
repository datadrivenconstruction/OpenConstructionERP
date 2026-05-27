"""Deep-audit unit tests for the ``changeorders`` module.

These tests target the second-pass audit fixes:

* Decimal-exact summary rollup (no float arithmetic on money).
* Atomic / collision-safe approval-chain start.
* Concurrent advance_approval guards (the "two approvers click at the
  same moment" hazard).
* ActivityLog write-through on every status transition.
* Service-level four-eyes guard for the approval-chain composition
  (a submitter cannot be inserted into their own chain).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.changeorders.repository import ChangeOrderRepository
from app.modules.changeorders.service import ChangeOrderService

# ── Shared stubs (mirrors test_changeorders_approval.py) ────────────────────


class _StubSession:
    """Minimal async session that records added rows.

    Behaviours covered:
    * ``execute(...)`` resolves the small set of selects this audit suite
      asks for. ``select(Project)`` returns the project stored under the
      WHERE-clause's UUID; everything else returns an empty result.
    * ``add(obj)`` appends to ``self.added`` and assigns ``id`` /
      ``created_at`` / ``updated_at`` so freshly-added rows look like
      persisted ORM objects.
    * ``flush`` / ``refresh`` / ``rollback`` are inert.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.projects: dict[uuid.UUID, SimpleNamespace] = {}
        self.repo: _StubRepo | None = None

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = now
        if not hasattr(obj, "updated_at") or obj.updated_at is None:
            obj.updated_at = now
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, stmt: Any) -> Any:
        sql = str(stmt).lower()

        class _Result:
            def __init__(self, value: Any) -> None:
                self._v = value

            def scalar_one_or_none(self) -> Any:
                return self._v

            def scalar_one(self) -> Any:
                return self._v if self._v is not None else 0

            def scalars(self) -> _Result:
                return self

            def all(self) -> list[Any]:
                return list(self._v) if isinstance(self._v, list) else []

        # Project lookup — both _resolve_currency and approve_order use it.
        if "oe_projects_project" in sql or "project " in sql:
            try:
                pid = stmt.whereclause.right.value  # type: ignore[attr-defined]
            except AttributeError:
                pid = None
            project = self.projects.get(pid) if pid else None
            return _Result(project)

        # Default: empty.
        return _Result(None)


class _StubRepo:
    """In-memory drop-in for :class:`ChangeOrderRepository`."""

    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, SimpleNamespace] = {}
        self.update_log: list[tuple[uuid.UUID, dict[str, Any]]] = []

    async def get_by_id(self, order_id: uuid.UUID) -> SimpleNamespace | None:
        return self.orders.get(order_id)

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        return sum(1 for o in self.orders.values() if o.project_id == project_id)

    async def create(self, order: SimpleNamespace) -> SimpleNamespace:
        if getattr(order, "id", None) is None:
            order.id = uuid.uuid4()
        now = datetime.now(UTC)
        order.created_at = now
        order.updated_at = now
        self.orders[order.id] = order
        return order

    async def update_fields(self, order_id: uuid.UUID, **fields: Any) -> None:
        self.update_log.append((order_id, dict(fields)))
        obj = self.orders.get(order_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)


def _make_service() -> tuple[ChangeOrderService, _StubSession, _StubRepo]:
    session = _StubSession()
    repo = _StubRepo()
    session.repo = repo
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
    currency: str = "EUR",
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
        currency=currency,
        metadata_={},
        linked_po_ids=[],
        linked_rfi_ids=[],
        current_approval_step=None,
        time_impact_days=None,
    )


# ── FIX 1: Decimal summary rollup ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_rollup_uses_decimal_not_float() -> None:
    """``ChangeOrderRepository.get_summary`` must roll up cost_impact in
    exact Decimal arithmetic — using ``float()`` on currency-typed sums
    leaks 0.1+0.2 == 0.30000000000000004 style errors into KPIs.
    """

    # Hand-build the repository with a stub session that returns three
    # approved orders whose decimal cost_impacts trip binary float.
    pid = uuid.uuid4()
    o1 = _make_order(project_id=pid, status="approved", cost_impact="0.10")
    o2 = _make_order(project_id=pid, status="approved", cost_impact="0.20")
    o3 = _make_order(project_id=pid, status="approved", cost_impact="100.05")

    class _OrdersSession(_StubSession):
        def __init__(self, orders: list[SimpleNamespace], project: SimpleNamespace) -> None:
            super().__init__()
            self._orders = orders
            self.projects[project.id] = project

        async def execute(self, stmt: Any) -> Any:
            sql = str(stmt).lower()

            class _Result:
                def __init__(self, value: Any) -> None:
                    self._v = value

                def scalar_one_or_none(self) -> Any:
                    return self._v

                def scalar_one(self) -> Any:
                    return self._v if self._v is not None else 0

                def scalars(self) -> _Result:
                    return self

                def all(self) -> list[Any]:
                    return list(self._v) if isinstance(self._v, list) else []

            # First call goes to ChangeOrder; second goes to Project.
            if "oe_changeorders_order" in sql:
                return _Result(self._orders)
            if "oe_projects_project" in sql:
                return _Result(next(iter(self.projects.values()), None))
            return _Result(None)

    project = SimpleNamespace(id=pid, currency="EUR")
    session = _OrdersSession([o1, o2, o3], project)
    repo = ChangeOrderRepository(session=session)  # type: ignore[arg-type]

    summary = await repo.get_summary(pid)

    # The result must equal exactly 100.35 — float arithmetic produces
    # 100.34999999999999 here.
    assert summary["total_approved_amount"] == Decimal("100.35")
    assert summary["total_cost_impact"] == Decimal("100.35")
    # Exposed as canonical decimal strings on the wire — schema validator
    # accepts both Decimal and str, but the repo must not lose precision.
    assert str(summary["total_cost_impact"]) == "100.35"


# ── FIX 2: Approval-chain start is atomic / collision-safe ───────────────────


@pytest.mark.asyncio
async def test_start_approval_chain_handles_concurrent_start_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent ``start_approval_chain`` calls must not both
    succeed. The second caller must see a clean 409, not a half-built
    chain or an unhandled IntegrityError.
    """
    from sqlalchemy.exc import IntegrityError

    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    repo.orders[order.id] = order

    # First call from inside _has_approval_chain returns 0 → chain looks
    # absent. Then the INSERT collides because another transaction
    # already wrote step 1. The service must convert that to 409.
    call_count = {"n": 0}

    async def _exec(stmt: Any) -> Any:
        call_count["n"] += 1
        sql = str(stmt).lower()

        class _R:
            def __init__(self, v: Any) -> None:
                self._v = v

            def scalar_one(self) -> Any:
                return self._v

            def scalar_one_or_none(self) -> Any:
                return self._v

            def scalars(self) -> _R:
                return self

            def all(self) -> list[Any]:
                return list(self._v) if isinstance(self._v, list) else []

        if "count(" in sql:
            return _R(0)
        return _R(None)

    monkeypatch.setattr(session, "execute", _exec)

    # The first session.flush call from inside start_approval_chain
    # carries the freshly-added approval rows; that's the moment the
    # unique index on (change_order_id, step_order) catches the
    # concurrent winner. Force the collision there.
    flush_calls = {"n": 0}

    async def _flush() -> None:
        flush_calls["n"] += 1
        raise IntegrityError("INSERT", {}, Exception("uq_oe_changeorder_approval_change_order_id_step_order"))

    monkeypatch.setattr(session, "flush", _flush)

    approvers = [uuid.uuid4(), uuid.uuid4()]
    with pytest.raises(HTTPException) as exc_info:
        await service.start_approval_chain(order.id, approvers)
    assert exc_info.value.status_code == 409
    assert "chain" in exc_info.value.detail.lower()


# ── FIX 3: Concurrent advance_approval is guarded ────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_advance_approval_uses_conditional_update() -> None:
    """If two approvers both call advance_approval on the same active
    step, the bare ``active_row.decision != 'pending'`` check is a
    TOCTOU window — both callers may read decision='pending' before
    either writes. The service must instead use a conditional UPDATE
    that only succeeds when ``decision='pending'`` AND
    ``step_order=cursor`` so exactly one caller wins; the loser sees
    a clean 409 without double-advancing the cursor.
    """

    pid = uuid.uuid4()
    approver_a = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    order.current_approval_step = 1

    shared_row = SimpleNamespace(
        id=uuid.uuid4(),
        change_order_id=order.id,
        step_order=1,
        approver_user_id=approver_a,
        decision="pending",  # row LOOKS pending to caller B at fetch time
        decided_at=None,
        comments=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    service, session, repo = _make_service()
    repo.orders[order.id] = order

    # Capture the conditional UPDATE statement — that's the contract we
    # require. The fix must issue an UPDATE … WHERE decision='pending'
    # so the DB enforces single-winner semantics; the seen-rowcount
    # check then maps 0 affected rows to 409 in the service.
    update_statements: list[str] = []
    cursor_writes: list[Any] = []

    async def _exec(stmt: Any) -> Any:
        sql = str(stmt).lower()

        class _R:
            def __init__(self, v: Any, rowcount: int = 0) -> None:
                self._v = v
                self.rowcount = rowcount

            def scalar_one(self) -> Any:
                return self._v

            def scalar_one_or_none(self) -> Any:
                return self._v

            def scalars(self) -> _R:
                return self

            def all(self) -> list[Any]:
                return list(self._v) if isinstance(self._v, list) else []

        if sql.startswith("update"):
            update_statements.append(sql)
            # Caller B's conditional UPDATE affects 0 rows because
            # caller A's UPDATE already flipped decision away from
            # 'pending'. Returning a result with rowcount=0 here is
            # the DB's "you lost the race" signal.
            return _R(None, rowcount=0)

        if "count(" in sql:
            return _R(1)
        if "step_order =" in sql or "step_order=" in sql:
            return _R(shared_row)
        return _R([shared_row])

    session.execute = _exec  # type: ignore[method-assign]

    # Patch repo.update_fields so we can prove the cursor was NOT
    # advanced when the race was lost.
    original_update_fields = repo.update_fields

    async def _track_update(order_id: uuid.UUID, **fields: Any) -> None:
        cursor_writes.append(fields)
        await original_update_fields(order_id, **fields)

    repo.update_fields = _track_update  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc_info:
        await service.advance_approval(order.id, str(approver_a), "approved")
    assert exc_info.value.status_code == 409
    # The service MUST have issued a conditional UPDATE … WHERE
    # decision = :pending — that's the DB-level guard that makes
    # concurrent approvers single-winner. The literal pending value is
    # bound as a parameter so the compiled SQL only shows ``decision =
    # :decision_1``; that's enough proof the WHERE clause filters on
    # the column (the alternative — bare python-side mutation — would
    # never issue an UPDATE statement against the table).
    assert any(
        "update" in s and "oe_changeorder_approval" in s and "decision =" in s.split("where", 1)[-1]
        for s in update_statements
    ), "advance_approval must use a conditional UPDATE … WHERE decision=:pending to be race-safe; got: " + repr(
        update_statements
    )
    # Cursor must not have moved.
    assert all(fields.get("current_approval_step") != 2 for fields in cursor_writes), (
        f"Cursor must NOT advance on lost race; got writes: {cursor_writes!r}"
    )
    assert order.current_approval_step == 1


# ── FIX 4: ActivityLog rows written on status transitions ────────────────────


@pytest.mark.asyncio
async def test_submit_writes_activity_log_row() -> None:
    """``submit_order`` must write an :class:`ActivityLog` row capturing
    actor + from_status + to_status so dispute timelines and ISO 9001
    traceability can be reproduced byte-for-byte.
    """
    from app.core.audit_log import ActivityLog

    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="draft")
    repo.orders[order.id] = order

    actor = str(uuid.uuid4())
    await service.submit_order(order.id, actor)

    audit_rows = [r for r in session.added if isinstance(r, ActivityLog)]
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.entity_type == "change_order"
    assert row.entity_id == str(order.id)
    assert row.action == "status_changed"
    assert row.from_status == "draft"
    assert row.to_status == "submitted"
    assert str(row.actor_id) == actor


@pytest.mark.asyncio
async def test_reject_writes_activity_log_row() -> None:
    """``reject_order`` must record the rejection with reason."""
    from app.core.audit_log import ActivityLog

    service, session, repo = _make_service()
    pid = uuid.uuid4()
    submitter = str(uuid.uuid4())
    rejector = str(uuid.uuid4())

    order = _make_order(project_id=pid, status="submitted", submitted_by=submitter)
    repo.orders[order.id] = order

    await service.reject_order(order.id, user_id=rejector)

    audit_rows = [r for r in session.added if isinstance(r, ActivityLog)]
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.action == "status_changed"
    assert row.from_status == "submitted"
    assert row.to_status == "rejected"
    assert str(row.actor_id) == rejector


# ── FIX 5: Service-level four-eyes for chain composition ─────────────────────


@pytest.mark.asyncio
async def test_start_approval_chain_rejects_submitter_in_chain() -> None:
    """The four-eyes principle (BUG-353) must extend to the multi-step
    chain. A scope author who submitted the CO cannot be a designated
    approver on its own chain — otherwise the spirit of four-eyes is
    bypassed (e.g. submitter as step 2 silently rubber-stamps).
    """
    service, _, repo = _make_service()
    pid = uuid.uuid4()
    submitter = uuid.uuid4()
    order = _make_order(
        project_id=pid,
        status="submitted",
        submitted_by=str(submitter),
    )
    repo.orders[order.id] = order

    other = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await service.start_approval_chain(order.id, [other, submitter, other])
    assert exc_info.value.status_code == 403
    assert "four-eyes" in exc_info.value.detail.lower()
