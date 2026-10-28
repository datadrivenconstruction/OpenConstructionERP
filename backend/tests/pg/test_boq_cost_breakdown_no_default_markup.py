"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the cost breakdown must not invent overhead or profit.

``get_cost_breakdown`` used to fall back to a synthetic 15% overhead plus 10%
profit whenever a BOQ had no markup rows, and fold both into ``grand_total``.
The BOQ editor reads a different endpoint (``get_boq_structured``), which never
invents markups, so one screen showed two figures 25% apart under the same
"Grand Total" label and the larger one was money nobody had entered.

The properties pinned here are about money reaching a costing screen, so they
run against a real cluster in the only lane that gates anything. The mock
repository suites cannot see this: the fallback lived in the service and the
disagreement only shows up when both endpoints answer for the same stored BOQ.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User

# One position, a round number, chosen so a 15/10 fallback would be unmistakable:
# 7,905,000 x 1.25 = 9,881,250, the exact pair reported from the running app.
POSITION_TOTAL = "7905000.00"


async def _boq_with_one_position(session) -> BOQ:
    """A stored BOQ carrying a single priced position and no markup rows."""
    owner = User(email="breakdown@example.test", hashed_password="x", full_name="Breakdown")
    session.add(owner)
    await session.flush()

    project = Project(name="Cost breakdown", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="No markups")
    session.add(boq)
    await session.flush()

    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01.001",
            description="Reinforced concrete wall",
            unit="m3",
            quantity="1",
            unit_rate=POSITION_TOTAL,
            total=POSITION_TOTAL,
        )
    )
    await session.flush()
    return boq


@pytest.mark.asyncio
async def test_grand_total_equals_direct_cost_when_no_markups(pg_session) -> None:
    """No markup rows means no markup. Not a typical markup, none."""
    boq = await _boq_with_one_position(pg_session)

    result = await BOQService(pg_session).get_cost_breakdown(boq.id)

    assert result.markups == [], "a BOQ with no markup rows must report no markups"
    assert Decimal(str(result.direct_cost)) == Decimal(POSITION_TOTAL)
    assert Decimal(str(result.grand_total)) == Decimal(POSITION_TOTAL)


@pytest.mark.asyncio
async def test_the_old_synthetic_markup_is_gone(pg_session) -> None:
    """Pins the exact number the fallback produced, so its return is loud.

    Asserting only "grand_total == direct_cost" would also pass if someone
    replaced 15/10 with 0/0 while leaving the invented rows in place. This
    checks the figure itself and the absence of the two names it used.
    """
    boq = await _boq_with_one_position(pg_session)

    result = await BOQService(pg_session).get_cost_breakdown(boq.id)

    assert Decimal(str(result.grand_total)) != Decimal("9881250.00")
    names = {m.name for m in result.markups}
    assert "Overhead" not in names
    assert "Profit" not in names


@pytest.mark.asyncio
async def test_real_markups_are_still_applied(pg_session) -> None:
    """The removal must not have cost us real markups.

    Without this, deleting the whole markup branch would leave both tests above
    green while silently dropping every markup a user actually entered.
    """
    boq = await _boq_with_one_position(pg_session)
    pg_session.add(
        BOQMarkup(
            boq_id=boq.id,
            name="Site overhead",
            markup_type="percentage",
            category="overhead",
            percentage="10",
            apply_to="direct_cost",
            is_active=True,
        )
    )
    await pg_session.flush()

    result = await BOQService(pg_session).get_cost_breakdown(boq.id)

    assert [m.name for m in result.markups] == ["Site overhead"]
    expected = Decimal(POSITION_TOTAL) * Decimal("1.10")
    assert Decimal(str(result.grand_total)).quantize(Decimal("0.01")) == expected.quantize(Decimal("0.01"))
