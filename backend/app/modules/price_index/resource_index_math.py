# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure Decimal computation of a Russian estimate by the resource-index method.

Russian estimates on the 2022 federal norm base (FSNB-2022) are priced by the
resource-index method set out in the Minstroy methodology (order 421/pr). Each
resource group of a norm is taken at its base price and multiplied by that
group's own regional quarterly index:

* ``labor``          - workers' wages (OT), index for workers' wages;
* ``machine``        - machine operation (EM), index for machine operation;
* ``operator_wages`` - machine operators' wages (OTm), its own index, used for
  the wage fund;
* ``material``       - materials (M), index for materials.

Overheads (NR) and estimated profit (SP) are then charged on the wage fund
``FOT = OT + OTm`` at the percentages set per type of work (Minstroy orders
812/pr and 774/pr), and VAT is charged on the total.

How operators are represented
-----------------------------
The platform stores a machine operator as its own resource line (kind
``operator``) whose money adds to the position, next to the machine line that
does not include the operator. That is the same money the methodology carries
inside the machine-hour price, so an ``operator`` line is treated as machine
operation whose whole amount is operators' wages:

* in direct cost it counts ONCE, inside EM, at the machine-operation index;
* for the wage fund its base amount is multiplied by the ``operator_wages``
  index and the result is shown as "EM, of which OTm".

Adding the operators to direct cost a second time, or leaving them out of FOT,
are the two ways to get this wrong; both change the total.

Rounding rule (the platform's, stated here so it can be checked)
---------------------------------------------------------------
Every product is rounded to kopecks (0.01) with ``ROUND_HALF_UP`` the moment it
is formed: the line base amount ``Q x q x p``, the line current amount
``base x index``, the operators' wage amount, each position's NR and SP, and the
VAT. Every sum is a sum of those rounded figures, so each printed number is
the sum of the numbers printed beneath it. Indices and percentages are used
exactly as given.

Every gap is an explicit error. A group with lines but no index raises
:class:`MissingIndexError` naming every missing group; a work type with no NR/SP
norm raises :class:`MissingOverheadNormError`; nothing defaults to ``1`` or to a
plausible percentage.

The module is free of I/O, ORM and ``float``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "GROUP_LABOR",
    "GROUP_MACHINE",
    "GROUP_MATERIAL",
    "GROUP_OPERATOR_WAGES",
    "INDEX_GROUPS",
    "KIND_LABOR",
    "KIND_MACHINE",
    "KIND_MATERIAL",
    "KIND_OPERATOR",
    "RESOURCE_KINDS",
    "EstimateInput",
    "EstimateResult",
    "EstimateTotals",
    "InvalidIndexError",
    "LineResult",
    "MissingIndexError",
    "MissingOverheadNormError",
    "OverheadProfitNorm",
    "PositionInput",
    "PositionResult",
    "ResourceIndexError",
    "ResourceIndexInputError",
    "ResourceLineInput",
    "WorkTypeSummary",
    "compute_resource_index_estimate",
    "normalise_quarter",
]

# ── Index groups (keys of the index table) ───────────────────────────────────

GROUP_LABOR = "labor"
GROUP_MACHINE = "machine"
GROUP_OPERATOR_WAGES = "operator_wages"
GROUP_MATERIAL = "material"

INDEX_GROUPS: tuple[str, ...] = (GROUP_LABOR, GROUP_MACHINE, GROUP_OPERATOR_WAGES, GROUP_MATERIAL)

# ── Resource kinds (what a line is) ──────────────────────────────────────────

KIND_LABOR = "labor"
KIND_MACHINE = "machine"
KIND_OPERATOR = "operator"
KIND_MATERIAL = "material"

RESOURCE_KINDS: tuple[str, ...] = (KIND_LABOR, KIND_MACHINE, KIND_OPERATOR, KIND_MATERIAL)

# Which index prices a line's money in direct cost.
_KIND_TO_GROUP: dict[str, str] = {
    KIND_LABOR: GROUP_LABOR,
    KIND_MACHINE: GROUP_MACHINE,
    KIND_OPERATOR: GROUP_MACHINE,
    KIND_MATERIAL: GROUP_MATERIAL,
}

MONEY_QUANTUM = Decimal("0.01")
_ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")

_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


# ── Errors ───────────────────────────────────────────────────────────────────


class ResourceIndexError(ValueError):
    """Base class for every refusal of the resource-index computation."""

    code = "resource_index_error"


class ResourceIndexInputError(ResourceIndexError):
    """The input itself is malformed (bad quarter, blank work type, unknown kind)."""

    code = "invalid_input"


