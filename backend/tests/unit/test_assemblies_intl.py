"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the database-free international assembly helpers.

These tests exercise ``app.modules.assemblies.intl`` in isolation - no
database, no ORM, no locale. They lock the international guarantees:

* Money is Decimal-exact (no IEEE-754 drift).
* No hardcoded currency; a mixed-currency sum is a clean error, never a
  meaningless total.
* The regional factor defaults to 1.0 (no adjustment) worldwide.
* The waste / overhead uplift defaults to 0 (no extra).
* Edge cases (empty lists, zero / negative / missing / non-finite inputs,
  division by zero) surface as ``ValueError`` or well-defined zeros, never a
  ``NaN`` / ``inf`` or an unhandled crash.
* The composite rate is explainable via a per-component breakdown that sums
  back to the composite total.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.assemblies.intl import (
    DEFAULT_REGIONAL_FACTOR,
    DEFAULT_WASTE_PCT,
    ComponentLine,
    apply_waste_uplift,
    build_composite_rate,
    component_line_total,
    composite_rate_breakdown,
    composite_rate_from_components,
    explain_concept,
    label_status,
    regional_adjusted_rate,
    unit_rate_from_total,
)

# ── Documented worldwide defaults ─────────────────────────────────────────────


def test_default_regional_factor_is_one():
    """The worldwide default regional factor is exactly 1.0 (no adjustment)."""
    assert Decimal("1") == DEFAULT_REGIONAL_FACTOR


def test_default_waste_pct_is_zero():
    """The default waste / overhead uplift is 0 percent (no extra)."""
    assert Decimal("0") == DEFAULT_WASTE_PCT


# ── component_line_total: exact, guarded ──────────────────────────────────────


@pytest.mark.parametrize(
    ("factor", "unit_rate", "expected"),
    [
        (1, 100, "100"),
        ("0.12", "750", "90.00"),  # rebar factor - exact, no 0.09999 drift
        (4.5, 18, "81.0"),
        (0, 200, "0"),  # disabled line (factor zero) -> well-defined zero
        (1, 0, "0"),  # free line (rate zero) -> well-defined zero
        ("2.5", "4", "10.0"),
    ],
)
def test_component_line_total_exact(factor, unit_rate, expected):
    """factor * unit_rate is computed exactly as Decimal."""
    assert component_line_total(factor, unit_rate) == Decimal(expected)


def test_component_line_total_is_decimal_exact_on_float_inputs():
    """0.12 * 750 must be exactly 90, never 89.9999..."""
    assert component_line_total(0.12, 750.0) == Decimal("90.00")


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_component_line_total_rejects_non_finite(bad):
    """inf / -inf / nan inputs raise ValueError, never return NaN / inf."""
    with pytest.raises(ValueError, match="finite"):
        component_line_total(bad, 10)
    with pytest.raises(ValueError, match="finite"):
        component_line_total(1, bad)


def test_component_line_total_rejects_negative():
    """A negative factor or rate is a clean input error."""
    with pytest.raises(ValueError, match="negative"):
        component_line_total(-1, 10)
    with pytest.raises(ValueError, match="negative"):
        component_line_total(1, -10)


def test_component_line_total_rejects_missing_rate():
    """A missing (None) rate is a clean input error, not a silent zero."""
    with pytest.raises(ValueError, match="required"):
        component_line_total(1, None)


def test_component_line_total_rejects_garbage_string():
    """Non-numeric text raises ValueError rather than crashing."""
    with pytest.raises(ValueError, match="not a valid number"):
        component_line_total("abc", 10)


# ── composite_rate_from_components ────────────────────────────────────────────


def test_composite_rate_concrete_wall_exact():
    """RC wall: 1*95 + 0.12*750 + 4.5*18 = 95 + 90 + 81 = 266, exact."""
    components = [
        {"description": "Concrete C30/37", "unit": "m3", "factor": 1.0, "unit_rate": "95.00"},
        {"description": "Rebar B500B", "unit": "t", "factor": 0.12, "unit_rate": "750.00"},
        {"description": "Formwork", "unit": "m2", "factor": 4.5, "unit_rate": "18.00"},
    ]
    assert composite_rate_from_components(components) == Decimal("266.00")


def test_composite_rate_empty_list_is_zero():
    """An empty component list is a well-defined zero, not an error."""
    assert composite_rate_from_components([]) == Decimal("0")


