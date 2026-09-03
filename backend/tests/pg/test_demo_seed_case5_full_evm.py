# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seeded baseline must be a plan the earned-value screen can measure against.

Two steps of the cost-control walkthrough land on this screen, the one that
freezes the plan and the one that reads the forecast, and the module shipped
with no seeder, so both opened on "this project has no baseline".

Filling the table is the easy half. The half that matters is that the numbers
close: a curve that is cumulative rather than per-period, a budget that is the
cost side of the bill rather than the bill itself, indices that follow from the
observations rather than being asserted next to them, and an actual cost that
is the same money the reconciliation screen shows one click earlier. Each of
those is a way to fill the screen and still be wrong.

Against a real PostgreSQL schema: the baseline carries a unique constraint on
(project_id, name) and the measures one on (baseline_id, data_date), so the
guard that stops a re-run doubling the register is what a version upgrade
would otherwise turn into a failed transaction.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

_DEMO_ID = "office-frankfurt"

#: Fixed so the periods under test can be named.
_TODAY = date(2026, 8, 14)

_POSITIONS: tuple[tuple[str, str, str], ...] = (
    ("310", "Baugrube ausheben und abfahren", "420000.00"),
    ("320", "Gruendung, Bodenplatte C30/37", "1850000.00"),
    ("330", "Aussenwaende, Stahlbeton", "4300000.00"),
    ("340", "Innenwaende und Stuetzen", "2100000.00"),
    ("420", "Waermeversorgungsanlagen", "1640000.00"),
    ("430", "Raumlufttechnische Anlagen", "1690000.00"),
)

_BILL_TOTAL = Decimal("12000000.00")


