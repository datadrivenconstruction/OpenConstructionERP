# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the cost-weighted trade matrix and the CSV snapshot export.

These cover the deepening work that wires the existing clash_cost_impact
arithmetic into the coordination hub:

* every trade-matrix cell now carries the summed open ``cost_impact`` of
  its discipline pair, re-bucketed into the matrix's 6-trade vocabulary;
* the response carries the project currency + a ``total_cost_impact``;
* the CSV export serialises the live dashboard + alerts + cost-weighted
  pair breakdown into one parseable file (and always bypasses the cache).

They drive the service directly against a transaction-isolated PostgreSQL
session + minimal seed, mirroring ``test_aggregation.py``.
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.coordination_hub.service import (
    _DASHBOARD_CACHE,
    CoordinationHubService,
)
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session + seeded user + project."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"cohub-cm-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Hub Tester",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Coordination Hub Cost Test",
            owner_id=owner.id,
            currency="EUR",
            budget_estimate="1000000",
        )
        s.add(project)
        await s.commit()
        s.info["project_id"] = project.id
        s.info["owner_id"] = str(owner.id)
        _DASHBOARD_CACHE.clear()
        yield s


def _make_run(project_id, name: str):
    from app.modules.clash.models import ClashRun

    return ClashRun(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        model_ids=[],
        clash_type="hard",
        tolerance_m=0.01,
        clearance_m=0.0,
        mode="cross_discipline",
        status="completed",
        element_count=0,
        total_clashes=0,
        summary={},
        rules=[],
        spatial_grid_mm=500,
        created_by="tester",
    )


def _make_result(
    run,
    *,
    a_disc: str,
    b_disc: str,
    status_: str = "new",
    a_stable: str = "A",
    b_stable: str = "B",
):
    from app.modules.clash.models import ClashResult

    return ClashResult(
        id=uuid.uuid4(),
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id=a_stable,
        b_stable_id=b_stable,
        a_name="a",
        b_name="b",
        a_discipline=a_disc,
        b_discipline=b_disc,
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.05,
        distance_m=0.0,
        cx=0.0,
        cy=0.0,
        cz=0.0,
        status=status_,
        severity="medium",
        signature=uuid.uuid4().hex[:16],
    )


# ── Cost-weighted trade matrix ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trade_matrix_cell_carries_cost_impact(session: AsyncSession) -> None:
    """An open arch/struct clash linked to a priced BOQ position produces
    a positive ``cost_impact`` on that cell, and the response totals it."""
    project_id = session.info["project_id"]
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="T", description="")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01",
            description="wall",
            unit="m3",
            quantity="10",
            unit_rate="100",
            total="1000",
            cad_element_ids=["EP-A"],
        )
    )
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    session.add(
        _make_result(
            run,
            a_disc="Architectural",
            b_disc="Structural",
            a_stable="EP-A",
            b_stable="EP-B",
        )
    )
    await session.commit()

    svc = CoordinationHubService(session)
    matrix = await svc.trade_matrix(project_id, currency="EUR")

    pair_to_cell = {(c.row, c.col): c for c in matrix.cells}
    assert ("arch", "struct") in pair_to_cell
    cell = pair_to_cell[("arch", "struct")]
    assert cell.open == 1
    # 10% of 1000 rework + labour hours @ default rate => strictly positive.
    assert cell.cost_impact > Decimal("0")
    # The response total equals the sum of the cells.
    assert matrix.total_cost_impact == sum((c.cost_impact for c in matrix.cells), Decimal("0"))
    assert matrix.currency == "EUR"


@pytest.mark.asyncio
async def test_trade_matrix_folds_mep_subdisciplines_into_one_cell(
    session: AsyncSession,
) -> None:
    """Mechanical and Electrical both fold into ``mep`` for the matrix, so
    their cost impact lands on the same canonical cell (the cost service
    keeps them apart, the hub re-buckets to the 6-trade vocabulary)."""
    project_id = session.info["project_id"]
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    session.add(_make_result(run, a_disc="Mechanical", b_disc="Structural"))
    session.add(_make_result(run, a_disc="Electrical", b_disc="Structural"))
    await session.commit()

    svc = CoordinationHubService(session)
    matrix = await svc.trade_matrix(project_id, currency="EUR")
    pair_to_cell = {(c.row, c.col): c for c in matrix.cells}
    # Both mechanical and electrical x structural collapse to (mep, struct).
    assert ("mep", "struct") in pair_to_cell
    assert pair_to_cell[("mep", "struct")].count == 2


