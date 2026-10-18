# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control request and response models.

Money goes out as plain decimal strings, like every other cost-domain
response, so a client never parses a float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer, field_validator

from app.modules.costmodel.cost_control import COST_STAGES
from app.modules.costmodel.forecast_docs import EVIDENCE_KINDS
from app.modules.costmodel.schemas import _serialise_money

Money = Annotated[Decimal, PlainSerializer(_serialise_money, return_type=str, when_used="json")]
OptionalMoney = Annotated[Decimal | None, PlainSerializer(_serialise_money, return_type=str | None, when_used="json")]

#: Rows that can be put on a cost line from cost control (see costmodel.inheritance_service).
VectorKind = Literal["contract_line", "po_item", "contract", "change_order_item", "invoice_line"]

RowKind = Literal["cost_line", "contract", "unassigned", "changes_without_contract", "other", "remaining", "allowance"]

#: A project's forecast method, or a line's.
ForecastMethod = Literal["best_available", "maximum", "evm_cpi", "manual"]
#: The methods a line can be set to by choice; ``manual`` is set by entering an amount.
LineForecastMethod = Literal["best_available", "maximum", "evm_cpi"]
#: Where a line's method comes from: the project, the line's own choice, or a person's amount.
MethodOrigin = Literal["project", "line", "manual"]
SnapshotStatus = Literal["draft", "frozen"]


class ForecastOverrideInfo(BaseModel):
    """A manual forecast; ``closed_at`` is empty while it is the one in force."""

    id: UUID
    amount: Money
    reason: str
    document_ref: str = ""
    document_id: UUID | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    closed_at: datetime | None = None


class CostControlRow(BaseModel):
    """One row of the report: a cost line, a contract, or money with no cost line."""

    key: str
    kind: RowKind
    code: str = ""
    description: str = ""
    account_id: str | None = None
    status: str = ""
    budget: Money = Decimal("0")
    estimate: Money = Decimal("0")
    planned: Money = Decimal("0")
    awarded: Money = Decimal("0")
    changes: Money = Decimal("0")
    committed: Money = Decimal("0")
    certified: Money = Decimal("0")
    paid: Money = Decimal("0")
    # Measured quantity times the contract rate, and supplier invoices (net after agreed deductions).
    measured: Money = Decimal("0")
    invoiced: Money = Decimal("0")
    pending_changes: Money = Decimal("0")
    forecast: Money = Decimal("0")
    forecast_source: str = "none"
    automatic_forecast: Money = Decimal("0")
    automatic_source: str = "none"
    variance: Money = Decimal("0")
    variance_pct: OptionalMoney = None
    override: ForecastOverrideInfo | None = None
    # The method the forecast was worked out with, and whether it could be (see cost_control.MethodOutcome).
    forecast_method: str = "best_available"
    method_origin: MethodOrigin = "project"
    method_applied: bool = True
    method_comment: str = ""


class CostControlAccount(BaseModel):
    """A control account the cost lines are grouped under."""

    id: str
    code: str
    name: str
    # The account's own title; empty when its code list has none (then ``name`` is shown).
    title: str = ""
    parent_id: str | None = None
    level: int = 1
    # Money planned on the account itself; it also appears as an ``allowance`` row.
    own_amount: Money = Decimal("0")


class CostControlFinding(BaseModel):
    """Something worth a look, produced by the ``cost_control`` validation rules."""

    rule_id: str
    severity: Literal["warning", "info"]
    line_key: str | None = None
    code: str = ""
    amount: Money = Decimal("0")
    details: dict[str, str] = Field(default_factory=dict)


class SnapshotSummary(BaseModel):
    """A saved snapshot, without its rows."""

    id: UUID
    taken_on: str
    stage: str
    label: str = ""
    note: str = ""
    currency: str = ""
    totals: dict[str, str] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime | None = None
    status: SnapshotStatus = "frozen"
    frozen_at: datetime | None = None
    frozen_by: str | None = None
    previous_snapshot_id: UUID | None = None
    # The forecast method and evidence threshold in force when the figures were taken.
    forecast_method: str = "best_available"
    threshold_amount: Money = Decimal("0")
    threshold_pct: OptionalMoney = None


