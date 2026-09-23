# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Roll subcontractor pay applications up into the GC's progress claim.

A general contractor's monthly bill to the owner is, line by line, mostly what
its subcontractors billed it that month. This module lines the two up: for one
GC progress claim it takes the subcontractor pay applications a person included
in it, maps each of their lines onto the GC's schedule of values, and reports
per GC line what the subs claimed, what was certified and approved, whether a
lien waiver covers it and whether the sub's certificates held through the
period end, or, for a certificate the national pack reads on the day of
payment, on that day.

It suggests; it never writes a claim line. The amounts it derives reach the
claim only through the contracts module's existing preview and commit path,
after a person has looked at them.

Layout
------
* Pure functions (:func:`build_claim_rollup`, :func:`resolve_contract_line`,
  :func:`waiver_state`, :func:`resolve_prime_contract`, :func:`claim_period`,
  :func:`order_claims`, :func:`suggest_claim_lines`,
  :func:`rule_context_from_rollup`) take plain objects with the model's
  attribute names and return plain dicts. No session, no ORM query, so each is
  tested with simple namespaces.
* :func:`claim_rule_context` is the one async entry point. This module
  registers it with the contracts module's claim context registry at startup
  (``claim_rules.register_sub_rollup_context``), which is how contracts reads
  subcontract facts for the ``pay_application`` rule set without importing
  this module at all.

Currencies are never blended. A pay application whose currency differs from
the claim's is left out of every figure and counted instead. A blank currency
on either side is unknown rather than different: the column defaults to ``""``
and legacy rows carry it, so treating blank as a mismatch would refuse them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.subcontractors.service import (
    REQUIRED_CERT_TYPES_FOR_PAYMENT,
    SubcontractorService,
    _is_payment_waiver,
    evaluate_required_certificates,
)
from app.modules.subcontractors.validators import MONEY_TOLERANCE

ZERO = Decimal("0")
HUNDRED = Decimal("100")

#: Claim statuses whose billed amounts are part of the record. A rejected claim
#: billed nothing, so pay applications rolled into it do not count as billed.
_REJECTED_CLAIM_STATUS = "rejected"

#: The payment status after which a sub's lien rights for the period should be
#: released unconditionally.
_PAID_STATUS = "paid"


#: The ``valid_at`` a pack gives a certificate that counts on the day the sub is
#: paid rather than at the claim's period end.
_VALID_AT_PAYMENT_DATE = "payment_date"


@dataclass(frozen=True)
class PaymentDateRequirement:
    """A certificate the law reads on the day the sub is paid, not at the period end.

    The German exemption certificate is the case this exists for: section 48b
    EStG exempts a payment only when the certificate is valid on the day the
    payment is made. A certificate that held on the last day of the claim's
    period and ran out before the money went is no exemption at all.

    Attributes:
        cert_type: The certificate type, as the certificate register spells it.
        withholding_scheme: The tax withholding scheme that applies to a
            payment the certificate does not cover, when the pack names one.
        reference: The statute the pack cites for this requirement.
    """

    cert_type: str
    withholding_scheme: str | None = None
    reference: str | None = None


@dataclass(frozen=True)
class SubPaymentRequirements:
    """What a subcontractor must hold before being paid on this project.

    Attributes:
        certificate_types: Certificate types the sub must hold. Every one of
            them is judged at the period end except those in ``payment_date``.
        lien_waiver_required: Whether the national practice expects a lien
            waiver with every payment, independently of the agreement's own
            ``requires_lien_waiver`` switch.
        source: ``pack`` when a national regional pack supplied these,
            ``fallback`` when none did and the module's built-in list applies.
        reference: The statute or source the pack cites, when it cites one.
        payment_date: The certificates the pack says are judged on the
            payment date (``valid_at: "payment_date"``). Empty for every pack
            that judges all of them at the period end.
    """

    certificate_types: tuple[str, ...] = REQUIRED_CERT_TYPES_FOR_PAYMENT
    lien_waiver_required: bool = False
    source: str = "fallback"
    reference: str | None = None
    payment_date: tuple[PaymentDateRequirement, ...] = ()

    @property
    def period_end_types(self) -> tuple[str, ...]:
        """The certificate types judged at the claim's period end."""
        on_payment = {req.cert_type for req in self.payment_date}
        return tuple(t for t in self.certificate_types if t not in on_payment)


def _payment_date_requirements(raw: Any) -> tuple[PaymentDateRequirement, ...]:
    """The pack's certificate requirements whose ``valid_at`` is the payment date."""
    if not isinstance(raw, list | tuple):
        return ()
    found: list[PaymentDateRequirement] = []
    for item in raw:
        if not isinstance(item, Mapping) or item.get("valid_at") != _VALID_AT_PAYMENT_DATE:
            continue
        cert_type = str(item.get("cert_type") or "").strip()
        if not cert_type or any(req.cert_type == cert_type for req in found):
            continue
        scheme = str(item.get("withholding_scheme") or "").strip()
        reference = str(item.get("statute_reference") or "").strip()
        found.append(PaymentDateRequirement(cert_type, scheme or None, reference or None))
    return tuple(found)


