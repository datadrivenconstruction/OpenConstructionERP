# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Pure aggregation of an estimate's resource demand into a procurement statement.

Every priced position stores a resource split under
``Position.metadata_["resources"]`` - a list of
``{type, name, unit, quantity, unit_rate, total, currency}`` dicts written when a
position is edited and when an assembly is applied. Each resource ``quantity`` and
``unit_rate`` is expressed *per one unit of the position*: the platform invariant
is ``position.unit_rate == sum(r.quantity * r.unit_rate)`` (see
``app.modules.boq.service._resource_total_in_base`` and the assembly apply path).
The whole-position demand for a resource is therefore ``r.quantity * position.quantity``
and its cost ``r.quantity * r.unit_rate * position.quantity``.

This module rolls that demand up across every position of the estimate and groups
it by ``(kind, name, unit)`` so a buyer sees one procurement-ready schedule: how
many labour-hours, how much of each material, machine and subcontract line, and at
what cost. It is a pure, ``Decimal``-exact library with no ORM or database
dependency, so it is trivially unit-tested from plain dicts.

Money is reported to 2 decimal places and quantities to 4, matching the rest of the
platform. Resource lines priced in a foreign currency are converted to the project
base currency via an optional ``fx_rates`` map (units of base per one foreign unit),
mirroring ``_resource_total_in_base``: a missing rate leaves the line in its own
units rather than zeroing it, so the rollup is deterministic and never silently
drops a cost.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.boq.supplier_suggestion import effective_suggestion
from app.modules.price_breakdown import ResourceKind, coerce_kind, kind_i18n_key

_2P = Decimal("0.01")
_4P = Decimal("0.0001")

# Display order of the categories in the statement, most labour-driven to least.
# Kept stable so a saved snapshot and a live run always line up row for row.
KIND_ORDER: tuple[ResourceKind, ...] = (
    ResourceKind.LABOUR,
    ResourceKind.MATERIAL,
    ResourceKind.MACHINERY,
    ResourceKind.EQUIPMENT,
    ResourceKind.SUBCONTRACT,
    ResourceKind.OTHER,
)

# English default labels per category. These are defaults only; the response also
# carries the stable ``price_breakdown.kind.<value>`` i18n key so a frontend can
# translate the heading without any shared locale file being edited here.
KIND_LABELS: dict[ResourceKind, str] = {
    ResourceKind.LABOUR: "Labour",
    ResourceKind.MATERIAL: "Material",
    ResourceKind.MACHINERY: "Machinery",
    ResourceKind.EQUIPMENT: "Equipment",
    ResourceKind.SUBCONTRACT: "Subcontract",
    ResourceKind.OTHER: "Other",
}


