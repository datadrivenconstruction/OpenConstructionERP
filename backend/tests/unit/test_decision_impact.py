# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure decision-time impact-preview engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Money is
exercised exclusively with Decimal literals; every before / after row is
asserted to satisfy resulting == committed + candidate, and currencies are
asserted never to blend.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.change_intelligence.decision_impact import (
    COMMITTED_STATUSES,
    KIND_VARIATION_ORDER,
    TWOPLACES,
    ChangeImpact,
    CurrencyTotal,
    DecisionImpact,
    DecisionImpactRow,
    is_committed,
    project_with_pending,
    project_with_pending_many,
    quantize_money,
)


def _impact(
    kind: str,
    currency: str,
    cost: str,
    days: str,
    status: str = "approved",
) -> ChangeImpact:
    """Build a ChangeImpact from string money / day literals.

    The default status is a committed CHANGE-ORDER status. The families do not
    share a status vocabulary, so a variation-order fixture has to spell its own
    out: a variation order's FSM is issued -> in_progress -> completed | voided
    and can never hold "approved", so the default would build a row the database
    cannot produce.
    """
    return ChangeImpact(
        kind=kind,
        currency=currency,
        cost_impact=Decimal(cost),
        schedule_impact_days=Decimal(days),
        status=status,
    )


def _row_by_key(impact: DecisionImpact, kind: str, currency: str) -> DecisionImpactRow:
    """Fetch the single row for a (kind, currency); fail if absent / duplicated."""
    matches = [r for r in impact.rows if r.kind == kind and r.currency == currency]
    assert len(matches) == 1, f"expected exactly one row for ({kind!r}, {currency!r}), got {len(matches)}"
    return matches[0]


def _total_by_currency(impact: DecisionImpact, currency: str) -> CurrencyTotal:
    """Fetch the single currency rollup; fail if absent / duplicated."""
    matches = [t for t in impact.totals_by_currency if t.currency == currency]
    assert len(matches) == 1, f"expected exactly one currency total for {currency!r}, got {len(matches)}"
    return matches[0]


def _assert_row_consistent(row: DecisionImpactRow) -> None:
    """resulting == committed + candidate, and money is 2dp, for one row."""
    assert row.resulting_cost == quantize_money(row.current_committed_cost + row.candidate_cost_delta)
    assert row.resulting_days == row.current_committed_days + row.candidate_days_delta
    for amt in (row.current_committed_cost, row.candidate_cost_delta, row.resulting_cost):
        assert amt == amt.quantize(TWOPLACES)


def _assert_total_consistent(total: CurrencyTotal) -> None:
    """resulting == committed + candidate, and money is 2dp, for one rollup."""
    assert total.resulting_cost == quantize_money(total.current_committed_cost + total.candidate_cost_delta)
    assert total.resulting_days == total.current_committed_days + total.candidate_days_delta
    for amt in (total.current_committed_cost, total.candidate_cost_delta, total.resulting_cost):
        assert amt == amt.quantize(TWOPLACES)


# ---------------------------------------------------------------------------
# constants / primitives
# ---------------------------------------------------------------------------


def test_committed_statuses_are_approved_and_executed() -> None:
    assert frozenset({"approved", "executed"}) == COMMITTED_STATUSES


def test_twoplaces_constant() -> None:
    assert Decimal("0.01") == TWOPLACES


def test_quantize_money_half_up() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")
    assert quantize_money(Decimal("-1.005")) == Decimal("-1.01")


@pytest.mark.parametrize(
    "status,expected",
    [
        ("approved", True),
        ("executed", True),
        ("APPROVED", True),  # case-insensitive
        ("  Executed  ", True),  # trimmed + case-insensitive
        ("draft", False),
        ("pending", False),
        ("submitted", False),
        ("rejected", False),
        ("", False),
        ("   ", False),
    ],
)
def test_is_committed_vocabulary(status: str, expected: bool) -> None:
    # No kind argument: the default is the change-order vocabulary.
    assert is_committed(status) is expected


