# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Decimal-exact EVM metric kernel.

The maths here is the reason the module exists, so every expected value below
is worked out by hand from the standard formulas rather than read back from the
implementation. A test that only asserts "some number came out" would pass just
as happily against a wrong CPI, which is the failure this suite is built to
catch: a CPI that is quietly too high reports an overspending project as
healthy, and nothing downstream ever questions it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.full_evm.metrics import (
    DEFAULT_MONEY_QUANTUM,
    EAC_FALLBACK_LADDER,
    EAC_METHODS,
    MAX_MINOR_UNITS,
    compute_metrics,
    eac_variants,
    quantize_ratio,
    quantum_for_minor_units,
    to_decimal,
)

# A project half way through: 1.0m budget, 550k planned, 500k earned, 520k spent.
# Behind schedule (EV < PV) and over budget (AC > EV).
_BAC = "1000000"
_PV = "550000"
_EV = "500000"
_AC = "520000"


# ── Performance indices ──────────────────────────────────────────────────────


def test_cpi_and_spi_match_the_definitions() -> None:
    """CPI is EV/AC and SPI is EV/PV, to six decimal places."""
    metrics = compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac=_AC)

    # 500000 / 520000 = 0.9615384615..., 500000 / 550000 = 0.9090909090...
    assert metrics.cpi == Decimal("0.961538")
    assert metrics.spi == Decimal("0.909091")


def test_variances_are_exact_money_subtractions() -> None:
    """SV is EV-PV and CV is EV-AC; both are always defined."""
    metrics = compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac=_AC)

    assert metrics.sv == Decimal("-50000.00")
    assert metrics.cv == Decimal("-20000.00")


def test_percent_complete_and_spent_are_fractions_of_the_budget() -> None:
    """Percent complete is EV/BAC and percent spent is AC/BAC."""
    metrics = compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac=_AC)

    assert metrics.percent_complete == Decimal("0.500000")
    assert metrics.percent_spent == Decimal("0.520000")


# ── EAC variants: the three standard formulas disagree, on purpose ───────────


def test_all_three_eac_variants_are_reported_side_by_side() -> None:
    """Each variant is computed from its own formula and none is hidden.

    remaining = AC + (BAC - EV)             = 520000 + 500000 = 1020000
    cpi       = BAC / CPI                    = 1000000 / (500000/520000) = 1040000
    combined  = AC + (BAC-EV) / (CPI * SPI)  = 520000 + 500000 / 0.87412587 = 1092000
    """
    variants = eac_variants(
        bac=Decimal(_BAC),
        pv=Decimal(_PV),
        ev=Decimal(_EV),
        ac=Decimal(_AC),
    )

    assert variants["remaining"] == Decimal("1020000.00")
    assert variants["cpi"] == Decimal("1040000.00")
    assert variants["combined"] == Decimal("1092000.00")
    # They genuinely differ - the point of reporting all three.
    assert len({variants["remaining"], variants["cpi"], variants["combined"]}) == 3


def test_eac_cpi_is_not_computed_through_the_rounded_index() -> None:
    """EAC on the cost trend uses exact money terms, not the stored CPI.

    The stored CPI is rounded to six decimals. Dividing BAC by that rounded
    number gives a different answer from the algebraically identical
    ``BAC * AC / EV``, and on a large budget the difference is real money. This
    is the guarantee that a rounded index can never move a forecast.
    """
    bac, ev, ac = Decimal("7000000"), Decimal("2345678"), Decimal("2600000")
    metrics = compute_metrics(bac=bac, pv="3000000", ev=ev, ac=ac, method="cpi")

    exact = (bac * ac / ev).quantize(DEFAULT_MONEY_QUANTUM)
    assert metrics.eac == exact

    naive = (bac / metrics.cpi).quantize(DEFAULT_MONEY_QUANTUM)
    assert naive != exact, "the rounded-index route must actually differ, or this test proves nothing"


def test_combined_variant_uses_both_indices() -> None:
    """The combined EAC changes when only the schedule index changes.

    Same cost picture, worse schedule: if the combined formula were quietly
    ignoring SPI it would return the cost-only number instead.
    """
    on_plan = compute_metrics(bac=_BAC, pv=_EV, ev=_EV, ac=_AC, method="combined")
    behind = compute_metrics(bac=_BAC, pv="800000", ev=_EV, ac=_AC, method="combined")

    assert on_plan.spi == Decimal("1.000000")
    assert behind.eac > on_plan.eac


# ── ETC, VAC, TCPI ───────────────────────────────────────────────────────────


