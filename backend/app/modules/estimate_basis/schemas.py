# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate-basis request / response schemas.

Money rollups on the coverage summary arrive as Decimal-as-string, matching the
rest of the estimating surface; nothing here routes a total through a float.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

QualificationCategory = Literal["inclusion", "exclusion", "assumption"]


class QualificationItem(BaseModel):
    """One editable line of the basis-of-estimate."""

    id: str = Field(..., description="Stable id, unique within the document.")
    category: QualificationCategory
    text: str = Field(..., max_length=2000)
    trade_code: str | None = None
    trade_label: str | None = None
    basis: str = Field(default="", description="Why the line was drafted: present/absent/flag/standard.")
    source: Literal["auto", "manual"] = "auto"
    enabled: bool = True


class TradePresenceOut(BaseModel):
    """A trade present in the estimate, with its rollup."""

    code: str
    label: str
    core: bool
    position_count: int
    total: str = Field(..., description="Rolled-up total for the trade (Decimal string).")


class TradeRefOut(BaseModel):
    """A reference to a trade (used for absent/expected trades)."""

    code: str
    label: str


class CoverageSummary(BaseModel):
    """The present / absent / flagged picture the basis was drafted from."""

    present_trades: list[TradePresenceOut] = Field(default_factory=list)
    absent_trades: list[TradeRefOut] = Field(default_factory=list)
    total_positions: int = 0
    classified_positions: int = 0
    unclassified_positions: int = 0
    zero_rate_positions: int = 0
    missing_quantity_positions: int = 0
    provisional_positions: int = 0
    by_others_positions: int = 0


class FinancialsSummary(BaseModel):
    """The money the document qualifies, snapshotted at generation time.

    Every amount is a Decimal-as-string. The two trailing flags come straight
    from the BOQ roll-up and mean the same thing they mean there: the total
    below is not safe to read as final.
    """

    direct_cost: str = "0.00"
    markups_total: str = "0.00"
    grand_total: str = "0.00"
    currency: str = ""
    is_mixed_currency: bool = False
    has_unresolved_escalation: bool = False
    markup_count: int = 0
    boq_count: int = 0


class ProvenanceBucketOut(BaseModel):
    """One ``Position.source`` value, with its line count and share."""

    source: str
    family: str
    position_count: int = 0
    total: str = "0.00"
    share_pct: str = "0.0"


class ProvenanceFamilyOut(BaseModel):
    """One provenance family, rolled up across its sources."""

    family: str
    position_count: int = 0
    total: str = "0.00"
    share_pct: str = "0.0"


class ClassReasonOut(BaseModel):
    """One piece of evidence behind the suggested class.

    ``code`` is an enum key the client translates; ``value`` is the number that
    goes in the sentence. Nothing here is prose, so the reasoning survives
    translation.
    """

    code: str
    value: str = ""


class ClassSuggestionOut(BaseModel):
    """The class the platform suggests, and why.

    A suggestion is never the decision: :attr:`EstimateBasisResponse.estimate_class`
    stays ``None`` until an estimator confirms or overrides it.
    """

    suggested_class: int = 0
    base_class: int = 0
    reasons: list[ClassReasonOut] = Field(default_factory=list)


class ProvenanceSummaryOut(BaseModel):
    """Where the estimate's lines came from, by count and by value.

    ``share_basis`` names what the percentages are a share OF - ``value``
    normally, ``count`` for a bill that carries no money and could not be shared
    out by value. A reader is never left to guess which.
    """

    buckets: list[ProvenanceBucketOut] = Field(default_factory=list)
    families: list[ProvenanceFamilyOut] = Field(default_factory=list)
    total_positions: int = 0
    priced_total: str = "0.00"
    share_basis: str = "value"
    ai_position_count: int = 0
    ai_total: str = "0.00"
    scored_position_count: int = 0
    low_confidence_count: int = 0
    low_confidence_total: str = "0.00"
    model_linked_positions: int = 0
    stale_links: int = 0
    broken_links: int = 0
    suggestion: ClassSuggestionOut = Field(default_factory=ClassSuggestionOut)