async def _make_project(session, *, name: str, demo: bool = True, locale: str = "de") -> tuple[uuid.UUID, uuid.UUID]:
    """Create the project, its owner and its priced bill, as the installer does."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "projektsteuerung-evm@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference project controls lead")
        session.add(owner)
        await session.flush()

    project = (await session.execute(select(Project).where(Project.name == name))).scalars().first()
    if project is None:
        project = Project(
            name=name,
            owner_id=owner.id,
            country_code="DE",
            currency="EUR",
            locale=locale,
            metadata_={"demo_id": _DEMO_ID} if demo else {},
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


async def _baseline(session, project_id: uuid.UUID):
    from app.modules.full_evm.models import EVMBaseline

    rows = await session.execute(select(EVMBaseline).where(EVMBaseline.project_id == project_id))
    return rows.scalars().all()


async def _measures(session, project_id: uuid.UUID):
    from app.modules.full_evm.models import EVMMeasure

    rows = await session.execute(
        select(EVMMeasure).where(EVMMeasure.project_id == project_id).order_by(EVMMeasure.data_date)
    )
    return list(rows.scalars().all())


async def test_the_project_gets_exactly_one_approved_baseline(pg_session) -> None:
    """One baseline, approved, named in the project's own language.

    Only one baseline is approved at a time, and the rule is enforced by the
    service rather than by the schema. This seeder writes rows past the
    service, so a second approved row would be a state the product considers
    impossible and nothing in the database would object.
    """
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Buerogebaeude Europaviertel EVM")
    report = await seed_full_evm_demo(pg_session, [pid], today=_TODAY)
    assert report["projects"] == 1, f"the seeder skipped its own project: {report}"

    rows = await _baseline(pg_session, pid)
    assert len(rows) == 1
    baseline = rows[0]
    assert baseline.status == "approved"
    assert baseline.approved_at is not None
    assert baseline.name == "Basisplan Ausführung", "a German project's plan is not named in English"
    assert baseline.currency == "EUR"

    # Validation is left as the engine found it. Stamping a plan "passed"
    # without running the rule set would be inventing an approval.
    assert baseline.validation_status == "pending"
    assert baseline.validation_findings == []
    assert baseline.validation_score is None


async def test_the_budget_is_the_cost_side_of_the_bill_not_the_bill(pg_session) -> None:
    """BAC is what the job was priced to cost, not what it sells for.

    Using the bill itself as the budget reports every job as finishing under
    budget by exactly its own margin, which is a number that always looks
    healthy and never means anything.
    """
    from app.core.demo_commercial import budget_share_total
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Buerogebaeude Europaviertel EVM Budget")
    await seed_full_evm_demo(pg_session, [pid], today=_TODAY)

    baseline = (await _baseline(pg_session, pid))[0]
    assert baseline.bac < _BILL_TOTAL, "the budget cannot be the whole bill; the margin is not cost"
    assert baseline.bac == pytest.approx(_BILL_TOTAL * budget_share_total(), abs=Decimal("1"))


async def test_the_curve_is_cumulative_and_reaches_the_budget(pg_session) -> None:
    """Eighteen points, never decreasing, closing on the budget.

    ``planned_value`` is cumulative to the period end. Writing the amount
    planned *within* the period into that column is the commonest way to get a
    curve wrong, and the module carries a monotonicity rule precisely because
    a curve that goes down is always a data fault.
    """
    from app.modules.full_evm.models import EVMBaselinePeriod
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Buerogebaeude Europaviertel EVM Kurve")
    counts = await seed_full_evm_demo(pg_session, [pid], today=_TODAY)
    assert counts["periods"] == 18

    baseline = (await _baseline(pg_session, pid))[0]
    rows = (
        (
            await pg_session.execute(
                select(EVMBaselinePeriod)
                .where(EVMBaselinePeriod.baseline_id == baseline.id)
                .order_by(EVMBaselinePeriod.ordinal)
            )
        )
        .scalars()
        .all()
    )
    assert [p.ordinal for p in rows] == list(range(18))

    values = [p.planned_value for p in rows]
    assert values == sorted(values), f"the planned-value curve is not cumulative: {values[:4]}"
    assert values[0] > 0
    assert values[-1] == pytest.approx(baseline.bac, abs=Decimal("1")), "the curve must close on the budget"

    # Period ends are month ends, ascending, and the last one is the finish.
    ends = [p.period_end for p in rows]
    assert ends == sorted(ends)
    assert ends[0] == date(2025, 9, 30)
    assert ends[-1] == date(2027, 2, 28)
    assert baseline.finish_date == ends[-1]


async def test_every_index_follows_from_the_observations(pg_session) -> None:
    """SV, CV, SPI, CPI and the forecast are recomputed, not trusted.

    A seeder that writes its own CPI can write one that does not follow from
    its own EV and AC. Recomputing here from the three stored observations is
    what makes the stored figures a claim the test can refute.
    """
    from app.modules.full_evm.metrics import compute_metrics
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Buerogebaeude Europaviertel EVM Indizes")
    counts = await seed_full_evm_demo(pg_session, [pid], today=_TODAY)
    assert counts["measures"] == 6

    # The stored figures were computed from unrounded observations and then
    # quantized on the way in, so recomputing from the rounded values can move
    # the last unit. A tolerance of one unit is the difference between "this
    # was derived" and "this was typed next to it", which is what is under
    # test; the exact figure is compute_metrics' own business and it has its
    # own tests.
    penny = Decimal("0.05")
    for measure in await _measures(pg_session, pid):
        expected = compute_metrics(
            bac=measure.bac, pv=measure.pv, ev=measure.ev, ac=measure.ac, method=measure.eac_method
        )
        assert measure.sv == expected.sv, f"{measure.data_date} schedule variance is not EV - PV"
        assert measure.cv == expected.cv, f"{measure.data_date} cost variance is not EV - AC"
        assert measure.spi == pytest.approx(expected.spi, abs=penny)
        assert measure.cpi == pytest.approx(expected.cpi, abs=penny)
        assert measure.eac == pytest.approx(expected.eac, abs=Decimal("1"))
        assert measure.etc_ == pytest.approx(expected.etc, abs=Decimal("1"))
        assert measure.vac == pytest.approx(expected.vac, abs=Decimal("1"))
        assert measure.eac_method_effective == expected.eac_method_effective
        assert set(measure.eac_variants) == set(expected.eac_variants), "the audit trail drops a formula"


async def test_the_job_reads_as_behind_and_over_spent(pg_session) -> None:
    """The seeded job is late and losing money, and both show up as indices.

    A demo where planned and actual coincide reports SPI and CPI of exactly
    one on every row, which teaches a viewer nothing about what the columns
    are for. The direction is asserted, not just the movement: the forecast
    outturn has to exceed the budget, and the variance at completion has to be
    the negative number that says so.
    """
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Buerogebaeude Europaviertel EVM Trend")
    await seed_full_evm_demo(pg_session, [pid], today=_TODAY)

    measures = await _measures(pg_session, pid)
    for measure in measures:
        assert measure.spi is not None and measure.spi < 1, f"{measure.data_date} is not behind schedule"
        assert measure.cpi is not None and measure.cpi < 1, f"{measure.data_date} is not over cost"
        assert measure.eac is not None and measure.eac > measure.bac, f"{measure.data_date} forecasts no overrun"
        assert measure.vac is not None and measure.vac < 0
        assert measure.ev < measure.pv
        assert measure.ac > measure.ev

    # The job keeps going: the newest measurement has earned the most.
    earned = [m.ev for m in measures]
    assert earned == sorted(earned)
    assert len(set(earned)) == len(earned), "the measurements repeat one position"
    assert measures[-1].data_date == date(2026, 8, 31)


async def test_the_actual_cost_is_the_money_the_reconciliation_shows(pg_session) -> None:
    """One job, two screens, the same spend.

    A viewer reads cost to date on the reconciliation and actual cost on this
    screen within a minute of each other. Two seeders each inventing their own
    progress would put two different numbers under two labels that mean the
    same thing, and the viewer would be right to stop trusting both.
    """
    from app.modules.cvr.compute import summarise_lines
    from app.modules.cvr.models import CvrLine, CvrReport
    from app.modules.cvr.seed import seed_cvr_demo
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Buerogebaeude Europaviertel EVM Abgleich")
    await seed_cvr_demo(pg_session, [pid], today=_TODAY)
    await seed_full_evm_demo(pg_session, [pid], today=_TODAY)

    report = (
        (await pg_session.execute(select(CvrReport).where(CvrReport.project_id == pid, CvrReport.period == "2026-08")))
        .scalars()
        .one()
    )
    lines = (await pg_session.execute(select(CvrLine).where(CvrLine.report_id == report.id))).scalars().all()
    cost_to_date = summarise_lines(lines)["total_cost_to_date"]

    measure = (await _measures(pg_session, pid))[-1]
    assert measure.data_date == date(2026, 8, 31), "the newest measurement is not the month the report covers"
    assert measure.ac == pytest.approx(cost_to_date, abs=Decimal("1")), (
        f"the two screens disagree about what the job has cost: {measure.ac} against {cost_to_date}"
    )


async def test_a_second_run_leaves_the_baseline_alone(pg_session) -> None:
    """Re-running the seed adds nothing.

    The boot backfill re-runs on every version upgrade, and the baseline
    carries a unique constraint on (project_id, name): a guard that does not
    hold turns an upgrade into a failed transaction.
    """
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Buerogebaeude Europaviertel EVM Wiederholung")
    first = await seed_full_evm_demo(pg_session, [pid], today=_TODAY)
    assert first["baselines"] == 1

    second = await seed_full_evm_demo(pg_session, [pid], today=_TODAY)
    assert second == {"projects": 0, "baselines": 0, "periods": 0, "measures": 0}
    assert len(await _baseline(pg_session, pid)) == 1


async def test_a_project_that_is_not_ours_is_left_alone(pg_session) -> None:
    """No demo marker, no baseline.

    The backfill hands this seeder every project on the installation, and an
    approved baseline is a plan somebody signed. Writing one into a customer's
    live project is a data incident, not an untidy screen.
    """
    from app.modules.full_evm.seed import seed_full_evm_demo

    pid, _owner = await _make_project(pg_session, name="Kundenprojekt ohne Demo-Marke EVM", demo=False)
    report = await seed_full_evm_demo(pg_session, [pid], today=_TODAY)
    assert report["projects"] == 0
    assert await _baseline(pg_session, pid) == []
