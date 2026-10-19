# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""KSeF rules.

The document rules register into the ``einvoice_clearance`` rule set, the way
Egypt's do. That set's ERROR rules are the gate the clearance service runs
before it calls an adapter, so an FA(2) document dated after FA(2) ended, or an
invoice whose P_18A disagrees with its own lines, never reaches KSeF. Every rule
here passes without reading anything on a document that is not Polish, because
the gate runs every rule of the set on every country.

* ``einvoice_clearance.pl_ksef_structure``       ERROR. Readable XML in the
      structure in force on the issue date (FA(3) from 2026-02-01), from the
      registration's own NIP, quoting valid KSeF numbers.
* ``einvoice_clearance.pl_ksef_split_payment``   ERROR. P_18A says what the
      lines and the total say.
* ``einvoice_clearance.pl_ksef_split_payment_unchecked`` WARNING. The VAT
      data holding the threshold could not be read, so P_18A went unchecked.
* ``einvoice_clearance.pl_ksef_registration``    ERROR. The KSeF settings are
      usable, including the end of token authentication.
* ``einvoice_clearance.pl_ksef_number_format``   ERROR. A cleared document's
      identifier is a KSeF number with a correct checksum.
* ``einvoice_clearance.pl_ksef_offline_deadline``WARNING. When an invoice
      issued offline has to be in KSeF, and whether that day has passed.
* ``einvoice_clearance.pl_ksef_annex_15_hint``   WARNING. A construction PKWiU
      on a line not marked Annex 15.
* ``einvoice_clearance.pl_ksef_nip``            ERROR. The seller and buyer NIP
      pass the shared party identifier check.
* ``einvoice_clearance.pl_ksef_nip_unchecked``  WARNING. That check is not
      installed, or its rule awaits expert review.

One rule registers into the ``finance`` set:

* ``finance.pl_ksef_number_in_payment_title``    The payment title carries the
      KSeF number. A warning before 2027-01-01 and an error from then; the
      severity is the payment date's, not the rule's.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.modules.einvoice_clearance.validators import EINVOICE_CLEARANCE_RULE_SET
from app.modules.einvoice_ksef import fa3, ksef_number, offline, split_payment
from app.modules.einvoice_ksef.adapter import KSEF_ADAPTER_KEY, settings_problems
from app.modules.einvoice_ksef.facts import FA2, FA3, schema_for_namespace
from app.modules.einvoice_ksef.payments import SEVERITY_ERROR, payment_title_finding

logger = logging.getLogger(__name__)

COUNTRY = "PL"
FINANCE_RULE_SET = "finance"
RECORD_PAYMENT = "payment"
KSEF_FORMATS = (FA3.key, FA2.key)


# ── Context readers ──────────────────────────────────────────────────────────


def _root(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _section(context: ValidationContext, key: str) -> dict[str, Any]:
    value = _root(context).get(key)
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _intent(context: ValidationContext) -> str:
    return _text(_root(context).get("intent")).lower() or "save"


def _is_polish(context: ValidationContext) -> bool:
    regime = _section(context, "regime")
    document = _section(context, "document")
    payload = _section(context, "payload")
    if COUNTRY in (_text(regime.get("country")).upper(), _text(document.get("country")).upper()):
        return True
    return _text(payload.get("format")) in KSEF_FORMATS


def _ksef_fields(context: ValidationContext) -> dict[str, Any]:
    fields = _section(context, "document").get("country_fields")
    value = fields.get("ksef") if isinstance(fields, dict) else None
    return value if isinstance(value, dict) else {}


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _text(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _today(context: ValidationContext) -> date:
    value = _root(context).get("reference_time")
    if isinstance(value, datetime):
        return value.date()
    raw = _text(value)
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return datetime.now(UTC).date()


def _decimal(value: Any) -> Decimal | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _nip(value: Any) -> str:
    raw = _text(value).upper().replace(" ", "").replace("-", "")
    return raw[2:] if raw.startswith("PL") else raw


class _KsefRule(ValidationRule):
    standard = "KSeF"

    def _ok(self, message: str = "OK") -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message=message,
        )

    def _fail(
        self,
        message: str,
        *,
        element_ref: str | None = None,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
        severity: Severity | None = None,
    ) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=message,
            element_ref=element_ref,
            suggestion=suggestion,
            details=details or {},
        )


def _document_id(context: ValidationContext) -> str | None:
    return _text(_section(context, "document").get("id")) or None


def _payload_text(context: ValidationContext) -> str:
    payload = _section(context, "payload")
    if _text(payload.get("format")) not in ("", *KSEF_FORMATS):
        return ""
    return _text(payload.get("text"))


