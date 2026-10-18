# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost control demo shows exactly the figures the film script expects.

Table B of the script is what the page must show right after the install,
table C the saved forecasts, table D the figures after each live step of the
series: approving the open change order, putting the order on a cost group,
and entering a manual forecast. If any of these drift, the film no longer
matches the screen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.contracts.models import Contract
from app.modules.costmodel.cost_control import (
    FINDING_CERTIFIED_OVER_COMMITTED,
    FINDING_OVER_PLAN,
    FINDING_PARTLY_AWARDED,
    FINDING_PENDING_CHANGES,
    FINDING_UNASSIGNED,
)
from app.modules.costmodel.cost_control_demo import (
    DEMO_ID,
    PROJECT_NAME,
    install_cost_control_demo,
    post_change_order_to_contract,
)
from app.modules.costmodel.cost_control_schemas import AssignRequest, AssignTarget, ForecastOverrideRequest
from app.modules.costmodel.cost_control_service import CostControlService
from app.modules.costmodel.models import CostLine
from app.modules.projects.models import Project
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal
TODAY = date(2026, 10, 17)
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f11d")

#: Table B: code -> planned, awarded, changes, forecast, source, variance, variance %, certified, paid.
TABLE_B: dict[str, tuple[str, str, str, str, str, str, str | None, str, str]] = {
    "310": ("180000", "172000", "4500", "176500", "final", "-3500", "-1.9", "176500", "167675"),
    "320": ("240000", "251000", "0", "268400", "measured", "28400", "11.8", "268400", "254980"),
    "330": ("520000", "498000", "18600", "516600", "awarded", "-3400", "-0.7", "210000", "199500"),
    "340": ("310000", "96000", "0", "310000", "partly_awarded", "0", "0.0", "0", "0"),
    "410": ("150000", "0", "0", "162000", "estimate", "12000", "8.0", "0", "0"),
    "440": ("210000", "0", "0", "210000", "budget", "0", "0.0", "0", "0"),
    "unassigned": ("0", "24800", "0", "24800", "awarded", "0", None, "0", "0"),
}

DESCRIPTIONS = {
    "310": "Baugrube, Erdbau",
    "320": "Gründung",
    "330": "Außenwände, Fassade",
    "340": "Innenwände, Trockenbau",
    "410": "Abwasser, Wasser, Gas",
    "440": "Starkstromanlagen",
}


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
async def project_id(session: AsyncSession) -> uuid.UUID:
    return await install_cost_control_demo(session, OWNER, today=TODAY)


def _by_code(report) -> dict[str, object]:  # noqa: ANN001
    return {(r.code or r.key): r for r in report.rows}


async def _line(session: AsyncSession, project_id: uuid.UUID, code: str) -> CostLine:
    return (
        await session.execute(select(CostLine).where(CostLine.project_id == project_id, CostLine.code == code))
    ).scalar_one()


async def _headline(
    service: CostControlService, project_id: uuid.UUID
) -> tuple[Decimal, Decimal, Decimal, Decimal, str]:
    report = await service.report(project_id, today=TODAY)
    rows = _by_code(report)
    t = report.totals
    return (
        rows["330"].forecast,  # type: ignore[attr-defined]
        rows["340"].forecast,  # type: ignore[attr-defined]
        D(t["forecast"]),
        D(t["variance"]),
        t["variance_pct"],
    )


async def test_the_project_is_marked_as_a_demo(session: AsyncSession, project_id: uuid.UUID) -> None:
    project = await session.get(Project, project_id)
    assert project is not None
    assert (project.name, project.currency, project.locale) == (PROJECT_NAME, "EUR", "de")
    assert project.address is not None and project.address["city"] == "Musterstadt"
    assert project.metadata_["demo_id"] == DEMO_ID and project.metadata_["is_demo"] is True
    lines = (await session.execute(select(CostLine).where(CostLine.project_id == project_id))).scalars().all()
    assert {line.code: line.description for line in lines} == DESCRIPTIONS


