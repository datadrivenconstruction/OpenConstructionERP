"""‌⁠‍Business logic for the subcontractors module.

Highlights:
    - Pure helpers (`derive_cert_status`, `compute_expiry_alerts`,
      `next_payment_blocked`, `compute_rating`, `validate_tax_id`) -
      unit-tested independently so the cron / route layer can be wired
      separately.
    - `SubcontractorService` orchestrates the lifecycle workflows
      (prequalification, payment application, retention, rating, SOV).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.subcontractors.models import (
    Certificate,
    LienWaiver,
    PaymentApplication,
    PaymentApplicationLine,
    PrequalificationApplication,
    RetentionLedger,
    SubcontractAgreement,
    Subcontractor,
    SubcontractorContact,
    SubcontractorRating,
    WorkPackage,
)
from app.modules.subcontractors.repository import (
    AgreementRepository,
    CertificateRepository,
    LienWaiverRepository,
    PaymentApplicationLineRepository,
    PaymentApplicationRepository,
    PrequalificationRepository,
    RatingRepository,
    RetentionLedgerRepository,
    SubcontractorContactRepository,
    SubcontractorRepository,
    WorkPackageRepository,
)
from app.modules.subcontractors.schemas import (
    AgreementCreate,
    AgreementUpdate,
    CertificateCreate,
    CertificateUpdate,
    CurrencyAmount,
    ExpiryAlert,
    PaymentApplicationCreate,
    PaymentApplicationUpdate,
    PaymentBlockResult,
    PrequalificationCreate,
    PrequalificationUpdate,
    RatingCreate,
    SOVRow,
    SOVSummaryResponse,
    SubcontractorContactCreate,
    SubcontractorContactUpdate,
    SubcontractorCreate,
    SubcontractorDashboard,
    SubcontractorUpdate,
    TaxIdValidationResponse,
    WorkPackageCreate,
    WorkPackageUpdate,
)

logger = logging.getLogger(__name__)

REQUIRED_CERT_TYPES_FOR_PAYMENT: tuple[str, ...] = ("insurance", "license")
EXPIRY_WINDOWS: tuple[int, ...] = (60, 30, 7)

# ── R5 PII safety ──────────────────────────────────────────────────────────
# Subcontractor contacts carry e-mail + phone - GDPR Art. 5(1)(c) requires
# logs strip them before interpolation. Mirror the v4.2.4 contacts pattern.

# Fields on SubcontractorUpdate that NO caller may set directly via PATCH -
# they are derived from internal events (rating roll-up).
_DERIVED_FIELDS_ON_SUB: frozenset[str] = frozenset({"rating_score"})


def _redact_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "<redacted>"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


def _redact_phone(phone: str | None) -> str:
    if not phone:
        return "<redacted>"
    digits = re.sub(r"\D", "", phone)
    return f"***{digits[-2:]}" if len(digits) >= 2 else "<redacted>"


# ── Pure helpers ─────────────────────────────────────────────────────────


def derive_cert_status(
    valid_until: date | None,
    revoked: bool = False,
    *,
    today: date | None = None,
) -> str:
    """‌⁠‍Derive certificate status from validity / revocation state.

    Returns one of: valid / expired / revoked.
    """
    if revoked:
        return "revoked"
    if valid_until is None:
        return "valid"
    ref = today or date.today()
    if valid_until < ref:
        return "expired"
    return "valid"


def compute_expiry_alerts(
    certificates: list[Certificate],
    today: date | None = None,
) -> list[ExpiryAlert]:
    """‌⁠‍Return alerts at 60 / 30 / 7 days before each certificate expires.

    A certificate emits one alert per window it has just crossed
    (e.g. a cert that expires in 5 days fires both the 7-day and lower
    windows - we emit the smallest matching window).
    """
    ref = today or date.today()
    alerts: list[ExpiryAlert] = []
    for cert in certificates:
        if cert.revoked or cert.valid_until is None:
            continue
        delta = (cert.valid_until - ref).days
        if delta < 0:
            continue
        # Pick the smallest window the cert is inside of (most urgent).
        # `EXPIRY_WINDOWS` is sorted descending in declaration; iterate ascending
        # to find the tightest band.
        matched: int | None = None
        for window in sorted(EXPIRY_WINDOWS):
            if delta <= window:
                matched = window
                break
        if matched is None:
            continue
        alerts.append(
            ExpiryAlert(
                certificate_id=cert.id,
                subcontractor_id=cert.subcontractor_id,
                cert_type=cert.cert_type,
                valid_until=cert.valid_until,
                days_until_expiry=delta,
                window=matched,
            )
        )
    return alerts


def next_payment_blocked(
    certificates: list[Certificate],
    today: date | None = None,
    *,
    required_types: tuple[str, ...] = REQUIRED_CERT_TYPES_FOR_PAYMENT,
) -> PaymentBlockResult:
    """Return (blocked, reasons) for the next payment based on certificates.

    A payment is blocked if any required cert type is expired, revoked, or
    missing.
    """
    ref = today or date.today()
    reasons: list[str] = []

    have_by_type: dict[str, list[Certificate]] = {}
    for cert in certificates:
        have_by_type.setdefault(cert.cert_type, []).append(cert)

    for cert_type in required_types:
        certs_of_type = have_by_type.get(cert_type, [])
        if not certs_of_type:
            reasons.append(f"missing_required_certificate:{cert_type}")
            continue
        # Need at least one valid (not revoked, not expired) cert per type.
        has_valid = any((not c.revoked) and (c.valid_until is None or c.valid_until >= ref) for c in certs_of_type)
        if not has_valid:
            reasons.append(f"expired_or_revoked_certificate:{cert_type}")

    return PaymentBlockResult(blocked=bool(reasons), reasons=reasons)


# Tax forms that never release a payment - they prove vendor tax status, not
# that the sub has waived lien rights for the amount being paid. Everything in
# the waiver enum other than these (the four conditional/unconditional ×
# partial/final lien-waiver types) counts toward the gate. Matching by the
# tax-form exclusion rather than an allow-list keeps this correct if new lien
# variants are added to ``_VALID_WAIVER_TYPES``.
_TAX_FORM_WAIVER_TYPES: frozenset[str] = frozenset({"w9", "w8"})


def _is_payment_waiver(waiver_type: str) -> bool:
    """True when a waiver type counts toward releasing a payment.

    The stored enum is compound (e.g. ``unconditional_final``); tax forms
    (``w9`` / ``w8``) are excluded. Also tolerates the bare ``conditional`` /
    ``unconditional`` bases for forward-compatibility.
    """
    return waiver_type not in _TAX_FORM_WAIVER_TYPES and (waiver_type.startswith(("conditional", "unconditional")))


def lien_waiver_blocked(
    payment_net_amount: Decimal,
    waivers: list[LienWaiver],
    *,
    required: bool,
) -> PaymentBlockResult:
    """Return whether the next payment is blocked by a missing or short waiver.

    Only applies when the agreement requires waivers. The payment is released
    only if it carries at least one lien waiver (any conditional/unconditional
    partial/final type - not a W-9/W-8 tax form) whose covered amount is at
    least the payment's net amount.
    """
    if not required:
        return PaymentBlockResult(blocked=False, reasons=[])
    payment_waivers = [w for w in waivers if _is_payment_waiver(w.waiver_type)]
    if not payment_waivers:
        return PaymentBlockResult(blocked=True, reasons=["missing_waiver"])
    covered = max((w.amount for w in payment_waivers), default=Decimal("0"))
    if covered < payment_net_amount:
        return PaymentBlockResult(blocked=True, reasons=["waiver_amount_mismatch"])
    return PaymentBlockResult(blocked=False, reasons=[])


# Prequalification states that bar awarding live work (TOP-30 #20). A
# subcontractor explicitly rejected or suspended in prequalification - or
# administratively blocked - must not be moved onto a live subcontract or paid.
# ``pending`` (the default for a new vendor) and ``approved`` are allowed; the
# UI still nudges to finish prequalification while pending.
_AWARD_BARRED_PREQUAL_STATES: frozenset[str] = frozenset({"rejected", "suspended"})


def subcontractor_award_block(subcontractor: object) -> PaymentBlockResult:
    """Why, if at all, a subcontractor may not be awarded live work.

    Returns the reasons an agreement cannot be activated and a payment cannot
    be claimed for this vendor: ``subcontractor_blocked`` (admin block) and/or
    ``prequalification_<status>`` for a rejected/suspended prequal.
    """
    reasons: list[str] = []
    if getattr(subcontractor, "is_blocked", False):
        reasons.append("subcontractor_blocked")
    prequal = getattr(subcontractor, "prequalification_status", "") or ""
    if prequal in _AWARD_BARRED_PREQUAL_STATES:
        reasons.append(f"prequalification_{prequal}")
    return PaymentBlockResult(blocked=bool(reasons), reasons=reasons)


@dataclass
class Rating:
    """Weighted rating components and overall score (all 0–100)."""

    quality_score: Decimal = Decimal("0")
    hse_score: Decimal = Decimal("0")
    schedule_score: Decimal = Decimal("0")
    cost_score: Decimal = Decimal("0")
    overall_score: Decimal = Decimal("0")
    basis: dict[str, Any] = field(default_factory=dict)


# Default category weights - biased toward HSE for construction.
DEFAULT_RATING_WEIGHTS: dict[str, Decimal] = {
    "quality": Decimal("0.30"),
    "hse": Decimal("0.30"),
    "schedule": Decimal("0.20"),
    "cost": Decimal("0.20"),
}


def _clamp(value: Decimal) -> Decimal:
    """Clamp a score to [0, 100] with 2-dp rounding."""
    if value < 0:
        value = Decimal("0")
    if value > 100:
        value = Decimal("100")
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_rating(
    events: dict[str, Any],
    *,
    weights: dict[str, Decimal] | None = None,
) -> Rating:
    """Compute a weighted subcontractor rating from event counts / inputs.

    Input shape (all optional, integers/decimals):
        - ncr_count: int (non-conformance reports)
        - hse_incidents: int
        - schedule_deviations_days: int (signed; positive = behind)
        - cost_variance_percent: Decimal (positive = over budget)
        - direct_scores: dict with optional explicit overrides per category

    Output:
        Rating with category sub-scores and overall (0–100, higher = better).
    """
    w = weights or DEFAULT_RATING_WEIGHTS

    raw_direct = events.get("direct_scores")
    direct: dict[str, Any] = raw_direct if isinstance(raw_direct, dict) else {}

    def _safe_int(value: Any) -> int:
        """Coerce free-form event input to int; non-numeric → 0 (never raises)."""
        if value is None or value == "":
            return 0
        try:
            return int(Decimal(str(value)))
        except (InvalidOperation, ValueError, TypeError):
            return 0

    def _safe_decimal(value: Any) -> Decimal:
        """Coerce free-form event input to Decimal; non-numeric → 0."""
        if value is None or value == "":
            return Decimal("0")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0")

    def _from_count(count: int | None, *, penalty: int = 10, base: int = 100) -> Decimal:
        if count is None:
            return Decimal(str(base))
        return _clamp(Decimal(str(base)) - Decimal(str(penalty * max(0, count))))

    quality = (
        _safe_decimal(direct["quality"])
        if "quality" in direct
        else _from_count(_safe_int(events.get("ncr_count")), penalty=15)
    )
    hse = (
        _safe_decimal(direct["hse"])
        if "hse" in direct
        else _from_count(_safe_int(events.get("hse_incidents")), penalty=20)
    )

    if "schedule" in direct:
        schedule = _safe_decimal(direct["schedule"])
    else:
        deviation_days = _safe_int(events.get("schedule_deviations_days"))
        schedule = _clamp(Decimal("100") - Decimal(str(max(0, deviation_days))) * Decimal("2"))

    if "cost" in direct:
        cost = _safe_decimal(direct["cost"])
    else:
        cost_variance = _safe_decimal(events.get("cost_variance_percent"))
        # Penalise variance in either direction (over- and under-runs both hurt).
        cost = _clamp(Decimal("100") - abs(cost_variance) * Decimal("3"))

    quality = _clamp(quality)
    hse = _clamp(hse)
    schedule = _clamp(schedule)
    cost = _clamp(cost)

    overall = quality * w["quality"] + hse * w["hse"] + schedule * w["schedule"] + cost * w["cost"]

    return Rating(
        quality_score=quality,
        hse_score=hse,
        schedule_score=schedule,
        cost_score=cost,
        overall_score=_clamp(overall),
        basis={
            "ncr_count": events.get("ncr_count"),
            "hse_incidents": events.get("hse_incidents"),
            "schedule_deviations_days": events.get("schedule_deviations_days"),
            "cost_variance_percent": str(events.get("cost_variance_percent") or 0),
            "weights": {k: str(v) for k, v in w.items()},
        },
    )


# ── Tax-ID / VAT validator ──────────────────────────────────────────────


# Country → (standard_name, compiled regex).
# Patterns are *format* checks. They are deliberately permissive (no MOD-97 /
# checksum validation) - the goal is to reject obviously broken input at the
# UI boundary, not to authenticate against a registry. Live VIES checks are a
# follow-up module concern. Coverage: the 22 EU member states whose VAT
# numbers follow a published ISO/EU format, plus US (EIN), GB (post-Brexit
# VRN), CH, NO, AU (ABN), CA (BN9), BR (CNPJ), IN (GSTIN), AE (TRN), SA (TRN).
_TAX_ID_RULES: dict[str, tuple[str, re.Pattern[str]]] = {
    # EU VAT - country prefix is OPTIONAL on input; we normalise to bare body.
    "AT": ("EU VAT (AT)", re.compile(r"^U\d{8}$")),
    "BE": ("EU VAT (BE)", re.compile(r"^[01]\d{9}$")),
    "BG": ("EU VAT (BG)", re.compile(r"^\d{9,10}$")),
    "CY": ("EU VAT (CY)", re.compile(r"^\d{8}[A-Z]$")),
    "CZ": ("EU VAT (CZ)", re.compile(r"^\d{8,10}$")),
    "DE": ("EU VAT (DE)", re.compile(r"^\d{9}$")),
    "DK": ("EU VAT (DK)", re.compile(r"^\d{8}$")),
    "EE": ("EU VAT (EE)", re.compile(r"^\d{9}$")),
    "EL": ("EU VAT (EL)", re.compile(r"^\d{9}$")),
    "ES": ("EU VAT (ES)", re.compile(r"^[A-Z0-9]\d{7}[A-Z0-9]$")),
    "FI": ("EU VAT (FI)", re.compile(r"^\d{8}$")),
    "FR": ("EU VAT (FR)", re.compile(r"^[A-HJ-NP-Z0-9]{2}\d{9}$")),
    "HR": ("EU VAT (HR)", re.compile(r"^\d{11}$")),
    "HU": ("EU VAT (HU)", re.compile(r"^\d{8}$")),
    "IE": ("EU VAT (IE)", re.compile(r"^\d{7}[A-Z]{1,2}$|^\d[A-Z0-9+*]\d{5}[A-Z]$")),
    "IT": ("EU VAT (IT)", re.compile(r"^\d{11}$")),
    "LT": ("EU VAT (LT)", re.compile(r"^\d{9}$|^\d{12}$")),
    "LU": ("EU VAT (LU)", re.compile(r"^\d{8}$")),
    "LV": ("EU VAT (LV)", re.compile(r"^\d{11}$")),
    "MT": ("EU VAT (MT)", re.compile(r"^\d{8}$")),
    "NL": ("EU VAT (NL)", re.compile(r"^\d{9}B\d{2}$")),
    "PL": ("EU VAT (PL)", re.compile(r"^\d{10}$")),
    "PT": ("EU VAT (PT)", re.compile(r"^\d{9}$")),
    "RO": ("EU VAT (RO)", re.compile(r"^\d{2,10}$")),
    "SE": ("EU VAT (SE)", re.compile(r"^\d{12}$")),
    "SI": ("EU VAT (SI)", re.compile(r"^\d{8}$")),
    "SK": ("EU VAT (SK)", re.compile(r"^\d{10}$")),
    "GR": ("EU VAT (GR)", re.compile(r"^\d{9}$")),
    # Outside EU
    "GB": ("GB VRN", re.compile(r"^\d{9}$|^\d{12}$|^GD\d{3}$|^HA\d{3}$")),
    "US": ("US EIN", re.compile(r"^\d{9}$")),
    "CH": ("CH UID", re.compile(r"^E\d{9}$|^\d{9}MWST$")),
    "NO": ("NO Org.nr", re.compile(r"^\d{9}MVA$|^\d{9}$")),
    "AU": ("AU ABN", re.compile(r"^\d{11}$")),
    "CA": ("CA BN9/15", re.compile(r"^\d{9}$|^\d{9}RT\d{4}$")),
    "BR": ("BR CNPJ", re.compile(r"^\d{14}$")),
    "IN": ("IN GSTIN", re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9][Z][A-Z0-9]$")),
    "AE": ("AE TRN", re.compile(r"^\d{15}$")),
    "SA": ("SA TRN", re.compile(r"^\d{15}$")),
    "TR": ("TR VKN", re.compile(r"^\d{10}$|^\d{11}$")),
    "RU": ("RU INN", re.compile(r"^\d{10}$|^\d{12}$")),
    "ZA": ("ZA VAT", re.compile(r"^\d{10}$")),
}


def _normalise_tax_id(country: str, raw: str) -> tuple[str, str]:
    """Return (country_upper, canonical_tax_id) for a free-form input.

    * Drops whitespace, dashes, slashes, dots.
    * Upper-cases the result.
    * If the input starts with the same 2-letter country code as the
      ``country`` arg (e.g. ``DE123…`` with country=``DE``), strips it.
      EU VAT numbers commonly carry the country prefix in invoicing
      contexts but the format rules check only the body.
    """
    country_u = country.upper()[:2]
    cleaned = re.sub(r"[\s\-./,_]", "", raw or "").upper()
    if cleaned.startswith(country_u) and len(cleaned) > 2:
        cleaned = cleaned[2:]
    return country_u, cleaned


def validate_tax_id(country: str, tax_id: str) -> TaxIdValidationResponse:
    """Validate a tax-ID's format against the country's published pattern.

    Returns a structured :class:`TaxIdValidationResponse` indicating whether
    the format is valid and which standard it was checked against. Countries
    with no rule registered return ``format_valid=True`` with ``standard=None``
    - we don't want to block payment in unknown jurisdictions.
    """
    country_u, normalised = _normalise_tax_id(country or "", tax_id or "")
    if not normalised:
        return TaxIdValidationResponse(
            country=country_u,
            tax_id_normalised="",
            format_valid=False,
            standard=None,
            reason="empty_after_normalisation",
        )
    rule = _TAX_ID_RULES.get(country_u)
    if rule is None:
        return TaxIdValidationResponse(
            country=country_u,
            tax_id_normalised=normalised,
            format_valid=True,
            standard=None,
            reason=None,
        )
    standard_name, pattern = rule
    if pattern.fullmatch(normalised):
        return TaxIdValidationResponse(
            country=country_u,
            tax_id_normalised=normalised,
            format_valid=True,
            standard=standard_name,
            reason=None,
        )
    return TaxIdValidationResponse(
        country=country_u,
        tax_id_normalised=normalised,
        format_valid=False,
        standard=standard_name,
        reason=f"format_mismatch:{standard_name}",
    )


# ── State-machine transitions ───────────────────────────────────────────


_PREQUAL_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted"},
    "submitted": {"under_review", "rejected"},
    "under_review": {"approved", "rejected"},
    "approved": set(),
    "rejected": set(),
}

_PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"foreman_approved", "rejected"},
    "foreman_approved": {"finance_approved", "rejected"},
    "finance_approved": {"paid", "rejected"},
    "paid": set(),
    "rejected": set(),
}

_AGREEMENT_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "terminated"},
    "active": {"completed", "terminated"},
    "completed": set(),
    "terminated": set(),
}


def _assert_transition(
    from_status: str,
    to_status: str,
    table: dict[str, set[str]],
    label: str,
) -> None:
    if to_status not in table.get(from_status, set()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label} transition: {from_status} -> {to_status}",
        )


# ── Service ─────────────────────────────────────────────────────────────


class SubcontractorService:
    """Orchestrates the subcontractor lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subs = SubcontractorRepository(session)
        self.contacts = SubcontractorContactRepository(session)
        self.prequal = PrequalificationRepository(session)
        self.certs = CertificateRepository(session)
        self.agreements = AgreementRepository(session)
        self.work_packages = WorkPackageRepository(session)
        self.payments = PaymentApplicationRepository(session)
        self.payment_lines = PaymentApplicationLineRepository(session)
        self.retention = RetentionLedgerRepository(session)
        self.ratings = RatingRepository(session)
        self.lien_waivers = LienWaiverRepository(session)

    # ── Subcontractor CRUD ─────────────────────────────────────────────

    async def create_subcontractor(
        self,
        data: SubcontractorCreate,
        user_id: str | None = None,
    ) -> Subcontractor:
        # Read-then-write duplicate guard on (country, tax_id). The DB
        # also carries a partial unique index post-v3099 - that's the
        # backstop; this read keeps the happy path 409 instead of 500.
        # Stub repositories in unit tests don't implement the method;
        # the IntegrityError handler below still catches a race.
        find_by_tax_id = getattr(self.subs, "find_by_tax_id", None)
        if data.tax_id and find_by_tax_id is not None:
            existing = await find_by_tax_id(
                data.tax_id,
                country=data.country,
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(f"A subcontractor with this tax_id already exists for country {data.country or '?'}."),
                )
        entity = Subcontractor(
            contact_id=data.contact_id,
            legal_name=data.legal_name,
            trade_name=data.trade_name,
            tax_id=data.tax_id,
            trade_categories=data.trade_categories,
            prequalification_status=data.prequalification_status,
            country=data.country,
            address=data.address,
            website=data.website,
            notes=data.notes,
            created_by=user_id,
        )
        try:
            await self.subs.create(entity)
        except IntegrityError:
            # Two concurrent POSTs raced past the read-then-write check
            # above. Translate to 409 so callers retry intelligently.
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A subcontractor with this tax_id already exists.",
            ) from None
        event_bus.publish_detached(
            "subcontractors.subcontractor.created",
            {"subcontractor_id": str(entity.id), "legal_name": entity.legal_name},
            source_module="subcontractors",
        )
        logger.info(
            "subcontractor.created id=%s name=%s by=%s",
            entity.id,
            entity.legal_name,
            user_id or "<anon>",
        )
        return entity

    async def get_subcontractor(self, sub_id: uuid.UUID) -> Subcontractor:
        entity = await self.subs.get_by_id(sub_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Subcontractor not found")
        return entity

    async def update_subcontractor(
        self,
        sub_id: uuid.UUID,
        data: SubcontractorUpdate,
    ) -> Subcontractor:
        await self.get_subcontractor(sub_id)
        fields = data.model_dump(exclude_unset=True)
        # Defence-in-depth: even if a future schema regression re-introduces
        # ``rating_score`` on the update payload, the service must never
        # accept it through this gate.
        for derived in _DERIVED_FIELDS_ON_SUB:
            if derived in fields:
                fields.pop(derived, None)
                logger.warning(
                    "Refusing PATCH to derived field %s on sub=%s",
                    derived,
                    sub_id,
                )
        if fields:
            await self.subs.update_fields(sub_id, **fields)
        entity = await self.get_subcontractor(sub_id)
        return entity

    async def delete_subcontractor(self, sub_id: uuid.UUID) -> None:
        await self.get_subcontractor(sub_id)
        await self.subs.delete(sub_id)

    # ── Contact CRUD ─────────────────────────────────────────────────────

    async def create_contact(
        self,
        data: SubcontractorContactCreate,
    ) -> SubcontractorContact:
        entity = SubcontractorContact(
            subcontractor_id=data.subcontractor_id,
            name=data.name,
            role=data.role,
            email=data.email,
            phone=data.phone,
            primary=data.primary,
        )
        await self.contacts.create(entity)
        # PII-safe log line - never interpolate raw e-mail / phone.
        logger.info(
            "subcontractor_contact.created id=%s sub=%s role=%s email=%s phone=%s",
            entity.id,
            data.subcontractor_id,
            data.role or "<none>",
            _redact_email(data.email),
            _redact_phone(data.phone),
        )
        return entity

    async def update_contact(
        self,
        contact_id: uuid.UUID,
        data: SubcontractorContactUpdate,
    ) -> SubcontractorContact:
        entity = await self.contacts.get_by_id(contact_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Contact not found")
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.contacts.update_fields(contact_id, **fields)
            await self.session.refresh(entity)
            # Log only field *names* - values may carry new PII the
            # operator should not see in centralised log storage.
            logger.info(
                "subcontractor_contact.updated id=%s changed=%s",
                contact_id,
                sorted(fields.keys()),
            )
        return entity

    async def delete_contact(self, contact_id: uuid.UUID) -> None:
        await self.contacts.delete(contact_id)

    # ── Prequalification workflow ───────────────────────────────────────

    async def create_prequalification(
        self,
        data: PrequalificationCreate,
        user_id: str | None = None,
    ) -> PrequalificationApplication:
        # Ensure parent subcontractor exists.
        await self.get_subcontractor(data.subcontractor_id)
        entity = PrequalificationApplication(
            subcontractor_id=data.subcontractor_id,
            status=data.status,
            answers=data.answers,
            created_by=user_id,
        )
        await self.prequal.create(entity)
        return entity

    async def update_prequalification(
        self,
        prequal_id: uuid.UUID,
        data: PrequalificationUpdate,
    ) -> PrequalificationApplication:
        entity = await self.prequal.get_by_id(prequal_id)
        if entity is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.prequalification_not_found", locale=get_locale())
            )
        fields = data.model_dump(exclude_unset=True)
        # Status transitions go through dedicated methods.
        fields.pop("status", None)
        if fields:
            await self.prequal.update_fields(prequal_id, **fields)
            await self.session.refresh(entity)
        return entity

    async def submit_prequalification(
        self,
        prequal_id: uuid.UUID,
    ) -> PrequalificationApplication:
        entity = await self.prequal.get_by_id(prequal_id)
        if entity is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.prequalification_not_found", locale=get_locale())
            )
        _assert_transition(entity.status, "submitted", _PREQUAL_TRANSITIONS, "prequalification")
        await self.prequal.update_fields(
            prequal_id,
            status="submitted",
            submitted_at=datetime.now(UTC),
        )
        await self.session.refresh(entity)
        event_bus.publish_detached(
            "subcontractors.prequalification.submitted",
            {"prequalification_id": str(entity.id), "subcontractor_id": str(entity.subcontractor_id)},
            source_module="subcontractors",
        )
        return entity

    async def approve_prequalification(
        self,
        prequal_id: uuid.UUID,
        reviewer_id: str,
        notes: str | None = None,
    ) -> PrequalificationApplication:
        entity = await self.prequal.get_by_id(prequal_id)
        if entity is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.prequalification_not_found", locale=get_locale())
            )
        # Snapshot scalars up front. ``update_fields`` below ends with
        # ``expire_all()``; afterwards any read OR write of ``entity`` would emit
        # a sync lazy-load SELECT during the next autoflush -> MissingGreenlet on
        # asyncpg (SQLite tolerated it). Track the FSM status in a local instead
        # of mutating the now-expired ORM instance (the prior ``entity.status =``
        # write on the expired row was the exact crash trigger).
        current_status = entity.status
        subcontractor_id = entity.subcontractor_id
        if current_status == "submitted":
            # Auto-move through `under_review` so the state machine stays linear.
            await self.prequal.update_fields(prequal_id, status="under_review")
            current_status = "under_review"
        _assert_transition(current_status, "approved", _PREQUAL_TRANSITIONS, "prequalification")
        prior_status = current_status
        await self.prequal.update_fields(
            prequal_id,
            status="approved",
            reviewer_id=reviewer_id,
            decision_at=datetime.now(UTC),
            decision_notes=notes,
        )
        # Cascade: parent subcontractor is now approved.
        await self.subs.update_fields(
            subcontractor_id,
            prequalification_status="approved",
        )
        await self.session.refresh(entity)

        # Epic H - universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=reviewer_id,
            entity_type="subcontractor_prequalification",
            entity_id=str(prequal_id),
            action="status_changed",
            from_status=prior_status,
            to_status="approved",
            reason=notes,
            module="subcontractors",
            parent_entity_type="subcontractor",
            parent_entity_id=str(subcontractor_id),
            before_state={"status": prior_status},
            after_state={"status": "approved"},
        )

        event_bus.publish_detached(
            "subcontractors.prequalification.approved",
            {"prequalification_id": str(prequal_id), "subcontractor_id": str(subcontractor_id)},
            source_module="subcontractors",
        )
        return entity

    async def reject_prequalification(
        self,
        prequal_id: uuid.UUID,
        reviewer_id: str,
        notes: str | None = None,
    ) -> PrequalificationApplication:
        entity = await self.prequal.get_by_id(prequal_id)
        if entity is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.prequalification_not_found", locale=get_locale())
            )
        _assert_transition(entity.status, "rejected", _PREQUAL_TRANSITIONS, "prequalification")
        prior_status = entity.status
        # Snapshot needed scalars before update_fields() expires the ORM instance,
        # otherwise reading them later emits a sync lazy-load SELECT (MissingGreenlet on asyncpg).
        subcontractor_id = entity.subcontractor_id
        await self.prequal.update_fields(
            prequal_id,
            status="rejected",
            reviewer_id=reviewer_id,
            decision_at=datetime.now(UTC),
            decision_notes=notes,
        )
        await self.subs.update_fields(
            subcontractor_id,
            prequalification_status="rejected",
        )
        await self.session.refresh(entity)

        # Epic H - universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=reviewer_id,
            entity_type="subcontractor_prequalification",
            entity_id=str(prequal_id),
            action="status_changed",
            from_status=prior_status,
            to_status="rejected",
            reason=notes,
            module="subcontractors",
            parent_entity_type="subcontractor",
            parent_entity_id=str(subcontractor_id),
            before_state={"status": prior_status},
            after_state={"status": "rejected"},
        )

        return entity

    # ── Certificate management ──────────────────────────────────────────

    async def record_certificate(
        self,
        data: CertificateCreate,
        *,
        today: date | None = None,
    ) -> Certificate:
        await self.get_subcontractor(data.subcontractor_id)
        status_value = derive_cert_status(data.valid_until, revoked=False, today=today)
        entity = Certificate(
            subcontractor_id=data.subcontractor_id,
            cert_type=data.cert_type,
            issued_by=data.issued_by,
            issue_date=data.issue_date,
            valid_until=data.valid_until,
            document_url=data.document_url,
            status=status_value,
            revoked=False,
            notes=data.notes,
        )
        await self.certs.create(entity)
        return entity

    async def update_certificate(
        self,
        certificate_id: uuid.UUID,
        data: CertificateUpdate,
        *,
        today: date | None = None,
    ) -> Certificate:
        entity = await self.certs.get_by_id(certificate_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Certificate not found")
        fields = data.model_dump(exclude_unset=True)
        if fields:
            # Recompute status from new valid_until / revoked
            new_valid = fields.get("valid_until", entity.valid_until)
            new_revoked = fields.get("revoked", entity.revoked)
            fields["status"] = derive_cert_status(new_valid, new_revoked, today=today)
            await self.certs.update_fields(certificate_id, **fields)
            await self.session.refresh(entity)
        return entity

    async def delete_certificate(self, certificate_id: uuid.UUID) -> None:
        await self.certs.delete(certificate_id)

    async def list_expiring_certificates(
        self,
        days: int = 60,
        *,
        today: date | None = None,
    ) -> list[ExpiryAlert]:
        ref = today or date.today()
        # Pull anything ending within `days` (inclusive of already-expired
        # so we still surface them for cleanup actions, but `compute_expiry_alerts`
        # only emits alerts for upcoming windows).
        upper = ref + timedelta(days=days)
        candidate = await self.certs.list_expiring_within(days=days, today=ref)
        # Filter once more: keep only those not yet expired.
        future = [c for c in candidate if c.valid_until and c.valid_until >= ref and c.valid_until <= upper]
        return compute_expiry_alerts(future, today=ref)

    # ── Agreements ──────────────────────────────────────────────────────

    async def create_agreement(
        self,
        data: AgreementCreate,
        user_id: str | None = None,
    ) -> SubcontractAgreement:
        await self.get_subcontractor(data.subcontractor_id)
        entity = SubcontractAgreement(
            subcontractor_id=data.subcontractor_id,
            project_id=data.project_id,
            title=data.title,
            total_value=data.total_value,
            currency=data.currency,
            start_date=data.start_date,
            end_date=data.end_date,
            retention_percent=data.retention_percent,
            retention_release_event=data.retention_release_event,
            requires_lien_waiver=data.requires_lien_waiver,
            notes=data.notes,
            # Born unsigned. Set explicitly rather than leaning on the column
            # default so the state machine has a deterministic origin
            # regardless of the persistence layer's flush-time defaulting.
            status="draft",
            created_by=user_id,
        )
        await self.agreements.create(entity)
        return entity

    async def update_agreement(
        self,
        agreement_id: uuid.UUID,
        data: AgreementUpdate,
    ) -> SubcontractAgreement:
        entity = await self.agreements.get_by_id(agreement_id)
        if entity is None:
            raise HTTPException(status_code=404, detail=translate("errors.agreement_not_found", locale=get_locale()))
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] is not None:
            _assert_transition(
                entity.status,
                fields["status"],
                _AGREEMENT_TRANSITIONS,
                "agreement",
            )
            # Prequalification gate (TOP-30 #20): a draft can be drawn up while
            # a sub is still being vetted, but it cannot go live for a blocked
            # or rejected/suspended vendor.
            if fields["status"] == "active" and entity.status != "active":
                await self._assert_subcontractor_awardable(entity.subcontractor_id)
        if fields:
            await self.agreements.update_fields(agreement_id, **fields)
            await self.session.refresh(entity)
        return entity

    async def subcontractor_award_eligibility(
        self,
        subcontractor_id: uuid.UUID,
    ) -> PaymentBlockResult:
        """Report whether a subcontractor may be awarded live work (TOP-30 #20)."""
        sub = await self.subs.get_by_id(subcontractor_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="Subcontractor not found")
        return subcontractor_award_block(sub)

    async def award_eligibility_for_contact(
        self,
        contact_id: uuid.UUID,
    ) -> tuple[Subcontractor, PaymentBlockResult] | None:
        """Resolve a CRM contact's subcontractor + award-block verdict.

        Used by procurement (PO gating + the PO-row vendor badge) to find
        out whether the vendor behind a ``vendor_contact_id`` is a
        registered, prequalified subcontractor. Returns ``None`` when the
        contact is not linked to any active subcontractor - procurement
        treats that as "unknown vendor, no gate" rather than an error, so a
        plain ad-hoc supplier with no prequal record is never blocked.
        """
        sub = await self.subs.get_by_contact_id(contact_id)
        if sub is None:
            return None
        return sub, subcontractor_award_block(sub)

    async def _assert_subcontractor_awardable(
        self,
        subcontractor_id: uuid.UUID,
    ) -> None:
        block = await self.subcontractor_award_eligibility(subcontractor_id)
        if block.blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": block.reasons[0],
                    "message": (
                        "This subcontractor is not approved for award. Clear the "
                        "block or complete prequalification before activating the "
                        "agreement."
                    ),
                    "reasons": block.reasons,
                },
            )

    async def delete_agreement(self, agreement_id: uuid.UUID) -> None:
        await self.agreements.delete(agreement_id)

    # ── Work packages ──────────────────────────────────────────────────

    async def create_work_package(self, data: WorkPackageCreate) -> WorkPackage:
        agreement = await self.agreements.get_by_id(data.agreement_id)
        if agreement is None:
            raise HTTPException(status_code=404, detail=translate("errors.agreement_not_found", locale=get_locale()))
        entity = WorkPackage(
            agreement_id=data.agreement_id,
            name=data.name,
            scope=data.scope,
            planned_value=data.planned_value,
            completion_percent=data.completion_percent,
            status=data.status,
        )
        await self.work_packages.create(entity)
        return entity

    async def update_work_package(
        self,
        wp_id: uuid.UUID,
        data: WorkPackageUpdate,
    ) -> WorkPackage:
        entity = await self.work_packages.get_by_id(wp_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Work package not found")
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.work_packages.update_fields(wp_id, **fields)
            await self.session.refresh(entity)
        return entity

    async def delete_work_package(self, wp_id: uuid.UUID) -> None:
        await self.work_packages.delete(wp_id)

    # ── Payment applications ───────────────────────────────────────────

    async def submit_payment_application(
        self,
        data: PaymentApplicationCreate,
        user_id: str | None = None,
        *,
        today: date | None = None,
    ) -> PaymentApplication:
        agreement = await self.agreements.get_by_id(data.agreement_id)
        if agreement is None:
            raise HTTPException(status_code=404, detail=translate("errors.agreement_not_found", locale=get_locale()))

        gross = Decimal(str(data.gross_amount))
        if gross <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Payment application gross amount must be greater than zero",
            )
        # Can only claim against an agreement that has been signed off.
        if agreement.status not in ("active", "completed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot submit a payment application against an agreement "
                    f"in status {agreement.status!r}; agreement must be active"
                ),
            )

        # Prequalification gate (TOP-30 #20): no payment for a blocked or
        # rejected/suspended vendor, even on an already-active agreement.
        await self._assert_subcontractor_awardable(agreement.subcontractor_id)

        # Block submission if required certs are missing / expired.
        certs = await self.certs.list_by_subcontractor(agreement.subcontractor_id)
        block = next_payment_blocked(certs, today=today)
        if block.blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "payment_blocked",
                    "reasons": block.reasons,
                },
            )

        retention_pct = Decimal(str(agreement.retention_percent))
        retention_amount = (gross * retention_pct / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        net_amount = gross - retention_amount
        application_number = data.application_number or (await self.payments.next_application_number(data.agreement_id))
        currency = data.currency or agreement.currency

        entity = PaymentApplication(
            agreement_id=data.agreement_id,
            application_number=application_number,
            period_start=data.period_start,
            period_end=data.period_end,
            gross_amount=gross,
            retention_amount=retention_amount,
            net_amount=net_amount,
            currency=currency,
            status="submitted",
            submitted_at=datetime.now(UTC),
            created_by=user_id,
        )
        await self.payments.create(entity)

        # Persist lines (if any).
        for line in data.lines:
            await self.payment_lines.create(
                PaymentApplicationLine(
                    payment_application_id=entity.id,
                    work_package_id=line.work_package_id,
                    claimed_amount=line.claimed_amount,
                    certified_amount=line.certified_amount,
                    approved_amount=line.approved_amount,
                )
            )

        # Retention ledger: accrual entry tied to this application.
        await self.retention.create(
            RetentionLedger(
                agreement_id=data.agreement_id,
                payment_application_id=entity.id,
                accrued_amount=retention_amount,
                released_amount=Decimal("0"),
            )
        )

        event_bus.publish_detached(
            "subcontractors.payment_application.submitted",
            {
                "payment_application_id": str(entity.id),
                "agreement_id": str(data.agreement_id),
                "subcontractor_id": str(agreement.subcontractor_id),
                "gross_amount": str(gross),
                "net_amount": str(net_amount),
                "currency": currency,
            },
            source_module="subcontractors",
        )
        return entity

    async def update_payment_application(
        self,
        payment_id: uuid.UUID,
        data: PaymentApplicationUpdate,
    ) -> PaymentApplication:
        entity = await self.payments.get_by_id(payment_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Payment application not found")
        if entity.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted payment applications can be edited",
            )
        fields = data.model_dump(exclude_unset=True)
        # Recompute retention if gross changes.
        if "gross_amount" in fields and fields["gross_amount"] is not None:
            gross = Decimal(str(fields["gross_amount"]))
            if gross <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Payment application gross amount must be greater than zero",
                )
            agreement = await self.agreements.get_by_id(entity.agreement_id)
            if agreement is None:
                raise HTTPException(
                    status_code=404, detail=translate("errors.agreement_not_found", locale=get_locale())
                )
            retention_amount = (gross * Decimal(str(agreement.retention_percent)) / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            fields["retention_amount"] = retention_amount
            fields["net_amount"] = gross - retention_amount
            # Keep the linked accrual ledger entry in lock-step - otherwise the
            # retention balance drifts away from the recomputed PA retention.
            for ledger in await self.retention.list_for_payment_application(payment_id):
                if ledger.released_amount == 0:
                    await self.retention.update_fields(
                        ledger.id,
                        accrued_amount=retention_amount,
                    )
        if fields:
            await self.payments.update_fields(payment_id, **fields)
            await self.session.refresh(entity)
        return entity

    async def approve_payment_application_foreman(
        self,
        payment_id: uuid.UUID,
        user_id: str,
    ) -> PaymentApplication:
        return await self._transition_payment(
            payment_id,
            "foreman_approved",
            extra={"foreman_approved_at": datetime.now(UTC), "foreman_approved_by": user_id},
        )

    async def approve_payment_application_finance(
        self,
        payment_id: uuid.UUID,
        user_id: str,
    ) -> PaymentApplication:
        await self._assert_lien_waiver_ok(payment_id)
        return await self._transition_payment(
            payment_id,
            "finance_approved",
            extra={"finance_approved_at": datetime.now(UTC), "finance_approved_by": user_id},
        )

    async def mark_paid(self, payment_id: uuid.UUID) -> PaymentApplication:
        await self._assert_lien_waiver_ok(payment_id)
        return await self._transition_payment(
            payment_id,
            "paid",
            extra={"paid_at": datetime.now(UTC)},
        )

    async def lien_waiver_status(self, payment_id: uuid.UUID) -> tuple[bool, PaymentBlockResult]:
        """Return ``(required, block_result)`` for a payment application.

        Read-only sibling of :meth:`_assert_lien_waiver_ok` so the UI can show a
        waiver badge and disable approve/pay before the user clicks. ``required``
        distinguishes "no waiver needed" from "waiver on file and clear", both of
        which are ``blocked=False``.
        """
        payment = await self.payments.get_by_id(payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment application not found")
        agreement = await self.agreements.get_by_id(payment.agreement_id)
        required = bool(getattr(agreement, "requires_lien_waiver", False))
        waivers = await self.lien_waivers.list_for_payment_app(payment_id) if required else []
        return required, lien_waiver_blocked(payment.net_amount, waivers, required=required)

    async def _assert_lien_waiver_ok(self, payment_id: uuid.UUID) -> None:
        """Raise 409 if the agreement requires a lien waiver that is not on file.

        No-op for agreements that do not require waivers, so existing payment
        flows are unaffected.
        """
        _required, result = await self.lien_waiver_status(payment_id)
        if result.blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": result.reasons[0] if result.reasons else "missing_waiver",
                    "message": ("This payment is blocked until a signed lien waiver covering the amount is on file."),
                    "reasons": result.reasons,
                },
            )

    async def reject_payment_application(
        self,
        payment_id: uuid.UUID,
        reason: str,
    ) -> PaymentApplication:
        entity = await self.payments.get_by_id(payment_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Payment application not found")
        if entity.status in ("paid", "rejected"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot reject a payment in status {entity.status}",
            )
        await self.payments.update_fields(
            payment_id,
            status="rejected",
            rejection_reason=reason,
        )
        # Reverse the retention accrual booked at submission - a rejected
        # payment application must not keep inflating the pending-retention
        # balance for the agreement.
        for ledger in await self.retention.list_for_payment_application(payment_id):
            if ledger.released_amount == 0 and ledger.accrued_amount != 0:
                await self.retention.update_fields(
                    ledger.id,
                    accrued_amount=Decimal("0"),
                    notes=(ledger.notes or "") + f" [reversed: payment {entity.application_number} rejected]",
                )
        await self.session.refresh(entity)
        return entity

    async def _transition_payment(
        self,
        payment_id: uuid.UUID,
        target: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> PaymentApplication:
        entity = await self.payments.get_by_id(payment_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Payment application not found")
        _assert_transition(entity.status, target, _PAYMENT_TRANSITIONS, "payment")
        payload: dict[str, Any] = {"status": target}
        if extra:
            payload.update(extra)
        await self.payments.update_fields(payment_id, **payload)
        await self.session.refresh(entity)

        if target == "paid":
            event_bus.publish_detached(
                "subcontractors.payment_application.paid",
                {
                    "payment_application_id": str(entity.id),
                    "agreement_id": str(entity.agreement_id),
                    "net_amount": str(entity.net_amount),
                    "currency": entity.currency,
                },
                source_module="subcontractors",
            )
        return entity

    # ── Retention ──────────────────────────────────────────────────────

    async def accrue_retention(
        self,
        agreement_id: uuid.UUID,
        amount: Decimal,
        payment_application_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> RetentionLedger:
        entry = RetentionLedger(
            agreement_id=agreement_id,
            payment_application_id=payment_application_id,
            accrued_amount=amount,
            released_amount=Decimal("0"),
            notes=notes,
        )
        await self.retention.create(entry)
        return entry

    async def release_retention(
        self,
        agreement_id: uuid.UUID,
        amount: Decimal,
        reason: str,
    ) -> RetentionLedger:
        agreement = await self.agreements.get_by_id(agreement_id)
        if agreement is None:
            raise HTTPException(status_code=404, detail=translate("errors.agreement_not_found", locale=get_locale()))
        # Never release more than the outstanding accrued balance - releasing
        # phantom retention would push the agreement's balance negative and
        # over-pay the subcontractor.
        balance = await self.retention_balance(agreement_id)
        if amount > balance:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Cannot release {amount}: exceeds the outstanding retention balance of {balance}"),
            )
        entry = RetentionLedger(
            agreement_id=agreement_id,
            payment_application_id=None,
            accrued_amount=Decimal("0"),
            released_amount=amount,
            released_at=datetime.now(UTC),
            release_reason=reason,
        )
        await self.retention.create(entry)
        event_bus.publish_detached(
            "subcontractors.retention.released",
            {
                "agreement_id": str(agreement_id),
                "amount": str(amount),
                "reason": reason,
            },
            source_module="subcontractors",
        )
        return entry

    async def retention_balance(self, agreement_id: uuid.UUID) -> Decimal:
        entries = await self.retention.list_for_agreement(agreement_id)
        accrued = sum((e.accrued_amount for e in entries), Decimal("0"))
        released = sum((e.released_amount for e in entries), Decimal("0"))
        return Decimal(accrued) - Decimal(released)

    # ── Rating ─────────────────────────────────────────────────────────

    async def update_rating(
        self,
        data: RatingCreate,
        events: dict[str, Any] | None = None,
    ) -> SubcontractorRating:
        await self.get_subcontractor(data.subcontractor_id)

        # If `events` are provided, recompute scores from them; else use
        # explicit fields from the payload.
        if events:
            rating = compute_rating(events)
            quality = rating.quality_score
            hse = rating.hse_score
            schedule = rating.schedule_score
            cost = rating.cost_score
            overall = rating.overall_score
            basis = rating.basis | (data.basis or {})
        else:
            quality = data.quality_score
            hse = data.hse_score
            schedule = data.schedule_score
            cost = data.cost_score
            overall = _clamp(
                Decimal(str(quality)) * DEFAULT_RATING_WEIGHTS["quality"]
                + Decimal(str(hse)) * DEFAULT_RATING_WEIGHTS["hse"]
                + Decimal(str(schedule)) * DEFAULT_RATING_WEIGHTS["schedule"]
                + Decimal(str(cost)) * DEFAULT_RATING_WEIGHTS["cost"]
            )
            basis = data.basis

        existing = await self.ratings.get_for_period(data.subcontractor_id, data.period)
        if existing is not None:
            await self.ratings.update_fields(
                existing.id,
                quality_score=quality,
                hse_score=hse,
                schedule_score=schedule,
                cost_score=cost,
                overall_score=overall,
                basis=basis,
            )
            await self.session.refresh(existing)
            entity = existing
        else:
            entity = SubcontractorRating(
                subcontractor_id=data.subcontractor_id,
                period=data.period,
                quality_score=quality,
                hse_score=hse,
                schedule_score=schedule,
                cost_score=cost,
                overall_score=overall,
                basis=basis,
            )
            await self.ratings.create(entity)

        # Roll-up onto the subcontractor itself.
        await self.subs.update_fields(data.subcontractor_id, rating_score=overall)
        # ``update_fields`` runs ``session.expire_all()``, which also
        # expires the rating ``entity`` created/updated above. Reload it
        # before returning so the response serializer doesn't trigger a
        # lazy load outside the async greenlet (MissingGreenlet -> 500).
        await self.session.refresh(entity)
        return entity

    # ── Dashboard ──────────────────────────────────────────────────────

    async def dashboard(
        self,
        sub_id: uuid.UUID,
        *,
        today: date | None = None,
    ) -> SubcontractorDashboard:
        sub = await self.get_subcontractor(sub_id)
        agreements = await self.agreements.list_for_subcontractor(sub_id)
        active_agreements = sum(1 for a in agreements if a.status == "active")

        # R5: collapse N+1 - single COUNT over all of this sub's agreements
        # and a single SUM(GROUP BY) over the retention ledger. Old code
        # fired 2 queries per agreement; for a sub with 30 agreements that
        # was 60 round-trips per dashboard hit.
        agreement_ids = [a.id for a in agreements]
        count_batched = getattr(self.payments, "count_open_for_agreements", None)
        if count_batched is not None:
            open_payments = await count_batched(agreement_ids)
        else:
            open_payments = 0
            for ag in agreements:
                payments = await self.payments.list_for_agreement(ag.id)
                open_payments += sum(
                    1
                    for p in payments
                    if p.status
                    in (
                        "submitted",
                        "foreman_approved",
                        "finance_approved",
                    )
                )
        # Money correctness: each SubcontractAgreement carries its OWN
        # currency, so retention balances must be grouped by currency rather
        # than blended into one scalar. ``pending_retention`` is kept for
        # back-compat (only meaningful when all agreements share a currency),
        # and ``retention_by_currency`` carries the per-currency breakdown.
        # A blank/unknown currency is bucketed under "" - never silently
        # treated as a hardcoded "EUR" default.
        agreement_currency: dict[uuid.UUID, str] = {a.id: (a.currency or "") for a in agreements}
        retention_by_currency: dict[str, Decimal] = {}

        def _add_retention(currency: str, value: Decimal) -> None:
            retention_by_currency[currency] = retention_by_currency.get(currency, Decimal("0")) + value

        balance_batched = getattr(self.retention, "balance_for_agreements", None)
        if balance_batched is not None:
            balances = await balance_batched(agreement_ids)
            pending_retention = Decimal("0")
            for ag_id, (accrued, released) in balances.items():
                bal = Decimal(accrued) - Decimal(released)
                pending_retention += bal
                _add_retention(agreement_currency.get(ag_id, ""), bal)
        else:
            pending_retention = Decimal("0")
            for ag in agreements:
                bal = await self.retention_balance(ag.id)
                pending_retention += bal
                _add_retention(ag.currency or "", bal)

        # Sort the breakdown deterministically (by currency code) so the
        # response is stable across calls. ``mixed_currency`` flags that the
        # scalar ``pending_retention`` blends >1 distinct currency and so
        # must not be presented as a meaningful total.
        retention_breakdown = [
            CurrencyAmount(currency=cur, amount=amt) for cur, amt in sorted(retention_by_currency.items())
        ]
        mixed_currency = len(retention_by_currency) > 1

        ref = today or date.today()
        certs = await self.certs.list_by_subcontractor(sub_id)
        expired = sum(1 for c in certs if c.valid_until is not None and c.valid_until < ref)
        expiring_soon = sum(
            1
            for c in certs
            if c.valid_until is not None and ref <= c.valid_until <= (ref + timedelta(days=60)) and not c.revoked
        )
        block = next_payment_blocked(certs, today=ref)

        return SubcontractorDashboard(
            subcontractor_id=sub.id,
            legal_name=sub.legal_name,
            prequalification_status=sub.prequalification_status,
            rating_score=sub.rating_score,
            active_agreements=active_agreements,
            open_payment_applications=open_payments,
            pending_retention=pending_retention,
            pending_retention_by_currency=retention_breakdown,
            mixed_currency=mixed_currency,
            expired_certificates=expired,
            expiring_soon_certificates=expiring_soon,
            blocked=block.blocked,
            block_reasons=block.reasons,
        )

    # ── SOV (Schedule of Values) ───────────────────────────────────────

    async def sov_summary(self, agreement_id: uuid.UUID) -> SOVSummaryResponse:
        """Build a Schedule-of-Values rollup for a subcontract agreement.

        For each work package under the agreement, sums the claimed /
        certified / approved amounts across every payment-application line
        that targets it. ``remaining = planned_value - approved_to_date``.

        The buyer (GC) uses this view to track progress payments against
        the master agreement and ensure they don't over-pay relative to
        physical completion.
        """
        agreement = await self.agreements.get_by_id(agreement_id)
        if agreement is None:
            raise HTTPException(status_code=404, detail=translate("errors.agreement_not_found", locale=get_locale()))

        work_packages = await self.work_packages.list_for_agreement(agreement_id)
        payment_apps = await self.payments.list_for_agreement(agreement_id)
        # Pull all lines for every PA in one pass.
        line_index: dict[uuid.UUID, list[Any]] = {wp.id: [] for wp in work_packages}
        for pa in payment_apps:
            lines = await self.payment_lines.list_for_application(pa.id)
            for line in lines:
                line_index.setdefault(line.work_package_id, []).append(line)

        rows: list[SOVRow] = []
        totals = {
            "planned_value": Decimal("0"),
            "claimed_to_date": Decimal("0"),
            "certified_to_date": Decimal("0"),
            "approved_to_date": Decimal("0"),
            "remaining": Decimal("0"),
        }
        for wp in work_packages:
            claimed = sum(
                (Decimal(line.claimed_amount or 0) for line in line_index.get(wp.id, [])),
                Decimal("0"),
            )
            certified = sum(
                (Decimal(line.certified_amount or 0) for line in line_index.get(wp.id, [])),
                Decimal("0"),
            )
            approved = sum(
                (Decimal(line.approved_amount or 0) for line in line_index.get(wp.id, [])),
                Decimal("0"),
            )
            planned = Decimal(wp.planned_value or 0)
            remaining = planned - approved
            if remaining < 0:
                remaining = Decimal("0")
            rows.append(
                SOVRow(
                    work_package_id=wp.id,
                    name=wp.name,
                    planned_value=planned,
                    completion_percent=Decimal(wp.completion_percent or 0),
                    claimed_to_date=claimed,
                    certified_to_date=certified,
                    approved_to_date=approved,
                    remaining=remaining,
                    status=wp.status,
                )
            )
            totals["planned_value"] += planned
            totals["claimed_to_date"] += claimed
            totals["certified_to_date"] += certified
            totals["approved_to_date"] += approved
            totals["remaining"] += remaining

        return SOVSummaryResponse(
            agreement_id=agreement.id,
            subcontractor_id=agreement.subcontractor_id,
            project_id=agreement.project_id,
            total_value=Decimal(agreement.total_value or 0),
            currency=agreement.currency or "",
            rows=rows,
            totals=totals,
        )

    # ── Rating bump from cross-module event ────────────────────────────

    async def bump_rating_from_event(
        self,
        subcontractor_id: uuid.UUID,
        kind: str,
        *,
        period: str | None = None,
    ) -> SubcontractorRating | None:
        """Recompute a subcontractor's rating after an event.

        ``kind`` is one of:
            ``ncr``         - +1 NCR for the current month
            ``hse``         - +1 HSE incident for the current month
            ``schedule``    - +1 schedule-deviation day
            ``cost_over``   - +1 cost-variance percent point

        Looks up the current period's rating row (or creates it), increments
        the relevant counter recorded in ``basis``, and recomputes the
        weighted overall score via :func:`compute_rating`.

        Returns the new rating row, or ``None`` if the subcontractor does
        not exist (silently - we don't want to block upstream events on a
        deleted-sub edge case).
        """
        sub = await self.subs.get_by_id(subcontractor_id)
        if sub is None:
            return None

        period_str = period or date.today().strftime("%Y-%m")
        existing = await self.ratings.get_for_period(subcontractor_id, period_str)

        # Pull prior basis or seed an empty one. ``basis`` is a JSON column
        # that can carry user-supplied values (via `update_rating`), so coerce
        # defensively - a poisoned counter must not 500 the event subscriber.
        def _basis_int(value: Any) -> int:
            try:
                return int(Decimal(str(value))) if value not in (None, "") else 0
            except (InvalidOperation, ValueError, TypeError):
                return 0

        def _basis_decimal(value: Any) -> Decimal:
            try:
                return Decimal(str(value)) if value not in (None, "") else Decimal("0")
            except (InvalidOperation, ValueError, TypeError):
                return Decimal("0")

        basis = dict(existing.basis or {}) if existing is not None else {}
        ncr_count = _basis_int(basis.get("ncr_count"))
        hse_incidents = _basis_int(basis.get("hse_incidents"))
        schedule_dev = _basis_int(basis.get("schedule_deviations_days"))
        cost_var = _basis_decimal(basis.get("cost_variance_percent"))

        if kind == "ncr":
            ncr_count += 1
        elif kind == "hse":
            hse_incidents += 1
        elif kind == "schedule":
            schedule_dev += 1
        elif kind == "cost_over":
            cost_var += Decimal("1")
        else:
            return existing

        events = {
            "ncr_count": ncr_count,
            "hse_incidents": hse_incidents,
            "schedule_deviations_days": schedule_dev,
            "cost_variance_percent": cost_var,
        }
        rating = compute_rating(events)

        if existing is not None:
            await self.ratings.update_fields(
                existing.id,
                quality_score=rating.quality_score,
                hse_score=rating.hse_score,
                schedule_score=rating.schedule_score,
                cost_score=rating.cost_score,
                overall_score=rating.overall_score,
                basis=rating.basis,
            )
            await self.session.refresh(existing)
            entity = existing
        else:
            entity = SubcontractorRating(
                subcontractor_id=subcontractor_id,
                period=period_str,
                quality_score=rating.quality_score,
                hse_score=rating.hse_score,
                schedule_score=rating.schedule_score,
                cost_score=rating.cost_score,
                overall_score=rating.overall_score,
                basis=rating.basis,
            )
            await self.ratings.create(entity)

        await self.subs.update_fields(subcontractor_id, rating_score=rating.overall_score)
        event_bus.publish_detached(
            "subcontractors.rating.updated",
            {
                "subcontractor_id": str(subcontractor_id),
                "period": period_str,
                "overall_score": str(rating.overall_score),
                "trigger": kind,
            },
            source_module="subcontractors",
        )
        return entity

    # ── Prequalification read model (TOP-30 #20) ───────────────────────

    async def prequal_view(self, sub_id: uuid.UUID) -> dict[str, Any]:
        """Build the current prequalification state for a subcontractor.

        Returns the persisted questionnaire + score plus a freshly recomputed
        answer-key score and the list of still-unanswered required questions,
        so the UI can render the form and the reviewer panel from one read.
        """
        sub = await self.get_subcontractor(sub_id)
        answers = sub.prequal_questionnaire or {}
        missing = validate_questionnaire(answers) if answers else []
        computed = compute_prequal_score(answers) if answers else None
        return {
            "subcontractor_id": sub.id,
            "prequalification_status": sub.prequalification_status,
            "prequal_score": sub.prequal_score,
            "prequal_questionnaire": sub.prequal_questionnaire,
            "prequal_completed_at": sub.prequal_completed_at,
            "is_blocked": bool(sub.is_blocked),
            "blocked_reason": sub.blocked_reason,
            "missing_required": missing,
            "computed_score": computed,
            "approval_threshold": PREQUAL_APPROVAL_THRESHOLD,
        }

    # ── Monthly rating rollup (TOP-30 #20) ─────────────────────────────

    async def compute_monthly_rating(
        self,
        subcontractor_id: uuid.UUID,
        period: str,
    ) -> SubcontractorRating | None:
        """Recompute and persist a subcontractor's rating for ``period``.

        ``period`` is a ``YYYY-MM`` string. The compute is the authoritative
        monthly rollup behind the cron / admin trigger. It combines two
        signal sources and takes the larger of the two per metric so neither
        a dropped event nor an un-landed cross-lane column undercounts:

        1. The counters already accumulated on the period's rating ``basis``
           by the event subscribers (``bump_rating_from_event``) - the live,
           low-latency path that is fully in this module's lane.
        2. A direct count of source rows for the period where the cross-lane
           linkage columns exist (``oe_ncr_ncr.responsible_subcontractor_id``,
           ``oe_safety_incident.responsible_subcontractor_id``, schedule
           slips on ``oe_schedule_activity.assigned_subcontractor_id``). When
           those columns are absent (the owning lanes have not shipped them
           yet) the direct count contributes zero and the event path stands
           alone - so this method is correct today and forward-compatible.

        The rollup is idempotent: it upserts the single
        ``(subcontractor_id, period)`` row (DB-unique), so a double-compute of
        the same month produces the same authoritative figures rather than a
        duplicate row (TC-10). Emits ``subcontractors.rating.updated``.

        Returns the rating row, or ``None`` if the subcontractor is unknown.
        """
        sub = await self.subs.get_by_id(subcontractor_id)
        if sub is None:
            return None

        existing = await self.ratings.get_for_period(subcontractor_id, period)

        def _basis_int(value: Any) -> int:
            try:
                return int(Decimal(str(value))) if value not in (None, "") else 0
            except (InvalidOperation, ValueError, TypeError):
                return 0

        accumulated = dict(existing.basis or {}) if existing is not None else {}
        ncr_acc = _basis_int(accumulated.get("ncr_count"))
        hse_acc = _basis_int(accumulated.get("hse_incidents"))
        sched_acc = _basis_int(accumulated.get("schedule_deviations_days"))

        direct = await self._count_source_events(subcontractor_id, period)

        events = {
            "ncr_count": max(ncr_acc, direct["ncr_count"]),
            "hse_incidents": max(hse_acc, direct["hse_incidents"]),
            "schedule_deviations_days": max(sched_acc, direct["schedule_deviations_days"]),
            # Cost variance has no cross-lane source row yet - carry whatever
            # the event path accumulated (kept as a string in basis).
            "cost_variance_percent": accumulated.get("cost_variance_percent") or 0,
        }
        rating = compute_rating(events)
        # Record where each metric came from for auditability.
        rating.basis["sources"] = {
            "ncr_count": {"event": ncr_acc, "direct": direct["ncr_count"]},
            "hse_incidents": {"event": hse_acc, "direct": direct["hse_incidents"]},
            "schedule_deviations_days": {
                "event": sched_acc,
                "direct": direct["schedule_deviations_days"],
            },
        }

        if existing is not None:
            await self.ratings.update_fields(
                existing.id,
                quality_score=rating.quality_score,
                hse_score=rating.hse_score,
                schedule_score=rating.schedule_score,
                cost_score=rating.cost_score,
                overall_score=rating.overall_score,
                basis=rating.basis,
            )
            await self.session.refresh(existing)
            entity = existing
        else:
            entity = SubcontractorRating(
                subcontractor_id=subcontractor_id,
                period=period,
                quality_score=rating.quality_score,
                hse_score=rating.hse_score,
                schedule_score=rating.schedule_score,
                cost_score=rating.cost_score,
                overall_score=rating.overall_score,
                basis=rating.basis,
            )
            try:
                await self.ratings.create(entity)
            except IntegrityError:
                # Two computes raced past the read-then-write check above and
                # both tried to INSERT the same (sub, period). The unique
                # constraint rejected the loser; reload the winner and update
                # it so the result is still the authoritative recompute.
                await self.session.rollback()
                existing = await self.ratings.get_for_period(subcontractor_id, period)
                if existing is None:
                    raise
                await self.ratings.update_fields(
                    existing.id,
                    quality_score=rating.quality_score,
                    hse_score=rating.hse_score,
                    schedule_score=rating.schedule_score,
                    cost_score=rating.cost_score,
                    overall_score=rating.overall_score,
                    basis=rating.basis,
                )
                await self.session.refresh(existing)
                entity = existing

        await self.subs.update_fields(subcontractor_id, rating_score=rating.overall_score)
        await self.session.refresh(entity)
        event_bus.publish_detached(
            "subcontractors.rating.updated",
            {
                "subcontractor_id": str(subcontractor_id),
                "period": period,
                "overall_score": str(rating.overall_score),
                "basis": rating.basis,
                "trigger": "monthly_compute",
            },
            source_module="subcontractors",
        )
        return entity

    async def _count_source_events(
        self,
        subcontractor_id: uuid.UUID,
        period: str,
    ) -> dict[str, int]:
        """Count NCR / HSE / schedule-slip source rows for the period.

        Reads the cross-lane source tables directly via raw SQL, guarded by
        runtime column reflection so a missing linkage column (owning lane has
        not shipped it) degrades to a zero count rather than erroring. The
        result feeds :meth:`compute_monthly_rating`. Counting failures never
        propagate - the event-accumulated basis remains the floor.
        """
        zero = {"ncr_count": 0, "hse_incidents": 0, "schedule_deviations_days": 0}
        # Pure-logic / stub sessions (unit tests) have no real connection;
        # bail out cleanly so the event path is used.
        run_sync = getattr(self.session, "run_sync", None)
        if run_sync is None:
            return dict(zero)

        try:
            from sqlalchemy import inspect as _sa_inspect

            def _columns(sync_conn: Any, table: str) -> set[str]:
                insp = _sa_inspect(sync_conn)
                if table not in set(insp.get_table_names()):
                    return set()
                return {c["name"] for c in insp.get_columns(table)}

            conn = await self.session.connection()
            ncr_cols = await conn.run_sync(_columns, "oe_ncr_ncr")
            safety_cols = await conn.run_sync(_columns, "oe_safety_incident")
            sched_cols = await conn.run_sync(_columns, "oe_schedule_activity")
        except Exception:  # noqa: BLE001 - reflection must never break the rollup
            logger.debug("compute_monthly_rating: column reflection failed", exc_info=True)
            return dict(zero)

        result = dict(zero)
        sub_str = str(subcontractor_id)
        like = f"{period}%"  # created_at::text starts with YYYY-MM

        # NCR - one row per non-conformance attributed to this sub in the month.
        if "responsible_subcontractor_id" in ncr_cols:
            result["ncr_count"] = await self._scalar_count(
                "oe_ncr_ncr",
                sub_str,
                like,
                sub_col="responsible_subcontractor_id",
            )
        # Safety incidents.
        if "responsible_subcontractor_id" in safety_cols:
            result["hse_incidents"] = await self._scalar_count(
                "oe_safety_incident",
                sub_str,
                like,
                sub_col="responsible_subcontractor_id",
            )
        # Schedule slips - activities assigned to this sub that finished late
        # (negative total float) within the month.
        if "assigned_subcontractor_id" in sched_cols:
            extra = ""
            if "total_float" in sched_cols:
                extra = " AND total_float IS NOT NULL AND total_float < 0"
            result["schedule_deviations_days"] = await self._scalar_count(
                "oe_schedule_activity",
                sub_str,
                like,
                sub_col="assigned_subcontractor_id",
                extra_where=extra,
            )
        return result

    async def _scalar_count(
        self,
        table: str,
        subcontractor_id: str,
        period_like: str,
        *,
        sub_col: str,
        extra_where: str = "",
    ) -> int:
        """Run a guarded ``COUNT(*)`` for one source table; 0 on any error.

        ``table`` and ``sub_col`` are internal allow-listed identifiers (never
        user input), so interpolating them into the SQL is safe; the values
        bind as parameters.
        """
        from sqlalchemy import text as _text

        sql = _text(
            f"SELECT COUNT(*) FROM {table} "  # noqa: S608 - identifiers are internal constants
            f"WHERE {sub_col} = :sid AND CAST(created_at AS TEXT) LIKE :period{extra_where}"
        )
        try:
            value = (await self.session.execute(sql, {"sid": subcontractor_id, "period": period_like})).scalar_one()
            return int(value or 0)
        except Exception:  # noqa: BLE001
            logger.debug("compute_monthly_rating: count on %s failed", table, exc_info=True)
            return 0

    # ── Wave 4 / T12 - construction management platform style prequal + insurance ─

    async def submit_prequal(
        self,
        sub_id: uuid.UUID,
        questionnaire_data: dict[str, Any],
        score: int | None = None,
        *,
        require_complete: bool = False,
    ) -> Subcontractor:
        """Persist a questionnaire payload + computed/explicit score.

        If ``score`` is ``None`` the service derives a value from the
        questionnaire answers via :func:`compute_prequal_score`, which scores
        the canonical question spec by an answer key (correct / total * 100)
        and falls back to the generic any-yes/no scorer for third-party
        questionnaires whose keys it does not recognise.

        When ``require_complete`` is true every REQUIRED question must carry
        a recognisable yes/no answer, otherwise a 400 is raised naming the
        missing keys (TC-14). The default is false so a partial draft can be
        saved and iterated on from the UI.

        ``prequal_completed_at`` is stamped to UTC now and rolls up onto
        the subcontractor row for cheap list-view rendering.
        """
        await self.get_subcontractor(sub_id)
        if require_complete:
            missing = validate_questionnaire(questionnaire_data)
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "incomplete_questionnaire",
                        "message": "Required questions are unanswered.",
                        "missing": missing,
                    },
                )
        computed = score if score is not None else compute_prequal_score(questionnaire_data)
        completed_at = datetime.now(UTC)
        await self.subs.update_fields(
            sub_id,
            prequal_questionnaire=questionnaire_data,
            prequal_score=computed,
            prequal_completed_at=completed_at,
        )
        event_bus.publish_detached(
            "subcontractors.prequal.submitted",
            {
                "subcontractor_id": str(sub_id),
                "score": computed,
            },
            source_module="subcontractors",
        )
        # Re-fetch so the response carries the freshly written values
        # rather than the stale pre-update row.
        return await self.get_subcontractor(sub_id)

    async def flag_expiring_insurance(
        self,
        days_ahead: int = 30,
        *,
        today: date | None = None,
    ) -> list[Subcontractor]:
        """Return subcontractors with insurance expiring within ``days_ahead``.

        Past-expiry rows are also surfaced - once expired the cert keeps
        showing on the report until the sub re-uploads. Subs whose
        ``insurance_expiry_date`` is NULL are NOT surfaced here (use a
        separate "missing insurance" report for that - emitting both in
        one list would conflate two distinct workflows).

        Emits ``subcontractors.insurance.expiring`` per flagged sub so
        notifications / digest queues can fan out per-sub.
        """
        ref = today or date.today()
        upper_bound = ref + timedelta(days=max(0, days_ahead))
        rows = await self.subs.list_with_insurance_expiry_within(
            upper_bound=upper_bound,
        )
        for sub in rows:
            event_bus.publish_detached(
                "subcontractors.insurance.expiring",
                {
                    "subcontractor_id": str(sub.id),
                    "legal_name": sub.legal_name,
                    "insurance_expiry_date": (
                        sub.insurance_expiry_date.isoformat() if sub.insurance_expiry_date else None
                    ),
                    "days_until_expiry": (
                        (sub.insurance_expiry_date - ref).days if sub.insurance_expiry_date else None
                    ),
                },
                source_module="subcontractors",
            )
        return rows

    async def block_subcontractor(
        self,
        sub_id: uuid.UUID,
        reason: str,
        by_user_id: str | None = None,
    ) -> Subcontractor:
        """Hard-block a subcontractor from bidding / payment.

        Sets ``is_blocked=True`` and stores the human-readable
        ``blocked_reason``. The reason is required so audit logs and the
        UI can surface "why" without spelunking through the event bus.
        """
        await self.get_subcontractor(sub_id)
        await self.subs.update_fields(
            sub_id,
            is_blocked=True,
            blocked_reason=reason,
        )
        event_bus.publish_detached(
            "subcontractors.blocked",
            {
                "subcontractor_id": str(sub_id),
                "reason": reason,
                "by_user_id": by_user_id,
            },
            source_module="subcontractors",
        )
        return await self.get_subcontractor(sub_id)

    async def unblock_subcontractor(
        self,
        sub_id: uuid.UUID,
        by_user_id: str | None = None,
    ) -> Subcontractor:
        """Clear the block flag + reason on a subcontractor."""
        await self.get_subcontractor(sub_id)
        await self.subs.update_fields(
            sub_id,
            is_blocked=False,
            blocked_reason=None,
        )
        event_bus.publish_detached(
            "subcontractors.unblocked",
            {
                "subcontractor_id": str(sub_id),
                "by_user_id": by_user_id,
            },
            source_module="subcontractors",
        )
        return await self.get_subcontractor(sub_id)


# ── Prequal score helper ─────────────────────────────────────────────────


# ── Structured prequalification questionnaire (TOP-30 #20) ───────────────────
#
# The default questionnaire shipped with the platform. Each entry is the
# question key, whether it is required, and the answer that scores a point
# (``expected``). Real GCs author their own questionnaires; this canonical set
# keeps the feature working out of the box and gives the validator / scorer a
# deterministic shape to score against.
#
# ``expected`` semantics: a "positive" question (license current?) scores when
# answered "yes"; a "negative" question (open HSE incidents?) scores when
# answered "no". This mirrors the frontend PrequalModal question set so the
# client-side preview score matches the server-trusted score.


@dataclass(frozen=True)
class PrequalQuestion:
    """One question in a prequalification questionnaire spec."""

    key: str
    required: bool
    expected: str  # "yes" or "no" - the answer that scores a point


DEFAULT_PREQUAL_QUESTIONS: tuple[PrequalQuestion, ...] = (
    PrequalQuestion("license_current", required=True, expected="yes"),
    PrequalQuestion("wcb_coverage", required=True, expected="yes"),
    PrequalQuestion("insurance_current", required=True, expected="yes"),
    PrequalQuestion("safety_program", required=True, expected="yes"),
    PrequalQuestion("references_available", required=True, expected="yes"),
    PrequalQuestion("financial_statements", required=True, expected="yes"),
    PrequalQuestion("has_open_incidents", required=True, expected="no"),
    PrequalQuestion("has_unpaid_liens", required=True, expected="no"),
)

# Default approval threshold for the structured scorer. A prequalification at or
# above this score is eligible to be auto-flagged for approval; below it the
# reviewer must approve explicitly. Kept as a module constant so the route layer
# and the tests share one source of truth.
PREQUAL_APPROVAL_THRESHOLD: int = 70


def _normalise_yes_no(value: Any) -> str | None:
    """Coerce a free-form answer to ``"yes"`` / ``"no"`` / ``None``.

    ``None`` means "not a recognisable yes/no answer" (unanswered or a
    scale/text answer that the structured scorer cannot evaluate).
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in _PREQUAL_TRUTHY:
            return "yes"
        if normalised in _PREQUAL_NEGATIVE:
            return "no"
    return None


def validate_questionnaire(
    answers: dict[str, Any],
    questions: tuple[PrequalQuestion, ...] = DEFAULT_PREQUAL_QUESTIONS,
) -> list[str]:
    """Return the list of missing / unanswered REQUIRED question keys.

    A required question is satisfied when its answer normalises to a
    recognisable yes/no value. An empty list means the questionnaire is
    complete and scoreable; a non-empty list drives a 400 at the route
    boundary (TC-14).
    """
    missing: list[str] = []
    for q in questions:
        if not q.required:
            continue
        if _normalise_yes_no(answers.get(q.key)) is None:
            missing.append(q.key)
    return missing


def compute_prequal_score(
    answers: dict[str, Any],
    questions: tuple[PrequalQuestion, ...] = DEFAULT_PREQUAL_QUESTIONS,
) -> int:
    """Score a structured questionnaire against an answer key, 0-100.

    Score = correct_answers / total_questions * 100, rounded to the nearest
    integer. A "correct" answer is one that matches the question's
    ``expected`` value (yes for positive questions, no for negative ones).
    Unanswered / unrecognised answers count as incorrect - they do not
    shrink the denominator, so leaving questions blank lowers the score
    rather than inflating it.

    Example (TC-1): 6 of 8 questions correct -> 6 / 8 * 100 = 75.

    Falls back to the generic any-yes/no scorer when none of the spec's
    keys appear in ``answers`` (a custom questionnaire the platform does
    not know the answer key for).
    """
    if not questions:
        return _compute_prequal_score(answers)
    known = sum(1 for q in questions if q.key in answers)
    if known == 0:
        # The submitted answers don't use the canonical spec at all - score
        # generically so a third-party questionnaire still produces a value.
        return _compute_prequal_score(answers)
    correct = 0
    for q in questions:
        if _normalise_yes_no(answers.get(q.key)) == q.expected:
            correct += 1
    return int(round((correct / len(questions)) * 100))


_PREQUAL_TRUTHY: frozenset[str] = frozenset(
    {
        "yes",
        "true",
        "y",
        "1",
        "ok",
        "pass",
        "passed",
        "compliant",
    }
)
_PREQUAL_NEGATIVE: frozenset[str] = frozenset(
    {
        "no",
        "false",
        "n",
        "0",
        "fail",
        "failed",
        "non-compliant",
        "noncompliant",
    }
)


def _compute_prequal_score(answers: dict[str, Any]) -> int:
    """Generic Yes/No questionnaire scorer.

    Walks every value in the answers dict; truthy strings (``"yes"`` /
    ``"true"``) and Python ``True`` count as 1, negative strings
    (``"no"`` / ``"false"``) and Python ``False`` count as 0; anything
    else (numeric scales, text answers) is ignored so it doesn't poison
    the denominator. If no recognisable Yes/No answers exist the score
    is 0 - better than dividing by zero.
    """
    yes = 0
    counted = 0
    for value in answers.values():
        if isinstance(value, bool):
            counted += 1
            if value:
                yes += 1
            continue
        if isinstance(value, str):
            normalised = value.strip().lower()
            if normalised in _PREQUAL_TRUTHY:
                counted += 1
                yes += 1
                continue
            if normalised in _PREQUAL_NEGATIVE:
                counted += 1
                continue
        # Numeric / non-Yes-No answers are intentionally skipped so a
        # mixed questionnaire (some scales, some Yes/No) doesn't double-
        # count the scale slots as zeros.
    if counted == 0:
        return 0
    return int(round((yes / counted) * 100))
