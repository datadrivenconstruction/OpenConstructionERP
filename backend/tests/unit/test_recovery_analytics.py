# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure recovery-performance analytics engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Money is
exercised exclusively with Decimal literals; rates are checked as exact Decimal
fractions in [0, 1].
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.cost_recovery.recovery_analytics import (
    ABSORBED_STATUSES,
    BAND_MODERATE,
    BAND_STRONG,
    BAND_WEAK,
    CLOSED_STATUSES,
    COHORT_HIGH,
    COHORT_LOW,
    DEFAULT_BAND,
    HIGH_BANDS,
    LOW_BANDS,
    OPEN_STATUSES,
    RATEPLACES,
    STATUS_ABSORBED,
    STATUS_AGREED,
    STATUS_DISPUTED,
    STATUS_PROPOSED,
    STATUS_RECOVERED,
    STATUS_WAIVED,
    TRACEABILITY_BANDS,
    CohortRecovery,
    CurrencyRecovery,
    RecoveryItem,
    RecoveryPerformance,
    cohort_for,
    compute_recovery_performance,
    normalise_band,
    quantize_money,
    quantize_rate,
    recovery_rate,
)


def _item(
    chargeable: Decimal = Decimal("1000.00"),
    recovered: Decimal = Decimal("0"),
    currency: str = "USD",
    traceability_band: str = BAND_STRONG,
    status: str = STATUS_AGREED,
) -> RecoveryItem:
    """Build a RecoveryItem with sensible defaults for a single test."""
    return RecoveryItem(
        chargeable=chargeable,
        recovered=recovered,
        currency=currency,
        traceability_band=traceability_band,
        status=status,
    )


def _by_cur(perf: RecoveryPerformance, currency: str) -> CurrencyRecovery:
    return next(r for r in perf.by_currency if r.currency == currency)


def _cohort(row: CurrencyRecovery, cohort: str) -> CohortRecovery | None:
    return next((c for c in row.by_cohort if c.cohort == cohort), None)


def _band(row: CurrencyRecovery, band: str) -> CohortRecovery | None:
    return next((c for c in row.by_band if c.cohort == band), None)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_status_sets_partition() -> None:
    assert frozenset({STATUS_PROPOSED, STATUS_AGREED, STATUS_DISPUTED}) == OPEN_STATUSES
    assert frozenset({STATUS_WAIVED, STATUS_ABSORBED}) == ABSORBED_STATUSES
    assert frozenset({STATUS_RECOVERED, STATUS_WAIVED, STATUS_ABSORBED}) == CLOSED_STATUSES
    assert OPEN_STATUSES.isdisjoint(CLOSED_STATUSES)
    assert ABSORBED_STATUSES <= CLOSED_STATUSES


def test_band_vocabulary_and_cohort_cut() -> None:
    assert TRACEABILITY_BANDS == (BAND_STRONG, BAND_MODERATE, BAND_WEAK)
    # The documented cut: only strong is HIGH; moderate + weak are LOW.
    assert frozenset({BAND_STRONG}) == HIGH_BANDS
    assert frozenset({BAND_MODERATE, BAND_WEAK}) == LOW_BANDS
    assert HIGH_BANDS.isdisjoint(LOW_BANDS)
    assert set(TRACEABILITY_BANDS) == HIGH_BANDS | LOW_BANDS
    assert DEFAULT_BAND == BAND_WEAK


# ---------------------------------------------------------------------------
# normalise_band / cohort_for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("strong", BAND_STRONG),
        ("moderate", BAND_MODERATE),
        ("weak", BAND_WEAK),
        ("STRONG", BAND_STRONG),
        ("  Moderate  ", BAND_MODERATE),
        ("", DEFAULT_BAND),
        ("   ", DEFAULT_BAND),
        ("bogus", DEFAULT_BAND),
        ("high", DEFAULT_BAND),  # not a band name; only weak/moderate/strong are
    ],
)
def test_normalise_band(raw: str, expected: str) -> None:
    assert normalise_band(raw) == expected


