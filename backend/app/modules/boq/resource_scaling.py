# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Proportional scaling of resource norms to a target total.

An estimator who knows a section should take 1 200 labour hours, not the
1 380 the norms add up to, wants to type 1 200 and have every labour norm
under that section shrink by the same factor. The same for a total cost, or
for one resource group (all the C30 concrete, all the crane hours).

The arithmetic, stated once:

* every matched resource row contributes ``position quantity x norm`` to the
  metric (hours, quantity), or that times its unit rate in the project's base
  currency (cost);
* rows that may not move - on a locked line, on a line the user excluded,
  a resource marked ``locked``, a cost that cannot be converted - and, for
  cost, every unmatched resource and every line priced without resources,
  are the *fixed* part;
* ``factor = (target - fixed) / scalable``, applied to each scalable norm and
  then rounded by the chosen rule; the plan reports what the rounded norms
  actually add up to, so the drift the rounding causes is on screen before
  anything is written.

Pure: no session, no FastAPI. The service loads the lines and writes the plan.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation
from typing import Any, Literal

Metric = Literal["hours", "cost", "quantity"]
RoundingMode = Literal["half_up", "up", "down"]

#: Resource types whose quantity is working time. ``labour`` is accepted as
#: the spelling some catalogues use; ``operator`` is the machine operator.
LABOUR_TYPES: frozenset[str] = frozenset({"labor", "labour", "operator"})

_ROUNDING = {"half_up": ROUND_HALF_UP, "up": ROUND_UP, "down": ROUND_DOWN}
MAX_DECIMALS = 6


class ScalingError(ValueError):
    """A request the arithmetic cannot satisfy; ``code`` names why for the UI."""

    def __init__(self, code: str, message: str, **params: Any) -> None:
        super().__init__(message)
        self.code = code
        self.params = params


@dataclass(frozen=True, slots=True)
class ScaleScope:
    """Which resource rows take part.

    ``resource_type`` narrows to one type (``labor``, ``equipment`` ...);
    ``resource_key`` to one resource, matched on its code, or on its name
    when it has no code. Both are compared case-insensitively.
    """

    resource_type: str | None = None
    resource_key: str | None = None


@dataclass(frozen=True, slots=True)
class RoundingRule:
    """How a scaled norm is rounded: ``decimals`` places, half up, up or down."""

    decimals: int = 3
    mode: RoundingMode = "half_up"

    def apply(self, value: Decimal) -> Decimal:
        """Round ``value`` by this rule."""
        decimals = max(0, min(MAX_DECIMALS, int(self.decimals)))
        quantum = Decimal(1).scaleb(-decimals)
        return value.quantize(quantum, rounding=_ROUNDING.get(self.mode, ROUND_HALF_UP))


@dataclass(slots=True)
class ScaleLine:
    """One BOQ line as the planner sees it."""

    id: str
    ordinal: str
    description: str
    quantity: Decimal
    resources: list[dict[str, Any]]
    total: Decimal = Decimal(0)
    currency: str = ""
    locked: bool = False
    excluded: bool = False


@dataclass(slots=True)
class ResourceChange:
    """One norm the plan changes."""

    index: int
    name: str
    type: str
    unit: str
    old_quantity: Decimal
    new_quantity: Decimal

    def to_dict(self) -> dict[str, Any]:
        """JSON shape, numbers as strings."""
        return {
            "index": self.index,
            "name": self.name,
            "type": self.type,
            "unit": self.unit,
            "old_quantity": _s(self.old_quantity),
            "new_quantity": _s(self.new_quantity),
        }