@pytest.mark.asyncio
async def test_trade_matrix_cost_zero_when_no_priced_positions(
    session: AsyncSession,
) -> None:
    """No BOQ overlap means labour-only impact; an unlinked clash still
    yields a non-negative (never None) cost_impact and never 500s."""
    project_id = session.info["project_id"]
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    # GUID-less clash (no stable ids) => labour hours = 0 in the kernel.
    session.add(_make_result(run, a_disc="Architectural", b_disc="Structural", a_stable="", b_stable=""))
    await session.commit()

    svc = CoordinationHubService(session)
    matrix = await svc.trade_matrix(project_id, currency="EUR")
    pair_to_cell = {(c.row, c.col): c for c in matrix.cells}
    cell = pair_to_cell[("arch", "struct")]
    assert cell.cost_impact == Decimal("0")


@pytest.mark.asyncio
async def test_trade_matrix_cost_serialises_as_string_in_json(
    session: AsyncSession,
) -> None:
    """The Decimal money fields emit as plain strings on the JSON wire."""
    project_id = session.info["project_id"]
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    session.add(_make_result(run, a_disc="arch", b_disc="struct"))
    await session.commit()

    svc = CoordinationHubService(session)
    matrix = await svc.trade_matrix(project_id, currency="EUR")
    dumped = matrix.model_dump(mode="json")
    assert isinstance(dumped["total_cost_impact"], str)
    for cell in dumped["cells"]:
        assert isinstance(cell["cost_impact"], str)


# ── CSV snapshot export ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_snapshot_csv_has_all_three_sections(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="T", description="")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01",
            description="wall",
            unit="m3",
            quantity="10",
            unit_rate="100",
            total="1000",
            cad_element_ids=["EP-A"],
        )
    )
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    session.add(
        _make_result(
            run,
            a_disc="Architectural",
            b_disc="Structural",
            a_stable="EP-A",
            b_stable="EP-B",
        )
    )
    await session.commit()

    svc = CoordinationHubService(session)
    csv_text = await svc.export_snapshot_csv(project_id, currency="EUR")

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == ["section", "key", "value", "detail", "currency"]
    sections = {r[0] for r in rows[1:]}
    assert "kpi" in sections
    assert "alert" in sections
    assert "trade_pair" in sections

    # The open-clash KPI reflects the seeded clash.
    kpi = {r[1]: r[2] for r in rows[1:] if r[0] == "kpi"}
    assert kpi["open_clashes"] == "1"
    # The trade-pair block names the arch x struct pair with a cost detail.
    pair_rows = [r for r in rows[1:] if r[0] == "trade_pair"]
    assert any("arch x struct" in r[1] for r in pair_rows)
    assert any("cost_impact=" in r[3] for r in pair_rows)


@pytest.mark.asyncio
async def test_export_snapshot_csv_empty_project_still_valid(
    session: AsyncSession,
) -> None:
    """A project with no clashes exports a parseable file with the KPI and
    alert blocks (alerts always seed the four known metrics) and no
    trade-pair rows."""
    project_id = session.info["project_id"]
    svc = CoordinationHubService(session)
    csv_text = await svc.export_snapshot_csv(project_id, currency="EUR")
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0][0] == "section"
    sections = {r[0] for r in rows[1:]}
    assert "kpi" in sections
    assert "alert" in sections
    assert "trade_pair" not in sections
    kpi = {r[1]: r[2] for r in rows[1:] if r[0] == "kpi"}
    assert kpi["open_clashes"] == "0"


@pytest.mark.asyncio
async def test_export_snapshot_csv_bypasses_dashboard_cache(
    session: AsyncSession,
) -> None:
    """Export must reflect a clash added AFTER a cached dashboard read."""
    project_id = session.info["project_id"]
    svc = CoordinationHubService(session)
    # Warm the 30s cache with an empty read.
    first = await svc.dashboard(project_id, currency="EUR")
    assert first.clashes.open_count == 0

    # Add a clash; the cache still holds the stale zero.
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    session.add(_make_result(run, a_disc="arch", b_disc="struct"))
    await session.commit()

    cached = await svc.dashboard(project_id, currency="EUR")
    assert cached.clashes.open_count == 0  # proves the cache is stale

    csv_text = await svc.export_snapshot_csv(project_id, currency="EUR")
    kpi = {r[1]: r[2] for r in csv.reader(io.StringIO(csv_text)) if r and r[0] == "kpi"}
    # The export bypassed the cache and saw the live count.
    assert kpi["open_clashes"] == "1"
