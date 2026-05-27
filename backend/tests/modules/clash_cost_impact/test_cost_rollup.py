"""Unit tests for the clash → BOQ cost-impact service.

The service is a pure read-projection — no clash module mutation, no
BOQ module mutation. The tests therefore build a tiny in-memory SQLite
fixture per test that materialises just enough of the upstream models'
shape (project + BOQ + position + clash run + clash result) to drive
the computation, then assert on the rounded wire-shape payload.

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is overridden by the
session-scoped ``tests/conftest.py`` before any ``from app.…`` import
runs, so this file may import the production models freely.

Test matrix (≥ 12, per the brief):
    * single clash, one affected BOQ position
    * single clash, no affected BOQ positions (labour-only)
    * single clash, no element GUIDs (low confidence)
    * two clashes share a position — each counts it (no shared-pool dedup)
    * trade-pair labour-hours lookup (symmetric)
    * unknown discipline pair falls back to the default hours
    * currency comes from the project record
    * project rollup sums across many clashes
    * project rollup excludes closed / ignored clashes
    * rework factor configurable per project (decimal or percent both work)
    * blended rate configurable per project
    * Decimal precision: wire-shape rounded to 2 dp, internal full precision
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.database import Base, async_session_factory, engine
from app.modules.boq.models import BOQ, Position
from app.modules.clash.models import ClashResult, ClashRun
from app.modules.clash_cost_impact.service import (
    DEFAULT_BLENDED_RATE,
    DEFAULT_REWORK_FACTOR,
    DEFAULT_TRADE_PAIR_HOURS,
    TRADE_PAIR_HOURS,
    ClashCostImpactService,
    trade_pair_hours,
)
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest_asyncio.fixture
async def db_session():
    """Per-test SQLite session with the tables freshly created.

    Each test gets a clean slate so cross-test bleed-through (e.g. one
    test's "closed" clash polluting another's open-rollup) is impossible.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        yield session


async def _make_user(session) -> User:
    user = User(
        email=f"qs-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Quantity Surveyor",
        role="manager",
        is_active=True,
        locale="en",
    )
    session.add(user)
    await session.flush()
    return user


async def _make_project(
    session,
    *,
    owner: User,
    currency: str = "EUR",
    metadata: dict | None = None,
) -> Project:
    project = Project(
        name=f"Clash-Cost Test {uuid.uuid4().hex[:6]}",
        description="cost impact fixture",
        currency=currency,
        owner_id=owner.id,
        metadata_=metadata or {},
    )
    session.add(project)
    await session.flush()
    return project


async def _make_boq_with_position(
    session,
    project: Project,
    *,
    cad_element_ids: list[str],
    quantity: str = "10",
    unit_rate: str = "100",
    total: str | None = None,
    ordinal: str = "01.01.001",
    description: str = "Test position",
) -> Position:
    boq = BOQ(project_id=project.id, name="Test BOQ", description="")
    session.add(boq)
    await session.flush()
    pos = Position(
        boq_id=boq.id,
        ordinal=ordinal,
        description=description,
        unit="m3",
        quantity=quantity,
        unit_rate=unit_rate,
        total=total if total is not None else str(Decimal(quantity) * Decimal(unit_rate)),
        cad_element_ids=cad_element_ids,
    )
    session.add(pos)
    await session.flush()
    return pos


async def _make_run(session, project: Project, *, model_ids: list[uuid.UUID] | None = None) -> ClashRun:
    run = ClashRun(
        project_id=project.id,
        name="Test Run",
        model_ids=[str(m) for m in (model_ids or [uuid.uuid4()])],
        status="completed",
        created_by=str(project.owner_id),
    )
    session.add(run)
    await session.flush()
    return run