@pytest.mark.parametrize(
    ("band", "expected"),
    [
        (BAND_STRONG, COHORT_HIGH),
        (BAND_MODERATE, COHORT_LOW),
        (BAND_WEAK, COHORT_LOW),
        ("STRONG", COHORT_HIGH),
        ("", COHORT_LOW),  # blank -> weak -> low
        ("garbage", COHORT_LOW),
    ],
)
def test_cohort_for(band: str, expected: str) -> None:
    assert cohort_for(band) == expected


# ---------------------------------------------------------------------------
# recovery_rate (rate math + divide-by-zero)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("recovered", "chargeable", "expected"),
    [
        (Decimal("690"), Decimal("1000"), Decimal("0.6900")),  # the headline 69%
        (Decimal("0"), Decimal("1000"), Decimal("0.0000")),  # entitled, recovered nothing
        (Decimal("1000"), Decimal("1000"), Decimal("1.0000")),  # full recovery
        (Decimal("1"), Decimal("3"), Decimal("0.3333")),  # 1/3 quantized half-up
        (Decimal("2"), Decimal("3"), Decimal("0.6667")),  # 2/3 quantized half-up
        (Decimal("350"), Decimal("1000"), Decimal("0.3500")),  # the report's 35% foil
    ],
)
def test_recovery_rate_math(recovered: Decimal, chargeable: Decimal, expected: Decimal) -> None:
    assert recovery_rate(recovered, chargeable) == expected


def test_recovery_rate_divide_by_zero_is_none() -> None:
    # No entitlement -> undefined ratio -> None, never 0.
    assert recovery_rate(Decimal("0"), Decimal("0")) is None
    assert recovery_rate(Decimal("100"), Decimal("0")) is None


def test_recovery_rate_negative_chargeable_is_none() -> None:
    assert recovery_rate(Decimal("0"), Decimal("-50")) is None


def test_recovery_rate_clamps_over_recovery_to_one() -> None:
    # An over-recovery on the raw inputs cannot report a rate above 100%.
    assert recovery_rate(Decimal("1500"), Decimal("1000")) == Decimal("1.0000")


def test_recovery_rate_clamps_negative_recovery_to_zero() -> None:
    assert recovery_rate(Decimal("-10"), Decimal("1000")) == Decimal("0.0000")


def test_recovery_rate_is_a_fraction_not_percent() -> None:
    # 0.69, not 69 - documented rate form.
    rate = recovery_rate(Decimal("69"), Decimal("100"))
    assert rate == Decimal("0.6900")
    assert rate < Decimal("1")


# ---------------------------------------------------------------------------
# quantize helpers
# ---------------------------------------------------------------------------


def test_quantize_money_half_up() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")


def test_quantize_rate_half_up_four_places() -> None:
    assert quantize_rate(Decimal("0.66665")) == Decimal("0.6667")
    assert quantize_rate(Decimal("0.66664")) == Decimal("0.6666")
    assert Decimal("0.0001") == RATEPLACES


# ---------------------------------------------------------------------------
# RecoveryItem properties
# ---------------------------------------------------------------------------


def test_item_band_and_cohort_properties() -> None:
    assert _item(traceability_band="STRONG").band == BAND_STRONG
    assert _item(traceability_band="STRONG").cohort == COHORT_HIGH
    assert _item(traceability_band="moderate").cohort == COHORT_LOW
    assert _item(traceability_band="").band == DEFAULT_BAND
    assert _item(traceability_band="").cohort == COHORT_LOW


def test_item_clamped_chargeable_floors_negative() -> None:
    assert _item(chargeable=Decimal("-5")).clamped_chargeable == Decimal("0")
    assert _item(chargeable=Decimal("100")).clamped_chargeable == Decimal("100")


def test_item_clamped_recovered_bounds() -> None:
    # Negative -> 0; over-recovery -> capped at chargeable.
    assert _item(chargeable=Decimal("100"), recovered=Decimal("-1")).clamped_recovered == Decimal("0")
    assert _item(chargeable=Decimal("100"), recovered=Decimal("250")).clamped_recovered == Decimal("100")
    assert _item(chargeable=Decimal("100"), recovered=Decimal("40")).clamped_recovered == Decimal("40")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (STATUS_WAIVED, True),
        (STATUS_ABSORBED, True),
        (STATUS_AGREED, False),
        (STATUS_PROPOSED, False),
        (STATUS_DISPUTED, False),
        (STATUS_RECOVERED, False),
    ],
)
def test_item_is_absorbed(status: str, expected: bool) -> None:
    assert _item(status=status).is_absorbed is expected


