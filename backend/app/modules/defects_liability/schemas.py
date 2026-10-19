# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Defects-liability Pydantic v2 schemas (request / response models).

Calendar dates cross the wire as ISO-8601 strings (``YYYY-MM-DD``) and are typed
as :class:`datetime.date` on create/update so Pydantic parses and validates them.
The register and readiness responses report their derived percentages
(``overall_health_score``, per-subcontractor ``health_score``) as plain decimal
strings (``None`` meaning "undefined", e.g. an empty register) via field
serialisers, so no float rounding is introduced at the API edge, mirroring the
money-as-string convention used across the platform. Other derived views (counts,
expiring / expired / overdue / ready lists) come straight from the dicts produced
by the pure :mod:`app.modules.defects_liability.register` core.

The warranty-type / status / defect-status / severity vocabularies are the single
source of truth in :mod:`app.modules.defects_liability.register`; the ``Literal``
types below enumerate the same values so an out-of-vocabulary value is rejected at
the edge (422).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer

from app.modules.defects_liability import limitation

# Vocabularies (kept in lock-step with app.modules.defects_liability.register).
WarrantyTypeLiteral = Literal[
    "workmanship",
    "manufacturer",
    "latent_defect",
    "extended",
    "other",
]
WarrantyStatusLiteral = Literal[
    "in_dlp",
    "expiring",
    "expired",
    "closed",
    "on_hold",
]
DefectStatusLiteral = Literal[
    "open",
    "rectifying",
    "rectified",
    "rejected",
    "closed",
]
DefectSeverityLiteral = Literal["minor", "major", "critical"]
# The statutory limitation regimes a warranty period can be derived from (kept in
# lock-step with ALL_LIMITATION_REGIMES in
# app.modules.defects_liability.limitation, and pinned equal to it by the tests).
# Always optional, on create and on update alike: an entry with no regime is the
# normal state and the only state every existing row is in.
LimitationRegimeLiteral = Literal[
    "de_vob_b", "de_bgb", "eg_civil_651", "fr_civil_1792_6", "fr_civil_1792_3", "fr_civil_1792", "sa_sbc_decennial"
]


def _serialise_pct(v: Decimal | None) -> str | None:
    """Render a percentage Decimal as a plain decimal string for JSON.

    Returns ``None`` when the value is ``None`` (undefined), ``"0"`` for a
    non-finite or unparseable value, and otherwise the value formatted with
    :func:`format` (``"f"``) so no scientific notation or float rounding leaks
    into the response.
    """
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


# -- Warranty / DLP entry ----------------------------------------------------


class WarrantyCreate(BaseModel):
    """Create a warranty / DLP entry on a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=255)
    element_description: str | None = Field(default=None, max_length=20000)
    subcontractor_id: UUID | None = None
    subcontractor_name: str | None = Field(default=None, max_length=255)
    work_package: str | None = Field(default=None, max_length=120)
    warranty_type: WarrantyTypeLiteral | None = None
    handover_date: date | None = None
    warranty_start_date: date | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=1200)
    warranty_end_date: date | None = None
    limitation_regime: LimitationRegimeLiteral | None = None
    dlp_end_date: date | None = None
    status: WarrantyStatusLiteral = "in_dlp"
    retention_release_date: date | None = None
    contract_id: UUID | None = None
    document_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=20000)


class WarrantyUpdate(BaseModel):
    """Patch a warranty / DLP entry. Only fields provided are changed.

    A field explicitly set to ``null`` clears it; an omitted field is left
    untouched (the service applies ``exclude_unset``).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    element_description: str | None = Field(default=None, max_length=20000)
    subcontractor_id: UUID | None = None
    subcontractor_name: str | None = Field(default=None, max_length=255)
    work_package: str | None = Field(default=None, max_length=120)
    warranty_type: WarrantyTypeLiteral | None = None
    handover_date: date | None = None
    warranty_start_date: date | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=1200)
    warranty_end_date: date | None = None
    limitation_regime: LimitationRegimeLiteral | None = None
    dlp_end_date: date | None = None
    status: WarrantyStatusLiteral | None = None
    retention_release_date: date | None = None
    contract_id: UUID | None = None
    document_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=20000)


