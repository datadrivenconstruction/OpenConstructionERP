# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seeded reconciliation must be a register a commercial manager can read.

The screen it fills is the culmination of the Soll-Ist case: a viewer is told
they will read the margin while the job is running. That promise fails in two
different ways, and only one of them is "the screen is empty".

Empty is the first: the module shipped with no seeder, nothing on the screen
is computed on read, so every install opened on three empty states. That is
what the row counts here gate.

The second is worse because it looks fine. A register whose margin is the same
figure in all three closed months has nothing to say; a register whose totals
disagree with the bill the viewer just looked at on the 5D screen argues
against itself; a register scaled from an invented contract value is a number
nobody can check. Those are what the arithmetic here gates.

Against a real PostgreSQL schema, because the reports carry a unique
constraint on (project_id, period) and the guard that stops a re-run doubling
the register is the thing most likely to break.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

#: The showcase project this test impersonates: the case-5 hero, filmed in
#: German, so the register has to come out in German too.
_DEMO_ID = "office-frankfurt"

#: A fixed day to strike the register against, so the periods under test are
#: predictable. The seeder defaults to the real date; pinning it here is what
#: lets the assertions name months.
_TODAY = date(2026, 8, 14)

#: The priced bill the register must scale itself from. Six positions so the
#: total is not a single round number that could match by accident.
_POSITIONS: tuple[tuple[str, str, str], ...] = (
    ("310", "Baugrube ausheben und abfahren", "420000.00"),
    ("320", "Gruendung, Bodenplatte C30/37", "1850000.00"),
    ("330", "Aussenwaende, Stahlbeton", "4300000.00"),
    ("340", "Innenwaende und Stuetzen", "2100000.00"),
    ("420", "Waermeversorgungsanlagen", "1640000.00"),
    ("430", "Raumlufttechnische Anlagen", "1690000.00"),
)

#: What those six add up to. Written out rather than summed in the test, so a
#: fixture edited without thinking fails here instead of silently moving every
#: expectation with it.
_BILL_TOTAL = Decimal("12000000.00")


