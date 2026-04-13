"""Requirement vector adapter​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — feeds the ``oe_requirements`` collection.

Each :class:`~app.modules.requirements.models.Requirement` row is
embedded as the EAC triplet (entity / attribute / constraint) plus the
unit, category, priority and any free-form notes.  The result is upserted
into the multi-collection vector store via the helpers in
:mod:`app.core.vector_index`.

Why this matters
================

Requirements are the bridge between client intent and the executed
project — semantically searching them lets the AI advisor answer
questions like *"are there any requirements about fire-rating on
exterior walls?"* and the global Cmd+Shift+K modal lets estimators find
the original constraint a BOQ position is meant to satisfy.

The same adapter is also reused by the cross-module "Similar items"
panel — when a user opens a requirement detail, they get a one-click
list of related requirements pulled from past projects.

Implements the :class:`~app.core.vector_index.EmbeddingAdapter` protocol.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_REQUIREMENTS
from app.modules.requirements.models import Requirement


class RequirementVectorAdapter:
    """Embed requirements into the unified vector store."""

    collection_name: str = COLLECTION_REQUIREMENTS
    module_name: str = "requirements"

    def to_text(self, row: Requirement) -> str:
        """Build the canonical text that gets embedded.

        Concatenates the EAC triplet, unit, category, priority, status
        and free-form notes — all the textual fields the user might
        plausibly search by.  Format is " | "-separated key=value pairs
        which the multilingual model handles well.
        """
        parts: list[str] = []
        if row.entity:
            parts.append(f"entity={row.entity}")
        if row.attribute:
            parts.append(f"attribute={row.attribute}")
        # The constraint triple is the heart of the requirement.
        if row.constraint_type and row.constraint_value:
            parts.append(f"{row.constraint_type} {row.constraint_value}")
        elif row.constraint_value:
            parts.append(row.constraint_value)
        if row.unit:
            parts.append(f"unit={row.unit}")
        if row.category:
            parts.append(f"category={row.category}")
        if row.priority:
            parts.append(f"priority={row.priority}")
        if row.status:
            parts.append(f"status={row.status}")
        if row.notes:
            # Notes are free-form prose — kept verbatim because that's
            # often where the most semantically rich content lives.
            parts.append(row.notes.strip())
        # Embed a sample of pinned BIM element ids so semantic search
        # like "requirements linked to roof elements" can route from a
        # selected element back to the requirements that pin it.  We
        # cap the sample at 5 because the vector store payload budget
        # is tight and the full id list lives in metadata_ anyway.
        meta = getattr(row, "metadata_", None) or {}
        bim_ids = meta.get("bim_element_ids") if isinstance(meta, dict) else None
        if isinstance(bim_ids, list) and bim_ids:
            sample = ",".join(str(x) for x in bim_ids[:5] if x)
            if sample:
                parts.append(f"bim_element_ids={sample}")
        return " | ".join(p for p in parts if p)

    def to_payload(self, row: Requirement) -> dict[str, Any]:
        """Light metadata returned with every search hit so the UI can
        render a row card without an extra Postgres roundtrip."""
        title_parts = [row.entity or "", row.attribute or ""]
        title = ".".join(p for p in title_parts if p) or "requirement"
        constraint = (
            f"{row.constraint_type} {row.constraint_value}".strip()
            if row.constraint_type and row.constraint_value
            else (row.constraint_value or "")
        )
        return {
            "title": title[:160],
            "constraint": constraint[:160],
            "unit": row.unit or "",
            "category": row.category or "",
            "priority": row.priority or "",
            "status": row.status or "",
            "requirement_set_id": str(row.requirement_set_id)
            if row.requirement_set_id
            else "",
            "linked_position_id": str(row.linked_position_id)
            if row.linked_position_id
            else "",
        }

    def project_id_of(self, row: Requirement) -> str | None:
        """Resolve the owning project id via the parent RequirementSet.

        Returns ``None`` if the requirement isn't attached to a set yet
        (should never happen in practice — defensive coding).
        """
        rs = getattr(row, "requirement_set", None)
        if rs is not None and getattr(rs, "project_id", None):
            return str(rs.project_id)
        return None


# Singleton instance — adapters are stateless so one shared object is fine.
requirement_vector_adapter = RequirementVectorAdapter()
