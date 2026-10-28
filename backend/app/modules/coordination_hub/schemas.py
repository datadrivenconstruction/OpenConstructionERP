# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic response schemas for the Coordination Hub module.

These are presentation-only DTOs; they never round-trip back through a
write path. Every numeric field is a plain ``int`` / ``float`` so the
JSON wire matches the BIM dashboards' existing convention (no
``Decimal`` leakage past the boundary - see ``feedback_no_orjson_default``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py - money fields are stored /
# accepted as Decimal but emitted as plain decimal strings in JSON.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# ── KPI rollup ─────────────────────────────────────────────────────────────


class FederationStats(BaseModel):
    """Federation rollup - count + composition."""

    count: int = 0
    total_members: int = 0
    total_elements: int = 0


class ClashDelta(BaseModel):
    """Run-to-run movement for the open clash queue."""

    new: int = 0
    resolved: int = 0
    reopened: int = 0


class ClashStats(BaseModel):
    """Clash rollup - open / resolved / ignored + last-run delta."""

    open_count: int = 0
    resolved_count: int = 0
    ignored_count: int = 0
    delta_since_last_run: ClashDelta = Field(default_factory=ClashDelta)
    last_run_at: datetime | None = None


class RulePackStats(BaseModel):
    """BIM requirement / rule-pack rollup."""

    installed_count: int = 0
    last_check_pass_count: int = 0
    last_check_fail_count: int = 0
    last_check_at: datetime | None = None


class SmartViewStats(BaseModel):
    """Smart-view inventory split by scope.

    ``project_count`` is a true per-project figure. ``user_count`` is
    GLOBAL ("personal views, all projects") - user-scoped views carry no
    project link, so the UI must label it accordingly rather than
    implying it is project-scoped.
    """

    user_count: int = 0
    project_count: int = 0


class BCFActivityStats(BaseModel):
    """BCF I/O activity over the last 30 days."""

    topics_exported_30d: int = 0
    topics_imported_30d: int = 0
    last_export_at: datetime | None = None