async def _make_clash(
    session,
    run: ClashRun,
    *,
    a_stable_id: str = "",
    b_stable_id: str = "",
    a_discipline: str = "Structural",
    b_discipline: str = "Mechanical",
    status_: str = "new",
) -> ClashResult:
    clash = ClashResult(
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id=a_stable_id,
        b_stable_id=b_stable_id,
        a_name=f"Element A {a_stable_id}",
        b_name=f"Element B {b_stable_id}",
        a_discipline=a_discipline,
        b_discipline=b_discipline,
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
    session.add(clash)
    await session.flush()
    return clash


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_clash_with_one_affected_position(db_session):
    """An overlap on ``a_stable_id`` triggers the rework leg + high confidence."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    pos = await _make_boq_with_position(
        db_session,
        project,
        cad_element_ids=["GUID-A"],
        quantity="10",
        unit_rate="500",
    )
    run = await _make_run(db_session, project)
    clash = await _make_clash(
        db_session,
        run,
        a_stable_id="GUID-A",
        b_stable_id="GUID-OTHER",
        a_discipline="Structural",
        b_discipline="Mechanical",
    )

    service = ClashCostImpactService(db_session)
    payload, project_id = await service.impact_for_clash(clash.id)
    assert payload is not None
    assert project_id == project.id

    # position.total = 5000 → rework_subtotal = 500.00
    assert payload["components"]["rework_positions_total"] == 5000.00
    assert payload["components"]["rework_subtotal"] == 500.00
    # Struct ↔ Mech = 8 h × 50 EUR = 400.00
    assert payload["components"]["labour_hours"] == 8.0
    assert payload["components"]["labour_subtotal"] == 400.00
    assert payload["total_estimate"] == 900.00
    assert payload["confidence"] == "high"
    assert len(payload["affected_positions"]) == 1
    assert str(payload["affected_positions"][0]["position_id"]) == str(pos.id)


@pytest.mark.asyncio
async def test_single_clash_no_affected_positions_medium_confidence(db_session):
    """No BOQ overlap → labour-only impact, medium confidence."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    # BOQ position whose GUIDs do NOT overlap the clash.
    await _make_boq_with_position(db_session, project, cad_element_ids=["UNRELATED-1"])
    run = await _make_run(db_session, project)
    clash = await _make_clash(
        db_session,
        run,
        a_stable_id="GUID-A",
        b_stable_id="GUID-B",
        a_discipline="Structural",
        b_discipline="Mechanical",
    )

    service = ClashCostImpactService(db_session)
    payload, _ = await service.impact_for_clash(clash.id)
    assert payload is not None
    assert payload["components"]["rework_positions_total"] == 0.0
    assert payload["components"]["rework_subtotal"] == 0.0
    assert payload["components"]["labour_subtotal"] == 400.00
    assert payload["total_estimate"] == 400.00
    assert payload["confidence"] == "medium"
    assert payload["affected_positions"] == []


@pytest.mark.asyncio
async def test_single_clash_no_element_guids_low_confidence(db_session):
    """No stable ids at all → zero impact + low confidence."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    run = await _make_run(db_session, project)
    clash = await _make_clash(
        db_session,
        run,
        a_stable_id="",
        b_stable_id="",
        a_discipline="Structural",
        b_discipline="Mechanical",
    )

    service = ClashCostImpactService(db_session)
    payload, _ = await service.impact_for_clash(clash.id)
    assert payload is not None
    assert payload["total_estimate"] == 0.0
    assert payload["components"]["labour_subtotal"] == 0.0
    assert payload["confidence"] == "low"


@pytest.mark.asyncio
async def test_two_clashes_share_a_position_no_dedup(db_session):
    """A position linked to two clashes contributes to BOTH rollups (no dedup)."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    await _make_boq_with_position(
        db_session,
        project,
        cad_element_ids=["GUID-SHARED"],
        quantity="10",
        unit_rate="500",
    )
    run = await _make_run(db_session, project)
    clash_1 = await _make_clash(
        db_session,
        run,
        a_stable_id="GUID-SHARED",
        b_stable_id="GUID-OTHER-1",
    )
    clash_2 = await _make_clash(
        db_session,
        run,
        a_stable_id="GUID-SHARED",
        b_stable_id="GUID-OTHER-2",
    )

    service = ClashCostImpactService(db_session)
    payload_1, _ = await service.impact_for_clash(clash_1.id)
    payload_2, _ = await service.impact_for_clash(clash_2.id)
    assert payload_1["components"]["rework_subtotal"] == 500.00
    assert payload_2["components"]["rework_subtotal"] == 500.00


@pytest.mark.asyncio
async def test_trade_pair_labour_hours_lookup_symmetric():
    """``trade_pair_hours`` is symmetric on the pair + falls back on unknown."""
    assert trade_pair_hours("Structural", "Mechanical") == 8
    assert trade_pair_hours("Mechanical", "Structural") == 8
    assert trade_pair_hours("arch", "Plumbing") == 4
    # Unknown discipline → default fallback (no KeyError).
    assert trade_pair_hours("Unknown", "Unmapped") == DEFAULT_TRADE_PAIR_HOURS
    # Table sanity — the documented constants are present.
    assert TRADE_PAIR_HOURS[("mechanical", "structural")] == 8


