# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure dispute-exposure (dispute radar) engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Money is
exercised exclusively with Decimal literals. The tests are table-driven where it
helps and lock in the contract the dispute-risk feature depends on: each driver
raises exposure and can become the dominant driver, the score is money-weighted
so a high-value low-evidence change outranks a low-value one, the documented band
thresholds, the report's ~75% cohort relationship, a per-currency summary that
never blends, empty input, and full determinism.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.change_intelligence.dispute_risk import (
    AGE_SATURATION_DAYS,
    BAND_MODERATE,
    BAND_STRONG,
    BAND_WEAK,
    BAND_WEAKNESS,
    COHORT_SHARED_FACTOR_LEVEL,
    CURE_BY_DRIVER,
    DRIVER_AGE,
    DRIVER_EVIDENCE,
    DRIVER_NONE,
    DRIVER_OWNERSHIP,
    DRIVER_SLA,
    ELEVATED_THRESHOLD,
    EXPOSURE_ELEVATED,
    EXPOSURE_HIGH,
    EXPOSURE_LOW,
    HIGH_THRESHOLD,
    MAX_EXPOSURE,
    MONEY_MAX_MULTIPLIER,
    MONEY_SATURATION_AMOUNT,
    TARGET_COHORT_RATIO,
    TOTAL_WEIGHT,
    W_AGE,
    W_EVIDENCE,
    W_OWNERSHIP,
    W_SLA,
    CurrencyExposure,
    DisputeExposureSummary,
    DisputeRiskInput,
    DisputeRiskItem,
    age_fraction,
    assess_dispute_risk,
    band_for_exposure,
    cohort_exposure_ratio,
    evidence_weakness,
    money_multiplier,
    rank_dispute_exposure,
    summarize_dispute_exposure,
)


def _inp(
    change_id: str = "C-1",
    change_ref: str = "CO-001",
    kind: str = "change_order",
    title: str = "scope change",
    provability_score: int | None = None,
    provability_band: str = BAND_STRONG,
    days_overdue: float = 0.0,
    sla_breached: bool = False,
    ownership_ambiguous: bool = False,
    outstanding_amount: Decimal = Decimal("0"),
    currency: str = "USD",
    committed_cost_at_risk: Decimal | None = None,
) -> DisputeRiskInput:
    """Build a DisputeRiskInput with sensible (clean, low-risk) defaults."""
    return DisputeRiskInput(
        change_id=change_id,
        change_ref=change_ref,
        kind=kind,
        title=title,
        provability_score=provability_score,
        provability_band=provability_band,
        days_overdue=days_overdue,
        sla_breached=sla_breached,
        ownership_ambiguous=ownership_ambiguous,
        outstanding_amount=outstanding_amount,
        currency=currency,
        committed_cost_at_risk=committed_cost_at_risk,
    )


# --------------------------------------------------------------------------- #
# weighting table
# --------------------------------------------------------------------------- #


def test_weights_sum_to_total_weight() -> None:
    assert W_EVIDENCE + W_AGE + W_SLA + W_OWNERSHIP == TOTAL_WEIGHT


def test_evidence_is_the_dominant_factor() -> None:
    # The report ties dispute escalation most strongly to evidence confidence.
    assert W_EVIDENCE > W_AGE
    assert W_EVIDENCE > W_SLA
    assert W_EVIDENCE > W_OWNERSHIP
    # In fact evidence outweighs every other factor combined, so it can always
    # be the dominant driver when fully present.
    assert W_EVIDENCE > W_AGE + W_SLA + W_OWNERSHIP


def test_band_weakness_is_monotonic() -> None:
    # Weaker provability band => more evidence weakness.
    assert BAND_WEAKNESS[BAND_STRONG] < BAND_WEAKNESS[BAND_MODERATE] < BAND_WEAKNESS[BAND_WEAK]
    for v in BAND_WEAKNESS.values():
        assert 0.0 <= v <= 1.0


# --------------------------------------------------------------------------- #
# evidence_weakness
# --------------------------------------------------------------------------- #


