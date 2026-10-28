# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Payroll Pydantic schemas - request/response models.

Money is exposed as strings (Decimal-as-string) end to end so the JSON
never loses cents to binary-float rounding. The frontend parses them with
``Number(...)`` only for display.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Allowed coarse buckets (display/grouping only - NOT tax rules) and value modes.
DeductionType = Literal["tax", "social", "pension", "other"]
DeductionMode = Literal["fixed", "percentage"]


class PayrollDeductionResponse(BaseModel):
    """A single withholding line on a payslip returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    entry_id: UUID
    label: str
    deduction_type: str
    mode: str
    value: str
    base_amount: str
    amount: str
    currency: str
    ordinal: int
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class PayrollDeductionCreate(BaseModel):
    """Request body to add a deduction line to a payslip (entry).

    The amount is derived server-side: a ``fixed`` deduction uses ``value`` as
    the sum; a ``percentage`` deduction applies ``value`` percent to
    ``base_amount`` (or the entry gross when ``base_amount`` is omitted). The
    platform never supplies tax rates - the caller enters them.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    label: str = Field(min_length=1, max_length=160)
    deduction_type: DeductionType = "other"
    mode: DeductionMode = "fixed"
    # Decimal-as-string in / out: a non-negative fixed amount, or a percentage
    # in [0, 100] when ``mode='percentage'``.
    value: str = Field(default="0", max_length=50)
    # Optional explicit base for a percentage deduction. When omitted/blank the
    # service uses the parent entry's gross amount.
    base_amount: str | None = Field(default=None, max_length=50)

    @field_validator("value")
    @classmethod
    def _validate_value(cls, v: str) -> str:
        """Reject non-numeric / negative / non-finite values up front."""
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("value must be a number") from exc
        if not d.is_finite() or d < 0:
            raise ValueError("value must be a non-negative finite number")
        return str(d)

    @field_validator("base_amount")
    @classmethod
    def _validate_base(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("base_amount must be a number") from exc
        if not d.is_finite() or d < 0:
            raise ValueError("base_amount must be a non-negative finite number")
        return str(d)


class PayrollBatchGenerate(BaseModel):
    """Request body for generating a draft batch from field labour."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    # Optional ISO YYYY-MM-DD bounds. When omitted, all unbatched labour for
    # the project is aggregated. ``date_to`` is inclusive.
    date_from: str | None = Field(default=None, max_length=20)
    date_to: str | None = Field(default=None, max_length=20)
    period_label: str | None = Field(default=None, max_length=120)
    notes: str = Field(default="", max_length=2000)


class PayrollEntryResponse(BaseModel):
    """A single payroll line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    batch_id: UUID
    resource_id: UUID | None
    worker: str
    work_date: str | None
    hours: str
    rate: str
    # ``amount`` is GROSS pay; ``net_amount`` is gross - sum(deductions).
    amount: str
    net_amount: str
    currency: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    deductions: list[PayrollDeductionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PayrollBatchResponse(BaseModel):
    """A payroll batch (without entries) returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period_label: str
    period_start: str | None
    period_end: str | None
    status: str
    currency: str
    total_hours: str
    # ``total_amount`` is batch GROSS; net = gross - total_deductions.
    total_amount: str
    total_deductions: str
    total_net: str
    entry_count: int
    notes: str
    created_by: UUID | None
    submitted_at: datetime | None = None
    submitted_by: UUID | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    posted_at: datetime | None = None
    posted_by: UUID | None = None
    gl_transaction_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class PayrollBatchDetailResponse(PayrollBatchResponse):
    """A payroll batch with its entries expanded."""

    entries: list[PayrollEntryResponse] = Field(default_factory=list)


class ReconciliationRow(BaseModel):
    """One reconciliation line: batch hours vs source field hours per worker.

    ``delta_hours`` is ``batch_hours - source_hours``; a non-zero delta flags a
    batch that drifted from the live field data (e.g. a report edited after the
    batch was generated). All hour figures are Decimal-as-string.
    """

    model_config = ConfigDict(extra="ignore")

    worker_key: str
    work_date: str | None
    resource_id: UUID | None = None
    batch_hours: str
    source_hours: str
    delta_hours: str
    matched: bool


class ReconciliationResponse(BaseModel):
    """Reconciliation of a batch against the live field-labour sources."""

    model_config = ConfigDict(extra="ignore")

    batch_id: UUID
    project_id: UUID
    batch_total_hours: str
    source_total_hours: str
    delta_total_hours: str
    balanced: bool
    rows: list[ReconciliationRow] = Field(default_factory=list)


class PayrollExportRow(BaseModel):
    """A single export row (JSON export; CSV mirrors these columns)."""

    model_config = ConfigDict(extra="ignore")

    worker: str
    resource_id: str
    work_date: str
    hours: str
    rate: str
    amount: str
    deductions: str
    net_amount: str
    currency: str
    source: str


class PayrollExportResponse(BaseModel):
    """JSON export envelope for ERP handoff."""

    model_config = ConfigDict(extra="ignore")

    batch_id: UUID
    project_id: UUID
    period_label: str
    status: str
    currency: str
    total_hours: str
    total_amount: str
    total_deductions: str
    total_net: str
    rows: list[PayrollExportRow] = Field(default_factory=list)


class LabourCostResponse(BaseModel):
    """Live labour-cost rollup for a project (base currency)."""

    model_config = ConfigDict(extra="ignore")

    project_id: UUID
    currency: str
    labour_cost: str
    total_hours: str
