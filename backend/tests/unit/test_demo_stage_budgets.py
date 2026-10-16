# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The budgets of a demo told at a construction stage read that stage, in both budget registers.

The Regensburg hub showed "EUR 13.218.070 of EUR 41.583.615" in its budget card next to "50.5 % consumed,
20.607.269,79 of 40.768.250,00, over budget" for a site that is digging its pit: the generic seed spends
80 % of the first sections of every project, and the finance budgets and the 5D budget lines used two
different formulas. Both now read one table of shares per DIN 276 group.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data
from app.core.demo_showcase import STAGE_SPEND, stage_spend


def _budgets(demo_id: str) -> list[dict]:
    template = DEMO_TEMPLATES[demo_id]
    data = _generate_module_data(template, uuid.uuid4(), uuid.uuid4(), demo_id, datetime.now(UTC))
    return data["finance_budgets"]


def _sum(rows: list[dict], key: str) -> Decimal:
    return sum((Decimal(r[key]) for r in rows), Decimal(0))


def test_every_staged_group_is_a_section_of_its_template() -> None:
    for demo_id, table in STAGE_SPEND.items():
        groups = {str(sec[0])[:3] for sec in DEMO_TEMPLATES[demo_id].sections}
        assert set(table) <= groups, demo_id
        for bound, incurred in table.values():
            assert 0 <= incurred <= bound <= 1, demo_id


def test_a_generic_demo_keeps_the_generic_budget() -> None:
    assert stage_spend("office-frankfurt", "310") is None
    assert stage_spend("residential-regensburg", "460") == (0.0, 0.0)


@pytest.mark.parametrize(
    ("demo_id", "max_incurred"),
    [("residential-regensburg", Decimal("0.15")), ("school-ludwigsburg", Decimal("0.05"))],
)
def test_a_staged_demo_is_neither_half_spent_nor_over_budget(demo_id: str, max_incurred: Decimal) -> None:
    rows = _budgets(demo_id)
    original, revised = _sum(rows, "original_budget"), _sum(rows, "revised_budget")
    actual, committed = _sum(rows, "actual"), _sum(rows, "committed")
    assert revised == original  # no revision recorded yet, one base for both widgets
    assert 0 < actual <= original * max_incurred
    # The hub warns from 90 % of the budget spoken for (committed is the open part, so it adds).
    assert actual + committed < original * Decimal("0.9")


def test_the_running_site_has_spent_more_than_the_school_before_its_gate() -> None:
    reg, lud = _budgets("residential-regensburg"), _budgets("school-ludwigsburg")
    share = lambda rows: _sum(rows, "actual") / _sum(rows, "original_budget")  # noqa: E731
    assert share(reg) > share(lud)