def test_evidence_weakness_from_numeric_score() -> None:
    # 1 - score/100; perfect score => no weakness, zero score => full weakness.
    assert evidence_weakness(100, BAND_STRONG) == pytest.approx(0.0)
    assert evidence_weakness(0, BAND_WEAK) == pytest.approx(1.0)
    assert evidence_weakness(40, BAND_MODERATE) == pytest.approx(0.6)


def test_numeric_score_overrides_band() -> None:
    # When a score is present, the band is ignored for the weakness fraction.
    assert evidence_weakness(80, BAND_WEAK) == pytest.approx(0.2)


def test_evidence_weakness_from_band_when_no_score() -> None:
    assert evidence_weakness(None, BAND_STRONG) == BAND_WEAKNESS[BAND_STRONG]
    assert evidence_weakness(None, BAND_MODERATE) == BAND_WEAKNESS[BAND_MODERATE]
    assert evidence_weakness(None, BAND_WEAK) == BAND_WEAKNESS[BAND_WEAK]


def test_unknown_band_treated_as_weakest() -> None:
    # An unwired / mis-mapped band scores conservatively (max weakness).
    assert evidence_weakness(None, "nonsense") == BAND_WEAKNESS[BAND_WEAK]


def test_evidence_weakness_clamps_out_of_range_score() -> None:
    assert evidence_weakness(150, BAND_STRONG) == pytest.approx(0.0)
    assert evidence_weakness(-20, BAND_WEAK) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# age_fraction
# --------------------------------------------------------------------------- #


def test_age_fraction_zero_when_not_overdue() -> None:
    assert age_fraction(0.0) == 0.0
    assert age_fraction(-5.0) == 0.0


def test_age_fraction_ramps_then_saturates() -> None:
    assert age_fraction(AGE_SATURATION_DAYS / 2.0) == pytest.approx(0.5)
    assert age_fraction(AGE_SATURATION_DAYS) == pytest.approx(1.0)
    assert age_fraction(AGE_SATURATION_DAYS * 3.0) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# money_multiplier
# --------------------------------------------------------------------------- #


def test_money_multiplier_floor_at_zero_money() -> None:
    assert money_multiplier(Decimal("0")) == 1.0
    assert money_multiplier(Decimal("-100")) == 1.0


def test_money_multiplier_ceiling_at_saturation() -> None:
    assert money_multiplier(MONEY_SATURATION_AMOUNT) == pytest.approx(MONEY_MAX_MULTIPLIER)
    assert money_multiplier(MONEY_SATURATION_AMOUNT * 4) == pytest.approx(MONEY_MAX_MULTIPLIER)


def test_money_multiplier_monotonic_between_floor_and_ceiling() -> None:
    half = money_multiplier(MONEY_SATURATION_AMOUNT / 2)
    assert 1.0 < half < MONEY_MAX_MULTIPLIER
    assert half == pytest.approx(1.0 + 0.5 * (MONEY_MAX_MULTIPLIER - 1.0))


# --------------------------------------------------------------------------- #
# assess_dispute_risk - extremes
# --------------------------------------------------------------------------- #


def test_perfectly_clean_change_scores_zero_low_and_no_driver() -> None:
    item = assess_dispute_risk(
        _inp(
            provability_score=100,
            provability_band=BAND_STRONG,
            days_overdue=0,
            sla_breached=False,
            ownership_ambiguous=False,
            committed_cost_at_risk=Decimal("0"),
        )
    )
    assert item.exposure_score == 0
    assert item.band == EXPOSURE_LOW
    assert item.dominant_driver == DRIVER_NONE
    assert item.recommended_cure == CURE_BY_DRIVER[DRIVER_NONE]
    assert item.money_multiplier == 1.0
    assert item.intrinsic_exposure == 0.0