async def test_the_cost_line_table_matches_table_b(session: AsyncSession, project_id: uuid.UUID) -> None:
    report = await CostControlService(session).report(project_id, today=TODAY)
    rows = _by_code(report)
    assert set(rows) == set(TABLE_B)
    for code, expected in TABLE_B.items():
        r = rows[code]
        planned, awarded, changes, forecast, source, var, pct, certified, paid = expected
        got = (
            r.planned,  # type: ignore[attr-defined]
            r.awarded,  # type: ignore[attr-defined]
            r.changes,  # type: ignore[attr-defined]
            r.forecast,  # type: ignore[attr-defined]
            r.forecast_source,  # type: ignore[attr-defined]
            r.variance,  # type: ignore[attr-defined]
            r.variance_pct,  # type: ignore[attr-defined]
            r.certified,  # type: ignore[attr-defined]
            r.paid,  # type: ignore[attr-defined]
        )
        want = (
            D(planned),
            D(awarded),
            D(changes),
            D(forecast),
            source,
            D(var),
            None if pct is None else D(pct),
            D(certified),
            D(paid),
        )
        assert got == want, code
    assert rows["unassigned"].kind == "unassigned"  # type: ignore[attr-defined]


async def test_the_totals_and_headline_figures_match_table_b(session: AsyncSession, project_id: uuid.UUID) -> None:
    report = await CostControlService(session).report(project_id, today=TODAY)
    t = report.totals
    assert D(t["planned"]) == D("1610000")
    assert D(t["awarded"]) == D("1041800")
    assert D(t["changes"]) == D("23100")
    assert D(t["forecast"]) == D("1668300")
    assert D(t["variance"]) == D("58300") and t["variance_pct"] == "3.6"
    assert D(t["certified"]) == D("654900")
    assert D(t["paid"]) == D("622155")
    assert D(t["pending_changes"]) == D("9200") and t["pending_count"] == "1"
    assert D(t["forecast_with_pending"]) == D("1677500")
    assert report.currency == "EUR"


async def test_the_findings_match_table_b(session: AsyncSession, project_id: uuid.UUID) -> None:
    report = await CostControlService(session).report(project_id, today=TODAY)
    found = {(f.rule_id, f.code) for f in report.findings}
    assert found == {
        (FINDING_UNASSIGNED, ""),
        (FINDING_CERTIFIED_OVER_COMMITTED, "320"),
        (FINDING_OVER_PLAN, "320"),
        (FINDING_OVER_PLAN, "410"),
        (FINDING_PARTLY_AWARDED, "340"),
        (FINDING_PENDING_CHANGES, ""),
    }
    by_key = {(f.rule_id, f.code): f for f in report.findings}
    assert by_key[(FINDING_UNASSIGNED, "")].amount == D("24800")
    assert by_key[(FINDING_OVER_PLAN, "320")].details["pct"] == "11.8"
    assert by_key[(FINDING_OVER_PLAN, "410")].details["pct"] == "8.0"
    assert by_key[(FINDING_PARTLY_AWARDED, "340")].details["pct"] == "31"
    assert by_key[(FINDING_PENDING_CHANGES, "")].details["count"] == "1"
    assert by_key[(FINDING_PENDING_CHANGES, "")].amount == D("9200")


async def test_the_saved_forecasts_match_table_c(session: AsyncSession, project_id: uuid.UUID) -> None:
    service = CostControlService(session)
    page = await service.list_snapshots(project_id)
    got = [(s.taken_on, s.stage, s.label, D(s.totals["forecast"])) for s in page.items]
    assert got == [
        ("2026-03-15", "detailed_estimate", "Kostenberechnung Entwurf", D("1610000")),
        ("2026-06-30", "award", "Vergabe Rohbau und Fassade", D("1598000")),
        ("2026-08-31", "forecast", "Kostenbericht August", D("1640000")),
        ("2026-09-30", "forecast", "Kostenbericht September", D("1651200")),
    ]
    # Each stored snapshot reads like one the page saved: rows add up to the totals,
    # and a line's history finds its own row in every one of them.
    for summary in page.items:
        _, detail = await service.get_snapshot(summary.id)
        assert sum(D(r["forecast"]) for r in detail.rows) == D(summary.totals["forecast"])
        assert sum(D(r["planned"]) for r in detail.rows) == D(summary.totals["planned"]) == D("1610000")
    history = await service.line_history(await _line(session, project_id, "320"))
    assert [p.forecast for p in history.snapshots] == [D("240000"), D("251000"), D("256900"), D("268100")]

    report = await service.report(project_id, today=TODAY)
    assert report.last_snapshot is not None and report.last_snapshot.taken_on == "2026-09-30"


