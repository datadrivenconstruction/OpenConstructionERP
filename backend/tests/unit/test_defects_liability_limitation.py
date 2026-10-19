# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the opt-in limitation regime on the defects-liability register.

Two things are being proved here and they pull in opposite directions.

The first is that the feature is right for the person who needs it: four years
under the VOB/B, five under the BGB, counted from Abnahme the way § 188 BGB
counts, and a recorded period that contradicts the regime it names gets reported
rather than silently corrected.

The second is that the feature does not exist for anybody else. An entry that
never named a regime must derive no date, lose no date, gain no finding and cause
no review, and it must do all of that even when its own numbers are a mess - the
case a half-careful implementation trips on, because it is tempting to derive a
date whenever the arithmetic happens to be possible. Those tests are written
against an entry that has a start date to derive from and a period that
disagrees with itself, so a regression that quietly starts deriving or reporting
is caught rather than looking like a no-op.

The service-layer derivation is driven through transient ORM instances with no
session, which is what :func:`_apply_derived_period` actually operates on, so
the whole file runs with no database.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.validation.engine import Severity, rule_registry
from app.modules.defects_liability import limitation
from app.modules.defects_liability.models import DlpWarranty
from app.modules.defects_liability.schemas import LimitationRegimeLiteral, WarrantyResponse
from app.modules.defects_liability.service import (
    DefectsLiabilityService,
    _apply_derived_period,
    limitation_snapshot,
)
from app.modules.defects_liability.validators import (
    DEFECTS_LIABILITY_RULE_SET,
    LimitationPeriodMatchesRegime,
    LimitationRegimeNeedsStartDate,
    evaluate_limitation,
)

# A fixed acceptance date so every derived date in this file is exact.
ACCEPTANCE = date(2026, 3, 1)


@pytest.fixture(autouse=True)
def _rules_registered():
    """Put the module's rules in the process-global registry before each test.

    The registry is populated by the application's startup hooks, which no test
    process runs. Without this the engine reports the rule set as unsupported and
    returns a clean report - indistinguishable from the rules having run and found
    nothing, which is exactly the false green these tests exist to prevent.
    """
    from app.modules.defects_liability.validators import register_defects_liability_rules

    register_defects_liability_rules()


# -- Builders ----------------------------------------------------------------


def _warranty(**kwargs: Any) -> DlpWarranty:
    """A transient warranty row with the fields the limitation code reads."""
    defaults: dict[str, Any] = {
        "reference": "DLP-001",
        "title": "Curtain wall",
        "limitation_regime": None,
        "handover_date": None,
        "warranty_start_date": None,
        "warranty_months": None,
        "warranty_end_date": None,
        "dlp_end_date": None,
    }
    defaults.update(kwargs)
    return DlpWarranty(**defaults)


async def _findings(warranty: DlpWarranty) -> list:
    """The failing findings the limitation rules raise about one entry."""
    return await evaluate_limitation(limitation_snapshot(warranty), warranty_id="w1")


# -- The shipped regimes -----------------------------------------------------


def test_the_german_regimes_are_the_four_and_five_year_ones():
    """The whole point of the feature is that these two numbers differ by a year."""
    by_code = {spec.code: spec for spec in limitation.LIMITATION_REGIMES}
    assert set(by_code) == {
        "de_vob_b",
        "de_bgb",
        "eg_civil_651",
        "fr_civil_1792_6",
        "fr_civil_1792_3",
        "fr_civil_1792",
        "sa_sbc_decennial",
    }
    assert by_code["de_vob_b"].months == 48
    assert by_code["de_bgb"].months == 60


def test_every_regime_names_the_provision_it_comes_from():
    """A derived date with no citation would be the same unjustified date as before."""
    for spec in limitation.LIMITATION_REGIMES:
        assert spec.statute.strip()
        assert spec.statute_reference.strip()
        assert spec.notes.strip()
        assert spec.country_code in ("DE", "EG", "FR", "SA")
        assert spec.starts_from in limitation.LIMITATION_STARTS
    assert "VOB/B" in limitation.regime_for("de_vob_b").statute
    assert "BGB" in limitation.regime_for("de_bgb").statute


