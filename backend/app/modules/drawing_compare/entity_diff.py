# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Entity-level diff of two DWG/DXF revisions.

Works on the entity records the CAD converter already stores for every
drawing version (``{entity_type, layer, geometry_data}``). Entities carry no
handle that survives a re-export, so identity is geometric:

1. **Unchanged** - same type, same layer and the same geometry once every
   coordinate is snapped to the tolerance grid.
2. **Modified** - left over on both sides with the same type and layer and an
   anchor (start point, insert point, centre) within the match radius: a text
   whose value changed, a line whose far end moved, a circle resized.
3. **Added / removed** - whatever is left on one side only.

Changed entities are then merged into regions (nearby boxes form one region)
so the change list reads "the stair core changed", not "41 lines changed".
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.drawing_compare.geometry import Rect, merge_rects, points_of, rect_from_points, union_of

# Text-bearing entities: their value is what an estimator reads off the sheet.
_TEXT_TYPES = frozenset({"TEXT", "MTEXT", "DIMENSION", "ATTRIB"})
# Presentation-only keys that never make an entity "different".
_IGNORED_KEYS = frozenset({"font", "style", "color"})
# Per region, how many entity rows are kept for the report.
MAX_ENTITIES_PER_REGION = 50
MAX_REGIONS = 500


@dataclass
class _Ent:
    index: int
    entity_type: str
    layer: str
    signature: str
    anchor: tuple[float, float] | None
    box: Rect | None
    text: str | None


@dataclass
class EntityChange:
    """One entity that differs between the revisions."""

    change: str  # added | removed | modified
    entity_type: str
    layer: str
    box: Rect | None
    old_text: str | None = None
    new_text: str | None = None
    old_index: int | None = None
    new_index: int | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"change": self.change, "entity_type": self.entity_type, "layer": self.layer}
        if self.box is not None:
            out["bbox"] = [self.box.x, self.box.y, self.box.w, self.box.h]
        if self.old_text is not None or self.new_text is not None:
            out["old_text"] = self.old_text
            out["new_text"] = self.new_text
        return out


@dataclass
class EntityDiffResult:
    """Outcome of :func:`diff_entities`."""

    changes: list[EntityChange] = field(default_factory=list)
    unchanged: int = 0
    old_total: int = 0
    new_total: int = 0
    tolerance: float = 0.0

    def counts(self) -> dict[str, int]:
        c = Counter(ch.change for ch in self.changes)
        return {"added": c["added"], "removed": c["removed"], "modified": c["modified"], "unchanged": self.unchanged}

    def by_layer(self) -> list[dict[str, Any]]:
        """Per layer and entity type, how many were added, removed, modified."""
        table: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for ch in self.changes:
            table[(ch.layer, ch.entity_type)][ch.change] += 1
        return [
            {
                "layer": layer,
                "entity_type": etype,
                "added": cnt["added"],
                "removed": cnt["removed"],
                "modified": cnt["modified"],
            }
            for (layer, etype), cnt in sorted(table.items())
        ]


def _quantize(value: Any, q: float) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        return round(float(value) / q)
    if isinstance(value, dict):
        return {k: _quantize(v, q) for k, v in value.items() if k not in _IGNORED_KEYS}
    if isinstance(value, (list, tuple)):
        return [_quantize(v, q) for v in value]
    return str(value)


def _text_of(entity_type: str, geometry: dict[str, Any]) -> str | None:
    if entity_type not in _TEXT_TYPES:
        return None
    for key in ("text", "text_override", "value"):
        val = geometry.get(key)
        if isinstance(val, str):
            return val
    return None


def _prepare(records: Sequence[Any], q: float) -> list[_Ent]:
    out: list[_Ent] = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict) or not rec.get("entity_type"):
            continue
        etype = str(rec.get("entity_type")).upper()
        layer = str(rec.get("layer") or "0")
        geometry = rec.get("geometry_data") if isinstance(rec.get("geometry_data"), dict) else {}
        assert isinstance(geometry, dict)  # noqa: S101 - narrowed above
        pts = points_of(geometry)
        sig = json.dumps(_quantize(geometry, q), sort_keys=True, separators=(",", ":"), default=str)
        out.append(
            _Ent(
                index=i,
                entity_type=etype,
                layer=layer,
                signature=f"{etype}|{layer}|{sig}",
                anchor=pts[0] if pts else None,
                box=rect_from_points(pts),
                text=_text_of(etype, geometry),
            )
        )
    return out


def drawing_extent(*record_lists: Sequence[Any]) -> Rect | None:
    """Union box of every entity on both revisions."""
    boxes: list[Rect] = []
    for records in record_lists:
        for rec in records:
            if isinstance(rec, dict) and isinstance(rec.get("geometry_data"), dict):
                box = rect_from_points(points_of(rec["geometry_data"]))
                if box is not None:
                    boxes.append(box)
    return union_of(boxes)


