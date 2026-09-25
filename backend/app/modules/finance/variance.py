"""What a budget line is expected to finish at, and how far that is from budget.

One function, in one place, because this rule was written three times and only
one of the three was ever corrected. The budget row said "measure the budget
against the outturn we expect, not against what has been spent so far"; the
dashboard total and the Excel export kept subtracting spend. So the same line
reported one number in the table and another in the header, and both of them
overstated the money still available.

The correction that matters most is the one all three shared. Committed money
was not counted anywhere. A line with 48.7 budgeted, 12.4 spent and 33.4 under
signed order reported 36.3 of headroom in green, when what is genuinely free is
15.3. That is not a rounding complaint: it is a cost report inviting somebody
to spend money that is already promised, on the very screen whose job is to
stop them.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = ["expected_outturn", "budget_variance"]


def expected_outturn(
    *,
    forecast_final: Decimal,
    committed: Decimal,
    actual: Decimal,
) -> Decimal:
    """The best evidence we have of what this line will finish at.

    In order of authority:

    A recorded forecast wins. That column exists so a cost engineer can say
    "33.4 is on order but 6 of it will be released, this finishes at 30", and a
    report that quietly recomputed over the top of a typed number would be a
    worse defect than the one this fixes, because the user would have no way to
    see it happening. A forecast below the commitment is a disagreement worth
    showing, not one to smooth away.

    Absent a forecast - and absent is a real state, not a bug, since the
    change-order and BOQ-generated writers insert zero - the line finishes at
    what it has incurred plus what is promised and not yet incurred. The
    ``committed`` column is that open part: a goods receipt or a settled
    invoice moves its amount from committed to actual
    (``FinanceService.sync_project_budget``), so the two are added, never
    compared. Comparing them was right while committed stayed at the full
    order value; since it drains as the work is incurred, the larger of the
    two understated every line with anything received against it.
    """
    if forecast_final > 0:
        return forecast_final
    return committed + actual


def budget_variance(
    *,
    revised_budget: Decimal,
    forecast_final: Decimal,
    committed: Decimal,
    actual: Decimal,
) -> Decimal:
    """How much of the revised budget is still free. Negative means over.

    Positive is money nobody has claimed yet, which is the only reading under
    which the green colour on this column means what a reader takes it to mean.
    """
    return revised_budget - expected_outturn(
        forecast_final=forecast_final,
        committed=committed,
        actual=actual,
    )