def test_etc_and_vac_follow_from_the_selected_eac() -> None:
    """ETC is EAC-AC and VAC is BAC-EAC, against whichever EAC was selected."""
    metrics = compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac=_AC, method="cpi")

    assert metrics.eac == Decimal("1040000.00")
    assert metrics.etc == Decimal("520000.00")
    assert metrics.vac == Decimal("-40000.00")


def test_tcpi_to_budget_and_to_forecast_are_both_reported() -> None:
    """TCPI to BAC is (BAC-EV)/(BAC-AC); TCPI to EAC is (BAC-EV)/(EAC-AC)."""
    metrics = compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac=_AC, method="cpi")

    # 500000 / 480000 = 1.0416666..., 500000 / 520000 = 0.9615384...
    assert metrics.tcpi_bac == Decimal("1.041667")
    assert metrics.tcpi_eac == Decimal("0.961538")


def test_negative_vac_means_forecast_overrun() -> None:
    """A project forecast over budget reports a negative VAC, not an absolute gap."""
    metrics = compute_metrics(bac="100000", pv="60000", ev="50000", ac="70000", method="cpi")

    assert metrics.vac is not None
    assert metrics.vac < 0


# ── Division-by-zero: undefined is None, never zero ──────────────────────────


def test_zero_actual_cost_leaves_cpi_undefined_not_zero() -> None:
    """Before any spend CPI has no denominator, so it is None.

    Zero would read as "no value earned per unit spent", which is the worst
    possible efficiency, for a project that is merely new.
    """
    metrics = compute_metrics(bac="500000", pv="0", ev="0", ac="0")

    assert metrics.cpi is None
    assert metrics.spi is None


def test_zero_planned_value_leaves_spi_undefined() -> None:
    """SPI is undefined while nothing was scheduled to be done yet."""
    metrics = compute_metrics(bac="500000", pv="0", ev="10000", ac="12000")

    assert metrics.spi is None
    assert metrics.cpi is not None


def test_tcpi_to_budget_is_undefined_when_the_budget_is_exactly_consumed() -> None:
    """BAC == AC makes the TCPI denominator zero, so it is None, not infinity."""
    metrics = compute_metrics(bac="100000", pv="90000", ev="60000", ac="100000", method="remaining")

    assert metrics.tcpi_bac is None


def test_tcpi_to_forecast_is_undefined_when_no_further_spend_is_forecast() -> None:
    """EAC == AC leaves nothing to divide by, so TCPI to EAC is None."""
    metrics = compute_metrics(bac="100000", pv="100000", ev="100000", ac="100000", method="remaining")

    assert metrics.eac == Decimal("100000.00")
    assert metrics.tcpi_eac is None


# ── Method selection and provenance ──────────────────────────────────────────


def test_auto_prefers_the_richest_computable_variant() -> None:
    """With all inputs present ``auto`` resolves to ``combined``."""
    metrics = compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac=_AC, method="auto")

    assert metrics.eac_method_requested == "auto"
    assert metrics.eac_method_effective == "combined"
    assert metrics.eac == Decimal("1092000.00")


def test_auto_degrades_to_remaining_before_anything_is_earned() -> None:
    """With EV zero the trend variants are undefined, so ``remaining`` runs."""
    metrics = compute_metrics(bac="400000", pv="50000", ev="0", ac="0", method="auto")

    assert metrics.eac_method_effective == "remaining"
    assert metrics.eac == Decimal("400000.00")


def test_a_named_method_that_cannot_run_says_which_one_did() -> None:
    """Requesting ``cpi`` on a project with no earned value records the fallback.

    This is the provenance guarantee: the row asks for one formula, another
    one produces the number, and both names survive. Reporting the requested
    name alone would claim a cost-trend forecast that was never computed.
    """
    metrics = compute_metrics(bac="400000", pv="50000", ev="0", ac="1000", method="cpi")

    assert metrics.eac_method_requested == "cpi"
    assert metrics.eac_method_effective == "remaining"


def test_unknown_method_is_rejected_rather_than_defaulted() -> None:
    """An unrecognised formula name raises instead of silently picking one."""
    with pytest.raises(ValueError, match="Unknown EAC method"):
        compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac=_AC, method="banana")


def test_supported_method_names_come_from_the_shared_vocabulary() -> None:
    """The kernel speaks the same EAC vocabulary as the rest of the platform."""
    assert set(EAC_METHODS) == {"auto", "remaining", "cpi", "combined"}


# ── Input hygiene ────────────────────────────────────────────────────────────


def test_float_input_does_not_smuggle_in_binary_noise() -> None:
    """A float amount is routed through str, so 0.1 stays 0.1."""
    assert to_decimal(0.1) == Decimal("0.1")


def test_non_finite_amounts_are_rejected() -> None:
    """NaN and infinity must never reach the register."""
    for bad in ("NaN", "Infinity", "-Infinity", float("inf")):
        with pytest.raises(ValueError, match="finite"):
            to_decimal(bad, field="BAC")


