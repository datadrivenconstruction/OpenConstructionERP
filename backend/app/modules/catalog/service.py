"""Catalog resource service — business logic for resource catalog management.

Stateless service layer. Handles:
- Resource CRUD
- Search with filters
- Extraction from cost item components
- Statistics
"""

import logging
import uuid
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.catalog.models import CatalogResource
from app.modules.catalog.repository import CatalogResourceRepository
from app.modules.catalog.schemas import (
    CatalogCategoryStat,
    CatalogResourceCreate,
    CatalogSearchQuery,
    CatalogStatsResponse,
    CatalogTypeStat,
)
from app.modules.costs.models import CostItem

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


def _categorize_material(name: str) -> str:
    """Categorize a material resource by name keywords."""
    name_lower = name.lower()
    for keywords, category in MATERIAL_CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return category
    return "General"


def _categorize_equipment(name: str) -> str:
    """Categorize an equipment resource by name keywords."""
    name_lower = name.lower()
    for keywords, category in EQUIPMENT_CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return category
    return "General Equipment"


def _categorize_resource(resource_type: str, name: str) -> str:
    """Categorize a resource based on its type and name."""
    if resource_type == "material":
        return _categorize_material(name)
    if resource_type == "equipment":
        return _categorize_equipment(name)
    if resource_type == "labor":
        return "Labor"
    if resource_type == "operator":
        return "Operators"
    return "General"


