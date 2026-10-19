"""Schedule from estimate, P0: effort, machine hours, confidence and the 5D rules.

Pure tests, no database. The design and the weights they pin are in
``docs/design/schedule_from_estimate.md`` (sections 3.2 to 3.4).
"""

from __future__ import annotations

import math

import pytest

from app.core.validation.engine import Severity, ValidationContext, ValidationEngine, rule_registry
from app.core.validation.rules import (
    Schedule5DBoqCoverage,
    Schedule5DCostReconciliation,
    Schedule5DDurationVsNorm,
    register_builtin_rules,
)
from app.modules.schedule.plan_confidence import (
    confidence_band,
    plan_confidence,
    task_confidence,
)
from app.modules.schedule.service import (
    _calc_duration_from_resources,
    _position_effort,
    machine_hours_per_unit,
    plausible_crew,
)

HPD = 8.0
WEEK = 5


def _effort(meta: dict, qty: float, *, workers: int = 1, sets: int = 1, unit: str = "m3"):
    return _position_effort(
        meta,
        qty,
        unit,
        1000.0,
        10_000.0,
        365,
        hours_per_day=HPD,
        work_days_per_week=WEEK,
        assumed_workers=workers,
        machine_sets=sets,
    )


def _cal_days(hours: float, people: int) -> int:
    return max(1, int(round(hours / (people * HPD) * 1.1 * 7 / WEEK)))


# ── Crew read from the bill ──────────────────────────────────────────────────


class TestPlausibleCrew:
    def test_a_crew_a_person_could_type_is_kept(self) -> None:
        assert plausible_crew(4) == 4
        assert plausible_crew(2.5) == 3
        assert plausible_crew(20) == 20

    def test_people_per_unit_from_the_cost_database_is_not_a_crew(self) -> None:
        # CWICR count_total_people_per_unit tracks the labour hours (median
        # ratio 1.01); 811.96 people on one unit is not a gang.
        assert plausible_crew(811.96) == 0
        assert plausible_crew(20.5) == 0

    def test_nothing_or_nonsense_is_no_crew(self) -> None:
        assert plausible_crew(0) == 0
        assert plausible_crew(-3) == 0

    def test_an_implausible_crew_falls_back_to_the_assumed_one(self) -> None:
        meta = {"labor_hours": 10.66, "workers_per_unit": 10.7 * 70}
        effort = _effort(meta, 100, workers=6)
        assert effort.crew == 6
        assert effort.labour_days == _cal_days(1066, 6)


# ── Machine hours ────────────────────────────────────────────────────────────


def _row(kind: str, qty: float, unit: str = "hr", **extra) -> dict:
    return {"type": kind, "quantity": qty, "unit": unit, **extra}