# ── Document rules ───────────────────────────────────────────────────────────


class KsefStructure(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_structure"
    name = "KSeF Document Uses The Structure In Force"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "KSeF takes FA(3) for invoices issued from 2026-02-01; FA(2) ended on 2026-01-31."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context) or _intent(context) == "cancel":
            return [self._ok()]
        document = _section(context, "document")
        doc_id = _document_id(context)
        found: list[RuleResult] = []
        issue_day = _as_date(document.get("invoice_date"))
        declared = _text(document.get("document_format"))
        if declared == FA2.key and issue_day is not None and issue_day.isoformat() > FA2.valid_to:
            found.append(
                self._fail(
                    f"The document is declared {FA2.system_code}, which KSeF accepted only until {FA2.valid_to}; "
                    f"an invoice issued on {issue_day.isoformat()} has to be {FA3.system_code}.",
                    element_ref=doc_id,
                    suggestion=f"Rebuild the document as {FA3.system_code} from the invoice.",
                    details={"document_format": declared, "valid_to": FA2.valid_to},
                )
            )
        text = _payload_text(context)
        if not text:
            return found or [self._ok()]
        try:
            summary = fa3.read_summary(text)
        except fa3.Fa3BuildError as exc:
            return [
                *found,
                self._fail(
                    str(exc),
                    element_ref=doc_id,
                    suggestion="Rebuild the document from the invoice.",
                ),
            ]
        schema = schema_for_namespace(summary.namespace)
        day = _as_date(summary.issue_date) or issue_day
        if schema is None:
            found.append(
                self._fail(
                    f"The document's namespace {summary.namespace or '(none)'} is not a KSeF invoice structure.",
                    element_ref=doc_id,
                    suggestion=f"KSeF expects {FA3.namespace}.",
                    details={"namespace": summary.namespace},
                )
            )
        elif day is not None and not (schema.valid_from <= day.isoformat() <= (schema.valid_to or "9999-12-31")):
            found.append(
                self._fail(
                    f"{schema.system_code} applies from {schema.valid_from}"
                    + (f" to {schema.valid_to}" if schema.valid_to else "")
                    + f"; this invoice is dated {day.isoformat()}.",
                    element_ref=doc_id,
                    suggestion=f"Rebuild the document as {FA3.system_code}.",
                    details={"namespace": summary.namespace, "issue_date": day.isoformat()},
                )
            )
        elif summary.system_code and summary.system_code != schema.system_code:
            found.append(
                self._fail(
                    f"The form code says {summary.system_code} but the namespace is {schema.system_code}.",
                    element_ref=doc_id,
                    details={"system_code": summary.system_code, "namespace": summary.namespace},
                )
            )
        own_nip = _nip(_section(context, "profile").get("tax_registration_id"))
        if own_nip and summary.seller_nip and summary.seller_nip != own_nip:
            found.append(
                self._fail(
                    f"The seller NIP in the document is {summary.seller_nip}, the registration's is {own_nip}.",
                    element_ref=doc_id,
                    suggestion="Send the document through the registration of the company that issued it.",
                    details={"document_nip": summary.seller_nip, "profile_nip": own_nip},
                )
            )
        for number in summary.corrected_ksef_numbers:
            problems = ksef_number.problems(number)
            if problems:
                found.append(
                    self._fail(
                        f"The corrected invoice's KSeF number {number} is not valid: {'; '.join(problems)}.",
                        element_ref=doc_id,
                        suggestion="Copy the KSeF number from the corrected invoice's UPO.",
                        details={"ksef_number": number},
                    )
                )
        return found or [self._ok()]


# ── NIP ──────────────────────────────────────────────────────────────────────


def _nip_checker() -> Any:
    """The shared party identifier check, or ``None`` where it is not installed.

    The NIP checksum belongs to ``app.core.party_identifiers`` (scheme ``nip``
    for PL), not to this module, so it is written once for every caller.
    """
    try:
        from app.core.party_identifiers import check
    except ImportError:
        return None
    return check


def _field(result: Any, name: str) -> Any:
    return result.get(name) if isinstance(result, dict) else getattr(result, name, None)


def nip_verdict(value: str) -> tuple[bool | None, str, bool]:
    """``(valid, why, firm)``; ``valid`` is ``None`` when nothing checked it.

    ``firm`` is False when the shared check marks its own rule for expert
    review: an unconfirmed rule warns and does not block.
    """
    check = _nip_checker()
    result = check(COUNTRY, "nip", value) if check is not None else None
    if result is None:
        return None, "", False
    valid = _field(result, "valid")
    if valid is None:
        return None, "", False
    details = _field(result, "details")
    review = details.get("needs_expert_review") if isinstance(details, dict) else None
    firm = str(review).strip().lower() not in ("yes", "true", "1")
    return bool(valid), str(_field(result, "reason") or ""), firm