def _dec(value: Any, default: str = "0") -> Decimal:
    """Coerce an arbitrary value to a finite ``Decimal``, never raising."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else Decimal(default)
    if value is None or value == "":
        return Decimal(default)
    try:
        out = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(default)
    return out if out.is_finite() else Decimal(default)


def _q(value: Decimal, quant: Decimal) -> str:
    return str(_dec(value).quantize(quant, rounding=ROUND_HALF_UP))


@dataclass
class ResourceLine:
    """One aggregated procurement line: a distinct resource across the estimate."""

    kind: ResourceKind
    name: str
    unit: str
    quantity: Decimal
    cost: Decimal
    position_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "kind_i18n_key": kind_i18n_key(self.kind),
            "name": self.name,
            "unit": self.unit,
            "quantity": _q(self.quantity, _4P),
            "cost": _q(self.cost, _2P),
            "position_count": self.position_count,
        }


@dataclass
class ResourceKindGroup:
    """All aggregated lines of one category, plus the category totals."""

    kind: ResourceKind
    lines: list[ResourceLine] = field(default_factory=list)

    @property
    def label(self) -> str:
        return KIND_LABELS[self.kind]

    @property
    def total_cost(self) -> Decimal:
        return sum((line.cost for line in self.lines), Decimal("0"))

    @property
    def total_quantity(self) -> Decimal:
        """Sum of line quantities. Meaningful for labour (hours); mixed units of a
        material category are not summed here - each material line keeps its own
        unit and quantity."""
        return sum((line.quantity for line in self.lines), Decimal("0"))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind.value,
            "kind_i18n_key": kind_i18n_key(self.kind),
            "label": self.label,
            "line_count": len(self.lines),
            "total_cost": _q(self.total_cost, _2P),
            "lines": [line.to_dict() for line in self.lines],
        }
        # Labour hours are the one cross-line quantity a buyer reads as a single
        # figure (the platform prices labour per hour), so expose it on the group.
        if self.kind is ResourceKind.LABOUR:
            out["total_hours"] = _q(self.total_quantity, _4P)
        return out


@dataclass
class ResourceStatement:
    """The whole procurement statement: ordered category groups plus grand totals."""

    currency: str
    groups: list[ResourceKindGroup] = field(default_factory=list)
    position_count: int = 0

    @property
    def total_cost(self) -> Decimal:
        return sum((group.total_cost for group in self.groups), Decimal("0"))

    @property
    def labor_hours(self) -> Decimal:
        for group in self.groups:
            if group.kind is ResourceKind.LABOUR:
                return group.total_quantity
        return Decimal("0")

    @property
    def line_count(self) -> int:
        return sum(len(group.lines) for group in self.groups)

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "position_count": self.position_count,
            "line_count": self.line_count,
            "labor_hours": _q(self.labor_hours, _4P),
            "total_cost": _q(self.total_cost, _2P),
            "groups": [group.to_dict() for group in self.groups],
        }


def _line_cost_per_unit(res: Mapping[str, Any]) -> Decimal:
    """Per-position-unit cost contribution of one resource line.

    Prefers ``quantity * unit_rate`` when both are present so the figure self-heals
    after an inline edit that changed the factors but left a stale ``total`` behind
    (same rule as ``boq.service.get_cost_breakdown``); falls back to the stored
    ``total`` only when a factor is missing.
    """
    qty = res.get("quantity")
    rate = res.get("unit_rate")
    if qty is not None and rate is not None:
        return _dec(qty) * _dec(rate)
    return _dec(res.get("total"))


def aggregate_resource_statement(
    positions: Iterable[Mapping[str, Any]],
    *,
    currency: str = "",
    fx_rates: Mapping[str, str] | None = None,
) -> ResourceStatement:
    """Aggregate stored per-position resource splits into a procurement statement.

    Args:
        positions: BoQ position dicts. Each is read for ``quantity`` and its
            ``metadata_["resources"]`` (``metadata`` is also accepted) split; an
            optional ``id`` is used only to count distinct contributing positions.
        currency: Project base currency label for the statement. When empty, the
            first resource currency seen is used so the response still carries a
            code the UI can format.
        fx_rates: Optional ``{code: rate}`` map (base units per one foreign unit)
            used to convert a resource line priced in a foreign currency. A missing
            rate leaves the line in its own units (deterministic, never zeroed).

    Returns:
        A :class:`ResourceStatement` with category groups ordered by
        :data:`KIND_ORDER` and, within each, lines sorted by descending cost.
    """
    base = (currency or "").strip().upper()
    fx = {str(k).strip().upper(): v for k, v in (fx_rates or {}).items()}
    first_currency = ""

    # (kind, name_lower, unit_lower) -> accumulator
    groups: dict[tuple[ResourceKind, str, str], dict[str, Any]] = {}
    contributing: set[str] = set()
    anon = 0

    for position in positions:
        meta = position.get("metadata_") or position.get("metadata") or {}
        resources = meta.get("resources") if isinstance(meta, Mapping) else None
        if not isinstance(resources, list) or not resources:
            continue
        pos_qty = _dec(position.get("quantity"), "0")
        pos_id = str(position.get("id") or "")
        if not pos_id:
            pos_id = f"__anon_{anon}"
            anon += 1
        contributed = False

        for res in resources:
            if not isinstance(res, Mapping):
                continue
            kind = coerce_kind(res.get("type") or res.get("resource_type") or res.get("kind"))
            name = str(res.get("name") or res.get("description") or res.get("code") or "").strip() or "-"
            unit = str(res.get("unit") or "").strip()

            res_currency = str(res.get("currency") or "").strip().upper()
            if res_currency and not first_currency:
                first_currency = res_currency

            per_unit_cost = _line_cost_per_unit(res)
            # Convert a foreign-priced line into the base currency before summing.
            if res_currency and base and res_currency != base:
                rate = fx.get(res_currency)
                if rate is not None:
                    rate_dec = _dec(rate)
                    if rate_dec.is_finite() and rate_dec > 0:
                        per_unit_cost = per_unit_cost * rate_dec

            line_qty = _dec(res.get("quantity"), "0") * pos_qty
            line_cost = per_unit_cost * pos_qty

            key = (kind, name.lower(), unit.lower())
            acc = groups.get(key)
            if acc is None:
                acc = {"name": name, "unit": unit, "quantity": Decimal("0"), "cost": Decimal("0"), "positions": set()}
                groups[key] = acc
            acc["quantity"] += line_qty
            acc["cost"] += line_cost
            acc["positions"].add(pos_id)
            contributed = True

        if contributed:
            contributing.add(pos_id)

    by_kind: dict[ResourceKind, list[ResourceLine]] = {kind: [] for kind in KIND_ORDER}
    for (kind, _name_lower, _unit_lower), acc in groups.items():
        by_kind.setdefault(kind, []).append(
            ResourceLine(
                kind=kind,
                name=acc["name"],
                unit=acc["unit"],
                quantity=acc["quantity"],
                cost=acc["cost"],
                position_count=len(acc["positions"]),
            )
        )

    ordered_groups: list[ResourceKindGroup] = []
    for kind in KIND_ORDER:
        lines = by_kind.get(kind) or []
        if not lines:
            continue
        # Highest-cost lines first, then name for a stable, readable order.
        lines.sort(key=lambda line: (-line.cost, line.name.lower()))
        ordered_groups.append(ResourceKindGroup(kind=kind, lines=lines))

    return ResourceStatement(
        currency=base or first_currency or "",
        groups=ordered_groups,
        position_count=len(contributing),
    )


@dataclass
class BuyListSource:
    """One BOQ resource line that contributes to a buy-list row.

    ``resource_key`` names the resource within its position's split: the
    resource's own ``id`` when it carries one, otherwise its index in the split
    and its ``code`` (``"2:CWICR-123"``), or the index alone. ``quantity`` is
    the gross purchase quantity this one line contributes, in ``unit`` as the
    source states it, so a requisition raised from the row can keep both.
    ``suggested_vendor_id`` is the supplier the estimator suggested for the
    resource, or the position default, with ``suggested_vendor_origin`` saying
    which; sources of one row may suggest different suppliers.
    """

    position_id: str
    resource_key: str
    quantity: Decimal
    unit: str
    code: str = ""
    catalog_item_id: str | None = None
    suggested_vendor_id: str | None = None
    suggested_vendor_origin: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggested_vendor_id": self.suggested_vendor_id,
            "suggested_vendor_origin": self.suggested_vendor_origin,
            "position_id": self.position_id,
            "resource_key": self.resource_key,
            "quantity": _q(self.quantity, _4P),
            "unit": self.unit,
            "code": self.code,
            "catalog_item_id": self.catalog_item_id,
        }


def _resource_key(res: Mapping[str, Any], index: int) -> str:
    """A reference to one resource within a position's resource split."""
    own = str(res.get("id") or "").strip()
    if own:
        return own
    code = str(res.get("code") or "").strip()
    return f"{index}:{code}" if code else str(index)


