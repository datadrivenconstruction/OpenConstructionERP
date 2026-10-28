# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the Variance column on a budget line is allowed to mean.

Variance used to be ``revised_budget - actual``, which is spend to date
measured against the budget. On a job that is half built that quantity is
positive on every line by construction, so the column a cost report exists to
show an overrun in was green on all of them and could not go red until the
money had already gone. These tests pin the reading that can: the revised
budget against the outturn the line is forecast to reach.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.finance.schemas import BudgetResponse


def _budget(**over: str) -> BudgetResponse:
    """A budget line with the money fields overridable one at a time."""
    now = datetime.now(UTC)
    fields: dict[str, str] = {
        "original_budget": "100000",
        "revised_budget": "100000",
        "committed": "0",
        "actual": "0",
        "forecast_final": "0",
    }
    fields.update(over)
    return BudgetResponse(
        id=uuid4(),
        project_id=uuid4(),
        created_at=now,
        updated_at=now,
        **fields,
    )


def test_forecast_over_budget_is_a_negative_variance() -> None:
    """The whole point: an overrun shows while there is still time to act.

    Only a fifth of the money is spent, so a spend-based reading would call
    this line comfortably under budget.
    """
    line = _budget(revised_budget="100000", actual="20000", forecast_final="115000")
    assert line.variance == "-15000"


def test_forecast_under_budget_is_a_positive_variance() -> None:
    line = _budget(revised_budget="100000", actual="20000", forecast_final="92000")
    assert line.variance == "8000"


def test_forecast_on_budget_is_zero_variance() -> None:
    line = _budget(revised_budget="100000", actual="60000", forecast_final="100000")
    assert line.variance == "0"


def test_spend_alone_does_not_move_the_variance() -> None:
    """Two lines with the same budget and forecast agree however much has been
    spent so far. Variance is about the outturn, not the run rate."""
    early = _budget(revised_budget="100000", actual="5000", forecast_final="104000")
    late = _budget(revised_budget="100000", actual="95000", forecast_final="104000")
    assert early.variance == late.variance == "-4000"


def test_a_line_with_no_forecast_falls_back_to_spend() -> None:
    """Zero is what the change-order and BOQ writers insert, and it means "no
    forecast recorded" rather than "this line will cost nothing". Spend to date
    is then the only outturn evidence there is; the alternative is reporting the
    entire budget as a surplus on a line nobody has estimated."""
    line = _budget(revised_budget="100000", actual="30000", forecast_final="0")
    assert line.variance == "70000"


def test_variance_keeps_the_cents() -> None:
    """Money subtracts as Decimal, so the tail is exact rather than carrying
    binary-float drift into a figure someone reports upward."""
    line = _budget(revised_budget="100000.10", actual="0", forecast_final="100000.35")
    assert line.variance == "-0.25"


@pytest.mark.parametrize("bad", ["", "not-a-number"])
def test_an_unparseable_money_field_zeroes_the_derived_numbers(bad: str) -> None:
    """A malformed row reports nothing rather than a misleading something."""
    line = _budget(forecast_final=bad)
    assert line.variance == "0"
    assert line.consumed_pct == 0.0
    assert line.warning_level == "normal"


def test_consumed_pct_still_measures_spend() -> None:
    """Consumption did not move with variance: it is the share of the budget
    already spent, and the warning bands hang off it."""
    line = _budget(revised_budget="100000", actual="96000", forecast_final="98000")
    assert line.consumed_pct == 96.0
    assert line.warning_level == "critical"
