# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Roll a CVR report up the project's WBS tree, parent by parent.

A report filled from the cost spine holds one line per WBS element it found
cost on. A commercial manager reads the CVR top down: the whole job, then a
section, then the element that went wrong. This module folds the report's own
lines into the WBS hierarchy without inventing a figure:

* a node's ``own`` figures are the sum of the lines booked directly to it;
* a node's ``total`` figures are ``own`` plus the totals of its children;
* lines whose WBS element is missing (no WBS, or an element since deleted) land
  in ``unallocated``, so the roots plus ``unallocated`` equal the report.

Every node carries the ids of its own lines and the count of lines and bill
positions beneath it, so each figure is traceable to the rows it came from.
:func:`reconciliation_rows` produces the payload the ``cvr.wbs_rollup_reconciles``
rule checks. Pure: plain values in, plain values out.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.cvr.compute import q2, to_decimal

ZERO = Decimal("0")

#: Figures summed up the tree, in the order the screen shows them.
ROLLUP_FIELDS: tuple[str, ...] = (
    "budget_cost",
    "committed_cost",
    "cost_to_date",
    "value_to_date",
    "forecast_cost",
    "forecast_value",
)


@dataclass(frozen=True)
class WbsNodeRef:
    """One WBS element as the tree needs it."""

    id: str
    parent_id: str | None
    code: str
    name: str
    sort_order: int = 0


@dataclass
class RollupNode:
    """A WBS element with the report figures booked to it and beneath it."""

    id: str
    parent_id: str | None
    code: str
    name: str
    sort_order: int = 0
    depth: int = 0
    own: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(ROLLUP_FIELDS, ZERO))
    total: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(ROLLUP_FIELDS, ZERO))
    line_ids: list[str] = field(default_factory=list)
    line_count: int = 0
    positions: int = 0
    children: list[RollupNode] = field(default_factory=list)

    @property
    def margin_to_date(self) -> Decimal:
        return self.total["value_to_date"] - self.total["cost_to_date"]

    @property
    def forecast_margin(self) -> Decimal:
        return self.total["forecast_value"] - self.total["forecast_cost"]


@dataclass
class WbsRollup:
    """The folded tree: roots in WBS order, unallocated lines, report totals."""

    roots: list[RollupNode]
    unallocated: RollupNode
    totals: dict[str, Decimal]

    def walk(self) -> Iterable[RollupNode]:
        """Every node, depth first, parents before children."""
        stack = list(reversed(self.roots))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))


def _line_positions(line: Any) -> int:
    meta = getattr(line, "metadata_", None) or {}
    try:
        return max(int(meta.get("positions") or 0), 0)
    except (TypeError, ValueError):
        return 0


def build_rollup(nodes: Iterable[WbsNodeRef], lines: Iterable[Any]) -> WbsRollup:
    """Fold report lines into the WBS tree.

    A parent that is not in ``nodes``, or a parent chain that loops back on
    itself, makes the element a root: a broken tree still shows every figure.
    """
    by_id: dict[str, RollupNode] = {
        n.id: RollupNode(id=n.id, parent_id=n.parent_id, code=n.code, name=n.name, sort_order=n.sort_order)
        for n in nodes
    }

    def chain_reaches_root(node_id: str) -> bool:
        seen: set[str] = set()
        current: str | None = node_id
        while current is not None:
            if current in seen:
                return False
            seen.add(current)
            parent = by_id[current].parent_id
            current = parent if parent in by_id else None
        return True

    roots: list[RollupNode] = []
    for node in by_id.values():
        parent = node.parent_id
        if parent in by_id and parent != node.id and chain_reaches_root(node.id):
            by_id[parent].children.append(node)
        else:
            node.parent_id = None
            roots.append(node)

    unallocated = RollupNode(id="", parent_id=None, code="", name="")
    totals = dict.fromkeys(ROLLUP_FIELDS, ZERO)
    for line in lines:
        key = str(getattr(line, "wbs_id", None) or "")
        target = by_id.get(key, unallocated)
        for name in ROLLUP_FIELDS:
            amount = to_decimal(getattr(line, name, 0) or 0)
            target.own[name] += amount
            totals[name] += amount
        target.line_ids.append(str(getattr(line, "id", "") or ""))
        target.positions += _line_positions(line)
    unallocated.total = dict(unallocated.own)
    unallocated.line_count = len(unallocated.line_ids)

    def order(items: list[RollupNode]) -> None:
        items.sort(key=lambda n: (n.sort_order, n.code, n.id))

    def finish(node: RollupNode, depth: int) -> None:
        node.depth = depth
        order(node.children)
        node.total = dict(node.own)
        node.line_count = len(node.line_ids)
        for child in node.children:
            finish(child, depth + 1)
            for name in ROLLUP_FIELDS:
                node.total[name] += child.total[name]
            node.line_count += child.line_count
            node.positions += child.positions

    order(roots)
    for root in roots:
        finish(root, 0)
    return WbsRollup(roots=roots, unallocated=unallocated, totals=totals)


def _money(values: dict[str, Decimal]) -> dict[str, str]:
    return {k: str(q2(v)) for k, v in values.items()}


def reconciliation_rows(rollup: WbsRollup) -> list[dict[str, Any]]:
    """Payload rows for ``cvr.wbs_rollup_reconciles``.

    One row per parent (its total against own plus children) and one row for the
    report (its line totals against the roots plus unallocated).
    """
    rows: list[dict[str, Any]] = []
    for node in rollup.walk():
        if not node.children:
            continue
        rows.append(
            {
                "id": node.id,
                "label": f"{node.code} {node.name}".strip(),
                "total": _money(node.total),
                "parts": [_money(node.own), *(_money(c.total) for c in node.children)],
            }
        )
    rows.append(
        {
            "id": "report",
            "label": "report",
            "total": _money(rollup.totals),
            "parts": [_money(rollup.unallocated.total), *(_money(r.total) for r in rollup.roots)],
        }
    )
    return rows


def figures(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """The six rolled figures plus both margins and the forecast margin percentage, to the cent."""
    out = {k: q2(values[k]) for k in ROLLUP_FIELDS}
    margin = values["forecast_value"] - values["forecast_cost"]
    out["margin_to_date"] = q2(values["value_to_date"] - values["cost_to_date"])
    out["forecast_margin"] = q2(margin)
    base = values["forecast_value"]
    out["forecast_margin_pct"] = q2(margin / base * Decimal("100")) if base > 0 else ZERO
    return out


def node_payload(node: RollupNode) -> dict[str, Any]:
    """A node as the response schema reads it."""
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "code": node.code,
        "name": node.name,
        "depth": node.depth,
        "child_count": len(node.children),
        "line_ids": list(node.line_ids),
        "line_count": node.line_count,
        "positions": node.positions,
        "own": figures(node.own),
        "total": figures(node.total),
    }
