# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebuild a bill's tree from one level per row, in document order.

A bill pasted or imported flat carries its chapter lines as ordinary
positions. The estimator marks each row with a level (0 = position,
n = section of level n) and the tree is rebuilt from document order: a
section hangs under the nearest open section of a lower level, a position
under the deepest open section. Pure, no database access.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

CONVERTED_KEY = "converted_from_position"


@dataclass(frozen=True)
class PlannedRow:
    """Where one row lands after restructuring."""

    position_id: uuid.UUID
    parent_id: uuid.UUID | None
    is_section: bool
    sort_order: int


def plan_restructure(rows: Sequence[tuple[uuid.UUID, int]], max_depth: int) -> list[PlannedRow]:
    """Turn ``(id, level)`` pairs in document order into parent links.

    Args:
        rows: Every row of the bill in document order with its level.
        max_depth: Deepest section nesting allowed.

    Returns:
        One :class:`PlannedRow` per input row, in the same order.

    Raises:
        ValueError: A level is negative, an id repeats, or the nesting
            would exceed ``max_depth``.
    """
    seen: set[uuid.UUID] = set()
    stack: list[tuple[int, uuid.UUID]] = []
    planned: list[PlannedRow] = []
    for index, (pid, level) in enumerate(rows):
        if pid in seen:
            raise ValueError(f"Position {pid} is listed twice.")
        seen.add(pid)
        if level < 0:
            raise ValueError(f"Level of position {pid} must be 0 or more.")
        if level == 0:
            parent = stack[-1][1] if stack else None
            planned.append(PlannedRow(pid, parent, False, index))
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        if len(stack) >= max_depth:
            raise ValueError(f"Section nesting deeper than {max_depth} levels.")
        parent = stack[-1][1] if stack else None
        stack.append((level, pid))
        planned.append(PlannedRow(pid, parent, True, index))
    return planned


def to_section_fields(row: Any) -> dict[str, Any]:
    """Fields that turn a priced position into a section header.

    The figures are kept under ``metadata.converted_from_position`` so the
    conversion can be undone without retyping them.
    """
    metadata = dict(row.metadata_ or {})
    metadata[CONVERTED_KEY] = {
        "unit": row.unit,
        "quantity": row.quantity,
        "unit_rate": row.unit_rate,
        "total": row.total,
        "resources": metadata.pop("resources", None),
    }
    return {"unit": "section", "quantity": "0", "unit_rate": "0", "total": "0", "metadata_": metadata}


def to_position_fields(row: Any) -> dict[str, Any]:
    """Fields that turn a section header back into a position.

    A header that was a position before gets its figures back; any other
    becomes an unpriced lump sum the estimator fills in.
    """
    metadata = dict(row.metadata_ or {})
    before = metadata.pop(CONVERTED_KEY, None)
    if isinstance(before, dict):
        resources = before.get("resources")
        if resources is not None:
            metadata["resources"] = resources
        return {
            "unit": before.get("unit") or "lsum",
            "quantity": str(before.get("quantity") or "0"),
            "unit_rate": str(before.get("unit_rate") or "0"),
            "total": str(before.get("total") or "0"),
            "metadata_": metadata,
        }
    return {"unit": "lsum", "quantity": "0", "unit_rate": "0", "total": "0", "metadata_": metadata}