@dataclass
class BuyListItem:
    """One material purchase line: a distinct material to procure across the estimate.

    ``sources`` lists every BOQ resource line folded into the row. The row
    itself groups by name and unit, which is a reading aid and not a material
    identity, so the sources are what a requisition raised from it must carry.
    """

    name: str
    unit: str
    quantity: Decimal
    cost: Decimal
    position_count: int
    sources: list[BuyListSource] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "quantity": _q(self.quantity, _4P),
            "cost": _q(self.cost, _2P),
            "position_count": self.position_count,
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass
class MaterialBuyList:
    """A procurement buy-list: one order line per distinct material, plus totals."""

    currency: str
    items: list[BuyListItem] = field(default_factory=list)
    position_count: int = 0

    @property
    def total_cost(self) -> Decimal:
        return sum((item.cost for item in self.items), Decimal("0"))

    @property
    def item_count(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "item_count": self.item_count,
            "position_count": self.position_count,
            "total_cost": _q(self.total_cost, _2P),
            "items": [item.to_dict() for item in self.items],
        }


def _line_gross_quantity_per_unit(res: Mapping[str, Any]) -> Decimal:
    """Per-position-unit *gross* (purchased) quantity of one resource line.

    The stored ``quantity`` is the net (installed) coefficient. A material may
    carry a ``waste_pct`` written by the norm-expansion / assembly material path
    (``gross = net * (1 + waste_pct/100)``); it lives in the line's nested
    ``metadata`` but a top-level key is also honoured. Grossing up from the live
    ``quantity`` rather than a stored absolute ``gross_qty`` keeps the figure
    self-healing after an inline quantity edit, and applies the very factor the
    money total was grossed up by, so a buy-list quantity and its cost stay in
    step. A missing or non-positive waste leaves net == gross.
    """
    net = _dec(res.get("quantity"), "0")
    waste_pct = res.get("waste_pct")
    if waste_pct is None:
        meta = res.get("metadata")
        if isinstance(meta, Mapping):
            waste_pct = meta.get("waste_pct")
    pct = _dec(waste_pct, "0")
    if pct > 0:
        return net * (Decimal("1") + pct / Decimal("100"))
    return net