def test_worst_case_change_scores_max_and_high() -> None:
    item = assess_dispute_risk(
        _inp(
            provability_score=0,
            provability_band=BAND_WEAK,
            days_overdue=AGE_SATURATION_DAYS * 2,
            sla_breached=True,
            ownership_ambiguous=True,
            committed_cost_at_risk=MONEY_SATURATION_AMOUNT * 2,
        )
    )
    assert item.exposure_score == MAX_EXPOSURE
    assert item.band == EXPOSURE_HIGH
    assert item.dominant_driver == DRIVER_EVIDENCE


def test_exposure_score_never_below_zero_or_above_max() -> None:
    worst = assess_dispute_risk(
        _inp(
            provability_score=0,
            provability_band=BAND_WEAK,
            days_overdue=999,
            sla_breached=True,
            ownership_ambiguous=True,
            committed_cost_at_risk=Decimal("99999999"),
        )
    )
    best = assess_dispute_risk(_inp(provability_score=100))
    assert 0 <= worst.exposure_score <= MAX_EXPOSURE
    assert 0 <= best.exposure_score <= MAX_EXPOSURE


def test_input_fields_carried_through_to_item() -> None:
    item = assess_dispute_risk(_inp(change_id="C-42", change_ref="VO-9", kind="variation_order", title="extra works"))
    assert item.change_id == "C-42"
    assert item.change_ref == "VO-9"
    assert item.kind == "variation_order"
    assert item.title == "extra works"


def test_factors_listed_in_fixed_order_with_weights() -> None:
    item = assess_dispute_risk(_inp(provability_score=50, days_overdue=5))
    assert [f.name for f in item.factors] == ["evidence", "overdue_age", "sla_breach", "ownership"]
    assert [f.weight for f in item.factors] == [W_EVIDENCE, W_AGE, W_SLA, W_OWNERSHIP]


# --------------------------------------------------------------------------- #
# each driver raises exposure (monotonicity) and can become dominant
# --------------------------------------------------------------------------- #


def test_lower_provability_raises_exposure() -> None:
    strong = assess_dispute_risk(_inp(provability_score=95))
    weak = assess_dispute_risk(_inp(provability_score=10))
    assert weak.exposure_score > strong.exposure_score


def test_more_overdue_raises_exposure() -> None:
    fresh = assess_dispute_risk(_inp(provability_score=100, days_overdue=0))
    aged = assess_dispute_risk(_inp(provability_score=100, days_overdue=20))
    assert aged.exposure_score > fresh.exposure_score


def test_sla_breach_raises_exposure() -> None:
    ok = assess_dispute_risk(_inp(provability_score=100, sla_breached=False))
    breached = assess_dispute_risk(_inp(provability_score=100, sla_breached=True))
    assert breached.exposure_score > ok.exposure_score


def test_ownership_ambiguity_raises_exposure() -> None:
    clear = assess_dispute_risk(_inp(provability_score=100, ownership_ambiguous=False))
    ambiguous = assess_dispute_risk(_inp(provability_score=100, ownership_ambiguous=True))
    assert ambiguous.exposure_score > clear.exposure_score


@pytest.mark.parametrize(
    ("kwargs", "expected_driver"),
    [
        # Only weak evidence present.
        (dict(provability_score=5, provability_band=BAND_WEAK), DRIVER_EVIDENCE),
        # Perfect evidence, only overdue.
        (dict(provability_score=100, days_overdue=AGE_SATURATION_DAYS), DRIVER_AGE),
        # Perfect evidence, only SLA breach.
        (dict(provability_score=100, sla_breached=True), DRIVER_SLA),
        # Perfect evidence, only ownership ambiguity.
        (dict(provability_score=100, ownership_ambiguous=True), DRIVER_OWNERSHIP),
    ],
)
def test_each_factor_can_be_dominant_driver(kwargs: dict, expected_driver: str) -> None:
    item = assess_dispute_risk(_inp(**kwargs))
    assert item.dominant_driver == expected_driver
    assert item.recommended_cure == CURE_BY_DRIVER[expected_driver]
    # The dominant factor is flagged in the factor breakdown, and only it.
    drivers = [f for f in item.factors if f.is_driver]
    assert len(drivers) == 1