@pytest.mark.asyncio
async def test_currency_comes_from_project(db_session):
    """The wire ``currency`` field mirrors the project record verbatim."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user, currency="USD")
    run = await _make_run(db_session, project)
    clash = await _make_clash(db_session, run, a_stable_id="X", b_stable_id="Y")
    service = ClashCostImpactService(db_session)
    payload, _ = await service.impact_for_clash(clash.id)
    assert payload["currency"] == "USD"


@pytest.mark.asyncio
async def test_project_rollup_sums_across_many_clashes(db_session):
    """Rollup ``total_open_impact`` equals the sum of every clash's total."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    await _make_boq_with_position(
        db_session,
        project,
        cad_element_ids=["A1"],
        quantity="5",
        unit_rate="200",
    )
    await _make_boq_with_position(
        db_session,
        project,
        cad_element_ids=["B1"],
        quantity="2",
        unit_rate="1000",
    )
    run = await _make_run(db_session, project)
    # Two clashes, two different pairs → two trade-pair rollup buckets.
    await _make_clash(
        db_session,
        run,
        a_stable_id="A1",
        b_stable_id="A2",
        a_discipline="Structural",
        b_discipline="Mechanical",
    )
    await _make_clash(
        db_session,
        run,
        a_stable_id="B1",
        b_stable_id="B2",
        a_discipline="Architectural",
        b_discipline="Electrical",
    )

    service = ClashCostImpactService(db_session)
    rollup = await service.rollup_for_project(project.id)
    assert rollup is not None
    assert rollup["clash_count"] == 2
    # Clash 1 = 1000*0.10 + 8*50 = 500. Clash 2 = 2000*0.10 + 4*50 = 400.
    assert rollup["total_open_impact"] == 900.00
    pairs = {tuple(p["pair"]): p for p in rollup["by_trade_pair"]}
    assert pairs[("mechanical", "structural")]["total"] == 500.00
    assert pairs[("architectural", "electrical")]["total"] == 400.00


@pytest.mark.asyncio
async def test_project_rollup_excludes_closed_clashes(db_session):
    """Resolved / ignored clashes never carry rework risk → out of the rollup."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    run = await _make_run(db_session, project)

    # One open + one resolved + one ignored.
    await _make_clash(db_session, run, a_stable_id="A", b_stable_id="B", status_="new")
    await _make_clash(db_session, run, a_stable_id="C", b_stable_id="D", status_="resolved")
    await _make_clash(db_session, run, a_stable_id="E", b_stable_id="F", status_="ignored")

    service = ClashCostImpactService(db_session)
    rollup = await service.rollup_for_project(project.id, status_filter="open")
    assert rollup is not None
    # Only the open clash counts.
    assert rollup["clash_count"] == 1
    assert rollup["total_open_impact"] == 400.00

    # With ``all`` every status counts (3 clashes × 400 = 1200).
    rollup_all = await service.rollup_for_project(project.id, status_filter="all")
    assert rollup_all["clash_count"] == 3
    assert rollup_all["total_open_impact"] == 1200.00


@pytest.mark.asyncio
async def test_rework_factor_configurable_per_project(db_session):
    """Override the rework factor via ``Project.metadata_``."""
    user = await _make_user(db_session)
    # 25 % rework instead of the 10 % default — accepted as percent.
    project = await _make_project(
        db_session,
        owner=user,
        metadata={"clash_cost_impact": {"rework_factor": 25}},
    )
    await _make_boq_with_position(
        db_session,
        project,
        cad_element_ids=["X"],
        quantity="10",
        unit_rate="100",
    )
    run = await _make_run(db_session, project)
    clash = await _make_clash(db_session, run, a_stable_id="X", b_stable_id="Y")
    service = ClashCostImpactService(db_session)
    payload, _ = await service.impact_for_clash(clash.id)
    # 1000 × 0.25 = 250 + 400 labour = 650
    assert payload["components"]["rework_factor_pct"] == 25.0
    assert payload["components"]["rework_subtotal"] == 250.00
    assert payload["total_estimate"] == 650.00

    # Decimal fraction form (0.30) also works.
    project.metadata_ = {"clash_cost_impact": {"rework_factor": "0.30"}}
    await db_session.flush()
    payload2, _ = await service.impact_for_clash(clash.id)
    assert payload2["components"]["rework_factor_pct"] == 30.0
    assert payload2["components"]["rework_subtotal"] == 300.00


@pytest.mark.asyncio
async def test_blended_rate_configurable_per_project(db_session):
    """Override the labour rate via ``Project.metadata_``."""
    user = await _make_user(db_session)
    project = await _make_project(
        db_session,
        owner=user,
        metadata={"clash_cost_impact": {"blended_rate": "75.00"}},
    )
    run = await _make_run(db_session, project)
    clash = await _make_clash(
        db_session,
        run,
        a_stable_id="X",
        b_stable_id="Y",
        a_discipline="Structural",
        b_discipline="Mechanical",
    )
    service = ClashCostImpactService(db_session)
    payload, _ = await service.impact_for_clash(clash.id)
    # 8 h × 75 = 600
    assert payload["components"]["blended_rate"] == 75.00
    assert payload["components"]["labour_subtotal"] == 600.00


@pytest.mark.asyncio
async def test_decimal_precision_rounds_to_two_dp(db_session):
    """The wire shape is rounded to 2 dp; internal arithmetic is exact."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    # 33.333… × 10 = 333.33… — guarantees the rounding path.
    await _make_boq_with_position(
        db_session,
        project,
        cad_element_ids=["Q"],
        quantity="3",
        unit_rate="33.33",
        total="99.99",
    )
    run = await _make_run(db_session, project)
    clash = await _make_clash(db_session, run, a_stable_id="Q", b_stable_id="R")
    service = ClashCostImpactService(db_session)
    payload, _ = await service.impact_for_clash(clash.id)
    # 99.99 × 0.10 = 9.999 → rounds to 10.00; labour 400 → total 410.00.
    assert payload["components"]["rework_subtotal"] == 10.00
    assert payload["total_estimate"] == 410.00


