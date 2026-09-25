# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Variance answers how much of the budget is still free.

The defect these tests hold is not arithmetic that went wrong once. It is a
rule that was written separately at each caller, so correcting one of them left
the others quietly disagreeing, and the disagreement was invisible because each
copy was internally consistent. The budget row, the dashboard header and the
Excel export each subtracted a different thing from the same budget.

Underneath all three, none of them counted committed money. A line with 48.7
budgeted, 12.4 spent and 33.4 under signed order reported 36.3 of headroom in
green. That number appeared on the very screen a cost manager reads before
deciding whether there is room for something else.

`committed` is the open part of each commitment: a goods receipt or a settled
invoice moves its amount from committed to actual
(``FinanceService.sync_project_budget``). So the line finishes at what it has
incurred plus what is still promised, 12.4 + 33.4 = 45.8, and 2.9 of it is
free. While `committed` stayed at the full order value the rule compared the
two instead of adding them, and reported 15.3; once the column drained as work
was incurred, that comparison dropped the spend from every line with anything
received against it.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.finance.schemas import BudgetResponse
from app.modules.finance.variance import budget_variance, expected_outturn

D = Decimal


class TestExpectedOutturn:
    def test_committed_money_is_not_headroom(self):
        """The case measured on a live screen, and the reason this exists."""
        assert expected_outturn(forecast_final=D("0"), committed=D("33.4"), actual=D("12.4")) == D("45.8")
        free = budget_variance(revised_budget=D("48.7"), forecast_final=D("0"), committed=D("33.4"), actual=D("12.4"))
        assert free == D("2.9")
        # Named so the number this replaced is on the record: the header used
        # to subtract spend alone and offer 36.3 as room to spend.
        assert free != D("36.3")

    def test_a_recorded_forecast_wins_even_when_it_is_lower(self):
        """The forecast column exists so a person can overrule the arithmetic.

        Recomputing over the top of a number somebody typed would be a worse
        defect than the one being fixed here, because nothing on the screen
        would show it happening. A forecast below the commitment is a
        disagreement to display, not one to smooth away.
        """
        assert expected_outturn(forecast_final=D("30"), committed=D("33.4"), actual=D("12.4")) == D("30")

    def test_spend_is_the_floor_when_there_is_nothing_else(self):
        assert expected_outturn(forecast_final=D("0"), committed=D("0"), actual=D("12.4")) == D("12.4")

    def test_the_open_commitment_and_spend_add_up(self):
        """`committed` is the open part, so it and the spend are two halves of one outturn.

        Taking the larger of the two, as the rule did while `committed` held the
        full order value, would report 33.4 here and drop the 12.4 already spent.
        """
        outturn = expected_outturn(forecast_final=D("0"), committed=D("33.4"), actual=D("12.4"))
        assert outturn == D("45.8")
        assert outturn != D("33.4")

    def test_an_overrun_is_reported_as_a_negative(self):
        assert budget_variance(revised_budget=D("48.7"), forecast_final=D("55"), committed=D("0"), actual=D("50")) == D(
            "-6.3"
        )


class TestTheBudgetRow:
    def _row(self, **money: str) -> BudgetResponse:
        from datetime import datetime
        from uuid import uuid4

        base = {
            "id": uuid4(),
            "project_id": uuid4(),
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
            "original_budget": "0",
            "revised_budget": "0",
            "committed": "0",
            "actual": "0",
            "forecast_final": "0",
        }
        base.update(money)
        return BudgetResponse.model_validate(base)

    def test_the_row_reports_what_is_free_not_what_is_left_unspent(self):
        row = self._row(revised_budget="48.70", committed="33.40", actual="12.40")
        assert Decimal(row.variance) == D("2.90")

    def test_the_flag_lights_on_money_spoken_for_not_money_gone(self):
        """A line 68% committed and 25% spent is not `normal`.

        The bar and the flag deliberately sit on different bases: `consumed_pct`
        is how much has left the building, `warning_level` is how much is
        promised. A warning that only lights once the money is gone is not a
        warning, it is a receipt.
        """
        row = self._row(revised_budget="48.70", committed="47.00", actual="12.40")
        assert row.consumed_pct == pytest.approx(25.5, abs=0.1)
        assert row.warning_level == "critical"

    def test_a_row_it_cannot_read_reports_nothing_rather_than_a_number(self):
        row = self._row(revised_budget="not money", committed="33.40", actual="12.40")
        assert row.variance == "0"
        assert row.warning_level == "normal"


class TestOneRuleOnlyRule:
    """The gate that actually holds: no second copy of the rule.

    Every failure this file describes came from a rule that existed in more
    than one place. Asserting the numbers is worth little on its own, because
    the numbers were right at each caller on the day it was written; what broke
    was that a later correction reached one caller and not the others.
    """

    def test_no_module_subtracts_spend_from_budget_on_its_own(self):
        """Two widenings, both paid for by a copy this gate had already let past.

        It used to read only `app/modules/finance`, and the fourth copy of the
        rule was on the dashboard card, one directory over. And it looked only
        for `revised - actual`, while that copy wrote `actual - planned`: the
        same subtraction with the operands swapped and the budget under another
        name. A gate that names one wording of a rule tests the wording.
        """
        import re

        modules = Path(__file__).resolve().parents[2] / "app" / "modules"
        # The rule governs the two models that carry `committed` and a
        # forecast beside `actual`. Elsewhere a planned figure minus an actual
        # one is a different measurement - savings against a requisition, a
        # finished job's post-calculation, percent complete - and flagging
        # those teaches the reader to skim the failure.
        closure = ("ProjectBudget", "BudgetLine")
        # `budget` and `budget_total`, not `budgeted`: the latter is the
        # purchase-requisition baseline, a different quantity in a file that
        # also happens to read budget lines.
        budget = r"(?:revised\w*|planned\w*|budget(?:_\w+)?\b|\w+_budget\b)"
        spend = r"(?:actual\w*|spent\w*)"
        # Spaces around the minus, which `ruff format` guarantees in code and
        # prose does not: without it the gate reports the phrase
        # "budget-actual" in a comment as a defect.
        patterns = [
            re.compile(budget + r" - " + spend),
            re.compile(spend + r" - " + budget),
        ]
        in_closure, offenders = 0, []
        for path in sorted(modules.glob("*/*.py")):
            if path.name == "variance.py":
                continue
            text = path.read_text(encoding="utf-8")
            if not any(model in text for model in closure):
                continue
            in_closure += 1
            if any(p.search(text) for p in patterns):
                offenders.append(str(path.relative_to(modules)).replace("\\", "/"))
        assert in_closure >= 8, f"only {in_closure} files read a budget row; the scope rule has gone stale"
        assert offenders == [], (
            f"of {in_closure} module files that read a budget row, these compute "
            f"variance themselves instead of calling variance.py: {offenders}"
        )

    def test_the_rule_is_defined_once(self):
        module = Path(__file__).resolve().parents[2] / "app" / "modules" / "finance"
        definitions = [
            path.name for path in module.glob("*.py") if "def expected_outturn" in path.read_text(encoding="utf-8")
        ]
        assert definitions == ["variance.py"]
