"""Persist scraped PriceRecords to the database — idempotent upsert with provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.acap.scraper.base import PriceRecord


async def persist_prices(
    session: AsyncSession,
    region_code: str,
    records: list[PriceRecord],
    source_url_map: dict[str, str] | None = None,
    scraped_at: datetime | None = None,
) -> int:
    """Upsert ``PriceRecord``\ s into the database, keyed on (region, source, type, name).

    * Get-or-create the ``Region`` row by *region_code*.
    * For each record, upsert ``MaterialPrice`` by the natural key.
    * Running twice yields identical row counts (idempotent).

    Returns the number of distinct ``MaterialPrice`` rows after the seed.
    """
    from sqlalchemy import select

    from app.modules.acap.models.prices import MaterialPrice, Region

    if scraped_at is None:
        scraped_at = datetime.now(UTC)

    # ── Get or create region ──────────────────────────────────────────
    stmt = select(Region).where(Region.code == region_code)
    result = await session.execute(stmt)
    region = result.scalar_one_or_none()

    if region is None:
        # Hard-coded Batam region data (D2 — Batam only)
        region_map: dict[str, tuple[str, str | None]] = {
            "BATAM": ("Batam", "Kepulauan Riau"),
        }
        name, province = region_map.get(region_code, (region_code, None))
        region = Region(code=region_code, name=name, province=province)
        session.add(region)
        await session.flush()

    # ── Upsert each record ────────────────────────────────────────────
    count = 0
    for rec in records:
        stmt = select(MaterialPrice).where(
            MaterialPrice.region_id == region.id,
            MaterialPrice.source == rec.source,
            MaterialPrice.item_type == rec.item_type,
            MaterialPrice.item_name == rec.item_name,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            session.add(
                MaterialPrice(
                    region_id=region.id,
                    source=rec.source,
                    source_url=rec.source_url,
                    item_type=rec.item_type,
                    item_name=rec.item_name,
                    satuan=rec.satuan,
                    price_min=rec.price_min,
                    price_max=rec.price_max,
                    extraction_method=rec.extraction_method,
                    scraped_at=scraped_at,
                )
            )
        else:
            existing.source_url = rec.source_url
            existing.satuan = rec.satuan
            existing.price_min = rec.price_min
            existing.price_max = rec.price_max
            existing.extraction_method = rec.extraction_method
            existing.scraped_at = scraped_at

        count += 1

    await session.commit()
    return count
