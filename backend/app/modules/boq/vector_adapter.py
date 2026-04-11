"""BOQ position vector adapter — feeds the ``oe_boq_positions`` collection.

Each :class:`~app.modules.boq.models.Position` row is embedded as the
description plus its unit and any classification codes.  The result is
upserted into the multi-collection vector store via the helpers in
:mod:`app.core.vector_index`.

The adapter is intentionally narrow — it knows nothing about the event
bus or HTTP routing.  Wiring lives in :mod:`app.modules.boq.events` and
``router.py`` respectively.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_BOQ
from app.modules.boq.models import Position


class BOQPositionAdapter:
    """Embed BOQ positions into the unified vector store."""

    collection_name: str = COLLECTION_BOQ
    module_name: str = "boq"

    def to_text(self, row: Position) -> str:
        """Build the canonical text that gets embedded.

        Concatenates the description, unit and any classification code
        values (DIN 276 / NRM / MasterFormat / etc.) so that semantic
        queries like *"reinforced concrete walls 240mm"* match positions
        regardless of which classification standard the project uses.
        """
        parts: list[str] = []
        if row.description:
            parts.append(row.description.strip())
        if row.ordinal:
            parts.append(f"[{row.ordinal}]")
        if row.unit:
            parts.append(row.unit)
        classification = getattr(row, "classification", None) or {}
        if isinstance(classification, dict):
            for key, value in classification.items():
                if value is None or value == "":
                    continue
                parts.append(f"{key}={value}")
        # Optional cost-code / WBS hints — useful for cross-project recall.
        if getattr(row, "cost_code_id", None):
            parts.append(f"cost_code={row.cost_code_id}")
        if getattr(row, "wbs_id", None):
            parts.append(f"wbs={row.wbs_id}")
        return " | ".join(p for p in parts if p)

    def to_payload(self, row: Position) -> dict[str, Any]:
        """Light metadata returned with every search hit so the UI can
        render a row card without an extra Postgres roundtrip."""
        return {
            "title": (row.description or "")[:160],
            "ordinal": row.ordinal or "",
            "unit": row.unit or "",
            "boq_id": str(row.boq_id) if row.boq_id else "",
            "classification": dict(getattr(row, "classification", {}) or {}),
            "validation_status": getattr(row, "validation_status", "") or "",
            "source": getattr(row, "source", "") or "",
        }

    def project_id_of(self, row: Position) -> str | None:
        """Resolve the owning project id via the parent BOQ.

        Returns ``None`` if the position is detached from a BOQ (should
        never happen in practice but defensive coding pays off).
        """
        boq = getattr(row, "boq", None)
        if boq is not None and getattr(boq, "project_id", None):
            return str(boq.project_id)
        return None


# Singleton instance — adapters are stateless so one shared object is fine.
boq_position_adapter = BOQPositionAdapter()