def test_dominant_driver_tie_breaks_to_earlier_factor() -> None:
    # Construct equal weighted contributions for SLA (15) and ownership (10)?
    # They differ in weight, so to tie we need equal weighted = fraction*weight.
    # SLA full = 15; ownership full = 10; not equal. Instead tie age vs sla:
    # age weight 20, sla weight 15 -> age fraction 0.75 gives 15 == sla full 15.
    item = assess_dispute_risk(
        _inp(
            provability_score=100,  # evidence contributes 0
            days_overdue=AGE_SATURATION_DAYS * 0.75,  # age weighted = 0.75*20 = 15
            sla_breached=True,  # sla weighted = 1.0*15 = 15
        )
    )
    # Age comes before SLA in the fixed order, so it wins the tie.
    assert item.dominant_driver == DRIVER_AGE


def test_no_driver_when_completely_clean() -> None:
    item = assess_dispute_risk(_inp(provability_score=100))
    assert item.dominant_driver == DRIVER_NONE
    assert all(not f.is_driver for f in item.factors)


# --------------------------------------------------------------------------- #
# money weighting
# --------------------------------------------------------------------------- #


def test_money_weighting_orders_high_value_above_low_value() -> None:
    # Two changes identical except committed cost-at-risk; the high-dollar one
    # must score higher (a high-dollar low-provability overdue change tops list).
    common = dict(provability_score=20, provability_band=BAND_WEAK, days_overdue=15)
    high = assess_dispute_risk(_inp(change_id="hi", committed_cost_at_risk=Decimal("400000"), **common))
    low = assess_dispute_risk(_inp(change_id="lo", committed_cost_at_risk=Decimal("1000"), **common))
    assert high.exposure_score > low.exposure_score
    assert high.money_multiplier > low.money_multiplier


def test_money_weighting_does_not_rescue_a_well_evidenced_clean_change() -> None:
    # A huge sum at risk on an otherwise spotless change still scores low: there
    # is nothing wrong to amplify (intrinsic exposure is zero).
    item = assess_dispute_risk(
        _inp(provability_score=100, days_overdue=0, committed_cost_at_risk=MONEY_SATURATION_AMOUNT * 10)
    )
    assert item.exposure_score == 0
    assert item.band == EXPOSURE_LOW


def test_money_basis_falls_back_to_outstanding_when_no_committed() -> None:
    item = assess_dispute_risk(
        _inp(
            provability_score=30,
            provability_band=BAND_WEAK,
            days_overdue=10,
            outstanding_amount=Decimal("123456.78"),
            committed_cost_at_risk=None,
        )
    )
    assert item.money_basis == Decimal("123456.78")


def test_committed_cost_preferred_over_outstanding_for_basis() -> None:
    item = assess_dispute_risk(
        _inp(
            outstanding_amount=Decimal("100.00"),
            committed_cost_at_risk=Decimal("90000.00"),
        )
    )
    assert item.money_basis == Decimal("90000.00")


def test_negative_money_basis_clamped_to_zero() -> None:
    item = assess_dispute_risk(_inp(provability_score=20, committed_cost_at_risk=Decimal("-500")))
    assert item.money_basis == Decimal("0.00")
    assert item.money_multiplier == 1.0


def test_money_basis_quantized_two_places() -> None:
    item = assess_dispute_risk(_inp(committed_cost_at_risk=Decimal("1000.005")))
    assert item.money_basis == Decimal("1000.01")  # half-up


# --------------------------------------------------------------------------- #
# banding
# --------------------------------------------------------------------------- #


def test_band_thresholds_are_inclusive_lower_bounds() -> None:
    assert band_for_exposure(MAX_EXPOSURE) == EXPOSURE_HIGH
    assert band_for_exposure(HIGH_THRESHOLD) == EXPOSURE_HIGH
    assert band_for_exposure(HIGH_THRESHOLD - 1) == EXPOSURE_ELEVATED
    assert band_for_exposure(ELEVATED_THRESHOLD) == EXPOSURE_ELEVATED
    assert band_for_exposure(ELEVATED_THRESHOLD - 1) == EXPOSURE_LOW
    assert band_for_exposure(0) == EXPOSURE_LOW


