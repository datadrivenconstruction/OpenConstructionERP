"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Max-Audit #10: ProjectBudget.committed must be idempotent and reversible.

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

import logging
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


# ── Goods receipts: the third writer of this field ──────────────────────────
#
# ``_on_gr_confirmed`` sat between the two handlers above with no idempotency
# key of any kind, while both of its siblings on ``committed`` were keyed on a
# ``committed_from_po:<po_id>`` marker. It makes three writes per delivery -
# ``committed -=``, ``actual +=`` and ``actual_from_receipts +=`` - so a replay
# double-counted all three. The deduction is clamped at zero, so the visible
# symptom was a commitment quietly too low, with nothing recording why.


def _gr_event(project_id: uuid.UUID, gr_id: uuid.UUID, po_id: uuid.UUID, amount: str) -> Event:
    return Event(
        name="procurement.gr.confirmed",
        data={
            "gr_id": str(gr_id),
            "po_id": str(po_id),
            "project_id": str(project_id),
            "amount": amount,
            "currency_code": "EUR",
        },
        source_module="oe_procurement",
    )


@pytest.mark.asyncio
async def test_gr_confirmed_posts_once_and_stamps_marker(budget_env: SimpleNamespace) -> None:
    """A confirmed receipt flips its amount from committed to actual, and says so."""
    po_id, gr_id = uuid.uuid4(), uuid.uuid4()
    await fin_events._on_po_approved(_approved_event(budget_env.project_id, po_id, "1000.00"))

    await fin_events._on_gr_confirmed(_gr_event(budget_env.project_id, gr_id, po_id, "400.00"))

    assert budget_env.budget.committed == Decimal("600.00")
    assert budget_env.budget.actual == Decimal("400.00")
    assert budget_env.budget.metadata_["actual_from_receipts"] == "400.00"
    assert budget_env.budget.metadata_[f"received_from_gr:{gr_id}"] == "400.00"


@pytest.mark.asyncio
async def test_gr_confirmed_replay_lands_all_three_writes_once(budget_env: SimpleNamespace) -> None:
    """Delivering the same receipt twice must move the money once.

    All three writes are asserted, not just the money: a guard that covered
    the total but not the metadata would leave ``actual_from_receipts``
    overstated, and that value is what the invoice-payment recompute adds
    back, so the error would resurface as inflated actuals later.
    """
    po_id, gr_id = uuid.uuid4(), uuid.uuid4()
    await fin_events._on_po_approved(_approved_event(budget_env.project_id, po_id, "1000.00"))
    event = _gr_event(budget_env.project_id, gr_id, po_id, "400.00")

    await fin_events._on_gr_confirmed(event)
    await fin_events._on_gr_confirmed(event)  # replay / redelivery

    assert budget_env.budget.committed == Decimal("600.00")  # NOT 200
    assert budget_env.budget.actual == Decimal("400.00")  # NOT 800
    assert budget_env.budget.metadata_["actual_from_receipts"] == "400.00"  # NOT 800.00


@pytest.mark.asyncio
async def test_two_different_receipts_both_land(budget_env: SimpleNamespace) -> None:
    """The negative control: keying on the receipt must not merge distinct receipts.

    A guard that deduplicated on the purchase order, or on "this budget has
    already taken a receipt", would silently drop the second delivery here and
    leave the commitment too high and the actual too low.
    """
    po_id = uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    await fin_events._on_po_approved(_approved_event(budget_env.project_id, po_id, "1000.00"))

    await fin_events._on_gr_confirmed(_gr_event(budget_env.project_id, first, po_id, "400.00"))
    await fin_events._on_gr_confirmed(_gr_event(budget_env.project_id, second, po_id, "250.00"))

    assert budget_env.budget.committed == Decimal("350.00")
    assert budget_env.budget.actual == Decimal("650.00")
    assert budget_env.budget.metadata_["actual_from_receipts"] == "650.00"
    assert budget_env.budget.metadata_[f"received_from_gr:{first}"] == "400.00"
    assert budget_env.budget.metadata_[f"received_from_gr:{second}"] == "250.00"


@pytest.mark.asyncio
async def test_gr_without_a_usable_id_does_not_post_silently(
    budget_env: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unkeyed posting cannot be deduplicated, so it is refused - and logged.

    Refusing is the safe half of the choice, but it declines to record real
    money, so the warning is the part that matters and is asserted here. A
    silent return would turn one failure mode into a quieter one.
    """
    po_id = uuid.uuid4()
    await fin_events._on_po_approved(_approved_event(budget_env.project_id, po_id, "1000.00"))
    bad = _gr_event(budget_env.project_id, uuid.uuid4(), po_id, "400.00")
    bad.data["gr_id"] = "not-a-uuid"

    with caplog.at_level(logging.WARNING, logger=fin_events.__name__):
        await fin_events._on_gr_confirmed(bad)

    assert budget_env.budget.committed == Decimal("1000.00")
    assert budget_env.budget.actual == Decimal("0")
    assert "no usable gr_id" in caplog.text


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