@pytest.mark.parametrize(
    "status,expected",
    [
        ("issued", True),  # an issued VO is in force, so its cost is committed
        ("in_progress", True),
        ("completed", True),
        ("COMPLETED", True),  # case-insensitive
        ("  issued  ", True),  # trimmed + case-insensitive
        ("voided", False),  # the one VO state that carries no committed cost
        # The change-order words are not variation-order states at all: a VO's
        # FSM is issued -> in_progress -> completed | voided. Answering True for
        # them would mean the change-order vocabulary is being applied to a
        # variation order, which is how every agreed VO once fell out of the
        # committed baseline.
        ("approved", False),
        ("executed", False),
        ("", False),
    ],
)
def test_is_committed_variation_order_vocabulary(status: str, expected: bool) -> None:
    assert is_committed(status, KIND_VARIATION_ORDER) is expected


# ---------------------------------------------------------------------------
# project_with_pending - single candidate, delta math + before/after
# ---------------------------------------------------------------------------


def test_single_candidate_on_top_of_committed() -> None:
    committed = [_impact("change_order", "USD", "100.00", "5")]
    candidate = _impact("change_order", "USD", "40.00", "2", status="draft")
    result = project_with_pending(committed, candidate)

    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("100.00")
    assert row.candidate_cost_delta == Decimal("40.00")
    assert row.resulting_cost == Decimal("140.00")
    assert row.current_committed_days == Decimal("5")
    assert row.candidate_days_delta == Decimal("2")
    assert row.resulting_days == Decimal("7")
    _assert_row_consistent(row)


def test_single_candidate_no_committed_baseline() -> None:
    # Nothing committed yet: committed columns zero, resulting == candidate.
    candidate = _impact("change_order", "USD", "40.00", "2", status="pending")
    result = project_with_pending([], candidate)

    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("0.00")
    assert row.candidate_cost_delta == Decimal("40.00")
    assert row.resulting_cost == Decimal("40.00")
    assert row.current_committed_days == Decimal("0")
    assert row.candidate_days_delta == Decimal("2")
    assert row.resulting_days == Decimal("2")
    _assert_row_consistent(row)


def test_single_candidate_negative_delta_is_a_credit() -> None:
    # A candidate credit / acceleration: signed amounts carry through.
    committed = [_impact("variation_order", "USD", "500.00", "10", status="completed")]
    candidate = _impact("variation_order", "USD", "-120.50", "-3", status="draft")
    result = project_with_pending(committed, candidate)

    row = _row_by_key(result, "variation_order", "USD")
    assert row.candidate_cost_delta == Decimal("-120.50")
    assert row.resulting_cost == Decimal("379.50")
    assert row.candidate_days_delta == Decimal("-3")
    assert row.resulting_days == Decimal("7")
    _assert_row_consistent(row)


def test_candidate_status_is_irrelevant_to_being_a_delta() -> None:
    # Even an already-"approved" candidate is treated as a prospective delta on
    # its own row - it does NOT fold into the committed baseline.
    committed = [_impact("change_order", "USD", "100.00", "5")]
    cand_draft = project_with_pending(committed, _impact("change_order", "USD", "40.00", "2", status="draft"))
    cand_approved = project_with_pending(committed, _impact("change_order", "USD", "40.00", "2", status="approved"))

    assert cand_draft == cand_approved
    row = _row_by_key(cand_approved, "change_order", "USD")
    assert row.current_committed_cost == Decimal("100.00")
    assert row.candidate_cost_delta == Decimal("40.00")


def test_single_candidate_zero_cost_and_days_still_surfaces_row() -> None:
    # The reviewer always sees the line they are deciding on, even if it is all
    # zeros (e.g. a documentation-only change).
    result = project_with_pending([], _impact("moc_entry", "EUR", "0.00", "0", status="draft"))
    row = _row_by_key(result, "moc_entry", "EUR")
    assert row.current_committed_cost == Decimal("0.00")
    assert row.candidate_cost_delta == Decimal("0.00")
    assert row.resulting_cost == Decimal("0.00")
    assert row.resulting_days == Decimal("0")


# ---------------------------------------------------------------------------
# committed-vs-noncommitted filtering of the baseline
# ---------------------------------------------------------------------------


def test_noncommitted_items_excluded_from_baseline() -> None:
    # Only approved/executed count toward current_committed; pending/draft do not.
    committed = [
        _impact("change_order", "USD", "100.00", "5", status="approved"),
        _impact("change_order", "USD", "60.00", "3", status="executed"),
        _impact("change_order", "USD", "999.00", "99", status="pending"),  # ignored
        _impact("change_order", "USD", "777.00", "77", status="draft"),  # ignored
    ]
    candidate = _impact("change_order", "USD", "10.00", "1", status="draft")
    result = project_with_pending(committed, candidate)

    row = _row_by_key(result, "change_order", "USD")
    # 100 + 60 committed; the pending/draft 999/777 are excluded.
    assert row.current_committed_cost == Decimal("160.00")
    assert row.current_committed_days == Decimal("8")
    assert row.candidate_cost_delta == Decimal("10.00")
    assert row.resulting_cost == Decimal("170.00")
    _assert_row_consistent(row)


