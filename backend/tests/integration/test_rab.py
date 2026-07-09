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

from app.modules.acap.layout.schema import FloorPlan, Kavling, Level, Opening, Point, Room
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
    await _add_price(session, region_id, item_type="material", item_name="BataX", price_min=1000, price_max=1200)
    await _add_price(session, region_id, item_type="upah_harian", item_name="TukangX", price_min=150000, price_max=150000)

    rate, missing, curated = await unit_rate_for_kode(session, "TEST.WALL")

    assert missing == []
    assert curated == []  # BataX/TukangX are not aliased -> direct match, factor 1
    assert rate == Decimal("122000.00")


@pytest.mark.asyncio
async def test_midpoint_price_case_insensitive_latest(session):
    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="material", item_name="BataX", price_min=1000, price_max=1200)

    price = await midpoint_price(session, "material", "batax")  # different case

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
    await _add_price(session, region_id, item_type="upah_harian", item_name="TukangX", price_min=150000, price_max=150000)
    # Deliberately no price for "BataY".

    rate, missing, curated = await unit_rate_for_kode(session, "TEST.WALL.MISSING")

    assert missing == ["BataY"]
    assert curated == []
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
    await _add_price(session, region_id, item_type="material", item_name="BataX", price_min=1000, price_max=1200)
    await _add_price(session, region_id, item_type="upah_harian", item_name="TukangX", price_min=150000, price_max=150000)

    rate, missing, _curated = await unit_rate_for_kode(session, "TEST.WALL")
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
    """Seed Batam prices under the RECONCILED (aliased) item_type/item_name for
    every resource of ACAP.DINDING.BATA_MERAH_1_4 / ACAP.PLESTERAN.1_4 /
    ACAP.ACIAN.STANDAR — i.e. what the real scraper produces + price_map aliases.
    """
    await _add_price(session, region_id, item_type="material", item_name="Bata merah", price_min=900, price_max=1100)
    # Semen priced per 50-kg sak; price_map applies the /50 unit factor.
    await _add_price(session, region_id, item_type="material", item_name="Semen (50 kg)", price_min=75000, price_max=85000)
    if include_pasir:
        await _add_price(session, region_id, item_type="material", item_name="Pasir m³", price_min=250000, price_max=300000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Pembantu Tukang", price_min=120000, price_max=120000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Tukang Batu", price_min=140000, price_max=140000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Kepala Tukang", price_min=160000, price_max=160000)
    # Mandor: a real "Mandor" upah_harian row now exists (price_map.py drops
    # the curated fallback per the 2026-07-09 full-house wiring spec), so
    # every kode (mandor is on ALL of them) needs it seeded to price.
    await _add_price(session, region_id, item_type="upah_harian", item_name="Mandor", price_min=150000, price_max=150000)


# Every OTHER resource the 2026-07-09 full-house wiring pass introduces,
# beyond the original dinding/plesteran/acian scope. Generated by walking
# every ELEMENT_KODE_MAP kode's AHSP resources through resolve_price_ref
# (see docs/plans/2026-07-09-rab-full-wiring-spec.md §1/§3) — one row per
# distinct (item_type, item_name) the reconciliation layer resolves to.
_FULL_HOUSE_EXTRA_PRICES: list[tuple[str, str, int, int]] = [
    # Consumables that resolve via the name-direct fallback (bucket bahan->material).
    # (bare "Paku biasa" / "Papan kayu" are covered below/by an alias, not here.)
    ("material", "Batu belah", 15000, 17000),
    ("material", "Conduit HI 20 mm", 15000, 17000),
    ("material", "Elbow", 15000, 17000),
    ("material", "Fischer S6 + sekrup", 15000, 17000),
    ("material", "Flexible conduit 20 mm", 15000, 17000),
    ("material", "Flexible hose", 15000, 17000),
    ("material", "Isolasi", 15000, 17000),
    ("material", "Kawat las", 15000, 17000),
    ("material", "Klem 20 mm", 15000, 17000),
    ("material", "Lasdop", 15000, 17000),
    ("material", "Sealant", 15000, 17000),
    ("material", "Sealtape", 15000, 17000),
    ("material", "Sekrup fixer", 15000, 17000),
    ("material", "Silicone sealant 300 ml", 15000, 17000),
    ("material", "Socket conduit 20 mm", 15000, 17000),
    ("material", "T dus", 15000, 17000),
    ("material", "Baja ringan kanal C75", 15000, 17000),
    ("material", "Besi beton 10 mm", 15000, 17000),
    ("material", "Cairan primer", 15000, 17000),
    ("material", "Cat dasar/plamir", 15000, 17000),
    ("material", "Cat interior", 15000, 17000),
    ("material", "Engsel pintu", 15000, 17000),
    ("material", "Floor drain", 15000, 17000),
    ("material", "Genteng beton", 15000, 17000),
    ("material", "Gypsum board 9mm", 15000, 17000),
    ("material", "Kabel NYM 3x2.5 mm2", 15000, 17000),
    ("material", "Kaca 5 mm", 15000, 17000),
    ("material", "Kait angin", 15000, 17000),
    ("material", "Kawat beton", 15000, 17000),
    ("material", "Kayu kelas III", 15000, 17000),
    ("material", "Keramik Lantai 40×40", 15000, 17000),
    ("material", "Keramik dinding", 15000, 17000),
    ("material", "Kerikil", 15000, 17000),
    ("material", "Kloset duduk", 500000, 502000),
    ("material", "Kran air", 15000, 17000),
    ("material", "Kunci tanam biasa", 15000, 17000),
    ("material", "Lem kayu", 15000, 17000),
    ("material", "MCB box", 15000, 17000),
    ("material", "Membran bakar", 15000, 17000),
    ("material", "Minyak bekisting", 15000, 17000),
    ("material", "Paku biasa", 15000, 17000),
    ("material", "Papan kayu kelas III", 15000, 17000),
    ("material", "Pasir beton", 15000, 17000),
    ("material", "Pipa PVC AW 1/2 inch", 15000, 17000),
    ("material", "Pipa PVC D 2 inch", 15000, 17000),
    ("material", "Pompa jet 27 lpm", 500000, 502000),
    ("material", "Profil aluminium 4 inch", 15000, 17000),
    ("material", "Rangka hollow", 15000, 17000),
    ("material", "Saklar tunggal", 15000, 17000),
    ("material", "Semen putih", 15000, 17000),
    ("material", "Tangki toren 0.7 m3", 500000, 502000),
    ("upah_harian", "Tukang aluminium", 120000, 122000),
    ("upah_harian", "Tukang besi", 120000, 122000),
    ("upah_harian", "Tukang cat", 120000, 122000),
    ("upah_harian", "Tukang kayu", 120000, 122000),
    ("upah_harian", "Tukang listrik", 120000, 122000),
    ("upah_harian", "Tukang pipa", 120000, 122000),
]


async def _seed_full_house_prices(session, region_id: uuid.UUID, *, include_pasir: bool = True) -> None:
    """Seed a Batam price row for EVERY resource across the whole
    ELEMENT_KODE_MAP (struktur praktis + finishing + bukaan + sanitair + MEP
    + atap) — i.e. enough for generate_rab to reach price_missing_lines == []
    on any plan geometry. Builds on _seed_full_wall_finish_prices for the
    original dinding/plesteran/acian scope.
    """
    await _seed_full_wall_finish_prices(session, region_id, include_pasir=include_pasir)
    for item_type, item_name, price_min, price_max in _FULL_HOUSE_EXTRA_PRICES:
        await _add_price(session, region_id, item_type=item_type, item_name=item_name, price_min=price_min, price_max=price_max)


@pytest.mark.asyncio
async def test_reconciliation_alias_unit_factor_and_curated(session):
    """Locks the money reconciliation: item_type/name alias and the semen /50
    unit factor — exact rupiah. Mandor is now market-sourced too (the
    2026-07-09 spec drops price_map's curated fallback since a real "Mandor"
    upah_harian row exists), so ``curated`` is empty here.

    ACIAN.STANDAR resources (from the seeded AHSP YAML): Semen portland
    3.25 kg, pekerja 0.2, tukang_batu 0.1, kepala_tukang 0.01, mandor
    0.0033 OH.
      semen        3.25  * (100000/50 = 2000) =  6500
      pekerja      0.2   * 100000             = 20000
      tukang_batu  0.1   * 140000             = 14000
      kepala_tukang 0.01 * 175000             =  1750
      mandor       0.0033 * 170000            =   561
      total                                    = 42811
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="material", item_name="Semen (50 kg)", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Pembantu Tukang", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Tukang Batu", price_min=140000, price_max=140000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Kepala Tukang", price_min=175000, price_max=175000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Mandor", price_min=170000, price_max=170000)

    rate, missing, curated = await unit_rate_for_kode(session, "ACAP.ACIAN.STANDAR")

    assert missing == []
    assert curated == []  # no more curated fallback -> fully market-sourced
    assert rate == Decimal("42811.00")


@pytest.mark.asyncio
async def test_generate_rab_full_pipeline_all_priced(session):
    """_plan_one_room_no_openings() is a single kamar_tidur, no doors/windows,
    no wet rooms -> every bukaan/sanitair/pipa_kotor element is 0-qty and
    skipped. The other 21 elements (dinding/plesteran/acian/cat_tembok,
    lantai/plafon/cat_plafon, atap, listplank, kolom/ring praktis, pondasi,
    listrik x4, pipa_bersih (riser-only), pompa, toren) all have nonzero qty.
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_house_prices(session, region_id, include_pasir=True)

    plan = _plan_one_room_no_openings()
    project_id = await _make_project(session)

    result = await generate_rab(session, plan, project_id)

    assert len(result.lines) == 21
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

    # No door/window on this plan -> bukaan elements are skipped entirely.
    lines_kodes = {line_["kode"] for line_ in result.lines}
    assert "ACAP.KUSEN.ALUMINIUM" not in lines_kodes
    assert "ACAP.SANITAIR.KLOSET_DUDUK" not in lines_kodes  # no wet room either

    assert result.price_missing_lines == []
    expected_grand_total = sum((line_["total"] for line_ in result.lines), Decimal("0"))
    assert result.grand_total == expected_grand_total
    assert result.not_covered  # informational, non-empty per spec scope note


@pytest.mark.asyncio
async def test_generate_rab_price_missing_excluded_from_grand_total(session):
    """Omitting 'Pasir pasang' price makes every kode that resource touches
    PRICE_MISSING: dinding, plesteran, pondasi (batu belah mortar) and
    lantai_keramik all use it. Every OTHER line on this plan (acian,
    finishing, atap, listrik, pipa_bersih, pompa, toren, ...) stays fully
    priced — grand_total must equal exactly the sum of those.
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_house_prices(session, region_id, include_pasir=False)

    plan = _plan_one_room_no_openings()
    project_id = await _make_project(session)

    result = await generate_rab(session, plan, project_id)

    missing_kodes = {
        "ACAP.DINDING.BATA_MERAH_1_4",
        "ACAP.PLESTERAN.1_4",
        "ACAP.PONDASI.BATU_BELAH_1_4",
        "ACAP.LANTAI.KERAMIK_40",
    }
    for line in result.lines:
        if line["kode"] in missing_kodes:
            assert line["price_missing"] is True
            assert "Pasir pasang" in line["missing_resources"]
            assert line["total"] is None
            assert line["unit_rate"] is None
        else:
            assert line["price_missing"] is False
            assert line["total"] is not None

    acian_line = next(line_ for line_ in result.lines if line_["kode"] == "ACAP.ACIAN.STANDAR")
    assert acian_line["price_missing"] is False

    assert len(result.price_missing_lines) == len(missing_kodes)
    expected_grand_total = sum((line_["total"] for line_ in result.lines if line_["total"] is not None), Decimal("0"))
    assert result.grand_total == expected_grand_total


@pytest.mark.asyncio
async def test_persist_rab_creates_boq_with_sections_and_positions(session):
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_house_prices(session, region_id, include_pasir=True)

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

    assert len(leaves) == 21  # see test_generate_rab_full_pipeline_all_priced
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
    await _seed_full_house_prices(session, region_id, include_pasir=False)

    plan = _plan_one_room_no_openings()
    project_id = await _make_project(session)
    result = await generate_rab(session, plan, project_id)

    boq_id = await persist_rab(session, project_id, result)

    from app.modules.boq.models import Position

    positions = (await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()
    leaves = [p for p in positions if p.unit != "section"]

    missing_leaves = [leaf for leaf in leaves if leaf.metadata_["price_missing"] is True]
    priced_leaves = [leaf for leaf in leaves if leaf.metadata_["price_missing"] is False]

    # dinding + plesteran + pondasi + lantai_keramik all use "Pasir pasang"
    # (see test_generate_rab_price_missing_excluded_from_grand_total).
    assert len(missing_leaves) == 4
    assert len(priced_leaves) == 17

    for leaf in missing_leaves:
        assert leaf.validation_status == "errors"
        assert "Pasir pasang" in leaf.metadata_["missing_resources"]
        # never a guessed rate — service persists money as a quantized string
        # ("0.0000"), never the (unknown) real component-priced value.
        assert Decimal(leaf.unit_rate) == Decimal("0")

    assert priced_leaves[0].validation_status != "errors"


# ═══════════════════════════════════════════════════════════════════════════
# Unit-factor money-path locks — LANTAI.KERAMIK_40 (÷6), BETON.KOLOM_PRAKTIS
# (÷7.4), PLAFON.RANGKA_HOLLOW (÷4). Real seeded AHSP coefficients (seed_ahsp)
# + a minimal price fixture per kode, hand-computed exact Decimal rate.
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unit_factor_keramik_lantai_divide_by_6(session):
    """LANTAI.KERAMIK_40: 'Keramik lantai 40x40' koef is per keping (bh); the
    price is quoted per dus (6 keping) -> unit_factor = 1/6.

      keramik  6.563  * (90000/6 = 15000)  =  98445
      semen    13.632 * (100000/50 = 2000) =  27264
      semenwrn 1.5    * (100000/50 = 2000) =   3000
      pasir    0.027  * 200000             =   5400
      pekerja  0.1538 * 100000             =  15380
      tk_batu  0.0769 * 140000             =  10766
      k_tukang 0.0077 * 160000             =   1232
      mandor   0.0026 * 150000             =    390
      total                                = 161877
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="material", item_name="Keramik Lantai 40×40", price_min=90000, price_max=90000)
    await _add_price(session, region_id, item_type="material", item_name="Semen (50 kg)", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="material", item_name="Semen putih", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="material", item_name="Pasir m³", price_min=200000, price_max=200000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Pembantu Tukang", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Tukang Batu", price_min=140000, price_max=140000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Kepala Tukang", price_min=160000, price_max=160000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Mandor", price_min=150000, price_max=150000)

    rate, missing, curated = await unit_rate_for_kode(session, "ACAP.LANTAI.KERAMIK_40")

    assert missing == []
    assert curated == []
    assert rate == Decimal("161877.00")


