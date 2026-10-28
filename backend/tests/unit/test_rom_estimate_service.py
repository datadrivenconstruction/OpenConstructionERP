"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the conceptual (ROM) estimate engine.

These pin the behaviour of :mod:`app.modules.rom_estimate.service`, a pure,
database-free layer that turns minimal input (building type, gross floor area,
quality, region) into a headline total, a six-element breakdown and an honest
accuracy band. The focus is reference-data integrity, Decimal-exact money that
sums cleanly, international robustness (unit conversion, no hardcoded currency)
and clear guards for bad input.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.rom_estimate.schemas import RomEstimateRequest
from app.modules.rom_estimate.service import (
    BUILDING_TYPES,
    DEFAULT_RECONCILE_TOLERANCE_PCT,
    ELEMENT_KEYS,
    QUALITY_LEVELS,
    REGIONS,
    STATUS_NO_BASELINE,
    STATUS_ON_TRACK,
    STATUS_OVER,
    STATUS_UNDER,
    _parse_money,
    build_reconciliation,
    build_reference,
    build_rom_estimate,
    rom_result_to_row_kwargs,
)


def _req(**kwargs: object) -> RomEstimateRequest:
    """Build a request with sensible defaults for the field under test."""
    base: dict[str, object] = {
        "building_type": "office",
        "gross_floor_area": Decimal("1000"),
        "quality": "standard",
        "region": "global",
    }
    base.update(kwargs)
    return RomEstimateRequest(**base)


# ── Reference-data integrity ─────────────────────────────────────────────────


def test_every_profile_has_six_elements_summing_to_one() -> None:
    """Each building type's elemental shares cover all six elements and sum to 1."""
    for key, profile in BUILDING_TYPES.items():
        assert tuple(profile.shares) == ELEMENT_KEYS, f"{key} elements out of order"
        assert sum(profile.shares.values()) == Decimal("1"), f"{key} shares must sum to 1"
        assert all(share > 0 for share in profile.shares.values()), f"{key} has a non-positive share"


def test_profiles_have_positive_rates_and_a_valid_band() -> None:
    """Base rates are positive and the accuracy band is low<0<high."""
    for key, profile in BUILDING_TYPES.items():
        assert profile.base_rate_per_m2 > 0, f"{key} base rate must be positive"
        assert profile.accuracy_low_pct < 0 < profile.accuracy_high_pct, f"{key} band invalid"


def test_quality_and_region_factors_are_positive_with_documented_defaults() -> None:
    """Factors are strictly positive; the worldwide/standard defaults are 1."""
    assert all(opt.factor > 0 for opt in QUALITY_LEVELS.values())
    assert all(opt.factor > 0 for opt in REGIONS.values())
    assert QUALITY_LEVELS["standard"].factor == Decimal("1.00")
    assert REGIONS["global"].factor == Decimal("1.00")


def test_build_reference_exposes_the_whole_table() -> None:
    ref = build_reference()
    assert {b.key for b in ref.building_types} == set(BUILDING_TYPES)
    assert {q.key for q in ref.quality_levels} == set(QUALITY_LEVELS)
    assert {r.key for r in ref.regions} == set(REGIONS)
    assert [e.key for e in ref.elements] == list(ELEMENT_KEYS)
    assert ref.default_region == "global"


# ── Core estimate maths ──────────────────────────────────────────────────────


def test_standard_global_total_equals_base_rate_times_area() -> None:
    """Office / standard / global: total = base rate x GFA, cost/m2 = base rate."""
    result = build_rom_estimate(_req(gross_floor_area=Decimal("1000")))
    base = BUILDING_TYPES["office"].base_rate_per_m2
    assert result.cost_per_m2 == base
    assert result.total == base * Decimal("1000")
    assert result.gfa_canonical_m2 == Decimal("1000")


def test_breakdown_has_six_lines_and_sums_exactly_to_total() -> None:
    """The elemental breakdown always reconciles to the headline total."""
    result = build_rom_estimate(_req(gross_floor_area=Decimal("1234.5")))
    assert len(result.elements) == 6
    assert [e.key for e in result.elements] == list(ELEMENT_KEYS)
    assert sum(e.amount for e in result.elements) == result.total
    assert sum(e.cost_share_pct for e in result.elements) == Decimal("100.00")


def test_quality_scales_the_total() -> None:
    """A premium build costs more than a standard one, economy less."""
    standard = build_rom_estimate(_req(quality="standard")).total
    premium = build_rom_estimate(_req(quality="premium")).total
    economy = build_rom_estimate(_req(quality="economy")).total
    assert economy < standard < premium
    assert premium == standard * QUALITY_LEVELS["premium"].factor