class SnapshotPage(BaseModel):
    """Saved forecasts, oldest first, in the paging envelope every register uses."""

    items: list[SnapshotSummary] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class CostControlReport(BaseModel):
    """The cost control report for one project, along one axis."""

    project_id: UUID
    currency: str
    axis: Literal["cost_line", "contract"]
    as_of: str
    totals: dict[str, str]
    rows: list[CostControlRow]
    accounts: list[CostControlAccount] = Field(default_factory=list)
    findings: list[CostControlFinding] = Field(default_factory=list)
    last_snapshot: SnapshotSummary | None = None
    forecast_method: str = "best_available"


class SnapshotCreateRequest(BaseModel):
    """Save the report as it stands today."""

    stage: str = "forecast"
    label: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=4000)

    @field_validator("stage")
    @classmethod
    def _known_stage(cls, v: str) -> str:
        if v not in COST_STAGES:
            raise ValueError(f"stage must be one of {', '.join(COST_STAGES)}")
        return v


class EvidenceItem(BaseModel):
    """One piece of evidence behind a forecast move: a project document, minutes, or another reference."""

    kind: Literal["document", "minutes", "other"] = "document"
    ref: str = Field(default="", max_length=500)
    document_id: UUID | None = None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in EVIDENCE_KINDS:
            raise ValueError(f"kind must be one of {', '.join(EVIDENCE_KINDS)}")
        return v

    @field_validator("ref")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class SnapshotNoteRequest(BaseModel):
    """The comment and evidence behind one line of a draft snapshot."""

    comment: str = Field(default="", max_length=4000)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=20)


class SnapshotLine(BaseModel):
    """One line of a snapshot with its move since the previous frozen snapshot and its documentation."""

    key: str
    kind: str = ""
    code: str = ""
    description: str = ""
    source: str = "none"
    method: str = "best_available"
    forecast: Money = Decimal("0")
    committed: Money = Decimal("0")
    #: The previous frozen snapshot's forecast; empty when the line is new.
    previous: OptionalMoney = None
    delta: Money = Decimal("0")
    delta_pct: OptionalMoney = None
    needs_evidence: bool = False
    documented: bool = False
    comment: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    note_updated_at: datetime | None = None


class SnapshotDetail(SnapshotSummary):
    """A saved snapshot with its rows, its documented lines and, for a draft, what still blocks freezing."""

    rows: list[dict[str, str]] = Field(default_factory=list)
    lines: list[SnapshotLine] = Field(default_factory=list)
    previous: SnapshotSummary | None = None
    findings: list[ForecastFinding] = Field(default_factory=list)


class ForecastOverrideRequest(BaseModel):
    """A person's forecast for one cost line. The reason is required."""

    amount: Decimal = Field(..., max_digits=18, decimal_places=2)
    reason: str = Field(..., min_length=3, max_length=2000)
    document_ref: str = Field(default="", max_length=255)
    document_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Give a short reason for the forecast")
        return v

    @field_validator("amount")
    @classmethod
    def _finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("amount must be a finite number")
        return v


class LineHistoryPoint(BaseModel):
    """The line as a saved snapshot recorded it."""

    snapshot_id: UUID
    taken_on: str
    stage: str
    label: str = ""
    forecast: Money = Decimal("0")
    forecast_source: str = "none"
    committed: Money = Decimal("0")
    certified: Money = Decimal("0")


class LineChangeEvent(BaseModel):
    """An approved change that moved money on this line."""

    approved_on: str | None = None
    source_kind: str
    source_code: str = ""
    contract_code: str = ""
    amount: Money = Decimal("0")


class MethodOutcomeInfo(BaseModel):
    """What one forecast method makes of a line."""

    method: ForecastMethod
    amount: Money
    source: str
    applied: bool = True
    progress: OptionalMoney = None
    cpi: OptionalMoney = None
    earned: OptionalMoney = None
    actual: OptionalMoney = None


class LineMethodChoice(BaseModel):
    """The forecast method one cost line was set to, and why."""

    cost_line_id: UUID
    method: LineForecastMethod
    comment: str = ""
    updated_by: str | None = None
    updated_at: datetime | None = None


