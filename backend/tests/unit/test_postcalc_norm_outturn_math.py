# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure tests for the per-norm estimate-against-outturn rollup (DB-free).

The end-to-end contract lives in ``tests/modules/postcalc/test_norm_outturn.py``
and is the one that would have caught the feature being unusable. These are the
arithmetic underneath it, asserted from plain values, because the cases that
matter most here are the ones a live fixture makes expensive to reach: two
positions whose per-line factors differ sharply, a group whose units do not
match, a norm that has been deleted, and every refusal.

The aggregation case is the reason this file exists. Averaging the per-line
factors and dividing summed hours by summed earned hours give the same answer
whenever the lines are the same size, so a fixture built with equal positions
cannot tell the two apart. The lines below are deliberately unequal.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.postcalc.model import (
    STATUS_NO_ACTUALS,
    STATUS_NO_BASELINE,
    STATUS_NO_PROGRESS,
    STATUS_ON_PLAN,
    STATUS_OVER_PRODUCTIVE,
    STATUS_UNDER_PRODUCTIVE,
)
from app.modules.postcalc.norm_outturn import NormBaseline, group_by_norm

D = Decimal

NORM = str(uuid.uuid4())
OTHER_NORM = str(uuid.uuid4())


class Row:
    """A stand-in for a ``PositionActuals`` row, positional attributes only."""

    def __init__(
        self,
        *,
        norm_id: str = NORM,
        norm_work_key: str = "plastering_internal",
        unit: str = "m2",
        estimate_quantity: str = "100",
        estimate_amount: str = "1620.00",
        installed_percent: str | None = None,
        labour_hours: str = "0",
        plant_hours: str = "0",
        committed_amount: str = "0",
        claimed_amount: str = "0",
        consumed_amount: str = "0",
    ) -> None:
        self.boq_position_id = uuid.uuid4()
        self.norm_id = norm_id
        self.norm_work_key = norm_work_key
        self.unit = unit
        self.estimate_quantity = D(estimate_quantity)
        self.estimate_amount = D(estimate_amount)
        self.installed_percent = None if installed_percent is None else D(installed_percent)
        self.labour_hours = D(labour_hours)
        self.plant_hours = D(plant_hours)
        self.committed_amount = D(committed_amount)
        self.claimed_amount = D(claimed_amount)
        self.consumed_amount = D(consumed_amount)


def baseline(hours_per_unit: str = "0.45", *, unit: str = "m2") -> dict[str, NormBaseline]:
    return {
        NORM: NormBaseline(
            work_key="plastering_internal",
            name="Internal plastering",
            unit=unit,
            labour_hours_per_unit=D(hours_per_unit),
        )
    }


def roll(rows: list[Row], *, baselines=None, per_unit: str = "0.45"):
    """Group and return the single norm row, with a per-unit bill split."""
    report = group_by_norm(
        list(rows),
        baselines=baseline() if baselines is None else baselines,
        bill_labour_hours_per_unit={row.boq_position_id: D(per_unit) for row in rows},
    )
    (row,) = report.norms
    return row, report


class TestItSumsBeforeItDivides:
    """The failure a fixture of equal lines cannot see."""

    def test_two_unequal_lines_divide_summed_hours_by_summed_earned(self) -> None:
        # 900 m2 fully in place, 405 earned at 0.45, 380 booked -> 0.9383.
        # 3 m2 fully in place, 1.35 earned, 6 booked -> 4.4444.
        # The mean of those two factors is 2.69, which describes no job that
        # ever happened. The right answer weights by the work done: 386 booked
        # against 406.35 earned is 0.9499.
        big = Row(estimate_quantity="900", installed_percent="100", labour_hours="380")
        small = Row(estimate_quantity="3", installed_percent="100", labour_hours="6")

        row, _ = roll([big, small])

        assert row.earned_hours == D("406.35")
        assert row.actual_labour_hours == D("386.00")
        assert row.productivity_factor == D("0.9499")
        assert row.productivity_factor != D("2.6914"), "the per-line factors were averaged"
        assert row.status == STATUS_OVER_PRODUCTIVE

    def test_a_line_with_no_progress_lowers_no_denominator_it_did_not_earn(self) -> None:
        """An untouched position must not dilute the factor of a finished one."""
        done = Row(estimate_quantity="100", installed_percent="100", labour_hours="50")
        untouched = Row(estimate_quantity="100")

        row, _ = roll([done, untouched])

        assert row.bill_quantity == D("200.0000")
        assert row.installed_quantity == D("100.0000")
        # 45 earned on the finished half, not 90 on the whole bill.
        assert row.earned_hours == D("45.00")
        assert row.productivity_factor == D("1.1111")


class TestTheTwoBaselinesAreReportedApart:
    def test_the_norm_baseline_moves_and_the_bill_baseline_does_not(self) -> None:
        rows = [Row(estimate_quantity="100", installed_percent="100", labour_hours="45")]

        # The bill was priced at 0.45; the library has since been corrected to 0.60.
        row, _ = roll(rows, baselines=baseline("0.60"), per_unit="0.45")

        assert row.bill_labour_hours == D("45.00")
        assert row.bill_labour_hours_per_unit == D("0.4500")
        assert row.norm_labour_hours == D("60.00")
        assert row.norm_labour_hours_per_unit == D("0.60")

        # Against the bill the crew was exactly on plan; against the corrected
        # library it beat the allowance. Both are true and they are different
        # numbers, which is the whole reason neither is called "estimated".
        assert row.productivity_factor == D("1.0000")
        assert row.status == STATUS_ON_PLAN
        assert row.norm_productivity_factor == D("0.7500")

    def test_a_deleted_norm_keeps_the_bill_and_loses_only_the_live_side(self) -> None:
        rows = [Row(estimate_quantity="100", installed_percent="100", labour_hours="60")]

        row, report = roll(rows, baselines={})

        assert row.norm_row_present is False
        assert row.norm_labour_hours is None
        assert row.norm_labour_hours_per_unit is None
        assert row.norm_productivity_factor is None
        # The work key is the human handle, and it survives on the position.
        assert row.work_key == "plastering_internal"
        assert row.bill_labour_hours == D("45.00")
        assert row.productivity_factor == D("1.3333")
        assert row.status == STATUS_UNDER_PRODUCTIVE
        assert report.positions_with_deleted_norm == 1


