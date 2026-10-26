# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Position-level diff, three-way plan and grouping for estimate branches.

Pure and database-free: everything here works on :class:`LineState` values
built from ORM positions or from a snapshot blob, so the rules that decide
what a cherry-pick or a merge writes are unit-testable on plain data.

Identity across bills. A branch is a deep copy, so its positions have new ids.
``reference_code`` cannot pair them: one code may be reused on many lines of a
bill. Every position therefore carries ``metadata[LINEAGE_KEY]``, the id of the
line it descends from; a line that has none is its own lineage (its id). The
key survives snapshots, restores and further copies because they carry the
metadata blob.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

#: Metadata key holding the id of the line a position descends from.
LINEAGE_KEY = "branch_lineage"

#: Units that mark a header row when quantity and rate are both zero; the same
#: rule as ``app.modules.boq.service._is_section``.
SECTION_UNITS: tuple[str, ...] = ("", "section")

#: Fields a branch compare and a three-way plan look at, in display order.
COMPARED_FIELDS: tuple[str, ...] = ("ordinal", "description", "unit", "quantity", "unit_rate", "classification")

#: Fields that decide whether a line counts as changed for money.
_NUMERIC = ("quantity", "unit_rate")


def to_decimal(value: Any) -> Decimal:
    """Parse a stored money or quantity string; anything unreadable is zero."""
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def lineage_of(metadata: Any, fallback_id: Any) -> str:
    """The lineage key of a line: the stored key, else its own id."""
    if isinstance(metadata, Mapping):
        value = metadata.get(LINEAGE_KEY)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(fallback_id) if fallback_id is not None else ""


@dataclass(frozen=True)
class LineState:
    """One position as the diff sees it."""

    key: str
    id: str | None
    parent_key: str | None
    ordinal: str
    description: str
    unit: str
    quantity: Decimal
    unit_rate: Decimal
    total: Decimal
    classification: dict[str, Any] = field(default_factory=dict)
    sort_order: int = 0

    @property
    def is_section(self) -> bool:
        """A header row: section unit and no quantity or rate."""
        return (self.unit or "").strip().lower() in SECTION_UNITS and self.quantity == 0 and self.unit_rate == 0

    def value(self, name: str) -> Any:
        """The comparable value of a field."""
        return getattr(self, name)

    def display(self, name: str) -> Any:
        """A JSON-safe rendering of a field."""
        value = getattr(self, name)
        if isinstance(value, Decimal):
            return str(value)
        return value


def _index(raw: Iterable[dict[str, Any]]) -> dict[str, LineState]:
    """Build ``{key: LineState}`` from rows with ``id``, ``parent_id`` and ``metadata``.

    A key that occurs twice (a line copied inside one bill with its metadata)
    keeps the first line; the later one falls back to its own id so it is not
    silently merged with its twin.
    """
    rows = list(raw)
    id_to_key: dict[str, str] = {}
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("id")) if row.get("id") is not None else None
        key = lineage_of(row.get("metadata"), row_id)
        if not key or key in seen:
            key = f"id:{row_id}"
        seen.add(key)
        keys.append(key)
        if row_id:
            id_to_key[row_id] = key
    out: dict[str, LineState] = {}
    for row, key in zip(rows, keys, strict=True):
        parent = row.get("parent_id")
        classification = row.get("classification")
        out[key] = LineState(
            key=key,
            id=str(row.get("id")) if row.get("id") is not None else None,
            parent_key=id_to_key.get(str(parent)) if parent else None,
            ordinal=str(row.get("ordinal") or ""),
            description=str(row.get("description") or ""),
            unit=str(row.get("unit") or ""),
            quantity=to_decimal(row.get("quantity")),
            unit_rate=to_decimal(row.get("unit_rate")),
            total=to_decimal(row.get("total")),
            classification=dict(classification) if isinstance(classification, Mapping) else {},
            sort_order=int(row.get("sort_order") or 0),
        )
    return out


def lines_from_positions(positions: Iterable[Any]) -> dict[str, LineState]:
    """Index ORM positions (or anything with the same attributes) by lineage key."""
    return _index(
        {
            "id": p.id,
            "parent_id": p.parent_id,
            "ordinal": p.ordinal,
            "description": p.description,
            "unit": p.unit,
            "quantity": p.quantity,
            "unit_rate": p.unit_rate,
            "total": p.total,
            "classification": p.classification,
            "sort_order": p.sort_order,
            "metadata": p.metadata_,
        }
        for p in positions
    )