class LineMethodRequest(BaseModel):
    """Read a line with another forecast method than the project's. A comment says why (rule V22 asks for it)."""

    method: LineForecastMethod
    comment: str = Field(default="", max_length=2000)

    @field_validator("comment")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LineHistory(BaseModel):
    """Why a line's forecast is what it is: snapshots, changes and manual forecasts."""

    cost_line_id: UUID
    code: str
    description: str = ""
    currency: str = ""
    current: CostControlRow
    snapshots: list[LineHistoryPoint] = Field(default_factory=list)
    changes: list[LineChangeEvent] = Field(default_factory=list)
    overrides: list[ForecastOverrideInfo] = Field(default_factory=list)
    project_method: str = "best_available"
    method_choice: LineMethodChoice | None = None
    #: Every method on this line side by side, so the choice is made on figures.
    methods: list[MethodOutcomeInfo] = Field(default_factory=list)


class UnassignedItem(BaseModel):
    """A contract line, order item or contract without a schedule whose money is on no cost line yet."""

    kind: Literal["contract_line", "po_item", "contract"]
    id: UUID
    group_id: UUID
    group_code: str = ""
    group_title: str = ""
    code: str = ""
    description: str = ""
    amount: Money


class UnassignedPage(BaseModel):
    """Unassigned lines, one page of them, contract lines first."""

    items: list[UnassignedItem]
    total: int
    offset: int
    limit: int


class AssignTarget(BaseModel):
    kind: VectorKind
    id: UUID


class AssignRequest(BaseModel):
    """Put these rows on one cost line.

    A row that inherits another cost line is overridden onto this one, which
    needs ``reason``; it is recorded on the row with who and when.
    """

    cost_line_id: UUID
    items: list[AssignTarget] = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=2000)


class AssignResult(BaseModel):
    assigned: int


# ── The chain panel: suspense buckets, rules V6 to V10 and V15, their fixes ──


class SuspenseItem(BaseModel):
    """One row with money on no cost line."""

    kind: VectorKind
    id: UUID
    group_id: UUID
    group_code: str = ""
    group_title: str = ""
    code: str = ""
    description: str = ""
    amount: Money
    #: True when the row has something above it that names a cost line.
    can_inherit: bool = False


class SuspenseBucket(BaseModel):
    """The rows of one kind on no cost line; count and amount are for all of them."""

    kind: VectorKind
    count: int
    amount: Money
    inheritable: int
    #: True when the bucket's money is in the report's "not on any cost line" row.
    in_report: bool
    items: list[SuspenseItem] = Field(default_factory=list)


class ChainFinding(BaseModel):
    """A finding of the chain rules, message in the caller's language."""

    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str
    suggestion: str = ""
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ChainReport(BaseModel):
    """Suspense buckets and chain findings of one project."""

    project_id: UUID
    currency: str = ""
    buckets: list[SuspenseBucket] = Field(default_factory=list)
    findings: list[ChainFinding] = Field(default_factory=list)


class SetVectorRequest(BaseModel):
    """Put one row on a cost line (``set``), back on what it inherits (``inherit``), or off (``clear``)."""

    kind: VectorKind
    id: UUID
    mode: Literal["set", "inherit", "clear"] = "set"
    cost_line_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=2000)


class SetVectorResult(BaseModel):
    cost_line_id: UUID | None = None
    source: str | None = None
    override: bool = False


class InheritResult(BaseModel):
    """How many rows of each kind took the account they inherit."""

    contract_line: int = 0
    change_order_item: int = 0
    invoice_line: int = 0


class DirectCostRequest(BaseModel):
    """The cost line a supplier invoice without a contract is recorded on."""

    cost_line_id: UUID


class DirectCostResult(BaseModel):
    contract_id: UUID
    contract_code: str
    contract_line_id: UUID | None = None


# ── Forecast method, documentation and comparison ─────────────────────────


class CostControlSettingsInfo(BaseModel):
    """A project's forecast method and the move above which a line needs evidence."""

    project_id: UUID
    forecast_method: ForecastMethod = "best_available"
    evidence_threshold_amount: Money = Decimal("0")
    #: Percent of the previous forecast; empty leaves the percentage test out.
    evidence_threshold_pct: OptionalMoney = Decimal("10")
    #: True while the project has never stored settings and reads the defaults.
    is_default: bool = True
    updated_by: str | None = None
    updated_at: datetime | None = None


