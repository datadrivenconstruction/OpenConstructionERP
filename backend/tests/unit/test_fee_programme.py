"""The neutral fee programme: ordered fee lines on component bases, by date.

The numbers are the Shenzhen 2025 row of the provincial worked example (labour
600,000 x 1.15, materials 1,150,000, plant 100,000, provisional sum 100,000,
VAT 9%), written here as a plain schedule so the engine is tested without any
pack data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.fee_programme import (
    FeeSchedule,
    compute,
    in_force,
    resolve,
    schedule_from_dict,
)

D = Decimal

_SZ = {
    "key": "sz_2025",
    "jurisdiction": "CN-GD-SZ",
    "edition": "2025",
    "effective_from": "2026-01-01",
    "labour_factor": "1.15",
    "lines": [
        {
            "code": "mgmt",
            "group": "fenbu",
            "base": {"labour": "1", "plant": "0.1"},
            "rate": "20.44",
            "band": {"min": "14", "max": "26"},
        },
        {"code": "profit", "group": "fenbu", "base": {"direct": "1", "line:mgmt": "1"}, "rate": "5"},
        {
            "code": "safety",
            "group": "cuoshi",
            "base": {"fenbu": "1"},
            "rate": "3.42",
            "non_competitive": True,
            "floor": "1.90",
        },
        {"code": "training", "group": "cuoshi", "base": {"fenbu": "1"}, "rate": "0.4"},
    ],
}

_COMPONENTS = {"labour": D(600000), "material": D(1150000), "plant": D(100000), "provisional_sum": D(100000)}


def _sz() -> FeeSchedule:
    return schedule_from_dict(_SZ)


def test_shenzhen_2025_worked_example_reproduces_to_the_cent() -> None:
    result = compute(_sz(), _COMPONENTS)
    amounts = {line.code: line.amount for line in result.lines}
    assert amounts == {
        "mgmt": D("143080.00"),
        "profit": D("104154.00"),
        "safety": D("74803.40"),
        "training": D("8748.94"),
    }
    assert result.labour == D("690000.00")
    assert result.subtotals["fenbu"] == D("2187234.00")
    assert result.pre_tax == D("2370786.34")
    assert result.vat == D("213370.77")
    assert result.total == D("2584157.11")


def test_labour_factor_is_skipped_when_labour_already_includes_social_insurance() -> None:
    result = compute(_sz(), _COMPONENTS, apply_labour_factor=False)
    assert result.labour == D("600000.00")
    assert result.labour_factor_applied is False


def test_a_coefficient_scales_the_rate_of_one_line() -> None:
    sched = schedule_from_dict(
        {
            "key": "split",
            "jurisdiction": "X",
            "lines": [
                {"code": "civil", "base": {"labour": "1", "plant": "1"}, "rate": "19", "coefficient": "0.22"},
                {"code": "safety", "base": {"labour": "1", "plant": "1"}, "rate": "19", "coefficient": "0.61"},
            ],
        }
    )
    result = compute(sched, {"labour": D(600000), "plant": D(100000)})
    assert [line.amount for line in result.lines] == [D("29260.00"), D("81130.00")]


def test_an_option_picks_the_rate_and_a_user_rate_wins_over_it() -> None:
    sched = schedule_from_dict(
        {
            "key": "bj",
            "jurisdiction": "X",
            "options": [{"key": "grade", "values": ["a", "b"], "default": "a"}],
            "lines": [
                {
                    "code": "safety",
                    "base": {"labour": "1"},
                    "rate_options": {"option": "grade", "rates": {"a": "10", "b": "20"}},
                },
                {"code": "mgmt", "base": {"labour": "1"}, "rate": None, "user_input": True},
            ],
        }
    )
    base = {"labour": D(1000)}
    first = compute(sched, base)
    assert [line.amount for line in first.lines] == [D("100.00"), D("0.00")]
    assert first.lines[1].status == "missing"
    second = compute(sched, base, options={"grade": "b"}, rates={"mgmt": D("15")})
    assert [line.amount for line in second.lines] == [D("200.00"), D("150.00")]
    assert second.lines[1].status == "user"
    assert second.lines[0].status == "published"


def test_a_base_can_exclude_lump_sum_measures() -> None:
    sched = schedule_from_dict(
        {
            "key": "sc",
            "jurisdiction": "X",
            "lines": [
                {"code": "safety", "base": {"fenbu": "1", "provisional_sum": "1"}, "rate": "10"},
            ],
        }
    )
    result = compute(sched, {"labour": D(100), "lump_sum_measures": D(1000), "provisional_sum": D(50)})
    assert result.lines[0].amount == D("15.00")
    assert result.pre_tax == D("1165.00")


def test_resolve_picks_the_schedule_in_force_on_the_date() -> None:
    old = schedule_from_dict(
        {
            "key": "old",
            "jurisdiction": "X",
            "effective_from": "2024-02-15",
            "effective_to": "2025-12-31",
            "superseded_by": "new",
            "lines": [],
        }
    )
    new = schedule_from_dict({"key": "new", "jurisdiction": "X", "effective_from": "2026-01-01", "lines": []})
    assert resolve([old, new], date(2025, 12, 31)).key == "old"
    assert resolve([old, new], date(2026, 1, 1)).key == "new"
    assert resolve([old, new], date(2020, 1, 1)) is None
    assert in_force(old, date(2026, 6, 1)) is False
    assert in_force(new, None) is True
