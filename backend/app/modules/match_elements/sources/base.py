# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍SourceAdapter — uniform read interface across BIM/DWG/PDF/photo.

Each adapter loads source-specific elements (BIMElement rows, DWG
session entries, PDF measurements, etc.) and yields :class:`SourceElement`
records that the service then groups, matches and applies to BOQ.

The shape is intentionally minimal so adding the next source is a
single-file affair. Quantities are a free-form dict because each source
has different "natural" measurements (BIM has volume/area/length, PDF
has area/length/count, photo CV has count/area).
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol


class SourceElement:
    """‌⁠‍A single estimable element from any source.

    Lightweight DTO — not a Pydantic model — because we instantiate
    these by the millions (200K-element Revit models are a thing) and
    pydantic validation overhead matters.
    """

    __slots__ = (
        "id",
        "category",
        "name",
        "attributes",
        "quantities",
        "raw_ref",
    )

    def __init__(
        self,
        *,
        id: str,
        category: str,
        name: str | None,
        attributes: dict[str, Any],
        quantities: dict[str, float],
        raw_ref: str | None = None,
    ) -> None:
        self.id = id
        self.category = category
        self.name = name
        self.attributes = attributes
        self.quantities = quantities
        # Source-native reference (model_id, drawing_id, page_id, ...).
        self.raw_ref = raw_ref


class SourceAdapter(Protocol):
    """‌⁠‍Protocol every source adapter implements."""

    source_name: str  # 'bim' | 'dwg' | 'pdf' | 'photo'

    async def list_attribute_keys(
        self,
        project_id: uuid.UUID,
    ) -> list[str]:
        """Return all attributes available for group-by on this project.

        e.g. for BIM: ``["ifc_class", "type_name", "level", "material",
        "thickness_mm", ...]``. The frontend chip-bar renders these as
        drag-source chips.
        """
        ...

    async def list_categories(
        self,
        project_id: uuid.UUID,
    ) -> list[tuple[str, int]]:
        """Return ``[(category_name, element_count), ...]`` for the
        scope-filter chip-bar (include/exclude IfcCategory).
        """
        ...

    async def iter_elements(
        self,
        *,
        project_id: uuid.UUID,
        filters: dict[str, list[Any]] | None = None,
        excluded_categories: list[str] | None = None,
        use_net_quantities: bool = True,
    ) -> list[SourceElement]:
        """Load all elements matching the filters / scope-exclusion.

        ``use_net_quantities`` only matters for BIM where openings can be
        deducted from gross volumes. Other sources ignore it.
        """
        ...