class MissingIndexError(ResourceIndexError):
    """A resource group that has lines has no index for the region and quarter.

    Attributes:
        region: The region the index was looked up for.
        quarter: The quarter the index was looked up for.
        groups: Every missing group, sorted, so one error names them all.
    """

    code = "missing_index"

    def __init__(self, region: str, quarter: str, groups: tuple[str, ...]) -> None:
        self.region = region
        self.quarter = quarter
        self.groups = groups
        super().__init__(f"no index for {', '.join(groups)} in region {region!r}, quarter {quarter!r}")


class InvalidIndexError(ResourceIndexError):
    """An index the computation needs is zero or negative."""

    code = "invalid_index"

    def __init__(self, group: str, value: Decimal) -> None:
        self.group = group
        self.value = value
        super().__init__(f"index for {group!r} must be positive, got {value}")


class MissingOverheadNormError(ResourceIndexError):
    """A work type in use has no NR/SP percentages."""

    code = "missing_overhead_norm"

    def __init__(self, work_types: tuple[str, ...]) -> None:
        self.work_types = work_types
        super().__init__(f"no overhead and profit norm for work type(s) {', '.join(work_types)}")


# ── Input ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OverheadProfitNorm:
    """NR and SP percentages of FOT for one type of work."""

    work_type: str
    nr_pct: Decimal
    sp_pct: Decimal


@dataclass(frozen=True)
class ResourceLineInput:
    """One resource of a norm at base prices.

    ``quantity`` is the consumption per unit of the position (the norm), so the
    line's base amount is ``position quantity x quantity x base_unit_price``.
    """

    code: str
    name: str
    unit: str
    kind: str
    quantity: Decimal
    base_unit_price: Decimal


@dataclass(frozen=True)
class PositionInput:
    """One estimate position: a norm applied to a quantity, of one work type."""

    ref: str
    ordinal: str
    description: str
    unit: str
    quantity: Decimal
    work_type: str
    resources: tuple[ResourceLineInput, ...]


@dataclass(frozen=True)
class EstimateInput:
    """Everything the computation reads, and nothing else.

    Attributes:
        region: Region the indices belong to (reported back, used in errors).
        quarter: ``YYYY-Qn`` quarter the indices belong to.
        indices: Index per group for that region and quarter.
        norms: NR/SP percentages keyed by work type.
        positions: The positions to price.
        vat_rate_pct: VAT rate in percent for the pricing date.
    """

    region: str
    quarter: str
    indices: Mapping[str, Decimal]
    norms: Mapping[str, OverheadProfitNorm]
    positions: tuple[PositionInput, ...]
    vat_rate_pct: Decimal


# ── Output ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LineResult:
    """One resource line with every multiplication spelled out."""

    code: str
    name: str
    unit: str
    kind: str
    quantity: Decimal
    base_unit_price: Decimal
    position_quantity: Decimal
    base_amount: Decimal
    index_group: str
    index: Decimal
    current_amount: Decimal
    operator_wage_index: Decimal | None = None
    operator_wage_current: Decimal | None = None


@dataclass(frozen=True)
class PositionResult:
    """One position priced: base and current figures by group, FOT, NR, SP."""

    ref: str
    ordinal: str
    description: str
    unit: str
    quantity: Decimal
    work_type: str
    lines: tuple[LineResult, ...]
    base_ot: Decimal
    base_em: Decimal
    base_otm: Decimal
    base_m: Decimal
    base_direct: Decimal
    ot: Decimal
    em: Decimal
    otm: Decimal
    m: Decimal
    direct: Decimal
    fot: Decimal
    nr_pct: Decimal
    nr: Decimal
    sp_pct: Decimal
    sp: Decimal
    total: Decimal


@dataclass(frozen=True)
class WorkTypeSummary:
    """FOT, NR and SP summed for one work type, as a smeta summary prints them."""

    work_type: str
    nr_pct: Decimal
    sp_pct: Decimal
    fot: Decimal
    nr: Decimal
    sp: Decimal


@dataclass(frozen=True)
class EstimateTotals:
    """Estimate totals, each the sum of the position figures beneath it."""

    base_ot: Decimal
    base_em: Decimal
    base_otm: Decimal
    base_m: Decimal
    base_direct: Decimal
    ot: Decimal
    em: Decimal
    otm: Decimal
    m: Decimal
    direct: Decimal
    fot: Decimal
    nr: Decimal
    sp: Decimal
    total: Decimal
    vat_rate_pct: Decimal
    vat: Decimal
    total_with_vat: Decimal