def test_the_api_literal_is_pinned_to_the_shipped_vocabulary():
    """A drift here would let a value through the door the arithmetic has no regime for."""
    assert set(LimitationRegimeLiteral.__args__) == set(limitation.ALL_LIMITATION_REGIMES)


def test_an_unknown_regime_code_is_inert_rather_than_fatal():
    """A stray value fails to match, matching the register's vocabulary convention."""
    assert limitation.regime_for("de_wishful") is None
    assert limitation.regime_for(None) is None
    assert limitation.derive_period("de_wishful", ACCEPTANCE) is None


# -- Counting the period -----------------------------------------------------


def test_vob_b_runs_four_years_from_acceptance():
    derived = limitation.derive_period("de_vob_b", ACCEPTANCE)
    assert derived is not None
    assert derived.months == 48
    assert derived.end_date == date(2030, 3, 1)


def test_bgb_runs_five_years_from_acceptance():
    derived = limitation.derive_period("de_bgb", ACCEPTANCE)
    assert derived is not None
    assert derived.months == 60
    assert derived.end_date == date(2031, 3, 1)


def test_the_two_regimes_are_a_year_apart_on_the_same_acceptance_date():
    """The difference that decides whether a claim can still be brought."""
    vob = limitation.derive_period("de_vob_b", ACCEPTANCE)
    bgb = limitation.derive_period("de_bgb", ACCEPTANCE)
    assert (bgb.end_date - vob.end_date).days == 365


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        # § 188 Abs. 3 BGB: where the final month has no matching day, the period
        # ends on its last day. Non-leap and leap targets both.
        (date(2024, 8, 31), 6, date(2025, 2, 28)),
        (date(2023, 8, 31), 6, date(2024, 2, 29)),
        (date(2026, 5, 31), 48, date(2030, 5, 31)),
        # An acceptance on a leap day: four years later the day exists, five
        # years later it does not.
        (date(2024, 2, 29), 48, date(2028, 2, 29)),
        (date(2024, 2, 29), 60, date(2029, 2, 28)),
        # Year rollover arithmetic, and the degenerate zero-month period.
        (date(2026, 12, 31), 1, date(2027, 1, 31)),
        (date(2026, 3, 1), 0, date(2026, 3, 1)),
    ],
)
def test_the_period_end_is_always_a_real_calendar_day(start: date, months: int, expected: date):
    assert limitation.add_months(start, months) == expected


def test_the_acceptance_date_falls_back_to_handover():
    """Both regimes run from Abnahme; the explicitly recorded start wins."""
    assert limitation.limitation_start(date(2026, 4, 1), date(2026, 3, 1)) == date(2026, 4, 1)
    assert limitation.limitation_start(None, date(2026, 3, 1)) == date(2026, 3, 1)
    assert limitation.limitation_start(None, None) is None


def test_no_acceptance_date_derives_nothing_rather_than_inventing_one():
    """The failure the whole feature exists to prevent."""
    assert limitation.derive_period("de_vob_b", None) is None


# -- The opt-in, at the layer that writes ------------------------------------


def test_an_entry_with_no_regime_is_untouched_even_when_a_date_could_be_derived():
    """The case a naive implementation derives anyway: everything present but the choice."""
    warranty = _warranty(warranty_start_date=ACCEPTANCE, handover_date=ACCEPTANCE, dlp_end_date=date(2027, 3, 1))
    _apply_derived_period(warranty, set())
    assert warranty.limitation_regime is None
    assert warranty.warranty_months is None
    assert warranty.warranty_end_date is None
    assert warranty.dlp_end_date == date(2027, 3, 1)


def test_choosing_a_regime_fills_the_period_the_caller_left_open():
    warranty = _warranty(limitation_regime="de_vob_b", warranty_start_date=ACCEPTANCE)
    _apply_derived_period(warranty, {"limitation_regime"})
    assert warranty.warranty_months == 48
    assert warranty.warranty_end_date == date(2030, 3, 1)


