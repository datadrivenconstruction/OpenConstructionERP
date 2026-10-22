# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response schemas of the procurement concept API.

Money travels as a decimal string ("1250000.00"); a JSON number for an amount
is refused (422), so no float ever touches a threshold comparison. Calendar
days are ``YYYY-MM-DD``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.procurement_concept.catalogue import CODE_PATTERN, parse_amount

# NUMERIC(18, 2): sixteen integer digits and two decimals.
MAX_MONEY = Decimal("9999999999999999.99")


def _money(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        out = parse_amount(v)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if out < 0:
        raise ValueError("amount must not be negative")
    if out > MAX_MONEY:
        raise ValueError("amount is too large")
    if -out.as_tuple().exponent > 2:
        raise ValueError("amount has more than two decimals")
    return out


class _In(BaseModel):
    """Request body. Absent means "keep"; an explicit ``null`` is allowed only for the fields in ``clearable``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # Fields a caller may clear with ``null``. For every other field ``null`` is a 422: it would otherwise
    # reach a NOT NULL column.
    clearable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _refuse_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            bad = sorted(k for k, v in data.items() if v is None and k in cls.model_fields and k not in cls.clearable)
            if bad:
                raise ValueError(f"null is not allowed for: {', '.join(bad)}")
        return data


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


# ── Concept ──────────────────────────────────────────────────────────────


class ConceptActionIn(BaseModel):
    """Body of a concept action. Only ``reopen`` reads it: the reason is recorded with the reopening."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class ConceptSet(_In):
    """Create or change the concept. Absent fields keep their value."""

    clearable: ClassVar[frozenset[str]] = frozenset({"governance_document_id", "default_profile_id"})

    catalogue_source: Literal["shipped", "tenant"] | None = None
    catalogue_id: str | None = Field(default=None, min_length=1, max_length=64)
    catalogue_version: int | None = Field(default=None, ge=1)
    # Codes of the pinned catalogue (a company catalogue may define its own); checked against it on save.
    jurisdiction: str | None = Field(default=None, pattern=CODE_PATTERN, max_length=20)
    client_type: str | None = Field(default=None, pattern=CODE_PATTERN, max_length=20)
    # Absent on create = take module 3's owner capability (public_client), else False.
    public_client: bool | None = None
    vat_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    # A gate code of the project, or "" to use the gate the governance catalogue tags. Manage permission.
    release_gate_code: str | None = Field(default=None, max_length=64)
    governance_document_id: uuid.UUID | None = None
    default_profile_id: uuid.UUID | None = None

    @field_validator("vat_rate_pct", mode="before")
    @classmethod
    def _vat(cls, v: Any) -> Any:
        return _money(v)


# ── Packages ─────────────────────────────────────────────────────────────


class PackagePut(_In):
    """Procurement attributes of one ContractPackage (created on first PUT)."""

    clearable: ClassVar[frozenset[str]] = frozenset(
        {
            "advance_release_kind",
            "advance_release_id",
            "estimated_value",
            "cost_ref_kind",
            "cost_ref_id",
            "procedure_code",
            "tender_basis",
            "framework_agreement_id",
            "need_date",
            "need_activity_id",
            "lead_time_days",
            "procedure_days",
            "planned_start",
            "prequal_profile_id",
        }
    )

    split_basis: Literal["trade", "section", "system", "whole"] | None = None
    is_advance: bool | None = None
    advance_reason: str | None = Field(default=None, max_length=4000)
    advance_release_kind: Literal["gate_decision", "condition", "commitment"] | None = None
    advance_release_id: uuid.UUID | None = None
    estimated_value: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    # The BOQ section whose positions become the scope lines of the execution vehicle. It is the only cost
    # reference the module reads, so it is the only one it accepts.
    cost_ref_kind: Literal["boq_section"] | None = None
    cost_ref_id: uuid.UUID | None = None
    lot_group: str | None = Field(default=None, max_length=64)
    small_lot_exemption: bool | None = None
    procedure_code: str | None = Field(default=None, max_length=64)
    tender_basis: Literal["detailed", "functional", "mixed"] | None = None
    framework_agreement_id: uuid.UUID | None = None
    evaluation_method: Literal["lowest_price", "best_value"] | None = None
    # Award criteria and their weights in percent, e.g. {"price": "60", "quality": "40"}; empty or summing to 100.
    evaluation_weights: dict[str, Decimal] | None = Field(default=None, max_length=20)
    need_date: date | None = None
    # A milestone of the project's schedule (for example one of the framework schedule) that owns the need date.
    need_activity_id: uuid.UUID | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=1500)
    procedure_days: int | None = Field(default=None, ge=0, le=1500)
    planned_start: date | None = None
    prequal_profile_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=8000)

    @field_validator("estimated_value", mode="before")
    @classmethod
    def _value(cls, v: Any) -> Any:
        return _money(v)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @field_validator("evaluation_weights")
    @classmethod
    def _weights(cls, v: dict[str, Decimal] | None) -> dict[str, str] | None:
        if not v:
            return v
        for name, weight in v.items():
            if not name.strip() or len(name) > 64:
                raise ValueError("an award criterion needs a name of at most 64 characters")
            if not weight.is_finite() or weight < 0 or weight > 100:
                raise ValueError("an award criterion weight is a percentage between 0 and 100")
        if sum(v.values(), Decimal("0")) != 100:
            raise ValueError("award criterion weights must sum to 100")
        return {name: format(weight, "f") for name, weight in v.items()}

    @model_validator(mode="after")
    def _cost_reference(self) -> PackagePut:
        if (self.cost_ref_kind is None) != (self.cost_ref_id is None) and (
            "cost_ref_kind" in self.model_fields_set or "cost_ref_id" in self.model_fields_set
        ):
            raise ValueError("cost_ref_kind and cost_ref_id are set or cleared together")
        return self


