# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure NRM 1 elemental rollup: bill lines in, cost plan out.

No session, no I/O beyond reading the element table shipped beside this file.
The service hands over the bill's leaf positions (already converted to the
project's base currency) and the markup amounts the bill's own cascade
produced, and this module regroups them. It never prices a markup itself. The
bill's markup stack is computed in exactly one place,
``app.modules.boq.service._calculate_markup_amounts``, and a cost plan that
recomputed it would be a second markup system that drifts the first time one of
the two is fixed.

Placement of a position, in order:

1. Its own ``classification.nrm`` code if it has one, even an invalid one. An
   explicit code is the estimator's statement, and a typo in it should surface
   as unallocated rather than be papered over by the section above.
2. Otherwise the nearest ancestor's code. A bill laid out as NRM sections
   ("Element 2 - Superstructure" with priced items below) codes the section and
   leaves the items blank, and those items are superstructure.
3. A code is read segment by segment as integers, never as a float, so
   ``2.10`` and ``2.1`` stay different elements and ``02.05`` is ``2.5``.
4. Group 0-14 and element in the table: placed on the element. Group only, or
   an element number the table does not list: placed on the group as a
   group-level line, with the code kept. Anything else: not allocated.

Group 0 and groups 1-8 are subtotalled apart, as NRM 1 does: group 0 is the
facilitating works estimate and groups 1-8 alone are the building works
estimate, the figure a cost per m2 of GIFA is benchmarked on. Folding demolition
or remediation into the building works estimate would overstate that rate by
exactly the abnormal costs a benchmark leaves out.

An empty placeholder row (the "Add Position" row nobody has typed into yet,
see ``app.modules.boq.service.is_empty_position``) carries no money and is not
a position, so it is skipped outright: it counts nowhere and raises nothing.

Nothing else is ever dropped. The invariant every caller can rely on, and the
tests pin, is ``facilitating_works_estimate + building_works_estimate + addon
groups + unallocated == direct_cost`` exactly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path
from typing import Any, Literal

from app.modules.cost_plan.schemas import (
    CostPlanResponse,
    ElementRow,
    GroupLevelRow,
    GroupRow,
    MarkupRow,
    PlacementReason,
    SubtotalRow,
    UnallocatedBlock,
    UnallocatedPosition,
)

__all__ = [
    "FACILITATING_GROUP",
    "MAX_LISTED_UNALLOCATED",
    "Catalogue",
    "CatalogueElement",
    "CatalogueGroup",
    "LeafInput",
    "MarkupInput",
    "Placement",
    "build_cost_plan",
    "load_nrm1_catalogue",
    "normalise_code",
    "place_code",
]

_DATA_FILE = Path(__file__).resolve().parent / "data" / "nrm1_elements.json"
_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")
_CODE_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){0,4}$")

#: The unallocated list is capped so a bill of ten thousand uncoded lines does
#: not ship them all to the browser. The total and the count are never capped.
MAX_LISTED_UNALLOCATED = 500

#: NRM 1 group 0, facilitating works. It is subtotalled as the facilitating
#: works estimate and kept out of the building works estimate (groups 1-8).
FACILITATING_GROUP = "0"


# ── Element table ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CatalogueElement:
    """One element of a group, for example ``2.5 External walls``."""

    code: str
    name: str


@dataclass(frozen=True)
class CatalogueGroup:
    """One NRM 1 group element.

    ``kind`` is ``works`` for 0-8, which build the facilitating works estimate
    (group 0) and the building works estimate (1-8), and ``addon`` for 9-14,
    which NRM 1 places below them.
    """

    code: str
    name: str
    kind: Literal["works", "addon"]
    elements: tuple[CatalogueElement, ...]

    def element(self, code: str) -> CatalogueElement | None:
        """The element with this exact normalised code, or None."""
        for element in self.elements:
            if element.code == code:
                return element
        return None


