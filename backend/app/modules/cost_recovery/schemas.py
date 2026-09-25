# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the cost recovery API.

Money is carried on the wire as a string (the Decimal rendered losslessly) per
the platform money-as-string convention, so the read models are built
explicitly in the router rather than validated straight off the ORM rows.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.modules.cost_recovery.back_charge import BackChargeStatus


class BackChargeCreate(BaseModel):
    """Request body to record a new back-charge."""

    source_ref: str = ""
    responsible_party: str = ""
    description: str = ""
    basis: str = ""
    gross_amount: Decimal = Decimal("0")
    chargeable_pct: Decimal = Decimal("1")
    currency: str = ""
    status: BackChargeStatus = "proposed"
    # Optional link to a scored change subject. When both are set, create scores
    # the subject's provability and stamps its band onto the back-charge, so the
    # recovery-by-traceability cohort split is populated from real evidence
    # instead of every row defaulting to the conservative low cohort.
    # subject_kind is a change-family token: change_order, variation_notice,
    # variation_request, variation_order, moc_entry.
    subject_kind: str | None = None
    subject_id: uuid.UUID | None = None
    # The responsible party as a record. Either may be sent; a contact that
    # belongs to a subcontractor links both. ``responsible_party`` stays the
    # free-text fallback and is filled from the record's name when blank.
    subcontractor_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    # The record the cost arose from, in the same project. A punch item fills
    # an unsent gross and currency from its rework cost, an NCR fills an unsent
    # gross from a numeric cost impact; both fill a blank description.
    ncr_id: uuid.UUID | None = None
    punch_item_id: uuid.UUID | None = None


class BackChargeUpdate(BaseModel):
    """Partial update of a back-charge; only the supplied fields are changed."""

    subcontractor_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    responsible_party: str | None = None
    description: str | None = None
    basis: str | None = None
    gross_amount: Decimal | None = None
    chargeable_pct: Decimal | None = None
    status: BackChargeStatus | None = None
    recovered_amount: Decimal | None = None


class BackChargeOut(BaseModel):
    """One back-charge with its derived chargeable / outstanding amounts."""

    id: str
    project_id: str
    source_ref: str
    responsible_party: str
    description: str
    basis: str
    gross_amount: str
    chargeable_pct: str
    chargeable_amount: str
    currency: str
    status: str
    recovered_amount: str
    outstanding: str
    is_open: bool
    agreed_at: str | None
    recovered_at: str | None
    # Provability band stamped from a linked change subject at create time
    # (weak / moderate / strong); blank when the back-charge was not linked to a
    # scored subject, which the recovery engine treats as the low cohort.
    traceability_band: str = ""
    subcontractor_id: str | None = None
    contact_id: str | None = None
    ncr_id: str | None = None
    punch_item_id: str | None = None


class PartyRecoveryOut(BaseModel):
    """Back-charge rollup for one responsible party in one currency."""

    party: str
    currency: str
    item_count: int
    open_count: int
    gross_total: str
    chargeable_total: str
    recovered_total: str
    outstanding_total: str


class CurrencyRecoveryOut(BaseModel):
    """Back-charge rollup for one currency across all parties."""

    currency: str
    item_count: int
    chargeable_total: str
    recovered_total: str
    outstanding_total: str


class RecoveryLedgerOut(BaseModel):
    """The project's back-charge position: per-party and per-currency rollups."""

    project_id: str
    item_count: int
    open_count: int
    primary_currency: str
    primary_outstanding: str
    by_party: list[PartyRecoveryOut]
    by_currency: list[CurrencyRecoveryOut]


class PendingBackChargeOut(BaseModel):
    """One agreed back-charge still to be deducted from a subcontractor."""

    back_charge_id: str
    project_id: str
    source_ref: str
    description: str
    currency: str
    amount: str
    apportioned: bool


class PendingBackChargesOut(BaseModel):
    """What a subcontractor owes back, per currency, never summed across them."""

    subcontractor_id: str
    items: list[PendingBackChargeOut]
    totals: dict[str, str]


# --- Apportionment (splitting one back-charge across parties) ----------------


class ApportionmentShareIn(BaseModel):
    """One party's requested share of a back-charge.

    ``share_pct`` is a FRACTION in [0, 1] (0.6 means 60%), not a whole-number
    percentage; the shares for one back-charge must sum to 1.0 (the engine
    validates this and 422s otherwise). ``basis`` is optional free text grounding
    the share (a contract clause, an apportionment finding).
    """

    party: str = ""
    share_pct: Decimal = Decimal("0")
    basis: str = ""


class ApportionmentRequest(BaseModel):
    """Request to compute and persist an apportionment of a back-charge.

    The back-charge's chargeable amount is split across ``shares`` (which must
    sum to 1.0) and the resulting per-party amounts are stored, replacing any
    previous apportionment of the same back-charge.
    """

    shares: list[ApportionmentShareIn]


class ApportionedShareOut(BaseModel):
    """One persisted party share of a back-charge, money as a string."""

    id: str
    back_charge_id: str
    project_id: str
    party: str
    basis: str
    share_pct: str
    share_amount: str
    currency: str


class BackChargeApportionmentOut(BaseModel):
    """A back-charge's full apportionment: the per-party shares and a total.

    ``share_total`` is the sum of the persisted share amounts (a single
    currency), which reconciles to the back-charge's chargeable amount exactly.
    ``is_apportioned`` is false when no apportionment has been recorded yet.
    """

    back_charge_id: str
    project_id: str
    currency: str
    chargeable_amount: str
    share_total: str
    is_apportioned: bool
    shares: list[ApportionedShareOut]


# --- Recovery performance (recovered vs entitled, by traceability) -----------


class CohortRecoveryOut(BaseModel):
    """Recovery performance for one traceability cohort or band, one currency.

    ``cohort`` is a HIGH/LOW cohort label ('high' / 'low') or an individual band
    ('strong' / 'moderate' / 'weak'), depending on which list it appears in.
    ``rate`` is a fraction in [0, 1] rendered as a string, or null when the
    cohort had no chargeable amount (an undefined ratio, never a misleading 0).
    """

    cohort: str
    currency: str
    item_count: int
    chargeable_total: str
    recovered_total: str
    outstanding_total: str
    absorbed_total: str
    rate: str | None


class CurrencyRecoveryPerfOut(BaseModel):
    """Recovery performance for one currency across all traceability cohorts."""

    currency: str
    item_count: int
    chargeable_total: str
    recovered_total: str
    outstanding_total: str
    absorbed_total: str
    rate: str | None
    by_cohort: list[CohortRecoveryOut]
    by_band: list[CohortRecoveryOut]


class RecoveryPerformanceOut(BaseModel):
    """The recovery position per currency, never blended across currency codes.

    ``project_id`` is null for the portfolio variant that spans every project
    the caller may access. ``primary_rate`` is the largest-chargeable currency's
    overall recovery rate as a string fraction (or null), a single headline that
    never mixes currencies.
    """

    project_id: str | None
    item_count: int
    primary_currency: str
    primary_rate: str | None
    by_currency: list[CurrencyRecoveryPerfOut]