def aggregate_material_buy_list(
    positions: Iterable[Mapping[str, Any]],
    *,
    currency: str = "",
    fx_rates: Mapping[str, str] | None = None,
) -> MaterialBuyList:
    """Roll the estimate's material resource lines into a procurement buy-list.

    Every ``type == material`` resource line across all positions is grouped and
    its gross purchase quantity and cost summed. A line that names a catalogue
    item (``catalog_item_id``) groups with the other lines of that item in the
    same unit, whatever they are called; a line without one groups by
    ``(normalized name, unit)``. A coded and an uncoded line, or two different
    catalogue items, never share a row even when their names agree (issue #516),
    so a buyer reads one order line per distinct material - the next action the
    passive rollup never gave them. Non-material lines (labour, machinery,
    equipment, subcontract, other) are skipped.

    The quantity is grossed up for waste (see :func:`_line_gross_quantity_per_unit`)
    and scaled by the position quantity; the cost reuses the same self-healing and
    FX rules as :func:`aggregate_resource_statement`, so money is the project-base
    figure a buyer commits to. Both are ``Decimal``-exact.

    Args:
        positions: BoQ position dicts. Each is read for ``quantity`` and its
            ``metadata_["resources"]`` (``metadata`` is also accepted) split; an
            optional ``id`` is used only to count distinct contributing positions.
        currency: Project base currency label for the list. When empty, the first
            resource currency seen is used so the response still carries a code.
        fx_rates: Optional ``{code: rate}`` map (base units per one foreign unit)
            used to convert a resource line priced in a foreign currency. A missing
            rate leaves the line in its own units (deterministic, never zeroed).

    Returns:
        A :class:`MaterialBuyList` whose items are sorted by descending cost, then
        name, for a stable, readable purchase order.
    """
    base = (currency or "").strip().upper()
    fx = {str(k).strip().upper(): v for k, v in (fx_rates or {}).items()}
    first_currency = ""

    # ("item", catalog id, unit) or ("name", name, unit) -> accumulator
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    contributing: set[str] = set()
    anon = 0

    for position in positions:
        meta = position.get("metadata_") or position.get("metadata") or {}
        resources = meta.get("resources") if isinstance(meta, Mapping) else None
        if not isinstance(resources, list) or not resources:
            continue
        pos_qty = _dec(position.get("quantity"), "0")
        pos_id = str(position.get("id") or "")
        if not pos_id:
            pos_id = f"__anon_{anon}"
            anon += 1
        contributed = False

        for res_index, res in enumerate(resources):
            if not isinstance(res, Mapping):
                continue
            kind = coerce_kind(res.get("type") or res.get("resource_type") or res.get("kind"))
            if kind is not ResourceKind.MATERIAL:
                continue
            name = str(res.get("name") or res.get("description") or res.get("code") or "").strip() or "-"
            unit = str(res.get("unit") or "").strip()

            res_currency = str(res.get("currency") or "").strip().upper()
            if res_currency and not first_currency:
                first_currency = res_currency

            per_unit_cost = _line_cost_per_unit(res)
            # Convert a foreign-priced line into the base currency before summing.
            if res_currency and base and res_currency != base:
                rate = fx.get(res_currency)
                if rate is not None:
                    rate_dec = _dec(rate)
                    if rate_dec.is_finite() and rate_dec > 0:
                        per_unit_cost = per_unit_cost * rate_dec

            line_qty = _line_gross_quantity_per_unit(res) * pos_qty
            line_cost = per_unit_cost * pos_qty

            catalog_item_id = str(res.get("catalog_item_id") or "").strip() or None
            key = ("item", catalog_item_id, unit.lower()) if catalog_item_id else ("name", name.lower(), unit.lower())
            acc = groups.get(key)
            if acc is None:
                acc = {
                    "name": name,
                    "unit": unit,
                    "quantity": Decimal("0"),
                    "cost": Decimal("0"),
                    "positions": set(),
                    "sources": [],
                }
                groups[key] = acc
            acc["quantity"] += line_qty
            acc["cost"] += line_cost
            acc["positions"].add(pos_id)
            suggested, origin = effective_suggestion(meta, res)
            acc["sources"].append(
                BuyListSource(
                    position_id=pos_id,
                    resource_key=_resource_key(res, res_index),
                    quantity=line_qty,
                    unit=unit,
                    code=str(res.get("code") or "").strip(),
                    catalog_item_id=catalog_item_id,
                    suggested_vendor_id=str(suggested) if suggested else None,
                    suggested_vendor_origin=origin,
                )
            )
            contributed = True

        if contributed:
            contributing.add(pos_id)

    items = [
        BuyListItem(
            name=acc["name"],
            unit=acc["unit"],
            quantity=acc["quantity"],
            cost=acc["cost"],
            position_count=len(acc["positions"]),
            sources=acc["sources"],
        )
        for acc in groups.values()
    ]
    # Highest-cost lines first, then name for a stable, readable purchase order.
    items.sort(key=lambda item: (-item.cost, item.name.lower()))

    return MaterialBuyList(
        currency=base or first_currency or "",
        items=items,
        position_count=len(contributing),
    )