def test_item_absorbed_amount_only_when_absorbed() -> None:
    # Open / recovered items absorb nothing.
    assert _item(chargeable=Decimal("100"), status=STATUS_AGREED).absorbed_amount == Decimal("0")
    assert _item(chargeable=Decimal("100"), status=STATUS_RECOVERED).absorbed_amount == Decimal("0")


def test_item_absorbed_amount_is_uncollected_remainder() -> None:
    # Waived after collecting 30 of 100 -> 70 absorbed.
    item = _item(chargeable=Decimal("100"), recovered=Decimal("30"), status=STATUS_WAIVED)
    assert item.absorbed_amount == Decimal("70")
    # Fully waived with nothing collected -> whole charge absorbed.
    item2 = _item(chargeable=Decimal("100"), recovered=Decimal("0"), status=STATUS_ABSORBED)
    assert item2.absorbed_amount == Decimal("100")


# ---------------------------------------------------------------------------
# compute_recovery_performance - empty
# ---------------------------------------------------------------------------


def test_compute_empty_input() -> None:
    perf = compute_recovery_performance([])
    assert isinstance(perf, RecoveryPerformance)
    assert perf.item_count == 0
    assert perf.primary_currency == ""
    assert perf.primary_rate is None
    assert perf.by_currency == ()


# ---------------------------------------------------------------------------
# compute_recovery_performance - overall rate + totals
# ---------------------------------------------------------------------------


def test_compute_overall_rate_and_totals() -> None:
    items = [
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("600.00"), status=STATUS_DISPUTED),
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("780.00"), status=STATUS_AGREED),
    ]
    perf = compute_recovery_performance(items)
    usd = _by_cur(perf, "USD")
    assert usd.item_count == 2
    assert usd.chargeable_total == Decimal("2000.00")
    assert usd.recovered_total == Decimal("1380.00")
    # 1380 / 2000 = 0.69
    assert usd.rate == Decimal("0.6900")
    assert perf.primary_currency == "USD"
    assert perf.primary_rate == Decimal("0.6900")


def test_compute_outstanding_excludes_closed() -> None:
    items = [
        # Open: 1000 chargeable, 400 recovered -> 600 outstanding.
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("400.00"), status=STATUS_AGREED),
        # Recovered (closed): nothing outstanding regardless of amounts.
        _item(chargeable=Decimal("500.00"), recovered=Decimal("500.00"), status=STATUS_RECOVERED),
        # Waived (closed): nothing outstanding.
        _item(chargeable=Decimal("300.00"), recovered=Decimal("0"), status=STATUS_WAIVED),
    ]
    perf = compute_recovery_performance(items)
    usd = _by_cur(perf, "USD")
    assert usd.outstanding_total == Decimal("600.00")


def test_compute_overall_rate_none_when_nothing_chargeable() -> None:
    # All items have zero/negative chargeable -> overall rate undefined.
    items = [
        _item(chargeable=Decimal("0"), recovered=Decimal("0"), status=STATUS_WAIVED),
        _item(chargeable=Decimal("-10"), recovered=Decimal("0"), status=STATUS_AGREED),
    ]
    perf = compute_recovery_performance(items)
    usd = _by_cur(perf, "USD")
    assert usd.chargeable_total == Decimal("0.00")
    assert usd.rate is None
    assert perf.primary_rate is None


# ---------------------------------------------------------------------------
# compute_recovery_performance - per-currency separation (never blended)
# ---------------------------------------------------------------------------


