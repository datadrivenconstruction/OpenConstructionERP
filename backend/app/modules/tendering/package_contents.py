# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a tender package asks for, and what it is budgeted at.

A package is raised over lines of a bill. Two things narrow it further:

* a **resource scope**: the cost components (labour, material, plant, ...) of
  each line the subcontractor is asked to price. A contractor that buys the
  long-lead materials itself sends the fixing out alone; the owner-supplied
  rows of a line are left out of the package budget and named to the bidder;
* a **budget override**: a figure the buyer enters by hand. The computed sum
  stays visible next to it, so the two can always be compared.

Both live in the package ``metadata_`` (``resource_scope``, ``budget_override``)
and every reader of the package budget (comparison, levelling, award record,
preview) goes through :func:`scoped_line` and :func:`package_budget`, so the
number a bid is measured against is the same everywhere.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.price_breakdown import coerce_kind
from app.modules.price_breakdown.model import ResourceKind

#: Every cost kind a scope may name, in display order.
SCOPE_KINDS: tuple[str, ...] = tuple(k.value for k in ResourceKind)

#: Metadata keys of the package.
SCOPE_KEY = "resource_scope"
OVERRIDE_KEY = "budget_override"

_ZERO = Decimal("0")


def _dec(value: Any) -> Decimal:
    """A finite Decimal out of a stored value, 0 when it cannot be read."""
    if value is None or isinstance(value, bool) or value == "":
        return _ZERO
    try:
        out = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return _ZERO
    return out if out.is_finite() else _ZERO


def position_metadata(position: Any) -> Mapping[str, Any]:
    """The metadata dict of an ORM position or of its API schema."""
    raw = getattr(position, "metadata_", None)
    if isinstance(raw, Mapping):
        return raw
    raw = getattr(position, "metadata", None)
    return raw if isinstance(raw, Mapping) else {}


