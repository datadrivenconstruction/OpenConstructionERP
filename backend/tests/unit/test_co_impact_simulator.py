"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Change-order what-if impact simulator + AI/heuristic draft (TOP-30 #11).

Two layers are covered:

* The pure projection / heuristic helpers (no DB) - these are the deterministic
  core that always works, with or without an AI provider key.
* The service ``simulate_impact`` against real PostgreSQL - proving the budget,
  FX, schedule and override wiring lines up with the finance aggregation.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.service import (
    ChangeOrderService,
    _compute_impact_projection,
    _heuristic_days,
    _heuristic_draft,
    _heuristic_money,
)
from app.modules.finance.models import ProjectBudget
from app.modules.projects.models import Project
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


# ── Pure projection math ─────────────────────────────────────────────────────


def test_projection_cost_and_evm_math() -> None:
    proj = _compute_impact_projection(
        bac=Decimal("1000000"),
        ev=Decimal("400000"),
        ac=Decimal("420000"),
        pv=Decimal("1000000"),
        co_cost_base=Decimal("50000"),
        schedule_days=5,
        planned_end="2027-12-31",
        item_count=3,
        target_boq_name="Main BOQ",
    )
    # Cost: budget grows by exactly the CO amount.
    assert proj["cost"]["budget_before"] == "1000000.00"
    assert proj["cost"]["budget_after"] == "1050000.00"
    assert proj["cost"]["delta"] == "50000.00"
    assert proj["cost"]["pct_of_budget"] == 5.0
    # EVM: CPI = 400000/420000 = 0.9524; EAC = AC + (BAC-EV)/CPI.
    assert proj["evm"]["cpi"] == "0.9524"
    assert proj["evm"]["eac_before"] == "1050000.00"
    assert proj["evm"]["eac_after"] == "1102500.00"
    assert proj["evm"]["vac_before"] == "-50000.00"
    assert proj["evm"]["vac_after"] == "-52500.00"


def test_projection_schedule_shifts_end_date() -> None:
    proj = _compute_impact_projection(
        bac=Decimal("0"),
        ev=Decimal("0"),
        ac=Decimal("0"),
        pv=Decimal("0"),
        co_cost_base=Decimal("0"),
        schedule_days=5,
        planned_end="2027-12-31",
        item_count=0,
        target_boq_name=None,
    )
    assert proj["schedule"]["current_end_date"] == "2027-12-31"
    assert proj["schedule"]["projected_end_date"] == "2028-01-05"
    assert proj["schedule"]["finish_moves"] is True


def test_projection_handles_missing_end_date_and_zero_budget() -> None:
    proj = _compute_impact_projection(
        bac=Decimal("0"),
        ev=Decimal("0"),
        ac=Decimal("0"),
        pv=Decimal("0"),
        co_cost_base=Decimal("1000"),
        schedule_days=0,
        planned_end=None,
        item_count=0,
        target_boq_name=None,
    )
    assert proj["schedule"]["current_end_date"] is None
    assert proj["schedule"]["projected_end_date"] is None
    assert proj["schedule"]["finish_moves"] is False
    # No baseline budget -> percentage is 0, not a division error.
    assert proj["cost"]["pct_of_budget"] == 0.0


# ── Heuristic draft (offline, no AI key) ─────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Material cost ~USD 15k", Decimal("15000")),
        ("approx 15,000 CAD extra material", Decimal("15000")),
        ("cost impact EUR 8.500,50", Decimal("8500.50")),
        ("total $1,250,000.00 budget overrun", Decimal("1250000.00")),
        ("no figures, just words", Decimal("0")),
    ],
)
def test_heuristic_money(text: str, expected: Decimal) -> None:
    assert _heuristic_money(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("about 3 days delay expected", 3),
        ("a 10 working days extension", 10),
        ("no schedule mention here", 0),
    ],
)
def test_heuristic_days(text: str, expected: int) -> None:
    assert _heuristic_days(text) == expected


def test_heuristic_draft_shape() -> None:
    draft = _heuristic_draft(
        "Extra excavation due to rock. ~3 days delay. Material cost USD 15k.",
        "CAD",
        "daily_log",
        None,
    )
    assert draft["ai_used"] is False
    assert draft["provider"] == "heuristic"
    assert draft["cost_impact"] == "15000.00"
    assert draft["schedule_impact_days"] == 3
    # Daily-log sourced drafts default to the "unforeseen" reason category.
    assert draft["reason_category"] == "unforeseen"
    assert draft["lines"] and draft["lines"][0]["cost_delta"] == "15000.00"
    assert 0 < draft["confidence"] <= 100


# ── Service-level simulate_impact against real PostgreSQL ────────────────────


