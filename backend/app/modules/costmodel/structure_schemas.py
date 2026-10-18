# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schemas for the cost structure, code lists and split allocations.

Money and shares travel as decimal strings, like every other cost figure.
Problems are stable keys (``shares_do_not_add_up``, ``duplicate_code``) the UI
translates; the English ``message`` next to a validation finding is the
backend's translation for the caller's locale.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

AllocationMode = Literal["percent", "quantity"]


def _money(value: Decimal | None) -> str:
    if value is None or not isinstance(value, Decimal) or not value.is_finite():
        return "0"
    return format(value, "f")


# ── Code lists ───────────────────────────────────────────────────────────────


class CodeListSummary(BaseModel):
    """A code list a structure can be built from."""

    key: str
    name: str
    standard: str
    source: Literal["builtin", "pack", "custom"]
    pack_slug: str | None = None
    entry_count: int = 0
    depth: int = 0


class CodeListPage(BaseModel):
    """Every code list a structure can be built from, in one page (the set is small and bounded)."""

    items: list[CodeListSummary] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class CodeListEntryOut(BaseModel):
    """One code of a list."""

    code: str
    title: str
    parent: str | None = None
    level: int = 1


class CodeListDetail(CodeListSummary):
    """A whole code list, entries in tree order."""

    entries: list[CodeListEntryOut] = Field(default_factory=list)


class CodeListIssueOut(BaseModel):
    """One thing wrong with an uploaded row."""

    row: int | None = None
    code: str = ""
    problem: str
    params: dict[str, Any] = Field(default_factory=dict)


class CodeListImportResult(BaseModel):
    """What an import found. Nothing is stored unless ``ok`` and not ``dry_run``."""

    ok: bool
    dry_run: bool
    key: str
    name: str
    entry_count: int = 0
    depth: int = 0
    issues: list[CodeListIssueOut] = Field(default_factory=list)
    preview: list[CodeListEntryOut] = Field(default_factory=list)
    code_list: CodeListSummary | None = None


# ── The structure ────────────────────────────────────────────────────────────


class StructureNode(BaseModel):
    """One account of the cost structure with its money."""

    id: UUID
    parent_id: UUID | None = None
    code: str
    title: str
    name: str
    level: int
    classification_standard: str = ""
    status: str = "open"
    is_leaf_postable: bool = True
    own_amount: Decimal = Decimal("0")
    posted: Decimal = Decimal("0")
    children_total: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    line_count: int = 0
    child_count: int = 0

    @field_serializer("own_amount", "posted", "children_total", "total", when_used="json")
    def _ser(self, v: Decimal) -> str:
        return _money(v)


class SuspenseBucket(BaseModel):
    """Money on cost lines that resolves to no postable account."""

    kind: Literal["no_account", "invalid_account"]
    line_count: int = 0
    amount: Decimal = Decimal("0")
    line_ids: list[UUID] = Field(default_factory=list)

    @field_serializer("amount", when_used="json")
    def _ser(self, v: Decimal) -> str:
        return _money(v)


class StructureFinding(BaseModel):
    """A validation finding on the structure, message in the caller's language."""

    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str
    suggestion: str = ""
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class StructureTree(BaseModel):
    """The project's cost structure, tree-ordered, with suspense and findings."""

    project_id: UUID
    currency: str = ""
    standards: list[str] = Field(default_factory=list)
    nodes: list[StructureNode] = Field(default_factory=list)
    suspense: list[SuspenseBucket] = Field(default_factory=list)
    total: Decimal = Decimal("0")
    findings: list[StructureFinding] = Field(default_factory=list)

    @field_serializer("total", when_used="json")
    def _ser(self, v: Decimal) -> str:
        return _money(v)


class ApplyCodeListRequest(BaseModel):
    """Create the accounts of a code list in a project, optionally down to a level."""

    key: str = Field(..., min_length=1, max_length=40)
    max_level: int | None = Field(default=None, ge=1, le=12)