def test_non_numeric_amounts_are_rejected_with_a_usable_message() -> None:
    """A bad amount names the field it came from."""
    with pytest.raises(ValueError, match="BAC is not a valid amount"):
        to_decimal("banana", field="BAC")


def test_negative_cumulative_money_is_rejected_not_clamped() -> None:
    """A negative total is a data fault; clamping it would produce a plausible lie."""
    with pytest.raises(ValueError, match="AC cannot be negative"):
        compute_metrics(bac=_BAC, pv=_PV, ev=_EV, ac="-1")


def test_missing_amount_reads_as_zero() -> None:
    """``None`` is the meaningful default for an unreported cumulative total."""
    assert to_decimal(None) == Decimal("0")


# ── Currency neutrality ──────────────────────────────────────────────────────


def test_zero_decimal_currency_rounds_to_whole_units() -> None:
    """A currency with no minor unit gets whole-unit amounts, not forced cents."""
    quantum = quantum_for_minor_units(0)
    metrics = compute_metrics(bac="1000000", pv="500000", ev="450000", ac="470000", quantum=quantum)

    assert quantum == Decimal("1")
    assert metrics.eac == metrics.eac.quantize(Decimal("1"))


def test_three_decimal_currency_keeps_its_third_place() -> None:
    """A three-decimal currency is stored exactly, not pre-rounded to cents."""
    quantum = quantum_for_minor_units(3)
    assert quantum == Decimal("0.001")

    metrics = compute_metrics(bac="1000.000", pv="500.000", ev="333.333", ac="400.000", quantum=quantum)
    assert metrics.eac is not None
    assert metrics.eac.as_tuple().exponent == -3


def test_minor_unit_count_outside_the_storable_range_is_rejected() -> None:
    """A precision the column cannot hold is an error, not a silent truncation."""
    with pytest.raises(ValueError, match="minor_units"):
        quantum_for_minor_units(MAX_MINOR_UNITS + 1)
    with pytest.raises(ValueError, match="minor_units"):
        quantum_for_minor_units(-1)


# ── Serialisation ────────────────────────────────────────────────────────────


def test_to_dict_emits_money_as_strings_and_undefined_as_none() -> None:
    """JSON gets exact strings for amounts and ``null`` for undefined indices."""
    payload = compute_metrics(bac="100000", pv="0", ev="0", ac="0").to_dict()

    assert payload["bac"] == "100000.00"
    assert payload["cpi"] is None
    assert payload["spi"] is None
    assert payload["eac_variants"]["cpi"] is None
    assert payload["eac_variants"]["remaining"] == "100000.00"


def test_ratio_quantisation_passes_none_through() -> None:
    """Rounding an undefined index keeps it undefined."""
    assert quantize_ratio(None) is None
    assert quantize_ratio(Decimal("1.23456789")) == Decimal("1.234568")


# ── Degradation ladder ───────────────────────────────────────────────────────


def test_combined_degrades_to_the_cost_trend_not_straight_to_remaining() -> None:
    """With PV = 0 the combined formula cannot run but the cost trend still can.

    Skipping past ``cpi`` to ``remaining`` would answer the same question two
    ways inside one module: the legacy forecast path walks combined -> cpi ->
    remaining, so the register has to walk it too or identical inputs produce
    two different EACs depending on which surface asked.
    """
    metrics = compute_metrics(bac="1000000", pv="0", ev="500000", ac="520000", method="combined")

    assert metrics.eac_method_requested == "combined"
    assert metrics.eac_method_effective == "cpi"
    # BAC * AC / EV = 1000000 * 520000 / 500000
    assert metrics.eac == Decimal("1040000.00")


def test_a_named_method_never_degrades_upwards_into_a_richer_formula() -> None:
    """Asking for the cost trend cannot silently return the combined index.

    Degradation only ever moves towards simpler formulas. A caller who chose
    ``cpi`` deliberately excluded the schedule term, so reintroducing it would
    contradict the request rather than rescue it.
    """
    assert EAC_FALLBACK_LADDER["cpi"] == ("cpi", "remaining")
    assert "combined" not in EAC_FALLBACK_LADDER["cpi"]
    assert EAC_FALLBACK_LADDER["remaining"] == ("remaining",)

    # Every rung must terminate at the one formula that needs no division.
    for requested, ladder in EAC_FALLBACK_LADDER.items():
        assert ladder[-1] == "remaining", f"{requested} can fail to resolve"


def test_every_supported_method_has_a_ladder() -> None:
    """A method the kernel accepts but cannot resolve would raise a KeyError."""
    assert set(EAC_FALLBACK_LADDER) == set(EAC_METHODS)
