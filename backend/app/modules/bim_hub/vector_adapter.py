"""BIM element vector adapter — feeds the ``oe_bim_elements`` collection.

Each :class:`~app.modules.bim_hub.models.BIMElement` row is embedded as
its display name plus element type, category, discipline, storey,
material and any classification / family metadata stored in
``properties``.  The resulting canonical text is upserted into the
multi-collection vector store via the helpers in
:mod:`app.core.vector_index`.

The adapter is intentionally narrow — it knows nothing about the event
bus or HTTP routing.  Wiring lives in :mod:`app.modules.bim_hub.events`
and ``router.py`` respectively.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_BIM_ELEMENTS
from app.modules.bim_hub.models import BIMElement


class BIMElementVectorAdapter:
    """Embed BIM elements into the unified vector store."""

    collection_name: str = COLLECTION_BIM_ELEMENTS
    module_name: str = "bim_elements"

    def to_text(self, row: BIMElement) -> str:
        """Build the canonical text that gets embedded.

        Concatenates the element's name, type, category, discipline,
        storey, material plus any classification codes and Revit
        family/type hints so that semantic queries like
        *"exterior concrete wall 240mm"* match elements regardless of
        which BIM authoring tool they came from.
        """
        parts: list[str] = []
        if row.name:
            parts.append(row.name.strip())
        if row.element_type:
            parts.append(row.element_type)
        category = getattr(row, "category", None)
        if category:
            parts.append(str(category))
        if row.discipline:
            parts.append(row.discipline)
        if row.storey:
            parts.append(f"storey={row.storey}")

        properties = getattr(row, "properties", None) or {}
        if isinstance(properties, dict):
            material = (
                properties.get("material")
                or properties.get("Material")
                or properties.get("material_name")
            )
            if material:
                parts.append(f"material={material}")

            family = properties.get("family") or properties.get("Family")
            if family:
                parts.append(f"family={family}")
            family_type = (
                properties.get("type")
                or properties.get("Type")
                or properties.get("family_type")
            )
            if family_type:
                parts.append(f"type={family_type}")

            classification = (
                properties.get("classification")
                or properties.get("Classification")
            )
            if isinstance(classification, dict):
                for key, value in classification.items():
                    if value is None or value == "":
                        continue
                    parts.append(f"{key}={value}")
            elif classification:
                parts.append(f"classification={classification}")

        return " | ".join(p for p in parts if p)

    def to_payload(self, row: BIMElement) -> dict[str, Any]:
        """Light metadata returned with every search hit so the UI can
        render an element card without an extra Postgres roundtrip."""
        title_source = row.name or row.element_type or str(getattr(row, "id", ""))
        return {
            "title": (title_source or "")[:160],
            "element_type": row.element_type or "",
            "category": getattr(row, "category", "") or "",
            "discipline": getattr(row, "discipline", "") or "",
            "storey": getattr(row, "storey", "") or "",
            "model_id": str(row.model_id) if getattr(row, "model_id", None) else "",
        }

    def project_id_of(self, row: BIMElement) -> str | None:
        """Resolve the owning project id via the parent BIMModel.

        Only works when the caller has eager-loaded the ``model``
        relationship — otherwise returns ``None`` and lets the router /
        event handler populate ``project_id`` explicitly.
        """
        model = getattr(row, "model", None)
        if model is not None and getattr(model, "project_id", None):
            return str(model.project_id)
        return None


# Singleton instance — adapters are stateless so one shared object is fine.
bim_element_vector_adapter = BIMElementVectorAdapter()
