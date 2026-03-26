"""Seed catalog: extract top 100 resources from CWICR cost item components.

Reads all cost items, aggregates their components by code/type, computes
avg/min/max rates, categorizes, and inserts the top 100 into oe_catalog_resource.

Usage: cd backend && python -m app.scripts.seed_catalog
"""

import asyncio
import logging
import sys
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Categorization maps ──────────────────────────────────────────────────

MATERIAL_CATEGORIES: list[tuple[list[str], str]] = [
    (["concrete", "cement"], "Concrete & Cement"),
    (["steel", "metal", "bolt", "nail"], "Steel & Metal"),
    (["weld", "electrode"], "Welding"),
    (["wood", "timber", "plywood"], "Wood & Timber"),
    (["pipe", "valve"], "Pipes & Fittings"),
    (["paint", "primer", "varnish"], "Paint & Finish"),
    (["cable", "wire"], "Electrical"),
    (["sand", "gravel", "crushed"], "Aggregates"),
    (["oxygen", "acetylene", "propane"], "Chemicals"),
    (["water"], "Water"),
]

EQUIPMENT_CATEGORIES: list[tuple[list[str], str]] = [
    (["crane"], "Cranes"),
    (["truck", "flatbed"], "Trucks"),
    (["excavator"], "Excavators"),
    (["bulldozer"], "Bulldozers"),
    (["weld"], "Welding Equipment"),
    (["winch", "hoist"], "Hoists & Winches"),
    (["compressor"], "Compressors"),
    (["pump"], "Pumps"),
]


def categorize_material(name: str) -> str:
    """Categorize a material resource by name keywords."""
    name_lower = name.lower()
    for keywords, category in MATERIAL_CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return category
    return "General"


def categorize_equipment(name: str) -> str:
    """Categorize an equipment resource by name keywords."""
    name_lower = name.lower()
    for keywords, category in EQUIPMENT_CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return category
    return "General Equipment"


def categorize_resource(resource_type: str, name: str) -> str:
    """Categorize a resource based on its type and name."""
    if resource_type == "material":
        return categorize_material(name)
    if resource_type == "equipment":
        return categorize_equipment(name)
    if resource_type == "labor":
        return "Labor"
    if resource_type == "operator":
        return "Operators"
    return "General"


async def main() -> None:
    """Extract top 100 resources from cost item components."""
    from sqlalchemy import select

    from app.database import Base, async_session_factory, engine
    from app.modules.catalog.models import CatalogResource
    from app.modules.costs.models import CostItem

    # Ensure tables exist (SQLite dev mode)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("=" * 70)
    print("  CATALOG SEED — Extract top 100 resources from CWICR components")
    print("=" * 70)

    async with async_session_factory() as session:
        # 1. Query all active cost items
        stmt = select(CostItem).where(CostItem.is_active.is_(True))
        result = await session.execute(stmt)
        cost_items = list(result.scalars().all())
        print(f"\nFound {len(cost_items)} active cost items")

        if not cost_items:
            print("No cost items found. Run cost database import first.")
            print("  e.g.: python -m app.scripts.seed_demo")
            return

        # 2. Aggregate components by (code, type)
        component_data: dict[str, dict] = {}
        total_components = 0

        for item in cost_items:
            components = item.components or []
            for comp in components:
                code = comp.get("code", "")
                if not code:
                    continue

                comp_type = comp.get("type", "other")
                if comp_type not in ("material", "equipment", "labor", "operator"):
                    continue

                total_components += 1
                key = f"{comp_type}:{code}"
                rate = float(comp.get("unit_rate", 0) or 0)

                if key not in component_data:
                    component_data[key] = {
                        "code": code,
                        "name": comp.get("name", code),
                        "type": comp_type,
                        "unit": comp.get("unit", "unit"),
                        "rates": [],
                        "count": 0,
                    }

                component_data[key]["rates"].append(rate)
                component_data[key]["count"] += 1

        print(f"Found {total_components} total component references")
        print(f"Found {len(component_data)} unique components")

        # 3. Sort by usage count and select top items per type
        type_limits = {
            "material": 50,
            "equipment": 30,
            "labor": 10,
            "operator": 10,
        }

        # Clean up previously extracted resources
        del_stmt = select(CatalogResource).where(
            CatalogResource.source == "cwicr_extraction"
        )
        old_result = await session.execute(del_stmt)
        old_resources = list(old_result.scalars().all())
        for old_res in old_resources:
            await session.delete(old_res)
        if old_resources:
            print(f"\nRemoved {len(old_resources)} previously extracted resources")

        # 4. Create resources
        resources_created: list[CatalogResource] = []
        counts: dict[str, int] = defaultdict(int)

        for resource_type, limit in type_limits.items():
            typed_components = [
                v for v in component_data.values() if v["type"] == resource_type
            ]
            typed_components.sort(key=lambda x: x["count"], reverse=True)

            print(f"\n{'─' * 50}")
            print(f"  {resource_type.upper()} (top {limit} of {len(typed_components)} found)")
            print(f"{'─' * 50}")

            for comp in typed_components[:limit]:
                rates = comp["rates"]
                avg_rate = sum(rates) / len(rates) if rates else 0.0
                min_rate = min(rates) if rates else 0.0
                max_rate = max(rates) if rates else 0.0
                category = categorize_resource(resource_type, comp["name"])
                resource_code = f"CAT-{resource_type[:3].upper()}-{comp['code']}"

                resource = CatalogResource(
                    resource_code=resource_code,
                    name=comp["name"],
                    resource_type=resource_type,
                    category=category,
                    unit=comp["unit"],
                    base_price=f"{avg_rate:.2f}",
                    min_price=f"{min_rate:.2f}",
                    max_price=f"{max_rate:.2f}",
                    currency="EUR",
                    usage_count=comp["count"],
                    source="cwicr_extraction",
                    specifications={
                        "sample_count": len(rates),
                        "original_code": comp["code"],
                    },
                    metadata_={},
                )
                session.add(resource)
                resources_created.append(resource)
                counts[resource_type] += 1

                print(
                    f"  {resource_code:30s} | {comp['name'][:35]:35s} | "
                    f"{category:20s} | {comp['unit']:5s} | "
                    f"avg {avg_rate:>8.2f} | "
                    f"uses: {comp['count']:>4d}"
                )

        await session.commit()

        # 5. Print summary
        total = sum(counts.values())
        print(f"\n{'=' * 70}")
        print(f"  SUMMARY")
        print(f"{'=' * 70}")
        print(f"  Total resources created: {total}")
        for rt, c in counts.items():
            print(f"    {rt:12s}: {c:>3d}")
        print(f"{'=' * 70}")

        if total == 0:
            print("\nNo components found in cost items.")
            print("Make sure cost items have 'components' with 'code', 'type', and 'unit_rate'.")
            print("Run: python -m app.scripts.seed_demo  (for demo data)")


if __name__ == "__main__":
    asyncio.run(main())
