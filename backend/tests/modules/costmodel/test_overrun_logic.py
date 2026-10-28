"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Gap D unit tests: the pure overrun-decision function.

``is_budget_line_overrun`` is a no-I/O decision used by both the subscriber and
the threshold UI logic, so it is exercised in isolation here (no DB needed).

Covers TEST MATRIX cases 1-4 (unit) plus boundary / parse-defence extras:
    1  not breached      (planned=100, actual=105, threshold=10  -> False)
    2  breached          (planned=100, actual=111, threshold=10  -> True)
    3  disabled          (threshold=0                            -> False)
    4  no planned        (planned=0                              -> False)
"""

from __future__ import annotations

import pytest

from app.modules.costmodel.service import is_budget_line_overrun

# ── Case 1: under the threshold ────────────────────────────────────────────────


def test_overrun_not_breached() -> None:
    # 105 < 100 * 1.10 = 110 -> no overrun yet.
    assert is_budget_line_overrun("100", "105", "10") is False


# ── Case 2: over the threshold ─────────────────────────────────────────────────


def test_overrun_breached() -> None:
    # 111 >= 110 -> overrun.
    assert is_budget_line_overrun("100", "111", "10") is True


# ── Case 3: alerting disabled (threshold 0) ────────────────────────────────────


def test_overrun_disabled() -> None:
    assert is_budget_line_overrun("100", "1000", "0") is False


# ── Case 4: no planned baseline ────────────────────────────────────────────────


def test_overrun_no_planned() -> None:
    assert is_budget_line_overrun("0", "500", "10") is False


# ── Boundary: actual exactly equals the limit (>= so it breaches) ──────────────


def test_overrun_exact_boundary_breaches() -> None:
    assert is_budget_line_overrun("100", "110", "10") is True


def test_overrun_just_below_boundary() -> None:
    assert is_budget_line_overrun("100", "109.99", "10") is False


# ── Parse defence: garbage / None inputs are False, never raise ────────────────


@pytest.mark.parametrize(
    ("planned", "actual", "threshold"),
    [
        (None, "100", "10"),
        ("100", None, "10"),
        ("100", "100", None),
        ("abc", "100", "10"),
        ("100", "xyz", "10"),
        ("100", "100", "nan"),
        ("nan", "100", "10"),
    ],
)
def test_overrun_bad_inputs_are_false(planned, actual, threshold) -> None:
    assert is_budget_line_overrun(planned, actual, threshold) is False


# ── Negative threshold is treated as disabled ──────────────────────────────────


def test_overrun_negative_threshold_disabled() -> None:
    assert is_budget_line_overrun("100", "1000", "-10") is False


# ── Decimal precision: large baseline, fractional threshold ────────────────────


def test_overrun_decimal_precision() -> None:
    # 1,000,000 * 1.025 = 1,025,000. 1,025,000 breaches; 1,024,999 does not.
    assert is_budget_line_overrun("1000000", "1025000", "2.5") is True
    assert is_budget_line_overrun("1000000", "1024999.99", "2.5") is False