class PackageStateIn(_In):
    action: Literal["hold", "resume", "cancel"]
    reason: str = Field(default="", max_length=4000)


class RuleOverrideIn(_In):
    """Override one rule outcome of a snapshot. The reason is mandatory and checked by the service."""

    rule_code: str = Field(min_length=1, max_length=64)
    outcome: Literal["pass", "warn", "fail"]
    reason: str = Field(default="", max_length=4000)


# ── Prequalification ─────────────────────────────────────────────────────


class ProfileCriterion(_In):
    code: str = Field(min_length=1, max_length=64)
    weight: Decimal = Field(default=Decimal("0"), le=100)

    @field_validator("weight", mode="before")
    @classmethod
    def _w(cls, v: Any) -> Any:
        return _money(v)


class ProfileIn(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"package_id"})

    package_id: uuid.UUID | None = None
    name: str = Field(default="", max_length=255)
    criteria: list[ProfileCriterion] = Field(default_factory=list, max_length=60)
    # Scores run from 0 to 100, so the pass mark does too.
    pass_mark: Decimal = Field(default=Decimal("0"), le=100)
    validity_months: int = Field(default=12, ge=1, le=120)

    @field_validator("pass_mark", mode="before")
    @classmethod
    def _pm(cls, v: Any) -> Any:
        return _money(v)


class CandidateIn(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"subcontractor_id", "vendor_id"})

    subcontractor_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    free_name: str = Field(default="", max_length=255)
    source: Literal["market_sounding", "own_list", "framework", "public_notice"] = "own_list"
    list: Literal["long", "short", "excluded"] = "long"
    decision_rationale: str = Field(default="", max_length=4000)
    conflict_of_interest_declared: bool = False
    conflict_note: str = Field(default="", max_length=4000)


class CandidatePatch(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"subcontractor_id", "vendor_id"})

    subcontractor_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    free_name: str | None = Field(default=None, max_length=255)
    source: Literal["market_sounding", "own_list", "framework", "public_notice"] | None = None
    list: Literal["long", "short", "excluded"] | None = None
    decision_rationale: str | None = Field(default=None, max_length=4000)
    conflict_of_interest_declared: bool | None = None
    conflict_note: str | None = Field(default=None, max_length=4000)


class EvidenceRef(_In):
    kind: Literal["certificate", "prequal_application", "rating", "reference", "document"]
    id: str = Field(min_length=1, max_length=64)


class ScoreIn(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"passed", "score"})

    criterion_code: str = Field(min_length=1, max_length=64)
    passed: bool | None = None
    score: Decimal | None = Field(default=None, ge=0, le=100)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=2000)

    @field_validator("score", mode="before")
    @classmethod
    def _s(cls, v: Any) -> Any:
        return _money(v)


class ScoresPut(_In):
    scores: list[ScoreIn] = Field(max_length=60)