def test_compute_per_currency_separation() -> None:
    items = [
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("500.00"), currency="USD"),
        _item(chargeable=Decimal("800.00"), recovered=Decimal("600.00"), currency="EUR"),
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("250.00"), currency="USD"),
    ]
    perf = compute_recovery_performance(items)
    currencies = {r.currency for r in perf.by_currency}
    assert currencies == {"USD", "EUR"}

    usd = _by_cur(perf, "USD")
    eur = _by_cur(perf, "EUR")
    # USD: 750 / 2000 = 0.375
    assert usd.chargeable_total == Decimal("2000.00")
    assert usd.recovered_total == Decimal("750.00")
    assert usd.rate == Decimal("0.3750")
    # EUR: 600 / 800 = 0.75 - computed independently, never mixed with USD
    assert eur.chargeable_total == Decimal("800.00")
    assert eur.recovered_total == Decimal("600.00")
    assert eur.rate == Decimal("0.7500")


def test_compute_currency_rows_sorted_by_chargeable_desc_then_code() -> None:
    items = [
        _item(chargeable=Decimal("300.00"), currency="USD"),
        _item(chargeable=Decimal("900.00"), currency="EUR"),
        _item(chargeable=Decimal("600.00"), currency="GBP"),
    ]
    perf = compute_recovery_performance(items)
    assert [r.currency for r in perf.by_currency] == ["EUR", "GBP", "USD"]
    assert perf.primary_currency == "EUR"


def test_compute_primary_currency_alphabetical_tie_break() -> None:
    items = [
        _item(chargeable=Decimal("500.00"), recovered=Decimal("100.00"), currency="USD"),
        _item(chargeable=Decimal("500.00"), recovered=Decimal("250.00"), currency="EUR"),
    ]
    perf = compute_recovery_performance(items)
    # Equal chargeable -> EUR wins alphabetically; headline rate is EUR's.
    assert perf.primary_currency == "EUR"
    assert perf.primary_rate == Decimal("0.5000")


# ---------------------------------------------------------------------------
# compute_recovery_performance - high vs low traceability cohort (the moat)
# ---------------------------------------------------------------------------


def test_compute_high_vs_low_cohort_contrast() -> None:
    # Reproduces the report's headline: traceable (strong) owners recover far
    # more than untraceable (weak/moderate) ones, on the firm's own data.
    items = [
        # HIGH cohort (strong): 690 of 1000 recovered -> 0.69
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("690.00"), traceability_band=BAND_STRONG),
        # LOW cohort (weak): 350 of 1000 -> 0.35
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("350.00"), traceability_band=BAND_WEAK),
        # LOW cohort (moderate): folds in with weak under LOW.
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("350.00"), traceability_band=BAND_MODERATE),
    ]
    perf = compute_recovery_performance(items)
    usd = _by_cur(perf, "USD")

    high = _cohort(usd, COHORT_HIGH)
    low = _cohort(usd, COHORT_LOW)
    assert high is not None and low is not None
    assert high.chargeable_total == Decimal("1000.00")
    assert high.rate == Decimal("0.6900")
    # LOW = weak + moderate: 700 / 2000 = 0.35
    assert low.item_count == 2
    assert low.chargeable_total == Decimal("2000.00")
    assert low.recovered_total == Decimal("700.00")
    assert low.rate == Decimal("0.3500")
    # The contrast the report is about: high recovers nearly double.
    assert high.rate > low.rate


def test_compute_cohort_rows_ordered_high_then_low() -> None:
    items = [
        _item(traceability_band=BAND_WEAK),
        _item(traceability_band=BAND_STRONG),
    ]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    assert [c.cohort for c in usd.by_cohort] == [COHORT_HIGH, COHORT_LOW]


def test_compute_cohort_present_only_when_items_present() -> None:
    # Only strong items -> only the HIGH cohort row exists (no empty LOW row).
    items = [_item(traceability_band=BAND_STRONG)]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    assert [c.cohort for c in usd.by_cohort] == [COHORT_HIGH]
    assert _cohort(usd, COHORT_LOW) is None


def test_compute_cohort_rate_none_when_no_chargeable() -> None:
    # A LOW cohort that was entitled to nothing reports None, not 0.
    items = [
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("500.00"), traceability_band=BAND_STRONG),
        _item(chargeable=Decimal("0"), recovered=Decimal("0"), traceability_band=BAND_WEAK, status=STATUS_WAIVED),
    ]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    low = _cohort(usd, COHORT_LOW)
    assert low is not None
    assert low.chargeable_total == Decimal("0.00")
    assert low.rate is None