def test_composite_rate_accepts_component_line_objects():
    """ComponentLine dataclass instances work like dicts."""
    components = [
        ComponentLine(factor=2, unit_rate=10, unit="m"),
        ComponentLine(factor=1, unit_rate="5.5", unit="m"),
    ]
    assert composite_rate_from_components(components) == Decimal("25.5")


def test_composite_rate_reads_unit_cost_alias():
    """The ORM's ``unit_cost`` field name is accepted as the rate."""
    components = [{"factor": 1, "unit_cost": "42", "unit": "m"}]
    assert composite_rate_from_components(components) == Decimal("42")


# ── Never sum across currency codes ───────────────────────────────────────────


def test_composite_rate_rejects_mixed_currencies():
    """Two different currency codes cannot be summed - clean ValueError."""
    components = [
        {"factor": 1, "unit_rate": 100, "unit": "m", "currency": "EUR"},
        {"factor": 1, "unit_rate": 100, "unit": "m", "currency": "USD"},
    ]
    with pytest.raises(ValueError, match="currenc"):
        composite_rate_from_components(components)


def test_composite_rate_rejects_component_conflicting_expected_currency():
    """A component currency that differs from expected_currency is rejected."""
    components = [{"factor": 1, "unit_rate": 100, "unit": "m", "currency": "USD"}]
    with pytest.raises(ValueError, match="currenc"):
        composite_rate_from_components(components, expected_currency="EUR")


def test_composite_rate_same_currency_ok():
    """Consistent currency codes sum without complaint."""
    components = [
        {"factor": 1, "unit_rate": 100, "unit": "m", "currency": "eur"},
        {"factor": 2, "unit_rate": 50, "unit": "m", "currency": "EUR "},
    ]
    assert composite_rate_from_components(components) == Decimal("200")


def test_composite_rate_currency_agnostic_when_none_stated():
    """No currency stated anywhere still computes (currency is optional data)."""
    components = [{"factor": 3, "unit_rate": 10, "unit": "kg"}]
    assert composite_rate_from_components(components) == Decimal("30")


# ── Explainable breakdown ─────────────────────────────────────────────────────


def test_breakdown_sums_back_to_composite_rate():
    """The per-component line totals sum to the composite rate (checkable)."""
    components = [
        {"description": "a", "unit": "m", "factor": 1, "unit_rate": "95"},
        {"description": "b", "unit": "t", "factor": "0.12", "unit_rate": "750"},
        {"description": "c", "unit": "m2", "factor": "4.5", "unit_rate": "18"},
    ]
    rows = composite_rate_breakdown(components)
    assert len(rows) == 3
    summed = sum((row["line_total"] for row in rows), Decimal("0"))
    assert summed == composite_rate_from_components(components)
    assert rows[0]["unit"] == "m"
    assert rows[1]["line_total"] == Decimal("90.00")


def test_breakdown_backfills_resolved_currency():
    """A row without its own currency inherits the single resolved currency."""
    components = [
        {"factor": 1, "unit_rate": 10, "unit": "m", "currency": "GBP"},
        {"factor": 1, "unit_rate": 20, "unit": "m"},  # no currency stated
    ]
    rows = composite_rate_breakdown(components)
    assert rows[0]["currency"] == "GBP"
    assert rows[1]["currency"] == "GBP"


# ── regional_adjusted_rate ────────────────────────────────────────────────────


def test_regional_default_leaves_rate_unchanged():
    """The default regional factor (1.0) returns the base rate unchanged."""
    assert regional_adjusted_rate("266.00") == Decimal("266.00")


def test_regional_factor_applies_exactly():
    """266 * 1.12 = 297.92, exact."""
    assert regional_adjusted_rate("266.00", "1.12") == Decimal("297.9200")


def test_regional_rate_rejects_negative_factor():
    """A negative regional factor is a clean input error."""
    with pytest.raises(ValueError, match="negative"):
        regional_adjusted_rate(100, -1)


def test_regional_rate_rejects_non_finite():
    """Infinity / NaN factors raise rather than poison the rate."""
    with pytest.raises(ValueError, match="finite"):
        regional_adjusted_rate(100, float("inf"))


# ── apply_waste_uplift ────────────────────────────────────────────────────────


def test_waste_default_is_no_op():
    """The default waste percentage (0) returns the rate unchanged."""
    assert apply_waste_uplift("100") == Decimal("100")