@dataclass(frozen=True)
class Catalogue:
    """The element table, in printing order."""

    standard: str
    groups: tuple[CatalogueGroup, ...]

    def group(self, code: str) -> CatalogueGroup | None:
        """The group with this exact normalised code, or None."""
        for group in self.groups:
            if group.code == code:
                return group
        return None


@cache
def load_nrm1_catalogue() -> Catalogue:
    """Read the shipped NRM 1 element table.

    Raises:
        ValueError: When the file is malformed, so a broken data edit fails
            loudly at first use instead of producing a plan with a group
            missing.
    """
    raw: dict[str, Any] = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    groups: list[CatalogueGroup] = []
    for entry in raw.get("groups", []):
        kind = entry.get("kind")
        if kind not in ("works", "addon"):
            raise ValueError(f"NRM 1 table: group {entry.get('code')!r} has kind {kind!r}")
        group_code = normalise_code(entry.get("code"))
        if group_code is None or "." in group_code:
            raise ValueError(f"NRM 1 table: group code {entry.get('code')!r} is not a single number")
        elements: list[CatalogueElement] = []
        for item in entry.get("elements", []):
            element_code = normalise_code(item.get("code"))
            if element_code is None or element_code.split(".")[0] != group_code or element_code.count(".") != 1:
                raise ValueError(f"NRM 1 table: element {item.get('code')!r} does not belong to group {group_code}")
            elements.append(CatalogueElement(code=element_code, name=str(item["name"])))
        groups.append(CatalogueGroup(code=group_code, name=str(entry["name"]), kind=kind, elements=tuple(elements)))
    if not groups:
        raise ValueError("NRM 1 table is empty")
    return Catalogue(standard=str(raw.get("standard", "NRM1")), groups=tuple(groups))


# ── Codes ────────────────────────────────────────────────────────────────────


def _raw_text(raw: object) -> str | None:
    """The code as text, or None when nothing was written.

    A boolean is not a code (``True`` is an ``int`` to Python). An ``int`` or
    ``float`` reaches here from a JSON column that a spreadsheet import typed as
    a number; ``str`` keeps what the float can still say (``2.1``), and a float
    cannot carry ``2.10`` in the first place, so nothing more is recoverable.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        text = str(raw)
    elif isinstance(raw, str):
        text = raw
    else:
        return None
    text = text.strip()
    return text or None


def normalise_code(raw: object) -> str | None:
    """Reduce a written NRM code to its canonical dotted form.

    ``"02.05"`` becomes ``"2.5"``, ``"2.6.1."`` becomes ``"2.6.1"``, and ``7``
    becomes ``"7"``. Each segment is read as an integer, so ``"2.10"`` stays
    ``"2.10"`` and is never confused with ``"2.1"``.

    Returns:
        The canonical code, or None when ``raw`` is empty or not an NRM number.
    """
    text = _raw_text(raw)
    if text is None:
        return None
    text = text.rstrip(".")
    if not _CODE_RE.match(text):
        return None
    return ".".join(str(int(segment)) for segment in text.split("."))


@dataclass(frozen=True)
class Placement:
    """Where one code lands in the table."""

    reason: PlacementReason
    group_code: str | None = None
    element_code: str | None = None

    @property
    def allocated(self) -> bool:
        """True when the money sits on a group (element or group level)."""
        return self.group_code is not None


def place_code(raw: object, catalogue: Catalogue) -> Placement:
    """Place a written code on the element table.

    Args:
        raw: The code as found on the position (string, number or None).
        catalogue: The element table.

    Returns:
        The placement and the reason for it.
    """
    if _raw_text(raw) is None:
        return Placement(reason="no_code")
    code = normalise_code(raw)
    if code is None:
        return Placement(reason="invalid_code")
    segments = code.split(".")
    group = catalogue.group(segments[0])
    if group is None:
        return Placement(reason="unknown_group")
    if len(segments) == 1:
        return Placement(reason="group_level", group_code=group.code)
    element = group.element(f"{segments[0]}.{segments[1]}")
    if element is None:
        return Placement(reason="unknown_element", group_code=group.code)
    return Placement(reason="matched", group_code=group.code, element_code=element.code)


# ── Inputs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LeafInput:
    """One priced bill position, already in the project's base currency.

    ``code`` is the position's own ``classification.nrm``; ``inherited_code``
    is the nearest ancestor's, used only when the position has none.
    ``placeholder`` marks an empty row nobody has filled in yet. Such a row is
    skipped by the rollup, but only while its amount is zero: a row flagged by
    mistake that carries money is still counted, so no money can be lost.
    """

    id: Any
    ordinal: str
    description: str
    amount: Decimal
    code: object = None
    inherited_code: object = None
    placeholder: bool = False


@dataclass(frozen=True)
class MarkupInput:
    """One line of the bill's markup cascade with the amount the bill computed."""

    id: Any
    name: str
    category: str
    markup_type: str
    apply_to: str
    amount: Decimal
    percentage: Decimal | None = None
    fixed_amount: Decimal | None = None
    scoped: bool = False


