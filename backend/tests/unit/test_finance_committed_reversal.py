"""Max-Audit #10: ProjectBudget.committed must be idempotent and reversible.

`procurement.po.approved` commits a PO's amount against the project budget.
Two failure modes were confirmed by the audit:

  1. Re-firing ``po.approved`` for the same PO (e.g. an
     ``approved -> draft -> approved`` round-trip, or an event replay) added
     the amount a SECOND time, inflating ``committed``.
  2. A PO leaving ``approved`` (``approved -> cancelled`` or
     ``approved -> draft``) never decremented ``committed``, leaving a
     phantom commitment forever.

These tests pin the fix: approval stamps a ``committed_from_po:<po_id>``
marker so a replay is a no-op, and ``procurement.po.cancelled`` /
``procurement.po.reverted`` decrement exactly the marked amount.

The handlers open their own ``async_session_factory()`` session, so we drive
them with a DB-free fake session that serves a single seeded budget row and
records commits - mirroring the stub style of
``backend/tests/unit/test_procurement_events.py``.

The tests are written as files only; per the parallel-run rules they are not
executed here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event
from app.modules.finance import events as fin_events
from app.modules.finance.models import ProjectBudget

# ── Fake session over a single in-memory budget row ─────────────────────────


class _Result:
    """Minimal mimic of a SQLAlchemy ``Result``."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """Async-context-manager session that serves one ProjectBudget row.

    - ``select(ProjectBudget)...`` resolves to the seeded budget.
    - ``select(PurchaseOrderItem.wbs_id)...`` resolves to None (no wbs hint),
      so the handlers fall back to the "first budget for the project" rule and
      land on our seeded row.
    """

    def __init__(self, budget: SimpleNamespace) -> None:
        self.budget = budget
        self.commits = 0

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        entity = stmt.column_descriptions[0].get("entity")
        if entity is ProjectBudget:
            return _Result(self.budget)
        # PurchaseOrderItem.wbs_id lookup → no hint.
        return _Result(None)

    async def commit(self) -> None:
        self.commits += 1


def _make_budget(project_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        committed=Decimal("0"),
        actual=Decimal("0"),
        metadata_={},
    )


@pytest.fixture
def budget_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Wire the finance handlers to a single fake-session-backed budget."""
    project_id = uuid.uuid4()
    budget = _make_budget(project_id)
    session = _FakeSession(budget)

    monkeypatch.setattr(fin_events, "async_session_factory", lambda: session)
    return SimpleNamespace(project_id=project_id, budget=budget, session=session)


def _approved_event(project_id: uuid.UUID, po_id: uuid.UUID, amount: str) -> Event:
    return Event(
        name="procurement.po.approved",
        data={
            "po_id": str(po_id),
            "project_id": str(project_id),
            "po_number": "PO-001",
            "amount_total": amount,
            "currency_code": "EUR",
        },
        source_module="oe_procurement",
    )


def _decommit_event(name: str, project_id: uuid.UUID, po_id: uuid.UUID, amount: str) -> Event:
    return Event(
        name=name,
        data={
            "po_id": str(po_id),
            "project_id": str(project_id),
            "po_number": "PO-001",
            "amount_total": amount,
            "currency_code": "EUR",
        },
        source_module="oe_procurement",
    )


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_commits_once_and_stamps_marker(budget_env: SimpleNamespace) -> None:
    """A single approval adds the amount and records the per-PO marker."""
    po_id = uuid.uuid4()
    await fin_events._on_po_approved(_approved_event(budget_env.project_id, po_id, "1000.00"))

    assert budget_env.budget.committed == Decimal("1000.00")
    assert budget_env.budget.metadata_[f"committed_from_po:{po_id}"] == "1000.00"


