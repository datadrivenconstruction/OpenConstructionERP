"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the tendering international / plain-language helpers.

These are pure, database-free tests for ``app.modules.tendering.intl``. They
pin the behaviour that matters for a worldwide audience: guarded divisions,
Decimal-exact rates, ISO 8601 deadlines with a caller-supplied response window,
late-response detection, award readiness, and the refusal to sum across
currencies.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.tendering import intl

# ── Concept explanations and status labels ────────────────────────────────────


def test_explain_returns_plain_sentence_for_known_concept() -> None:
    text = intl.explain("response_rate")
    assert "response rate" in text.lower()
    assert text.endswith(".")


def test_explain_is_case_insensitive_and_trims() -> None:
    assert intl.explain("  Award_Readiness ") == intl.explain("award_readiness")


def test_explain_unknown_concept_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown tender concept"):
        intl.explain("teleport")


def test_list_concepts_is_sorted_and_nonempty() -> None:
    concepts = intl.list_concepts()
    assert concepts == sorted(concepts)
    assert "award_readiness" in concepts


def test_status_labels_known_and_unknown() -> None:
    assert intl.package_status_label("awarded") == "Awarded to a winner"
    assert intl.recipient_status_label("sent") == "Invitation sent"
    assert intl.bid_status_label("submitted") == "Offer received"
    # Unknown codes degrade to a readable fallback, never crash.
    assert intl.package_status_label("brand_new") == "Brand new"
    assert intl.bid_status_label("") == "Unknown"


# ── Response rate ─────────────────────────────────────────────────────────────


def test_response_rate_basic() -> None:
    rr = intl.response_rate(invited=4, responded=3)
    assert rr.rate == Decimal(3) / Decimal(4)
    assert rr.rate_pct == 75.0
    assert rr.outstanding == 1
    assert rr.measurable is True


def test_response_rate_is_decimal_exact() -> None:
    # 1/3 is not representable in binary float; the Decimal fraction must be exact.
    rr = intl.response_rate(invited=3, responded=1)
    assert rr.rate == Decimal(1) / Decimal(3)


def test_response_rate_zero_invited_is_guarded() -> None:
    rr = intl.response_rate(invited=0, responded=0)
    assert rr.rate == Decimal("0")
    assert rr.rate_pct == 0.0
    assert rr.measurable is False
    assert "cannot be measured" in rr.explanation


def test_response_rate_full() -> None:
    rr = intl.response_rate(invited=5, responded=5)
    assert rr.rate == Decimal("1")
    assert rr.rate_pct == 100.0
    assert rr.outstanding == 0


@pytest.mark.parametrize(
    ("invited", "responded"),
    [(-1, 0), (2, -1), (2, 3)],
)
def test_response_rate_bad_inputs_raise(invited: int, responded: int) -> None:
    with pytest.raises(ValueError):
        intl.response_rate(invited=invited, responded=responded)


# ── Package coverage ──────────────────────────────────────────────────────────


def test_package_coverage_counts_covered_and_uncovered() -> None:
    packages = [
        {"package_id": "a", "name": "Concrete", "responded": 3},
        {"package_id": "b", "name": "Steel", "responded": 1},
        {"package_id": "c", "name": "Facade", "responded": 0},
    ]
    cov = intl.package_coverage(packages, min_responses=2)
    assert cov.total_packages == 3
    assert cov.covered_count == 1
    assert cov.uncovered_count == 2
    assert cov.covered == ["Concrete"]
    assert set(cov.uncovered) == {"Steel", "Facade"}
    assert cov.coverage_rate == Decimal(1) / Decimal(3)


def test_package_coverage_default_threshold_is_one() -> None:
    packages = [
        {"name": "A", "responded": 1},
        {"name": "B", "responded": 0},
    ]
    cov = intl.package_coverage(packages)
    assert cov.min_responses == 1
    assert cov.covered_count == 1


def test_package_coverage_reads_alternative_keys() -> None:
    packages = [
        {"id": "x", "name": "A", "bid_count": 2},
        {"id": "y", "name": "B", "responded_count": 5},
    ]
    cov = intl.package_coverage(packages, min_responses=2)
    assert cov.covered_count == 2


def test_package_coverage_empty_is_guarded() -> None:
    cov = intl.package_coverage([], min_responses=1)
    assert cov.total_packages == 0
    assert cov.coverage_rate == Decimal("0")
    assert cov.coverage_pct == 0.0
    assert cov.items == []


def test_package_coverage_bad_min_responses_raises() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        intl.package_coverage([], min_responses=0)


def test_package_coverage_negative_count_raises() -> None:
    with pytest.raises(ValueError):
        intl.package_coverage([{"name": "A", "responded": -1}])


# ── Deadlines and late responses ──────────────────────────────────────────────