# ── Rollup ───────────────────────────────────────────────────────────────────


def _ratio(amount: Decimal, divisor: Decimal | None, scale: Decimal = Decimal("1")) -> Decimal | None:
    """``amount * scale / divisor`` to cents, or None without a usable divisor."""
    if divisor is None or divisor == 0:
        return None
    return (amount * scale / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass
class _Bucket:
    total: Decimal = Decimal("0")
    count: int = 0

    def add(self, amount: Decimal) -> None:
        self.total += amount
        self.count += 1


def build_cost_plan(
    *,
    boq_id: Any,
    boq_name: str,
    project_id: Any,
    currency: str,
    leaves: Sequence[LeafInput],
    markups: Sequence[MarkupInput],
    gifa: Decimal | None = None,
    gifa_source: Literal["project", "entered", "none"] = "none",
    catalogue: Catalogue | None = None,
) -> CostPlanResponse:
    """Regroup a bill into the NRM 1 elemental structure.

    Args:
        boq_id: The bill's id.
        boq_name: The bill's name.
        project_id: The owning project's id.
        currency: The base currency every amount is in.
        leaves: Every non-section position of the bill. Empty placeholder
            rows may be included; they are skipped.
        markups: The bill's active markup lines in cascade order, each with the
            amount the bill's own cascade gave it.
        gifa: Gross internal floor area in m2, or None.
        gifa_source: Where ``gifa`` came from.
        catalogue: The element table; the shipped NRM 1 table by default.

    Returns:
        The cost plan. ``direct_cost`` is the sum of ``leaves`` and
        ``grand_total`` is that plus the sum of ``markups``.
    """
    table = catalogue or load_nrm1_catalogue()
    if gifa is not None and gifa <= 0:
        gifa = None
        gifa_source = "none"

    element_buckets: dict[str, _Bucket] = {}
    group_level: dict[str, _Bucket] = {}
    group_level_codes: dict[str, set[str]] = {}
    unallocated = _Bucket()
    unallocated_rows: list[UnallocatedPosition] = []
    direct_cost = Decimal("0")
    position_count = 0
    inherited = 0

    for leaf in leaves:
        if leaf.placeholder and leaf.amount == 0:
            continue
        position_count += 1
        direct_cost += leaf.amount
        own_written = _raw_text(leaf.code) is not None
        written = leaf.code if own_written else leaf.inherited_code
        placement = place_code(written, table)
        if placement.allocated and not own_written:
            inherited += 1
        if placement.element_code is not None:
            element_buckets.setdefault(placement.element_code, _Bucket()).add(leaf.amount)
        elif placement.group_code is not None:
            group_level.setdefault(placement.group_code, _Bucket()).add(leaf.amount)
            group_level_codes.setdefault(placement.group_code, set()).add(
                normalise_code(written) or placement.group_code
            )
        else:
            unallocated.add(leaf.amount)
            if len(unallocated_rows) < MAX_LISTED_UNALLOCATED:
                unallocated_rows.append(
                    UnallocatedPosition(
                        id=leaf.id,
                        ordinal=leaf.ordinal,
                        description=leaf.description,
                        code=_raw_text(written),
                        reason=placement.reason,
                        total=leaf.amount,
                    )
                )

    markups_total = sum((m.amount for m in markups), Decimal("0"))
    grand_total = direct_cost + markups_total

    def subtotal(amount: Decimal) -> SubtotalRow:
        return SubtotalRow(
            total=amount,
            cost_per_m2=_ratio(amount, gifa),
            share_pct=_ratio(amount, grand_total, _HUNDRED),
        )

    def group_row(group: CatalogueGroup) -> GroupRow:
        elements: list[ElementRow] = []
        total = Decimal("0")
        count = 0
        for element in group.elements:
            bucket = element_buckets.get(element.code, _Bucket())
            total += bucket.total
            count += bucket.count
            elements.append(
                ElementRow(
                    code=element.code,
                    name=element.name,
                    position_count=bucket.count,
                    **subtotal(bucket.total).model_dump(),
                )
            )
        level: GroupLevelRow | None = None
        if group.code in group_level:
            bucket = group_level[group.code]
            total += bucket.total
            count += bucket.count
            level = GroupLevelRow(
                position_count=bucket.count,
                codes=sorted(group_level_codes.get(group.code, set()), key=_code_sort_key),
                **subtotal(bucket.total).model_dump(),
            )
        return GroupRow(
            code=group.code,
            name=group.name,
            kind=group.kind,
            position_count=count,
            elements=elements,
            group_level=level,
            **subtotal(total).model_dump(),
        )

    works = [group_row(g) for g in table.groups if g.kind == "works"]
    addons = [group_row(g) for g in table.groups if g.kind == "addon"]
    facilitating_total = sum((g.total for g in works if g.code == FACILITATING_GROUP), Decimal("0"))
    building_total = sum((g.total for g in works if g.code != FACILITATING_GROUP), Decimal("0"))

    has_scoped = any(m.scoped for m in markups)
    markup_rows: list[MarkupRow] = []
    running = direct_cost
    for line in markups:
        base: Decimal | None = None
        if not has_scoped and (line.markup_type or "percentage").lower() != "fixed":
            compounding = (line.apply_to or "direct_cost").lower() in ("cumulative", "subtotal")
            base = running if compounding else direct_cost
        running += line.amount
        markup_rows.append(
            MarkupRow(
                id=line.id,
                name=line.name,
                category=line.category,
                markup_type=line.markup_type,
                apply_to=line.apply_to,
                percentage=line.percentage,
                fixed_amount=line.fixed_amount,
                base=base,
                running_total=running,
                scoped=line.scoped,
                **subtotal(line.amount).model_dump(),
            )
        )

    warnings: list[str] = []
    if unallocated.count:
        warnings.append("unallocated_positions")
    if gifa is None:
        warnings.append("no_gifa")
    if markups and any(g.position_count for g in addons):
        warnings.append("addons_in_bill_and_markups")
    if has_scoped:
        warnings.append("scoped_markups")

    return CostPlanResponse(
        boq_id=boq_id,
        boq_name=boq_name,
        project_id=project_id,
        currency=currency,
        gifa=gifa,
        gifa_source=gifa_source,
        groups=works,
        facilitating_works_estimate=subtotal(facilitating_total),
        building_works_estimate=subtotal(building_total),
        addon_groups=addons,
        unallocated=UnallocatedBlock(
            position_count=unallocated.count,
            positions=unallocated_rows,
            positions_truncated=len(unallocated_rows) < unallocated.count,
            **subtotal(unallocated.total).model_dump(),
        ),
        direct_cost=subtotal(direct_cost),
        markups=markup_rows,
        markups_total=subtotal(markups_total),
        grand_total=subtotal(grand_total),
        position_count=position_count,
        allocated_count=position_count - unallocated.count,
        inherited_count=inherited,
        warnings=warnings,
    )


def _code_sort_key(code: str) -> tuple[int, ...]:
    """Sort dotted codes numerically, so ``5.10`` follows ``5.9``."""
    return tuple(int(part) for part in code.split(".") if part.isdigit())