class ApplyCodeListResult(BaseModel):
    """How many accounts applying a code list added."""

    key: str
    accounts_created: int = 0


# ── Allocations (the vector of a bill position) ─────────────────────────────


class AllocationRowIn(BaseModel):
    """One share: onto a cost line, or onto an account (its line for this bill is found or made)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_line_id: UUID | None = None
    control_account_id: UUID | None = None
    share: Decimal = Field(..., gt=0, max_digits=20, decimal_places=6)

    @field_validator("share")
    @classmethod
    def _finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("share must be a finite number")
        return v


class PositionAllocationRequest(BaseModel):
    """The whole vector of one position. One row is a plain single allocation."""

    mode: AllocationMode = "percent"
    rows: list[AllocationRowIn] = Field(..., min_length=1, max_length=50)
    note: str = Field(default="", max_length=2000)


class AllocationRowOut(BaseModel):
    """One share as stored, with the money it carries."""

    cost_line_id: UUID
    cost_line_code: str = ""
    cost_line_description: str = ""
    account_id: UUID | None = None
    account_code: str = ""
    account_title: str = ""
    #: False when the line has no account, or a heading or closed one: its money then
    #: sits in a suspense bucket of the structure instead of on an account.
    account_postable: bool = False
    share: Decimal = Decimal("0")
    fraction: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")

    @field_serializer("share", "fraction", "amount", when_used="json")
    def _ser(self, v: Decimal) -> str:
        return _money(v)


class PositionAllocationOut(BaseModel):
    """The vector of one position.

    ``mode`` is ``single`` for a position on one cost line through
    ``cost_line_id``, ``percent`` or ``quantity`` for a split, and ``none`` for a
    position on no cost line. ``valid`` is False when stored shares no longer
    add up (a quantity split whose position was remeasured), with the problem
    key in ``problem``. ``in_suspense`` is True when at least one share lands on
    a cost line without a postable account, so part of the money is in a
    suspense bucket rather than on the structure.
    """

    position_id: UUID
    boq_id: UUID
    ordinal: str = ""
    description: str = ""
    unit: str = ""
    quantity: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    mode: Literal["single", "percent", "quantity", "none"]
    rows: list[AllocationRowOut] = Field(default_factory=list)
    valid: bool = True
    problem: str | None = None
    share_total: Decimal = Decimal("0")
    share_expected: Decimal = Decimal("0")
    in_suspense: bool = False

    @field_serializer("quantity", "total", "share_total", "share_expected", when_used="json")
    def _ser(self, v: Decimal) -> str:
        return _money(v)


class AllocationCoverage(BaseModel):
    """How much of a bill's value sits on the cost structure.

    The value splits three ways and adds back up to ``value_total``:
    ``value_allocated`` reaches a postable account, ``value_in_suspense`` sits on
    a cost line whose account is missing, a heading or closed, and
    ``value_unallocated`` is on no cost line at all. ``share_pct`` counts only
    the first part, so money in suspense never reads as covered.
    """

    boq_id: UUID
    positions_total: int = 0
    positions_allocated: int = 0
    positions_split: int = 0
    positions_invalid: int = 0
    value_total: Decimal = Decimal("0")
    value_allocated: Decimal = Decimal("0")
    value_unallocated: Decimal = Decimal("0")
    positions_in_suspense: int = 0
    value_in_suspense: Decimal = Decimal("0")
    share_pct: Decimal = Decimal("0")

    @field_serializer(
        "value_total", "value_allocated", "value_unallocated", "value_in_suspense", "share_pct", when_used="json"
    )
    def _ser(self, v: Decimal) -> str:
        return _money(v)


class BoqAllocations(BaseModel):
    """Every costed position of a bill with its vector, and the coverage."""

    boq_id: UUID
    project_id: UUID
    currency: str = ""
    coverage: AllocationCoverage
    positions: list[PositionAllocationOut] = Field(default_factory=list)