@pytest.mark.asyncio
async def test_unit_factor_kolom_praktis_besi_divide_by_7_4(session):
    """BETON.KOLOM_PRAKTIS: 'Besi beton' koef is per kg; the price is quoted
    per 12 m batang of D10 rebar (7.4 kg) -> unit_factor = 1/7.4.

      kayu     0.002 * 1600000            =   3200
      paku     0.01  * 20000              =    200
      besi     3.0   * (74000/7.4=10000)  =  30000
      kwt betn 0.45  * 30000              =  13500
      semen    4.0   * (100000/50=2000)   =   8000
      pasir    0.006 * 300000             =   1800
      kerikil  0.009 * 300000             =   2700
      pekerja  0.18  * 100000             =  18000
      tk_batu  0.02  * 140000             =   2800
      tk_kayu  0.02  * 130000             =   2600
      tk_besi  0.02  * 130000             =   2600
      k_tukang 0.006 * 160000             =    960
      mandor   0.009 * 150000             =   1350
      total                               =  87710
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="material", item_name="Kayu kelas III", price_min=1600000, price_max=1600000)
    await _add_price(session, region_id, item_type="material", item_name="Paku biasa", price_min=20000, price_max=20000)
    await _add_price(session, region_id, item_type="material", item_name="Besi beton 10 mm", price_min=74000, price_max=74000)
    await _add_price(session, region_id, item_type="material", item_name="Kawat beton", price_min=30000, price_max=30000)
    await _add_price(session, region_id, item_type="material", item_name="Semen (50 kg)", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="material", item_name="Pasir beton", price_min=300000, price_max=300000)
    await _add_price(session, region_id, item_type="material", item_name="Kerikil", price_min=300000, price_max=300000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Pembantu Tukang", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Tukang Batu", price_min=140000, price_max=140000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Tukang kayu", price_min=130000, price_max=130000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Tukang besi", price_min=130000, price_max=130000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Kepala Tukang", price_min=160000, price_max=160000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Mandor", price_min=150000, price_max=150000)

    rate, missing, curated = await unit_rate_for_kode(session, "ACAP.BETON.KOLOM_PRAKTIS")

    assert missing == []
    assert curated == []
    assert rate == Decimal("87710.00")


@pytest.mark.asyncio
async def test_unit_factor_plafon_hollow_divide_by_4(session):
    """PLAFON.RANGKA_HOLLOW: 'Besi hollow 40x40' koef is per m'; the price is
    quoted per 4 m batang -> unit_factor = 1/4.

      hollow   4.0    * (40000/4=10000)  =  40000
      kwt las  0.05   * 16000            =    800
      pekerja  0.35   * 100000           =  35000
      tk_besi  0.35   * 130000           =  45500
      k_tukang 0.035  * 160000           =   5600
      mandor   0.0117 * 150000           =   1755
      total                              = 128655
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _add_price(session, region_id, item_type="material", item_name="Rangka hollow", price_min=40000, price_max=40000)
    # "Kawat las" has no price_map alias -> name-direct fallback translates the
    # bucket bahan->material, matching a real "material" price row.
    await _add_price(session, region_id, item_type="material", item_name="Kawat las", price_min=16000, price_max=16000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Pembantu Tukang", price_min=100000, price_max=100000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Tukang besi", price_min=130000, price_max=130000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Kepala Tukang", price_min=160000, price_max=160000)
    await _add_price(session, region_id, item_type="upah_harian", item_name="Mandor", price_min=150000, price_max=150000)

    rate, missing, curated = await unit_rate_for_kode(session, "ACAP.PLAFON.RANGKA_HOLLOW")

    assert missing == []
    assert curated == []
    assert rate == Decimal("128655.00")


# ═══════════════════════════════════════════════════════════════════════════
# Whole-house plan — every ELEMENT_KODE_MAP label wired end to end
# ═══════════════════════════════════════════════════════════════════════════


def _plan_two_room_one_km_with_door_window() -> FloorPlan:
    """2 indoor rooms (ruang_tamu + kamar_tidur) + 1 kamar_mandi, one door
    (Ruang Tamu) + one window (Kamar Tidur), single level. Every element in
    ELEMENT_KODE_MAP resolves to a nonzero quantity for this plan."""
    ruang_tamu = Room(
        name="Ruang Tamu",
        type="ruang_tamu",
        polygon=[Point(x=0.0, y=0.0), Point(x=4.0, y=0.0), Point(x=4.0, y=4.0), Point(x=0.0, y=4.0)],
        area_m2=16.0,
    )
    kamar_tidur = Room(
        name="Kamar Tidur",
        type="kamar_tidur",
        polygon=[Point(x=4.0, y=0.0), Point(x=8.0, y=0.0), Point(x=8.0, y=4.0), Point(x=4.0, y=4.0)],
        area_m2=16.0,
    )
    km = Room(
        name="KM",
        type="kamar_mandi",
        polygon=[Point(x=0.0, y=4.0), Point(x=2.0, y=4.0), Point(x=2.0, y=6.0), Point(x=0.0, y=6.0)],
        area_m2=4.0,
    )
    door = Opening(type="door", room="Ruang Tamu", width_m=0.9)
    window = Opening(type="window", room="Kamar Tidur", width_m=1.2)
    level = Level(level=1, rooms=[ruang_tamu, kamar_tidur, km], walls=[], openings=[door, window])
    return FloorPlan(kavling=Kavling(width_m=8.0, length_m=6.0), levels=[level])


@pytest.mark.asyncio
async def test_generate_rab_whole_house_plan_all_priced(session):
    """2-room + 1-KM plan with a door + a window -> every ELEMENT_KODE_MAP
    label has a nonzero quantity, so with every resource priced
    (_seed_full_house_prices) the whole RAB comes back fully priced.
    """
    await seed_ahsp(session)
    region_id = await _seed_batam_region(session)
    await _seed_full_house_prices(session, region_id)

    plan = _plan_two_room_one_km_with_door_window()
    project_id = await _make_project(session)

    result = await generate_rab(session, plan, project_id)

    assert result.price_missing_lines == []
    assert result.grand_total > 0

    kodes_present = {line["kode"] for line in result.lines}
    for expected_kode in (
        "ACAP.LANTAI.KERAMIK_40",
        "ACAP.PLAFON.RANGKA_HOLLOW",
        "ACAP.ATAP.RANGKA_BAJARINGAN_C75",
        "ACAP.KUSEN.ALUMINIUM",
        "ACAP.KACA.POLOS_5",
        "ACAP.SANITAIR.KLOSET_DUDUK",
        "ACAP.LISTRIK.TITIK_LAMPU",
        "ACAP.POMPA.JET_27",
    ):
        assert expected_kode in kodes_present, f"missing line for {expected_kode}"

    # This plan has walls, an indoor floor, a roof, a door, a window, and a
    # wet room -> every single ELEMENT_KODE_MAP label computes a nonzero qty.
    assert len(result.lines) == len(ELEMENT_KODE_MAP)


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
    await _seed_full_house_prices(session, region_id, include_pasir=True)

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
    assert len([p for p in positions if p.unit != "section"]) == 21


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