def test_a_period_typed_in_the_same_payload_wins_over_the_derived_one():
    """The derivation fills what the caller left open; it never argues with what they wrote."""
    warranty = _warranty(
        limitation_regime="de_vob_b",
        warranty_start_date=ACCEPTANCE,
        warranty_months=36,
        warranty_end_date=date(2029, 3, 1),
    )
    _apply_derived_period(warranty, {"limitation_regime", "warranty_months", "warranty_end_date"})
    assert warranty.warranty_months == 36
    assert warranty.warranty_end_date == date(2029, 3, 1)


def test_a_regime_with_no_acceptance_date_writes_nothing_at_all():
    warranty = _warranty(limitation_regime="de_bgb", warranty_months=None, warranty_end_date=None)
    _apply_derived_period(warranty, {"limitation_regime"})
    assert warranty.warranty_months is None
    assert warranty.warranty_end_date is None


def test_the_retention_clock_is_never_derived_from_a_statutory_period():
    """dlp_end_date decides when retention money is released; a Verjährungsfrist must not move it."""
    preset = _warranty(limitation_regime="de_bgb", warranty_start_date=ACCEPTANCE, dlp_end_date=date(2027, 3, 1))
    _apply_derived_period(preset, {"limitation_regime"})
    assert preset.dlp_end_date == date(2027, 3, 1)

    unset = _warranty(limitation_regime="de_bgb", warranty_start_date=ACCEPTANCE)
    _apply_derived_period(unset, {"limitation_regime"})
    assert unset.dlp_end_date is None


# -- The opt-in, at the layer that reports -----------------------------------


@pytest.mark.asyncio
async def test_a_regime_free_entry_raises_no_finding_even_when_its_own_period_disagrees():
    """No regime means no reason to check against, so there is nothing to nag about.

    The entry here is internally inconsistent on purpose - a 999-month period
    ending three years after acceptance - so a rule that started examining
    regime-free rows would have plenty to say and this test would catch it.
    """
    warranty = _warranty(
        warranty_start_date=ACCEPTANCE,
        handover_date=ACCEPTANCE,
        warranty_months=999,
        warranty_end_date=date(2029, 3, 1),
    )
    assert await _findings(warranty) == []


@pytest.mark.asyncio
async def test_a_month_count_that_contradicts_its_regime_is_reported():
    warranty = _warranty(limitation_regime="de_vob_b", warranty_start_date=ACCEPTANCE, warranty_months=60)
    findings = await _findings(warranty)
    matched = [f for f in findings if f.rule_id == LimitationPeriodMatchesRegime.rule_id]
    assert len(matched) == 1
    assert matched[0].severity == Severity.WARNING
    assert matched[0].details["statutory_months"] == 48
    assert matched[0].details["recorded_months"] == 60
    assert "VOB/B" in matched[0].message


@pytest.mark.asyncio
async def test_an_end_date_that_contradicts_its_regime_is_reported_with_the_gap():
    """A BGB entry ending on the VOB/B date is the exact year that decides a claim."""
    warranty = _warranty(
        limitation_regime="de_bgb",
        warranty_start_date=ACCEPTANCE,
        warranty_end_date=date(2030, 3, 1),
    )
    findings = await _findings(warranty)
    matched = [f for f in findings if f.rule_id == LimitationPeriodMatchesRegime.rule_id]
    assert len(matched) == 1
    assert matched[0].details["statutory_end_date"] == "2031-03-01"
    assert matched[0].details["difference_days"] == -365


@pytest.mark.asyncio
async def test_a_period_that_agrees_with_its_regime_raises_nothing():
    warranty = _warranty(
        limitation_regime="de_vob_b",
        warranty_start_date=ACCEPTANCE,
        warranty_months=48,
        warranty_end_date=date(2030, 3, 1),
    )
    assert await _findings(warranty) == []


