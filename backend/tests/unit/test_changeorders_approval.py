"""Unit tests for the Procore-style multi-step approval chain (T3).

Covers:

* ``start_approval_chain`` creates N rows + arms the cursor on step 1.
* Sequential approvals advance the cursor; final approval flips the CO
  to ``approved`` and triggers the legacy side-effects.
* Wrong user at the active step ⇒ 403.
* Reject mid-chain flips the CO to ``rejected`` and clears the cursor;
  downstream pending steps stay pending (audit trail).
* Legacy ``approve_order`` keeps working when no chain rows exist.
* Legacy ``approve_order`` returns 409 when a chain *is* present.

The repository, session, and downstream side-effect methods are stubbed
so the test runs without a real DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.changeorders.service import ChangeOrderService

# ── Stubs ───────────────────────────────────────────────────────────────────


class _StubSession:
    """Minimal async-session replacement for the chain tests.

    Holds an in-memory store of ``ChangeOrderApproval``-shaped namespaces.
    Recognises three SQL statement shapes the chain code uses:

    * ``select(func.count()).select_from(select(ChangeOrderApproval)…)``
      — returns the number of approval rows for the CO.
    * ``select(ChangeOrderApproval).where(change_order_id == X, step_order == N)``
      — returns the row at the *active cursor* (read from the test-side
      ``active_step`` field). The real query's literal step value can't
      be cheaply extracted from the SQL string at runtime, so the stub
      relies on the caller pointing it at the row it expects via
      ``session.active_step = N`` before each ``advance_approval`` call.
    * ``select(ChangeOrderApproval).where(change_order_id == X)``
      — returns every row for the CO (ordered by step_order).
    """

    def __init__(self) -> None:
        self.approvals: list[SimpleNamespace] = []
        self.added: list[Any] = []
        self.published: list[tuple[str, dict]] = []
        # Repo back-pointer set by ``_make_service``. The step-lookup
        # branch reads the CO's ``current_approval_step`` from here so
        # the stub always returns the *currently active* approval row,
        # without needing to parse SQL bind parameters out of the stmt.
        self.repo: _StubRepo | None = None

    async def refresh(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    def add(self, obj: Any) -> None:
        # Mimic SQLAlchemy `session.add` — the chain code adds approval
        # rows that don't yet have an id; populate one so the row
        # behaves like a persisted object.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = now
        if not hasattr(obj, "updated_at") or obj.updated_at is None:
            obj.updated_at = now
        self.added.append(obj)
        self.approvals.append(obj)

    async def execute(self, stmt: Any) -> Any:
        """Resolve the small set of SQL shapes the chain uses."""
        sql = str(stmt).lower()

        class _ScalarOneOrNone:
            def __init__(self, value: Any) -> None:
                self._v = value

            def scalar_one_or_none(self) -> Any:
                return self._v

            def scalar_one(self) -> Any:
                return self._v

            def scalars(self) -> _ScalarOneOrNone:
                return self

            def all(self) -> list[Any]:
                return list(self._v) if isinstance(self._v, list) else []

        # COUNT(*) probe — used by _has_approval_chain.
        if "count(" in sql:
            # Whichever CO was being filtered, the stub stores all rows
            # for one CO at a time; this is good enough for unit tests.
            return _ScalarOneOrNone(len(self.approvals))

        # Specific-step lookup vs all-rows-for-CO. Both share the same
        # SELECT clause so we can't disambiguate on column names; the
        # WHERE-on-step shape always has the bind expression
        # ``step_order = :step_order_1`` in the compiled SQL, while the
        # all-rows shape filters only on ``change_order_id``.
        if "step_order =" in sql or "step_order=" in sql:
            cursor: int | None = None
            if self.repo is not None and self.repo.orders:
                # Single-CO test setup — just look at the only order.
                only_order = next(iter(self.repo.orders.values()))
                cursor = getattr(only_order, "current_approval_step", None)
            if cursor is None:
                return _ScalarOneOrNone(None)
            for row in self.approvals:
                if row.step_order == cursor:
                    return _ScalarOneOrNone(row)
            return _ScalarOneOrNone(None)

        # Otherwise: list all approvals for the CO.
        rows = sorted(self.approvals, key=lambda r: r.step_order)
        return _ScalarOneOrNone(rows)


class _StubRepo:
    """In-memory drop-in for ``ChangeOrderRepository`` (chain-only fields)."""

    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, SimpleNamespace] = {}

    async def get_by_id(self, order_id: uuid.UUID) -> SimpleNamespace | None:
        return self.orders.get(order_id)

    async def update_fields(self, order_id: uuid.UUID, **fields: Any) -> None:
        obj = self.orders.get(order_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)


def _make_service() -> tuple[ChangeOrderService, _StubSession, _StubRepo]:
    session = _StubSession()
    repo = _StubRepo()
    session.repo = repo  # back-pointer for the step-lookup stub branch
    service = ChangeOrderService.__new__(ChangeOrderService)
    service.session = session  # type: ignore[attr-defined]
    service.repo = repo  # type: ignore[attr-defined]
    return service, session, repo


def _make_order(
    *,
    project_id: uuid.UUID,
    status: str = "submitted",
    submitted_by: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        code="CO-001",
        title="Approval chain test",
        description="",
        reason_category="client_request",
        status=status,
        submitted_by=submitted_by,
        approved_by=None,
        rejected_by=None,
        submitted_at=None,
        approved_at=None,
        rejected_at=None,
        cost_impact="0",
        schedule_impact_days=0,
        currency="EUR",
        metadata_={},
        linked_po_ids=[],
        linked_rfi_ids=[],
        current_approval_step=None,
    )


def _approver_chain_for(
    session: _StubSession,
    order_id: uuid.UUID,
    approver_ids: list[uuid.UUID],
) -> None:
    """Pre-seed approval rows so the lookup-by-step stub finds them."""
    for step, aid in enumerate(approver_ids, start=1):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            change_order_id=order_id,
            step_order=step,
            approver_user_id=aid,
            decision="pending",
            decided_at=None,
            comments=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.approvals.append(row)


# ── start_approval_chain ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_approval_chain_creates_rows_and_arms_cursor() -> None:
    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    repo.orders[order.id] = order

    approvers = [uuid.uuid4() for _ in range(3)]
    rows = await service.start_approval_chain(order.id, approvers)

    assert len(rows) == 3
    assert [r.step_order for r in rows] == [1, 2, 3]
    assert [r.approver_user_id for r in rows] == approvers
    assert all(r.decision == "pending" for r in rows)
    assert order.current_approval_step == 1


@pytest.mark.asyncio
async def test_start_approval_chain_rejects_empty_list() -> None:
    service, _, repo = _make_service()
    order = _make_order(project_id=uuid.uuid4(), status="submitted")
    repo.orders[order.id] = order

    with pytest.raises(HTTPException) as exc_info:
        await service.start_approval_chain(order.id, [])
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_start_approval_chain_rejects_non_submitted_co() -> None:
    service, _, repo = _make_service()
    order = _make_order(project_id=uuid.uuid4(), status="draft")
    repo.orders[order.id] = order

    with pytest.raises(HTTPException) as exc_info:
        await service.start_approval_chain(order.id, [uuid.uuid4()])
    assert exc_info.value.status_code == 400
    assert "submitted" in exc_info.value.detail.lower()


# ── advance_approval — sequential 3-step approval ───────────────────────────


@pytest.mark.asyncio
async def test_three_step_chain_approves_advances_then_finalises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    order.current_approval_step = 1
    repo.orders[order.id] = order

    approvers = [uuid.uuid4() for _ in range(3)]
    _approver_chain_for(session, order.id, approvers)

    # Patch out the legacy final-step side-effects so we don't need a
    # real DB for ``approve_order``. We only care that the chain reaches
    # the final step and the CO ends up status='approved'.
    final_calls: list[tuple[uuid.UUID, str]] = []

    async def _fake_approve_order(
        oid: uuid.UUID,
        uid: str,
        *,
        boq_id: Any = None,
        _from_chain: bool = False,
    ) -> SimpleNamespace:
        final_calls.append((oid, uid))
        assert _from_chain is True  # chain must use the escape hatch
        order.status = "approved"
        order.approved_by = uid
        order.approved_at = datetime.now(UTC).isoformat()[:19]
        return order

    monkeypatch.setattr(service, "approve_order", _fake_approve_order)

    # Step 1: first approver approves.
    row1 = await service.advance_approval(order.id, str(approvers[0]), "approved", comments="ok")
    assert row1.decision == "approved"
    assert order.current_approval_step == 2
    assert order.status == "submitted"

    # Step 2: second approver approves.
    row2 = await service.advance_approval(order.id, str(approvers[1]), "approved", comments="also ok")
    assert row2.decision == "approved"
    assert order.current_approval_step == 3
    assert order.status == "submitted"

    # Step 3: final approver approves → chain complete.
    row3 = await service.advance_approval(order.id, str(approvers[2]), "approved", comments="ship it")
    assert row3.decision == "approved"
    assert order.status == "approved"
    assert len(final_calls) == 1


# ── advance_approval — wrong user is forbidden ──────────────────────────────


@pytest.mark.asyncio
async def test_wrong_user_at_active_step_is_forbidden() -> None:
    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    order.current_approval_step = 1
    repo.orders[order.id] = order

    approvers = [uuid.uuid4(), uuid.uuid4()]
    _approver_chain_for(session, order.id, approvers)

    # An entirely unrelated user tries to advance step 1.
    intruder = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        await service.advance_approval(order.id, intruder, "approved")
    assert exc_info.value.status_code == 403
    # The cursor is unchanged.
    assert order.current_approval_step == 1
    # And step 1 is still pending.
    step_1 = next(r for r in session.approvals if r.step_order == 1)
    assert step_1.decision == "pending"


# ── advance_approval — reject mid-chain kills the chain ─────────────────────


@pytest.mark.asyncio
async def test_reject_at_step_2_short_circuits_chain() -> None:
    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    order.current_approval_step = 2  # mid-chain
    repo.orders[order.id] = order

    approvers = [uuid.uuid4() for _ in range(3)]
    _approver_chain_for(session, order.id, approvers)
    # Mark step 1 as already approved (we're testing rejection at 2).
    step_1 = next(r for r in session.approvals if r.step_order == 1)
    step_1.decision = "approved"
    step_1.decided_at = datetime.now(UTC)

    row = await service.advance_approval(order.id, str(approvers[1]), "rejected", comments="scope creep")
    assert row.decision == "rejected"
    assert order.status == "rejected"
    assert order.current_approval_step is None

    # Downstream step 3 stays pending — the audit trail must show it
    # never had a chance to act.
    step_3 = next(r for r in session.approvals if r.step_order == 3)
    assert step_3.decision == "pending"


# ── Legacy approve_order — forward-compat shim behaviour ───────────────────


@pytest.mark.asyncio
async def test_legacy_approve_order_works_when_no_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CO with no approval rows must still flow through the legacy path."""
    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    repo.orders[order.id] = order
    # session.approvals is empty → _has_approval_chain returns False.

    # Stub the budget/BOQ side-effects so we don't need a real DB.
    async def _noop_apply(_o: Any, *, boq_id: Any = None) -> dict:
        return {"applied": False, "reason": "stub"}

    async def _noop_writeback(**_kw: Any) -> dict:
        return {"action": "skipped", "budget_id": None}

    async def _noop_assert(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(service, "_apply_to_boq", _noop_apply)
    monkeypatch.setattr(service, "_write_budget_delta_row", _noop_writeback)
    monkeypatch.setattr(service, "_assert_not_self_approval", _noop_assert)

    user_id = str(uuid.uuid4())
    result = await service.approve_order(order.id, user_id)
    assert result.status == "approved"
    assert result.approved_by == user_id


@pytest.mark.asyncio
async def test_legacy_approve_order_blocked_when_chain_present() -> None:
    """A CO with rows in its chain rejects the legacy single-step call."""
    service, session, repo = _make_service()
    pid = uuid.uuid4()
    order = _make_order(project_id=pid, status="submitted")
    order.current_approval_step = 1
    repo.orders[order.id] = order

    # Seed a chain so _has_approval_chain returns True.
    _approver_chain_for(session, order.id, [uuid.uuid4(), uuid.uuid4()])

    with pytest.raises(HTTPException) as exc_info:
        await service.approve_order(order.id, str(uuid.uuid4()))
    assert exc_info.value.status_code == 409
    assert "advance-approval" in exc_info.value.detail