@pytest.mark.asyncio
async def test_reapprove_replay_is_idempotent(budget_env: SimpleNamespace) -> None:
    """Re-firing po.approved for the same PO must NOT add committed twice.

    This is the inflation bug: before the fix the second event blindly did
    ``committed = current + amount`` and doubled the commitment.
    """
    po_id = uuid.uuid4()
    event = _approved_event(budget_env.project_id, po_id, "1000.00")

    await fin_events._on_po_approved(event)
    await fin_events._on_po_approved(event)  # replay / re-fire

    assert budget_env.budget.committed == Decimal("1000.00")  # NOT 2000


@pytest.mark.asyncio
async def test_cancel_decrements_committed(budget_env: SimpleNamespace) -> None:
    """approve → cancel must shed the committed amount, not leave it forever."""
    po_id = uuid.uuid4()
    await fin_events._on_po_approved(_approved_event(budget_env.project_id, po_id, "1000.00"))
    assert budget_env.budget.committed == Decimal("1000.00")

    await fin_events._on_po_decommitted(
        _decommit_event("procurement.po.cancelled", budget_env.project_id, po_id, "1000.00")
    )

    assert budget_env.budget.committed == Decimal("0")
    # Marker cleared so a re-approval can commit cleanly again.
    assert f"committed_from_po:{po_id}" not in budget_env.budget.metadata_


@pytest.mark.asyncio
async def test_approve_revert_reapprove_commits_once(budget_env: SimpleNamespace) -> None:
    """approve → revert → re-approve nets a SINGLE commitment.

    The full audit scenario: the FSM allows approved->draft->approved, and the
    re-approval re-publishes po.approved. With the reversal clearing the marker
    on revert, the re-approval commits exactly once more, ending at the single
    PO amount - never doubled, never zero.
    """
    po_id = uuid.uuid4()
    approved = _approved_event(budget_env.project_id, po_id, "1000.00")

    # approve
    await fin_events._on_po_approved(approved)
    assert budget_env.budget.committed == Decimal("1000.00")

    # revert to draft → decrement
    await fin_events._on_po_decommitted(
        _decommit_event("procurement.po.reverted", budget_env.project_id, po_id, "1000.00")
    )
    assert budget_env.budget.committed == Decimal("0")

    # re-approve → commits once more (marker was cleared on revert)
    await fin_events._on_po_approved(approved)
    assert budget_env.budget.committed == Decimal("1000.00")


@pytest.mark.asyncio
async def test_decommit_without_marker_is_noop(budget_env: SimpleNamespace) -> None:
    """A cancel for a PO that never committed must not drive committed negative."""
    po_id = uuid.uuid4()
    budget_env.budget.committed = Decimal("500.00")  # unrelated existing commitment

    await fin_events._on_po_decommitted(
        _decommit_event("procurement.po.cancelled", budget_env.project_id, po_id, "1000.00")
    )

    # Untouched: we only ever reverse a commitment we actually recorded.
    assert budget_env.budget.committed == Decimal("500.00")


@pytest.mark.asyncio
async def test_decommit_clamps_at_zero(budget_env: SimpleNamespace) -> None:
    """If a parallel write already drained committed, reversal floors at zero."""
    po_id = uuid.uuid4()
    await fin_events._on_po_approved(_approved_event(budget_env.project_id, po_id, "1000.00"))

    # Simulate gr.confirmed (or another write) having already reduced committed
    # below the marked amount.
    budget_env.budget.committed = Decimal("300.00")

    await fin_events._on_po_decommitted(
        _decommit_event("procurement.po.cancelled", budget_env.project_id, po_id, "1000.00")
    )

    assert budget_env.budget.committed == Decimal("0")  # clamped, not -700


@pytest.mark.asyncio
async def test_subscriptions_wire_decommit_events() -> None:
    """The new cancel/revert events must be wired into the finance bus."""
    names = {name for name, _ in fin_events._SUBSCRIPTIONS}
    assert "procurement.po.cancelled" in names
    assert "procurement.po.reverted" in names
    # Both route to the reversal handler.
    handlers = {name: handler for name, handler in fin_events._SUBSCRIPTIONS}
    assert handlers["procurement.po.cancelled"] is fin_events._on_po_decommitted
    assert handlers["procurement.po.reverted"] is fin_events._on_po_decommitted