class ReferenceIn(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"value", "year"})

    project_name: str = Field(min_length=1, max_length=255)
    client: str = Field(default="", max_length=255)
    value: Decimal | None = None
    currency: str = Field(default="", max_length=3)
    year: int | None = Field(default=None, ge=1900, le=2100)
    role: str = Field(default="", max_length=120)
    contact: str = Field(default="", max_length=255)
    verified: bool = False

    @field_validator("value", mode="before")
    @classmethod
    def _v(cls, v: Any) -> Any:
        return _money(v)


# ── Market sounding ──────────────────────────────────────────────────────


class SoundingIn(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"lead_time_signal_days"})

    package_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    trade: str = Field(default="", max_length=120)
    held_on: date
    method: Literal["survey", "meeting", "rfi", "notice"] = "meeting"
    participant_candidate_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    findings: str = Field(default="", max_length=8000)
    capacity_signal: Literal["ample", "adequate", "tight", "insufficient"] = "adequate"
    price_signal: Literal["below_estimate", "in_line", "above_estimate", "unknown"] = "unknown"
    lead_time_signal_days: int | None = Field(default=None, ge=0, le=1500)
    mitigation: str = Field(default="", max_length=4000)
    resplit: bool = False


class SoundingPatch(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"lead_time_signal_days"})

    package_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    trade: str | None = Field(default=None, max_length=120)
    held_on: date | None = None
    method: Literal["survey", "meeting", "rfi", "notice"] | None = None
    participant_candidate_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    findings: str | None = Field(default=None, max_length=8000)
    capacity_signal: Literal["ample", "adequate", "tight", "insufficient"] | None = None
    price_signal: Literal["below_estimate", "in_line", "above_estimate", "unknown"] | None = None
    lead_time_signal_days: int | None = Field(default=None, ge=0, le=1500)
    mitigation: str | None = Field(default=None, max_length=4000)
    resplit: bool | None = None


# ── Schedule and execution ───────────────────────────────────────────────


class ScheduleConfirm(_In):
    package_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class ExecutionIn(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"vehicle", "submission_deadline"})

    # Override of the vehicle chosen from the package kind (rule 15); never both.
    vehicle: Literal["bid_package", "rfq"] | None = None
    submission_deadline: date | None = None


class ExecutionLinkIn(_In):
    """Link an existing tender package of the project instead of creating a vehicle (rule 15)."""

    tender_package_id: uuid.UUID


# ── Frameworks ───────────────────────────────────────────────────────────


class FrameworkLot(_In):
    """One lot of a framework agreement."""

    code: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=255)


class FrameworkIn(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"subcontractor_id", "vendor_id"})

    code: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=255)
    subcontractor_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    supplier_name: str = Field(default="", max_length=255)
    scope: str = Field(default="", max_length=8000)
    package_kinds: list[Literal["design", "works", "supply", "supply_and_install", "services"]] = Field(
        default_factory=list
    )
    lots: list[FrameworkLot] = Field(default_factory=list, max_length=50)
    max_value: Decimal
    currency: str = Field(min_length=3, max_length=3)
    start_date: date
    end_date: date
    call_off_mode: Literal["direct", "mini_competition"] = "direct"
    source_procedure_ref: str = Field(default="", max_length=255)

    @field_validator("max_value", mode="before")
    @classmethod
    def _mv(cls, v: Any) -> Any:
        return _money(v)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v: str) -> str:
        return v.upper()


class FrameworkPatch(_In):
    clearable: ClassVar[frozenset[str]] = frozenset({"subcontractor_id", "vendor_id"})

    title: str | None = Field(default=None, max_length=255)
    subcontractor_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    supplier_name: str | None = Field(default=None, max_length=255)
    scope: str | None = Field(default=None, max_length=8000)
    package_kinds: list[Literal["design", "works", "supply", "supply_and_install", "services"]] | None = None
    lots: list[FrameworkLot] | None = Field(default=None, max_length=50)
    max_value: Decimal | None = None
    end_date: date | None = None
    call_off_mode: Literal["direct", "mini_competition"] | None = None
    source_procedure_ref: str | None = Field(default=None, max_length=255)

    @field_validator("max_value", mode="before")
    @classmethod
    def _mv(cls, v: Any) -> Any:
        return _money(v)


class FrameworkStateIn(_In):
    target: Literal["active", "expired", "exhausted", "terminated"]
