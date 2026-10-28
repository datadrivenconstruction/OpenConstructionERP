"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure rules of the HSE frame (framework module 11): no database."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.hse_frame import rules
from app.modules.hse_frame.catalogue import (
    HseFrameCatalogue,
    Thresholds,
    resolved_shipped,
    shipped_catalogues,
    validate_hse_frame_catalogue,
)

HAZARDOUS = {"explosives", "diving"}
DE = Thresholds(
    advance_notice_min_working_days=30,
    advance_notice_min_workers=20,
    advance_notice_person_days=500,
    advance_notice_lead_days=14,
    coordinator_min_employers=2,
    later_works_file_with_coordinator=True,
    source_url="https://example.invalid/law",
    review_status="unconfirmed",
)


def _duties(thresholds: Thresholds = DE, **facts: object) -> rules.Duties:
    return rules.duties(rules.Facts(**facts), thresholds, HAZARDOUS)  # type: ignore[arg-type]


def test_a_big_long_site_needs_an_advance_notice() -> None:
    d = _duties(duration_working_days=31, peak_workers=21)
    assert d.advance_notice is True
    assert d.plan is True


def test_the_limits_are_exclusive() -> None:
    d = _duties(duration_working_days=30, peak_workers=20, person_days=500)
    assert d.advance_notice is False


def test_person_days_alone_trigger_the_notice() -> None:
    assert _duties(duration_working_days=10, peak_workers=5, person_days=501).advance_notice is True


def test_missing_facts_are_unknown_not_no_duty() -> None:
    d = _duties()
    assert (d.advance_notice, d.coordinator, d.plan, d.later_works_file) == (None, None, None, None)


def test_one_known_big_figure_decides_even_when_the_rest_is_unknown() -> None:
    assert _duties(person_days=900).advance_notice is True


def test_a_neutral_catalogue_never_decides_a_figure_duty() -> None:
    d = _duties(Thresholds(), duration_working_days=999, peak_workers=999, person_days=999, employers_count=9)
    assert (d.advance_notice, d.coordinator) == (None, None)


def test_hazardous_work_makes_the_plan_compulsory_without_a_notice() -> None:
    d = _duties(duration_working_days=5, peak_workers=3, person_days=10, hazardous_work_codes=("explosives",))
    assert d.advance_notice is False
    assert d.plan is True


def test_no_hazardous_work_counts_only_once_it_was_assessed() -> None:
    small = {"duration_working_days": 5, "peak_workers": 3, "person_days": 10}
    assert _duties(**small).plan is None
    assert _duties(hazardous_works_assessed=True, **small).plan is False


def test_a_code_the_catalogue_does_not_know_is_not_hazardous_work() -> None:
    assert _duties(hazardous_work_codes=("juggling",), hazardous_works_assessed=True).hazardous_work is False


@pytest.mark.parametrize(("employers", "expected"), [(1, False), (2, True), (5, True)])
def test_a_coordinator_is_needed_from_the_threshold_of_employers(employers: int, expected: bool) -> None:
    d = _duties(employers_count=employers)
    assert d.coordinator is expected
    assert d.later_works_file is expected


def test_trigger_lookup() -> None:
    d = _duties(employers_count=3)
    assert d.get(None) is True
    assert d.get("always") is True
    assert d.get("multiple_employers") is True
    assert d.get("advance_notice") is None


def test_a_role_counts_from_its_day_to_its_end_day() -> None:
    today = date(2026, 5, 10)
    assert rules.role_in_force("appointed", date(2026, 5, 10), None, today)
    assert not rules.role_in_force("appointed", date(2026, 5, 11), None, today)
    assert rules.role_in_force("appointed", date(2026, 1, 1), date(2026, 5, 10), today)
    assert not rules.role_in_force("appointed", date(2026, 1, 1), date(2026, 5, 9), today)
    assert not rules.role_in_force("proposed", date(2026, 1, 1), None, today)


def test_items_state() -> None:
    assert rules.items_state([]) == "unknown"
    assert rules.items_state([("recommended", "open")]) == "unknown"
    assert rules.items_state([("mandatory", "met"), ("mandatory", "open")]) == "not_met"
    assert rules.items_state([("mandatory", "met"), ("mandatory", "waived")]) == "met"
    assert rules.items_state([("mandatory", "met"), ("recommended", "open")]) == "warning"


def test_roles_state() -> None:
    assert rules.roles_state([("a", True)], []) == "not_met"
    assert rules.roles_state([("a", True)], ["a"]) == "met"
    assert rules.roles_state([("a", None)], []) == "unknown"
    assert rules.roles_state([("a", False)], []) == "met"
    assert rules.roles_state([("a", True), ("b", None)], ["a"]) == "unknown"


def test_the_advance_notice_is_late_inside_the_lead_time() -> None:
    d = _duties(duration_working_days=40, peak_workers=30)
    today = date(2026, 5, 1)
    assert rules.advance_notice_overdue(d, None, date(2026, 5, 10), 14, today) is True
    assert rules.advance_notice_overdue(d, None, date(2026, 6, 30), 14, today) is False
    assert rules.advance_notice_overdue(d, None, None, 14, today) is None
    assert rules.advance_notice_overdue(d, date(2026, 4, 1), date(2026, 5, 2), 14, today) is False


# ── catalogue ──────────────────────────────────────────────────────────────


def test_the_shipped_catalogues_load_and_the_land_ones_extend_the_country() -> None:
    shipped = shipped_catalogues()
    assert {"neutral", "de", "de_by", "de_bw"} <= set(shipped)
    assert shipped["de"].jurisdiction_countries == ("DE",)
    assert shipped["de_by"].extends == "de"
    assert shipped["de_bw"].extends == "de"


def test_the_neutral_catalogue_states_no_figure() -> None:
    assert not shipped_catalogues()["neutral"].thresholds.has_figure()


def test_a_land_inherits_the_figures_and_replaces_the_template_by_code() -> None:
    by = resolved_shipped("de_by")
    de = resolved_shipped("de")
    assert by.thresholds.advance_notice_min_workers == 20
    mine, base = by.entry("templates", "archaeology_clearance"), de.entry("templates", "archaeology_clearance")
    assert "BayDSchG" in mine.legal_basis
    assert not base.legal_basis
    assert len(by.templates) == len(de.templates)


def test_every_template_names_a_topic_of_the_catalogue() -> None:
    for cid in ("neutral", "de", "de_by", "de_bw"):
        cat = resolved_shipped(cid)
        assert {t.topic for t in cat.templates} <= cat.codes("topics"), cid


def test_every_criterion_of_the_phase_model_has_a_topic() -> None:
    criteria = {t.criterion for t in resolved_shipped("neutral").topics if t.criterion}
    assert criteria == {
        "hse_requirements_issued",
        "environmental_assessment_done",
        "site_clearances_on_file",
        "energy_and_climate_targets_set",
        "sustainability_targets_set",
        "safety_coordination_appointed",
        "security_concept_approved",
    }


def test_a_figure_without_a_source_is_refused() -> None:
    body = HseFrameCatalogue(id="x", thresholds=Thresholds(coordinator_min_employers=2))
    assert "statutory_figure_without_source: thresholds" in validate_hse_frame_catalogue(body, "shipped")


def test_a_law_named_without_a_source_is_refused() -> None:
    body = HseFrameCatalogue.model_validate(
        {"id": "x", "hazardous_works": [{"code": "diving", "legal_basis": "Some Act, section 1"}]}
    )
    assert any(e.startswith("legal_basis_without_source") for e in validate_hse_frame_catalogue(body, "shipped"))
