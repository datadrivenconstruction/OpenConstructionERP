"""BIM element-rule correctness + security hardening.

* E-I18N-017 — ``_coerce_number`` accepts comma decimals / trailing units
* E-SEC-002  — ``must_match`` is ReDoS-resistant (bounded, safe-regex guard)
* E-BIM-010  — wall/door/window "has dimension" rules assert a value > 0
* E-XMOD-015 — BIM-model score uses the shared severity-weighted formula
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.core.validation.engine import SEVERITY_WEIGHTS, compute_quality_score
from app.modules.validation.rules.bim_element_rule import (
    BIMElementRule,
    _check_value,
    _coerce_number,
    _is_pattern_safe,
)
from app.modules.validation.rules.bim_universal import (
    DOOR_HAS_DIMENSIONS,
    WALL_HAS_THICKNESS,
)


def _elem(**kw):
    base = {
        "id": "e1",
        "name": "El",
        "element_type": "wall",
        "properties": {},
        "quantities": {},
    }
    base.update(kw)
    return SimpleNamespace(**base)


class TestCoerceNumberLocale:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0,24", 0.24),
            ("1.234,56", 1234.56),
            ("3.0 m", 3.0),
            ("0.24", 0.24),
            ("2,5", 2.5),
            (1.5, 1.5),
            (3, 3.0),
        ],
    )
    def test_parses(self, raw: object, expected: float) -> None:
        assert _coerce_number(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [None, True, "abc", ""])
    def test_non_numbers_return_none(self, raw: object) -> None:
        assert _coerce_number(raw) is None

    def test_german_thickness_not_false_failure(self) -> None:
        # E-I18N-017: '0,24' >= 0.24 must PASS, not "is not a number".
        assert _check_value("0,24", {"must_be_gte": 0.24}) is None
        assert _check_value("0.24", {"must_be_gte": 0.24}) is None
        assert _check_value("0,10", {"must_be_gte": 0.24}) is not None


class TestRegexHardening:
    def test_nested_quantifier_rejected(self) -> None:
        assert _is_pattern_safe("(a+)+$") is False
        assert _is_pattern_safe("(a*)*") is False
        assert _is_pattern_safe("(?:ab+)+") is False

    def test_normal_patterns_allowed(self) -> None:
        assert _is_pattern_safe("^[A-Z]{2}$") is True
        assert _is_pattern_safe(r"\d{3}\.\d{2}") is True

    def test_overlong_pattern_rejected(self) -> None:
        assert _is_pattern_safe("a" * 2000) is False

    def test_catastrophic_pattern_does_not_hang(self) -> None:
        """E-SEC-002: the classic ReDoS input must resolve fast."""
        rule = BIMElementRule(
            rule_id="r",
            name="R",
            severity="error",
            property_checks=[{"property": "mark", "must_match": "(a+)+$"}],
        )
        elem = _elem(properties={"mark": "a" * 40 + "!"})
        started = time.monotonic()
        results = rule.evaluate(elem)
        elapsed = time.monotonic() - started
        assert elapsed < 2.0  # was >25s (timeout-killed) before the fix
        assert len(results) == 1  # degrades to a plain non-match failure

    def test_safe_pattern_still_matches(self) -> None:
        rule = BIMElementRule(
            rule_id="r",
            name="R",
            severity="error",
            property_checks=[{"property": "mark", "must_match": r"^WALL-\d+$"}],
        )
        assert rule.evaluate(_elem(properties={"mark": "WALL-12"})) == []
        assert len(rule.evaluate(_elem(properties={"mark": "nope"}))) == 1


class TestPositiveQuantityRules:
    def test_wall_thickness_zero_fails(self) -> None:
        # E-BIM-010: thickness_m=0 must FAIL (was a silent PASS).
        assert len(WALL_HAS_THICKNESS.evaluate(_elem(quantities={"thickness_m": 0}))) == 1

    def test_wall_thickness_missing_fails(self) -> None:
        assert len(WALL_HAS_THICKNESS.evaluate(_elem(quantities={}))) == 1

    def test_wall_thickness_positive_passes(self) -> None:
        assert WALL_HAS_THICKNESS.evaluate(_elem(quantities={"thickness_m": 0.24})) == []

    def test_wall_thickness_german_string_passes(self) -> None:
        # '0,24' is a valid positive number once locale-coerced.
        assert WALL_HAS_THICKNESS.evaluate(_elem(quantities={"thickness_m": "0,24"})) == []

    def test_door_zero_dimensions_fail(self) -> None:
        door = _elem(
            element_type="door",
            properties={"width": 0.9},
            quantities={"width_m": 0, "height_m": 0},
        )
        assert len(DOOR_HAS_DIMENSIONS.evaluate(door)) >= 1


class TestScoreAlignment:
    """E-XMOD-015: one scoring definition shared by BOQ + BIM paths."""

    def test_shared_weights(self) -> None:
        assert SEVERITY_WEIGHTS == {"error": 3.0, "warning": 1.5, "info": 0.4}

    def test_all_pass_is_one(self) -> None:
        assert compute_quality_score(10.0, 10.0, 0) == 1.0

    def test_blocking_error_caps_score(self) -> None:
        # 7/8 weighted would be 0.875 — a single error caps it to 0.25.
        assert compute_quality_score(7 * 3.0, 8 * 3.0, 1) == 0.25

    def test_no_checks_is_one(self) -> None:
        assert compute_quality_score(0.0, 0.0, 0) == 1.0
