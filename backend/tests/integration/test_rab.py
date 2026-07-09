# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""ACAP RAB generator tests — needs a real PostgreSQL session.

Covers app.modules.acap.rab.generator: midpoint_price, unit_rate_for_kode,
generate_rab, persist_rab. Uses the fork's transactional_session pattern
(rolled back after each test) — mirrors test_coefficients.py / test_scraper.py.

NOTE: cannot be run in this sandbox (no local PostgreSQL); the reviewer runs
this suite in Docker. Written against the exact fixture pattern of the
neighbouring integration suites.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.acap.layout.schema import FloorPlan, Kavling, Level, Point, Room
from app.modules.acap.models.coefficients import AhspCoefficient, AhspResource
from app.modules.acap.models.prices import MaterialPrice, Region
from app.modules.acap.rab.generator import (
    ELEMENT_KODE_MAP,
    generate_rab,
    midpoint_price,
    persist_rab,
    unit_rate_for_kode,
)
from app.modules.acap.seed import seed_ahsp
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated session — rolled back after each test."""
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _make_project(session) -> uuid.UUID:
    from app.modules.projects.models import Project

    project = Project(name=f"ACAP RAB {uuid.uuid4().hex[:6]}", currency="IDR", owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    return project.id


async def _seed_batam_region(session) -> uuid.UUID:
    region = Region(code="BATAM", name="Batam", province="Kepulauan Riau")
    session.add(region)
    await session.flush()
    return region.id


async def _add_price(
    session,
    region_id: uuid.UUID,
    *,
    item_type: str,
    item_name: str,
    price_min: float,
    price_max: float,
    source: str = "test-source",
) -> None:
    session.add(
        MaterialPrice(
            region_id=region_id,
            source=source,
            source_url="https://example.test",
            item_type=item_type,
            item_name=item_name,
            price_min=price_min,
            price_max=price_max,
            scraped_at=datetime.now(UTC),
        )
    )
    await session.flush()


# ═══════════════════════════════════════════════════════════════════════════
# unit_rate_for_kode — exact worked example
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unit_rate_exact_worked_example(session):
    """70*1100 + 0.3*150000 = 77000 + 45000 = 122000 exactly."""
    coeff = AhspCoefficient(kode="TEST.WALL", uraian="Test wall", satuan="m2", kategori="test")
    session.add(coeff)
    await session.flush()
    session.add_all(
        [
            AhspResource(coefficient_id=coeff.id, tipe="bahan", nama="BataX", satuan="bh", koef=Decimal("70")),
            AhspResource(coefficient_id=coeff.id, tipe="tenaga", nama="TukangX", satuan="OH", koef=Decimal("0.3")),
        ]
    )
    await session.flush()

    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="bahan", item_name="BataX", price_min=1000, price_max=1200)
    await _add_price(session, region_id, item_type="tenaga", item_name="TukangX", price_min=150000, price_max=150000)

    rate, missing = await unit_rate_for_kode(session, "TEST.WALL")

    assert missing == []
    assert rate == Decimal("122000.00")


@pytest.mark.asyncio
async def test_midpoint_price_case_insensitive_latest(session):
    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="bahan", item_name="BataX", price_min=1000, price_max=1200)

    price = await midpoint_price(session, "bahan", "batax")  # different case

    assert price == Decimal("1100")


@pytest.mark.asyncio
async def test_midpoint_price_no_match_returns_none(session):
    await _seed_batam_region(session)

    price = await midpoint_price(session, "bahan", "Nonexistent Material")

    assert price is None


# ═══════════════════════════════════════════════════════════════════════════
# unit_rate_for_kode — PRICE_MISSING never guessed
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unit_rate_price_missing_resource_flagged(session):
    coeff = AhspCoefficient(kode="TEST.WALL.MISSING", uraian="Test wall missing", satuan="m2", kategori="test")
    session.add(coeff)
    await session.flush()
    session.add_all(
        [
            # BataY has NO price row seeded below.
            AhspResource(coefficient_id=coeff.id, tipe="bahan", nama="BataY", satuan="bh", koef=Decimal("10")),
            AhspResource(coefficient_id=coeff.id, tipe="tenaga", nama="TukangX", satuan="OH", koef=Decimal("0.1")),
        ]
    )
    await session.flush()

    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="tenaga", item_name="TukangX", price_min=150000, price_max=150000)
    # Deliberately no price for "BataY".

    rate, missing = await unit_rate_for_kode(session, "TEST.WALL.MISSING")

    assert missing == ["BataY"]
    # Never a guessed number for the missing component: only the matched
    # tenaga contributes (0.1 * 150000 = 15000).
    assert rate == Decimal("15000.00")


# ═══════════════════════════════════════════════════════════════════════════
# takeoff -> qty integration (Decimal exactness)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_takeoff_qty_times_rate_exact(session):
    """net wall area 42.0 (from test_takeoff.py's fixture) x unit_rate -> exact total."""
    coeff = AhspCoefficient(kode="TEST.WALL", uraian="Test wall", satuan="m2", kategori="test")
    session.add(coeff)
    await session.flush()
    session.add_all(
        [
            AhspResource(coefficient_id=coeff.id, tipe="bahan", nama="BataX", satuan="bh", koef=Decimal("70")),
            AhspResource(coefficient_id=coeff.id, tipe="tenaga", nama="TukangX", satuan="OH", koef=Decimal("0.3")),
        ]
    )
    await session.flush()
    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="bahan", item_name="BataX", price_min=1000, price_max=1200)
    await _add_price(session, region_id, item_type="tenaga", item_name="TukangX", price_min=150000, price_max=150000)

    rate, missing = await unit_rate_for_kode(session, "TEST.WALL")
    assert missing == []
    assert rate == Decimal("122000.00")

    net_wall_area_m2 = Decimal("42.0")  # asserted exactly in test_takeoff.py
    total = net_wall_area_m2 * rate

    assert total == Decimal("5124000.000")