async def test_the_saved_forecasts_are_frozen_records_with_their_reasons(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    from app.modules.costmodel.cost_control_forecast import ForecastDocsService

    service = CostControlService(session)
    page = await service.list_snapshots(project_id)
    assert [s.status for s in page.items] == ["frozen"] * 4
    # Each one points at the one before it, so every move reads against the last frozen figure.
    assert [s.previous_snapshot_id for s in page.items[1:]] == [s.id for s in page.items[:-1]]
    _, september = await service.get_snapshot(page.items[-1].id)
    foundations = next(line for line in september.lines if line.code == "320")
    assert foundations.delta == D("11200")
    assert foundations.documented and foundations.comment
    # The ladder from August to September carries the reason on its step.
    ladder = await ForecastDocsService(session).ladder(
        project_id, start=str(page.items[2].id), end=str(page.items[3].id)
    )
    step = next(s for s in ladder.steps if s.code == "320")
    assert step.comment == foundations.comment and len(step.evidence) == 2


async def test_a_second_install_returns_the_same_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    again = await install_cost_control_demo(session, OWNER, today=TODAY)
    assert again == project_id
    count = (
        await session.execute(select(func.count()).select_from(Project).where(Project.name == PROJECT_NAME))
    ).scalar()
    assert count == 1
    lines = (
        await session.execute(select(func.count()).select_from(CostLine).where(CostLine.project_id == project_id))
    ).scalar()
    assert lines == 6


async def test_the_series_moves_the_figures_as_table_d_says(session: AsyncSession, project_id: uuid.UUID) -> None:
    from app.modules.changeorders.service import ChangeOrderService

    service = CostControlService(session)
    assert await _headline(service, project_id) == (D("516600"), D("310000"), D("1668300"), D("58300"), "3.6")

    # Episode 3: N-03 is approved. The approval itself, then the contract side the
    # approval subscriber writes in the running app.
    order = (
        await session.execute(
            select(ChangeOrder).where(ChangeOrder.project_id == project_id, ChangeOrder.code == "N-03")
        )
    ).scalar_one()
    approver = str(uuid.uuid4())
    await ChangeOrderService(session).approve_order(order.id, approver)
    order = await session.get(ChangeOrder, order.id)
    assert order is not None and order.status == "approved"
    contract = (
        await session.execute(select(Contract).where(Contract.project_id == project_id, Contract.code == "SUB-03"))
    ).scalar_one()
    await post_change_order_to_contract(session, contract, order, approved_on=TODAY)
    assert await _headline(service, project_id) == (D("525800"), D("310000"), D("1677500"), D("67500"), "4.2")
    report = await service.report(project_id, today=TODAY)
    assert D(report.totals["pending_changes"]) == D("0") and report.totals["pending_count"] == "0"
    assert FINDING_PENDING_CHANGES not in {f.rule_id for f in report.findings}

    # Episode 4: the order item goes onto cost group 330; the total stays the same.
    page = await service.unassigned(project_id)
    assert [(i.kind, i.group_code, i.amount) for i in page.items] == [("po_item", "B-2026-014", D("24800"))]
    facade = await _line(session, project_id, "330")
    await service.assign(
        project_id,
        AssignRequest(cost_line_id=facade.id, items=[AssignTarget(kind=i.kind, id=i.id) for i in page.items]),
    )
    assert await _headline(service, project_id) == (D("550600"), D("310000"), D("1677500"), D("67500"), "4.2")
    report = await service.report(project_id, today=TODAY)
    assert "unassigned" not in {r.key for r in report.rows}
    assert FINDING_UNASSIGNED not in {f.rule_id for f in report.findings}

    # Episode 5: an own forecast with a reason on cost group 340.
    drywall = await _line(session, project_id, "340")
    await service.set_override(
        drywall,
        ForecastOverrideRequest(amount=D("322400"), reason="Los 2 Trockenbau nach Angebot noch zu vergeben"),
        str(OWNER),
    )
    assert await _headline(service, project_id) == (D("550600"), D("322400"), D("1689900"), D("79900"), "5.0")
    report = await service.report(project_id, today=TODAY)
    row = _by_code(report)["340"]
    assert row.forecast_source == "manual"  # type: ignore[attr-defined]


async def test_the_cli_owner_is_the_named_account_or_the_first_admin(session: AsyncSession) -> None:
    from app.cli import _cost_control_demo_owner
    from app.modules.users.models import User

    editor = User(email="cc-editor@example.test", hashed_password="x", role="editor")
    admin = User(email="cc-admin@example.test", hashed_password="x", role="admin")
    session.add_all([editor, admin])
    await session.flush()
    assert await _cost_control_demo_owner(session, "CC-Editor@example.test") == editor.id
    first_admin = await _cost_control_demo_owner(session, None)
    assert (await session.get(User, first_admin)).role == "admin"  # type: ignore[union-attr]
    with pytest.raises(LookupError):
        await _cost_control_demo_owner(session, "nobody@example.test")
