# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service tests for PROJECT-scoped "escalate stored rates" preview.

The catalogue-scoped path (region / category / explicit ids) is covered by
``test_price_index_escalation.py``. These add the project scope: given a project
whose BOQ positions link to a known set of cost items via
``metadata.cost_item_id``, ``escalate_stored_rates(project_id=...)`` must
escalate exactly those items (and flag the null-``price_as_of`` ones), ignoring
cost items the project never references. The documented region fallback and the
untouched catalogue path are exercised too.

They build a project -> BOQ -> positions graph directly on a transaction-
isolated PostgreSQL session with ``disable_fks=True`` (so a bare ``owner_id``
needs no real user row), the same harness style the other unit suites use.
Escalation is read-only, so nothing is written back.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.costs.models import CostItem
from app.modules.price_index.models import CostIndexPoint, CostIndexSeries
from app.modules.price_index.schemas import EscalatePreviewRequest
from app.modules.price_index.service import PriceIndexService, ProjectNotFoundError
from app.modules.projects.models import Project
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session with FK triggers off (bare owner_id is fine)."""
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _make_series(session: AsyncSession, name: str = "Test Index") -> CostIndexSeries:
    """A small rising index: 2019-01 -> 1.0, 2023-01 -> 1.24, 2026-01 -> 1.4."""
    series = CostIndexSeries(name=name, description="")
    session.add(series)
    await session.flush()
    for period, factor in (("2019-01", "1.000000"), ("2023-01", "1.240000"), ("2026-01", "1.400000")):
        session.add(CostIndexPoint(series_id=series.id, period=period, factor=D(factor)))
    await session.flush()
    return series


async def _make_item(
    session: AsyncSession,
    *,
    code: str,
    rate: str,
    price_as_of: date | None,
    region: str | None = None,
    classification: dict | None = None,
    is_active: bool = True,
) -> CostItem:
    item = CostItem(
        code=code,
        description=f"Item {code}",
        unit="m3",
        rate=rate,
        currency="EUR",
        region=region,
        price_as_of=price_as_of,
        classification=classification or {},
        is_active=is_active,
    )
    session.add(item)
    await session.flush()
    return item


async def _make_project(session: AsyncSession, *, name: str = "Tower A", region: str = "DACH") -> Project:
    project = Project(name=name, region=region, owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    return project


async def _make_boq(session: AsyncSession, project: Project) -> BOQ:
    boq = BOQ(project_id=project.id, name="Estimate")
    session.add(boq)
    await session.flush()
    return boq


async def _add_position(
    session: AsyncSession,
    boq: BOQ,
    *,
    ordinal: str,
    cost_item_id: uuid.UUID | str | None,
) -> Position:
    """Add a position, linking it to a cost item via metadata.cost_item_id."""
    metadata: dict = {}
    if cost_item_id is not None:
        metadata["cost_item_id"] = str(cost_item_id)
    pos = Position(
        boq_id=boq.id,
        ordinal=ordinal,
        description=f"Position {ordinal}",
        unit="m3",
        quantity="10",
        unit_rate="100",
        total="1000",
        metadata_=metadata,
    )
    session.add(pos)
    await session.flush()
    return pos


async def test_project_scope_escalates_only_referenced_items(session: AsyncSession) -> None:
    """Only the cost items the project's BOQ links to are escalated.

    A/B/C are referenced (C has no price date -> flagged); D is a catalogue item
    the project never references and must be absent; a manual position with no
    link contributes nothing. The same item referenced twice appears once.
    """
    series = await _make_series(session)
    a = await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10))
    b = await _make_item(session, code="B", rate="80.00", price_as_of=date(2023, 1, 5))
    c = await _make_item(session, code="C", rate="50.00", price_as_of=None)
    d = await _make_item(session, code="D", rate="70.00", price_as_of=date(2019, 1, 1))

    project = await _make_project(session, name="Tower A")
    boq = await _make_boq(session, project)
    await _add_position(session, boq, ordinal="0001", cost_item_id=a.id)
    await _add_position(session, boq, ordinal="0002", cost_item_id=b.id)
    await _add_position(session, boq, ordinal="0003", cost_item_id=c.id)
    await _add_position(session, boq, ordinal="0004", cost_item_id=a.id)  # duplicate link
    await _add_position(session, boq, ordinal="0005", cost_item_id=None)  # manual, no link

    service = PriceIndexService(session)
    response = await service.escalate_stored_rates(
        EscalatePreviewRequest(target_date=date(2026, 1, 15), series_id=series.id, project_id=project.id)
    )

    assert response.scope == "project"
    assert response.project_id == project.id
    assert response.project_name == "Tower A"
    assert response.project_fallback is False
    assert response.target_period == "2026-01"

    codes = {line.code for line in response.results}
    assert codes == {"A", "B", "C"}  # D never referenced; duplicate A collapsed
    assert d.id not in {line.cost_item_id for line in response.results}
    assert response.item_count == 3
    assert response.escalatable_count == 2

    lines = {line.code: line for line in response.results}
    # A: 2019-01 (1.0) -> 2026-01 (1.4) => 100.00 * 1.4 = 140.00
    assert lines["A"].escalatable is True
    assert lines["A"].factor == D("1.400000")
    assert lines["A"].escalated_rate == D("140.00")
    # B: 2023-01 (1.24) -> 2026-01 (1.4) => 80 * (1.4/1.24) = 90.32
    assert lines["B"].escalatable is True
    assert lines["B"].escalated_rate == D("90.32")
    # C: no price_as_of -> flagged, nothing computed
    assert lines["C"].escalatable is False
    assert lines["C"].escalated_rate is None
    assert lines["C"].note is not None and "price_as_of" in lines["C"].note


async def test_project_scope_serialises_decimals_as_strings(session: AsyncSession) -> None:
    """The project-scoped response keeps money / factors as plain strings."""
    series = await _make_series(session)
    a = await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10))
    project = await _make_project(session)
    boq = await _make_boq(session, project)
    await _add_position(session, boq, ordinal="0001", cost_item_id=a.id)

    service = PriceIndexService(session)
    response = await service.escalate_stored_rates(
        EscalatePreviewRequest(target_date=date(2026, 1, 15), series_id=series.id, project_id=project.id)
    )
    dumped = response.model_dump(mode="json")
    assert dumped["scope"] == "project"
    assert dumped["project_id"] == str(project.id)
    line = dumped["results"][0]
    assert line["escalated_rate"] == "140.00"
    assert isinstance(line["escalated_rate"], str)


async def test_project_scope_narrows_by_region(session: AsyncSession) -> None:
    """A region filter narrows the project's referenced set further (AND)."""
    series = await _make_series(session)
    berlin = await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10), region="DE_BERLIN")
    munich = await _make_item(session, code="B", rate="100.00", price_as_of=date(2019, 1, 10), region="DE_MUNICH")

    project = await _make_project(session)
    boq = await _make_boq(session, project)
    await _add_position(session, boq, ordinal="0001", cost_item_id=berlin.id)
    await _add_position(session, boq, ordinal="0002", cost_item_id=munich.id)

    service = PriceIndexService(session)
    response = await service.escalate_stored_rates(
        EscalatePreviewRequest(
            target_date=date(2026, 1, 15),
            series_id=series.id,
            project_id=project.id,
            region="DE_BERLIN",
        )
    )
    assert response.project_fallback is False
    assert response.item_count == 1
    assert response.results[0].cost_item_id == berlin.id