def test_item_band_matches_band_for_exposure() -> None:
    for kwargs in (
        dict(provability_score=100),
        dict(provability_score=55, days_overdue=8, sla_breached=True),
        dict(
            provability_score=0,
            provability_band=BAND_WEAK,
            days_overdue=40,
            sla_breached=True,
            ownership_ambiguous=True,
        ),
    ):
        item = assess_dispute_risk(_inp(**kwargs))
        assert item.band == band_for_exposure(item.exposure_score)


# --------------------------------------------------------------------------- #
# the ~75% cohort relationship
# --------------------------------------------------------------------------- #


def test_cohort_ratio_reproduces_report_relationship_exactly() -> None:
    # Low evidence-confidence lands ~75% higher exposure than high confidence.
    assert cohort_exposure_ratio() == pytest.approx(TARGET_COHORT_RATIO)


def test_cohort_ratio_built_from_band_anchors_at_shared_level() -> None:
    # Re-derive the ratio independently from the published anchors + weights to
    # prove the helper is not hand-fudged: with the three other factors held at
    # COHORT_SHARED_FACTOR_LEVEL, the shared contribution cancels into the ratio.
    shared = COHORT_SHARED_FACTOR_LEVEL * (W_AGE + W_SLA + W_OWNERSHIP)
    weak = BAND_WEAKNESS[BAND_WEAK] * W_EVIDENCE + shared
    strong = BAND_WEAKNESS[BAND_STRONG] * W_EVIDENCE + shared
    assert weak / strong == pytest.approx(TARGET_COHORT_RATIO)


def test_weak_cohort_materially_exceeds_strong_cohort_on_realistic_inputs() -> None:
    # On genuinely comparable changes (same age / SLA / ownership / money),
    # differing only in provability band, the weak cohort is well above strong.
    common = dict(
        days_overdue=AGE_SATURATION_DAYS * 0.5,
        sla_breached=False,
        ownership_ambiguous=False,
        committed_cost_at_risk=Decimal("100000"),
    )
    weak = assess_dispute_risk(_inp(provability_band=BAND_WEAK, **common))
    strong = assess_dispute_risk(_inp(provability_band=BAND_STRONG, **common))
    assert weak.exposure_score > strong.exposure_score
    # The spread is substantial - at least the report's order of magnitude.
    assert weak.exposure_score >= strong.exposure_score * 1.5


def test_moderate_cohort_sits_between_weak_and_strong() -> None:
    common = dict(days_overdue=10.0, committed_cost_at_risk=Decimal("80000"))
    weak = assess_dispute_risk(_inp(provability_band=BAND_WEAK, **common)).exposure_score
    moderate = assess_dispute_risk(_inp(provability_band=BAND_MODERATE, **common)).exposure_score
    strong = assess_dispute_risk(_inp(provability_band=BAND_STRONG, **common)).exposure_score
    assert strong < moderate < weak


# --------------------------------------------------------------------------- #
# rank_dispute_exposure
# --------------------------------------------------------------------------- #


def test_rank_sorts_by_exposure_descending() -> None:
    items = [
        _inp(change_id="a", change_ref="CO-A", provability_score=90, days_overdue=0),
        _inp(
            change_id="b",
            change_ref="CO-B",
            provability_score=10,
            provability_band=BAND_WEAK,
            days_overdue=40,
            sla_breached=True,
            committed_cost_at_risk=Decimal("300000"),
        ),
        _inp(change_id="c", change_ref="CO-C", provability_score=55, days_overdue=10),
    ]
    ranked = rank_dispute_exposure(items)
    scores = [r.exposure_score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].change_ref == "CO-B"


