"""Finding #8 — ``compute_boq_totals`` batches its per-BOQ loads.

GET /boqs/ (paginated up to 100) calls ``compute_boq_totals(boq_ids)`` for
the whole page. The original implementation looped per BOQ and, per
iteration, awaited ``_resolve_project_fx(boq_id)`` (an identical
``Project JOIN BOQ`` query - every BOQ on a page shares ONE project) and
``position_repo.list_all_for_boq(boq_id)`` (an unbounded full position load
per BOQ). That is ~2xN round trips plus an N-way full-table position read on
a hot path.

The fix keeps the currency-aware money math identical (Issue #111) but:

* resolves the project FX table ONCE per distinct project via
  ``_resolve_project_fx_by_project``,
* loads every position for the whole set in a single ``boq_id IN (...)``
  query (``list_all_for_boqs``) grouped in Python.

These tests pin BOTH the unchanged result (a 2-BOQ project's list totals
equal the per-BOQ computation and the FX conversion still applies) AND the
batching itself (FX resolved once per project, positions loaded in one
batched call) - the batching assertions FAIL on the original per-BOQ loop.

Test isolation: a transaction-isolated PostgreSQL session on the shared
schema-loaded ``oe_test_unit`` database (rolled back on teardown), never
the production database.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_compute_totals_batched.py -v --tb=short
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.service import BOQService
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


async def _make_two_boq_project(session: AsyncSession):
    """Seed one EUR project with two BOQs.

    * BOQ-1 mixes a base-EUR leaf with a USD leaf (USD priced via
      ``metadata.currency``, rate 1.10) and carries a 10% overhead markup.
    * BOQ-2 holds a single plain-EUR leaf, no markup.

    Returns ``(boq1_id, boq2_id)``.
    """
    from app.modules.boq.models import BOQ, BOQMarkup, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name="Two BOQ",
            owner_id=OWNER_ID,
            currency="EUR",
            fx_rates=[{"code": "USD", "rate": "1.10", "label": "US Dollar"}],
        )
    )
    await session.flush()

    boq1 = BOQ(id=uuid.uuid4(), project_id=project_id, name="BOQ One")
    boq2 = BOQ(id=uuid.uuid4(), project_id=project_id, name="BOQ Two")
    session.add_all([boq1, boq2])
    await session.flush()

    # BOQ-1: section header (excluded from money) + EUR leaf + USD leaf.
    section = Position(
        id=uuid.uuid4(),
        boq_id=boq1.id,
        ordinal="01",
        description="Section A",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq1.id,
            parent_id=section.id,
            ordinal="01.001",
            description="EUR work",
            unit="m2",
            quantity="100",
            unit_rate="10",
            total="1000",
            sort_order=1,
        )
    )
    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq1.id,
            parent_id=section.id,
            ordinal="01.002",
            description="USD work",
            unit="m2",
            quantity="50",
            unit_rate="10",
            total="500",
            metadata_={"currency": "USD"},
            sort_order=2,
        )
    )
    # 10% overhead on the (FX-converted) direct cost.
    session.add(
        BOQMarkup(
            id=uuid.uuid4(),
            boq_id=boq1.id,
            name="Overhead",
            markup_type="percentage",
            percentage="10",
            apply_to="direct_cost",
            sort_order=0,
            is_active=True,
        )
    )

    # BOQ-2: single plain-EUR leaf, no markup.
    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq2.id,
            ordinal="01",
            description="EUR only",
            unit="m3",
            quantity="20",
            unit_rate="25",
            total="500",
            sort_order=0,
        )
    )
    await session.commit()
    return boq1.id, boq2.id


@pytest.mark.asyncio
async def test_two_boq_totals_are_fx_correct(session):
    """List totals for a 2-BOQ project match the per-BOQ FX-aware figures."""
    boq1_id, boq2_id = await _make_two_boq_project(session)
    service = BOQService(session)

    totals = await service.compute_boq_totals([boq1_id, boq2_id])

    # BOQ-1: 1000 EUR + (500 USD x 1.10) = 1550 direct, +10% = 1705 grand.
    assert totals[boq1_id]["direct_cost"] == pytest.approx(1550.0)
    assert totals[boq1_id]["markups_total"] == pytest.approx(155.0)
    assert totals[boq1_id]["grand_total"] == pytest.approx(1705.0)
    assert totals[boq1_id]["base_currency"] == "EUR"
    assert totals[boq1_id]["is_mixed_currency"] is True

    # BOQ-2: plain 500 EUR, no markup, single currency.
    assert totals[boq2_id]["direct_cost"] == pytest.approx(500.0)
    assert totals[boq2_id]["markups_total"] == pytest.approx(0.0)
    assert totals[boq2_id]["grand_total"] == pytest.approx(500.0)
    assert totals[boq2_id]["is_mixed_currency"] is False


@pytest.mark.asyncio
async def test_batched_matches_per_boq(session):
    """The 2-BOQ batched result equals computing each BOQ on its own.

    The list path and the single-BOQ detail path (which calls
    ``compute_boq_totals([boq_id])``) must report identical figures.
    """
    boq1_id, boq2_id = await _make_two_boq_project(session)
    service = BOQService(session)

    batched = await service.compute_boq_totals([boq1_id, boq2_id])
    single1 = await service.compute_boq_totals([boq1_id])
    single2 = await service.compute_boq_totals([boq2_id])

    assert batched[boq1_id] == single1[boq1_id]
    assert batched[boq2_id] == single2[boq2_id]


@pytest.mark.asyncio
async def test_fx_resolved_once_and_positions_batched(session, monkeypatch):
    """Finding #8 regression: no per-BOQ FX query, no per-BOQ position load.

    Counts the data-access calls compute_boq_totals makes. The fixed code
    resolves FX ONCE per distinct project (one ``_resolve_project_fx_by_project``
    for the single shared project) and loads positions in ONE batched
    ``list_all_for_boqs`` call. The original per-BOQ loop instead called the
    per-BOQ ``_resolve_project_fx`` and ``list_all_for_boq`` once each PER BOQ
    and never touched the batched helpers - so these assertions fail on it.
    """
    boq1_id, boq2_id = await _make_two_boq_project(session)
    service = BOQService(session)

    calls = {
        "fx_by_project": 0,
        "fx_by_boq": 0,
        "positions_batched": 0,
        "positions_per_boq": 0,
    }

    orig_fx_by_project = service._resolve_project_fx_by_project
    orig_fx_by_boq = service._resolve_project_fx
    orig_pos_batched = service.position_repo.list_all_for_boqs
    orig_pos_per_boq = service.position_repo.list_all_for_boq

    async def spy_fx_by_project(project_id):
        calls["fx_by_project"] += 1
        return await orig_fx_by_project(project_id)

    async def spy_fx_by_boq(boq_id):
        calls["fx_by_boq"] += 1
        return await orig_fx_by_boq(boq_id)

    async def spy_pos_batched(boq_ids):
        calls["positions_batched"] += 1
        return await orig_pos_batched(boq_ids)

    async def spy_pos_per_boq(boq_id):
        calls["positions_per_boq"] += 1
        return await orig_pos_per_boq(boq_id)

    monkeypatch.setattr(service, "_resolve_project_fx_by_project", spy_fx_by_project)
    monkeypatch.setattr(service, "_resolve_project_fx", spy_fx_by_boq)
    monkeypatch.setattr(service.position_repo, "list_all_for_boqs", spy_pos_batched)
    monkeypatch.setattr(service.position_repo, "list_all_for_boq", spy_pos_per_boq)

    await service.compute_boq_totals([boq1_id, boq2_id])

    # FX resolved exactly once for the single shared project (not per BOQ).
    assert calls["fx_by_project"] == 1
    assert calls["fx_by_boq"] == 0
    # Positions loaded in a single batched query (not one full load per BOQ).
    assert calls["positions_batched"] == 1
    assert calls["positions_per_boq"] == 0
