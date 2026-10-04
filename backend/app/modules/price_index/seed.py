# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deterministic demo seed for the Price Index module.

Loads one generic construction cost index series with a handful of periods and
a few regional factors so the page is never empty on a fresh install. The seed
is idempotent: it keys on the series name and on each region code, so re-running
it never duplicates a row. Only generic vocabulary is used - no named published
index.

Usage:
    >>> from app.modules.price_index.seed import seed_price_index_demo
    >>> await seed_price_index_demo(session)
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.price_index.models import (
    CostIndexPoint,
    CostIndexSeries,
    LocationFactor,
    PriceIndexSeedMarker,
    ResourceIndexValue,
    WorkTypeOverheadNorm,
)

_DEMO_SERIES_NAME = "General Construction Cost Index"

# A gently rising generic index normalised to 1.0 at the base period, standing
# in for real construction cost inflation across recent years.
_DEMO_POINTS: tuple[tuple[str, str], ...] = (
    ("2019-01", "1.000000"),
    ("2021-01", "1.085000"),
    ("2023-01", "1.240000"),
    ("2025-01", "1.355000"),
    ("2026-01", "1.400000"),
)

# Generic regional factors relative to a national baseline of 1.0.
_DEMO_REGIONS: tuple[tuple[str, str, str], ...] = (
    ("NATIONAL_AVG", "National average", "1.000000"),
    ("HIGH_COST_METRO", "High-cost metro area", "1.150000"),
    ("LOW_COST_RURAL", "Low-cost rural area", "0.900000"),
)


async def seed_price_index_demo(session: AsyncSession) -> dict[str, int]:
    """Insert the demo series and regional factors if they are absent.

    Args:
        session: An open async session; the caller owns the transaction.

    Returns:
        Counts of the rows this call actually inserted.
    """
    series_added = 0
    points_added = 0

    existing_series = (
        await session.execute(select(CostIndexSeries).where(CostIndexSeries.name == _DEMO_SERIES_NAME))
    ).scalar_one_or_none()

    if existing_series is None:
        series = CostIndexSeries(
            name=_DEMO_SERIES_NAME,
            description="Construction cost index used for period-to-period escalation.",
        )
        session.add(series)
        await session.flush()
        series_added = 1
        for period, factor in _DEMO_POINTS:
            session.add(CostIndexPoint(series_id=series.id, period=period, factor=Decimal(factor)))
            points_added += 1
        await session.flush()

    existing_regions = set((await session.execute(select(LocationFactor.region_code))).scalars().all())
    regions_added = 0
    for region_code, label, factor in _DEMO_REGIONS:
        if region_code in existing_regions:
            continue
        session.add(LocationFactor(region_code=region_code, label=label, factor=Decimal(factor)))
        regions_added += 1
    if regions_added:
        await session.flush()

    return {
        "series": series_added,
        "points": points_added,
        "location_factors": regions_added,
    }


# ── Resource-index method (Russia) - SAMPLE reference data ───────────────────
#
# These rows exist so the resource-index breakdown can be tried on a fresh
# install. They are NOT the official values: the indices come from the Minstroy
# quarterly letter for the region and quarter, and the NR/SP percentages from
# Minstroy orders 812/pr and 774/pr for the type of work. Every row is flagged
# ``is_sample`` and the breakdown shows a banner whenever one is used.

SAMPLE_SOURCE_NOTE = (
    "SAMPLE for demonstration only, not an official value. Replace it with the "
    "value from the Minstroy quarterly letter for your region and quarter."
)
SAMPLE_NORM_SOURCE_NOTE = (
    "SAMPLE for demonstration only, not an official value. Replace it with the "
    "percentages Minstroy orders 812/pr (NR) and 774/pr (SP) give for this type of work."
)

SAMPLE_REGION = "RU-MOW"
SAMPLE_QUARTER = "2026-Q1"

_SAMPLE_INDICES: tuple[tuple[str, str], ...] = (
    ("labor", "1.600000"),
    ("machine", "1.300000"),
    ("operator_wages", "1.600000"),
    ("material", "1.200000"),
)

_SAMPLE_NORMS: tuple[tuple[str, str, str, str], ...] = (
    ("earthworks_machine", "Земляные работы, механизированные (earthworks by machine)", "100", "60"),
    ("concrete_cast_in_situ", "Бетонные и железобетонные монолитные конструкции (cast in-situ concrete)", "110", "65"),
    ("masonry", "Конструкции из кирпича и блоков (brick and block masonry)", "120", "70"),
    ("finishing", "Отделочные работы (finishing works)", "105", "55"),
)

#: The marker key the resource-index sample seed records once it has run.
RESOURCE_INDEX_SEED_KEY = "ru_resource_index_samples"


async def seed_resource_index_samples(session: AsyncSession) -> dict[str, int]:
    """Insert the sample resource indices and NR/SP norms, once per install.

    The first run on an install puts the samples into whichever of the two
    tables is empty and records :data:`RESOURCE_INDEX_SEED_KEY` in
    :class:`PriceIndexSeedMarker`, whether it inserted anything or not. Every
    later run finds the marker and does nothing. So a person who entered an
    official value never gets the samples next to it, and a person who deleted
    the samples (the natural first step before typing in the letter) does not
    get them back on the next restart, although the tables are empty again.

    Args:
        session: An open async session; the caller owns the transaction.

    Returns:
        Counts of the rows this call actually inserted.
    """
    indices_added = 0
    norms_added = 0

    already = (
        await session.execute(
            select(PriceIndexSeedMarker.id).where(PriceIndexSeedMarker.seed_key == RESOURCE_INDEX_SEED_KEY)
        )
    ).first()
    if already is not None:
        return {"resource_indices": 0, "overhead_norms": 0}

    has_index = (await session.execute(select(ResourceIndexValue.id).limit(1))).first() is not None
    if not has_index:
        for group, value in _SAMPLE_INDICES:
            session.add(
                ResourceIndexValue(
                    region_code=SAMPLE_REGION,
                    quarter=SAMPLE_QUARTER,
                    resource_group=group,
                    index_value=Decimal(value),
                    source=SAMPLE_SOURCE_NOTE,
                    is_sample=True,
                )
            )
            indices_added += 1

    has_norm = (await session.execute(select(WorkTypeOverheadNorm.id).limit(1))).first() is not None
    if not has_norm:
        for code, label, nr_pct, sp_pct in _SAMPLE_NORMS:
            session.add(
                WorkTypeOverheadNorm(
                    work_type_code=code,
                    label=label,
                    nr_pct=Decimal(nr_pct),
                    sp_pct=Decimal(sp_pct),
                    source=SAMPLE_NORM_SOURCE_NOTE,
                    is_sample=True,
                )
            )
            norms_added += 1

    session.add(PriceIndexSeedMarker(seed_key=RESOURCE_INDEX_SEED_KEY))
    await session.flush()
    return {"resource_indices": indices_added, "overhead_norms": norms_added}