def test_rank_high_dollar_low_provability_overdue_tops_the_list() -> None:
    items = [
        # Moderately risky but small money.
        _inp(
            change_id="small",
            change_ref="CO-S",
            provability_score=40,
            provability_band=BAND_MODERATE,
            days_overdue=20,
            committed_cost_at_risk=Decimal("2000"),
        ),
        # High-dollar, low-provability, overdue -> must rank first.
        _inp(
            change_id="big",
            change_ref="CO-B",
            provability_score=15,
            provability_band=BAND_WEAK,
            days_overdue=25,
            committed_cost_at_risk=Decimal("450000"),
        ),
    ]
    ranked = rank_dispute_exposure(items)
    assert ranked[0].change_id == "big"


def test_rank_ties_break_by_money_then_ref_then_id() -> None:
    # Two perfectly clean changes both score 0 -> tie on score. Larger money
    # basis first, then change_ref, then change_id.
    items = [
        _inp(change_id="id-z", change_ref="CO-Z", provability_score=100, committed_cost_at_risk=Decimal("10")),
        _inp(change_id="id-a", change_ref="CO-A", provability_score=100, committed_cost_at_risk=Decimal("10")),
        _inp(change_id="id-big", change_ref="CO-M", provability_score=100, committed_cost_at_risk=Decimal("5000")),
    ]
    ranked = rank_dispute_exposure(items)
    # All score 0; CO-M has the largest money basis so it leads, then CO-A, CO-Z.
    assert [r.change_ref for r in ranked] == ["CO-M", "CO-A", "CO-Z"]


def test_rank_is_stable_and_deterministic() -> None:
    items = [_inp(change_id=f"c{i}", change_ref=f"CO-{i:02d}", provability_score=50, days_overdue=5) for i in range(6)]
    a = rank_dispute_exposure(items)
    b = rank_dispute_exposure(items)
    assert [r.change_id for r in a] == [r.change_id for r in b]


def test_rank_empty_input() -> None:
    assert rank_dispute_exposure([]) == []


# --------------------------------------------------------------------------- #
# summarize_dispute_exposure
# --------------------------------------------------------------------------- #


def test_summary_counts_bands() -> None:
    items = [
        assess_dispute_risk(
            _inp(
                change_id="hi",
                provability_score=0,
                provability_band=BAND_WEAK,
                days_overdue=40,
                sla_breached=True,
                ownership_ambiguous=True,
                committed_cost_at_risk=Decimal("400000"),
            )
        ),
        assess_dispute_risk(
            _inp(
                change_id="mid",
                provability_score=45,
                provability_band=BAND_MODERATE,
                days_overdue=10,
                sla_breached=True,
            )
        ),
        assess_dispute_risk(_inp(change_id="lo", provability_score=100)),
    ]
    summary = summarize_dispute_exposure(items)
    assert summary.item_count == 3
    # All three band keys present, summing to item_count.
    assert set(summary.band_counts) == {EXPOSURE_HIGH, EXPOSURE_ELEVATED, EXPOSURE_LOW}
    assert sum(summary.band_counts.values()) == 3
    assert summary.band_counts[EXPOSURE_HIGH] == 1
    assert summary.band_counts[EXPOSURE_LOW] == 1


def test_summary_per_currency_never_blends() -> None:
    items = [
        assess_dispute_risk(
            _inp(
                change_id="u1",
                provability_score=20,
                provability_band=BAND_WEAK,
                days_overdue=20,
                currency="USD",
                committed_cost_at_risk=Decimal("100000"),
            )
        ),
        assess_dispute_risk(
            _inp(
                change_id="e1",
                provability_score=20,
                provability_band=BAND_WEAK,
                days_overdue=20,
                currency="EUR",
                committed_cost_at_risk=Decimal("50000"),
            )
        ),
        assess_dispute_risk(
            _inp(
                change_id="u2",
                provability_score=30,
                provability_band=BAND_WEAK,
                days_overdue=10,
                currency="USD",
                committed_cost_at_risk=Decimal("20000"),
            )
        ),
    ]
    summary = summarize_dispute_exposure(items)
    by_cur = {c.currency: c for c in summary.by_currency}
    assert set(by_cur) == {"USD", "EUR"}
    # USD basis is the sum of the two USD changes only; EUR untouched by USD.
    assert by_cur["USD"].money_basis_total == Decimal("120000.00")
    assert by_cur["USD"].item_count == 2
    assert by_cur["EUR"].money_basis_total == Decimal("50000.00")
    assert by_cur["EUR"].item_count == 1


