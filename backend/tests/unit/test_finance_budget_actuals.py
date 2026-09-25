# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - which budget line a paid supplier invoice lands on.

``plan_actuals`` is pure; every rule in ``finance.budget_actuals`` is pinned
here. The one that matters most: N budget lines keep their own actual, a paid
amount is never written onto all of them. The end-to-end run is
``test_budget_lines_keep_their_own_actual_and_commitment`` in
``tests/integration/test_finance_project_cost_position.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.finance.budget_actuals import (
    BudgetLineRow,
    PaidInvoice,
    PaidLine,
    pick_line,
    plan_actuals,
)

D = Decimal


def _row(wbs: str | None, category: str | None = None, currency: str = "EUR") -> BudgetLineRow:
    return BudgetLineRow(id=uuid.uuid4(), wbs_id=wbs, category=category, currency=currency)


def _inv(*lines: tuple[str | None, str], po: uuid.UUID | None = None, currency: str = "EUR") -> PaidInvoice:
    return PaidInvoice(currency=currency, po_id=po, lines=[PaidLine(w, None, D(a)) for w, a in lines])


def test_n_budget_lines_keep_their_own_actual() -> None:
    earth, concrete, finishes = _row("01"), _row("02"), _row("03")
    plan = plan_actuals(
        [earth, concrete, finishes],
        [_inv(("01", "1000"), ("02", "3000")), _inv(("02", "500"))],
        received_by_po={},
        committed_by_po={},
    )
    assert plan.actual == {earth.id: D("1000"), concrete.id: D("3500")}
    assert finishes.id not in plan.actual


def test_an_amount_without_a_matching_line_lands_on_one_line_only() -> None:
    first, second = _row("01"), _row("02")
    plan = plan_actuals([first, second], [_inv((None, "700"))], received_by_po={}, committed_by_po={})
    assert sum(plan.actual.values()) == D("700")
    assert len(plan.actual) == 1


def test_the_project_level_line_takes_what_has_no_wbs() -> None:
    wbs_line, project_line = _row("01"), _row(None)
    assert pick_line([wbs_line, project_line], None, None, "EUR") == project_line.id


def test_an_amount_never_lands_on_a_line_in_another_currency() -> None:
    usd = _row("01", currency="USD")
    plan = plan_actuals([usd], [_inv(("01", "100"))], received_by_po={}, committed_by_po={})
    assert plan.actual == {}
    assert plan.unplaced == {"EUR": D("100")}


def test_an_order_paid_after_receipt_is_spent_once() -> None:
    line = _row("02")
    po = uuid.uuid4()
    plan = plan_actuals(
        [line],
        [_inv(("02", "40000"), po=po)],
        received_by_po={po: D("40000")},
        committed_by_po={po: (line.id, D("50000"))},
    )
    # The receipt already moved the 40 000 into actual.
    assert plan.actual == {}
    assert plan.released == {}


def test_an_order_paid_without_receipt_moves_from_committed_to_actual() -> None:
    line = _row("02")
    po = uuid.uuid4()
    plan = plan_actuals(
        [line],
        [_inv(("02", "30000"), po=po)],
        received_by_po={},
        committed_by_po={po: (line.id, D("50000"))},
    )
    assert plan.actual == {line.id: D("30000")}
    assert plan.released == {line.id: {po: D("30000")}}


def test_payment_beyond_the_order_releases_no_more_than_it_committed() -> None:
    line = _row("02")
    po = uuid.uuid4()
    plan = plan_actuals(
        [line],
        [_inv(("02", "55000"), po=po)],
        received_by_po={po: D("20000")},
        committed_by_po={po: (line.id, D("50000"))},
    )
    assert plan.actual == {line.id: D("35000")}
    assert plan.released == {line.id: {po: D("30000")}}

