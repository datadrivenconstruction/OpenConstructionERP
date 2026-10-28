"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service-level tests for the conceptual-vs-detailed reconciliation.

Exercise :meth:`RomEstimateService.reconcile_with_boq` end to end on a
transaction-isolated PostgreSQL session: a saved conceptual (ROM) baseline
against a live detailed BOQ, plus the graceful-degradation paths (no saved
baseline, no BOQ). The pure variance / status maths is pinned separately in
``test_rom_estimate_service.py``; these tests pin the database wiring - that the
most-recent baseline is read, that the detailed total reuses the BOQ FX-aware
rollup, and that the currency and BOQ count come through.

Test isolation: a transaction-isolated PostgreSQL session on the shared
schema-loaded unit-test database (rolled back on teardown), never production.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rom_estimate.models import RomEstimate
from app.modules.rom_estimate.schemas import RomCreateBoqRequest
from app.modules.rom_estimate.service import (
    STATUS_NO_BASELINE,
    STATUS_ON_TRACK,
    STATUS_OVER,
    STATUS_UNDER,
    RomEstimateService,
)
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"o-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            )
        )
        await s.flush()
        await s.commit()
        yield s


async def _make_project(session: AsyncSession, currency: str = "EUR") -> uuid.UUID:
    """Seed one project with a base currency and return its id."""
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(Project(id=project_id, name="Recon", owner_id=OWNER_ID, currency=currency))
    await session.flush()
    return project_id


async def _add_boq_with_total(session: AsyncSession, project_id: uuid.UUID, total: str) -> None:
    """Add a BOQ carrying a single base-currency leaf whose total is ``total``."""
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="BOQ")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq.id,
            ordinal="01",
            description="Work",
            unit="m2",
            quantity="1",
            unit_rate=total,
            total=total,
            sort_order=0,
        )
    )
    await session.flush()


async def _add_concept(
    session: AsyncSession,
    project_id: uuid.UUID,
    total: str,
    currency: str = "EUR",
) -> uuid.UUID:
    """Save a conceptual (ROM) baseline row with a known total and return its id."""
    row = RomEstimate(
        project_id=project_id,
        name="Concept",
        building_type="office",
        quality="standard",
        region="global",
        currency=currency,
        gross_floor_area="1000",
        gfa_unit="m2",
        cost_per_m2="0",
        total_cost=total,
    )
    session.add(row)
    await session.flush()
    return row.id


@pytest.mark.asyncio
async def test_reconcile_over_when_detailed_exceeds_saved_concept(session: AsyncSession) -> None:
    """A detailed BOQ above the saved concept reconciles to the 'over' band."""
    project_id = await _make_project(session)
    await _add_concept(session, project_id, total="800", currency="EUR")
    await _add_boq_with_total(session, project_id, total="1000")
    await session.commit()

    rec = await RomEstimateService(session).reconcile_with_boq(project_id)

    assert rec.conceptual_total == Decimal("800")
    assert rec.detailed_total == Decimal("1000")
    assert rec.variance_amount == Decimal("200")
    assert rec.variance_pct == Decimal("25.00")
    assert rec.status == STATUS_OVER
    assert rec.currency == "EUR"
    assert rec.boq_count == 1


@pytest.mark.asyncio
async def test_reconcile_reads_the_most_recent_baseline(session: AsyncSession) -> None:
    """When several concepts are saved, the newest is the one reconciled against."""
    project_id = await _make_project(session)
    await _add_concept(session, project_id, total="500", currency="EUR")
    await _add_concept(session, project_id, total="900", currency="EUR")  # newest
    await _add_boq_with_total(session, project_id, total="950")
    await session.commit()

    rec = await RomEstimateService(session).reconcile_with_boq(project_id)

    assert rec.conceptual_total == Decimal("900")
    assert rec.variance_amount == Decimal("50")