class TestMachineHours:
    def test_the_largest_machine_row_is_taken_not_the_sum(self) -> None:
        # The USA base follows each plant row with an operator and an
        # electricity row of the same hours, all typed equipment.
        meta = {
            "resources": [
                _row("equipment", 5.26, "machine hours"),
                _row("equipment", 5.26, "machine hours", name="Equipment Operator"),
                _row("equipment", 5.26, "machine hours", name="Electricity"),
                _row("equipment", 0.14, "machine hours"),
            ]
        }
        assert machine_hours_per_unit(meta) == pytest.approx(5.26)

    @pytest.mark.parametrize("unit", ["hr", "h", "machine hours", "machine-hours", "h-maş.", "giờ máy", "sa", "Std."])
    def test_hour_units_in_several_languages(self, unit: str) -> None:
        assert machine_hours_per_unit({"resources": [_row("equipment", 2, unit)]}) == 2

    @pytest.mark.parametrize("kind", ["equipment", "machine", "machinery", "plant"])
    def test_machine_types(self, kind: str) -> None:
        assert machine_hours_per_unit({"resources": [_row(kind, 3)]}) == 3

    def test_shifts_money_and_labour_are_not_machine_hours(self) -> None:
        meta = {
            "resources": [
                _row("equipment", 1.5, "机班"),
                _row("equipment", 900, "EUR"),
                _row("labor", 7),
                _row("material", 4),
                "not a row",
            ]
        }
        assert machine_hours_per_unit(meta) == 0
        assert machine_hours_per_unit({"resources": "broken"}) == 0
        assert machine_hours_per_unit({}) == 0

    def test_machine_hours_outlasting_the_labour_set_the_duration(self) -> None:
        # 100 m3: 100 labour hours for 4 people is about 4 days; 300 machine
        # hours for one machine is about 41 days. The machine bounds the work.
        meta = {"resources": [_row("labor", 1.0), _row("equipment", 3.0)]}
        effort = _effort(meta, 100, workers=4)
        assert effort.machine_hours == pytest.approx(300)
        assert effort.machine_days == _cal_days(300, 1)
        assert effort.machine_days > effort.labour_days
        days, source = _calc_duration_from_resources(
            meta, 100, "m3", 1000.0, 10_000.0, 365, hours_per_day=HPD, work_days_per_week=WEEK, assumed_workers=4
        )
        assert (days, source) == (effort.machine_days, "machine_hours")

    def test_labour_wins_when_it_is_longer(self) -> None:
        meta = {"labor_hours": 10, "resources": [_row("equipment", 0.5)]}
        days, source = _calc_duration_from_resources(
            meta, 100, "m3", 1000.0, 10_000.0, 365, hours_per_day=HPD, work_days_per_week=WEEK
        )
        assert source == "labor_hours"
        assert days == _cal_days(1000, 1)

    def test_parallel_gangs_bring_a_machine_each(self) -> None:
        meta = {"resources": [_row("labor", 1.0), _row("equipment", 3.0)]}
        one = _effort(meta, 100, sets=1)
        three = _effort(meta, 100, sets=3)
        assert three.machine_days == _cal_days(300, 3)
        assert three.machine_days < one.machine_days

    def test_a_position_with_only_machine_rows_takes_the_machine_duration(self) -> None:
        meta = {"resources": [_row("equipment", 0.2)]}
        effort = _effort(meta, 500)
        assert effort.source == "machine_hours"
        assert effort.labour_hours == 0
        assert effort.machine_days == _cal_days(100, 1)

    def test_no_machine_rows_keeps_the_old_answer(self) -> None:
        meta = {"labor_hours": 2, "workers_per_unit": 2}
        days, source = _calc_duration_from_resources(
            meta, 40, "m2", 1000.0, 10_000.0, 365, hours_per_day=HPD, work_days_per_week=WEEK
        )
        assert source == "labor_hours"
        assert days == _cal_days(80, 2)


class TestEffortTotals:
    def test_labour_hours_and_crew_from_the_norm(self) -> None:
        effort = _effort({"labor_hours": 2, "workers_per_unit": 3}, 40)
        assert effort.labour_hours == pytest.approx(80)
        assert effort.crew == 3
        assert effort.source == "labor_hours"

    def test_labour_rows_give_the_crew_from_their_count(self) -> None:
        meta = {"resources": [_row("labor", 0.5), _row("labor", 0.25), _row("operator", 0.25)]}
        effort = _effort(meta, 100, workers=2)
        assert effort.source == "resource_sum"
        assert effort.labour_hours == pytest.approx(100)
        assert effort.crew == 3

    def test_unverified_norm_rows_are_reported(self) -> None:
        demo = {"demo_provenance": {"productivity_verified": False}}
        meta = {"resources": [_row("labor", 1.0, **demo), _row("equipment", 0.1, **demo)]}
        assert _effort(meta, 10).unverified is True
        assert _effort({"resources": [_row("labor", 1.0)]}, 10).unverified is False


# ── Confidence ───────────────────────────────────────────────────────────────