class CatalogResourceService:
    """Business logic for catalog resource operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CatalogResourceRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_resource(self, data: CatalogResourceCreate) -> CatalogResource:
        """Create a new catalog resource.

        Raises HTTPException 409 if resource_code already exists.
        """
        existing = await self.repo.get_by_code(data.resource_code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Catalog resource with code '{data.resource_code}' already exists",
            )

        resource = CatalogResource(
            resource_code=data.resource_code,
            name=data.name,
            resource_type=data.resource_type,
            category=data.category,
            unit=data.unit,
            base_price=str(data.base_price),
            min_price=str(data.min_price),
            max_price=str(data.max_price),
            currency=data.currency,
            usage_count=0,
            source=data.source,
            region=data.region,
            specifications=data.specifications,
            metadata_=data.metadata,
        )
        resource = await self.repo.create(resource)

        await _safe_publish(
            "catalog.resource.created",
            {"resource_id": str(resource.id), "code": resource.resource_code},
            source_module="oe_catalog",
        )

        logger.info("Catalog resource created: %s (%s)", resource.resource_code, resource.name)
        return resource

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_resource(self, resource_id: uuid.UUID) -> CatalogResource:
        """Get catalog resource by ID. Raises 404 if not found."""
        resource = await self.repo.get_by_id(resource_id)
        if resource is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Catalog resource not found",
            )
        return resource

    async def search_resources(self, query: CatalogSearchQuery) -> tuple[list[CatalogResource], int]:
        """Search catalog resources with filters and pagination."""
        return await self.repo.search(
            q=query.q,
            resource_type=query.resource_type,
            category=query.category,
            region=query.region,
            unit=query.unit,
            min_price=query.min_price,
            max_price=query.max_price,
            offset=query.offset,
            limit=query.limit,
        )

    async def get_stats(self) -> CatalogStatsResponse:
        """Get aggregated statistics for the catalog."""
        total = await self.repo.count()
        by_type_raw = await self.repo.stats_by_type()
        by_category_raw = await self.repo.stats_by_category()

        return CatalogStatsResponse(
            total=total,
            by_type=[CatalogTypeStat(resource_type=rt, count=c) for rt, c in by_type_raw],
            by_category=[CatalogCategoryStat(category=cat, count=c) for cat, c in by_category_raw],
        )

    # ── Regions ─────────────────────────────────────────────────────────

    async def get_loaded_regions(self) -> list[str]:
        """Return distinct region identifiers that have catalog resources."""
        from sqlalchemy import distinct

        stmt = (
            select(distinct(CatalogResource.region))
            .where(CatalogResource.is_active.is_(True))
            .where(CatalogResource.region.isnot(None))
            .where(CatalogResource.region != "")
        )
        result = await self.session.execute(stmt)
        regions = [row[0] for row in result.all()]
        regions.sort()
        return regions

    async def get_region_stats(self) -> list[dict[str, object]]:
        """Return resource count per loaded region."""
        return await self.repo.stats_by_region()

    async def delete_region(self, region: str) -> int:
        """Delete all catalog resources for a given region."""
        count = await self.repo.delete_by_region(region)
        await _safe_publish(
            "catalog.region.deleted",
            {"region": region, "deleted": count},
            source_module="oe_catalog",
        )
        logger.info("Deleted catalog region %s: %d resources removed", region, count)
        return count

    async def import_region_from_costs(self, region: str) -> dict[str, int]:
        """Import catalog resources from cost item components for a specific region.

        Extracts materials, equipment, labor, and operators from cost items
        that belong to the given region. Replaces any existing catalog data
        for that region.

        Returns:
            Dict with counts by resource_type.
        """
        # Clear existing catalog entries for this region
        await self.repo.delete_by_region(region)

        # Query cost items for this region
        stmt = select(CostItem).where(CostItem.is_active.is_(True)).where(CostItem.region == region)
        result = await self.session.execute(stmt)
        cost_items = list(result.scalars().all())

        if not cost_items:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No cost items found for region '{region}'. "
                f"Import the cost database first via /v1/costs/load-cwicr/{region}",
            )

        # Determine currency from first cost item
        currency = "EUR"
        first_item = cost_items[0]
        if hasattr(first_item, "currency") and first_item.currency:
            currency = first_item.currency

        # Aggregate components by (code, type)
        component_data: dict[str, dict] = {}

        for item in cost_items:
            components = item.components or []
            for comp in components:
                code = comp.get("code", "")
                if not code:
                    continue

                comp_type = comp.get("type", "other")
                if comp_type not in ("material", "equipment", "labor", "operator"):
                    continue

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

        # Create catalog resources (no limit per type for region import)
        resources_to_create: list[CatalogResource] = []
        counts: dict[str, int] = defaultdict(int)

        for comp_data in component_data.values():
            rates = comp_data["rates"]
            if not rates:
                continue

            avg_rate = sum(rates) / len(rates)
            min_rate = min(rates)
            max_rate = max(rates)

            comp_type = comp_data["type"]
            category = _categorize_resource(comp_type, comp_data["name"])
            resource_code = f"CAT-{region}-{comp_type[:3].upper()}-{comp_data['code']}"

            resource = CatalogResource(
                resource_code=resource_code,
                name=comp_data["name"],
                resource_type=comp_type,
                category=category,
                unit=comp_data["unit"],
                base_price=f"{avg_rate:.2f}",
                min_price=f"{min_rate:.2f}",
                max_price=f"{max_rate:.2f}",
                currency=currency,
                usage_count=comp_data["count"],
                source="cost_import",
                region=region,
                specifications={
                    "sample_count": len(rates),
                    "original_code": comp_data["code"],
                },
                metadata_={},
            )
            resources_to_create.append(resource)
            counts[comp_type] += 1

        if resources_to_create:
            await self.repo.bulk_create(resources_to_create)

        await _safe_publish(
            "catalog.region.imported",
            {
                "region": region,
                "total": len(resources_to_create),
                "by_type": dict(counts),
            },
            source_module="oe_catalog",
        )

        logger.info(
            "Catalog region import for %s: %d resources (%s)",
            region,
            len(resources_to_create),
            dict(counts),
        )
        return dict(counts)

    # ── Extract from cost items ──────────────────────────────────────────

    async def extract_from_cost_items(self) -> dict[str, int]:
        """Extract top 100 resources from cost item components.

        Aggregates components across all active cost items, computes
        avg/min/max rates, categorizes, and inserts the top 100 into
        the catalog.

        Returns:
            Dict with counts by resource_type.
        """
        # Soft-delete previously extracted resources
        await self.repo.delete_by_source("cwicr_extraction")

        # Query all active cost items with components
        stmt = select(CostItem).where(CostItem.is_active.is_(True))
        result = await self.session.execute(stmt)
        cost_items = list(result.scalars().all())

        # Aggregate components by (code, type)
        component_data: dict[str, dict] = {}

        for item in cost_items:
            components = item.components or []
            for comp in components:
                code = comp.get("code", "")
                if not code:
                    continue

                comp_type = comp.get("type", "other")
                if comp_type not in ("material", "equipment", "labor", "operator"):
                    continue

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

        # Sort by usage count and select top items per type
        type_limits = {
            "material": 50,
            "equipment": 30,
            "labor": 10,
            "operator": 10,
        }

        resources_to_create: list[CatalogResource] = []
        counts: dict[str, int] = defaultdict(int)

        for resource_type, limit in type_limits.items():
            typed_components = [v for v in component_data.values() if v["type"] == resource_type]
            typed_components.sort(key=lambda x: x["count"], reverse=True)

            for comp in typed_components[:limit]:
                rates = comp["rates"]
                avg_rate = sum(rates) / len(rates) if rates else 0
                min_rate = min(rates) if rates else 0
                max_rate = max(rates) if rates else 0

                category = _categorize_resource(resource_type, comp["name"])
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
                resources_to_create.append(resource)
                counts[resource_type] += 1

        if resources_to_create:
            await self.repo.bulk_create(resources_to_create)

        await _safe_publish(
            "catalog.resources.extracted",
            {
                "total": len(resources_to_create),
                "by_type": dict(counts),
            },
            source_module="oe_catalog",
        )

        logger.info(
            "Catalog extraction complete: %d resources (%s)",
            len(resources_to_create),
            dict(counts),
        )
        return dict(counts)
