# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ``formwork`` rule set, exercised through the core validation engine.

No database: the rules are pure and read plain dicts, so these drive
``evaluate_assignment`` / ``evaluate_project`` directly. That is also the
honest test of the wiring - a rule that is registered but never requested by
rule-set name is dormant, and going through the engine is what proves it runs.

Each test names the rule it is about and asserts on that rule id, so removing
the rule (or breaking its trigger) fails the test rather than quietly reducing
the finding count.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.formwork.schemas import FormworkValidationReport
from app.modules.formwork.validators import (
    FORMWORK_RULE_SET,
    evaluate_assignment,
    evaluate_project,
    register_formwork_rules,
)

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
ASSIGNMENT_ID = "22222222-2222-2222-2222-222222222222"
POSITION_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def _rules_registered():
    """Re-register before each test.

    The registry is process-global and another module's test may have replaced
    a rule set; re-registering is idempotent and makes this file independent of
    collection order.
    """
    register_formwork_rules()


def _assignment(**overrides: Any) -> dict[str, Any]:
    """A clean assignment payload that fires no rule, plus overrides."""
    base: dict[str, Any] = {
        "id": ASSIGNMENT_ID,
        "project_id": PROJECT_ID,
        "boq_position_id": POSITION_ID,
        "formwork_system_id": "44444444-4444-4444-4444-444444444444",
        "area_m2": "800.00",
        "reuse_count": 4,
        "waste_pct": "5.00",
        "computed_unit_cost": "31.06",
        "computed_total": "24848.00",
        "notes": "L02 core walls",
        "system_name": "Framed steel panel",
        "system_unit_rate": "65.00",
        "erect_strike_rate": "16.00",
        "reuses_max": 100,
        "strip_time_days": 1,
        "currency": "EUR",
        "derived_reuse_count": 4,
        "dated_pour_count": 0,
        "cycle_conflicts": [],
    }
    base.update(overrides)
    return base


def _pours(*areas: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"55555555-5555-5555-5555-55555555555{i}",
            "pour_no": i + 1,
            "pour_date": None,
            "level_label": f"L{i + 1:02d}",
            "area_m2": area,
        }
        for i, area in enumerate(areas)
    ]


def _fired(report: FormworkValidationReport) -> set[str]:
    return {finding.rule_id for finding in report.findings}


# ── the clean baseline ──────────────────────────────────────────────────────


async def test_a_well_formed_assignment_fires_no_rule():
    """The baseline must be clean, or every other test proves nothing."""
    report = await evaluate_assignment(
        {"assignment": _assignment(), "pours": _pours("200", "200", "200", "200")},
        project_id=PROJECT_ID,
    )
    assert _fired(report) == set()
    assert report.status == "passed"
    assert report.error_count == 0
    assert report.passed_count > 0


async def test_the_rule_set_is_actually_registered():
    """A requested rule set with no rules reports unsupported, not passed."""
    report = await evaluate_assignment({"assignment": _assignment(), "pours": []}, project_id=PROJECT_ID)
    assert report.unsupported_rule_sets == []
    assert FORMWORK_RULE_SET == "formwork"


# ── formwork.rate_present ───────────────────────────────────────────────────


async def test_a_system_with_no_rates_at_all_is_an_error():
    report = await evaluate_assignment(
        {
            "assignment": _assignment(system_unit_rate="0", erect_strike_rate="0"),
            "pours": [],
        },
        project_id=PROJECT_ID,
    )
    assert "formwork.rate_present" in _fired(report)
    assert report.error_count >= 1
    assert report.status == "errors"


async def test_a_labour_only_system_is_accepted():
    """Hired panels with the hire in the preliminaries still price the labour."""
    report = await evaluate_assignment(
        {"assignment": _assignment(system_unit_rate="0"), "pours": []},
        project_id=PROJECT_ID,
    )
    assert "formwork.rate_present" not in _fired(report)


# ── formwork.reuse_within_limit / reuse_near_limit ──────────────────────────


async def test_reuse_beyond_the_system_cap_is_an_error():
    report = await evaluate_assignment(
        {"assignment": _assignment(reuse_count=120, reuses_max=100), "pours": []},
        project_id=PROJECT_ID,
    )
    assert "formwork.reuse_within_limit" in _fired(report)


