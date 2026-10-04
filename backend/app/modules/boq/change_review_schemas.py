# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes for BOQ change review.

Quantities and money travel as strings, the same as on ``Position``, so a
figure never passes through a float between the database and the screen.
Every status and reason is a short machine code; the frontend owns the words.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Change flags ──────────────────────────────────────────────────────────


class ChangeFlagResponse(BaseModel):
    """One change flag with enough of its position to read it in a list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    boq_id: uuid.UUID
    position_id: uuid.UUID
    ordinal: str
    description: str
    source_type: str
    source_key: str
    source_id: str | None = None
    source_label: str
    source_version: str | None = None
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)
    detected_via: str
    status: str
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    created_at: datetime


class ChangeFlagListResponse(BaseModel):
    """Flags of one BOQ plus the counts the editor badge reads."""

    boq_id: uuid.UUID
    open_count: int
    reviewed_count: int
    flags: list[ChangeFlagResponse]


class ChangeFlagSummaryResponse(BaseModel):
    """Open flag counts for the toolbar badge, without the rows."""

    boq_id: uuid.UUID
    open_count: int
    open_by_source: dict[str, int] = Field(default_factory=dict)


class ChangeFlagScanResponse(BaseModel):
    """What one scan found and how many of those were new."""

    boq_id: uuid.UUID
    positions_checked: int
    bim_flags_found: int
    document_flags_found: int
    created: int
    open_count: int


class ChangeFlagReviewRequest(BaseModel):
    """Mark flags reviewed (or reopen them).

    Either name the flags in ``flag_ids`` or set ``all_open`` to close every
    open flag of the BOQ at once. Naming none of them is refused.
    """

    flag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    all_open: bool = False
    status: Literal["reviewed", "open"] = "reviewed"
    note: str | None = Field(default=None, max_length=2000)


class ChangeFlagReviewResponse(BaseModel):
    """How many flags the review call changed."""

    boq_id: uuid.UUID
    updated: int
    open_count: int


# ── BIM quantity proposals ────────────────────────────────────────────────


ProposalStatus = Literal["changed", "elements_missing", "no_quantity"]


class BIMQuantityProposalRow(BaseModel):
    """One position whose linked BIM quantity moved with a new model version.

    ``previous_model_quantity`` is what the linked elements measure in the
    version the position is linked to, ``new_model_quantity`` what the same
    elements (matched by stable id) measure in the newest version. ``delta``
    and ``total_delta`` are against what the position holds now, so they are
    exactly what accepting the row changes.
    """

    position_id: uuid.UUID
    ordinal: str
    description: str
    unit: str
    unit_rate: str
    current_quantity: str
    previous_model_quantity: str
    new_model_quantity: str
    delta: str
    current_total: str
    new_total: str
    total_delta: str
    method: Literal["unit", "rule"]
    status: ProposalStatus
    appliable: bool
    manual_override: bool
    model_id: uuid.UUID | None = None
    new_model_id: uuid.UUID | None = None
    model_name: str = ""
    model_version: str = ""
    element_count: int = 0
    modified_count: int = 0
    missing_count: int = 0


class BIMQuantityProposalResponse(BaseModel):
    """All proposals for one BOQ. Computing them writes nothing."""

    boq_id: uuid.UUID
    positions_checked: int
    appliable_count: int
    total_delta: str
    rows: list[BIMQuantityProposalRow]


class BIMQuantityApplyRequest(BaseModel):
    """The positions a person accepted. Figures are recomputed on the server."""

    position_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=5000)


class BIMQuantityApplyResultRow(BaseModel):
    """Outcome for one requested position."""

    position_id: uuid.UUID
    applied: bool
    reason: str
    old_quantity: str | None = None
    new_quantity: str | None = None
    old_total: str | None = None
    new_total: str | None = None


class BIMQuantityApplyResponse(BaseModel):
    """What the apply wrote. ``total_delta`` is the sum over applied rows."""

    boq_id: uuid.UUID
    applied: int
    skipped: int
    total_delta: str
    results: list[BIMQuantityApplyResultRow]
