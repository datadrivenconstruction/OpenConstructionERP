# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response schemas for estimate branches (variants) of a BOQ."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

BranchStatus = Literal["open", "merged", "archived"]
Resolution = Literal["source", "target"]


class BranchCreate(BaseModel):
    """Fork a branch from a bill (main or another branch), optionally from one of its snapshots."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    note: str = Field(default="", max_length=4000)
    snapshot_id: UUID | None = Field(
        default=None,
        description="Snapshot of the source bill to start from; the current state when omitted.",
    )


class BranchUpdate(BaseModel):
    """Rename a branch, change its note or archive / reopen it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=4000)
    status: Literal["open", "archived"] | None = None


class DesignOptionRef(BaseModel):
    """A design option a branch prices."""

    id: UUID
    name: str
    set_id: UUID | None = None
    set_name: str = ""
    boq_id: UUID | None = None


class BranchNode(BaseModel):
    """One bill in a branch tree: the main estimate or a branch of it."""

    boq_id: UUID
    name: str
    is_main: bool
    parent_boq_id: UUID | None = None
    status: str = "open"
    note: str = ""
    is_locked: bool = False
    created_at: str | None = None
    created_by: UUID | None = None
    author: str = ""
    position_count: int = 0
    direct_cost: str = "0"
    grand_total: str = "0"
    delta_vs_parent: str | None = None
    base_snapshot_id: UUID | None = None
    source_snapshot_id: UUID | None = None
    merged_at: str | None = None
    merged_by: UUID | None = None
    merge_snapshot_id: UUID | None = None
    design_option: DesignOptionRef | None = None


class BranchTreeResponse(BaseModel):
    """Every branch of a main estimate, flat with parent links, main first."""

    main_boq_id: UUID
    currency: str = ""
    can_merge: bool = False
    nodes: list[BranchNode]
    design_options: list[DesignOptionRef] = Field(default_factory=list)


class BranchCompareRow(BaseModel):
    """One position of a branch compare."""

    key: str
    change_type: Literal["added", "removed", "changed", "unchanged"]
    changed_fields: list[str] = Field(default_factory=list)
    ordinal: str
    description: str
    unit: str
    a_description: str | None = None
    b_description: str | None = None
    a_quantity: str | None = None
    b_quantity: str | None = None
    a_unit_rate: str | None = None
    b_unit_rate: str | None = None
    a_total: str = "0"
    b_total: str = "0"
    delta: str = "0"
    section_key: str = ""
    section: str = ""
    cost_group: str = ""


class BranchCompareGroup(BaseModel):
    """Totals of one section or one cost group on both sides."""

    key: str
    label: str
    total_a: str
    total_b: str
    delta: str


class BranchCompareSummary(BaseModel):
    """Counts and totals of a branch compare."""

    added: int = 0
    removed: int = 0
    changed: int = 0
    unchanged: int = 0
    total_a: str = "0"
    total_b: str = "0"
    delta: str = "0"
    delta_percent: float = 0.0


class BranchCompareResponse(BaseModel):
    """Bill A against bill B, position by position."""

    a_boq_id: UUID
    b_boq_id: UUID
    a_name: str
    b_name: str
    currency: str = ""
    summary: BranchCompareSummary
    rows: list[BranchCompareRow]
    by_section: list[BranchCompareGroup]
    by_cost_group: list[BranchCompareGroup]


class PlanFieldValues(BaseModel):
    """A field as the common ancestor, the source and the target hold it."""

    base: Any = None
    source: Any = None
    target: Any = None


class PlanItem(BaseModel):
    """What carrying one changed position across would do."""

    key: str
    action: Literal["add", "update", "remove"]
    conflict: bool = False
    ordinal: str
    description: str
    is_section: bool = False
    parent_key: str | None = None
    depth: int = 0
    fields: dict[str, PlanFieldValues] = Field(default_factory=dict)


class ApplyPlanRequest(BaseModel):
    """Preview carrying changes from a source bill into a target bill."""

    source_boq_id: UUID
    keys: list[str] | None = Field(
        default=None,
        max_length=5000,
        description="Lineage keys of the positions to carry; every change when omitted.",
    )


class ApplyPlanResponse(BaseModel):
    """The previewed plan."""

    source_boq_id: UUID
    target_boq_id: UUID
    base_known: bool
    items: list[PlanItem]
    conflicts: int = 0


class CherryPickRequest(ApplyPlanRequest):
    """Carry the named changes into the target, deciding every conflict."""

    resolutions: dict[str, Resolution] = Field(
        default_factory=dict,
        description="Per conflicting key: 'source' takes the source version, 'target' keeps the target's.",
    )


class MergeRequest(BaseModel):
    """Merge a branch back into its main estimate."""

    resolutions: dict[str, Resolution] = Field(default_factory=dict)
    include_markups: bool = Field(default=False, description="Replace main's markups with the branch's.")
    confirm: bool = Field(default=False, description="Must be true; the merge rewrites the main estimate.")


class ApplyResult(BaseModel):
    """What a cherry-pick or a merge wrote."""

    target_boq_id: UUID
    snapshot_id: UUID | None = None
    added: int = 0
    updated: int = 0
    removed: int = 0
    kept_target: int = 0
    skipped: list[str] = Field(default_factory=list)
    status: str | None = None


class DesignOptionLinkBody(BaseModel):
    """Point a design option at this branch, or clear the link with null."""

    option_id: UUID | None = None