class WarrantyResponse(BaseModel):
    """A warranty / DLP entry returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    reference: str
    title: str
    element_description: str | None = None
    subcontractor_id: UUID | None = None
    subcontractor_name: str | None = None
    work_package: str | None = None
    warranty_type: str | None = None
    handover_date: date | None = None
    warranty_start_date: date | None = None
    warranty_months: int | None = None
    warranty_end_date: date | None = None
    limitation_regime: str | None = None
    dlp_end_date: date | None = None
    status: str
    retention_release_date: date | None = None
    contract_id: UUID | None = None
    document_id: UUID | None = None
    sort_order: int
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    # -- Derived limitation view (all three are None until a regime is chosen) --
    #
    # These say why the period ends when it ends, and they say nothing at all
    # about an entry that never chose a regime: no regime, no citation, no
    # statutory period, no computed date. They are recomputed from the stored
    # regime and dates on every read rather than stored, so correcting an
    # acceptance date corrects the statutory date with it, and so a row can never
    # hold a citation that disagrees with the regime it names.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def limitation_statute(self) -> str | None:
        """The provision the chosen regime comes from, or ``None`` if none was chosen.

        A legal citation rather than prose, so it is shown untranslated in every
        language; the sentence around it is built on the screen.
        """
        spec = limitation.regime_for(self.limitation_regime)
        return spec.statute if spec is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def limitation_months(self) -> int | None:
        """The chosen regime's statutory period in months, or ``None``.

        This is what the law gives, which is not necessarily what
        ``warranty_months`` holds: a contract may agree a different period, and
        where the two disagree the validation rules report it rather than either
        number being quietly changed.
        """
        spec = limitation.regime_for(self.limitation_regime)
        return spec.months if spec is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def limitation_end_date(self) -> date | None:
        """The day the statutory period runs out, or ``None``.

        ``None`` when no regime was chosen and equally when one was chosen but no
        acceptance date is recorded, because there is then nothing to count from
        and a date would have to be invented.
        """
        derived = limitation.derive_period(
            self.limitation_regime,
            limitation.limitation_start(self.warranty_start_date, self.handover_date),
        )
        return derived.end_date if derived is not None else None


# -- Defect notice -----------------------------------------------------------


class DefectCreate(BaseModel):
    """Raise a defect notice against a warranty / DLP entry.

    The warranty and project are taken from the path, never the body, so a defect
    can only ever be attached to the warranty named in the URL.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str = Field(..., min_length=1, max_length=40)
    description: str = Field(..., min_length=1, max_length=20000)
    severity: DefectSeverityLiteral | None = None
    raised_date: date | None = None
    due_date: date | None = None
    status: DefectStatusLiteral = "open"
    rectified_date: date | None = None
    responsible_party: str | None = Field(default=None, max_length=255)
    punchlist_id: str | None = Field(default=None, max_length=36)
    ncr_id: str | None = Field(default=None, max_length=36)


class DefectUpdate(BaseModel):
    """Patch (or close) a defect notice. Only fields provided are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, min_length=1, max_length=20000)
    severity: DefectSeverityLiteral | None = None
    raised_date: date | None = None
    due_date: date | None = None
    status: DefectStatusLiteral | None = None
    rectified_date: date | None = None
    responsible_party: str | None = Field(default=None, max_length=255)
    punchlist_id: str | None = Field(default=None, max_length=36)
    ncr_id: str | None = Field(default=None, max_length=36)


class DefectResponse(BaseModel):
    """A defect notice returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    warranty_id: UUID
    reference: str
    description: str
    severity: str | None = None
    raised_date: date | None = None
    due_date: date | None = None
    status: str
    rectified_date: date | None = None
    responsible_party: str | None = None
    punchlist_id: str | None = None
    ncr_id: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# -- Derived register views --------------------------------------------------