def diff_entities(
    old_records: Sequence[Any],
    new_records: Sequence[Any],
    *,
    tolerance: float | None = None,
    match_radius: float | None = None,
) -> EntityDiffResult:
    """Diff two entity lists; see the module docstring for the three passes.

    ``tolerance`` defaults to a millionth of the drawing diagonal (export
    round-off), ``match_radius`` to half a percent of it.
    """
    extent = drawing_extent(old_records, new_records)
    diag = math.hypot(extent.w, extent.h) if extent is not None else 1.0
    diag = diag if diag > 0 else 1.0
    q = tolerance if tolerance and tolerance > 0 else max(diag * 1e-6, 1e-9)
    radius = match_radius if match_radius and match_radius > 0 else diag * 0.005

    old = _prepare(old_records, q)
    new = _prepare(new_records, q)
    result = EntityDiffResult(old_total=len(old), new_total=len(new), tolerance=q)

    # Pass 1: exact signature, as a multiset so duplicated entities pair off one by one.
    by_sig: dict[str, list[_Ent]] = defaultdict(list)
    for ent in old:
        by_sig[ent.signature].append(ent)
    new_left: list[_Ent] = []
    for ent in new:
        bucket = by_sig.get(ent.signature)
        if bucket:
            bucket.pop()
            result.unchanged += 1
        else:
            new_left.append(ent)
    old_left = [e for bucket in by_sig.values() for e in bucket]
    old_left.sort(key=lambda e: e.index)

    # Pass 2: same type and layer, nearest anchor inside the radius.
    cell = radius if radius > 0 else 1.0
    grid: dict[tuple[str, str, int, int], list[_Ent]] = defaultdict(list)
    for ent in old_left:
        if ent.anchor is not None:
            key = (ent.entity_type, ent.layer, int(ent.anchor[0] // cell), int(ent.anchor[1] // cell))
            grid[key].append(ent)
    matched_old: set[int] = set()
    added: list[_Ent] = []
    for ent in new_left:
        best: _Ent | None = None
        best_d = radius
        if ent.anchor is not None:
            gx, gy = int(ent.anchor[0] // cell), int(ent.anchor[1] // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for cand in grid.get((ent.entity_type, ent.layer, gx + dx, gy + dy), ()):
                        if cand.index in matched_old or cand.anchor is None:
                            continue
                        d = math.hypot(cand.anchor[0] - ent.anchor[0], cand.anchor[1] - ent.anchor[1])
                        if d <= best_d:
                            best, best_d = cand, d
        if best is None:
            added.append(ent)
            continue
        matched_old.add(best.index)
        box = best.box.union(ent.box) if best.box is not None and ent.box is not None else (ent.box or best.box)
        result.changes.append(
            EntityChange(
                change="modified",
                entity_type=ent.entity_type,
                layer=ent.layer,
                box=box,
                old_text=best.text,
                new_text=ent.text,
                old_index=best.index,
                new_index=ent.index,
            )
        )
    for ent in added:
        result.changes.append(
            EntityChange(
                change="added",
                entity_type=ent.entity_type,
                layer=ent.layer,
                box=ent.box,
                new_text=ent.text,
                new_index=ent.index,
            )
        )
    for ent in old_left:
        if ent.index in matched_old:
            continue
        result.changes.append(
            EntityChange(
                change="removed",
                entity_type=ent.entity_type,
                layer=ent.layer,
                box=ent.box,
                old_text=ent.text,
                old_index=ent.index,
            )
        )
    return result


@dataclass
class EntityRegion:
    """A cluster of changed entities shown as one row in the change list."""

    kind: str  # added | removed | modified | text
    box: Rect
    layer: str
    entity_type: str
    counts: dict[str, int]
    layers: list[str]
    entities: list[dict[str, Any]]
    old_text: str | None = None
    new_text: str | None = None
    members: list[EntityChange] = field(default_factory=list)


def cluster_entity_changes(
    changes: Sequence[EntityChange],
    *,
    gap: float,
    min_size: float = 0.0,
) -> list[EntityRegion]:
    """Merge changed entities whose boxes lie within ``gap`` into regions.

    A region made only of added entities reads ``added``, only removed
    ``removed``; one holding a single changed text reads ``text`` so a revised
    dimension or note stands out; anything else is ``modified``. Entities
    without geometry are dropped (nothing to point at on the sheet).
    """
    located = [c for c in changes if c.box is not None]
    boxes = [c.box for c in located if c.box is not None]
    regions: list[EntityRegion] = []
    for group in merge_rects(boxes, gap=gap):
        members = [located[i] for i in group]
        box = union_of(m.box for m in members if m.box is not None)
        assert box is not None  # noqa: S101 - every member is located
        if min_size > 0 and box.w < min_size and box.h < min_size:
            pad = (min_size - min(box.w, box.h)) / 2
            box = box.expanded(pad)
        kinds = Counter(m.change for m in members)
        layers = Counter(m.layer for m in members)
        types = Counter(m.entity_type for m in members)
        text_members = [
            m for m in members if m.change == "modified" and (m.old_text is not None or m.new_text is not None)
        ]
        if len(members) == 1 and text_members and text_members[0].old_text != text_members[0].new_text:
            kind = "text"
        elif set(kinds) == {"added"}:
            kind = "added"
        elif set(kinds) == {"removed"}:
            kind = "removed"
        else:
            kind = "modified"
        text_src = text_members[0] if text_members else None
        regions.append(
            EntityRegion(
                kind=kind,
                box=box,
                layer=layers.most_common(1)[0][0],
                entity_type=types.most_common(1)[0][0],
                counts={"added": kinds["added"], "removed": kinds["removed"], "modified": kinds["modified"]},
                layers=sorted(layers),
                entities=[m.as_dict() for m in members[:MAX_ENTITIES_PER_REGION]],
                old_text=text_src.old_text if text_src else None,
                new_text=text_src.new_text if text_src else None,
                members=members,
            )
        )
    regions.sort(key=lambda r: (-(r.counts["added"] + r.counts["removed"] + r.counts["modified"]), r.box.y, r.box.x))
    return regions[:MAX_REGIONS]
