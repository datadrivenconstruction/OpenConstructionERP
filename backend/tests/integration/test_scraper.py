from __future__ import annotations

import pathlib
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.acap.models.prices import MaterialPrice, Region
from app.modules.acap.scraper.arsiteqi import parse_arsiteqi
from app.modules.acap.scraper.base import PriceRecord, parse_price_range, parse_rupiah
from app.modules.acap.scraper.persist import persist_prices
from app.modules.acap.scraper.sobatbangun import parse_sobatbangun
from tests._pg import transactional_session

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "acap_scraper"


# ═══════════════════════════════════════════════════════════════════════════
# Unit: base parse helpers
# ═══════════════════════════════════════════════════════════════════════════


def test_parse_rupiah_and_range():
    assert parse_rupiah("Rp. 175.000") == 175000
    assert parse_rupiah("Rp 65.000") == 65000
    assert parse_rupiah("Rp. 100.000") == 100000

    low, high = parse_price_range("Rp 65.000 – Rp 105.000")
    assert (low, high) == (65000, 105000)

    low, high = parse_price_range("Rp. 175.000")
    assert low == high == 175000


# ═══════════════════════════════════════════════════════════════════════════
# Integration: arsiteqi adapter
# ═══════════════════════════════════════════════════════════════════════════


def test_arsiteqi_adapter():
    html = (FIXTURES / "arsiteqi_batam_upah.html").read_text()
    records = parse_arsiteqi(html, "https://arsiteqi.or.id/upah/tukang-bangunan-batam/")

    # Harian: Kepala Tukang
    kepala = next(r for r in records if r.item_name == "Kepala Tukang")
    assert kepala.item_type == "upah_harian"
    assert kepala.price_min == kepala.price_max == 175000
    assert kepala.satuan == "orang/hari"

    # Harian: Tukang Batu
    batu = next(r for r in records if r.item_name == "Tukang Batu")
    assert batu.price_min == batu.price_max == 140000

    # Borongan: Galian Tanah Pondasi
    galian = next(r for r in records if r.item_name == "Galian Tanah Pondasi")
    assert galian.item_type == "upah_borongan"
    assert galian.price_min == galian.price_max == 70000
    assert galian.satuan == "m3"

    assert len(records) >= 20, f"Expected ≥20 records, got {len(records)}"


# ═══════════════════════════════════════════════════════════════════════════
# Integration: sobatbangun adapter
# ═══════════════════════════════════════════════════════════════════════════


def test_sobatbangun_adapter():
    html = (FIXTURES / "sobatbangun_material.html").read_text()
    records = parse_sobatbangun(html, "https://sobatbangun.com/artikel/harga-material-bangunan-terbaru/")

    # Semen (should prefer 2026 table row)
    semen = next(r for r in records if "Semen" in r.item_name)
    assert semen.item_type == "material"
    assert semen.price_min == 65000
    assert semen.price_max == 105000

    # Pasir Cor
    pasir = next(r for r in records if "Pasir Cor" in r.item_name)
    assert pasir.price_min == 280000
    assert pasir.price_max == 380000

    # No duplicate item_names
    names = [r.item_name.strip().lower() for r in records]
    assert len(names) == len(set(names)), f"Duplicate item_names: {[n for n in names if names.count(n) > 1]}"


# ═══════════════════════════════════════════════════════════════════════════
# DB: provenance not-null constraints
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_price_provenance_not_null(session):
    """MaterialPrice with source=None raises IntegrityError."""
    region = Region(code="BATAM", name="Batam", province="Kepulauan Riau")
    session.add(region)
    await session.flush()

    mp = MaterialPrice(
        region_id=region.id,
        source=None,  # type: ignore[arg-type]  — deliberately null to test constraint
        source_url="x",
        item_type="material",
        item_name="Test",
        price_min=100,
        price_max=200,
        scraped_at=datetime.now(UTC),
    )
    session.add(mp)
    with pytest.raises(IntegrityError):
        await session.flush()

    # Clean up so the session stays usable
    await session.rollback()


@pytest.mark.asyncio
async def test_price_region_id_not_null(session):
    """MaterialPrice with region_id=None raises IntegrityError."""
    mp = MaterialPrice(
        region_id=None,  # type: ignore[arg-type]
        source="test",
        source_url="x",
        item_type="material",
        item_name="Test",
        price_min=100,
        price_max=200,
        scraped_at=datetime.now(UTC),
    )
    session.add(mp)
    with pytest.raises(IntegrityError):
        await session.flush()

    await session.rollback()


@pytest.mark.asyncio
async def test_price_scraped_at_not_null(session):
    """MaterialPrice with scraped_at=None raises IntegrityError."""
    region = Region(code="BATAM", name="Batam", province="Kepulauan Riau")
    session.add(region)
    await session.flush()

    mp = MaterialPrice(
        region_id=region.id,
        source="test",
        source_url="x",
        item_type="material",
        item_name="Test",
        price_min=100,
        price_max=200,
        scraped_at=None,  # type: ignore[arg-type]
    )
    session.add(mp)
    with pytest.raises(IntegrityError):
        await session.flush()

    await session.rollback()


# ═══════════════════════════════════════════════════════════════════════════
# DB: persist idempotency
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_persist_idempotent(session):
    """Running persist_prices twice yields identical row counts."""
    records = [
        PriceRecord(
            source="sobatbangun.com",
            source_url="https://example.com/a",
            item_type="material",
            item_name="Semen (50 kg)",
            satuan="Sak",
            price_min=65000,
            price_max=105000,
        ),
        PriceRecord(
            source="sobatbangun.com",
            source_url="https://example.com/b",
            item_type="material",
            item_name="Pasir Cor",
            satuan="m3",
            price_min=280000,
            price_max=380000,
        ),
        PriceRecord(
            source="arsiteqi.or.id",
            source_url="https://example.com/c",
            item_type="upah_harian",
            item_name="Kepala Tukang",
            satuan="orang/hari",
            price_min=175000,
            price_max=175000,
        ),
    ]

    # First persist
    await persist_prices(session, region_code="BATAM", records=records)

    price_count_1 = len((await session.execute(select(MaterialPrice))).scalars().all())
    region_count_1 = len((await session.execute(select(Region))).scalars().all())

    # Second persist
    await persist_prices(session, region_code="BATAM", records=records)

    price_count_2 = len((await session.execute(select(MaterialPrice))).scalars().all())
    region_count_2 = len((await session.execute(select(Region))).scalars().all())

    # Row counts identical
    assert price_count_1 == price_count_2
    assert price_count_1 == len(records)
    assert region_count_1 == region_count_2
    assert region_count_1 == 1  # only BATAM