class TestEveryRefusalSaysWhy:
    def test_nothing_recorded_is_no_actuals(self) -> None:
        row, _ = roll([Row()])
        assert row.status == STATUS_NO_ACTUALS
        assert row.productivity_factor is None

    def test_hours_against_nothing_installed_is_no_progress(self) -> None:
        row, _ = roll([Row(labour_hours="27")])
        assert row.status == STATUS_NO_PROGRESS
        assert row.actual_labour_hours == D("27.00")
        assert row.productivity_factor is None

    def test_work_in_place_with_no_hours_booked_is_a_timesheet_gap(self) -> None:
        row, _ = roll([Row(installed_percent="100")])
        assert row.status == STATUS_NO_ACTUALS
        assert row.productivity_factor is None

    def test_a_bill_with_no_labour_split_has_no_baseline(self) -> None:
        row, _ = roll([Row(installed_percent="100", labour_hours="40")], per_unit="0")
        assert row.status == STATUS_NO_BASELINE
        assert row.bill_labour_hours == D("0.00")
        assert row.productivity_factor is None
        # The library still has an opinion even where the bill carries none.
        assert row.norm_productivity_factor == D("0.8889")

    def test_a_reported_zero_is_a_reading_and_still_earns_nothing(self) -> None:
        """Zero percent complete is a real reading, and it has no denominator."""
        row, _ = roll([Row(installed_percent="0", labour_hours="27")])
        assert row.installed_quantity == D("0.0000")
        assert row.status == STATUS_NO_PROGRESS
        assert row.productivity_factor is None


class TestMixedUnits:
    """Quantities in different units cannot be added, so there is no rate."""

    def test_two_units_in_one_group_collapse_the_baseline_and_say_so(self) -> None:
        rows = [
            Row(unit="m2", estimate_quantity="100", installed_percent="100", labour_hours="45"),
            Row(unit="m3", estimate_quantity="10", installed_percent="100", labour_hours="20"),
        ]

        row, _ = roll(rows)

        assert row.mixed_units is True
        assert row.bill_labour_hours_per_unit is None
        assert row.productivity_factor is None
        assert row.norm_productivity_factor is None
        assert row.status == STATUS_NO_BASELINE
        # Hours and money carry no unit of the position's, so they still sum.
        assert row.actual_labour_hours == D("65.00")

    def test_one_unit_throughout_is_not_flagged(self) -> None:
        row, _ = roll([Row(unit="m2"), Row(unit="m2")])
        assert row.mixed_units is False
        assert row.unit == "m2"


class TestWhatIsCountedAndWhatIsNot:
    def test_positions_carrying_no_norm_are_counted_not_grouped(self) -> None:
        report = group_by_norm(
            [Row(), Row(norm_id="", norm_work_key=""), Row(norm_id="", norm_work_key="")],
            baselines=baseline(),
            bill_labour_hours_per_unit={},
        )
        assert report.positions_without_norm == 2
        assert len(report.norms) == 1
        assert report.norms[0].positions == 1

    def test_two_norms_come_back_ordered_by_work_key(self) -> None:
        report = group_by_norm(
            [Row(), Row(norm_id=OTHER_NORM, norm_work_key="brickwork")],
            baselines=baseline(),
            bill_labour_hours_per_unit={},
        )
        assert [n.work_key for n in report.norms] == ["brickwork", "plastering_internal"]

    def test_material_consumption_of_nothing_is_unknown_rather_than_zero(self) -> None:
        """An unmetered norm and one that used no material are different facts."""
        unmetered, _ = roll([Row(consumed_amount="0")])
        assert unmetered.consumed_amount is None

        metered, _ = roll([Row(consumed_amount="9900.00"), Row(consumed_amount="0")])
        assert metered.consumed_amount == D("9900.00")

    def test_norms_answerable_counts_verdicts_not_rows(self) -> None:
        report = group_by_norm(
            [
                Row(installed_percent="100", labour_hours="45"),
                Row(norm_id=OTHER_NORM, norm_work_key="brickwork"),
            ],
            baselines=baseline(),
            bill_labour_hours_per_unit={},
        )
        # Neither has a bill split here, so neither can be answered; the count
        # is over verdicts, and a report of two rows is not two answers.
        assert len(report.norms) == 2
        assert report.norms_answerable == 0


class TestItNeverRaisesOnStoredJunk:
    """Money and quantities are strings on this table and can hold anything."""

    @pytest.mark.parametrize("junk", ["", "n/a", "NaN", "Infinity", None])
    def test_an_unusable_quantity_is_zero_rather_than_an_exception(self, junk) -> None:
        row = Row()
        row.estimate_quantity = junk
        out, _ = roll([row])
        assert out.bill_quantity == D("0.0000")
        assert out.status == STATUS_NO_BASELINE