def render_csv(statement: ResourceStatement) -> str:
    """Render a procurement statement as spreadsheet-friendly CSV.

    Layout: a title block (currency, totals), then per category a heading row, one
    row per resource line (category / name / unit / quantity / cost) and a category
    subtotal. Money is 2dp and quantities 4dp, ``Decimal``-exact. The csv writer
    escapes any commas or quotes inside a name, and a fixed line terminator keeps
    the output identical across platforms.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    cur = statement.currency

    writer.writerow(["Resource / procurement statement"])
    writer.writerow(["Currency", cur])
    writer.writerow(["Total labour hours", _q(statement.labor_hours, _4P)])
    writer.writerow(["Total cost", _q(statement.total_cost, _2P)])
    writer.writerow([])
    writer.writerow(["Category", "Resource", "Unit", "Quantity", "Cost", "Positions"])
    for group in statement.groups:
        for line in group.lines:
            writer.writerow(
                [
                    group.label,
                    line.name,
                    line.unit,
                    _q(line.quantity, _4P),
                    _q(line.cost, _2P),
                    line.position_count,
                ]
            )
        writer.writerow([f"{group.label} subtotal", "", "", "", _q(group.total_cost, _2P), ""])
        writer.writerow([])
    writer.writerow(["Grand total", "", "", "", _q(statement.total_cost, _2P), ""])
    return buf.getvalue()