@pytest.mark.asyncio
async def test_reconcile_no_baseline_when_no_saved_concept(session: AsyncSession) -> None:
    """A project with a BOQ but no saved concept degrades to no_baseline."""
    project_id = await _make_project(session)
    await _add_boq_with_total(session, project_id, total="1000")
    await session.commit()

    rec = await RomEstimateService(session).reconcile_with_boq(project_id)

    assert rec.status == STATUS_NO_BASELINE
    assert rec.conceptual_total is None
    assert rec.variance_amount is None
    assert rec.detailed_total == Decimal("1000")
    assert rec.boq_count == 1


@pytest.mark.asyncio
async def test_reconcile_detailed_zero_when_no_boq(session: AsyncSession) -> None:
    """A saved concept with no BOQ yet reads as a detailed total of 0 (fully under)."""
    project_id = await _make_project(session)
    await _add_concept(session, project_id, total="800", currency="EUR")
    await session.commit()

    rec = await RomEstimateService(session).reconcile_with_boq(project_id)

    assert rec.detailed_total == Decimal("0")
    assert rec.variance_amount == Decimal("-800")
    assert rec.variance_pct == Decimal("-100.00")
    assert rec.status == STATUS_UNDER
    assert rec.boq_count == 0


# ── Handoff: create_boq_from_rom ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_boq_from_rom_seeds_baseline_and_provisional_boq(session: AsyncSession) -> None:
    """The handoff saves the baseline and seeds a six-section provisional BOQ."""
    from app.modules.boq.repository import BOQRepository, PositionRepository

    project_id = await _make_project(session, currency="EUR")
    request = RomCreateBoqRequest(
        building_type="office",
        gross_floor_area=Decimal("1000"),
        quality="standard",
        region="north_america",
        currency="EUR",
        boq_name="Concept BOQ",
    )

    resp = await RomEstimateService(session).create_boq_from_rom(project_id, request, OWNER_ID)
    await session.commit()

    assert resp.sections_created == 6
    assert resp.positions_created == 6
    assert resp.estimate_id  # the conceptual baseline was persisted

    # The BOQ exists in the project and is stamped with the concept baseline.
    boq = await BOQRepository(session).get_by_id(uuid.UUID(resp.boq_id))
    assert boq is not None
    assert boq.project_id == project_id
    assert boq.metadata_["source"] == "rom_estimate"
    assert boq.metadata_["rom_estimate_id"] == resp.estimate_id

    # Six section headers (no money) + six concept-rate leaves nested under them.
    positions = await PositionRepository(session).list_all_for_boq(boq.id)
    sections = [p for p in positions if p.unit == "section"]
    leaves = [p for p in positions if p.unit != "section"]
    assert len(sections) == 6
    assert len(leaves) == 6
    section_ids = {s.id for s in sections}
    assert all(leaf.parent_id in section_ids for leaf in leaves)
    assert all(Decimal(s.total) == Decimal("0") for s in sections)
    assert all(Decimal(leaf.quantity) == Decimal("1000") for leaf in leaves)
    assert all(leaf.source == "rom_estimate" for leaf in leaves)

    # The seeded leaf totals reproduce the saved concept total exactly (Decimal).
    baseline = await RomEstimateService(session).latest_estimate(project_id)
    assert baseline is not None
    assert sum(Decimal(leaf.total) for leaf in leaves) == Decimal(baseline.total_cost)
    assert Decimal(baseline.total_cost) > 0


@pytest.mark.asyncio
async def test_create_boq_from_rom_makes_the_reconciliation_live(session: AsyncSession) -> None:
    """After the handoff the concept-vs-detailed reconciliation is on track (not dead)."""
    project_id = await _make_project(session, currency="EUR")
    request = RomCreateBoqRequest(
        building_type="warehouse",
        gross_floor_area=Decimal("2500"),
        quality="standard",
        region="global",
        currency="EUR",
        boq_name="Shed",
    )
    await RomEstimateService(session).create_boq_from_rom(project_id, request, OWNER_ID)
    await session.commit()

    rec = await RomEstimateService(session).reconcile_with_boq(project_id)

    # The seeded BOQ total equals the concept, so the design is on track - the
    # previously dead reconciliation panel now has a live baseline.
    assert rec.status == STATUS_ON_TRACK
    assert rec.conceptual_total is not None
    assert rec.variance_amount == Decimal("0")
    assert rec.boq_count == 1