@pytest.mark.asyncio
async def test_defaults_are_documented_and_used(db_session):
    """Sanity — the module-level defaults match the spec and apply on a vanilla project."""
    assert Decimal("0.10") == DEFAULT_REWORK_FACTOR
    assert Decimal("50.0") == DEFAULT_BLENDED_RATE

    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user)
    run = await _make_run(db_session, project)
    clash = await _make_clash(
        db_session,
        run,
        a_stable_id="X",
        b_stable_id="Y",
        a_discipline="Structural",
        b_discipline="Mechanical",
    )
    service = ClashCostImpactService(db_session)
    payload, _ = await service.impact_for_clash(clash.id)
    assert payload["components"]["rework_factor_pct"] == 10.0
    assert payload["components"]["blended_rate"] == 50.0


@pytest.mark.asyncio
async def test_missing_clash_returns_none(db_session):
    """A non-existent clash id resolves to a (None, None) tuple → 404 path."""
    service = ClashCostImpactService(db_session)
    payload, project_id = await service.impact_for_clash(uuid.uuid4())
    assert payload is None
    assert project_id is None


@pytest.mark.asyncio
async def test_missing_project_in_rollup_returns_none(db_session):
    """A non-existent project resolves to ``None`` for the router 404 path."""
    service = ClashCostImpactService(db_session)
    rollup = await service.rollup_for_project(uuid.uuid4())
    assert rollup is None


@pytest.mark.asyncio
async def test_rollup_isolates_by_project_id(db_session):
    """A clash on project B never leaks into project A's rollup.

    The router enforces project ownership via ``verify_project_access``;
    the service layer additionally scopes its queries to the supplied
    ``project_id`` so a router-level bypass (e.g. an admin viewer) still
    cannot accidentally merge two projects' clashes into one rollup.
    """
    user = await _make_user(db_session)
    proj_a = await _make_project(db_session, owner=user, currency="EUR")
    proj_b = await _make_project(db_session, owner=user, currency="USD")
    # Clash on project B only.
    run_b = await _make_run(db_session, proj_b)
    await _make_clash(db_session, run_b, a_stable_id="B1", b_stable_id="B2")

    service = ClashCostImpactService(db_session)
    rollup_a = await service.rollup_for_project(proj_a.id)
    rollup_b = await service.rollup_for_project(proj_b.id)
    assert rollup_a["clash_count"] == 0
    assert rollup_a["total_open_impact"] == 0.0
    assert rollup_a["currency"] == "EUR"
    assert rollup_b["clash_count"] == 1
    assert rollup_b["currency"] == "USD"


@pytest.mark.asyncio
async def test_empty_project_rollup_is_well_formed(db_session):
    """A project with zero clashes returns a zero-totals envelope, not 500."""
    user = await _make_user(db_session)
    project = await _make_project(db_session, owner=user, currency="GBP")
    service = ClashCostImpactService(db_session)
    rollup = await service.rollup_for_project(project.id)
    assert rollup is not None
    assert rollup["clash_count"] == 0
    assert rollup["total_open_impact"] == 0.0
    assert rollup["currency"] == "GBP"
    assert rollup["by_trade_pair"] == []