# ═══════════════════════════════════════════════════════════════════════════
# generate_rab / persist_rab — full pipeline against the real seeded AHSP DB
# ═══════════════════════════════════════════════════════════════════════════


def _plan_one_room_no_openings() -> FloorPlan:
    """Kavling 8x10, one room (3,4) rectangle -> net_wall_area = 42.0 m2 (see test_takeoff.py)."""
    room = Room(
        name="Kamar Tidur",
        type="kamar_tidur",
        polygon=[
            Point(x=0.0, y=0.0),
            Point(x=3.0, y=0.0),
            Point(x=3.0, y=4.0),
            Point(x=0.0, y=4.0),
        ],
        area_m2=12.0,
    )
    level = Level(level=1, rooms=[room], walls=[], openings=[])
    return FloorPlan(kavling=Kavling(width_m=8.0, length_m=10.0), levels=[level])


async def _seed_full_wall_finish_prices(session, region_id: uuid.UUID, *, include_pasir: bool = True) -> None:
    """Seed Batam prices for every bahan/tenaga resource used by
    ACAP.DINDING.BATA_MERAH_1_4 / ACAP.PLESTERAN.1_4 / ACAP.ACIAN.STANDAR.
    """
    await _add_price(session, region_id, item_type="bahan", item_name="Bata merah", price_min=900, price_max=1100)
    await _add_price(session, region_id, item_type="bahan", item_name="Semen portland", price_min=1500, price_max=1700)
    if include_pasir:
        await _add_price(session, region_id, item_type="bahan", item_name="Pasir pasang", price_min=250000, price_max=300000)
    await _add_price(session, region_id, item_type="tenaga", item_name="pekerja", price_min=120000, price_max=120000)
    await _add_price(session, region_id, item_type="tenaga", item_name="tukang_batu", price_min=140000, price_max=140000)
    await _add_price(session, region_id, item_type="tenaga", item_name="kepala_tukang", price_min=160000, price_max=160000)
    await _add_price(session, region_id, item_type="tenaga", item_name="mandor", price_min=180000, price_max=180000)


@pytest.mark.asyncio
async def test_generate_rab_full_pipeline_all_priced(session):
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_wall_finish_prices(session, region_id, include_pasir=True)

    plan = _plan_one_room_no_openings()
    project_id = await _make_project(session)

    result = await generate_rab(session, plan, project_id)

    assert len(result.lines) == len(ELEMENT_KODE_MAP) == 3
    for line in result.lines:
        assert line["price_missing"] is False
        assert line["missing_resources"] == []
        assert line["unit_rate"] is not None
        assert line["total"] is not None

    dinding_line = next(line_ for line_ in result.lines if line_["kode"] == "ACAP.DINDING.BATA_MERAH_1_4")
    assert dinding_line["quantity"] == Decimal("42.0")

    plesteran_line = next(line_ for line_ in result.lines if line_["kode"] == "ACAP.PLESTERAN.1_4")
    acian_line = next(line_ for line_ in result.lines if line_["kode"] == "ACAP.ACIAN.STANDAR")
    assert plesteran_line["quantity"] == Decimal("84.0")
    assert acian_line["quantity"] == Decimal("84.0")

    assert result.price_missing_lines == []
    expected_grand_total = sum((line_["total"] for line_ in result.lines), Decimal("0"))
    assert result.grand_total == expected_grand_total
    assert result.not_covered  # informational, non-empty per spec scope note