def test_executed_status_counts_as_committed() -> None:
    committed = [_impact("change_order", "USD", "250.00", "4", status="executed")]
    result = project_with_pending(committed, _impact("change_order", "USD", "0.00", "0", status="draft"))
    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("250.00")


def test_committed_status_matching_is_case_insensitive_and_trimmed() -> None:
    committed = [_impact("change_order", "USD", "80.00", "2", status="  Approved ")]
    result = project_with_pending(committed, _impact("change_order", "USD", "0.00", "0", status="draft"))
    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("80.00")


def test_all_baseline_noncommitted_yields_zero_committed() -> None:
    committed = [
        _impact("change_order", "USD", "100.00", "5", status="pending"),
        _impact("change_order", "USD", "50.00", "2", status="rejected"),
    ]
    candidate = _impact("change_order", "USD", "10.00", "1", status="draft")
    result = project_with_pending(committed, candidate)
    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("0.00")
    assert row.candidate_cost_delta == Decimal("10.00")
    assert row.resulting_cost == Decimal("10.00")


# ---------------------------------------------------------------------------
# multi-currency separation - never blend
# ---------------------------------------------------------------------------


def test_currencies_never_blend_across_rows() -> None:
    # Committed USD work, candidate priced in EUR -> two distinct rows.
    committed = [_impact("change_order", "USD", "100.00", "5")]
    candidate = _impact("change_order", "EUR", "40.00", "2", status="draft")
    result = project_with_pending(committed, candidate)

    usd = _row_by_key(result, "change_order", "USD")
    eur = _row_by_key(result, "change_order", "EUR")
    assert usd.current_committed_cost == Decimal("100.00")
    assert usd.candidate_cost_delta == Decimal("0.00")  # no EUR candidate touches USD
    assert usd.resulting_cost == Decimal("100.00")
    assert eur.current_committed_cost == Decimal("0.00")  # no USD committed touches EUR
    assert eur.candidate_cost_delta == Decimal("40.00")
    assert eur.resulting_cost == Decimal("40.00")
    _assert_row_consistent(usd)
    _assert_row_consistent(eur)


def test_currency_totals_kept_separate() -> None:
    committed = [
        _impact("change_order", "USD", "100.00", "5"),
        _impact("variation_order", "EUR", "200.00", "10", status="completed"),
    ]
    candidate = _impact("change_order", "USD", "25.00", "1", status="draft")
    result = project_with_pending(committed, candidate)

    usd_total = _total_by_currency(result, "USD")
    eur_total = _total_by_currency(result, "EUR")
    assert usd_total.current_committed_cost == Decimal("100.00")
    assert usd_total.candidate_cost_delta == Decimal("25.00")
    assert usd_total.resulting_cost == Decimal("125.00")
    assert eur_total.current_committed_cost == Decimal("200.00")
    assert eur_total.candidate_cost_delta == Decimal("0.00")
    assert eur_total.resulting_cost == Decimal("200.00")
    _assert_total_consistent(usd_total)
    _assert_total_consistent(eur_total)


def test_empty_currency_code_is_its_own_bucket() -> None:
    # An unpriced change (empty currency) is surfaced, not dropped or merged.
    committed = [_impact("change_order", "USD", "100.00", "5")]
    candidate = _impact("change_order", "", "0.00", "3", status="draft")
    result = project_with_pending(committed, candidate)

    blank = _row_by_key(result, "change_order", "")
    assert blank.candidate_days_delta == Decimal("3")
    assert blank.current_committed_cost == Decimal("0.00")
    # The empty-currency row sorts before "USD".
    currencies = [r.currency for r in result.rows]
    assert currencies == ["", "USD"]


# ---------------------------------------------------------------------------
# multiple kinds - one row per (kind, currency), deterministic order
# ---------------------------------------------------------------------------