def requirements_from_pack(progress_billing: Mapping[str, Any] | None) -> SubPaymentRequirements:
    """Read the ``sub_payment_requirements`` block of a pack's ``progress_billing``.

    The expected shape is ``{"certificate_types": [...], "lien_waiver_required":
    bool, "statute_reference" | "source": str, "requirements": [...]}``. When the
    pack answers nothing, or answers without a certificate list, the built-in
    ``REQUIRED_CERT_TYPES_FOR_PAYMENT`` applies and the result says so in
    ``source``, so a reader can tell a country's rule from this module's
    default rather than taking the default for law.

    Each entry of ``requirements`` may say when its certificate counts
    (``valid_at``). ``period_end`` is what ``certificate_types`` has always
    meant. ``payment_date`` entries are collected into
    :attr:`SubPaymentRequirements.payment_date` and judged on the day the sub
    is paid instead.
    """
    block = progress_billing.get("sub_payment_requirements") if isinstance(progress_billing, Mapping) else None
    if not isinstance(block, Mapping):
        return SubPaymentRequirements()
    raw_types = block.get("certificate_types")
    types = tuple(str(t).strip() for t in raw_types if str(t).strip()) if isinstance(raw_types, list | tuple) else ()
    reference = block.get("statute_reference") or block.get("source")
    return SubPaymentRequirements(
        certificate_types=types or REQUIRED_CERT_TYPES_FOR_PAYMENT,
        lien_waiver_required=block.get("lien_waiver_required") is True,
        source="pack" if types else "fallback",
        reference=str(reference) if reference else None,
        payment_date=_payment_date_requirements(block.get("requirements")),
    )


def withholding_terms(scheme_code: str | None, reference: str | None = None) -> dict[str, Any] | None:
    """What the withholding scheme takes from a payment no certificate covers.

    Read from the shipped scheme catalogue of the tax withholding module: the
    rate a payee without the certificate is deducted at, whether the base
    includes VAT, and the small-amount limit per calendar year where the
    scheme has one. ``reference`` is the statute the pack cites and wins over
    the catalogue's shorter one.

    ``None`` when the pack names no scheme, the scheme is not shipped, or the
    tax withholding module is not installed. The caller then still says that
    withholding may apply, only without a figure it cannot vouch for.
    """
    if not scheme_code:
        return None
    try:
        from app.modules.tax_withholding.data import regime_by_scheme  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        # Only the absence of the module is a normal install.
        if exc.name not in ("app.modules.tax_withholding", "app.modules.tax_withholding.data"):
            raise
        return None
    regime = regime_by_scheme(scheme_code)
    if not regime:
        return None
    band = next(
        (b for b in regime.get("bands") or [] if b.get("code") == regime.get("default_band_code")),
        None,
    )
    if band is None or band.get("rate_pct") in (None, ""):
        return None
    limit = regime.get("threshold_amount")
    return {
        "scheme": scheme_code,
        "rate_pct": str(band["rate_pct"]),
        "vat_included": not regime.get("vat_excluded", False),
        "annual_limit": str(limit) if limit not in (None, "") else None,
        "currency": str(regime.get("currency_code") or ""),
        "reference": reference or str(regime.get("legal_reference") or "") or None,
    }


# ── Small pure helpers ───────────────────────────────────────────────────────


def _dec(value: Any) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return ZERO