class EstimateClassOption(BaseModel):
    """One AACE 18R-97 estimate class, as the platform publishes it.

    Served so the client never hardcodes a standard's numbers. The label and
    methodology are English source strings; the client keys its own translated
    copy off ``estimate_class`` and falls back to these.
    """

    estimate_class: int = Field(..., ge=1, le=5)
    label: str = ""
    accuracy_low: str = ""
    accuracy_high: str = ""
    definition_level_low: int = 0
    definition_level_high: int = 0
    methodology: str = ""


class EstimateClassCatalog(BaseModel):
    """The five estimate classes, most defined first."""

    items: list[EstimateClassOption] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    """Draft a fresh basis-of-estimate from a project's estimate contents."""

    project_id: uuid.UUID
    boq_id: uuid.UUID | None = Field(
        default=None,
        description="Restrict the derivation to one BOQ; omit to span the whole project.",
    )
    title: str | None = Field(default=None, max_length=255)
    currency: str = Field(
        default="",
        max_length=8,
        description="Override the estimate currency; blank resolves it from the project.",
    )
    base_date: str | None = Field(default=None, max_length=40)


class UpdateRequest(BaseModel):
    """Persist user edits to a drafted basis-of-estimate.

    Every field is optional so the client can patch a single list (e.g. only the
    exclusions) without echoing the whole document back.
    """

    title: str | None = Field(default=None, max_length=255)
    status: Literal["draft", "final"] | None = None
    notes: str | None = Field(default=None, max_length=8000)
    inclusions: list[QualificationItem] | None = None
    exclusions: list[QualificationItem] | None = None
    assumptions: list[QualificationItem] | None = None
    # The human half of the document. ``estimate_class`` accepts 0 as the way to
    # say "unstate it" - a client cannot send a bare ``None`` through an
    # all-optional patch and mean anything but "leave it alone".
    estimate_class: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="AACE class 1-5, lower is more defined. 0 clears the answer; omit to leave it alone.",
    )
    accuracy_low_pct: str | None = Field(default=None, max_length=20)
    accuracy_high_pct: str | None = Field(default=None, max_length=20)
    market_conditions: str | None = Field(default=None, max_length=8000)
    contingency_rationale: str | None = Field(default=None, max_length=8000)
    budget_target: dict | None = Field(
        default=None,
        description="Client budget target: {type, amount, currency, gross_net, contingency_mode, contingency_amount, source, date, notes}.",
    )


class EstimateBasisResponse(BaseModel):
    """A full basis-of-estimate document."""

    id: str
    project_id: str
    boq_id: str | None
    title: str
    status: str
    notes: str
    inclusions: list[QualificationItem]
    exclusions: list[QualificationItem]
    assumptions: list[QualificationItem]
    coverage: CoverageSummary
    financials: FinancialsSummary = Field(default_factory=FinancialsSummary)
    provenance: ProvenanceSummaryOut = Field(default_factory=ProvenanceSummaryOut)
    currency: str = ""
    pricing_date: str | None = None
    estimate_class: int | None = Field(
        default=None,
        description="AACE class the estimator stated. None means nobody has stated one.",
    )
    accuracy_low_pct: str = ""
    accuracy_high_pct: str = ""
    accuracy_low_amount: str = Field(
        default="",
        description="The accuracy band applied to the grand total. Blank when no class is stated.",
    )
    accuracy_high_amount: str = ""
    market_conditions: str = ""
    contingency_rationale: str = ""
    budget_target: dict | None = Field(
        default=None,
        description="Client budget target alongside the calculated estimate.",
    )
    generated_at: str | None
    created_at: str | None
    updated_at: str | None


class EstimateBasisSummary(BaseModel):
    """A lightweight row for the per-project document list."""

    id: str
    project_id: str
    boq_id: str | None
    title: str
    status: str
    inclusion_count: int
    exclusion_count: int
    assumption_count: int
    estimate_class: int | None = None
    grand_total: str = ""
    currency: str = ""
    generated_at: str | None
    created_at: str | None
    updated_at: str | None


class EstimateBasisListResponse(BaseModel):
    """The documents drafted for one project, newest first."""

    project_id: str
    items: list[EstimateBasisSummary] = Field(default_factory=list)