async def _make_frankfurt(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Create the project, its owner and its priced bill, as the installer does."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "kaufmaennische-leitung-cvr@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference commercial lead")
        session.add(owner)
        await session.flush()

    name = "Buerogebaeude Europaviertel CVR"
    project = (await session.execute(select(Project).where(Project.name == name))).scalars().first()
    if project is None:
        project = Project(
            name=name,
            owner_id=owner.id,
            country_code="DE",
            currency="EUR",
            locale="de",
            metadata_={"demo_id": _DEMO_ID},
        )
        session.add(project)
        await session.flush()

        boq = BOQ(project_id=project.id, name="Kostenberechnung nach DIN 276", status="approved")
        session.add(boq)
        await session.flush()
        for index, (ordinal, description, total) in enumerate(_POSITIONS):
            session.add(
                Position(
                    boq_id=boq.id,
                    ordinal=ordinal,
                    description=description,
                    unit="psch",
                    quantity="1",
                    unit_rate=total,
                    total=total,
                    sort_order=index,
                )
            )
        await session.flush()
    return uuid.UUID(str(project.id)), uuid.UUID(str(owner.id))


async def _reports(session, project_id: uuid.UUID):
    from app.modules.cvr.models import CvrReport

    rows = await session.execute(select(CvrReport).where(CvrReport.project_id == project_id).order_by(CvrReport.period))
    return list(rows.scalars().all())


async def _lines(session, report_id: uuid.UUID):
    from app.modules.cvr.models import CvrLine

    rows = await session.execute(select(CvrLine).where(CvrLine.report_id == report_id).order_by(CvrLine.sort_order))
    return list(rows.scalars().all())


async def test_the_register_carries_three_closed_months_and_the_one_running(pg_session) -> None:
    """Three finals in consecutive months, plus the month in progress as a draft.

    One report is not a reconciliation: the whole value of the screen is that
    the margin can be seen moving. Three closed months is the minimum that
    shows a direction rather than a point.
    """
    from app.modules.cvr.seed import seed_cvr_demo

    pid, _owner = await _make_frankfurt(pg_session)
    report = await seed_cvr_demo(pg_session, [pid], today=_TODAY)
    assert report["projects"] == 1, f"the seeder skipped its own project: {report}"

    reports = await _reports(pg_session, pid)
    assert len(reports) == report["reports"] == 4

    assert [r.period for r in reports] == ["2026-05", "2026-06", "2026-07", "2026-08"]
    assert [r.status for r in reports] == ["final", "final", "final", "draft"]
    assert {r.currency for r in reports} == {"EUR"}, "a reconciliation with no currency code cannot be totalled"


async def test_the_register_speaks_german_on_a_german_project(pg_session) -> None:
    """Titles, notes and cost heads are the site's own language, not English.

    The screen is filmed in German. A register whose every figure is right and
    whose every word is English is not usable in the film it exists for.
    """
    from app.modules.cvr.models import CashflowPoint
    from app.modules.cvr.seed import seed_cvr_demo

    pid, _owner = await _make_frankfurt(pg_session)
    await seed_cvr_demo(pg_session, [pid], today=_TODAY)

    reports = await _reports(pg_session, pid)
    assert reports[0].title == "Kosten-Wert-Abgleich Mai 2026"
    assert reports[-1].title == "Kosten-Wert-Abgleich August 2026"
    for row in reports:
        assert "Monat" in (row.notes or ""), f"the note on {row.period} is not German: {row.notes!r}"

    heads = [line.description for line in await _lines(pg_session, reports[0].id)]
    assert heads[0].startswith("KG 300"), f"a German bill is grouped by DIN 276, got {heads[0]!r}"
    assert "Nachträge (beauftragt)" in heads

    points = (await pg_session.execute(select(CashflowPoint).where(CashflowPoint.project_id == pid))).scalars().all()
    assert {p.label for p in points} == {"Ist", "Prognose"}


async def test_the_totals_reconcile_against_the_projects_own_bill(pg_session) -> None:
    """Forecast value equals the priced bill, and cost never exceeds its forecast.

    The viewer arrives from the 5D screen, which totals the same bill. A
    register scaled from anything else disagrees with the screen they just
    left, and the module's own advisory flag fires whenever a position to date
    has already passed the forecast it is measured against.
    """
    from app.modules.cvr.compute import summarise_lines
    from app.modules.cvr.seed import seed_cvr_demo

    pid, _owner = await _make_frankfurt(pg_session)
    await seed_cvr_demo(pg_session, [pid], today=_TODAY)

    for row in await _reports(pg_session, pid):
        lines = await _lines(pg_session, row.id)
        assert len(lines) == 6
        summary = summarise_lines(lines)
        assert summary["total_forecast_value"] == _BILL_TOTAL, (
            f"{row.period} forecasts {summary['total_forecast_value']} against a bill of {_BILL_TOTAL}"
        )
        assert not summary["warnings"], f"{row.period} trips the module's own forecast flags: {summary['warnings']}"
        for line in lines:
            assert line.accruals > 0, f"{line.cost_code} books no accrual, so the column reads as unused"


async def test_the_margin_moves_from_month_to_month(pg_session) -> None:
    """The whole point of the screen: three closed months, three different margins.

    A register that repeats one figure has nothing to report. The direction is
    asserted too - the seeded story is a job whose services package is
    overrunning, so the blended margin erodes as that package catches up.
    """
    from app.modules.cvr.compute import summarise_lines
    from app.modules.cvr.seed import seed_cvr_demo

    pid, _owner = await _make_frankfurt(pg_session)
    await seed_cvr_demo(pg_session, [pid], today=_TODAY)

    margins = []
    for row in await _reports(pg_session, pid):
        summary = summarise_lines(await _lines(pg_session, row.id))
        assert summary["total_value_to_date"] > 0, f"{row.period} has earned nothing"
        margins.append(summary["margin_to_date_pct"])

    assert len(set(margins)) == len(margins), f"the margin does not move: {margins}"
    assert margins == sorted(margins, reverse=True), f"the seeded overrun should erode the margin: {margins}"
    assert all(Decimal("0") < m < Decimal("20") for m in margins), f"implausible margins: {margins}"


async def test_the_cashflow_curve_spans_the_job_and_starts_out_of_pocket(pg_session) -> None:
    """Eighteen months, cumulative, and negative early - the contractor funds the work.

    A cashflow that is positive from the first month is not a construction
    cashflow; it is the defect of paying yourself before you have built
    anything. The curve is also what the report periods are struck from, so
    its month count and the report months have to line up.
    """
    from app.modules.cvr.compute import cumulative_series
    from app.modules.cvr.models import CashflowPoint
    from app.modules.cvr.seed import seed_cvr_demo

    pid, _owner = await _make_frankfurt(pg_session)
    counts = await seed_cvr_demo(pg_session, [pid], today=_TODAY)
    assert counts["cashflow_points"] == 18

    points = (
        (
            await pg_session.execute(
                select(CashflowPoint).where(CashflowPoint.project_id == pid).order_by(CashflowPoint.period)
            )
        )
        .scalars()
        .all()
    )
    assert points[0].period == "2025-09"
    assert points[-1].period == "2027-02"

    series = cumulative_series(points)
    assert series["points"][0]["cumulative_net"] < 0, "the first month should show the contractor out of pocket"
    assert series["net_position"] > 0, "the job should end in the black"

    # The curve closes on the whole bill because the last month is the final
    # account: retention comes back and nothing is left outstanding. What the
    # client still holds mid-job is visible instead in the month before it.
    assert series["total_cash_in"] == _BILL_TOTAL
    assert series["points"][-2]["cumulative_cash_in"] < _BILL_TOTAL

    # The curve and the reports are one story, not two: what the job is
    # forecast to make is what the cashflow closes on.
    from app.core.demo_commercial import forecast_margin

    assert series["net_position"] == pytest.approx(_BILL_TOTAL * forecast_margin(), abs=Decimal("1"))


async def test_the_applications_net_off_the_retention_they_state(pg_session) -> None:
    """Net is gross less retention on every row, and the lifecycle is visible.

    The service recomputes ``net_value`` on every write; the seeder writes ORM
    rows straight past it, which is exactly the path where the three figures
    drift apart unnoticed.
    """
    from app.modules.cvr.models import PaymentApplication
    from app.modules.cvr.seed import seed_cvr_demo

    pid, _owner = await _make_frankfurt(pg_session)
    await seed_cvr_demo(pg_session, [pid], today=_TODAY)

    rows = (
        (
            await pg_session.execute(
                select(PaymentApplication)
                .where(PaymentApplication.project_id == pid)
                .order_by(PaymentApplication.period)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 4
    for row in rows:
        assert row.net_value == row.gross_value - row.retention
        assert row.gross_value > 0
        assert row.retention > 0, "an application that withholds nothing states a retention it did not apply"
        assert row.application_number

    assert [r.status for r in rows] == ["paid", "paid", "certified", "submitted"]


async def test_a_second_run_leaves_the_register_alone(pg_session) -> None:
    """Re-running the seed adds nothing.

    The boot backfill re-runs on every version upgrade, and the report table
    carries a unique constraint on (project_id, period): a guard that does not
    hold turns an upgrade into a failed transaction rather than a duplicate.
    """
    from app.modules.cvr.seed import seed_cvr_demo

    pid, _owner = await _make_frankfurt(pg_session)
    first = await seed_cvr_demo(pg_session, [pid], today=_TODAY)
    assert first["reports"] == 4

    second = await seed_cvr_demo(pg_session, [pid], today=_TODAY)
    assert second == {"projects": 0, "reports": 0, "lines": 0, "cashflow_points": 0, "applications": 0}
    assert len(await _reports(pg_session, pid)) == 4


async def test_a_project_that_is_not_ours_is_left_alone(pg_session) -> None:
    """No demo marker, no register.

    The backfill hands this seeder every project on the installation. A
    reconciliation states what a job earned and what it cost, so writing one
    into a customer's live project is a data incident and not an untidy
    screen. The gate is ownership, and a project with no bill is skipped too
    rather than given an invented contract value.
    """
    from app.modules.cvr.seed import seed_cvr_demo
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "kunde-cvr@reference.example"
    owner = (await pg_session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Customer")
        pg_session.add(owner)
        await pg_session.flush()

    live = Project(name="Kundenprojekt ohne Demo-Marke", owner_id=owner.id, currency="EUR", metadata_={})
    pg_session.add(live)
    await pg_session.flush()

    report = await seed_cvr_demo(pg_session, [uuid.UUID(str(live.id))], today=_TODAY)
    assert report["projects"] == 0
    assert await _reports(pg_session, uuid.UUID(str(live.id))) == []