async def test_project_scope_falls_back_to_region_when_no_links(session: AsyncSession) -> None:
    """A project whose positions carry no typed link uses its region as proxy.

    With no ``metadata.cost_item_id`` on any position there is nothing to
    escalate exactly, so the project's own region selects the active catalogue
    rows in that region and the response flags ``project_fallback``.
    """
    series = await _make_series(session)
    in_region = await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 1), region="DE_BERLIN")
    await _make_item(session, code="B", rate="100.00", price_as_of=date(2019, 1, 1), region="DE_MUNICH")

    project = await _make_project(session, region="DE_BERLIN")
    boq = await _make_boq(session, project)
    await _add_position(session, boq, ordinal="0001", cost_item_id=None)
    await _add_position(session, boq, ordinal="0002", cost_item_id=None)

    service = PriceIndexService(session)
    response = await service.escalate_stored_rates(
        EscalatePreviewRequest(target_date=date(2026, 1, 15), series_id=series.id, project_id=project.id)
    )
    assert response.scope == "project"
    assert response.project_fallback is True
    assert response.item_count == 1
    assert response.results[0].cost_item_id == in_region.id
    assert response.results[0].escalated_rate == D("140.00")


async def test_unknown_project_raises(session: AsyncSession) -> None:
    """A project id that does not exist is a not-found error, not a silent scan."""
    series = await _make_series(session)
    await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10), region="DE_BERLIN")

    service = PriceIndexService(session)
    with pytest.raises(ProjectNotFoundError):
        await service.escalate_stored_rates(
            EscalatePreviewRequest(target_date=date(2026, 1, 15), series_id=series.id, project_id=uuid.uuid4())
        )


async def test_catalogue_scope_unchanged_without_project(session: AsyncSession) -> None:
    """Without project_id the selection stays catalogue-scoped and untouched.

    A project with a linked position exists but must not influence a region /
    category catalogue request; the response carries the catalogue defaults.
    """
    series = await _make_series(session)
    berlin = await _make_item(
        session,
        code="A",
        rate="200.00",
        price_as_of=date(2019, 1, 1),
        region="DE_BERLIN",
        classification={"collection": "Concrete"},
    )
    # A different-region item the region filter must exclude.
    await _make_item(session, code="B", rate="200.00", price_as_of=date(2019, 1, 1), region="DE_MUNICH")

    project = await _make_project(session)
    boq = await _make_boq(session, project)
    await _add_position(session, boq, ordinal="0001", cost_item_id=berlin.id)

    service = PriceIndexService(session)
    response = await service.escalate_stored_rates(
        EscalatePreviewRequest(target_date=date(2026, 1, 15), series_id=series.id, region="DE_BERLIN")
    )
    assert response.scope == "catalogue"
    assert response.project_id is None
    assert response.project_name is None
    assert response.project_fallback is False
    assert response.item_count == 1
    assert response.results[0].cost_item_id == berlin.id
    assert response.results[0].escalated_rate == D("280.00")  # 200 * 1.4
