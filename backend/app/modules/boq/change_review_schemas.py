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
ProposalBasis = Literal["model_change", "rule_result"]


class BIMQuantityProposalRow(BaseModel):
    """One position whose linked BIM quantity moved with a new model version.

    ``previous_model_quantity`` is what the position's elements measure in its
    baseline version: the version it is linked to, or a later one whose
    quantity was accepted here. ``new_model_quantity`` is what they measure in
    the newest ready version, matched by stable id (or, for a quantity-map
    rule, every element the rule matches there). ``delta`` and ``total_delta``
    are against what the position holds now, so they are exactly what
    accepting the row changes.

    ``basis`` is ``model_change`` for a model that moved, and ``rule_result``
    for a rule aimed at an existing position whose result never became its
    quantity; there ``previous_model_quantity`` is the rule on the baseline
    and the comparison is with the stored quantity.
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
    # Line money is in the position's own currency (``currency``: its
    # ``metadata.currency``, else the project base). ``total_delta_base`` is
    # the same change in the project base currency, ``None`` when the project
    # has no usable rate for ``currency``.
    total_delta: str
    currency: str = ""
    total_delta_base: str | None = None
    method: Literal["unit", "rule"]
    basis: ProposalBasis = "model_change"
    status: ProposalStatus
    appliable: bool
    manual_override: bool
    model_id: uuid.UUID | None = None
    new_model_id: uuid.UUID | None = None
    new_model_ids: list[uuid.UUID] = Field(default_factory=list)
    model_name: str = ""
    model_version: str = ""
    element_count: int = 0
    modified_count: int = 0
    missing_count: int = 0
    added_count: int = 0


class BIMQuantityProposalResponse(BaseModel):
    """All proposals for one BOQ. Computing them writes nothing.

    ``total_delta`` is in the project base currency (``currency``) and sums
    the appliable rows that could be converted; ``unconverted_count`` says how
    many appliable rows are priced in a currency without a usable rate and are
    therefore not in it.
    """

    boq_id: uuid.UUID
    positions_checked: int
    appliable_count: int
    currency: str = ""
    total_delta: str
    unconverted_count: int = 0
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
    currency: str | None = None
    total_delta: str | None = None
    total_delta_base: str | None = None


class BIMQuantityApplyResponse(BaseModel):
    """What the apply wrote.

    ``total_delta`` is the sum over applied rows in the project base currency
    (``currency``); rows in a currency without a usable rate are counted in
    ``unconverted_count`` instead of being added at 1:1.
    """

    boq_id: uuid.UUID
    applied: int
    skipped: int
    currency: str = ""
    total_delta: str
    unconverted_count: int = 0
    results: list[BIMQuantityApplyResultRow]