class TestConfidence:
    def test_weights_add_up_as_documented(self) -> None:
        c = task_confidence("labor_hours")
        assert c["duration"] == 0.9
        assert c["logic"] == 0.4
        assert c["breakdown"] == 0.7
        assert c["score"] == pytest.approx(0.5 * 0.9 + 0.3 * 0.4 + 0.2 * 0.7)
        assert c["band"] == "high"

    @pytest.mark.parametrize(
        ("source", "duration"),
        [
            ("labor_hours", 0.9),
            ("machine_hours", 0.85),
            ("resource_sum", 0.8),
            ("spans_works", 0.6),
            ("estimated_fallback", 0.4),
            ("cost_proportional", 0.2),
            ("default_minimum", 0.1),
        ],
    )
    def test_duration_factor_by_source(self, source: str, duration: float) -> None:
        assert task_confidence(source)["duration"] == duration

    def test_a_guess_held_down_by_the_price_scores_lower(self) -> None:
        assert task_confidence("estimated_fallback", capped_by_price=True)["duration"] == 0.3

    def test_synthetic_norms_are_capped(self) -> None:
        c = task_confidence("resource_sum", unverified=True)
        assert c["duration"] == 0.5
        assert "unverified_norm" in c["reasons"]
        # A guess is not lifted by the cap.
        assert task_confidence("estimated_fallback", unverified=True)["duration"] == 0.4

    def test_shortened_durations_lower_the_score(self) -> None:
        c = task_confidence("labor_hours", compressed_pct=50)
        assert c["duration"] == pytest.approx(0.9 * 0.75)
        assert "shortened" in c["reasons"]

    def test_lump_sums_and_spanning_lump_sums(self) -> None:
        lump = task_confidence("cost_proportional", lump_sum=True)
        assert lump["breakdown"] == 0.5
        assert lump["band"] == "low"
        spans = task_confidence("spans_works", lump_sum=True)
        assert spans["logic"] == 0.7

    def test_bands(self) -> None:
        assert confidence_band(0.7) == "high"
        assert confidence_band(0.69) == "medium"
        assert confidence_band(0.5) == "medium"
        assert confidence_band(0.49) == "low"

    def test_documented_examples(self) -> None:
        assert task_confidence("labor_hours")["score"] == pytest.approx(0.71)
        assert task_confidence("resource_sum")["score"] == pytest.approx(0.66)
        assert task_confidence("resource_sum", unverified=True)["score"] == pytest.approx(0.51)
        assert task_confidence("estimated_fallback")["score"] == pytest.approx(0.46)
        assert task_confidence("cost_proportional", lump_sum=True)["score"] == pytest.approx(0.32)

    def test_plan_score_is_weighted_by_cost(self) -> None:
        plan = plan_confidence([(0.9, 900.0), (0.3, 100.0)])
        assert plan["score"] == pytest.approx(0.84)
        assert plan["counts"] == {"high": 1, "medium": 0, "low": 1}
        assert plan["band"] == "high"

    def test_plan_score_without_prices_is_a_plain_mean(self) -> None:
        assert plan_confidence([(0.8, 0.0), (0.4, 0.0)])["score"] == pytest.approx(0.6)

    def test_empty_plan(self) -> None:
        plan = plan_confidence([])
        assert plan["score"] == 0
        assert plan["counts"] == {"high": 0, "medium": 0, "low": 0}


# ── 5D rules ─────────────────────────────────────────────────────────────────


def _ctx(data: dict) -> ValidationContext:
    return ValidationContext(data=data, metadata={"locale": "en"})


def _task(act_id: str, positions: list[str], cost: str | None, **extra) -> dict:
    return {
        "id": act_id,
        "name": f"Task {act_id}",
        "wbs_code": act_id,
        "activity_type": "task",
        "boq_position_ids": positions,
        "cost_planned": cost,
        **extra,
    }


def _position(pos_id: str, total: str) -> dict:
    return {"id": pos_id, "ordinal": f"01.{pos_id}", "description": f"Work {pos_id}", "total": total}


class TestBoqCoverage:
    @pytest.mark.asyncio
    async def test_unscheduled_priced_positions_are_listed(self) -> None:
        data = {
            "activities": [_task("a", ["p1"], "100"), {"id": "s", "activity_type": "summary"}],
            "boq_positions": [_position("p1", "100"), _position("p2", "40.50"), _position("p3", "0")],
        }
        results = await Schedule5DBoqCoverage().validate(_ctx(data))
        failed = [r for r in results if not r.passed]
        assert [r.element_ref for r in failed] == ["p2"]
        assert failed[0].severity == Severity.WARNING
        assert "01.p2" in failed[0].message
        assert "schedule_5d" not in failed[0].message  # resolved, not the raw key

    @pytest.mark.asyncio
    async def test_skips_without_positions(self) -> None:
        assert await Schedule5DBoqCoverage().validate(_ctx({"activities": [_task("a", [], None)]})) == []


