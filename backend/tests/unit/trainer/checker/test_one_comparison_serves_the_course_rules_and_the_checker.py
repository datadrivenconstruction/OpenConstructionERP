# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Decision 37: one comparison function, used by the course rules and the checker.

The course rules decide whether the seed already satisfies a graded readback
(the discriminating rule); the checker decides whether the learner's ERP
does. If the two compared differently, a course could load whose task passes
on the untouched seed, or be refused although the checker would fail it. The
case that once split them: a rate written as a fraction with a fraction
tolerance, read back from a percent column.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.trainer import validators
from app.modules.trainer.checker.matching import Expectation, compare, values_match
from app.modules.trainer.spec import normalise_course_dict

COURSE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "trainer" / "course_fixture_v1.json"

#: (expected, observed, kind, tolerance, unit, observed unit, currency, match?)
CASES = [
    # 0.05 as a fraction, tolerance 0.0001 as a fraction = 0.01 percentage points.
    (Decimal("0.05"), Decimal("5.009"), "percent", Decimal("0.0001"), "fraction", None, None, True),
    (Decimal("0.05"), Decimal("5.02"), "percent", Decimal("0.0001"), "fraction", None, None, False),
    (Decimal("5"), Decimal("0.05"), "percent", Decimal("0.01"), "percent", "fraction", None, True),
    (Decimal("5"), Decimal("0.05"), "percent", Decimal("0.01"), "percent", None, None, False),
    # Money is quantised to the currency on both sides before the tolerance.
    (Decimal("2433.12"), Decimal("2433.124"), "money", Decimal("0"), None, None, "GBP", True),
    (Decimal("2433.12"), Decimal("2433.13"), "money", Decimal("0"), None, None, "GBP", False),
    (Decimal("1200"), Decimal("1200.4"), "money", Decimal("0"), None, None, "JPY", True),
    # A plain number is never rounded.
    (Decimal("42"), Decimal("42.004"), "number", Decimal("0"), None, None, "GBP", False),
    ("Direct_Cost", "direct_cost", "text", Decimal("0"), None, None, None, True),
    (False, "false", "bool", Decimal("0"), None, None, None, True),
    (True, False, "bool", Decimal("0"), None, None, None, False),
]


def test_the_course_rules_use_the_checkers_comparison() -> None:
    assert validators.values_match is values_match


@pytest.mark.parametrize(
    ("expected", "observed", "kind", "tolerance", "unit", "observed_unit", "currency", "want"), CASES
)
def test_values_match_and_compare_agree(
    expected: Any,
    observed: Any,
    kind: str,
    tolerance: Decimal,
    unit: str | None,
    observed_unit: str | None,
    currency: str | None,
    want: bool,
) -> None:
    got = values_match(
        expected,
        observed,
        kind=kind,  # type: ignore[arg-type]
        tolerance=tolerance,
        unit=unit,
        observed_unit=observed_unit,
        currency=currency,
    )
    assert got is want
    if observed_unit is None:
        # The checker always observes in the field's own unit.
        expectation = Expectation(value=expected, kind=kind, tolerance=tolerance, unit=unit, currency=currency)  # type: ignore[arg-type]
        assert compare(observed, expectation) == ("match" if want else "mismatch")


def test_an_unreadable_side_is_neither_a_match_nor_a_mismatch() -> None:
    assert values_match(Decimal(5), "five", kind="number", tolerance=Decimal(1)) is None
    assert values_match(None, Decimal(5), kind="money", tolerance=Decimal(1), currency="GBP") is None


def _course_with_seeded_profit(percentage: str) -> dict[str, Any]:
    raw = json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    course, problems = normalise_course_dict(raw)
    assert problems == []
    course = copy.deepcopy(course)
    course["seed"]["boq"]["markups"] = [{"name": "Profit", "percentage": percentage, "apply_to": "direct_cost"}]
    return course


def _profit_readback_discriminates(course: dict[str, Any]) -> bool:
    t2 = next(i for i, t in enumerate(course["tasks"]) if t["id"] == "t2-markups")
    return dict(validators.discriminating_items(course)[t2])[1]


@pytest.mark.parametrize(("seeded", "differs"), [("5.009", False), ("5.02", True)])
def test_the_discriminating_rule_scales_a_fraction_tolerance_like_the_checker(seeded: str, differs: bool) -> None:
    """T2 expects profit 0.05 (fraction, tolerance 0.0001); the seed holds a percent."""
    course = _course_with_seeded_profit(seeded)
    assert _profit_readback_discriminates(course) is differs
    answer = next(a for t in course["tasks"] for a in t["answer_key"] if a["name"] == "profit_rate")
    expectation = Expectation(
        value=answer["value"], kind="percent", tolerance=Decimal(str(answer["tolerance"])), unit=answer["unit"]
    )
    assert compare(Decimal(seeded), expectation) == ("mismatch" if differs else "match")