@pytest.mark.asyncio
async def test_a_regime_with_nothing_to_count_from_is_reported():
    warranty = _warranty(limitation_regime="de_vob_b")
    findings = await _findings(warranty)
    assert [f.rule_id for f in findings] == [LimitationRegimeNeedsStartDate.rule_id]
    assert "Abnahme" in findings[0].message


@pytest.mark.asyncio
async def test_the_startup_hook_is_what_puts_the_rules_in_the_registry():
    """Importing the validators module is not enough; the hook has to call the registrar."""
    from app.modules.defects_liability import on_startup

    await on_startup()
    ids = {rule.rule_id for rule in rule_registry.get_rules_for_sets([DEFECTS_LIABILITY_RULE_SET])}
    assert ids == {
        LimitationPeriodMatchesRegime.rule_id,
        LimitationRegimeNeedsStartDate.rule_id,
    }


# -- The review, and what an untouched project sees --------------------------


class _StubService(DefectsLiabilityService):
    """The service with its one query replaced, so the review runs with no database."""

    def __init__(self, rows: list[DlpWarranty]) -> None:
        super().__init__(session=None)  # type: ignore[arg-type]
        self._rows = rows

    async def list_warranties(self, project_id, **kwargs) -> list[DlpWarranty]:  # noqa: ANN001, ARG002
        return self._rows


@pytest.mark.asyncio
async def test_a_project_where_nobody_chose_a_regime_reviews_nothing():
    """Not "reviewed and clean" - not looked at, which is what the screen keys off."""
    import uuid

    rows = [
        _warranty(reference="DLP-001", warranty_start_date=ACCEPTANCE, warranty_months=999),
        _warranty(reference="DLP-002", warranty_end_date=date(2029, 3, 1)),
    ]
    review = await _StubService(rows).review_limitation_periods(uuid.uuid4())
    assert review["total"] == 2
    assert review["reviewed_count"] == 0
    assert review["regimes_in_use"] == []
    assert review["findings"] == []


@pytest.mark.asyncio
async def test_the_review_reports_only_the_entries_that_named_a_regime():
    import uuid

    rows = [
        _warranty(reference="DLP-001", warranty_start_date=ACCEPTANCE, warranty_months=999),
        _warranty(
            reference="DLP-002",
            limitation_regime="de_vob_b",
            warranty_start_date=ACCEPTANCE,
            warranty_months=60,
        ),
    ]
    review = await _StubService(rows).review_limitation_periods(uuid.uuid4())
    assert review["total"] == 2
    assert review["reviewed_count"] == 1
    assert review["regimes_in_use"] == ["de_vob_b"]
    assert [f["reference"] for f in review["findings"]] == ["DLP-002"]
    assert review["findings"][0]["severity"] == "warning"


# -- What the API says about an entry either way -----------------------------


def _response(**kwargs: Any) -> WarrantyResponse:
    import uuid
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "reference": "DLP-001",
        "title": "Curtain wall",
        "status": "in_dlp",
        "sort_order": 0,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(kwargs)
    return WarrantyResponse(**payload)


def test_the_derived_limitation_view_is_empty_for_an_entry_with_no_regime():
    response = _response(warranty_start_date=ACCEPTANCE, warranty_months=48, warranty_end_date=date(2030, 3, 1))
    assert response.limitation_regime is None
    assert response.limitation_statute is None
    assert response.limitation_months is None
    assert response.limitation_end_date is None


def test_the_derived_limitation_view_names_the_statute_once_a_regime_is_chosen():
    response = _response(limitation_regime="de_bgb", warranty_start_date=ACCEPTANCE)
    assert "BGB" in response.limitation_statute
    assert response.limitation_months == 60
    assert response.limitation_end_date == date(2031, 3, 1)


def test_a_chosen_regime_with_no_acceptance_date_shows_no_computed_date():
    response = _response(limitation_regime="de_vob_b")
    assert response.limitation_months == 48
    assert response.limitation_end_date is None