@dataclass(frozen=True)
class EstimateResult:
    """The full priced estimate."""

    region: str
    quarter: str
    indices_used: dict[str, Decimal]
    positions: tuple[PositionResult, ...]
    by_work_type: tuple[WorkTypeSummary, ...]
    totals: EstimateTotals
    norms_used: dict[str, OverheadProfitNorm] = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _finite(value: Decimal, what: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ResourceIndexInputError(f"{what} must be a finite decimal")
    return value


def normalise_quarter(raw: str) -> str:
    """Return ``raw`` as ``YYYY-Qn``, upper-cased and trimmed.

    Raises:
        ResourceIndexInputError: If it is not a year and a quarter 1-4.
    """
    text = (raw or "").strip().upper()
    if not _QUARTER_RE.match(text):
        raise ResourceIndexInputError(f"quarter must look like '2026-Q1', got {raw!r}")
    return text


def _validate(data: EstimateInput) -> None:
    _finite(data.vat_rate_pct, "VAT rate")
    if data.vat_rate_pct < 0:
        raise ResourceIndexInputError("VAT rate cannot be negative")
    for position in data.positions:
        if not position.work_type or not position.work_type.strip():
            raise ResourceIndexInputError(f"position {position.ordinal or position.ref} has no work type")
        _finite(position.quantity, f"quantity of position {position.ordinal}")
        if position.quantity < 0:
            raise ResourceIndexInputError(f"position {position.ordinal} has a negative quantity")
        for line in position.resources:
            if line.kind not in _KIND_TO_GROUP:
                raise ResourceIndexInputError(
                    f"position {position.ordinal}: resource {line.code or line.name!r} has kind {line.kind!r}, "
                    f"which is not one of {', '.join(RESOURCE_KINDS)}"
                )
            _finite(line.quantity, f"quantity of resource {line.code}")
            _finite(line.base_unit_price, f"base price of resource {line.code}")
            if line.quantity < 0 or line.base_unit_price < 0:
                raise ResourceIndexInputError(
                    f"position {position.ordinal}: resource {line.code or line.name!r} has a negative value"
                )


def _required_groups(positions: tuple[PositionInput, ...]) -> set[str]:
    groups: set[str] = set()
    for position in positions:
        for line in position.resources:
            groups.add(_KIND_TO_GROUP[line.kind])
            if line.kind == KIND_OPERATOR:
                groups.add(GROUP_OPERATOR_WAGES)
    return groups


def _resolve_indices(data: EstimateInput, required: set[str]) -> dict[str, Decimal]:
    missing = tuple(sorted(g for g in required if data.indices.get(g) is None))
    if missing:
        raise MissingIndexError(data.region, data.quarter, missing)
    resolved: dict[str, Decimal] = {}
    for group in sorted(required):
        value = _finite(data.indices[group], f"index for {group}")
        if value <= 0:
            raise InvalidIndexError(group, value)
        resolved[group] = value
    return resolved


def _resolve_norms(data: EstimateInput) -> dict[str, OverheadProfitNorm]:
    used = {p.work_type.strip() for p in data.positions}
    missing = tuple(sorted(wt for wt in used if wt not in data.norms))
    if missing:
        raise MissingOverheadNormError(missing)
    norms: dict[str, OverheadProfitNorm] = {}
    for wt in sorted(used):
        norm = data.norms[wt]
        _finite(norm.nr_pct, f"NR percentage for {wt}")
        _finite(norm.sp_pct, f"SP percentage for {wt}")
        if norm.nr_pct < 0 or norm.sp_pct < 0:
            raise ResourceIndexInputError(f"NR and SP percentages for {wt!r} cannot be negative")
        norms[wt] = norm
    return norms


def _price_line(line: ResourceLineInput, position_qty: Decimal, indices: Mapping[str, Decimal]) -> LineResult:
    group = _KIND_TO_GROUP[line.kind]
    index = indices[group]
    base = _money(position_qty * line.quantity * line.base_unit_price)
    current = _money(base * index)
    otm_index: Decimal | None = None
    otm_current: Decimal | None = None
    if line.kind == KIND_OPERATOR:
        otm_index = indices[GROUP_OPERATOR_WAGES]
        otm_current = _money(base * otm_index)
    return LineResult(
        code=line.code,
        name=line.name,
        unit=line.unit,
        kind=line.kind,
        quantity=line.quantity,
        base_unit_price=line.base_unit_price,
        position_quantity=position_qty,
        base_amount=base,
        index_group=group,
        index=index,
        current_amount=current,
        operator_wage_index=otm_index,
        operator_wage_current=otm_current,
    )


def _sum(values: list[Decimal]) -> Decimal:
    return sum(values, _ZERO)


def _price_position(
    position: PositionInput,
    indices: Mapping[str, Decimal],
    norms: Mapping[str, OverheadProfitNorm],
) -> PositionResult:
    lines = tuple(_price_line(line, position.quantity, indices) for line in position.resources)

    def of(kinds: tuple[str, ...], attr: str) -> Decimal:
        return _sum([getattr(r, attr) for r in lines if r.kind in kinds])

    base_ot = of((KIND_LABOR,), "base_amount")
    base_em = of((KIND_MACHINE, KIND_OPERATOR), "base_amount")
    base_otm = of((KIND_OPERATOR,), "base_amount")
    base_m = of((KIND_MATERIAL,), "base_amount")
    ot = of((KIND_LABOR,), "current_amount")
    em = of((KIND_MACHINE, KIND_OPERATOR), "current_amount")
    otm = _sum([r.operator_wage_current for r in lines if r.operator_wage_current is not None])
    m = of((KIND_MATERIAL,), "current_amount")
    direct = ot + em + m
    fot = ot + otm
    work_type = position.work_type.strip()
    norm = norms[work_type]
    nr = _money(fot * norm.nr_pct / _HUNDRED)
    sp = _money(fot * norm.sp_pct / _HUNDRED)
    return PositionResult(
        ref=position.ref,
        ordinal=position.ordinal,
        description=position.description,
        unit=position.unit,
        quantity=position.quantity,
        work_type=work_type,
        lines=lines,
        base_ot=base_ot,
        base_em=base_em,
        base_otm=base_otm,
        base_m=base_m,
        base_direct=base_ot + base_em + base_m,
        ot=ot,
        em=em,
        otm=otm,
        m=m,
        direct=direct,
        fot=fot,
        nr_pct=norm.nr_pct,
        nr=nr,
        sp_pct=norm.sp_pct,
        sp=sp,
        total=direct + nr + sp,
    )


# ── Entry point ──────────────────────────────────────────────────────────────


def compute_resource_index_estimate(data: EstimateInput) -> EstimateResult:
    """Price an estimate by the resource-index method.

    Args:
        data: Positions with their resource lines at base prices, the index per
            group for one region and quarter, the NR/SP norms per work type and
            the VAT rate for the pricing date.

    Returns:
        Every line's base and current amount, every position's OT, EM (of which
        OTm), M, FOT, NR and SP, a per-work-type summary, and the totals with VAT.

    Raises:
        ResourceIndexInputError: Malformed quarter, blank work type, unknown
            resource kind, negative value.
        MissingIndexError: A group with lines has no index.
        InvalidIndexError: A needed index is not positive.
        MissingOverheadNormError: A work type in use has no NR/SP norm.
    """
    quarter = normalise_quarter(data.quarter)
    _validate(data)
    indices = _resolve_indices(data, _required_groups(data.positions))
    norms = _resolve_norms(data)

    positions = tuple(_price_position(p, indices, norms) for p in data.positions)

    summary: dict[str, list[PositionResult]] = {}
    for p in positions:
        summary.setdefault(p.work_type, []).append(p)
    by_work_type = tuple(
        WorkTypeSummary(
            work_type=wt,
            nr_pct=norms[wt].nr_pct,
            sp_pct=norms[wt].sp_pct,
            fot=_sum([p.fot for p in rows]),
            nr=_sum([p.nr for p in rows]),
            sp=_sum([p.sp for p in rows]),
        )
        for wt, rows in sorted(summary.items())
    )

    def total_of(attr: str) -> Decimal:
        return _sum([getattr(p, attr) for p in positions])

    total = total_of("total")
    vat = _money(total * data.vat_rate_pct / _HUNDRED)
    totals = EstimateTotals(
        base_ot=total_of("base_ot"),
        base_em=total_of("base_em"),
        base_otm=total_of("base_otm"),
        base_m=total_of("base_m"),
        base_direct=total_of("base_direct"),
        ot=total_of("ot"),
        em=total_of("em"),
        otm=total_of("otm"),
        m=total_of("m"),
        direct=total_of("direct"),
        fot=total_of("fot"),
        nr=total_of("nr"),
        sp=total_of("sp"),
        total=total,
        vat_rate_pct=data.vat_rate_pct,
        vat=vat,
        total_with_vat=total + vat,
    )
    return EstimateResult(
        region=data.region,
        quarter=quarter,
        indices_used=indices,
        positions=positions,
        by_work_type=by_work_type,
        totals=totals,
        norms_used=norms,
    )