def lines_from_snapshot(snapshot_data: Mapping[str, Any] | None) -> dict[str, LineState]:
    """Index the positions of a ``BOQSnapshot.snapshot_data`` blob by lineage key."""
    rows = (snapshot_data or {}).get("positions") or []
    return _index(r for r in rows if isinstance(r, Mapping))


def changed_fields(a: LineState | None, b: LineState | None) -> list[str]:
    """The compared fields that differ between two states of one line."""
    if a is None or b is None:
        return [] if a is b else list(COMPARED_FIELDS)
    out = [name for name in COMPARED_FIELDS if a.value(name) != b.value(name)]
    if a.parent_key != b.parent_key:
        out.append("parent")
    return out


def same(a: LineState | None, b: LineState | None) -> bool:
    """Whether two states of a line are equal for every compared field."""
    if a is None or b is None:
        return a is None and b is None
    return not changed_fields(a, b)


# ── Compare ──────────────────────────────────────────────────────────────


def _ancestry(lines: Mapping[str, LineState], line: LineState) -> list[LineState]:
    """The line's ancestors, nearest first, guarded against cycles."""
    out: list[LineState] = []
    seen = {line.key}
    current = line.parent_key
    while current and current not in seen and current in lines:
        seen.add(current)
        parent = lines[current]
        out.append(parent)
        current = parent.parent_key
    return out


def section_of(lines: Mapping[str, LineState], line: LineState) -> tuple[str, str]:
    """``(key, label)`` of the top-level section a line sits in, or empty for loose lines."""
    chain = [p for p in _ancestry(lines, line) if p.is_section]
    if not chain:
        return "", ""
    top = chain[-1]
    label = f"{top.ordinal} {top.description}".strip()
    return top.key, label


def cost_group_of(line: LineState, standard: str | None) -> str:
    """The line's cost group code: the project's standard first, else the first code it has."""
    codes = {k: v for k, v in line.classification.items() if isinstance(v, str | int) and str(v).strip()}
    if standard and standard in codes:
        return f"{standard}:{str(codes[standard]).strip()}"
    for name in sorted(codes):
        return f"{name}:{str(codes[name]).strip()}"
    return ""