def test_multiple_kinds_each_get_a_row() -> None:
    committed = [
        _impact("change_order", "USD", "100.00", "5"),
        _impact("variation_order", "USD", "200.00", "10", status="in_progress"),
    ]
    # The candidate carries a committed VO status on purpose: it must still be
    # read as a prospective delta, not folded into the VO baseline.
    candidate = _impact("variation_order", "USD", "50.00", "2", status="completed")
    result = project_with_pending(committed, candidate)

    co = _row_by_key(result, "change_order", "USD")
    vo = _row_by_key(result, "variation_order", "USD")
    assert co.candidate_cost_delta == Decimal("0.00")
    assert co.resulting_cost == Decimal("100.00")
    assert vo.candidate_cost_delta == Decimal("50.00")
    assert vo.resulting_cost == Decimal("250.00")


def test_rows_ordered_by_kind_then_currency() -> None:
    committed = [
        _impact("variation_order", "USD", "1.00", "0", status="issued"),
        _impact("change_order", "USD", "1.00", "0"),
        _impact("change_order", "EUR", "1.00", "0"),
    ]
    candidate = _impact("change_order", "EUR", "1.00", "0", status="draft")
    result = project_with_pending(committed, candidate)
    keys = [(r.kind, r.currency) for r in result.rows]
    assert keys == [
        ("change_order", "EUR"),
        ("change_order", "USD"),
        ("variation_order", "USD"),
    ]


def test_currency_totals_ordered_by_currency() -> None:
    committed = [
        _impact("change_order", "USD", "1.00", "0"),
        _impact("change_order", "EUR", "1.00", "0"),
        _impact("change_order", "GBP", "1.00", "0"),
    ]
    candidate = _impact("change_order", "USD", "1.00", "0", status="draft")
    result = project_with_pending(committed, candidate)
    assert [t.currency for t in result.totals_by_currency] == ["EUR", "GBP", "USD"]


# ---------------------------------------------------------------------------
# project_with_pending_many - candidate deltas summed per (kind, currency)
# ---------------------------------------------------------------------------


def test_many_candidates_same_kind_currency_sum() -> None:
    committed = [_impact("change_order", "USD", "100.00", "5")]
    candidates = [
        _impact("change_order", "USD", "40.00", "2", status="draft"),
        _impact("change_order", "USD", "10.00", "1", status="pending"),
        _impact("change_order", "USD", "-5.00", "0", status="draft"),
    ]
    result = project_with_pending_many(committed, candidates)

    row = _row_by_key(result, "change_order", "USD")
    # 40 + 10 - 5 = 45 candidate delta on top of 100 committed.
    assert row.candidate_cost_delta == Decimal("45.00")
    assert row.resulting_cost == Decimal("145.00")
    assert row.candidate_days_delta == Decimal("3")
    assert row.resulting_days == Decimal("8")
    _assert_row_consistent(row)


def test_many_candidates_across_kinds_and_currencies() -> None:
    committed = [
        _impact("change_order", "USD", "100.00", "5"),
        _impact("variation_order", "EUR", "200.00", "10", status="completed"),
    ]
    candidates = [
        _impact("change_order", "USD", "30.00", "1", status="draft"),
        _impact("variation_order", "EUR", "20.00", "2", status="pending"),
        _impact("change_order", "EUR", "15.00", "0", status="draft"),  # new kind+currency cell
    ]
    result = project_with_pending_many(committed, candidates)

    co_usd = _row_by_key(result, "change_order", "USD")
    vo_eur = _row_by_key(result, "variation_order", "EUR")
    co_eur = _row_by_key(result, "change_order", "EUR")
    assert co_usd.resulting_cost == Decimal("130.00")
    assert vo_eur.resulting_cost == Decimal("220.00")
    assert co_eur.current_committed_cost == Decimal("0.00")
    assert co_eur.resulting_cost == Decimal("15.00")

    # Currency rollups: USD has only the change_order; EUR rolls VO + CO.
    usd_total = _total_by_currency(result, "USD")
    eur_total = _total_by_currency(result, "EUR")
    assert usd_total.resulting_cost == Decimal("130.00")
    # EUR committed 200 (VO) + 0 (CO) = 200; candidate 20 (VO) + 15 (CO) = 35.
    assert eur_total.current_committed_cost == Decimal("200.00")
    assert eur_total.candidate_cost_delta == Decimal("35.00")
    assert eur_total.resulting_cost == Decimal("235.00")
    _assert_total_consistent(usd_total)
    _assert_total_consistent(eur_total)