def _document_nips(context: ValidationContext) -> list[tuple[str, str]]:
    text = _payload_text(context)
    if not text:
        return []
    try:
        summary = fa3.read_summary(text)
    except fa3.Fa3BuildError:
        return []
    return [(who, nip) for who, nip in (("seller", summary.seller_nip), ("buyer", summary.buyer_nip)) if nip]


class KsefNipValid(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_nip"
    name = "Seller And Buyer NIP Are Valid"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "KSeF refuses an invoice whose NIP fails its checksum."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context) or _intent(context) == "cancel":
            return [self._ok()]
        found = []
        for who, nip in _document_nips(context):
            valid, why, firm = nip_verdict(nip)
            if valid is False and firm:
                found.append(
                    self._fail(
                        f"The {who} NIP {nip} is not valid{f': {why}' if why else ''}.",
                        element_ref=_document_id(context),
                        suggestion=f"Correct the {who}'s NIP and rebuild the document.",
                        details={"party": who, "nip": nip, "reason": why},
                    )
                )
        return found or [self._ok()]


class KsefNipUnchecked(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_nip_unchecked"
    name = "NIP Not Checked"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "No NIP check is installed, or its rule awaits expert review, so the NIP went unchecked."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context) or _intent(context) == "cancel":
            return [self._ok()]
        found = []
        for who, nip in _document_nips(context):
            valid, why, firm = nip_verdict(nip)
            if valid is None or (valid is False and not firm):
                found.append(
                    self._fail(
                        f"The {who} NIP {nip} was not checked"
                        + (f"; the check, still under review, says: {why}." if valid is False else "."),
                        element_ref=_document_id(context),
                        details={"party": who, "nip": nip},
                    )
                )
        return found or [self._ok()]


def _split_decision(context: ValidationContext) -> tuple[fa3.Summary, split_payment.SplitPaymentDecision] | None:
    text = _payload_text(context)
    if not text:
        return None
    try:
        summary = fa3.read_summary(text)
    except fa3.Fa3BuildError:
        # Unreadable is the structure rule's finding, not this one's.
        return None
    if summary.gross is None:
        return None
    decision = split_payment.decide(
        gross=summary.gross,
        currency=summary.currency or "PLN",
        annex_15_lines=summary.annex_15_lines,
        exchange_rate=_decimal(_ksef_fields(context).get("exchange_rate")),
    )
    return summary, decision


class KsefSplitPayment(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_split_payment"
    name = "Split Payment Marker Matches The Invoice"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "P_18A is required when a line covers Annex 15 goods or services and the gross total exceeds PLN 15,000."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context) or _intent(context) == "cancel":
            return [self._ok()]
        found = _split_decision(context)
        if found is None:
            return [self._ok()]
        summary, decision = found
        if decision.verdict == split_payment.NOT_CHECKED:
            # Reported by the not-checked warning; a missing table must not block.
            return [self._ok()]
        doc_id = _document_id(context)
        details = {
            "verdict": decision.verdict,
            "annex_15_lines": decision.annex_15_lines,
            "marked": summary.split_payment,
        }
        if decision.verdict == split_payment.UNDECIDABLE:
            return [
                self._fail(
                    f"Whether split payment applies cannot be decided: {decision.reason}.",
                    element_ref=doc_id,
                    suggestion="Enter the PLN exchange rate on the document (country fields, ksef.exchange_rate).",
                    details=details,
                )
            ]
        if decision.required and not summary.split_payment:
            return [
                self._fail(
                    f"The invoice needs the split payment marker P_18A: {decision.reason}.",
                    element_ref=doc_id,
                    suggestion="Rebuild the document; the builder sets P_18A from the Annex 15 lines.",
                    details=details,
                )
            ]
        if not decision.required and summary.split_payment:
            return [
                self._fail(
                    f"The invoice is marked P_18A but {decision.reason}.",
                    element_ref=doc_id,
                    suggestion="Check the Annex 15 flags on the lines and rebuild the document.",
                    details=details,
                )
            ]
        return [self._ok()]