def test_waste_uplift_applies_exactly():
    """100 with 10 percent waste = 110, exact."""
    assert apply_waste_uplift("100", 10) == Decimal("110.0")


def test_waste_uplift_rejects_negative_pct():
    """A negative waste percentage is a clean input error."""
    with pytest.raises(ValueError, match="negative"):
        apply_waste_uplift(100, -5)


# ── unit_rate_from_total (division-by-zero guard) ─────────────────────────────


def test_unit_rate_from_total_exact():
    """1000 spread over 4 units = 250 per unit, exact."""
    assert unit_rate_from_total("1000", 4) == Decimal("250")


def test_unit_rate_from_total_zero_quantity_raises():
    """Dividing by a zero quantity is a clean ValueError, not a crash."""
    with pytest.raises(ValueError, match="greater than zero"):
        unit_rate_from_total(1000, 0)


def test_unit_rate_from_total_negative_quantity_raises():
    """A negative quantity is rejected too."""
    with pytest.raises(ValueError, match="greater than zero"):
        unit_rate_from_total(1000, -2)


# ── build_composite_rate: full explained pipeline ────────────────────────────


def test_build_composite_rate_full_pipeline_exact():
    """subtotal -> regional -> waste, all exact and exposed for checking."""
    components = [
        {"description": "Concrete", "unit": "m3", "factor": 1, "unit_rate": "95", "currency": "EUR"},
        {"description": "Rebar", "unit": "t", "factor": "0.12", "unit_rate": "750", "currency": "EUR"},
        {"description": "Formwork", "unit": "m2", "factor": "4.5", "unit_rate": "18", "currency": "EUR"},
    ]
    result = build_composite_rate(components, regional_factor="1.10", waste_pct="5")
    assert result["currency"] == "EUR"
    assert result["subtotal"] == Decimal("266.00")
    # 266 * 1.10 = 292.60
    assert result["regional_adjusted"] == Decimal("292.6000")
    # 292.60 * 1.05 = 307.23
    assert result["unit_rate"] == Decimal("307.230000")
    assert len(result["components"]) == 3


def test_build_composite_rate_defaults_are_neutral():
    """With default factor and waste, unit_rate equals the subtotal."""
    components = [{"factor": 1, "unit_rate": "266", "unit": "m3"}]
    result = build_composite_rate(components)
    assert result["subtotal"] == Decimal("266")
    assert result["regional_adjusted"] == Decimal("266")
    assert result["unit_rate"] == Decimal("266")
    assert result["currency"] is None


def test_build_composite_rate_empty_is_zero():
    """An empty assembly builds a zero rate without error."""
    result = build_composite_rate([])
    assert result["subtotal"] == Decimal("0")
    assert result["unit_rate"] == Decimal("0")


def test_build_composite_rate_rejects_mixed_currency():
    """Mixed currencies fail fast in the full pipeline too."""
    components = [
        {"factor": 1, "unit_rate": 1, "unit": "m", "currency": "EUR"},
        {"factor": 1, "unit_rate": 1, "unit": "m", "currency": "JPY"},
    ]
    with pytest.raises(ValueError, match="currenc"):
        build_composite_rate(components)


# ── Plain-language glossary and status labels ─────────────────────────────────


@pytest.mark.parametrize(
    "concept",
    ["component_factor", "composite_rate", "regional_factor", "waste_allowance"],
)
def test_explain_concept_returns_nonempty(concept):
    """Every documented concept has a one-line explanation."""
    text = explain_concept(concept)
    assert text
    assert len(text) > 10


def test_explain_concept_is_case_insensitive():
    """Concept lookup ignores case and surrounding whitespace."""
    assert explain_concept("  Regional_Factor ") == explain_concept("regional_factor")


def test_explain_concept_unknown_is_empty():
    """An unknown concept returns an empty string, not an error."""
    assert explain_concept("does_not_exist") == ""


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("pending", "Not checked yet"),
        ("passed", "All checks passed"),
        ("warnings", "Passed, with warnings to review"),
        ("errors", "Has errors to fix"),
    ],
)
def test_label_status_plain_language(code, expected):
    """Status codes map to clear, jargon-free labels."""
    assert label_status(code) == expected


def test_label_status_unknown_is_safe():
    """An unknown status code degrades to a safe label, never raises."""
    assert label_status("brand_new_code") == "Unknown status"
    assert label_status(None) == "Unknown status"