# ---------------------------------------------------------------------------
# compute_recovery_performance - three-band breakdown
# ---------------------------------------------------------------------------


def test_compute_three_band_breakdown() -> None:
    items = [
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("900.00"), traceability_band=BAND_STRONG),
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("500.00"), traceability_band=BAND_MODERATE),
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("100.00"), traceability_band=BAND_WEAK),
    ]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    assert [b.cohort for b in usd.by_band] == [BAND_STRONG, BAND_MODERATE, BAND_WEAK]
    assert _band(usd, BAND_STRONG).rate == Decimal("0.9000")
    assert _band(usd, BAND_MODERATE).rate == Decimal("0.5000")
    assert _band(usd, BAND_WEAK).rate == Decimal("0.1000")


def test_compute_band_breakdown_reconciles_to_cohorts() -> None:
    # moderate + weak band chargeable should equal the LOW cohort chargeable.
    items = [
        _item(chargeable=Decimal("400.00"), recovered=Decimal("100.00"), traceability_band=BAND_MODERATE),
        _item(chargeable=Decimal("600.00"), recovered=Decimal("200.00"), traceability_band=BAND_WEAK),
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("900.00"), traceability_band=BAND_STRONG),
    ]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    low = _cohort(usd, COHORT_LOW)
    mod = _band(usd, BAND_MODERATE)
    weak = _band(usd, BAND_WEAK)
    assert low.chargeable_total == mod.chargeable_total + weak.chargeable_total
    assert low.recovered_total == mod.recovered_total + weak.recovered_total
    high = _cohort(usd, COHORT_HIGH)
    strong = _band(usd, BAND_STRONG)
    assert high.chargeable_total == strong.chargeable_total


# ---------------------------------------------------------------------------
# compute_recovery_performance - absorbed handling
# ---------------------------------------------------------------------------


def test_compute_absorbed_total_and_cohort_concentration() -> None:
    # The report's point: absorbed cost concentrates in the low cohort.
    items = [
        # Strong, recovered in full -> nothing absorbed.
        _item(
            chargeable=Decimal("1000.00"),
            recovered=Decimal("1000.00"),
            traceability_band=BAND_STRONG,
            status=STATUS_RECOVERED,
        ),
        # Weak, waived after collecting nothing -> 800 absorbed.
        _item(chargeable=Decimal("800.00"), recovered=Decimal("0"), traceability_band=BAND_WEAK, status=STATUS_WAIVED),
        # Moderate, absorbed after collecting 100 of 500 -> 400 absorbed.
        _item(
            chargeable=Decimal("500.00"),
            recovered=Decimal("100.00"),
            traceability_band=BAND_MODERATE,
            status=STATUS_ABSORBED,
        ),
    ]
    perf = compute_recovery_performance(items)
    usd = _by_cur(perf, "USD")
    # 800 + 400 = 1200 absorbed in USD.
    assert usd.absorbed_total == Decimal("1200.00")

    high = _cohort(usd, COHORT_HIGH)
    low = _cohort(usd, COHORT_LOW)
    assert high.absorbed_total == Decimal("0.00")
    assert low.absorbed_total == Decimal("1200.00")


def test_compute_absorbed_zero_when_no_writeoffs() -> None:
    items = [
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("400.00"), status=STATUS_AGREED),
        _item(chargeable=Decimal("500.00"), recovered=Decimal("500.00"), status=STATUS_RECOVERED),
    ]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    assert usd.absorbed_total == Decimal("0.00")


# ---------------------------------------------------------------------------
# compute_recovery_performance - mixed statuses + Decimal exactness
# ---------------------------------------------------------------------------