def test_region_factor_scales_the_total() -> None:
    """A lower-cost region reduces the total relative to the worldwide default."""
    glob = build_rom_estimate(_req(region="global")).total
    cheap = build_rom_estimate(_req(region="eastern_europe")).total
    assert cheap < glob
    assert build_rom_estimate(_req(region="eastern_europe")).regional_factor == REGIONS["eastern_europe"].factor


def test_metric_and_imperial_area_give_the_same_cost_per_m2() -> None:
    """A GFA in ft2 benchmarks identically to the same area in m2."""
    metric = build_rom_estimate(_req(gross_floor_area=Decimal("1000"), gfa_unit="m2"))
    # 1000 m2 == 10763.91 ft2; cost per m2 must be unchanged.
    imperial = build_rom_estimate(_req(gross_floor_area=Decimal("10763.910417"), gfa_unit="ft2"))
    assert metric.cost_per_m2 == imperial.cost_per_m2
    assert abs(metric.gfa_canonical_m2 - imperial.gfa_canonical_m2) < Decimal("0.01")
    assert abs(metric.total - imperial.total) < Decimal("1")


def test_currency_label_is_carried_through() -> None:
    result = build_rom_estimate(_req(currency="USD"))
    assert result.currency == "USD"


# ── Base-rate override (anchor the total to a real cost per m2) ───────────────


def test_base_rate_override_anchors_the_total() -> None:
    """A base-rate override replaces the reference basis, so the number is real."""
    reference = build_rom_estimate(_req(region="global", quality="standard"))
    override = build_rom_estimate(_req(region="global", quality="standard", base_rate_per_m2_override=Decimal("1000")))
    # Standard / global: cost per m2 equals the override exactly (Decimal-exact).
    assert override.cost_per_m2 == Decimal("1000")
    assert override.total == Decimal("1000") * Decimal("1000")  # rate x 1000 m2 GFA
    # And it genuinely differs from the neutral reference-basis result.
    assert override.total != reference.total
    # The elemental breakdown still reconciles to the overridden total.
    assert sum(e.amount for e in override.elements) == override.total


def test_base_rate_override_still_scales_with_quality_and_region() -> None:
    """Quality and regional factors still apply on top of the override."""
    std_global = build_rom_estimate(
        _req(region="global", quality="standard", base_rate_per_m2_override=Decimal("1000"))
    )
    prem_na = build_rom_estimate(
        _req(region="north_america", quality="premium", base_rate_per_m2_override=Decimal("1000"))
    )
    assert std_global.cost_per_m2 == Decimal("1000")
    assert prem_na.cost_per_m2 == (Decimal("1000") * QUALITY_LEVELS["premium"].factor * REGIONS["north_america"].factor)


def test_missing_or_non_positive_override_keeps_the_reference_basis() -> None:
    """None or a non-positive override falls back to the building-type reference rate."""
    reference_rate = build_rom_estimate(_req()).cost_per_m2
    assert build_rom_estimate(_req(base_rate_per_m2_override=None)).cost_per_m2 == reference_rate
    assert build_rom_estimate(_req(base_rate_per_m2_override=Decimal("0"))).cost_per_m2 == reference_rate
    assert build_rom_estimate(_req(base_rate_per_m2_override=Decimal("-5"))).cost_per_m2 == reference_rate


# ── Accuracy band ────────────────────────────────────────────────────────────


def test_accuracy_band_brackets_the_total() -> None:
    result = build_rom_estimate(_req())
    assert result.accuracy.low_amount < result.total < result.accuracy.high_amount
    assert result.accuracy.low_pct < 0 < result.accuracy.high_pct
    assert result.accuracy.estimate_class == "order_of_magnitude"


def test_band_widens_when_no_region_is_applied() -> None:
    """The global (unlocalized) band is wider than a localized one, and flagged."""
    glob = build_rom_estimate(_req(region="global")).accuracy
    localized = build_rom_estimate(_req(region="north_america")).accuracy
    assert glob.localized is False
    assert localized.localized is True
    # Wider means a more-negative low bound and a higher upper bound.
    assert glob.low_pct < localized.low_pct
    assert glob.high_pct > localized.high_pct


# ── Input guards ─────────────────────────────────────────────────────────────


def test_unknown_building_type_raises_with_options() -> None:
    with pytest.raises(ValueError, match="Unknown building type"):
        build_rom_estimate(_req(building_type="castle"))


