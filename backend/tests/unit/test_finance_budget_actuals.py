# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - which budget line each source's committed and actual lands on.

``plan_budget`` is pure; every rule in ``finance.budget_actuals`` is pinned
here. The one that matters most: N budget lines keep their own figures, an
amount is never written onto all of them. The end-to-end runs are in
``tests/integration/test_finance_project_cost_position.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.finance.budget_actuals import (
    BudgetLineRow,
    parse_sync_marker,
    pick_line,
    plan_budget,
)
from app.modules.finance.cost_position import SourceFigure

D = Decimal


def _row(wbs: str | None, category: str | None = None, currency: str = "EUR") -> BudgetLineRow:
    return BudgetLineRow(id=uuid.uuid4(), wbs_id=wbs, category=category, currency=currency)


def _src(
    kind: str,
    wbs: str | None,
    committed: str,
    actual: str,
    *,
    ref: uuid.UUID | None = None,
    category: str | None = None,
    currency: str = "EUR",
) -> SourceFigure:
    return SourceFigure(kind, ref or uuid.uuid4(), currency, wbs, category, D(committed), D(actual))


def _plan(rows: list[BudgetLineRow], sources: list[SourceFigure], **kw: object):
    return plan_budget(rows, sources, order_rows=kw.get("order_rows", {}), order_handled=kw.get("order_handled", {}))


def test_n_budget_lines_keep_their_own_figures() -> None:
    earth, concrete, finishes = _row("01"), _row("02"), _row("03")
    inv = uuid.uuid4()
    plan = _plan(
        [earth, concrete, finishes],
        [_src("invoice", "01", "0", "1000", ref=inv), _src("invoice", "02", "0", "3000", ref=inv)],
    )
    assert plan.per_row == {
        earth.id: {f"invoice:{inv}": (D("0"), D("1000"))},
        concrete.id: {f"invoice:{inv}": (D("0"), D("3000"))},
    }
    assert finishes.id not in plan.per_row


def test_an_amount_without_a_matching_line_lands_on_one_line_only() -> None:
    first, second = _row("01"), _row("02")
    plan = _plan([first, second], [_src("invoice", None, "0", "700")])
    assert len(plan.per_row) == 1
    (figures,) = plan.per_row.values()
    assert sum(a for _, a in figures.values()) == D("700")


def test_the_project_level_line_takes_what_has_no_wbs() -> None:
    wbs_line, project_line = _row("01"), _row(None)
    assert pick_line([wbs_line, project_line], None, None, "EUR") == project_line.id


def test_a_line_of_the_same_wbs_wins_over_the_project_level_line() -> None:
    # A seeded line is keyed (wbs, "estimate"); an order booked to that WBS
    # carries no category and belongs on it, not on the catch-all.
    project_line, concrete = _row(None), _row("02", "estimate")
    assert pick_line([project_line, concrete], "02", None, "EUR") == concrete.id


def test_a_subcontract_lands_on_the_project_line_when_no_subcontract_line_exists() -> None:
    concrete, project_line = _row("02", "estimate"), _row(None)
    assert pick_line([concrete, project_line], None, "subcontractor", "EUR") == project_line.id


def test_a_figure_never_lands_on_a_line_in_another_currency() -> None:
    usd = _row("01", currency="USD")
    plan = _plan([usd], [_src("invoice", "01", "40", "100")])
    assert plan.per_row == {}
    assert plan.unplaced == {"EUR": (D("40"), D("100"))}


def test_an_order_adds_only_what_its_markers_did_not_put_there_on_their_row() -> None:
    project_line, concrete = _row(None), _row("02")
    po = uuid.uuid4()
    # Committed 50 000, received 40 000 and paid 55 000: open 0, incurred 55 000.
    # The markers put committed 10 000 and actual 40 000 on the concrete line.
    plan = _plan(
        [project_line, concrete],
        [_src("po", None, "0", "55000", ref=po)],
        order_rows={po: concrete.id},
        order_handled={po: (D("10000"), D("40000"))},
    )
    assert plan.per_row == {concrete.id: {f"po:{po}": (D("-10000"), D("15000"))}}


def test_an_order_approved_before_its_budget_line_is_placed_in_full() -> None:
    concrete = _row("02")
    po = uuid.uuid4()
    plan = _plan([concrete], [_src("po", "02", "50000", "0", ref=po)])
    assert plan.per_row == {concrete.id: {f"po:{po}": (D("50000"), D("0"))}}


def test_a_sync_marker_reads_back_and_garbage_reads_as_zero() -> None:
    assert parse_sync_marker("84000.00|36000.00") == (D("84000.00"), D("36000.00"))
    assert parse_sync_marker(None) == (D("0"), D("0"))
    assert parse_sync_marker("abc|12") == (D("0"), D("12"))