def test_compute_mixed_statuses_full_picture() -> None:
    items = [
        _item(
            chargeable=Decimal("1000.00"),
            recovered=Decimal("1000.00"),
            status=STATUS_RECOVERED,
            traceability_band=BAND_STRONG,
        ),
        _item(
            chargeable=Decimal("1000.00"),
            recovered=Decimal("250.00"),
            status=STATUS_DISPUTED,
            traceability_band=BAND_MODERATE,
        ),
        _item(
            chargeable=Decimal("1000.00"), recovered=Decimal("0"), status=STATUS_PROPOSED, traceability_band=BAND_WEAK
        ),
        _item(chargeable=Decimal("1000.00"), recovered=Decimal("0"), status=STATUS_WAIVED, traceability_band=BAND_WEAK),
    ]
    perf = compute_recovery_performance(items)
    usd = _by_cur(perf, "USD")
    assert usd.item_count == 4
    assert usd.chargeable_total == Decimal("4000.00")
    assert usd.recovered_total == Decimal("1250.00")
    # outstanding: only the two open items (disputed 750 + proposed 1000) = 1750.
    assert usd.outstanding_total == Decimal("1750.00")
    # absorbed: the one waived weak item = 1000.
    assert usd.absorbed_total == Decimal("1000.00")
    # overall: 1250 / 4000 = 0.3125
    assert usd.rate == Decimal("0.3125")


def test_compute_decimal_exactness_no_float_drift() -> None:
    # Sums that would drift in float stay exact in Decimal. 0.1 * 3 == 0.3 here.
    items = [
        _item(chargeable=Decimal("0.10"), recovered=Decimal("0.10"), status=STATUS_RECOVERED),
        _item(chargeable=Decimal("0.10"), recovered=Decimal("0.10"), status=STATUS_RECOVERED),
        _item(chargeable=Decimal("0.10"), recovered=Decimal("0.10"), status=STATUS_RECOVERED),
    ]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    assert usd.chargeable_total == Decimal("0.30")
    assert usd.recovered_total == Decimal("0.30")
    assert usd.rate == Decimal("1.0000")


def test_compute_rate_uses_exact_sums_then_quantizes() -> None:
    # 1/3 recovered across many small items: the rate is derived from the exact
    # Decimal sums, not from the quantized money totals.
    items = [_item(chargeable=Decimal("10.00"), recovered=Decimal("3.33"), status=STATUS_AGREED) for _ in range(3)]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    assert usd.chargeable_total == Decimal("30.00")
    assert usd.recovered_total == Decimal("9.99")
    # 9.99 / 30.00 = 0.333 -> 0.3330
    assert usd.rate == Decimal("0.3330")


def test_compute_over_recovery_does_not_inflate_totals_or_rate() -> None:
    # One item over-recovered: clamped so recovered <= chargeable and rate <= 1.
    items = [
        _item(chargeable=Decimal("500.00"), recovered=Decimal("900.00"), status=STATUS_AGREED),
    ]
    usd = _by_cur(compute_recovery_performance(items), "USD")
    assert usd.chargeable_total == Decimal("500.00")
    assert usd.recovered_total == Decimal("500.00")
    assert usd.outstanding_total == Decimal("0.00")
    assert usd.rate == Decimal("1.0000")


def test_compute_is_deterministic() -> None:
    items = [
        _item(
            chargeable=Decimal("1000.00"), recovered=Decimal("690.00"), traceability_band=BAND_STRONG, currency="USD"
        ),
        _item(chargeable=Decimal("800.00"), recovered=Decimal("200.00"), traceability_band=BAND_WEAK, currency="EUR"),
        _item(
            chargeable=Decimal("500.00"), recovered=Decimal("250.00"), traceability_band=BAND_MODERATE, currency="USD"
        ),
    ]
    first = compute_recovery_performance(items)
    second = compute_recovery_performance(list(reversed(items)))
    assert first == second


def test_compute_returns_immutable_dataclasses() -> None:
    items = [_item()]
    perf = compute_recovery_performance(items)
    assert all(isinstance(r, CurrencyRecovery) for r in perf.by_currency)
    usd = _by_cur(perf, "USD")
    assert all(isinstance(c, CohortRecovery) for c in usd.by_cohort)
    assert all(isinstance(c, CohortRecovery) for c in usd.by_band)
    with pytest.raises(AttributeError):
        perf.primary_currency = "EUR"  # type: ignore[misc]