class CostControlSettingsRequest(BaseModel):
    """Store a project's forecast method and evidence threshold."""

    forecast_method: ForecastMethod = "best_available"
    evidence_threshold_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    evidence_threshold_pct: Decimal | None = Field(default=Decimal("10"), ge=0, le=1000, max_digits=7, decimal_places=2)

    @field_validator("evidence_threshold_amount", "evidence_threshold_pct")
    @classmethod
    def _finite(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not v.is_finite():
            raise ValueError("must be a finite number")
        return v


class ForecastFinding(BaseModel):
    """A finding of rules V19, V20 or V22, message in the caller's language."""

    rule_id: str
    rule_number: str
    severity: Literal["error", "warning", "info"]
    message: str
    suggestion: str = ""
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ForecastPanel(BaseModel):
    """The project's forecast method, how many lines use each, and the documentation checks."""

    project_id: UUID
    currency: str = ""
    settings: CostControlSettingsInfo
    #: Cost lines per method actually in force (after a line's own choice or amount).
    method_counts: dict[str, int] = Field(default_factory=dict)
    #: Lines whose chosen method had nothing to work with, so the best available figure stands in.
    fallback_lines: int = 0
    line_choices: int = 0
    manual_lines: int = 0
    open_draft: SnapshotSummary | None = None
    findings: list[ForecastFinding] = Field(default_factory=list)


class SnapshotFreezeRefused(BaseModel):
    """Why a draft could not be frozen: the lines rule V20 still points at."""

    message: str
    findings: list[ForecastFinding] = Field(default_factory=list)


class ComparisonColumn(BaseModel):
    """One compared state: a snapshot, or today's figures (``id`` empty, ``status`` ``live``)."""

    id: UUID | None = None
    taken_on: str
    stage: str = "forecast"
    label: str = ""
    status: Literal["draft", "frozen", "live"] = "frozen"
    total: Money = Decimal("0")


class ComparisonRow(BaseModel):
    """One line across the compared states; an empty value where a state does not have the line."""

    key: str
    code: str = ""
    description: str = ""
    kind: str = ""
    values: list[OptionalMoney] = Field(default_factory=list)
    delta: Money = Decimal("0")
    delta_pct: OptionalMoney = None


class SnapshotMatrix(BaseModel):
    """Several snapshots side by side, oldest first."""

    project_id: UUID
    currency: str = ""
    columns: list[ComparisonColumn] = Field(default_factory=list)
    rows: list[ComparisonRow] = Field(default_factory=list)


class LadderStepInfo(BaseModel):
    """One line's move between two states, why, and what backs it."""

    key: str
    code: str = ""
    description: str = ""
    kind: str = ""
    before: OptionalMoney = None
    after: OptionalMoney = None
    delta: Money
    cause: Literal["new", "removed", "method", "source", "value"]
    source_before: str = ""
    source_after: str = ""
    method_before: str = ""
    method_after: str = ""
    comment: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)


class DeltaLadder(BaseModel):
    """From one total to the other, line by line, largest move first; small moves gathered in ``other``."""

    project_id: UUID
    currency: str = ""
    start_column: ComparisonColumn
    end_column: ComparisonColumn
    start: Money
    end: Money
    steps: list[LadderStepInfo] = Field(default_factory=list)
    other: Money = Decimal("0")
    other_count: int = 0


#: The phase layers of the comparison, left to right as the life of a cost.
PHASE_LAYERS: tuple[str, ...] = (
    "budget",
    "estimate",
    "tender",
    "awarded",
    "changes",
    "committed",
    "pending",
    "measured",
    "certified",
    "invoiced",
    "paid",
    "forecast",
)


class PhaseRow(BaseModel):
    """One account (with everything below it) or one cost line across the phase layers."""

    key: str
    kind: Literal["account", "cost_line", "allowance", "unassigned"]
    account_id: str | None = None
    parent_key: str | None = None
    level: int = 1
    code: str = ""
    description: str = ""
    values: dict[str, Money] = Field(default_factory=dict)
    #: Each layer as a percentage of the plan (budget, else estimate); empty without a plan.
    pct: dict[str, str | None] = Field(default_factory=dict)
    #: Measured work and invoices as a percentage of the commitment.
    progress_pct: str | None = None
    invoiced_pct: str | None = None


class PhaseComparison(BaseModel):
    """Every layer of the project's cost side by side on its account tree."""

    project_id: UUID
    currency: str = ""
    as_of: str
    layers: list[str] = Field(default_factory=lambda: list(PHASE_LAYERS))
    rows: list[PhaseRow] = Field(default_factory=list)
    totals: PhaseRow