async def _seed(
    session: AsyncSession,
    *,
    project_currency: str,
    co_currency: str,
    co_cost: str,
    schedule_days: int,
    revised_budget: str = "1000000",
    fx_rates: list | None = None,
    extra_budget: tuple[str, str] | None = None,
) -> ChangeOrder:
    project = Project(
        name="Impact Sim Project",
        owner_id=str(uuid.uuid4()),
        currency=project_currency,
        planned_end_date="2027-12-31",
        fx_rates=fx_rates or [],
    )
    session.add(project)
    await session.flush()

    session.add(
        ProjectBudget(
            project_id=project.id,
            category="Base",
            currency_code=project_currency,
            original_budget=Decimal("0"),
            revised_budget=Decimal(revised_budget),
            committed=Decimal("0"),
            actual=Decimal("0"),
            forecast_final=Decimal("0"),
        )
    )
    if extra_budget is not None:
        extra_currency, extra_revised = extra_budget
        session.add(
            ProjectBudget(
                project_id=project.id,
                category="Imported package",
                currency_code=extra_currency,
                original_budget=Decimal("0"),
                revised_budget=Decimal(extra_revised),
                committed=Decimal("0"),
                actual=Decimal("0"),
                forecast_final=Decimal("0"),
            )
        )
    order = ChangeOrder(
        project_id=project.id,
        code="CO-001",
        title="Rock excavation",
        description="",
        currency=co_currency,
        cost_impact=Decimal(co_cost),
        schedule_impact_days=schedule_days,
    )
    session.add(order)
    await session.flush()
    return order


@pytest.mark.asyncio
async def test_simulate_same_currency_adds_to_budget(session: AsyncSession) -> None:
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="50000",
        schedule_days=5,
    )
    svc = ChangeOrderService(session)
    result = await svc.simulate_impact(order.id)
    assert result["base_currency"] == "CAD"
    assert result["fx_converted"] is True
    assert result["cost"]["budget_before"] == "1000000.00"
    assert result["cost"]["budget_after"] == "1050000.00"
    assert result["schedule"]["projected_end_date"] == "2028-01-05"
    assert result["evm"]["bac_after"] == "1050000.00"


@pytest.mark.asyncio
async def test_simulate_respects_cost_override(session: AsyncSession) -> None:
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="50000",
        schedule_days=0,
    )
    svc = ChangeOrderService(session)
    result = await svc.simulate_impact(order.id, cost_override="120000", schedule_override=10)
    assert result["cost"]["budget_after"] == "1120000.00"
    assert result["schedule"]["days_added"] == 10


@pytest.mark.asyncio
async def test_simulate_fx_converts_foreign_co_cost(session: AsyncSession) -> None:
    # Project base CAD; CO priced in USD at 1.35 CAD per USD.
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="USD",
        co_cost="50000",
        schedule_days=0,
        fx_rates=[{"code": "USD", "rate": "1.35"}],
    )
    svc = ChangeOrderService(session)
    result = await svc.simulate_impact(order.id)
    assert result["fx_converted"] is True
    assert result["co_cost_base"] == "67500.00"  # 50000 * 1.35
    assert result["cost"]["budget_after"] == "1067500.00"


@pytest.mark.asyncio
async def test_simulate_flags_missing_fx_rate(session: AsyncSession) -> None:
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="USD",
        co_cost="50000",
        schedule_days=0,
        fx_rates=[],  # no USD rate configured
    )
    svc = ChangeOrderService(session)
    result = await svc.simulate_impact(order.id)
    assert result["fx_converted"] is False
    assert any("FX rate" in n for n in result["notes"])


# -- A blended baseline says so ----------------------------------------------
#
# ``_convert_to_base`` sums a currency it has no rate for in that currency's own
# units, so the figure degrades visibly rather than silently shrinking, and it
# returns the code so the caller can say what happened. The five baseline
# figures here dropped that code, which left the blend invisible: the reviewer
# saw one number and no reason to doubt it.


@pytest.mark.asyncio
async def test_simulate_names_the_budget_currency_it_could_not_convert(session: AsyncSession) -> None:
    """A JPY budget line with no rate is counted at face value into a CAD baseline."""
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="50000",
        schedule_days=0,
        extra_budget=("JPY", "1000000"),
        fx_rates=[],  # no JPY rate configured
    )
    svc = ChangeOrderService(session)
    result = await svc.simulate_impact(order.id)

    assert result["baseline_fx_missing"] == ["JPY"]
    assert any("JPY" in n for n in result["notes"])
    # 1,000,000 CAD + 1,000,000 JPY added as though they were the same money.
    # Asserted rather than only warned about, so the note can never drift away
    # from the arithmetic it is describing.
    assert result["cost"]["budget_before"] == "2000000.00"