class TestCostReconciliation:
    @pytest.mark.asyncio
    async def test_passes_on_the_same_total(self) -> None:
        data = {
            "activities": [_task("a", ["p1"], "100.10"), _task("b", ["p2"], "0.2")],
            "boq_positions": [_position("p1", "100.10"), _position("p2", "0.20")],
        }
        (result,) = await Schedule5DCostReconciliation().validate(_ctx(data))
        assert result.passed

    @pytest.mark.asyncio
    async def test_passes_within_a_cent(self) -> None:
        data = {"activities": [_task("a", ["p1"], "100.004")], "boq_positions": [_position("p1", "100.00")]}
        (result,) = await Schedule5DCostReconciliation().validate(_ctx(data))
        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_when_money_is_missing(self) -> None:
        data = {
            "activities": [_task("a", ["p1"], "100"), {"id": "s", "activity_type": "summary", "cost_planned": "999"}],
            "boq_positions": [_position("p1", "100"), _position("p2", "50")],
        }
        (result,) = await Schedule5DCostReconciliation().validate(_ctx(data))
        assert not result.passed
        assert result.severity == Severity.ERROR
        assert result.details["difference"] == "-50"
        assert "150" in result.message and "100" in result.message

    @pytest.mark.asyncio
    async def test_skips_without_positions(self) -> None:
        assert await Schedule5DCostReconciliation().validate(_ctx({"activities": [_task("a", [], "1")]})) == []


class TestDurationVsNorm:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("duration", "norm", "passed"),
        [(10, 10, True), (20, 10, True), (21, 10, False), (5, 10, True), (4, 10, False), (3, 1, True), (1, 3, True)],
    )
    async def test_far_from_the_norm(self, duration: int, norm: int, passed: bool) -> None:
        act = _task("a", ["p1"], None, duration_days=duration, metadata={"norm_days": norm})
        (result,) = await Schedule5DDurationVsNorm().validate(_ctx({"activities": [act]}))
        assert result.passed is passed
        if not passed:
            assert result.severity == Severity.WARNING
            assert str(norm) in result.message

    @pytest.mark.asyncio
    async def test_activities_without_a_norm_or_not_tasks_are_not_checked(self) -> None:
        acts = [
            _task("a", ["p1"], None, duration_days=50, metadata={}),
            {"id": "s", "activity_type": "summary", "duration_days": 50, "metadata": {"norm_days": 1}},
            _task("b", ["p2"], None, duration_days=50, metadata={"norm_days": "x"}),
        ]
        assert await Schedule5DDurationVsNorm().validate(_ctx({"activities": acts})) == []


class TestRegistration:
    @pytest.mark.asyncio
    async def test_the_schedule_5d_set_runs_through_the_engine(self) -> None:
        register_builtin_rules()
        ids = {rule.rule_id for rule in rule_registry.get_rules_for_sets(["schedule_5d"])}
        engine = ValidationEngine(rule_registry)
        data = {
            "activities": [_task("a", ["p1"], "100", duration_days=3, metadata={"norm_days": 3})],
            "boq_positions": [_position("p1", "100"), _position("p2", "1")],
        }
        report = await engine.validate(data, ["schedule_5d"], metadata={"locale": "en"})
        fired = {r.rule_id for r in report.results if not r.passed}
        assert fired == {"schedule_5d.boq_coverage", "schedule_5d.cost_reconciliation"}
        assert ids == {
            "schedule_5d.boq_coverage",
            "schedule_5d.cost_reconciliation",
            "schedule_5d.duration_vs_norm",
        }


def test_cal_days_helper_matches_the_generator_formula() -> None:
    # Guards the helper above against drifting from the generator's maths.
    assert _cal_days(80, 1) == max(1, int(round(10 * 1.1 * 7 / 5)))
    assert math.isclose(1.1 * 7 / 5, 1.54)