def _as_date(value: Any) -> date | None:
    """A ``date`` from a date, a datetime or an ISO string; ``None`` otherwise."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value.strip()) >= 10:
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def currencies_differ(first: str | None, second: str | None) -> bool:
    """Two populated, different ISO codes. Blank on either side is unknown, not different."""
    a = (first or "").strip().upper()
    b = (second or "").strip().upper()
    return bool(a) and bool(b) and a != b


def pay_app_currency(pay_app: Any, agreement: Any | None) -> str:
    """The currency a pay application is in: its own, else its agreement's.

    Mirrors ``submit_payment_application``, which stores ``data.currency or
    agreement.currency``.
    """
    own = str(getattr(pay_app, "currency", "") or "").strip()
    if own:
        return own.upper()
    return str(getattr(agreement, "currency", "") or "").strip().upper()


def resolve_contract_line(line: Any, wp_by_id: Mapping[uuid.UUID, Any]) -> uuid.UUID | None:
    """The GC schedule-of-values line a pay-application line bills under.

    The line's own override wins, then its work package's default, then
    nothing. Nothing is a real answer: the line is reported unmapped rather
    than placed on a guessed line.
    """
    own = getattr(line, "contract_line_id", None)
    if own is not None:
        return own
    package = wp_by_id.get(getattr(line, "work_package_id", None))
    return getattr(package, "contract_line_id", None) if package is not None else None


def waiver_state(waivers: Iterable[Any], net_amount: Any) -> dict[str, Any]:
    """Summarise the lien waivers filed against one pay application.

    ``state`` is the strongest payment waiver present (unconditional, then
    conditional, then none); W-9 and W-8 tax forms never count, exactly as in
    the payment gate. ``covers_net`` is that gate's own test: the largest
    waiver amount is at least the net. The through-date is the latest one among
    waivers of the reported state, read from ``through_date`` and, for a waiver
    filed before that column existed, from ``signed_date``: a waiver signed on
    a day cannot release work done after it, so the signing date is an honest
    upper bound, and ``through_date_basis`` says when it was used.
    """
    payment = [w for w in waivers if _is_payment_waiver(str(getattr(w, "waiver_type", "") or ""))]
    unconditional = [w for w in payment if str(w.waiver_type).startswith("unconditional")]
    strongest = unconditional or payment
    state = "unconditional" if unconditional else ("conditional" if payment else "none")
    covered = max((_dec(w.amount) for w in payment), default=ZERO)
    through: date | None = None
    basis: str | None = None
    for waiver in strongest:
        own = _as_date(getattr(waiver, "through_date", None))
        candidate, candidate_basis = (own, "through_date") if own else (_as_date(waiver.signed_date), "signed_date")
        if candidate is not None and (through is None or candidate > through):
            through, basis = candidate, candidate_basis
    return {
        "state": state,
        "amount_covered": covered,
        "covers_net": bool(payment) and covered >= _dec(net_amount),
        "through_date": through,
        "through_date_basis": basis,
    }


def unconditional_through(waivers: Iterable[Any]) -> date | None:
    """The latest day an unconditional waiver on file releases, or ``None``."""
    unconditional = [
        w
        for w in waivers
        if _is_payment_waiver(str(getattr(w, "waiver_type", "") or ""))
        and str(w.waiver_type).startswith("unconditional")
    ]
    return waiver_state(unconditional, ZERO)["through_date"] if unconditional else None


def resolve_prime_contract(
    agreement: Any,
    active_client_contract_ids: Sequence[uuid.UUID],
) -> tuple[uuid.UUID | None, str]:
    """Which GC prime contract a subcontract agreement sits under, and why.

    The agreement's own ``prime_contract_id`` when it names one. Otherwise the
    project's single active client contract, because a project with one prime
    contract leaves nothing to decide. With several and none named, the answer
    is ``None`` and ``ambiguous``: picking one would put a sub's billing on the
    wrong owner's bill, so a person has to name it.
    """
    explicit = getattr(agreement, "prime_contract_id", None)
    if explicit is not None:
        return explicit, "explicit"
    if len(active_client_contract_ids) == 1:
        return active_client_contract_ids[0], "single_active_client"
    if not active_client_contract_ids:
        return None, "none"
    return None, "ambiguous"


def claim_period(claim: Any) -> tuple[date | None, date | None, str]:
    """The claim's billing period and how it was read.

    Typed ``period_from`` / ``period_to`` columns win when the claim carries
    them (``dates``). Otherwise the string columns are parsed with the contracts
    module's ``parse_iso_day`` when that parser exists (``parsed``); it maps a
    bare month onto its first and last day and refuses to guess day-month
    order. With neither, the period is unknown (``explicit_only``) and only pay
    applications a person included are considered: matching on dates this
    module had to guess would include the wrong month's work.
    """
    typed_from = _as_date(getattr(claim, "period_from", None))
    typed_to = _as_date(getattr(claim, "period_to", None))
    if typed_from is not None or typed_to is not None:
        return typed_from, typed_to, "dates"
    try:
        from app.modules.contracts.periods import parse_iso_day  # noqa: PLC0415
    except ImportError:
        return None, None, "explicit_only"
    start = parse_iso_day(getattr(claim, "period_start", None), bound="start")
    end = parse_iso_day(getattr(claim, "period_end", None), bound="end")
    if start is None and end is None:
        return None, None, "explicit_only"
    return start, end, "parsed"


def in_period(pay_app: Any, period_from: date | None, period_to: date | None) -> bool | None:
    """Whether a pay application's period end falls inside the claim's period.

    ``None`` when either side is unknown, so nothing is asserted about a claim
    that has no period yet.
    """
    end = _as_date(getattr(pay_app, "period_end", None))
    if end is None or (period_from is None and period_to is None):
        return None
    if period_from is not None and end < period_from:
        return False
    return not (period_to is not None and end > period_to)


def order_claims(claims: Iterable[Any]) -> list[Any]:
    """Claims in billing order: by period end, undated last, then creation and number.

    Sorted in Python rather than SQL because a contract has a handful of
    claims, and because the period end is a typed column on some installs and
    a parsed string on others.

    The contracts module's own ordering is used when it has one, so that
    "earlier claim" here is the same set the claim's payment application counts
    as previously certified. Two orderings that agree until a tie would put a
    sub's payment in one claim's history and the GC's in another's.
    """
    try:
        from app.modules.contracts.periods import claim_order_key  # noqa: PLC0415
    except ImportError:
        claim_order_key = None
    if claim_order_key is not None:
        return sorted(claims, key=claim_order_key)

    def key(claim: Any) -> tuple[bool, date, datetime, str]:
        _, period_to, _ = claim_period(claim)
        created = getattr(claim, "created_at", None)
        created = created if isinstance(created, datetime) else datetime.min
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        return (period_to is None, period_to or date.min, created, str(getattr(claim, "claim_number", "") or ""))

    return sorted(claims, key=key)


def earlier_claim_ids(claims: Iterable[Any], claim_id: uuid.UUID) -> list[uuid.UUID]:
    """Ids of the non-rejected claims billed before ``claim_id`` on the same contract."""
    ordered = [c for c in order_claims(claims) if c.status != _REJECTED_CLAIM_STATUS or c.id == claim_id]
    ids = [c.id for c in ordered]
    if claim_id not in ids:
        return []
    return ids[: ids.index(claim_id)]


# ── Certificates judged on the payment date ──────────────────────────────────

#: Payment-date states that are not a verdict yet: the pay application is
#: unpaid, so the day the certificate is read on does not exist.
PENDING_PAYMENT_STATES = frozenset({"pending", "pending_open", "pending_invalid"})


def payment_day(pay_app: Any) -> date | None:
    """The day a paid pay application was paid, or ``None`` while it is not.

    The day is the UTC calendar day of ``paid_at``, which is when a person
    marked the pay application paid in this platform. That is the closest
    record of the payment it keeps; the bank's value date is not recorded. A
    ``paid_at`` without a timezone is read as UTC, which is how it is stored.
    """
    if getattr(pay_app, "status", None) != _PAID_STATUS:
        return None
    paid_at = getattr(pay_app, "paid_at", None)
    if isinstance(paid_at, datetime):
        if paid_at.tzinfo is not None:
            paid_at = paid_at.astimezone(UTC)
        return paid_at.date()
    return _as_date(paid_at)


def _judge_on_payment_date(
    pay_app: Any,
    certificates: Sequence[Any],
    requirement: PaymentDateRequirement,
    *,
    paid_on: date | None,
    as_of: date | None,
) -> dict[str, Any] | None:
    """One payment-date certificate for one pay application; ``None`` when it covered the payment.

    Paid, the certificate is judged on the payment day with the module's own
    per-type reading (inclusive boundary, a renewal counts). Unpaid, there is
    no verdict yet and the finding says so: ``pending`` with the end date of
    the certificate on file, ``pending_open`` when that one has no end date,
    and ``pending_invalid`` when nothing on file could cover a payment made
    after the period end, because it is missing, revoked or already ran out.
    """
    held = [c for c in certificates if getattr(c, "cert_type", None) == requirement.cert_type]
    live = [c for c in held if not getattr(c, "revoked", False)]
    open_ended = any(getattr(c, "valid_until", None) is None for c in live)
    ends = [c.valid_until for c in live if getattr(c, "valid_until", None) is not None]
    valid_until = None if open_ended or not ends else max(ends)
    lapsed_on: date | None = None
    if getattr(pay_app, "status", None) == _PAID_STATUS:
        if paid_on is None:
            state = "undated"
        else:
            verdict = evaluate_required_certificates(held, as_at=paid_on, required_types=(requirement.cert_type,))
            if not verdict:
                return None
            state, lapsed_on = verdict[0].state, verdict[0].lapsed_on
    elif not live or (not open_ended and as_of is not None and valid_until is not None and valid_until < as_of):
        state = "pending_invalid"
    else:
        state = "pending_open" if open_ended else "pending"
    return {
        "document_type": requirement.cert_type,
        "state": state,
        "judged_on": paid_on,
        "lapsed_on": lapsed_on,
        "valid_until": valid_until,
        "withholding": withholding_terms(requirement.withholding_scheme, requirement.reference),
    }


# ── The rollup ───────────────────────────────────────────────────────────────


def _pay_app_summary(
    pay_app: Any,
    *,
    agreement: Any | None,
    subcontractor_names: Mapping[uuid.UUID, str],
    lines: Sequence[Any],
    waivers: Sequence[Any],
    certificates: Sequence[Any],
    as_of: date | None,
    requirements: SubPaymentRequirements,
    currency: str,
    period: tuple[date | None, date | None],
) -> dict[str, Any]:
    """One pay application as the claim sees it: totals, waiver and certificates.

    A pack whose certificates are all judged at the period end gets exactly
    the keys it always got. Only a pack with payment-date certificates adds
    ``paid_on``, ``payment_date_findings`` and ``certificates_pending_payment``,
    and folds that verdict into ``certificates_ok``: ``False`` when a paid
    pay application was not covered on its payment day, ``None`` while the
    payment is still to come.
    """
    sub_id = getattr(agreement, "subcontractor_id", None)
    findings: list[dict[str, Any]] = []
    certificates_ok: bool | None = None
    if as_of is not None:
        # Judged as at the period end the claim bills for, never today. A
        # claim without a period end has no such date, and reporting its
        # certificates against today would flag or clear them for the wrong
        # month, so the answer stays unknown instead.
        findings = [
            {
                "document_type": f.document_type,
                "state": f.state,
                "source": f.source,
                "lapsed_on": f.lapsed_on,
            }
            for f in evaluate_required_certificates(
                certificates,
                as_at=as_of,
                required_types=requirements.period_end_types,
            )
        ]
        certificates_ok = not findings
    on_payment: dict[str, Any] = {}
    if requirements.payment_date:
        paid_on = payment_day(pay_app)
        judged = [
            _judge_on_payment_date(pay_app, certificates, req, paid_on=paid_on, as_of=as_of)
            for req in requirements.payment_date
        ]
        payment_findings = [f for f in judged if f is not None]
        pending = any(f["state"] in PENDING_PAYMENT_STATES for f in payment_findings)
        not_covered = any(f["state"] not in PENDING_PAYMENT_STATES for f in payment_findings)
        if findings or not_covered:
            certificates_ok = False
        elif pending:
            certificates_ok = None
        on_payment = {
            "paid_on": paid_on,
            "payment_date_findings": payment_findings,
            "certificates_pending_payment": pending,
        }
    return {
        "payment_application_id": pay_app.id,
        "application_number": pay_app.application_number,
        "agreement_id": pay_app.agreement_id,
        "agreement_title": str(getattr(agreement, "title", "") or ""),
        "subcontractor_id": sub_id,
        "subcontractor_name": subcontractor_names.get(sub_id, "") if sub_id is not None else "",
        "status": pay_app.status,
        "period_start": _as_date(getattr(pay_app, "period_start", None)),
        "period_end": _as_date(getattr(pay_app, "period_end", None)),
        "currency": pay_app_currency(pay_app, agreement),
        "gross_amount": _dec(pay_app.gross_amount),
        "net_amount": _dec(pay_app.net_amount),
        "claimed_amount": sum((_dec(ln.claimed_amount) for ln in lines), ZERO),
        "certified_amount": sum((_dec(ln.certified_amount) for ln in lines), ZERO),
        "approved_amount": sum((_dec(ln.approved_amount) for ln in lines), ZERO),
        # The claim bills a pay application through its lines, so one with
        # none bills nothing whatever its gross; the count lets the panel say
        # so instead of showing a bare zero.
        "line_count": len(lines),
        "progress_claim_id": getattr(pay_app, "progress_claim_id", None),
        "in_period": in_period(pay_app, *period),
        "requires_lien_waiver": bool(getattr(agreement, "requires_lien_waiver", False)),
        "waiver": waiver_state(waivers, pay_app.net_amount),
        "certificates_ok": certificates_ok,
        "certificate_findings": findings,
        "foreign_currency": currencies_differ(pay_app_currency(pay_app, agreement), currency),
        **on_payment,
    }


def build_claim_rollup(
    sov_lines: Sequence[Any],
    claim_lines: Sequence[Any],
    pay_apps: Sequence[Any],
    pay_app_lines: Sequence[Any],
    wp_by_id: Mapping[uuid.UUID, Any],
    waivers_by_pa: Mapping[uuid.UUID, Sequence[Any]],
    certs_by_sub: Mapping[uuid.UUID, Sequence[Any]],
    *,
    as_of: date | None,
    requirements: SubPaymentRequirements,
    currency: str,
    agreements_by_id: Mapping[uuid.UUID, Any],
    subcontractor_names: Mapping[uuid.UUID, str] | None = None,
    prior_pay_apps: Sequence[Any] = (),
    candidates: Sequence[Any] = (),
    period: tuple[date | None, date | None] = (None, None),
) -> dict[str, Any]:
    """Line up the pay applications included in one GC claim against its SOV.

    Args:
        sov_lines: The claim contract's schedule-of-values lines.
        claim_lines: The claim's own lines, for the GC's period figure per line.
        pay_apps: Pay applications included in this claim.
        pay_app_lines: Lines of every pay application in ``pay_apps`` and
            ``prior_pay_apps``.
        wp_by_id: Work packages by id, for the default line mapping.
        waivers_by_pa: Lien waivers by pay application id.
        certs_by_sub: Certificates by subcontractor id.
        as_of: The claim's period end, the date certificates are judged on;
            ``None`` when the claim has none, which leaves them unjudged. A
            certificate the pack judges on the payment date is read on each
            pay application's payment day instead, and is judged even when
            the claim has no period end.
        requirements: What a sub must hold before being paid.
        currency: The claim's currency. Pay applications in another one are
            counted in ``skipped_foreign_currency`` and nowhere else.
        agreements_by_id: Subcontract agreements by id.
        subcontractor_names: Display names by subcontractor id.
        prior_pay_apps: Pay applications included in earlier, non-rejected
            claims on the same contract. They add to the approved-to-date
            figure and are where the prior unconditional waivers are checked.
        candidates: Pay applications a person could still include.
        period: The claim's ``(from, to)``, for each candidate's ``in_period``.

    Returns:
        A dict matching ``ClaimSubRollupResponse`` minus the claim identity
        fields, plus ``prior_paid`` for the rules.
    """
    names = subcontractor_names or {}
    sov_by_id = {ln.id: ln for ln in sov_lines}
    parent_ids = {ln.parent_line_id for ln in sov_lines if getattr(ln, "parent_line_id", None) is not None}
    lines_by_pa: dict[uuid.UUID, list[Any]] = {}
    for line in pay_app_lines:
        lines_by_pa.setdefault(line.payment_application_id, []).append(line)

    gc_period: dict[uuid.UUID, Decimal] = {}
    for claim_line in claim_lines:
        gc_period[claim_line.contract_line_id] = gc_period.get(claim_line.contract_line_id, ZERO) + _dec(
            claim_line.period_completed_value
        )

    def summary(pay_app: Any) -> dict[str, Any]:
        agreement = agreements_by_id.get(pay_app.agreement_id)
        return _pay_app_summary(
            pay_app,
            agreement=agreement,
            subcontractor_names=names,
            lines=lines_by_pa.get(pay_app.id, []),
            waivers=waivers_by_pa.get(pay_app.id, []),
            certificates=certs_by_sub.get(getattr(agreement, "subcontractor_id", None), []),
            as_of=as_of,
            requirements=requirements,
            currency=currency,
            period=period,
        )

    def mapped(line: Any) -> tuple[uuid.UUID | None, str]:
        target = resolve_contract_line(line, wp_by_id)
        if target is None:
            return None, "none"
        if target not in sov_by_id:
            return None, "foreign_line"
        if target in parent_ids:
            return None, "parent_line"
        return target, ""

    rows_by_line: dict[uuid.UUID, list[dict[str, Any]]] = {}
    period_by_line: dict[uuid.UUID, Decimal] = {}
    to_date_by_line: dict[uuid.UUID, Decimal] = {}
    unmapped: list[dict[str, Any]] = []
    skipped_foreign = 0
    included: list[dict[str, Any]] = []

    for pay_app in pay_apps:
        info = summary(pay_app)
        included.append(info)
        pa_lines = lines_by_pa.get(pay_app.id, [])
        if info["foreign_currency"]:
            skipped_foreign += len(pa_lines)
            continue
        # One row per pay application per GC line, however many of its lines
        # land there: the reader wants "this sub billed X on this line".
        per_line: dict[uuid.UUID, dict[str, Any]] = {}
        for line in pa_lines:
            target, reason = mapped(line)
            if target is None:
                package = wp_by_id.get(line.work_package_id)
                unmapped.append(
                    {
                        "payment_application_id": pay_app.id,
                        "application_number": pay_app.application_number,
                        "subcontractor_name": info["subcontractor_name"],
                        "line_id": line.id,
                        "work_package_id": line.work_package_id,
                        "work_package_name": str(getattr(package, "name", "") or ""),
                        "approved_amount": _dec(line.approved_amount),
                        "claimed_amount": _dec(line.claimed_amount),
                        "reason": reason,
                        "contract_line_id": resolve_contract_line(line, wp_by_id),
                    }
                )
                continue
            row = per_line.setdefault(
                target,
                {
                    "payment_application_id": pay_app.id,
                    "application_number": pay_app.application_number,
                    "agreement_id": pay_app.agreement_id,
                    "subcontractor_id": info["subcontractor_id"],
                    "subcontractor_name": info["subcontractor_name"],
                    "status": pay_app.status,
                    "claimed_amount": ZERO,
                    "certified_amount": ZERO,
                    "approved_amount": ZERO,
                    "waiver_state": info["waiver"]["state"],
                    "waiver_covers_net": info["waiver"]["covers_net"],
                    "certificates_ok": info["certificates_ok"],
                    # Only where the pack judges a certificate on the payment
                    # date, so every other rollup keeps the keys it had.
                    **(
                        {"certificates_pending_payment": info["certificates_pending_payment"]}
                        if "certificates_pending_payment" in info
                        else {}
                    ),
                },
            )
            row["claimed_amount"] += _dec(line.claimed_amount)
            row["certified_amount"] += _dec(line.certified_amount)
            row["approved_amount"] += _dec(line.approved_amount)
        for target, row in per_line.items():
            rows_by_line.setdefault(target, []).append(row)
            period_by_line[target] = period_by_line.get(target, ZERO) + row["approved_amount"]
            to_date_by_line[target] = to_date_by_line.get(target, ZERO) + row["approved_amount"]

    prior_paid: list[dict[str, Any]] = []
    for pay_app in prior_pay_apps:
        agreement = agreements_by_id.get(pay_app.agreement_id)
        if pay_app.status == _PAID_STATUS:
            sub_id = getattr(agreement, "subcontractor_id", None)
            prior_paid.append(
                {
                    "payment_application_id": pay_app.id,
                    "application_number": pay_app.application_number,
                    "subcontractor_id": sub_id,
                    "subcontractor_name": names.get(sub_id, "") if sub_id is not None else "",
                    "period_end": _as_date(getattr(pay_app, "period_end", None)),
                    "unconditional_through": unconditional_through(waivers_by_pa.get(pay_app.id, [])),
                }
            )
        if pay_app.status == "rejected" or currencies_differ(pay_app_currency(pay_app, agreement), currency):
            continue
        for line in lines_by_pa.get(pay_app.id, []):
            target, _ = mapped(line)
            if target is not None:
                to_date_by_line[target] = to_date_by_line.get(target, ZERO) + _dec(line.approved_amount)

    lines_out: list[dict[str, Any]] = []
    for sov_line in sov_lines:
        line_id = sov_line.id
        if line_id not in rows_by_line and line_id not in to_date_by_line:
            continue
        scheduled = _dec(sov_line.total_value)
        to_date = to_date_by_line.get(line_id, ZERO)
        sub_period = period_by_line.get(line_id, ZERO)
        gc_value = gc_period.get(line_id, ZERO)
        lines_out.append(
            {
                "contract_line_id": line_id,
                "code": str(getattr(sov_line, "code", "") or ""),
                "description": str(getattr(sov_line, "description", "") or ""),
                "scheduled_value": scheduled,
                "gc_period_value": gc_value,
                "sub_period_approved": sub_period,
                "sub_approved_to_date": to_date,
                "variance": gc_value - sub_period,
                # Subcontract money is kept to two decimals and the GC line to
                # four, so a gap inside the money tolerance is rounding.
                "exceeds_scheduled_value": to_date - scheduled > MONEY_TOLERANCE,
                "subs": rows_by_line.get(line_id, []),
            }
        )

    def candidate_order(info: dict[str, Any]) -> tuple[int, date, str]:
        rank = {True: 0, None: 1, False: 2}[info["in_period"]]
        return (rank, info["period_end"] or date.max, str(info["application_number"]))

    return {
        "as_of": as_of,
        "currency": currency,
        "lines": lines_out,
        "included": included,
        "candidates": sorted((summary(pa) for pa in candidates), key=candidate_order),
        "unmapped_lines": unmapped,
        "prior_paid": prior_paid,
        "skipped_foreign_currency": skipped_foreign,
        "sub_period_approved_total": sum(period_by_line.values(), ZERO),
        "gc_period_total": sum(gc_period.values(), ZERO),
        "pack_requires_lien_waiver": requirements.lien_waiver_required,
        "requirements": {
            "certificate_types": list(requirements.certificate_types),
            "lien_waiver_required": requirements.lien_waiver_required,
            "source": requirements.source,
            "reference": requirements.reference,
            **(
                {"payment_date_types": [req.cert_type for req in requirements.payment_date]}
                if requirements.payment_date
                else {}
            ),
        },
    }


def suggest_claim_lines(
    rollup: Mapping[str, Any],
    sov_lines: Sequence[Any],
    claim_lines: Sequence[Any],
) -> list[dict[str, Any]]:
    """Turn a rollup into claim lines for the contracts preview.

    One item per GC line the subs billed on this period, carrying the period
    value (what the subs were approved for this period, capped at the line's
    scheduled value, as the commit route caps it) and the cumulative percent
    that the subs' approved-to-date represents. Every other line already on the
    claim is carried unchanged as ``existing``, because committing the preview
    replaces all of the claim's lines and would otherwise delete the GC's own
    work.
    """
    sov_by_id = {ln.id: ln for ln in sov_lines}
    current: dict[uuid.UUID, Decimal] = {}
    current_existing: dict[uuid.UUID, Any] = {}
    for claim_line in claim_lines:
        current[claim_line.contract_line_id] = current.get(claim_line.contract_line_id, ZERO) + _dec(
            claim_line.period_completed_value
        )
        current_existing[claim_line.contract_line_id] = claim_line

    items: list[dict[str, Any]] = []
    suggested: set[uuid.UUID] = set()
    for line in rollup.get("lines", []):
        period_value = _dec(line.get("sub_period_approved"))
        if period_value <= ZERO:
            continue
        sov_line = sov_by_id.get(line["contract_line_id"])
        if sov_line is None:
            continue
        scheduled = _dec(sov_line.total_value)
        to_date = _dec(line.get("sub_approved_to_date"))
        pct = (to_date / scheduled * HUNDRED) if scheduled > ZERO else ZERO
        pct = min(max(pct, ZERO), HUNDRED).quantize(Decimal("0.0001"))
        quantity = _dec(getattr(sov_line, "quantity", ZERO))
        billed = min(period_value, scheduled) if scheduled > ZERO else period_value
        # The period's share of the line quantity, in proportion to value: the
        # subs bill money, not quantity, so this is the only honest reading.
        period_qty = (quantity * billed / scheduled).quantize(Decimal("0.0001")) if scheduled > ZERO else ZERO
        items.append(
            {
                "contract_line_id": sov_line.id,
                "contract_line_code": str(sov_line.code or ""),
                "contract_line_description": str(sov_line.description or ""),
                "boq_position_id": None,
                "unit": getattr(sov_line, "unit", None),
                "contract_quantity": quantity,
                "contract_line_value": scheduled,
                "observed_pct": pct,
                "period_label": None,
                "recorded_at": None,
                "period_completed_qty": period_qty,
                "period_completed_value": billed,
                "cumulative_completed_value": min(to_date, scheduled) if scheduled > ZERO else to_date,
                "origin": "subcontract",
                "current_period_value": current.get(sov_line.id),
            }
        )
        suggested.add(sov_line.id)

    for line_id, value in current.items():
        if line_id in suggested:
            continue
        sov_line = sov_by_id.get(line_id)
        if sov_line is None:
            continue
        existing = current_existing[line_id]
        # Echo the line exactly as it stands, so committing it writes back
        # what is already there rather than a re-derivation of it.
        items.append(
            {
                "contract_line_id": line_id,
                "contract_line_code": str(sov_line.code or ""),
                "contract_line_description": str(sov_line.description or ""),
                "boq_position_id": None,
                "unit": getattr(sov_line, "unit", None),
                "contract_quantity": _dec(getattr(sov_line, "quantity", ZERO)),
                "contract_line_value": _dec(sov_line.total_value),
                "observed_pct": min(max(_dec(getattr(existing, "period_completed_pct", ZERO)), ZERO), HUNDRED),
                "period_label": None,
                "recorded_at": None,
                "period_completed_qty": _dec(getattr(existing, "period_completed_qty", ZERO)),
                "period_completed_value": value,
                "cumulative_completed_value": _dec(getattr(existing, "cumulative_completed_value", value)),
                "origin": "existing",
                "current_period_value": value,
            }
        )
    return items


# ── Rule context ─────────────────────────────────────────────────────────────


def _plain(value: Any) -> Any:
    """A JSON-safe copy: UUIDs and Decimals as strings, dates as ISO text."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def rule_context_from_rollup(rollup: Mapping[str, Any] | None) -> dict[str, Any]:
    """The ``subcontract_rollup`` entry of a claim's rule context.

    Empty when there is nothing to judge: no pay application included, none
    billed on an earlier claim, no unmapped line. The rules read an empty
    rollup as "no subcontract data" and report nothing, which is the right
    answer for a GC that self-performs the whole job.
    """
    if not rollup:
        return {}
    if not (rollup.get("included") or rollup.get("prior_paid") or rollup.get("lines")):
        return {}
    keys = (
        "as_of",
        "currency",
        "pack_requires_lien_waiver",
        "included",
        "prior_paid",
        "unmapped_lines",
        "lines",
        "requirements",
    )
    return {key: _plain(rollup.get(key)) for key in keys}


async def claim_rule_context(session: AsyncSession, claim: Any) -> dict[str, Any]:
    """Subcontract facts for one GC claim, as plain data for the rule engine.

    Registered as the contracts module's ``subcontract_rollup`` claim context
    provider, so its answer lands under ``context["subcontract_rollup"]`` for
    every claim the ``pay_application`` set checks. It reads only; a failure to load
    is raised rather than swallowed, because an empty answer would read as "no
    subcontract problems" on a claim that may have several.
    """
    rollup = await SubcontractorService(session).build_claim_rollup(claim)
    return rule_context_from_rollup(rollup)