def test_many_candidates_noncommitted_baseline_still_filtered() -> None:
    committed = [
        _impact("change_order", "USD", "100.00", "5", status="approved"),
        _impact("change_order", "USD", "500.00", "50", status="draft"),  # ignored
    ]
    candidates = [_impact("change_order", "USD", "10.00", "1", status="draft")]
    result = project_with_pending_many(committed, candidates)
    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("100.00")
    assert row.candidate_cost_delta == Decimal("10.00")


def test_many_with_empty_candidate_list_shows_baseline_only() -> None:
    committed = [
        _impact("change_order", "USD", "100.00", "5"),
        _impact("variation_order", "EUR", "200.00", "10", status="issued"),
    ]
    result = project_with_pending_many(committed, [])

    co = _row_by_key(result, "change_order", "USD")
    vo = _row_by_key(result, "variation_order", "EUR")
    assert co.candidate_cost_delta == Decimal("0.00")
    assert co.resulting_cost == Decimal("100.00")
    assert vo.candidate_cost_delta == Decimal("0.00")
    assert vo.resulting_cost == Decimal("200.00")
    _assert_row_consistent(co)
    _assert_row_consistent(vo)


# ---------------------------------------------------------------------------
# empty input
# ---------------------------------------------------------------------------


def test_empty_both_sides_yields_empty_preview() -> None:
    result = project_with_pending_many([], [])
    assert isinstance(result, DecisionImpact)
    assert result.rows == ()
    assert result.totals_by_currency == ()


def test_committed_only_no_candidate_via_many() -> None:
    committed = [_impact("change_order", "USD", "100.00", "5")]
    result = project_with_pending_many(committed, [])
    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("100.00")
    assert row.candidate_cost_delta == Decimal("0.00")
    assert row.resulting_cost == Decimal("100.00")


# ---------------------------------------------------------------------------
# money discipline: quantization, signed rounding, no float artifacts
# ---------------------------------------------------------------------------


def test_money_quantized_two_places_half_up() -> None:
    # 0.005 half-up rounds to 0.01 on each side, and resulting reconciles.
    committed = [_impact("change_order", "USD", "0.005", "0")]
    candidate = _impact("change_order", "USD", "0.005", "0", status="draft")
    result = project_with_pending(committed, candidate)
    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_cost == Decimal("0.01")
    assert row.candidate_cost_delta == Decimal("0.01")
    assert row.resulting_cost == Decimal("0.02")


def test_fractional_days_summed_as_decimal() -> None:
    committed = [_impact("change_order", "USD", "0.00", "1.5")]
    candidate = _impact("change_order", "USD", "0.00", "2.25", status="draft")
    result = project_with_pending(committed, candidate)
    row = _row_by_key(result, "change_order", "USD")
    assert row.current_committed_days == Decimal("1.5")
    assert row.candidate_days_delta == Decimal("2.25")
    assert row.resulting_days == Decimal("3.75")


def test_all_row_money_is_two_decimal_places() -> None:
    committed = [_impact("change_order", "USD", "1234.5", "5")]
    candidate = _impact("change_order", "USD", "1.1", "1", status="draft")
    result = project_with_pending(committed, candidate)
    for row in result.rows:
        assert row.current_committed_cost.as_tuple().exponent == -2
        assert row.candidate_cost_delta.as_tuple().exponent == -2
        assert row.resulting_cost.as_tuple().exponent == -2


def test_decimal_exactness_no_float_drift() -> None:
    # Values that would drift as floats stay exact through the Decimal sum.
    committed = [_impact("change_order", "USD", "0.10", "0")]
    candidate = _impact("change_order", "USD", "0.20", "0", status="draft")
    result = project_with_pending(committed, candidate)
    row = _row_by_key(result, "change_order", "USD")
    assert row.resulting_cost == Decimal("0.30")


# ---------------------------------------------------------------------------
# return types
# ---------------------------------------------------------------------------


def test_returns_proper_dataclasses() -> None:
    committed = [_impact("change_order", "USD", "100.00", "5")]
    result = project_with_pending(committed, _impact("change_order", "USD", "1.00", "1", status="draft"))
    assert isinstance(result, DecisionImpact)
    assert all(isinstance(r, DecisionImpactRow) for r in result.rows)
    assert all(isinstance(t, CurrencyTotal) for t in result.totals_by_currency)