@pytest.mark.asyncio
async def test_generate_rab_price_missing_excluded_from_grand_total(session):
    """Omitting 'Pasir pasang' price makes dinding + plesteran PRICE_MISSING
    (both use it) while acian (no pasir) stays fully priced — grand_total
    must then equal ONLY the acian line's total.
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_wall_finish_prices(session, region_id, include_pasir=False)

    plan = _plan_one_room_no_openings()
    project_id = await _make_project(session)

    result = await generate_rab(session, plan, project_id)

    dinding_line = next(line_ for line_ in result.lines if line_["kode"] == "ACAP.DINDING.BATA_MERAH_1_4")
    plesteran_line = next(line_ for line_ in result.lines if line_["kode"] == "ACAP.PLESTERAN.1_4")
    acian_line = next(line_ for line_ in result.lines if line_["kode"] == "ACAP.ACIAN.STANDAR")

    assert dinding_line["price_missing"] is True
    assert "Pasir pasang" in dinding_line["missing_resources"]
    assert dinding_line["total"] is None
    assert dinding_line["unit_rate"] is None

    assert plesteran_line["price_missing"] is True
    assert "Pasir pasang" in plesteran_line["missing_resources"]

    assert acian_line["price_missing"] is False
    assert acian_line["total"] is not None

    assert result.grand_total == acian_line["total"]
    assert len(result.price_missing_lines) == 2


@pytest.mark.asyncio
async def test_persist_rab_creates_boq_with_sections_and_positions(session):
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_wall_finish_prices(session, region_id, include_pasir=True)

    plan = _plan_one_room_no_openings()
    project_id = await _make_project(session)
    result = await generate_rab(session, plan, project_id)

    boq_id = await persist_rab(session, project_id, result)
    assert boq_id is not None

    from app.modules.boq.models import BOQ, Position

    boq = (await session.execute(select(BOQ).where(BOQ.id == boq_id))).scalar_one()
    assert boq.project_id == project_id
    assert boq.name == "RAB (auto) - v1"

    positions = (await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()
    sections = [p for p in positions if p.unit == "section"]
    leaves = [p for p in positions if p.unit != "section"]

    assert len(leaves) == 3
    for leaf in leaves:
        assert leaf.source == "takeoff"
        assert leaf.metadata_["acap_kode"] in ELEMENT_KODE_MAP.values()
        assert leaf.metadata_["price_missing"] is False
        assert leaf.validation_status != "errors"
    # every leaf hangs under a section (kategori grouping)
    assert all(leaf.parent_id in {s.id for s in sections} for leaf in leaves)


@pytest.mark.asyncio
async def test_persist_rab_flags_price_missing_on_position(session):
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_wall_finish_prices(session, region_id, include_pasir=False)

    plan = _plan_one_room_no_openings()
    project_id = await _make_project(session)
    result = await generate_rab(session, plan, project_id)

    boq_id = await persist_rab(session, project_id, result)

    from app.modules.boq.models import Position

    positions = (await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()
    leaves = [p for p in positions if p.unit != "section"]

    missing_leaves = [leaf for leaf in leaves if leaf.metadata_["price_missing"] is True]
    priced_leaves = [leaf for leaf in leaves if leaf.metadata_["price_missing"] is False]

    assert len(missing_leaves) == 2  # dinding + plesteran
    assert len(priced_leaves) == 1  # acian

    for leaf in missing_leaves:
        assert leaf.validation_status == "errors"
        assert "Pasir pasang" in leaf.metadata_["missing_resources"]
        # never a guessed rate — service persists money as a quantized string
        # ("0.0000"), never the (unknown) real component-priced value.
        assert Decimal(leaf.unit_rate) == Decimal("0")

    assert priced_leaves[0].validation_status != "errors"


# ═══════════════════════════════════════════════════════════════════════════
# HTTP layer — POST /projects/{project_id}/rab:generate
# ═══════════════════════════════════════════════════════════════════════════


def _build_app(session):
    """Minimal app exposing the acap router with session/auth overridden.

    Mirrors test_layout_edit.py's _build_app pattern exactly.
    """
    from fastapi import FastAPI

    from app.dependencies import get_current_user_id
    from app.modules.acap.router import get_session as acap_get_session
    from app.modules.acap.router import router as acap_router

    app = FastAPI()
    app.include_router(acap_router, prefix="/api/v1/acap")

    async def _override_session():
        yield session

    def _override_user_id() -> str:
        return str(uuid.uuid4())

    app.dependency_overrides[acap_get_session] = _override_session
    app.dependency_overrides[get_current_user_id] = _override_user_id
    return app


@pytest.mark.asyncio
async def test_generate_rab_endpoint_returns_boq_and_totals(session):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.modules.acap.models.floor_plan import FloorPlanRecord

    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_wall_finish_prices(session, region_id, include_pasir=True)

    project_id = await _make_project(session)
    plan = _plan_one_room_no_openings()
    session.add(
        FloorPlanRecord(
            project_id=project_id,
            version=1,
            requirement_text="test",
            jumlah_lantai=1,
            model="test",
            status="generated",
            plan_json=plan.model_dump(),
        )
    )
    await session.flush()

    app: FastAPI = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/acap/projects/{project_id}/rab:generate")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "boq_id" in body
    assert isinstance(body["grand_total"], str)
    assert Decimal(body["grand_total"]) > 0
    assert body["price_missing_lines"] == []
    assert isinstance(body["subtotals_by_kategori"], dict)
    assert body["not_covered"]

    from app.modules.boq.models import Position

    positions = (
        await session.execute(select(Position).where(Position.boq_id == uuid.UUID(body["boq_id"])))
    ).scalars().all()
    assert len([p for p in positions if p.unit != "section"]) == 3


@pytest.mark.asyncio
async def test_generate_rab_endpoint_404_when_no_layout(session):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    project_id = await _make_project(session)

    app: FastAPI = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/acap/projects/{project_id}/rab:generate")

    assert resp.status_code == 404