def compare_lines(
    a_lines: Mapping[str, LineState],
    b_lines: Mapping[str, LineState],
    *,
    standard: str | None = None,
) -> dict[str, Any]:
    """Position-level diff of bill A against bill B, with totals by section and cost group.

    Section headers carry no money and are left out of the rows. Every money
    figure is a string so it survives JSON without float rounding.
    """
    rows: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    total_a = Decimal("0")
    total_b = Decimal("0")
    sections: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}

    def _bucket(store: dict[str, dict[str, Any]], key: str, label: str) -> dict[str, Any]:
        if key not in store:
            store[key] = {"key": key, "label": label, "total_a": Decimal("0"), "total_b": Decimal("0")}
        return store[key]

    order = list(dict.fromkeys([*a_lines.keys(), *b_lines.keys()]))
    for key in order:
        a = a_lines.get(key)
        b = b_lines.get(key)
        ref = b or a
        assert ref is not None
        if ref.is_section and (a is None or a.is_section) and (b is None or b.is_section):
            continue
        a_total = a.total if a is not None else Decimal("0")
        b_total = b.total if b is not None else Decimal("0")
        total_a += a_total
        total_b += b_total

        if a is None:
            change_type, fields = "added", []
        elif b is None:
            change_type, fields = "removed", []
        else:
            fields = [f for f in changed_fields(a, b) if f != "parent"]
            change_type = "changed" if fields else "unchanged"
        counts[change_type] += 1

        sec_key, sec_label = section_of(b_lines if b is not None else a_lines, ref)
        group = cost_group_of(ref, standard)
        for store, bucket_key, label in ((sections, sec_key, sec_label), (groups, group, group)):
            bucket = _bucket(store, bucket_key, label)
            bucket["total_a"] += a_total
            bucket["total_b"] += b_total

        rows.append(
            {
                "key": key,
                "change_type": change_type,
                "changed_fields": fields,
                "ordinal": ref.ordinal,
                "description": ref.description,
                "unit": ref.unit,
                "a_description": a.description if a is not None else None,
                "b_description": b.description if b is not None else None,
                "a_quantity": str(a.quantity) if a is not None else None,
                "b_quantity": str(b.quantity) if b is not None else None,
                "a_unit_rate": str(a.unit_rate) if a is not None else None,
                "b_unit_rate": str(b.unit_rate) if b is not None else None,
                "a_total": str(a_total),
                "b_total": str(b_total),
                "delta": str(b_total - a_total),
                "section_key": sec_key,
                "section": sec_label,
                "cost_group": group,
            }
        )

    def _finish(store: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for bucket in store.values():
            out.append(
                {
                    "key": bucket["key"],
                    "label": bucket["label"],
                    "total_a": str(bucket["total_a"]),
                    "total_b": str(bucket["total_b"]),
                    "delta": str(bucket["total_b"] - bucket["total_a"]),
                }
            )
        return out

    delta = total_b - total_a
    percent = float(delta / total_a * 100) if total_a else 0.0
    return {
        "summary": {
            **counts,
            "total_a": str(total_a),
            "total_b": str(total_b),
            "delta": str(delta),
            "delta_percent": round(percent, 2),
        },
        "rows": rows,
        "by_section": _finish(sections),
        "by_cost_group": _finish(groups),
    }


# ── Three-way plan ───────────────────────────────────────────────────────


def _field_triplets(
    base: LineState | None, source: LineState | None, target: LineState | None
) -> dict[str, dict[str, Any]]:
    """Per changed field: what the common ancestor, the source and the target hold."""
    names = set(changed_fields(source, target)) | set(changed_fields(base, source))
    names.discard("parent")
    out: dict[str, dict[str, Any]] = {}
    for name in COMPARED_FIELDS:
        if name not in names:
            continue
        out[name] = {
            "base": base.display(name) if base is not None else None,
            "source": source.display(name) if source is not None else None,
            "target": target.display(name) if target is not None else None,
        }
    return out


def plan_apply(
    base: Mapping[str, LineState] | None,
    source: Mapping[str, LineState],
    target: Mapping[str, LineState],
    keys: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Decide, line by line, what carrying source changes into target would do.

    With a common ancestor (``base``) a line is a change of the source when it
    differs from the ancestor, and a conflict when the target changed the same
    line since the ancestor and does not already hold the source's version.
    Without one (the fork-point snapshot was deleted) every line where source
    and target differ is offered, none flagged as a conflict, and the caller
    reports the missing ancestor.

    Args:
        base: Lines of the common ancestor, or None when unknown.
        source: Lines of the bill the changes come from.
        target: Lines of the bill that receives them.
        keys: Restrict the plan to these lineage keys (a cherry-pick); None
            takes every change (a merge).

    Returns:
        One item per line with a non-noop action: ``key``, ``action``
        (``add`` | ``update`` | ``remove``), ``conflict``, ``ordinal``,
        ``description``, ``is_section``, ``parent_key``, ``depth`` and ``fields`` (base,
        source and target value of each differing field).
    """
    wanted = set(keys) if keys is not None else None
    universe = list(dict.fromkeys([*(base or {}).keys(), *source.keys(), *target.keys()]))
    items: list[dict[str, Any]] = []
    for key in universe:
        if wanted is not None and key not in wanted:
            continue
        s = source.get(key)
        t = target.get(key)
        b = base.get(key) if base is not None else None
        if base is not None and same(s, b):
            continue
        if same(s, t):
            continue
        if s is None and t is None:
            continue
        if s is None:
            action = "remove"
        elif t is None:
            action = "add"
        else:
            action = "update"
        conflict = base is not None and not same(t, b)
        ref = s or t
        assert ref is not None
        depth = len(_ancestry(source if s is not None else target, ref))
        items.append(
            {
                "key": key,
                "action": action,
                "conflict": conflict,
                "ordinal": ref.ordinal,
                "description": ref.description,
                "is_section": ref.is_section,
                "parent_key": ref.parent_key,
                "depth": depth,
                "fields": _field_triplets(b, s, t),
            }
        )
    return items


def divergence(
    base: Mapping[str, LineState] | None,
    branch: Mapping[str, LineState],
    main: Mapping[str, LineState],
) -> dict[str, Any]:
    """How far a branch and its main estimate have drifted apart since the fork.

    ``main_changes`` counts lines main changed since the fork that the branch
    does not hold; ``conflicts`` lists lines both changed, differently. Both
    are empty without a common ancestor, since then nobody can tell who moved.
    """
    if base is None:
        return {"base_known": False, "main_changes": 0, "conflicts": []}
    main_changes = 0
    conflicts: list[dict[str, Any]] = []
    for key in dict.fromkeys([*base.keys(), *branch.keys(), *main.keys()]):
        b = base.get(key)
        m = main.get(key)
        br = branch.get(key)
        if same(m, b) or same(m, br):
            continue
        main_changes += 1
        if not same(br, b):
            ref = br or m or b
            assert ref is not None
            conflicts.append({"key": key, "ordinal": ref.ordinal, "description": ref.description})
    return {"base_known": True, "main_changes": main_changes, "conflicts": conflicts}
