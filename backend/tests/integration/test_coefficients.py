from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.acap.loader import DEFAULT_DATA_DIR, load_ahsp_dir
from app.modules.acap.models.coefficients import AhspCoefficient, AhspResource
from app.modules.acap.seed import seed_ahsp
from tests._pg import transactional_session


# ═══════════════════════════════════════════════════════════════════════════
# Loader tests (no DB needed)
# ═══════════════════════════════════════════════════════════════════════════


def test_loader_loads_all():
    """load_ahsp_dir returns ≥26 items with unique kodes and correct spot data."""
    items = load_ahsp_dir(DEFAULT_DATA_DIR)

    assert len(items) >= 26, f"Expected ≥26 items, got {len(items)}"

    codes = [d["kode"] for d in items]
    assert len(codes) == len(set(codes)), "Duplicate kode found"

    # Spot-assert K175
    k175 = next(d for d in items if d["kode"] == "ACAP.BETON.K175")
    tenaga_pekerja = next(t for t in k175["tenaga"] if t["jabatan"] == "pekerja")
    assert tenaga_pekerja["koef_oh"] == 1.65
    bahan_semen = next(b for b in k175["bahan"] if "Semen" in b["nama"])
    assert bahan_semen["koef"] == 326.0

    # Spot-assert GALIAN_BIASA_1M
    galian = next(d for d in items if d["kode"] == "ACAP.TANAH.GALIAN_BIASA_1M")
    pekerja = next(t for t in galian["tenaga"] if t["jabatan"] == "pekerja")
    mandor = next(t for t in galian["tenaga"] if t["jabatan"] == "mandor")
    assert pekerja["koef_oh"] == 0.750
    assert mandor["koef_oh"] == 0.025


# ═══════════════════════════════════════════════════════════════════════════
# Seed tests (needs a DB session)
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated session — rolled back after each test."""
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_seed_idempotent(session):
    """Running seed twice yields the same row counts."""
    # First seed
    count1 = await seed_ahsp(session)
    assert count1 > 0

    coeff_count_after_first = await session.scalar(
        select(func.count()).select_from(AhspCoefficient)
    )
    res_count_after_first = await session.scalar(
        select(func.count()).select_from(AhspResource)
    )

    loaded_items = len(load_ahsp_dir(DEFAULT_DATA_DIR))
    assert coeff_count_after_first == loaded_items

    # Second seed
    count2 = await seed_ahsp(session)

    coeff_count_after_second = await session.scalar(
        select(func.count()).select_from(AhspCoefficient)
    )
    res_count_after_second = await session.scalar(
        select(func.count()).select_from(AhspResource)
    )

    # Counts should be identical and match loaded items
    assert coeff_count_after_first == coeff_count_after_second
    assert coeff_count_after_second == loaded_items
    assert res_count_after_first == res_count_after_second
    assert res_count_after_first > 0
