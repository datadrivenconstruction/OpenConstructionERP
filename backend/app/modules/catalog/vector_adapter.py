"""Resource catalogue vector adapter - feeds the ``oe_catalog_resources`` collection.

Resources are shared reference data, so rows carry no tenant or project.
Embedding is optional: without a vector store the catalogue search stays SQL only.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_CATALOG_RESOURCES
from app.modules.catalog.models import CatalogResource


class CatalogResourceAdapter:
    """Embed catalogue resources into the unified vector store."""

    collection_name: str = COLLECTION_CATALOG_RESOURCES
    module_name: str = "catalog"

    def to_text(self, row: CatalogResource) -> str:
        parts = [row.name, row.resource_type, row.category, row.unit, row.resource_code]
        return " | ".join(str(p).strip() for p in parts if p and str(p).strip())

    def to_payload(self, row: CatalogResource) -> dict[str, Any]:
        return {
            "resource_code": row.resource_code or "",
            "resource_type": row.resource_type or "",
            "category": row.category or "",
            "region": row.region or "",
        }

    def project_id_of(self, row: CatalogResource) -> str | None:
        return None


catalog_resource_adapter = CatalogResourceAdapter()