def test_deadline_from_window_adds_days() -> None:
    deadline = intl.deadline_from_window("2026-07-01T00:00:00+00:00", 14)
    assert deadline.startswith("2026-07-15")


def test_deadline_from_window_requires_positive_window() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        intl.deadline_from_window("2026-07-01", 0)


def test_deadline_from_window_bad_date_raises() -> None:
    with pytest.raises(ValueError, match="issued_at"):
        intl.deadline_from_window("not-a-date", 7)


def test_is_late_true_when_after_deadline() -> None:
    assert intl.is_late("2026-07-10T12:00:00Z", "2026-07-10T12:00:01Z") is True


def test_is_late_false_when_before_deadline() -> None:
    assert intl.is_late("2026-07-10T12:00:00Z", "2026-07-10T11:59:59Z") is False


def test_is_late_date_only_deadline_is_end_of_day() -> None:
    # A date-only deadline means anytime that day is on time.
    assert intl.is_late("2026-07-10", "2026-07-10T23:00:00Z") is False
    # The next day is late.
    assert intl.is_late("2026-07-10", "2026-07-11T00:30:00Z") is True


def test_is_late_handles_naive_submission_as_utc() -> None:
    # Naive submission (no offset) is read as UTC and compared consistently.
    assert intl.is_late("2026-07-10T12:00:00Z", "2026-07-10T13:00:00") is True


def test_is_late_requires_both_values() -> None:
    with pytest.raises(ValueError):
        intl.is_late("", "2026-07-10T12:00:00Z")
    with pytest.raises(ValueError):
        intl.is_late("2026-07-10T12:00:00Z", "")


# ── Award readiness ───────────────────────────────────────────────────────────


def test_award_readiness_ready_when_enough_compliant() -> None:
    ar = intl.award_readiness(responded=4, compliant=3, min_compliant=2)
    assert ar.ready is True
    assert ar.shortfall == 0


def test_award_readiness_not_ready_when_short() -> None:
    ar = intl.award_readiness(responded=4, compliant=1, min_compliant=3)
    assert ar.ready is False
    assert ar.shortfall == 2
    assert any("more needed" in r for r in ar.reasons)


def test_award_readiness_requires_deadline_passed_when_asked() -> None:
    # Enough compliant bids, but the deadline is in the far future.
    ar = intl.award_readiness(
        responded=5,
        compliant=5,
        min_compliant=1,
        deadline="2999-01-01T00:00:00Z",
        as_of="2026-07-05T00:00:00Z",
        require_deadline_passed=True,
    )
    assert ar.ready is False
    assert ar.deadline_passed is False
    assert any("deadline has not passed" in r for r in ar.reasons)


def test_award_readiness_ready_once_deadline_passed() -> None:
    ar = intl.award_readiness(
        responded=5,
        compliant=5,
        min_compliant=1,
        deadline="2026-07-01T00:00:00Z",
        as_of="2026-07-05T00:00:00Z",
        require_deadline_passed=True,
    )
    assert ar.ready is True
    assert ar.deadline_passed is True


def test_award_readiness_bad_counts_raise() -> None:
    with pytest.raises(ValueError):
        intl.award_readiness(responded=2, compliant=3)
    with pytest.raises(ValueError):
        intl.award_readiness(responded=2, compliant=1, min_compliant=0)


# ── Currency safety ───────────────────────────────────────────────────────────


def test_sum_by_currency_keeps_buckets_separate() -> None:
    totals = intl.sum_by_currency(
        [
            ("100.10", "EUR"),
            (Decimal("50.05"), "eur"),
            ("200", "USD"),
        ]
    )
    assert totals["EUR"] == Decimal("150.15")
    assert totals["USD"] == Decimal("200")


def test_sum_by_currency_is_decimal_exact() -> None:
    totals = intl.sum_by_currency([("0.1", "EUR"), ("0.2", "EUR")])
    assert totals["EUR"] == Decimal("0.3")


def test_sum_by_currency_unknown_code_bucketed_separately() -> None:
    totals = intl.sum_by_currency([("10", ""), ("5", "EUR")])
    assert totals[""] == Decimal("10")
    assert totals["EUR"] == Decimal("5")


def test_sum_by_currency_bad_amount_raises() -> None:
    with pytest.raises(ValueError, match="valid decimal"):
        intl.sum_by_currency([("abc", "EUR")])


def test_single_currency_returns_shared_code() -> None:
    assert intl.single_currency(["EUR", "eur", " EUR "]) == "EUR"


def test_single_currency_ignores_empty_entries() -> None:
    assert intl.single_currency(["", "USD", "  "]) == "USD"


def test_single_currency_rejects_mixed_set() -> None:
    with pytest.raises(ValueError, match="mixed-currency"):
        intl.single_currency(["EUR", "USD"])


def test_single_currency_rejects_empty_set() -> None:
    with pytest.raises(ValueError, match="no currency"):
        intl.single_currency(["", "  "])
