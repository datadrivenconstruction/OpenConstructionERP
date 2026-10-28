# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A progress period is a point in time, so two of them cannot be the same one.

The S-curve on a demo project fell 36.7 points in one month and ended the
year below its own July. Nothing was wrong with the readings: the seeder
writes one cumulative percentage per month and they climb. What was wrong was
the label. It kept the project's start year and wrapped the month with
``% 12``, so a programme starting in April 2026 labelled its 13th month
``2026-04`` again, exactly like its 1st.

Everything downstream is keyed by that label. The cumulative endpoint reads
the latest entry per period, sorts the periods as strings and subtracts
neighbours, so a month that owned three readings kept whichever one the
dedupe picked and the ladder came back out of order. The arithmetic was never
asked to produce a monotone series, it was handed a shuffled one.

What is pinned here is the property, not the fix: over the seeded set of a
project, one label means one month, and reading the percentages in label
order climbs. Both halves matter - unique labels with a scrambled ordering
would still draw a falling S-curve.

Pure generation, so no database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data, _period_label

# The seeder's own project start. April is what made the collision visible:
# any start month other than January wraps before the twelfth month is out.
_BASE = datetime(2026, 4, 1)


def _generate(template):
    return _generate_module_data(template, uuid.uuid4(), uuid.uuid4(), template.demo_id, _BASE)


class TestPeriodLabel:
    """The label itself, before any project is generated from it."""

    def test_the_first_month_is_the_start_month(self) -> None:
        assert _period_label(_BASE, 0) == "2026-04"

    def test_the_month_after_december_is_january_of_the_next_year(self) -> None:
        assert _period_label(_BASE, 8) == "2026-12"
        assert _period_label(_BASE, 9) == "2027-01"

    def test_the_thirteenth_month_is_not_the_first_one(self) -> None:
        # The regression itself: both used to be "2026-04".
        assert _period_label(_BASE, 12) == "2027-04"
        assert _period_label(_BASE, 12) != _period_label(_BASE, 0)

    def test_a_january_start_never_needed_the_carry(self) -> None:
        # The start month that hid the bug: with no wrap inside the first
        # year, the old expression and this one agree for twelve months.
        january = datetime(2026, 1, 1)
        assert [_period_label(january, m) for m in range(12)] == [f"2026-{m:02d}" for m in range(1, 13)]
        assert _period_label(january, 12) == "2027-01"

    def test_labels_sort_chronologically_as_plain_strings(self) -> None:
        # Every reader sorts these as text - the endpoint, the S-curve, the
        # period table - so the year has to lead and the month has to be
        # zero-padded for the sort to mean anything.
        labels = [_period_label(_BASE, m) for m in range(30)]
        assert labels == sorted(labels)


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
class TestSeededSeries:
    """The generated series, which is what the screen actually reads."""

    def test_every_period_is_named_once(self, demo_id: str) -> None:
        generated = _generate(DEMO_TEMPLATES[demo_id])
        for key in ("progress", "progress_plan"):
            labels = [row["period_label"] for row in generated[key]]
            assert labels, f"{demo_id} generated no {key} rows to check"
            duplicates = sorted({label for label in labels if labels.count(label) > 1})
            assert not duplicates, f"{demo_id} {key} names {duplicates} more than once"

    def test_completion_climbs_when_the_periods_are_read_in_order(self, demo_id: str) -> None:
        # The endpoint sorts by label and subtracts neighbours. A building
        # cannot become less built, so no neighbour may fall.
        generated = _generate(DEMO_TEMPLATES[demo_id])
        for key, field in (("progress", "percent_complete"), ("progress_plan", "planned_pct")):
            rows = sorted(generated[key], key=lambda row: row["period_label"])
            values = [float(row[field]) for row in rows]
            drops = [
                (rows[i]["period_label"], values[i - 1], values[i])
                for i in range(1, len(values))
                if values[i] < values[i - 1]
            ]
            assert not drops, f"{demo_id} {key} falls at {drops}"

    def test_the_actuals_stop_at_today_and_the_plan_does_not(self, demo_id: str) -> None:
        # A demo is installed into a story that started in April 2026 and runs
        # for years. Recording progress for the whole programme filed a job in
        # its fifth month as 88 per cent built, with readings dated two years
        # ahead, while the 4D schedule beside it read the real clock and said
        # eleven. The plan legitimately runs to the end; the actuals cannot
        # run past the month the reader is in.
        today = datetime.now()
        this_month = f"{today.year}-{today.month:02d}"
        generated = _generate(DEMO_TEMPLATES[demo_id])
        actuals = [row["period_label"] for row in generated["progress"]]
        assert max(actuals) <= this_month, f"{demo_id} records progress in {max(actuals)}"
        plan = [row["period_label"] for row in generated["progress_plan"]]
        assert max(plan) > max(actuals), f"{demo_id} plans no further than it has already built"

    def test_the_series_spans_the_programme_it_belongs_to(self, demo_id: str) -> None:
        # A collision used to shorten the axis as well as scramble it: three
        # readings sharing one label render as one period.
        template = DEMO_TEMPLATES[demo_id]
        months = max(int(template.total_months or 12), 1)
        assert len({row["period_label"] for row in generated_plan(template)}) == months


def generated_plan(template) -> list[dict]:
    return _generate(template)["progress_plan"]
