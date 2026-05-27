"""Locale-tolerant numeric handling in the core validation rules.

Covers the keystone i18n-data-layer fixes:

* ``_to_number`` parses de/fr/us number strings (E-I18N-004 / I18N-DATA-LAYER)
* numeric rules no longer crash the engine on locale-formatted strings
* ``_median`` is a true median for even lists (E-VAL-013)
* ``TotalMismatch`` uses a magnitude-aware tolerance (E-VAL-014)
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import (
    ValidationContext,
    rule_registry,
    validation_engine,
)
from app.core.validation.rules import (
    _NOT_A_NUMBER,
    TotalMismatch,
    UnitRateInRange,
    _median,
    _num,
    _to_number,
    register_builtin_rules,
)


class TestToNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.234,56", 1234.56),  # German
            ("150,00", 150.0),  # German decimal
            ("185.184,00", 185184.0),  # German with thousands
            ("1 234,56", 1234.56),  # French (ASCII space)
            ("1 234,56", 1234.56),  # French (NBSP)
            ("1 234,56", 1234.56),  # French (narrow NBSP)
            ("0,24", 0.24),  # German thickness
            ("2,5", 2.5),
            ("3.0 m", 3.0),  # trailing unit
            ("150,00 EUR", 150.0),  # trailing currency
            ("1234.56", 1234.56),  # canonical
            ("185184.0", 185184.0),  # canonical, dot decimal kept
            ("1,234,567", 1234567.0),  # US thousands
            ("1.234.567", 1234567.0),  # German thousands
            ("-1.234,56", -1234.56),  # negative German
            (5, 5.0),
            (5.5, 5.5),
        ],
    )
    def test_parses(self, raw: object, expected: float) -> None:
        assert _to_number(raw) == pytest.approx(expected)

    def test_none_is_none(self) -> None:
        assert _to_number(None) is None

    @pytest.mark.parametrize("raw", ["", "abc", True, float("nan"), float("inf")])
    def test_unparseable_is_sentinel(self, raw: object) -> None:
        assert _to_number(raw) is _NOT_A_NUMBER

    def test_num_falls_back_to_default(self) -> None:
        assert _num(None) == 0.0
        assert _num("garbage") == 0.0
        assert _num("1.234,56") == pytest.approx(1234.56)
        assert _num(None, default=None) is None


class TestNumericRulesDoNotCrashOnLocaleStrings:
    """E-I18N-004: German-format strings must not become 8 fake ERRORs."""

    @pytest.mark.asyncio
    async def test_german_numbers_produce_no_engine_errors(self) -> None:
        if not rule_registry.get_rule("boq_quality.position_has_quantity"):
            register_builtin_rules()
        data = {
            "positions": [
                {
                    "id": "p1",
                    "ordinal": "01.01",
                    "description": "Stahlbetonwand",
                    "unit": "m2",
                    "quantity": "1.234,56",
                    "unit_rate": "150,00",
                    "total": "185.184,00",
                    "classification": {"din276": "330"},
                    "currency": "EUR",
                }
            ]
        }
        report = await validation_engine.validate(data=data, rule_sets=["boq_quality"])
        assert report.engine_errors == []
        # quantity/rate parse fine → those completeness rules pass.
        bad = {r.rule_id for r in report.results if not r.passed and not r.is_engine_error}
        assert "boq_quality.position_has_quantity" not in bad
        assert "boq_quality.position_has_unit_rate" not in bad
        assert "boq_quality.total_mismatch" not in bad
        assert "boq_quality.negative_values" not in bad


class TestMedian:
    def test_even_list_is_mean_of_two_central(self) -> None:
        assert _median([10, 20, 30, 40]) == 25.0  # not 30 (upper-middle)

    def test_odd_list(self) -> None:
        assert _median([10, 20, 30]) == 20

    def test_empty(self) -> None:
        assert _median([]) == 0.0

    @pytest.mark.asyncio
    async def test_unit_rate_in_range_uses_true_median(self) -> None:
        ctx = ValidationContext(
            data={
                "positions": [{"id": str(i), "ordinal": str(i), "unit_rate": v} for i, v in enumerate([10, 20, 30, 40])]
            }
        )
        results = await UnitRateInRange().validate(ctx)
        assert results
        assert results[0].details["median"] == 25.0
        assert results[0].details["threshold"] == 125.0


class TestTotalMismatchTolerance:
    @pytest.mark.asyncio
    async def test_float_noise_within_absolute_floor_passes(self) -> None:
        ctx = ValidationContext(
            data={"positions": [{"id": "p", "ordinal": "1", "quantity": 0.1, "unit_rate": 0.2, "total": 0.02}]}
        )
        r = await TotalMismatch().validate(ctx)
        assert r[0].passed is True

    @pytest.mark.asyncio
    async def test_large_value_systematic_drift_is_flagged(self) -> None:
        # 2,000,000 stored, off by 5.0 — absolute 0.01 would have missed it,
        # the magnitude-aware tolerance (~2.0) catches it (E-VAL-014).
        ctx = ValidationContext(
            data={
                "positions": [{"id": "p", "ordinal": "1", "quantity": 1000.0, "unit_rate": 2000.0, "total": 2000005.0}]
            }
        )
        r = await TotalMismatch().validate(ctx)
        assert r[0].passed is False
        assert r[0].details["tolerance"] > 0.01

    @pytest.mark.asyncio
    async def test_locale_string_total_does_not_crash(self) -> None:
        ctx = ValidationContext(
            data={
                "positions": [
                    {"id": "p", "ordinal": "1", "quantity": "1.234,56", "unit_rate": "150,00", "total": "185.184,00"}
                ]
            }
        )
        r = await TotalMismatch().validate(ctx)
        assert r[0].passed is True  # 1234.56 * 150 == 185184.0
