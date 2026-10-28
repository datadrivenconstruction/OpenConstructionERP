# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ESG Site Performance Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Reporting period as an ISO year-month: four digits, dash, month 01-12.
PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"

# Serialize Decimal metric values as strings so no binary-float drift ever
# reaches the client (mirrors costs.schemas.DecimalMoney). The frontend parses
# these back with Number() for display only - never string arithmetic.
DecimalMoney = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str),
]


# ── Metric catalogue ──────────────────────────────────────────────────────────


class MetricDefinitionResponse(BaseModel):
    """One catalogue metric definition returned from the API."""

    key: str
    category: str
    label: str
    unit: str
    direction: str
    description: str = ""


# ── Entry Create / Update ─────────────────────────────────────────────────────


class EsgEntryCreate(BaseModel):
    """Create an ESG reading for a metric in a period.

    ``metric_key`` is checked against the catalogue and ``value`` / ``target``
    are range-checked (>= 0, and 0..100 for percentage metrics) in the service,
    so the caller gets a clear 400 with the exact reason.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    metric_key: str = Field(..., min_length=1, max_length=64)
    period: str = Field(..., pattern=PERIOD_PATTERN)
    value: DecimalMoney
    target: DecimalMoney | None = None
    note: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EsgEntryUpdate(BaseModel):
    """Partial update of an ESG reading.

    The metric and period are the entry's identity and are not editable; correct
    a mistake by deleting the entry and adding the right one.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    value: DecimalMoney | None = None
    target: DecimalMoney | None = None
    note: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class EsgEntryResponse(BaseModel):
    """An ESG reading returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    metric_key: str
    period: str
    value: DecimalMoney
    target: DecimalMoney | None = None
    note: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Summary (per-metric KPI + trend, grouped by pillar) ───────────────────────


class EsgTrendPoint(BaseModel):
    """One period point in a metric's short trend."""

    period: str
    value: DecimalMoney


class EsgMetricSummary(BaseModel):
    """Latest reading, target and short trend for a single metric.

    ``on_track`` compares the latest reading with its target using the metric's
    direction (lower/higher is better); it is ``None`` when there is no reading
    or no target. ``delta_pct`` is the signed percentage difference of the latest
    reading from its target, ``None`` when it cannot be computed (no target, or a
    zero target).
    """

    metric_key: str
    category: str
    label: str
    unit: str
    direction: str
    latest_period: str | None = None
    latest_value: DecimalMoney | None = None
    target: DecimalMoney | None = None
    on_track: bool | None = None
    delta_pct: float | None = None
    entry_count: int = 0
    trend: list[EsgTrendPoint] = Field(default_factory=list)


class EsgSummaryResponse(BaseModel):
    """Project ESG dashboard: every catalogue metric grouped by pillar.

    Every metric in the catalogue is present (with an empty trend when it has no
    readings yet) so the dashboard shows a complete, stable set of KPI cards.
    """

    project_id: UUID
    trend_periods: int
    latest_period: str | None = None
    by_category: dict[str, list[EsgMetricSummary]] = Field(default_factory=dict)