class WarrantyRef(BaseModel):
    """A lightweight reference to an entry, used in expiring / expired / ready lists."""

    warranty_id: str | None = None
    reference: str
    title: str
    status: str
    subcontractor_name: str | None = None
    work_package: str | None = None
    warranty_type: str | None = None
    dlp_end_date: str | None = None
    warranty_end_date: str | None = None
    open_defect_count: int = 0
    retention_release_ready: bool = False


class OverdueDefectRef(BaseModel):
    """One overdue defect, carrying its owning warranty's identity."""

    warranty_id: str | None = None
    warranty_reference: str
    title: str
    severity: str | None = None
    status: str
    due_date: str | None = None


class SubcontractorDlpHealthResponse(BaseModel):
    """Post-handover DLP health rollup for one subcontractor."""

    subcontractor: str
    total: int
    open_defects: int
    overdue_defects: int
    health_score: Decimal | None = None

    @field_serializer("health_score", when_used="json")
    def _ser_health(self, v: Decimal | None) -> str | None:
        return _serialise_pct(v)


class DlpRegisterResponse(BaseModel):
    """The full defects-liability register rollup for a project."""

    project_id: UUID
    as_of: str
    horizon_days: int
    total: int
    per_status: dict[str, int] = Field(default_factory=dict)
    per_warranty_type: dict[str, int] = Field(default_factory=dict)
    total_open_defects: int
    overall_health_score: Decimal | None = None
    is_clean: bool
    expiring: list[WarrantyRef] = Field(default_factory=list)
    expired: list[WarrantyRef] = Field(default_factory=list)
    overdue_defects: list[OverdueDefectRef] = Field(default_factory=list)
    retention_release_ready: list[WarrantyRef] = Field(default_factory=list)
    subcontractors: list[SubcontractorDlpHealthResponse] = Field(default_factory=list)

    @field_serializer("overall_health_score", when_used="json")
    def _ser_pct(self, v: Decimal | None) -> str | None:
        return _serialise_pct(v)


class RetentionReleaseReadinessResponse(BaseModel):
    """The entries clear for final retention release as of a date.

    Answers the single question the post-handover team asks when planning
    retention payments: which entries have run out their defects liability period
    with nothing left outstanding, so the money held back can be released.
    """

    project_id: UUID
    as_of: str
    total: int
    ready_count: int
    ready: list[WarrantyRef] = Field(default_factory=list)


# -- Limitation review -------------------------------------------------------


class LimitationFinding(BaseModel):
    """One validation finding about an entry that named a limitation regime.

    Carries the owning entry's identity so the finding can be chased back to the
    row without a second lookup, mirroring :class:`OverdueDefectRef`.

    ``message`` and ``suggestion`` are English, which is the platform's
    convention for validation-rule prose. ``details`` carries the same finding as
    named values - the citation, the recorded number and the statutory one - so
    the screen can put the sentence together in the reader's language instead of
    showing them English.
    """

    rule_id: str
    rule_name: str
    severity: str
    warranty_id: str
    reference: str
    title: str
    message: str
    suggestion: str | None = None
    details: dict = Field(default_factory=dict)


class LimitationReviewResponse(BaseModel):
    """What the limitation rules found across a project's warranty entries.

    ``reviewed_count`` is the number of entries that named a regime, which is the
    number of entries the rules looked at. A project where nobody chose a regime
    reviews nothing and finds nothing: ``reviewed_count`` is 0,
    ``regimes_in_use`` and ``findings`` are empty, and that is the whole answer.

    There is deliberately no ``as_of`` here, unlike the register and readiness
    views. Those two ask what has expired by a date; this one asks whether a
    record agrees with the law it names, which is true or false today and was
    true or false yesterday.
    """

    project_id: UUID
    total: int
    reviewed_count: int
    regimes_in_use: list[str] = Field(default_factory=list)
    findings: list[LimitationFinding] = Field(default_factory=list)