def test_summary_exposure_weighted_amount_matches_manual() -> None:
    item = assess_dispute_risk(
        _inp(
            change_id="x",
            provability_score=20,
            provability_band=BAND_WEAK,
            days_overdue=20,
            currency="USD",
            committed_cost_at_risk=Decimal("100000"),
        )
    )
    summary = summarize_dispute_exposure([item])
    usd = next(c for c in summary.by_currency if c.currency == "USD")
    expected = (item.money_basis * Decimal(item.exposure_score) / Decimal(MAX_EXPOSURE)).quantize(Decimal("0.01"))
    assert usd.exposure_weighted_amount == expected
    # The exposure-weighted amount never exceeds the basis.
    assert usd.exposure_weighted_amount <= usd.money_basis_total


def test_summary_currency_rows_sorted_by_weighted_desc_then_code() -> None:
    items = [
        assess_dispute_risk(
            _inp(
                change_id="e",
                provability_score=20,
                provability_band=BAND_WEAK,
                days_overdue=30,
                sla_breached=True,
                currency="EUR",
                committed_cost_at_risk=Decimal("500000"),
            )
        ),
        assess_dispute_risk(
            _inp(
                change_id="u",
                provability_score=40,
                provability_band=BAND_MODERATE,
                days_overdue=5,
                currency="USD",
                committed_cost_at_risk=Decimal("10000"),
            )
        ),
    ]
    summary = summarize_dispute_exposure(items)
    # EUR carries far more exposure-weighted money, so it comes first.
    assert [c.currency for c in summary.by_currency] == ["EUR", "USD"]


def test_summary_counts_dominant_drivers() -> None:
    items = [
        assess_dispute_risk(_inp(change_id="e1", provability_score=5, provability_band=BAND_WEAK)),
        assess_dispute_risk(_inp(change_id="e2", provability_score=10, provability_band=BAND_WEAK)),
        assess_dispute_risk(_inp(change_id="age", provability_score=100, days_overdue=AGE_SATURATION_DAYS)),
    ]
    summary = summarize_dispute_exposure(items)
    assert summary.top_driver_counts[DRIVER_EVIDENCE] == 2
    assert summary.top_driver_counts[DRIVER_AGE] == 1


def test_summary_empty_input() -> None:
    summary = summarize_dispute_exposure([])
    assert isinstance(summary, DisputeExposureSummary)
    assert summary.item_count == 0
    assert summary.band_counts == {EXPOSURE_HIGH: 0, EXPOSURE_ELEVATED: 0, EXPOSURE_LOW: 0}
    assert summary.by_currency == ()
    assert summary.top_driver_counts == {}


def test_summary_dataclass_types_returned() -> None:
    items = [
        assess_dispute_risk(
            _inp(provability_score=30, provability_band=BAND_WEAK, committed_cost_at_risk=Decimal("1000"))
        )
    ]
    summary = summarize_dispute_exposure(items)
    assert all(isinstance(c, CurrencyExposure) for c in summary.by_currency)


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #


def test_assess_is_deterministic() -> None:
    inp = _inp(
        provability_score=35,
        provability_band=BAND_WEAK,
        days_overdue=12,
        sla_breached=True,
        ownership_ambiguous=True,
        committed_cost_at_risk=Decimal("75000.50"),
    )
    a = assess_dispute_risk(inp)
    b = assess_dispute_risk(inp)
    assert a == b


def test_item_is_a_dispute_risk_item() -> None:
    assert isinstance(assess_dispute_risk(_inp()), DisputeRiskItem)