class CoordinationDashboardResponse(BaseModel):
    """Project-level Coordination Hub dashboard payload."""

    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    currency: str
    as_of: datetime
    federations: FederationStats = Field(default_factory=FederationStats)
    clashes: ClashStats = Field(default_factory=ClashStats)
    rule_packs: RulePackStats = Field(default_factory=RulePackStats)
    smart_views: SmartViewStats = Field(default_factory=SmartViewStats)
    bcf_activity: BCFActivityStats = Field(default_factory=BCFActivityStats)
    # v3 §10 - money is Decimal-as-string in JSON.
    open_cost_impact_total: Decimal = Decimal("0")

    @field_serializer("open_cost_impact_total", when_used="json")
    def _ser_open_cost_impact_total(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Trade matrix ───────────────────────────────────────────────────────────


class TradeMatrixCell(BaseModel):
    """One discipline-pair cell in the trade matrix.

    ``cost_impact`` is the summed open cost-impact (rework + labour) of the
    OPEN clashes in this discipline pair, computed via the
    :mod:`clash_cost_impact` kernel. It lets the heat-map weight a cell by
    money rather than raw count - a single high-severity Structural x MEP
    clash through a chiller can outweigh fifty cosmetic Arch x Arch ones.
    Emitted as a decimal string (v3 money convention); ``0`` when the
    cost-impact module is unavailable or the pair has no priced rework.
    """

    row: str
    col: str
    count: int = 0
    open: int = 0
    resolved: int = 0
    cost_impact: Decimal = Decimal("0")

    @field_serializer("cost_impact", when_used="json")
    def _ser_cost_impact(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class TradeMatrixResponse(BaseModel):
    """Trade-matrix grid for the dashboard heat-map."""

    project_id: uuid.UUID
    trades: list[str]
    cells: list[TradeMatrixCell]
    # Project display currency for the cost-weighted view; empty string
    # when the project carries no currency (no hard-coded EUR fallback).
    currency: str = ""
    # Sum of every cell's ``cost_impact`` - lets the UI render a "weighted
    # by EUR 1.2M open impact" caption without re-summing client-side.
    total_cost_impact: Decimal = Decimal("0")

    @field_serializer("total_cost_impact", when_used="json")
    def _ser_total_cost_impact(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Timeline ───────────────────────────────────────────────────────────────


class TimelineEvent(BaseModel):
    """One activity-stream entry.

    The label is built CLIENT-SIDE from ``type`` + ``params`` so the UI
    can localise it via i18next. ``params`` carries the interpolation
    values (``name``, ``total``, ``status`` …) the label template needs;
    the set of keys depends on ``type``. ``summary`` is retained as a
    pre-rendered English fallback for non-UI consumers (API exports,
    log lines) - the React timeline ignores it in favour of ``params``.
    """

    ts: datetime
    type: str
    # Interpolation params for the client-built label (name / total /
    # status …). Plain JSON scalars only - never a pre-rendered string.
    params: dict[str, str | int | None] = Field(default_factory=dict)
    # Pre-rendered English fallback for non-UI consumers (exports / logs).
    summary: str
    user_id: str | None = None
    # Optional deep-link target the UI can route to (e.g. /clash, /bcf).
    target: str | None = None


class TimelineResponse(BaseModel):
    """Activity timeline for a project."""

    project_id: uuid.UUID
    events: list[TimelineEvent]


# ── Canonical 6-trade taxonomy ─────────────────────────────────────────────

#: Fixed display ordering for the 6×6 trade matrix. Matches the
#: ``clash_cost_impact._normalise_discipline`` alias table so any
#: discipline label produced by the BIM importers maps to one of these
#: six rows/cols. ``other`` is the catch-all bucket - anything we can't
#: confidently bucket lands there rather than being silently dropped.
CANONICAL_TRADES: tuple[str, ...] = (
    "arch",
    "struct",
    "mep",
    "landscape",
    "civil",
    "other",
)


# ── Thresholds & alerts ────────────────────────────────────────────────────


#: Severity bucket of an evaluated threshold result.
ThresholdLevel = Literal["ok", "warn", "error"]


class ThresholdRow(BaseModel):
    """One configured threshold + its current evaluated state.

    ``current_value`` is the live metric value (e.g. count of open
    clashes, or cost-impact as a percentage of project budget).
    ``level`` is the current severity bucket: ``ok`` when ``enabled`` is
    False or no breach; ``warn`` when the metric crossed ``warn_value``
    but not ``error_value``; ``error`` once ``error_value`` is hit.
    """

    model_config = ConfigDict(from_attributes=True)

    metric: str
    warn_value: Decimal
    error_value: Decimal
    enabled: bool
    current_value: Decimal
    level: ThresholdLevel
    message: str = ""


class ThresholdAlert(BaseModel):
    """A single in-breach metric - surfaces in the dashboard banner."""

    metric: str
    current_value: Decimal
    threshold_value: Decimal
    level: ThresholdLevel
    message: str


class CoordinationThresholdsResponse(BaseModel):
    """List of every configured threshold for a project + alert summary."""

    project_id: uuid.UUID
    thresholds: list[ThresholdRow]
    alerts: list[ThresholdAlert]


class CoordinationThresholdUpdate(BaseModel):
    """PUT payload for editing one threshold.

    All three fields are optional so the caller can flip ``enabled``
    without restating the values; an empty payload is rejected so the
    PUT cannot be a no-op that still bumps ``updated_at``.
    """

    warn_value: Decimal | None = Field(default=None)
    error_value: Decimal | None = Field(default=None)
    enabled: bool | None = Field(default=None)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> CoordinationThresholdUpdate:
        if self.warn_value is None and self.error_value is None and self.enabled is None:
            raise ValueError("At least one of warn_value, error_value or enabled must be set.")
        return self