def component_key(kind: str, code: str | None, name: str, unit: str) -> str:
    """A short stable id of one resource row, from what it is and not where it sits."""
    identity = "\x1f".join((kind, (code or "").strip().lower(), name.strip().lower(), unit.strip().lower()))
    return hashlib.sha1(identity.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


@dataclass(frozen=True)
class ResourceScope:
    """The cost kinds a package covers, and the rows taken out line by line."""

    kinds: frozenset[str]
    excluded: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def includes(self, position_id: str, kind: str, key: str) -> bool:
        return kind in self.kinds and key not in self.excluded.get(position_id, frozenset())


def read_scope(metadata: Mapping[str, Any] | None) -> ResourceScope | None:
    """The package's resource scope, or None when it covers whole lines."""
    raw = (metadata or {}).get(SCOPE_KEY)
    if not isinstance(raw, Mapping):
        return None
    kinds = frozenset(str(k) for k in raw.get("kinds") or [] if str(k) in SCOPE_KINDS)
    excluded_raw = raw.get("excluded") if isinstance(raw.get("excluded"), Mapping) else {}
    excluded = {
        str(pid): frozenset(str(k) for k in keys)
        for pid, keys in excluded_raw.items()
        if isinstance(keys, list | tuple) and keys
    }
    if kinds == frozenset(SCOPE_KINDS) and not excluded:
        return None
    return ResourceScope(kinds=kinds, excluded=excluded)


def scope_to_metadata(kinds: Iterable[str], excluded: Mapping[str, Iterable[str]]) -> dict[str, Any] | None:
    """The stored form of a scope; None when it is the whole line (nothing to store)."""
    kept = [k for k in SCOPE_KINDS if k in set(kinds)]
    cleaned = {str(pid): sorted({str(k) for k in keys}) for pid, keys in excluded.items()}
    cleaned = {pid: keys for pid, keys in cleaned.items() if keys}
    if len(kept) == len(SCOPE_KINDS) and not cleaned:
        return None
    return {"kinds": kept, "excluded": cleaned}


def read_override(metadata: Mapping[str, Any] | None) -> Decimal | None:
    """The budget the buyer entered by hand, or None."""
    raw = (metadata or {}).get(OVERRIDE_KEY)
    if raw in (None, ""):
        return None
    value = _dec(raw)
    return value if value >= 0 else None


@dataclass
class LineComponent:
    """One resource row of a line, costed per unit of the line."""

    key: str
    name: str
    code: str | None
    kind: str
    unit: str
    quantity: Decimal
    unit_cost: Decimal
    included: bool

    @property
    def cost(self) -> Decimal:
        return self.quantity * self.unit_cost


def line_components(position: Any, scope: ResourceScope | None) -> list[LineComponent]:
    """The resource rows of a line, each marked in or out of the package."""
    rows = position_metadata(position).get("resources")
    if not isinstance(rows, list):
        return []
    pid = str(getattr(position, "id", ""))
    out: list[LineComponent] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        kind = coerce_kind(row.get("type") or row.get("resource_type") or row.get("kind")).value
        code = str(row.get("code") or "").strip() or None
        unit = str(row.get("unit") or "").strip()
        quantity = _dec(row.get("quantity"))
        unit_cost = _dec(row.get("unit_rate"))
        if row.get("total") not in (None, "") and quantity != 0:
            # A stored row total is the authority on the row's cost per line unit.
            unit_cost = _dec(row.get("total")) / quantity
        key = component_key(kind, code, name, unit)
        out.append(
            LineComponent(
                key=key,
                name=name,
                code=code,
                kind=kind,
                unit=unit,
                quantity=quantity,
                unit_cost=unit_cost,
                included=scope is None or scope.includes(pid, kind, key),
            )
        )
    return out


def base_line(position: Any) -> tuple[Decimal, Decimal]:
    """(unit rate, total) of a line as the bill prices it."""
    qty = _dec(getattr(position, "quantity", None))
    rate = _dec(getattr(position, "unit_rate", None))
    total = getattr(position, "total", None)
    return rate, (_dec(total) if total not in (None, "", 0, "0") else qty * rate)


@dataclass
class ScopedLine:
    """A line's budget inside the package."""

    unit_rate: Decimal
    total: Decimal
    #: True when the scope took part of the line's components out.
    split: bool = False
    #: True when the scope names kinds but the line has no components to split.
    unsplittable: bool = False
    components: list[LineComponent] = field(default_factory=list)


def scoped_line(position: Any, scope: ResourceScope | None) -> ScopedLine:
    """The share of a line's budget the package covers.

    The bill's rate is scaled by the included components' share of the
    component cost, so markups and currency conversion already folded into the
    rate stay in proportion. A line without priced components cannot be split
    and is budgeted in full; ``unsplittable`` says so.
    """
    rate, total = base_line(position)
    components = line_components(position, scope)
    if scope is None:
        return ScopedLine(rate, total, components=components)
    all_cost = sum((c.cost for c in components), _ZERO)
    if not components or all_cost <= 0:
        return ScopedLine(rate, total, unsplittable=True, components=components)
    included = sum((c.cost for c in components if c.included), _ZERO)
    if included == all_cost:
        return ScopedLine(rate, total, components=components)
    share = included / all_cost
    return ScopedLine(rate * share, total * share, split=True, components=components)


@dataclass
class PackageBudget:
    """The computed budget, the hand-entered one, and the one in force."""

    computed: Decimal
    override: Decimal | None

    @property
    def effective(self) -> Decimal:
        return self.override if self.override is not None else self.computed


def package_budget(positions: Iterable[Any], metadata: Mapping[str, Any] | None) -> PackageBudget:
    """Sum the in-scope lines of a package (provisional lines without total left out)."""
    from app.modules.boq.gaeb_common import is_excluded_from_total

    scope = read_scope(metadata)
    computed = _ZERO
    for position in positions:
        if is_excluded_from_total(position):
            continue
        computed += scoped_line(position, scope).total
    return PackageBudget(computed=computed, override=read_override(metadata))
