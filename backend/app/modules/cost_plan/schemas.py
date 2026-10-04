# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Response shapes for the NRM 1 elemental cost plan.

Every money figure travels as a plain decimal string (``"1234.5"``, never
``"1.2345E+3"``), so the browser formats it and never does arithmetic on a
float. Money is carried at full precision: the plan is a regrouping of the
bill, and rounding each row before it is summed is how a cost plan ends up a
cent away from the bill it was built from. Only the two derived ratios, cost
per m2 and share of total, are rounded, to two places, because nothing is
summed from them.

Element and group names are data from the NRM 1 table, not interface strings,
so they arrive here in the language of the standard. Everything else a reader
sees (column headings, the add-on labels, warnings) is a stable key the
frontend translates.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

__all__ = [
    "CostPlanResponse",
    "ElementRow",
    "GroupLevelRow",
    "GroupRow",
    "MarkupRow",
    "Money",
    "SubtotalRow",
    "UnallocatedBlock",
    "UnallocatedPosition",
]


def _plain_decimal(value: Decimal) -> str:
    """Render a Decimal as a positional string with no exponent."""
    return format(value, "f")


#: A Decimal that serialises to a positional string in JSON.
Money = Annotated[Decimal, PlainSerializer(_plain_decimal, return_type=str, when_used="json")]

#: Why a position sits where it does, as a stable key the UI translates.
#:
#: * ``matched`` - its code names an element in the table.
#: * ``group_level`` - its code names a group only (``"2"``).
#: * ``unknown_element`` - its group exists but the element does not
#:   (``"5.99"``); the money stays on the group as a group-level line.
#: * ``no_code`` - neither the position nor any parent carries an NRM code.
#: * ``invalid_code`` - the code is not an NRM number at all (``"abc"``).
#: * ``unknown_group`` - a well-formed number whose group NRM 1 does not have
#:   (``"15.1"``).
PlacementReason = Literal["matched", "group_level", "unknown_element", "no_code", "invalid_code", "unknown_group"]


class SubtotalRow(BaseModel):
    """One money line with its two derived ratios."""

    total: Money = Decimal("0")
    cost_per_m2: Money | None = Field(default=None, description="Total divided by GIFA; null without a GIFA.")
    share_pct: Money | None = Field(
        default=None, description="Percentage of the cost plan total; null when the total is zero."
    )


class ElementRow(SubtotalRow):
    """One NRM 1 element, for example 2.5 External walls."""

    code: str
    name: str
    position_count: int = 0


class GroupLevelRow(SubtotalRow):
    """Money coded to a group but not to one of its elements.

    Holds both a bare group code (``"2"``) and an element number the table does
    not list (``"5.99"``). ``codes`` names each distinct code that landed here,
    so an estimator can see whether it is a deliberate group-level line or a
    typo in an element number.
    """

    position_count: int = 0
    codes: list[str] = Field(default_factory=list)


class GroupRow(SubtotalRow):
    """One NRM 1 group element (0-14) with its elements."""

    code: str
    name: str
    kind: Literal["works", "addon"]
    position_count: int = 0
    elements: list[ElementRow] = Field(default_factory=list)
    group_level: GroupLevelRow | None = None


class UnallocatedPosition(BaseModel):
    """A bill position the plan could not place on any element."""

    id: uuid.UUID
    ordinal: str
    description: str
    code: str | None = Field(default=None, description="The code as written on the position, if any.")
    reason: PlacementReason
    total: Money


class UnallocatedBlock(SubtotalRow):
    """Everything not allocated to an element, listed rather than dropped.

    ``total`` and ``position_count`` always cover every unallocated position.
    ``positions`` is capped for a very large bill; ``positions_truncated`` says
    when the list is shorter than the count.
    """

    position_count: int = 0
    positions: list[UnallocatedPosition] = Field(default_factory=list)
    positions_truncated: bool = False


class MarkupRow(SubtotalRow):
    """One line of the bill's own markup cascade, read, never recomputed here.

    ``amount`` is ``total`` (kept under that name so every row shares one
    shape). ``base`` is the figure a single-stack line was computed on: the
    direct cost for ``direct_cost`` lines, the running subtotal before the line
    for ``cumulative`` and ``subtotal`` lines. It is null for a lump sum, and
    for every line when the bill carries section-scoped markups, because then
    a line earns on several bases at once and no single figure is honest.
    """

    id: uuid.UUID | None = None
    name: str
    category: str
    markup_type: str
    apply_to: str
    percentage: Money | None = None
    fixed_amount: Money | None = None
    base: Money | None = None
    running_total: Money = Decimal("0")
    scoped: bool = False


class CostPlanResponse(BaseModel):
    """An NRM 1 elemental cost plan rolled up from one bill of quantities.

    Reading order, top to bottom, is the order the plan is printed in:

    1. ``groups`` - group elements 0-8, each with its elements.
    2. ``works_estimate`` - their sum, the building works estimate.
    3. ``addon_groups`` - bill positions coded to groups 9-14
       (preliminaries, overheads and profit, fees, other costs, risk,
       inflation) that were priced as items in the bill.
    4. ``unallocated`` - positions with no usable NRM code.
    5. ``direct_cost`` - 1 + 3 + 4, equal to the bill's direct cost.
    6. ``markups`` - the bill's markup cascade in compounding order.
    7. ``grand_total`` - equal to the bill's grand total.
    """

    standard: Literal["NRM1"] = "NRM1"
    boq_id: uuid.UUID
    boq_name: str
    project_id: uuid.UUID
    currency: str = ""
    gifa: Money | None = None
    gifa_source: Literal["project", "entered", "none"] = "none"
    groups: list[GroupRow] = Field(default_factory=list)
    works_estimate: SubtotalRow = Field(default_factory=SubtotalRow)
    addon_groups: list[GroupRow] = Field(default_factory=list)
    unallocated: UnallocatedBlock = Field(default_factory=UnallocatedBlock)
    direct_cost: SubtotalRow = Field(default_factory=SubtotalRow)
    markups: list[MarkupRow] = Field(default_factory=list)
    markups_total: SubtotalRow = Field(default_factory=SubtotalRow)
    grand_total: SubtotalRow = Field(default_factory=SubtotalRow)
    position_count: int = 0
    allocated_count: int = 0
    inherited_count: int = Field(
        default=0, description="Positions placed through a parent section's code rather than their own."
    )
    warnings: list[str] = Field(default_factory=list, description="Stable warning keys the UI translates.")
