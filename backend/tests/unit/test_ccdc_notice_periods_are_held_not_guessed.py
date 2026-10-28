# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CCDC is recognised as a standard and carries its own sourced periods.

Two shipped Canadian demo packs declare CCDC 2 (2020) as their contract form.
The normaliser maps every CCDC variant to the CCDC family, which has real
notice periods derived from the contract text (GC 6.1, 6.3, 6.5, 6.6).

Claims and EOT are 10 working days (BUSINESS basis), while quotation (14),
assessment (15) and response (15) are calendar days.  This is the first
standard in the table that mixes day bases, and the working-day entries
differ materially from the standard-neutral fallback of 28 calendar days.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.change_intelligence.time_bar import (
    GENERIC_PERIODS,
    NOTICE_ASSESSMENT,
    NOTICE_CLAIM,
    NOTICE_EOT,
    NOTICE_PERIODS,
    NOTICE_QUOTATION,
    NOTICE_RESPONSE,
    STANDARD_CCDC,
    STANDARD_FIDIC,
    STANDARD_UNKNOWN,
    STATUS_UNKNOWN,
    ClockInput,
    build_clock,
    normalize_standard,
    period_bases_are_complete,
    period_for,
)

ALL_NOTICE_TYPES = (
    NOTICE_CLAIM,
    NOTICE_EOT,
    NOTICE_QUOTATION,
    NOTICE_ASSESSMENT,
    NOTICE_RESPONSE,
)

# ── 1. The form is recognised ────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        # Exactly the two strings the shipped Canadian demo packs declare.
        "CCDC 2 (2020) - stipulated price",
        "CCDC 2 (2020) - contrat à forfait",
        # Other members of the same family, and casing/spacing variants.
        "CCDC 5B (2010)",
        "ccdc 14",
        "  CCDC-2  ",
    ],
)
def test_a_ccdc_contract_form_is_recognised(raw: str) -> None:
    assert normalize_standard(raw) == STANDARD_CCDC


def test_recognising_ccdc_does_not_disturb_the_other_standards() -> None:
    assert normalize_standard("FIDIC Red Book 2017") == STANDARD_FIDIC
    assert normalize_standard("totally made up form") == STANDARD_UNKNOWN
    assert normalize_standard(None) == STANDARD_UNKNOWN
    assert normalize_standard("") == STANDARD_UNKNOWN


# ── 2. CCDC periods are sourced from the contract, not from the generic fallback


CCDC_EXPECTED: dict[str, int] = {
    NOTICE_CLAIM: 10,
    NOTICE_EOT: 10,
    NOTICE_QUOTATION: 14,
    NOTICE_ASSESSMENT: 15,
    NOTICE_RESPONSE: 15,
}


@pytest.mark.parametrize("notice_type", ALL_NOTICE_TYPES)
def test_ccdc_returns_its_own_period_not_the_generic_fallback(notice_type: str) -> None:
    """Each CCDC period comes from GC 6.x, not from the standard-neutral table."""
    actual = period_for(STANDARD_CCDC, notice_type)
    assert actual == CCDC_EXPECTED[notice_type]
    assert actual != GENERIC_PERIODS[notice_type], (
        f"{notice_type}: CCDC period equals the generic fallback ({actual}); "
        "the test cannot distinguish a sourced value from a fallback"
    )


def test_ccdc_is_registered_with_real_periods() -> None:
    """CCDC is in NOTICE_PERIODS with all five notice types populated."""
    assert STANDARD_CCDC in NOTICE_PERIODS
    assert set(NOTICE_PERIODS[STANDARD_CCDC]) == set(ALL_NOTICE_TYPES)


def test_a_genuinely_unknown_standard_still_gets_the_generic_fallback() -> None:
    """Held is not the same as unknown, and only held refuses.

    A record with no recognisable contract form keeps the standard-neutral
    window it has always had; this change narrows nothing except CCDC.
    """
    for notice_type in ALL_NOTICE_TYPES:
        assert period_for(STANDARD_UNKNOWN, notice_type) == GENERIC_PERIODS[notice_type]


def test_every_registered_period_still_states_its_basis() -> None:
    """CCDC carries no day counts, so the density gate is untouched by it.

    The gate returns the names of periods missing a basis, so an empty list is
    the passing answer.
    """
    assert period_bases_are_complete() == []


# ── 3. The CCDC clock carries real periods, not a generic countdown ──────


def _ccdc_clock(*, proof_on_file: bool) -> object:
    standard = normalize_standard("CCDC 2 (2020) - stipulated price")
    return build_clock(
        ClockInput(
            source_kind="variation",
            source_id="1",
            source_ref="VO-001",
            title="Toronto condo variation",
            standard=standard,
            notice_type=NOTICE_CLAIM,
            clause_ref="",
            trigger_date=datetime(2026, 8, 1, tzinfo=UTC),
            period_days=period_for(standard, NOTICE_CLAIM),
            explicit_due=None,
            satisfied_at=None,
            requires_notice=True,
            proof_on_file=proof_on_file,
            is_open=True,
        ),
        now=datetime(2026, 8, 25, tzinfo=UTC),
    )


def test_a_ccdc_clock_carries_the_sourced_period() -> None:
    """The clock is returned with the real CCDC claim period, not None."""
    clock = _ccdc_clock(proof_on_file=False)
    assert clock.standard == STANDARD_CCDC
    assert clock.period_days == 10
    assert clock.deadline is not None
    assert clock.status != STATUS_UNKNOWN


def test_a_ccdc_clock_without_proof_flags_at_risk() -> None:
    """A notice without proof on file is still at risk regardless of the source."""
    assert _ccdc_clock(proof_on_file=False).entitlement_at_risk is True


def test_a_ccdc_clock_does_not_use_the_generic_28_day_period() -> None:
    """The old defect gave CCDC the generic 28 calendar-day fallback.

    CCDC claims are 10 working days (GC 6.6), materially different from 28
    calendar days. A clock that still shows 28 calendar days is sourcing from
    the wrong table.
    """
    clock = _ccdc_clock(proof_on_file=True)
    assert clock.period_days != 28
    assert clock.deadline != datetime(2026, 8, 29, tzinfo=UTC)