@dataclass(slots=True)
class PlannedLine:
    """What the plan does to one line."""

    id: str
    ordinal: str
    description: str
    status: Literal["scaled", "locked", "excluded", "no_match", "unchanged"]
    old_value: Decimal = Decimal(0)
    new_value: Decimal = Decimal(0)
    changes: list[ResourceChange] = field(default_factory=list)
    resources: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON shape for the preview (the new resource list stays server-side)."""
        return {
            "id": self.id,
            "ordinal": self.ordinal,
            "description": self.description,
            "status": self.status,
            "old_value": _s(self.old_value),
            "new_value": _s(self.new_value),
            "changes": [c.to_dict() for c in self.changes],
        }


@dataclass(slots=True)
class ScalePlan:
    """The whole proposal: the factor, the totals before and after, every line."""

    metric: Metric
    target: Decimal
    current: Decimal
    fixed: Decimal
    scalable: Decimal
    factor: Decimal
    achieved: Decimal
    rounding: RoundingRule
    lines: list[PlannedLine]
    units: list[str]
    warnings: list[dict[str, Any]]

    @property
    def changed_lines(self) -> list[PlannedLine]:
        """Lines whose resources the plan rewrites."""
        return [line for line in self.lines if line.status == "scaled"]

    def to_dict(self) -> dict[str, Any]:
        """JSON shape for the preview and the apply response."""
        return {
            "metric": self.metric,
            "target": _s(self.target),
            "current": _s(self.current),
            "fixed": _s(self.fixed),
            "scalable": _s(self.scalable),
            "factor": _s(self.factor),
            "achieved": _s(self.achieved),
            "drift": _s(self.achieved - self.target),
            "rounding": {"decimals": self.rounding.decimals, "mode": self.rounding.mode},
            "units": self.units,
            "warnings": self.warnings,
            "counts": {
                "scaled": sum(1 for line in self.lines if line.status == "scaled"),
                "locked": sum(1 for line in self.lines if line.status == "locked"),
                "excluded": sum(1 for line in self.lines if line.status == "excluded"),
                "no_match": sum(1 for line in self.lines if line.status == "no_match"),
            },
            "lines": [line.to_dict() for line in self.lines if line.status != "no_match"],
        }


def _s(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def to_decimal(value: Any) -> Decimal:
    """Coerce a stored number to ``Decimal``; anything unusable is zero."""
    if value is None or isinstance(value, bool):
        return Decimal(0)
    try:
        d = value if isinstance(value, Decimal) else Decimal(repr(value) if isinstance(value, float) else str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return d if d.is_finite() else Decimal(0)


def _norm(text: Any) -> str:
    return str(text or "").strip().casefold()


def _type_key(rtype: Any) -> str:
    key = _norm(rtype)
    return "labor" if key == "labour" else key


def resource_matches(resource: Mapping[str, Any], scope: ScaleScope, metric: Metric) -> bool:
    """Whether ``resource`` takes part in a scaling of ``metric`` over ``scope``."""
    rtype = _norm(resource.get("type"))
    if scope.resource_type:
        if _type_key(rtype) != _type_key(scope.resource_type):
            return False
    elif metric == "hours" and rtype not in LABOUR_TYPES:
        return False
    if scope.resource_key:
        key = _norm(scope.resource_key)
        code = _norm(resource.get("code"))
        name = _norm(resource.get("name"))
        if code != key and name != key:
            return False
    return True


def _contribution(
    resource: Mapping[str, Any],
    line: ScaleLine,
    metric: Metric,
    quantity: Decimal,
    to_base: Callable[[Decimal, str], Decimal | None],
) -> Decimal | None:
    """What one resource row adds to the metric; ``None`` when its cost cannot be converted."""
    amount = line.quantity * quantity
    if metric != "cost":
        return amount
    rate = to_decimal(resource.get("unit_rate"))
    return to_base(amount * rate, str(resource.get("currency") or ""))


def plan_scaling(
    lines: Iterable[ScaleLine],
    *,
    scope: ScaleScope,
    metric: Metric,
    target: Decimal | None,
    rounding: RoundingRule,
    to_base: Callable[[Decimal, str], Decimal | None] | None = None,
) -> ScalePlan:
    """Work out the factor and the rounded norms that bring ``metric`` to ``target``.

    ``target=None`` measures only: the plan carries the current totals and a
    factor of one, so the dialog can show where the bill stands before the
    user types a number.

    Raises:
        ScalingError: ``target_negative``, ``nothing_to_scale`` (no movable
            row in scope) or ``target_below_fixed`` (the locked and excluded
            part alone already exceeds the target).
    """
    if target is not None and target < 0:
        raise ScalingError("target_negative", "The target cannot be negative.")
    convert = to_base or (lambda amount, _code: amount)
    fixed = Decimal(0)
    scalable = Decimal(0)
    units: set[str] = set()
    unconverted = 0
    staged: list[tuple[ScaleLine, list[int], Decimal, Decimal]] = []

    for line in lines:
        movable: list[int] = []
        line_fixed = Decimal(0)
        line_scalable = Decimal(0)
        has_resources = any(isinstance(r, dict) and to_decimal(r.get("quantity")) != 0 for r in line.resources)
        for idx, res in enumerate(line.resources):
            if not isinstance(res, dict):
                continue
            matched = resource_matches(res, scope, metric)
            if not matched and metric != "cost":
                continue
            value = _contribution(res, line, metric, to_decimal(res.get("quantity")), convert)
            if value is None:
                unconverted += 1
                continue
            if matched:
                units.add(str(res.get("unit") or "").strip())
            if matched and not (line.locked or line.excluded or res.get("locked")):
                movable.append(idx)
                line_scalable += value
            else:
                line_fixed += value
        if metric == "cost" and not has_resources:
            converted = convert(line.total, line.currency)
            if converted is None:
                unconverted += 1
            else:
                line_fixed += converted
        fixed += line_fixed
        scalable += line_scalable
        staged.append((line, movable, line_fixed, line_scalable))

    current = fixed + scalable
    measure_only = target is None
    if target is None:
        target = current
    if scalable == 0:
        raise ScalingError("nothing_to_scale", "No resource in scope can be scaled.", current=_s(current))
    if target < fixed:
        raise ScalingError(
            "target_below_fixed",
            "The locked and excluded part alone exceeds the target.",
            fixed=_s(fixed),
        )
    factor = (target - fixed) / scalable

    planned: list[PlannedLine] = []
    achieved = fixed
    rounded_to_zero = 0
    for line, movable, line_fixed, line_scalable in staged:
        base = PlannedLine(id=line.id, ordinal=line.ordinal, description=line.description, status="no_match")
        if line.locked or line.excluded:
            base.status = "locked" if line.locked else "excluded"
            base.old_value = base.new_value = line_fixed
            if line_fixed != 0 or any(
                resource_matches(r, scope, metric) for r in line.resources if isinstance(r, dict)
            ):
                planned.append(base)
            continue
        if not movable:
            planned.append(base)
            continue
        new_resources = [dict(r) if isinstance(r, dict) else r for r in line.resources]
        new_value = line_fixed
        changes: list[ResourceChange] = []
        for idx in movable:
            res = new_resources[idx]
            old_q = to_decimal(res.get("quantity"))
            new_q = old_q if measure_only else rounding.apply(old_q * factor)
            if old_q != 0 and new_q == 0:
                rounded_to_zero += 1
            contribution = _contribution(res, line, metric, new_q, convert) or Decimal(0)
            new_value += contribution
            if new_q != old_q:
                res["quantity"] = float(new_q)
                if res.get("total") is not None:
                    res["total"] = float((new_q * to_decimal(res.get("unit_rate"))).quantize(Decimal("0.01")))
                changes.append(
                    ResourceChange(
                        index=idx,
                        name=str(res.get("name") or res.get("code") or ""),
                        type=str(res.get("type") or ""),
                        unit=str(res.get("unit") or ""),
                        old_quantity=old_q,
                        new_quantity=new_q,
                    )
                )
        achieved += new_value - line_fixed
        planned.append(
            PlannedLine(
                id=line.id,
                ordinal=line.ordinal,
                description=line.description,
                status="scaled" if changes else "unchanged",
                old_value=line_fixed + line_scalable,
                new_value=new_value,
                changes=changes,
                resources=new_resources if changes else None,
            )
        )

    warnings: list[dict[str, Any]] = []
    clean_units = sorted(u for u in units if u)
    if metric != "cost" and len(clean_units) > 1:
        warnings.append({"code": "mixed_units", "units": clean_units})
    if unconverted:
        warnings.append({"code": "unconverted_currency", "count": unconverted})
    if rounded_to_zero:
        warnings.append({"code": "rounded_to_zero", "count": rounded_to_zero})
    return ScalePlan(
        metric=metric,
        target=target,
        current=current,
        fixed=fixed,
        scalable=scalable,
        factor=factor,
        achieved=achieved,
        rounding=rounding,
        lines=planned,
        units=clean_units,
        warnings=warnings,
    )


def scope_line_ids(rows: Iterable[Any], root_id: str | None, is_section: Callable[[Any], bool]) -> set[str]:
    """Ids of the non-section lines under ``root_id`` (any depth), or of every line when ``None``."""
    rows = list(rows)
    if root_id is None:
        return {str(r.id) for r in rows if not is_section(r)}
    children: dict[str, list[Any]] = {}
    for r in rows:
        if getattr(r, "parent_id", None):
            children.setdefault(str(r.parent_id), []).append(r)
    found: set[str] = set()
    stack = [str(root_id)]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for child in children.get(current, []):
            if not is_section(child):
                found.add(str(child.id))
            stack.append(str(child.id))
    return found


__all__ = [
    "LABOUR_TYPES",
    "PlannedLine",
    "ResourceChange",
    "RoundingRule",
    "ScaleLine",
    "ScalePlan",
    "ScaleScope",
    "ScalingError",
    "plan_scaling",
    "resource_matches",
    "scope_line_ids",
    "to_decimal",
]