async def test_reuse_at_the_cap_warns_about_headroom_without_erroring():
    report = await evaluate_assignment(
        {"assignment": _assignment(reuse_count=100, reuses_max=100), "pours": []},
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.reuse_near_limit" in fired
    assert "formwork.reuse_within_limit" not in fired


async def test_reuse_at_ninety_percent_of_the_cap_is_still_clean():
    """The headroom band is 10 percent, so 90 of 100 must not warn."""
    report = await evaluate_assignment(
        {"assignment": _assignment(reuse_count=90, reuses_max=100), "pours": []},
        project_id=PROJECT_ID,
    )
    assert "formwork.reuse_near_limit" not in _fired(report)


async def test_over_cap_does_not_also_raise_the_headroom_warning():
    """One finding per problem: the error already says the count is too high."""
    report = await evaluate_assignment(
        {"assignment": _assignment(reuse_count=150, reuses_max=100), "pours": []},
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.reuse_within_limit" in fired
    assert "formwork.reuse_near_limit" not in fired


# ── formwork.reuse_supported_by_schedule ────────────────────────────────────


async def test_a_reuse_count_the_schedule_does_not_deliver_warns():
    """Priced over 8 uses, but the cycle only turns the set around 4 times."""
    report = await evaluate_assignment(
        {
            "assignment": _assignment(reuse_count=8, derived_reuse_count=4),
            "pours": _pours("200", "200", "200", "200"),
        },
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.reuse_supported_by_schedule" in fired
    finding = next(f for f in report.findings if f.rule_id == "formwork.reuse_supported_by_schedule")
    assert finding.context["reuse_count"] == 8
    assert finding.context["derived_reuse_count"] == 4


async def test_pricing_below_what_the_schedule_supports_is_not_flagged():
    """Conservative is fine - only optimism is a finding."""
    report = await evaluate_assignment(
        {
            "assignment": _assignment(reuse_count=2, derived_reuse_count=4, area_m2="800.00"),
            "pours": _pours("200", "200", "200", "200"),
        },
        project_id=PROJECT_ID,
    )
    assert "formwork.reuse_supported_by_schedule" not in _fired(report)


async def test_no_schedule_means_no_opinion_on_the_reuse_count():
    """An undescribed cycle cannot contradict the typed count."""
    report = await evaluate_assignment(
        {"assignment": _assignment(reuse_count=40, derived_reuse_count=0), "pours": []},
        project_id=PROJECT_ID,
    )
    assert "formwork.reuse_supported_by_schedule" not in _fired(report)


# ── formwork.schedule_area_matches ──────────────────────────────────────────


async def test_pour_areas_that_disagree_with_the_priced_area_warn():
    report = await evaluate_assignment(
        {"assignment": _assignment(area_m2="800.00"), "pours": _pours("200", "200")},
        project_id=PROJECT_ID,
    )
    assert "formwork.schedule_area_matches" in _fired(report)


async def test_a_small_drift_stays_inside_the_tolerance():
    """805 against 800 is 0.6 percent - inside the 5 percent band."""
    report = await evaluate_assignment(
        {"assignment": _assignment(area_m2="800.00"), "pours": _pours("200", "200", "200", "205")},
        project_id=PROJECT_ID,
    )
    assert "formwork.schedule_area_matches" not in _fired(report)


async def test_a_scheduled_cycle_priced_against_no_area_warns():
    report = await evaluate_assignment(
        {"assignment": _assignment(area_m2="0"), "pours": _pours("200", "200")},
        project_id=PROJECT_ID,
    )
    assert "formwork.schedule_area_matches" in _fired(report)


# ── formwork.pour_numbers_unique ────────────────────────────────────────────


async def test_duplicate_pour_numbers_are_an_error():
    pours = _pours("200", "200")
    pours[1]["pour_no"] = pours[0]["pour_no"]
    report = await evaluate_assignment(
        {"assignment": _assignment(area_m2="400.00", derived_reuse_count=2, reuse_count=2), "pours": pours},
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.pour_numbers_unique" in fired
    finding = next(f for f in report.findings if f.rule_id == "formwork.pour_numbers_unique")
    assert finding.context["duplicate_pour_numbers"] == [1]


# ── formwork.strip_time_respected ───────────────────────────────────────────


async def test_a_cycle_faster_than_the_striking_time_warns():
    report = await evaluate_assignment(
        {
            "assignment": _assignment(
                strip_time_days=7,
                dated_pour_count=2,
                cycle_conflicts=[
                    {"from_pour_no": 1, "to_pour_no": 2, "gap_days": 3, "required_days": 7},
                ],
            ),
            "pours": _pours("200", "200", "200", "200"),
        },
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.strip_time_respected" in fired
    finding = next(f for f in report.findings if f.rule_id == "formwork.strip_time_respected")
    assert finding.context["conflict_count"] == 1
    assert finding.context["strip_time_days"] == 7


async def test_fewer_than_two_dated_pours_is_not_a_striking_time_finding():
    """With one date there is no gap to be too short."""
    report = await evaluate_assignment(
        {
            "assignment": _assignment(strip_time_days=14, dated_pour_count=1, cycle_conflicts=[]),
            "pours": _pours("200", "200", "200", "200"),
        },
        project_id=PROJECT_ID,
    )
    assert "formwork.strip_time_respected" not in _fired(report)


# ── formwork.waste_within_band ──────────────────────────────────────────────


@pytest.mark.parametrize("waste", ["0.00", "5.00", "15.00"])
async def test_plausible_waste_is_accepted(waste: str):
    report = await evaluate_assignment(
        {"assignment": _assignment(waste_pct=waste), "pours": []},
        project_id=PROJECT_ID,
    )
    assert "formwork.waste_within_band" not in _fired(report)


async def test_waste_above_the_band_warns():
    report = await evaluate_assignment(
        {"assignment": _assignment(waste_pct="45.00"), "pours": []},
        project_id=PROJECT_ID,
    )
    assert "formwork.waste_within_band" in _fired(report)


# ── formwork.boq_position_linked ────────────────────────────────────────────


async def test_an_unlinked_assignment_is_reported_as_info():
    report = await evaluate_assignment(
        {"assignment": _assignment(boq_position_id=None), "pours": []},
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.boq_position_linked" in fired
    # INFO only - it must not block, and it must not read as an error.
    assert report.error_count == 0
    assert report.info_count >= 1
    assert report.status == "info"


# ── project scope ───────────────────────────────────────────────────────────


async def test_mixed_currencies_across_a_project_are_an_error():
    report = await evaluate_project(
        {
            "assignments": [
                _assignment(id="a", currency="EUR"),
                _assignment(id="b", currency="GBP"),
            ],
        },
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.currency_consistent" in fired
    finding = next(f for f in report.findings if f.rule_id == "formwork.currency_consistent")
    assert finding.context["currencies"] == ["EUR", "GBP"]


async def test_one_currency_across_a_project_is_clean():
    report = await evaluate_project(
        {
            "assignments": [
                _assignment(id="a", currency="EUR", boq_position_id="p1"),
                _assignment(id="b", currency="EUR", boq_position_id="p2"),
            ],
        },
        project_id=PROJECT_ID,
    )
    assert _fired(report) == set()


async def test_two_assignments_on_one_boq_position_warn():
    report = await evaluate_project(
        {
            "assignments": [
                _assignment(id="a", boq_position_id=POSITION_ID),
                _assignment(id="b", boq_position_id=POSITION_ID),
            ],
        },
        project_id=PROJECT_ID,
    )
    fired = _fired(report)
    assert "formwork.boq_position_unique" in fired
    finding = next(f for f in report.findings if f.rule_id == "formwork.boq_position_unique")
    assert finding.context["count"] == 1


async def test_unlinked_assignments_do_not_collide_with_each_other():
    """Two assignments with no BOQ position are not both on 'the same' one."""
    report = await evaluate_project(
        {
            "assignments": [
                _assignment(id="a", boq_position_id=None),
                _assignment(id="b", boq_position_id=None),
            ],
        },
        project_id=PROJECT_ID,
    )
    assert "formwork.boq_position_unique" not in _fired(report)


# ── scope isolation ─────────────────────────────────────────────────────────


async def test_project_rules_stay_silent_on_an_assignment_pass():
    """Cross-assignment rules must not report a pass they never performed."""
    report = await evaluate_assignment(
        {"assignment": _assignment(currency="EUR"), "pours": []},
        project_id=PROJECT_ID,
    )
    rule_ids = {f.rule_id for f in report.findings}
    assert "formwork.currency_consistent" not in rule_ids
    assert "formwork.boq_position_unique" not in rule_ids


async def test_assignment_rules_stay_silent_on_a_project_pass():
    report = await evaluate_project(
        {"assignments": [_assignment(reuse_count=999, reuses_max=10)]},
        project_id=PROJECT_ID,
    )
    assert "formwork.reuse_within_limit" not in _fired(report)


# ── payload robustness ──────────────────────────────────────────────────────


async def test_unparseable_numbers_degrade_instead_of_crashing():
    """Validation augments a read path; a bad value must not raise."""
    report = await evaluate_assignment(
        {"assignment": _assignment(waste_pct="not-a-number", area_m2="also-not"), "pours": []},
        project_id=PROJECT_ID,
    )
    assert isinstance(report, FormworkValidationReport)
    assert report.status in {"passed", "warnings", "errors", "info"}


async def test_an_empty_project_reports_no_findings():
    report = await evaluate_project({"assignments": []}, project_id=PROJECT_ID)
    assert report.findings == []