def test_unknown_quality_raises() -> None:
    with pytest.raises(ValueError, match="Unknown quality level"):
        build_rom_estimate(_req(quality="gold-plated"))


def test_unknown_region_raises() -> None:
    with pytest.raises(ValueError, match="Unknown region"):
        build_rom_estimate(_req(region="atlantis"))


def test_unsupported_unit_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported unit"):
        build_rom_estimate(_req(gfa_unit="furlongs"))


def test_non_positive_area_is_rejected_by_the_request_schema() -> None:
    """The schema guards a zero/negative GFA before it reaches the engine."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RomEstimateRequest(building_type="office", gross_floor_area=Decimal("0"))


# ── Persistence mapping (pure, no session) ───────────────────────────────────


def test_result_to_row_kwargs_stores_strings_and_a_json_breakdown() -> None:
    """The row mapping keeps money as strings and snapshots the breakdown."""
    result = build_rom_estimate(_req(currency="EUR", name="Concept A"))
    project_id = uuid.uuid4()
    created_by = uuid.uuid4()
    kwargs = rom_result_to_row_kwargs(result, project_id=project_id, name="Concept A", created_by=created_by)

    assert kwargs["project_id"] == project_id
    assert kwargs["created_by"] == created_by
    assert kwargs["building_type"] == "office"
    assert kwargs["total_cost"] == format(result.total, "f")
    assert isinstance(kwargs["total_cost"], str)
    breakdown = kwargs["breakdown"]
    assert isinstance(breakdown, list) and len(breakdown) == 6
    # Every stored amount is a Decimal-as-string, and the snapshot sums to total.
    assert all(isinstance(line["amount"], str) for line in breakdown)
    assert sum(Decimal(line["amount"]) for line in breakdown) == result.total


# ── JSON contract (money serialised as strings) ──────────────────────────────


def test_result_json_emits_money_as_strings() -> None:
    payload = build_rom_estimate(_req(currency="EUR")).model_dump(mode="json")
    assert isinstance(payload["total"], str)
    assert isinstance(payload["cost_per_m2"], str)
    assert isinstance(payload["accuracy"]["low_amount"], str)
    assert all(isinstance(line["amount"], str) for line in payload["elements"])
    # The string total round-trips to the same Decimal.
    assert Decimal(payload["total"]) == build_rom_estimate(_req(currency="EUR")).total


# ── Reconciliation: concept vs live detailed BOQ (pure) ──────────────────────


def _reconcile(**kwargs: object) -> object:
    """Build a reconciliation with sensible defaults for the field under test."""
    base: dict[str, object] = {
        "project_id": uuid.uuid4(),
        "conceptual_total": Decimal("1000000"),
        "detailed_total": Decimal("1000000"),
    }
    base.update(kwargs)
    return build_reconciliation(**base)  # type: ignore[arg-type]


def test_variance_is_detailed_minus_conceptual() -> None:
    """Variance amount is exactly detailed - conceptual, Decimal-exact."""
    rec = _reconcile(conceptual_total=Decimal("1000000"), detailed_total=Decimal("1234567.89"))
    assert rec.variance_amount == Decimal("234567.89")


def test_over_when_detailed_exceeds_concept_beyond_tolerance() -> None:
    """A detailed total 20% above the concept lands in the 'over' band."""
    rec = _reconcile(conceptual_total=Decimal("1000000"), detailed_total=Decimal("1200000"))
    assert rec.status == STATUS_OVER
    assert rec.variance_amount == Decimal("200000")
    assert rec.variance_pct == Decimal("20.00")


def test_under_when_detailed_below_concept_beyond_tolerance() -> None:
    """A detailed total 20% below the concept lands in the 'under' band."""
    rec = _reconcile(conceptual_total=Decimal("1000000"), detailed_total=Decimal("800000"))
    assert rec.status == STATUS_UNDER
    assert rec.variance_amount == Decimal("-200000")
    assert rec.variance_pct == Decimal("-20.00")


def test_on_track_within_tolerance() -> None:
    """Drift inside the tolerance band is on_track."""
    rec = _reconcile(conceptual_total=Decimal("1000000"), detailed_total=Decimal("1050000"))
    assert rec.status == STATUS_ON_TRACK
    assert rec.variance_pct == Decimal("5.00")


def test_tolerance_boundary_is_on_track() -> None:
    """Exactly at the tolerance (+10%) is on_track, not over (strict comparison)."""
    rec = _reconcile(conceptual_total=Decimal("1000000"), detailed_total=Decimal("1100000"))
    assert rec.variance_pct == Decimal("10.00")
    assert rec.status == STATUS_ON_TRACK


def test_no_baseline_when_conceptual_is_none() -> None:
    """No stored concept -> conceptual_total null, variance null, no_baseline."""
    rec = _reconcile(conceptual_total=None, detailed_total=Decimal("500000"))
    assert rec.status == STATUS_NO_BASELINE
    assert rec.conceptual_total is None
    assert rec.variance_amount is None
    assert rec.variance_pct is None
    # The detailed side is still reported honestly.
    assert rec.detailed_total == Decimal("500000")


def test_no_baseline_when_conceptual_is_zero() -> None:
    """A zero concept is not a usable benchmark: no_baseline, variance null (again-zero guard)."""
    rec = _reconcile(conceptual_total=Decimal("0"), detailed_total=Decimal("500000"))
    assert rec.status == STATUS_NO_BASELINE
    assert rec.variance_amount is None
    assert rec.variance_pct is None


def test_no_baseline_when_conceptual_is_negative() -> None:
    """A defensive guard: a negative stored concept also yields no_baseline."""
    rec = _reconcile(conceptual_total=Decimal("-100"), detailed_total=Decimal("500000"))
    assert rec.status == STATUS_NO_BASELINE
    assert rec.variance_pct is None


def test_detailed_zero_with_a_concept_reads_as_fully_under() -> None:
    """With a concept but no BOQ, detailed is 0 and the design is 100% under."""
    rec = _reconcile(conceptual_total=Decimal("1000000"), detailed_total=Decimal("0"), boq_count=0)
    assert rec.detailed_total == Decimal("0")
    assert rec.variance_amount == Decimal("-1000000")
    assert rec.variance_pct == Decimal("-100.00")
    assert rec.status == STATUS_UNDER


def test_currency_prefers_base_and_flags_mismatch() -> None:
    """The reconciliation currency is the BOQ base; a differing concept currency is flagged."""
    rec = _reconcile(currency="EUR", conceptual_currency="USD")
    assert rec.currency == "EUR"
    assert rec.currency_mismatch is True


def test_currency_no_mismatch_when_equal_or_absent() -> None:
    """Matching currencies (or a blank one) are not flagged as a mismatch."""
    same = _reconcile(currency="EUR", conceptual_currency="eur")
    assert same.currency == "EUR"
    assert same.currency_mismatch is False
    # No base currency (no BOQ) falls back to the concept currency, still no flag.
    fallback = _reconcile(currency="", conceptual_currency="GBP")
    assert fallback.currency == "GBP"
    assert fallback.currency_mismatch is False


def test_tolerance_is_configurable_and_absolute() -> None:
    """A custom (even negative) tolerance is applied as an absolute band."""
    rec = _reconcile(
        conceptual_total=Decimal("1000000"),
        detailed_total=Decimal("1070000"),
        tolerance_pct=Decimal("-5"),
    )
    assert rec.tolerance_pct == Decimal("5")
    assert rec.status == STATUS_OVER  # +7% drift exceeds the 5% band


def test_default_tolerance_is_ten_percent() -> None:
    assert Decimal("10") == DEFAULT_RECONCILE_TOLERANCE_PCT


def test_reconciliation_json_emits_money_and_pct_as_strings() -> None:
    """Money and percentage fields serialise as Decimal strings; nulls stay null."""
    payload = _reconcile(
        conceptual_total=Decimal("1000000"),
        detailed_total=Decimal("1200000"),
    ).model_dump(mode="json")
    for key in ("conceptual_total", "detailed_total", "variance_amount", "variance_pct", "tolerance_pct"):
        assert isinstance(payload[key], str), key
    assert Decimal(payload["variance_amount"]) == Decimal("200000")

    null_payload = _reconcile(conceptual_total=None).model_dump(mode="json")
    assert null_payload["conceptual_total"] is None
    assert null_payload["variance_amount"] is None
    assert null_payload["variance_pct"] is None
    # The detailed total is never null - it is "0" at worst.
    assert isinstance(null_payload["detailed_total"], str)


# ── Money parsing helper ─────────────────────────────────────────────────────


def test_parse_money_reads_decimal_strings() -> None:
    assert _parse_money("1234.56") == Decimal("1234.56")
    assert _parse_money(Decimal("10")) == Decimal("10")


def test_parse_money_rejects_unusable_values() -> None:
    assert _parse_money(None) is None
    assert _parse_money("not-a-number") is None
    assert _parse_money("NaN") is None
    assert _parse_money("Infinity") is None
