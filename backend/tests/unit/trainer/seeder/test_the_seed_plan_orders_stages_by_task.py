# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seed plan: which ERP objects a course seeds, at which stage, in which order.

Pure: no database. Every red case is one edit of the synthetic fixture course,
run through the same parse the loader runs, so the plan sees exactly what a
stored course hands it.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.trainer.loader import parse_course_bytes
from app.modules.trainer.seeder import (
    ENROLMENT_STAGES,
    PlanError,
    SeedContext,
    build_plan,
    reading_timestamp,
    seeding,
    seeding_enrolment,
    stage_key,
)
from app.modules.trainer.seeder.plan import (
    bid_recorded_by_seed,
    period_window,
    section_line_ordinal,
    seeded_position_ordinals,
    stage_rank,
)
from app.modules.trainer.seeder.stages import _json_number, _markup_create
from app.modules.trainer.spec import BidSeed, CourseSpec, MarkupSeed, SectionSeed, Stage

COURSE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "trainer" / "course_fixture_v1.json"


@pytest.fixture(scope="module")
def raw_course() -> dict[str, Any]:
    return json.loads(COURSE_PATH.read_text(encoding="utf-8"))


def _stored(raw: dict[str, Any]) -> dict[str, Any]:
    """The spec dict a course row stores, through the loader's own parse."""
    parsed = parse_course_bytes(json.dumps(raw).encode("utf-8"), "course_fixture_v1.json")
    assert parsed.errors == [], parsed.errors
    assert parsed.spec is not None
    return parsed.spec


def _plan_errors(raw: dict[str, Any]) -> list[str]:
    with pytest.raises(PlanError) as info:
        build_plan(_stored(raw))
    return info.value.problems