@pytest.mark.asyncio
async def test_a_clean_co_conversion_does_not_vouch_for_the_baseline(session: AsyncSession) -> None:
    """The discriminating case, and the one that read as entirely clean before.

    The change order is priced in the project's own currency, so ``fx_converted``
    is True and the CO-cost note never fires. The baseline underneath it is
    still blended. One flag answering for the other is what made this invisible.
    """
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="50000",
        schedule_days=0,
        extra_budget=("JPY", "1000000"),
        fx_rates=[],
    )
    svc = ChangeOrderService(session)
    result = await svc.simulate_impact(order.id)

    assert result["fx_converted"] is True
    assert result["baseline_fx_missing"] == ["JPY"]


@pytest.mark.asyncio
async def test_a_rated_budget_currency_is_not_reported_as_missing(session: AsyncSession) -> None:
    """The negative control: the check must be able to come back empty.

    Same two-currency budget, but the rate exists. Nothing is reported missing
    and the JPY line converts, so the test can tell a real conversion apart from
    a warning that never fires.
    """
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="0",
        schedule_days=0,
        extra_budget=("JPY", "1000000"),
        fx_rates=[{"code": "JPY", "rate": "0.01"}],
    )
    svc = ChangeOrderService(session)
    result = await svc.simulate_impact(order.id)

    assert result["baseline_fx_missing"] == []
    assert not any("JPY" in n for n in result["notes"])
    # 1,000,000 CAD + (1,000,000 JPY * 0.01) = 1,010,000 CAD.
    assert result["cost"]["budget_before"] == "1010000.00"


@pytest.mark.asyncio
async def test_a_single_currency_project_reports_nothing_missing(session: AsyncSession) -> None:
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="50000",
        schedule_days=0,
    )
    result = await ChangeOrderService(session).simulate_impact(order.id)
    assert result["baseline_fx_missing"] == []


@pytest.mark.asyncio
async def test_the_snapshot_handed_to_the_audit_trail_carries_the_warning(session: AsyncSession) -> None:
    """The projection that ``publish_scenario`` stores is the one with the caveat.

    A stored figure outlives the reason to doubt it, so the caveat has to travel
    with the snapshot rather than only appear in the live response.

    This one asserts the payload; the stored row is asserted separately below.
    """
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="50000",
        schedule_days=0,
        extra_budget=("JPY", "1000000"),
        fx_rates=[],
    )
    snapshot = await ChangeOrderService(session).simulate_impact(order.id)

    assert snapshot["baseline_fx_missing"] == ["JPY"]
    assert any("JPY" in n for n in snapshot["notes"])


# -- Publishing a scenario actually stores one -------------------------------
#
# Until this was executed, nothing had ever called ``publish_scenario``. The one
# test naming it reads a list of route names to check the route is guarded,
# which is a test about the guard and not about the function, so a total failure
# shipped behind a button in the impact screen. These call it.


async def _published_snapshot(session: AsyncSession) -> dict:
    """Run a projection, publish it, and hand back what was stored."""
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="50000",
        schedule_days=0,
        extra_budget=("JPY", "1000000"),
        fx_rates=[],
    )
    svc = ChangeOrderService(session)
    snapshot = await svc.simulate_impact(order.id)
    saved = await svc.publish_scenario(order.id, snapshot)
    return saved.metadata_["simulations"][-1]["snapshot"]


@pytest.mark.asyncio
async def test_publishing_a_scenario_stores_it(session: AsyncSession) -> None:
    """The flush that used to raise, and the caveat that has to survive it.

    ``simulate_impact`` returns ``order_id`` as a ``uuid.UUID``. Storing the
    dict verbatim in a JSONB column raised on every call, so the audit trail
    this endpoint exists to write had never received a single row.
    """
    stored = await _published_snapshot(session)

    assert stored["baseline_fx_missing"] == ["JPY"]
    assert any("JPY" in n for n in stored["notes"])
    assert stored["cost"]["budget_before"] == "2000000.00"


@pytest.mark.asyncio
async def test_the_stored_scenario_survives_a_json_round_trip(session: AsyncSession) -> None:
    """The regression guard, aimed at the failure rather than at its symptom.

    Asserting a field is present would pass on a dict that still holds a UUID,
    because the failure happened at flush and not at read. Serializing the
    stored row is the same trip the database makes, so this fails the way
    production failed.
    """
    stored = await _published_snapshot(session)

    json.dumps(stored)  # raised "Object of type UUID is not JSON serializable"
    assert isinstance(stored["order_id"], str)


@pytest.mark.asyncio
async def test_publishing_keeps_only_the_last_ten_scenarios(session: AsyncSession) -> None:
    """The documented cap, asserted now that anything can be stored at all.

    The bound was written but never exercised, because no scenario had ever
    been persisted for an eleventh one to push out.
    """
    order = await _seed(
        session,
        project_currency="CAD",
        co_currency="CAD",
        co_cost="1000",
        schedule_days=0,
    )
    svc = ChangeOrderService(session)
    for _ in range(12):
        snapshot = await svc.simulate_impact(order.id)
        saved = await svc.publish_scenario(order.id, snapshot)

    assert len(saved.metadata_["simulations"]) == 10