class KsefSplitPaymentUnchecked(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_split_payment_unchecked"
    name = "Split Payment Not Checked"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "The Polish VAT data that holds the split payment threshold could not be read."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context) or _intent(context) == "cancel":
            return [self._ok()]
        found = _split_decision(context)
        if found is None or found[1].verdict != split_payment.NOT_CHECKED:
            return [self._ok()]
        summary, decision = found
        return [
            self._fail(
                f"P_18A was not checked: {decision.reason}. The document says "
                f"{'split payment' if summary.split_payment else 'no split payment'}.",
                element_ref=_document_id(context),
                suggestion="Check the split payment marker by hand, or restore the Polish VAT data.",
                details={"verdict": decision.verdict, "marked": summary.split_payment},
            )
        ]


class KsefRegistrationReady(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_registration"
    name = "KSeF Registration Is Usable"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The KSeF settings name an environment, a context and an authentication that still works."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        profile = _section(context, "profile")
        if not _is_polish(context) or _text(profile.get("adapter_key")) != KSEF_ADAPTER_KEY:
            return [self._ok()]
        if _intent(context) != "submit":
            return [self._ok()]
        problems = settings_problems(profile, today=_today(context))
        return [
            self._fail(
                f"The KSeF registration cannot be used: {problem}.",
                element_ref=_text(profile.get("id")) or None,
                suggestion="Fix the registration's KSeF settings.",
                details={"problem": problem},
            )
            for problem in problems
        ] or [self._ok()]


class KsefNumberFormat(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_number_format"
    name = "Cleared Document Carries A Valid KSeF Number"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A KSeF number is the seller NIP, the date, twelve hex digits and a CRC-8 checksum."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context):
            return [self._ok()]
        document = _section(context, "document")
        value = _text(document.get("authority_identifier"))
        if not value or value.startswith(ksef_number.PENDING_HANDLE_PREFIX):
            return [self._ok()]
        if _text(document.get("status")) != "cleared":
            return [self._ok()]
        problems = ksef_number.problems(value)
        if not problems:
            return [self._ok()]
        return [
            self._fail(
                f"The stored KSeF number {value} is not valid: {'; '.join(problems)}.",
                element_ref=_document_id(context),
                suggestion="Copy the KSeF number from the UPO, or refresh the document from KSeF.",
                details={"ksef_number": value},
            )
        ]


class KsefOfflineDeadline(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_offline_deadline"
    name = "Offline Invoice Upload Deadline"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "An invoice issued offline has to be sent to KSeF by a deadline that depends on the mode."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context) or _intent(context) == "cancel":
            return [self._ok()]
        fields = _ksef_fields(context)
        key = _text(fields.get("offline_mode"))
        document = _section(context, "document")
        if not key or _text(document.get("status")) in ("cleared", "accepted", "cancelled"):
            return [self._ok()]
        doc_id = _document_id(context)
        issue_day = _as_date(document.get("invoice_date"))
        if issue_day is None:
            return [self._ok()]
        try:
            deadline = offline.upload_deadline(
                key,
                issue_date=issue_day,
                event_end=_as_date(fields.get("offline_event_end")),
                failure_end=_as_date(fields.get("offline_failure_end")),
            )
        except offline.OfflineError as exc:
            return [
                self._fail(
                    str(exc),
                    element_ref=doc_id,
                    suggestion="Set ksef.offline_mode, and for offline or awaria ksef.offline_event_end.",
                    details={"offline_mode": key},
                )
            ]
        if deadline.due is None:
            return [
                self._fail(
                    deadline.explanation,
                    element_ref=doc_id,
                    details={"offline_mode": deadline.mode},
                )
            ]
        caveat = (
            ""
            if deadline.holidays_known
            else " Polish public holidays are not in the calendar, so the real day may be later."
        )
        today = _today(context)
        details = {
            "offline_mode": deadline.mode,
            "due": deadline.due.isoformat(),
            "holidays_known": deadline.holidays_known,
        }
        if offline.is_overdue(deadline, today):
            return [
                self._fail(
                    f"This invoice should have been in KSeF by {deadline.due.isoformat()} ({deadline.explanation}).{caveat}",
                    element_ref=doc_id,
                    suggestion="Send it now; a late upload is still required.",
                    details={**details, "overdue": True},
                )
            ]
        return [
            self._fail(
                f"Send this invoice to KSeF by {deadline.due.isoformat()} ({deadline.explanation}).{caveat}",
                element_ref=doc_id,
                details={**details, "overdue": False},
            )
        ]


class KsefAnnex15Hint(_KsefRule):
    rule_id = "einvoice_clearance.pl_ksef_annex_15_hint"
    name = "Construction Line Not Marked Annex 15"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Many construction services (PKWiU section 41-43) are listed in Annex 15 and need split payment."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_polish(context) or _intent(context) == "cancel":
            return [self._ok()]
        lines = _ksef_fields(context).get("lines")
        if not isinstance(lines, list):
            return [self._ok()]
        found = [
            self._fail(
                f"Line {index + 1} has PKWiU {_text(line.get('pkwiu'))}, a construction code, and is not marked "
                "Annex 15. Many construction services are listed there; check the line.",
                element_ref=_document_id(context),
                suggestion="Mark the line annex_15 if its PKWiU is on the Annex 15 list.",
                details={"line": index + 1, "pkwiu": _text(line.get("pkwiu"))},
            )
            for index, line in enumerate(lines)
            if isinstance(line, dict)
            and split_payment.looks_like_construction(_text(line.get("pkwiu")))
            and not bool(line.get("annex_15"))
        ]
        return found or [self._ok()]


# ── Finance rule ─────────────────────────────────────────────────────────────


class KsefNumberInPaymentTitle(_KsefRule):
    rule_id = "finance.pl_ksef_number_in_payment_title"
    name = "Payment Title Carries The KSeF Number"
    # The rule's ceiling. Each result carries the severity of its payment date.
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "From 2027-01-01 a transfer paying a KSeF invoice between VAT payers quotes its KSeF number."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _root(context)
        if _text(record.get("record_type")) != RECORD_PAYMENT or _text(record.get("country")).upper() != COUNTRY:
            return [self._ok()]
        payment_day = _as_date(record.get("payment_date"))
        if payment_day is None:
            return [self._ok()]
        finding = payment_title_finding(
            payment_date=payment_day,
            title=_text(record.get("reference")),
            invoice_ksef_number=_text(record.get("ksef_number")),
            between_vat_payers=bool(record.get("between_vat_payers", True)),
        )
        if finding.passed:
            return [self._ok(finding.message)]
        return [
            self._fail(
                finding.message,
                element_ref=_text(record.get("id")) or None,
                suggestion=f"Use a title that starts with {_text(record.get('ksef_number'))}.",
                details={"ksef_number": _text(record.get("ksef_number")), "payment_date": payment_day.isoformat()},
                severity=Severity.ERROR if finding.severity == SEVERITY_ERROR else Severity.WARNING,
            )
        ]


_DOCUMENT_RULES: tuple[ValidationRule, ...] = (
    KsefStructure(),
    KsefSplitPayment(),
    KsefSplitPaymentUnchecked(),
    KsefRegistrationReady(),
    KsefNumberFormat(),
    KsefOfflineDeadline(),
    KsefAnnex15Hint(),
    KsefNipValid(),
    KsefNipUnchecked(),
)
_FINANCE_RULES: tuple[ValidationRule, ...] = (KsefNumberInPaymentTitle(),)


def register_ksef_rules() -> None:
    """Register the rules. Idempotent: the registry overwrites by id."""
    for rule in _DOCUMENT_RULES:
        rule_registry.register(rule, [EINVOICE_CLEARANCE_RULE_SET])
    for rule in _FINANCE_RULES:
        rule_registry.register(rule, [FINANCE_RULE_SET])
    logger.debug("Registered %d KSeF rules", len(_DOCUMENT_RULES) + len(_FINANCE_RULES))


async def evaluate_payment(record: dict[str, Any], *, record_id: str = "") -> list[RuleResult]:
    """Run the payment title rule over one payment and return the failures.

    ``record`` carries ``payment_date``, ``reference`` (the title), ``country``
    and the paid invoice's ``ksef_number`` (see
    :func:`payments.ksef_number_for_invoice`). Finance does not call this on
    its own yet; see the gap in ``docs/design/poland/ksef.md``.
    """
    try:
        report = await validation_engine.validate(
            data={**record, "record_type": RECORD_PAYMENT},
            rule_sets=[FINANCE_RULE_SET],
            target_type=RECORD_PAYMENT,
            target_id=record_id,
        )
    except Exception:  # noqa: BLE001 - validation augments; it never breaks the caller
        logger.warning("KSeF payment validation failed for record %s", record_id, exc_info=True)
        return []
    return [result for result in report.results if not result.passed and not result.is_engine_error]


__all__ = [
    "FINANCE_RULE_SET",
    "KSEF_FORMATS",
    "RECORD_PAYMENT",
    "KsefAnnex15Hint",
    "KsefNipUnchecked",
    "KsefNipValid",
    "KsefNumberFormat",
    "KsefNumberInPaymentTitle",
    "KsefOfflineDeadline",
    "KsefRegistrationReady",
    "KsefSplitPayment",
    "KsefSplitPaymentUnchecked",
    "KsefStructure",
    "evaluate_payment",
    "nip_verdict",
    "register_ksef_rules",
]