@pytest.fixture
def course(raw_course: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(raw_course)


# ── The fixture's plan ───────────────────────────────────────────────────────


def test_unlock_and_pass_wording_parse_to_stages(raw_course: dict[str, Any]) -> None:
    plan = build_plan(_stored(raw_course))
    assert [stage_key(s) for s in plan.stages] == [
        "on_enrol",
        "on_unlock(1)",
        "on_unlock(3)",
        "on_unlock(4)",
        "on_unlock(5)",
    ]
    assert [(stage_key(s.stage), s.kind, s.ref_key) for s in plan.steps] == [
        ("on_enrol", "project", "project"),
        ("on_unlock(1)", "boq", "boq.main"),
        ("on_unlock(3)", "bid_package", "bid_package.main"),
        ("on_unlock(4)", "contract", "contract.main"),
        ("on_unlock(4)", "progress_readings", "progress.1"),
        ("on_unlock(5)", "variation_request", "variation_request.1"),
    ]


def test_contract_stage_lands_on_t4(raw_course: dict[str, Any]) -> None:
    plan = build_plan(_stored(raw_course))
    t4 = plan.for_stage(Stage("on_unlock", 4))
    # The contract is signed before its readings are written, in that order.
    assert [s.kind for s in t4] == ["contract", "progress_readings"]
    assert plan.for_stage(Stage("on_unlock", 2)) == []


def test_the_plan_accepts_the_validated_model_and_the_stored_dict(raw_course: dict[str, Any]) -> None:
    stored = _stored(raw_course)
    from_dict = build_plan(stored)
    from_model = build_plan(CourseSpec.model_validate(stored))
    assert from_dict.steps == from_model.steps


def test_enrolment_runs_on_enrol_and_the_first_unlock() -> None:
    assert [stage_key(s) for s in ENROLMENT_STAGES] == ["on_enrol", "on_unlock(1)"]
    assert stage_rank(Stage("on_enrol")) == 0
    assert stage_rank(Stage("on_unlock", 4)) == 4


def test_the_surety_bond_row_and_parties_are_not_seeded(raw_course: dict[str, Any]) -> None:
    # The surety bands are an academy action the learner runs (design §5.5);
    # parties are not written as contacts. Neither is a plan step.
    plan = build_plan(_stored(raw_course))
    assert {s.kind for s in plan.steps} == {
        "project",
        "boq",
        "bid_package",
        "contract",
        "progress_readings",
        "variation_request",
    }


def test_a_variation_without_an_erp_request_is_instruction_only(course: dict[str, Any]) -> None:
    del course["seed"]["variations"][0]["erp_request"]
    plan = build_plan(_stored(course))
    assert all(s.kind != "variation_request" for s in plan.steps)


# ── progress_link decides which lines are read ───────────────────────────────


def test_progress_link_decides_which_lines_carry_readings(course: dict[str, Any]) -> None:
    # Design §5.3 linked "exactly the lines that have a reading"; the course now
    # says it per line. C04 is ``none``: a reading on it could never be read.
    course["seed"]["progress_readings"][0]["readings"].append({"line_code": "C04", "percent_complete": 10})
    problems = _plan_errors(course)
    assert len(problems) == 1
    assert "line C04 has progress_link none" in problems[0]


def test_us_by_hand_lines_stay_unlinked(course: dict[str, Any]) -> None:
    # A by_hand reading is typed by the learner, so a ``none`` line is fine there.
    course["seed"]["progress_readings"][0]["by_hand"] = [{"line_code": "C04", "percent_complete": 10}]
    plan = build_plan(_stored(course))
    assert [s.ref_key for s in plan.steps if s.kind == "progress_readings"] == ["progress.1"]


def test_a_reading_on_a_line_the_schedule_does_not_have_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["progress_readings"][0]["readings"][0]["line_code"] = "C99"
    assert any("line C99 is not a line of the schedule of values" in p for p in _plan_errors(course))


def test_a_reading_outside_zero_to_hundred_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["progress_readings"][0]["readings"][1]["percent_complete"] = 150
    assert any("percent_complete 150 is outside 0-100" in p for p in _plan_errors(course))


def test_a_line_read_twice_in_one_period_is_refused(course: dict[str, Any]) -> None:
    readings = course["seed"]["progress_readings"][0]["readings"]
    readings.append(dict(readings[0]))
    assert any("line C01 is read twice" in p for p in _plan_errors(course))


def test_readings_before_the_contract_are_refused(course: dict[str, Any]) -> None:
    course["seed"]["progress_readings"][0]["stage"] = "on_unlock(3)"
    assert any("runs before the contract" in p for p in _plan_errors(course))


def test_readings_without_a_contract_are_refused(course: dict[str, Any]) -> None:
    del course["seed"]["contract"]
    assert any("the course seeds no contract" in p for p in _plan_errors(course))


def test_readings_run_in_period_order(course: dict[str, Any]) -> None:
    first = course["seed"]["progress_readings"][0]
    second = copy.deepcopy(first)
    second.update({"stage": "on_unlock(5)", "period_from": "2026-11-01", "period_to": "2026-11-30"})
    course["seed"]["progress_readings"] = [second, first]
    plan = build_plan(_stored(course))
    steps = [s for s in plan.steps if s.kind == "progress_readings"]
    # File order is second, first; the plan runs the earlier period first.
    assert [(s.ref_key, s.index) for s in steps] == [("progress.2", 1), ("progress.1", 0)]


def test_a_later_stage_reading_an_earlier_period_is_refused(course: dict[str, Any]) -> None:
    first = course["seed"]["progress_readings"][0]
    earlier = copy.deepcopy(first)
    earlier.update({"stage": "on_unlock(5)", "period_from": "2026-09-01", "period_to": "2026-09-30"})
    course["seed"]["progress_readings"].append(earlier)
    assert any("must cover a later period" in p for p in _plan_errors(course))


# ── Cross references between blocks ──────────────────────────────────────────


def test_the_project_is_seeded_on_enrol(course: dict[str, Any]) -> None:
    course["seed"]["project"]["stage"] = "on_unlock(1)"
    assert any("the project must be seeded on_enrol" in p for p in _plan_errors(course))


def test_a_stage_naming_a_missing_task_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["bid_package"]["stage"] = "on_unlock(9)"
    assert any("names task 9" in p for p in _plan_errors(course))


def test_a_boq_link_to_a_position_the_bill_lacks_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["schedule_of_values"][0]["progress_link"] = "boq:09.999"
    assert any("progress_link boq:09.999 names no seeded bill position" in p for p in _plan_errors(course))


def test_a_contract_seeded_before_its_bill_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["boq"]["stage"] = "on_unlock(5)"
    assert any("is seeded before the bill it links to" in p for p in _plan_errors(course))


def test_a_boq_link_without_a_bill_is_refused(course: dict[str, Any]) -> None:
    del course["seed"]["boq"]
    assert any("the course seeds no main bill" in p for p in _plan_errors(course))


def test_two_lines_reading_one_position_are_refused(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["schedule_of_values"][1]["progress_link"] = "boq:01.001"
    assert any("read progress from the same bill position" in p for p in _plan_errors(course))


def test_a_schedule_that_does_not_sum_to_the_contract_value_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["value"]["value"] = 34500.00
    assert any("sums to 34502.82, the contract value is 34500" in p for p in _plan_errors(course))


def test_a_retention_the_column_cannot_hold_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["retention_percent"] = {"value": 0.05125, "unit": "fraction"}
    assert any("does not fit the ERP column" in p for p in _plan_errors(course))


def test_a_vat_rate_above_hundred_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["vat_rate_percent"] = 120
    assert any("vat_rate_percent 120 is outside 0-100" in p for p in _plan_errors(course))


def test_an_sov_amount_that_is_not_quantity_times_rate_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["schedule_of_values"][3]["quantity"] = 7
    assert any("rate the ERP stores (four decimals)" in p for p in _plan_errors(course))


def test_duplicate_codes_are_refused(course: dict[str, Any]) -> None:
    seed = course["seed"]
    seed["boq"]["positions"][1]["code"] = "01.001"
    seed["bid_package"]["scope_lines"][1]["code"] = "F01"
    seed["contract"]["schedule_of_values"][1]["code"] = "C01"
    problems = _plan_errors(course)
    assert any("position ordinals ['01.001'] are not unique" in p for p in problems)
    assert any("two lines share a code" in p and "scope_lines" in p for p in problems)
    assert any("schedule_of_values: two lines share a code" in p for p in problems)


def test_a_bid_line_outside_the_scope_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["bid_package"]["bids"][0]["lines"][0]["code"] = "F99"
    assert any("line F99 is not a scope line" in p for p in _plan_errors(course))


def test_a_position_in_an_undeclared_section_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["boq"]["positions"][0]["section"] = "07"
    assert any("section 07 is not declared" in p for p in _plan_errors(course))


# ── Markups and section lines ────────────────────────────────────────────────


def test_markups_are_grouped_by_their_stage(course: dict[str, Any]) -> None:
    course["seed"]["boq"]["markups"] = [
        {"name": "Site overheads", "markup_type": "percentage", "percentage": 8, "unit": "percent"},
        {"name": "Profit", "stage": "on_unlock(3)", "percentage": 0.05, "unit": "fraction"},
    ]
    plan = build_plan(_stored(course))
    markups = [(stage_key(s.stage), s.ref_key) for s in plan.steps if s.kind == "markups"]
    assert markups == [
        ("on_unlock(1)", "boq.main.markups.on_unlock(1)"),
        ("on_unlock(3)", "boq.main.markups.on_unlock(3)"),
    ]
    # Inside a stage the markups follow their bill.
    assert [s.kind for s in plan.for_stage(Stage("on_unlock", 1))] == ["boq", "markups"]


def test_a_markup_before_its_bill_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["boq"]["markups"] = [{"name": "Early", "stage": "on_enrol", "percentage": 5}]
    assert any("runs before the bill it belongs to" in p for p in _plan_errors(course))


def test_a_fraction_markup_is_written_as_a_percent() -> None:
    created = _markup_create(MarkupSeed(name="Profit", percentage=Decimal("0.05"), unit="fraction"), sort_default=10)
    assert created.percentage == pytest.approx(5.0)
    assert created.sort_order == 10
    assert created.markup_type == "percentage"
    kept = _markup_create(
        MarkupSeed(
            name="Bond",
            markup_type="banded",
            apply_to="cumulative",
            category="bond",
            sort_order=100,
            fixed_amount=Decimal("250"),
            metadata={"bands": [{"up_to": 100000, "percentage": 1.2}]},
        ),
        sort_default=10,
    )
    assert (kept.markup_type, kept.apply_to, kept.category, kept.sort_order) == ("banded", "cumulative", "bond", 100)
    assert kept.fixed_amount == Decimal("250")
    assert kept.metadata == {"bands": [{"up_to": 100000, "percentage": 1.2}]}


def test_section_lines_become_positions_of_their_section(course: dict[str, Any]) -> None:
    course["seed"]["boq"]["sections"] += [
        {
            "ordinal": "02",
            "title": "General requirements",
            "lines": [{"code": "GR-01", "description": "Protection", "unit": "ls", "qty": 1, "rate": 1850}],
        },
        {"ordinal": "03", "title": "Subcontract", "line": "Subcontract quote", "unit": "ls", "amount": 9640},
        {"ordinal": "04", "title": "Built by the learner", "built_by_learner": "T2"},
    ]
    spec = CourseSpec.model_validate(_stored(course))
    assert seeded_position_ordinals(spec) == ["GR-01", "03.1", "01.001", "01.002", "01.003"]
    assert section_line_ordinal(SectionSeed(ordinal="09B")) == "09B.1"
    build_plan(spec)


def test_a_priced_section_line_without_a_unit_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["boq"]["sections"].append({"ordinal": "03", "line": "Subcontract quote", "amount": 9640})
    assert any("a priced line needs a unit" in p for p in _plan_errors(course))


# ── Reading timestamps (decision 20) ─────────────────────────────────────────


def test_a_reading_is_stamped_the_day_before_period_end_at_noon_utc() -> None:
    stamp = reading_timestamp(date(2026, 10, 1), date(2026, 10, 31))
    assert stamp == datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    earliest, latest = period_window(date(2026, 10, 1), date(2026, 10, 31))
    assert earliest <= stamp <= latest
    assert latest == datetime(2026, 10, 31, 23, 59, 59, 999999, tzinfo=UTC)


def test_a_one_day_period_is_stamped_inside_that_day() -> None:
    stamp = reading_timestamp(date(2026, 10, 31), date(2026, 10, 31))
    assert stamp == datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    earliest, latest = period_window(date(2026, 10, 31), date(2026, 10, 31))
    assert earliest <= stamp <= latest


# ── Small executor pieces that need no database ──────────────────────────────


def test_vat_is_written_as_a_plain_json_number() -> None:
    assert _json_number(Decimal("20")) == 20
    assert isinstance(_json_number(Decimal("20.0")), int)
    assert _json_number(Decimal("5.5")) == 5.5


def test_the_seed_context_names_codes_and_the_actor() -> None:
    enrolment = uuid.UUID("0123456789abcdef0123456789abcdef")
    learner = uuid.uuid4()
    ctx = SeedContext(enrolment_id=enrolment, learner_id=learner)
    assert ctx.code_suffix == "01234567"
    assert ctx.actor == str(learner)


def test_the_seeding_flag_is_set_only_inside_the_block() -> None:
    enrolment = uuid.uuid4()
    assert seeding_enrolment() is None
    with seeding(enrolment):
        assert seeding_enrolment() == enrolment
    assert seeding_enrolment() is None


# ── Bids the learner records, scope links ────────────────────────────────────


@pytest.mark.parametrize(
    ("recorded_by", "by_seed"),
    [
        (None, True),
        ("seed", True),
        ("seed (API, while Published)", True),
        ("Seed (API, während Published)", True),
        ("learner in T3 (Record bid), BEFORE Open Bids", False),
        ("Lernende in T3 ('Angebot erfassen')", False),
    ],
)
def test_a_bid_is_left_to_the_learner_unless_the_seed_records_it(recorded_by: str | None, by_seed: bool) -> None:
    bid = BidSeed(bidder="Firm", total=Decimal("100"), recorded_by=recorded_by)
    assert bid_recorded_by_seed(bid) is by_seed


def test_a_scope_line_linking_a_missing_position_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["bid_package"]["scope_lines"][0]["boq_position"] = "09.999"
    assert any("boq_position 09.999 names no seeded bill position" in p for p in _plan_errors(course))


def test_a_scope_line_linking_a_later_bill_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["bid_package"]["scope_lines"][0]["boq_position"] = "01.003"
    course["seed"]["boq"]["stage"] = "on_unlock(3)"
    course["seed"]["bid_package"]["stage"] = "on_unlock(2)"
    assert any("the package is seeded before the bill it links to" in p for p in _plan_errors(course))
