#!/usr/bin/env python3
"""
Extract catalog resources from USA_TENNESSEE cost items.

This script directly uses the backend catalog service to extract
region-specific resources from Tennessee cost items.

Usage: cd backend && python -m app.scripts.extract_tennessee_catalog
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    """Extract catalog resources from USA_TENNESSEE cost items."""
    from app.database import Base, async_session_factory, engine
    from app.modules.catalog.service import CatalogResourceService

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("=" * 60)
    print("  TENNESSEE CATALOG EXTRACTION")
    print("=" * 60)

    async with async_session_factory() as session:
        service = CatalogResourceService(session)

        region = "USA_TENNESSEE"
        print(f"\nExtracting catalog resources for region: {region}")

        try:
            counts = await service.import_region_from_costs(region)
            await session.commit()
            total = sum(counts.values())

            print(f"\n{'=' * 60}")
            print("  EXTRACTION COMPLETE")
            print(f"{'=' * 60}")
            print(f"  Total resources extracted: {total}")
            for resource_type, count in counts.items():
                print(f"    {resource_type:12s}: {count:>3d}")
            print(f"{'=' * 60}")

        except Exception as exc:
            await session.rollback()
            print(f"\n  Error: {exc}")
            raise


if __name__ == "__main__":
    asyncio.run(main())
