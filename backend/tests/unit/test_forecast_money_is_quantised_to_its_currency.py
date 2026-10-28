"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Forecast money is rounded to the currency it is denominated in.

Two surfaces used to round an amount with a quantum that never looked at the
currency, which is the defect ``app.core.money.money_quantum`` exists to end:

* ``project_intelligence.forecast.compute_cost_forecast`` rounded BAC / EV /
  AC / PV / EAC / ETC / VAC to two decimals. A Kuwaiti dinar lost its third
  digit, a real fils a real payment can carry; a yen gained two decimals
  nothing can settle.
* ``schedule.service_4d.ScheduleDashboardService.dashboard`` rounded the
  S-curve and the WBS rollup to four decimals. Four is never lossy for any
  currency in the registry, so that half of the defect is narrower: it only
  handed 0- and 2-decimal currencies digits they cannot express.

Every assertion here is written against a currency whose minor unit differs
from the old hardcoded quantum, so the test discriminates rather than
restating what the code already did.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_intelligence.forecast import compute_cost_forecast
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.service_4d import ScheduleDashboardService
from tests._pg import transactional_session

# EVM inputs chosen so EAC = BAC / CPI = BAC * AC / EV recurs: with EV 300 and
# AC 301 the ratio is 301/300, so every derived amount has an endless decimal
# tail and the quantum decides what survives.
_BAC = Decimal("1000")
_EV = Decimal("300")
_AC = Decimal("301")
_PV = Decimal("310")


# ── Pure EVM forecast (project_intelligence) ────────────────────────────────


def test_forecast_in_a_zero_decimal_currency_carries_no_decimals():
    """JPY has no subunit, so no forecast amount may show one."""
    fc = compute_cost_forecast(bac=_BAC, ev=_EV, ac=_AC, pv=_PV, currency="JPY")

    # EAC = 1000 * 301 / 300 = 1003.333..., which the old two-decimal quantum
    # rendered as "1003.33" - two digits of a yen that cannot be paid.
    assert fc.eac == "1003"
    assert fc.etc == "702"
    assert fc.vac == "-3"
    # The inputs are echoed through the same helper and must follow too.
    assert fc.bac == "1000"
    assert fc.ev == "300"
    assert fc.ac == "301"
    assert fc.pv == "310"
    for name in ("bac", "ev", "ac", "pv", "eac", "etc", "vac"):
        assert "." not in getattr(fc, name), f"{name} carries a decimal point in JPY"


def test_forecast_in_a_three_decimal_currency_keeps_its_third_digit():
    """KWD is divided into 1000 fils, and the third digit is a real one."""
    fc = compute_cost_forecast(bac=_BAC, ev=_EV, ac=_AC, pv=_PV, currency="KWD")

    # The old quantum truncated these to 1003.33 / 702.33 / -3.33, destroying a
    # fils that no later layer could recover.
    assert fc.eac == "1003.333"
    assert fc.etc == "702.333"
    assert fc.vac == "-3.333"


def test_forecast_without_a_currency_keeps_the_two_decimal_default():
    """A blank code is unknown, not zero-decimal: behaviour is unchanged."""
    fc = compute_cost_forecast(bac=_BAC, ev=_EV, ac=_AC, pv=_PV, currency="")

    assert fc.eac == "1003.33"
    assert fc.etc == "702.33"
    assert fc.vac == "-3.33"


def test_forecast_currency_is_reported_alongside_the_amounts():
    """The code that decided the rounding is on the payload that carries it."""
    fc = compute_cost_forecast(bac=_BAC, ev=_EV, ac=_AC, pv=_PV, currency="HUF")

    assert fc.currency == "HUF"
    # The forint's subunit left circulation, so the registry says zero.
    assert fc.eac == "1003"


# ── 4D dashboard (schedule) ─────────────────────────────────────────────────


async def _seed_project(session: AsyncSession, project_id: uuid.UUID, currency: str) -> None:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        email=f"owner-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="Owner",
    )
    session.add(owner)
    await session.flush()
    session.add(Project(id=project_id, name="Currency dashboard", owner_id=owner.id, currency=currency))
    await session.flush()


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


async def _dashboard_for_currency(session: AsyncSession, currency: str):
    project_id = uuid.uuid4()
    await _seed_project(session, project_id, currency)
    schedule = Schedule(project_id=project_id, name=f"{currency or 'blank'} schedule")
    session.add(schedule)
    await session.flush()
    session.add(
        Activity(
            schedule_id=schedule.id,
            name="Cost-loaded task",
            wbs_code="1.1",
            start_date="2026-01-01",
            end_date="2026-01-11",
            duration_days=10,
            progress_pct="50",
            cost_planned=Decimal("1000"),
            cost_actual=Decimal("400"),
        )
    )
    await session.flush()

    return await ScheduleDashboardService(session).dashboard(schedule.id, date(2026, 1, 11))


def _money_strings(result) -> list[str]:
    """Every money string the dashboard puts on the wire."""
    out: list[str] = []
    for point in result.s_curve_data:
        out.extend([point["planned_value"], point["earned_value"], point["actual_cost"]])
    for bucket in result.by_wbs.values():
        out.extend([bucket["planned_value"], bucket["earned_value"], bucket["actual_cost"]])
    return out


@pytest.mark.asyncio
async def test_dashboard_money_in_a_zero_decimal_currency_has_no_decimals(session: AsyncSession):
    """A yen dashboard must not emit sub-yen digits the old 4dp quantum added."""
    out = await _dashboard_for_currency(session, "JPY")

    amounts = _money_strings(out)
    assert amounts, "the fixture must produce money to inspect"
    offenders = [a for a in amounts if "." in a]
    assert offenders == [], f"JPY amounts carry decimals: {offenders[:5]}"
    # The full planned value lands whole at the last S-curve point.
    assert out.s_curve_data[-1]["planned_value"] == "1000"
    assert out.by_wbs["1"]["planned_value"] == "1000"
    assert out.currency == "JPY"


@pytest.mark.asyncio
async def test_dashboard_money_in_a_two_decimal_currency_has_exactly_two(session: AsyncSession):
    """A euro dashboard emits cents, not the four decimals it used to."""
    out = await _dashboard_for_currency(session, "EUR")

    amounts = _money_strings(out)
    assert amounts, "the fixture must produce money to inspect"
    wrong = [a for a in amounts if len(a.partition(".")[2]) != 2]
    assert wrong == [], f"EUR amounts are not written in cents: {wrong[:5]}"
    assert out.s_curve_data[-1]["planned_value"] == "1000.00"
    assert out.currency == "EUR"


@pytest.mark.asyncio
async def test_dashboard_reports_a_blank_currency_rather_than_guessing(session: AsyncSession):
    """A project with no currency set is unknown, never a guessed code."""
    out = await _dashboard_for_currency(session, "")

    assert out.currency == ""
    # Unknown falls back to two decimals, the least wrong assumption.
    assert out.s_curve_data[-1]["planned_value"] == "1000.00"
