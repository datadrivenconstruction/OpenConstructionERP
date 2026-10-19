# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ZATCA rules, registered into the ``einvoice_clearance`` rule set.

That set's ERROR rules are the gate the clearance service runs before it calls
an adapter, so a document ZATCA would refuse never leaves. Every rule passes
without reading anything on a document that is not a ZATCA one, because the gate
runs every rule of the set on every country.

The checks themselves live in :mod:`checks` and are shared; each rule here is one
group of them, so a finding names the rule that failed:

* ``zatca_document_readable``  ERROR. One UBL Invoice in the KSA namespaces.
* ``zatca_header``             ERROR. Profile, UUID, dates, type code, KSA-2 flags, ICV, PIH.
* ``zatca_parties``            ERROR. Seller VAT number and address, buyer where required.
* ``zatca_lines_totals``       ERROR. VAT categories, line and document equations.
* ``zatca_stamp``              ERROR. Hash, signature, certificate digests and QR agree with the document.
* ``zatca_construction_vat``   ERROR. The contracting guideline's treatment of retention, advances, damages.
* ``zatca_advisory``           WARNING. What ZATCA accepts with a warning.
* ``zatca_reporting_deadline`` WARNING. A simplified invoice not reported within 24 hours of issue.
* ``zatca_profile``            ERROR. The registration's VAT number is a Saudi VAT number.

Rules stay pure, as the rule set requires: whether the registration has an EGS
unit that can stamp is decided where the document is built (the unit row is
locked there) and where it is sent (the adapter), not here.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.einvoice_clearance.validators import EINVOICE_CLEARANCE_RULE_SET
from app.modules.einvoice_zatca import checks, data
from app.modules.einvoice_zatca.adapter import ZATCA_ADAPTER_KEY

logger = logging.getLogger(__name__)

COUNTRY = "SA"
ZATCA_FORMAT = "zatca_phase2"


def _root(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _section(context: ValidationContext, key: str) -> dict[str, Any]:
    value = _root(context).get(key)
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _intent(context: ValidationContext) -> str:
    return _text(_root(context).get("intent")).lower() or "save"


def _is_saudi(context: ValidationContext) -> bool:
    regime = _section(context, "regime")
    document = _section(context, "document")
    payload = _section(context, "payload")
    if COUNTRY in (_text(regime.get("country")).upper(), _text(document.get("country")).upper()):
        return True
    return _text(payload.get("format")) == ZATCA_FORMAT


def _zatca_fields(context: ValidationContext) -> dict[str, Any]:
    fields = _section(context, "document").get("country_fields")
    value = fields.get("zatca") if isinstance(fields, dict) else None
    return value if isinstance(value, dict) else {}


def _reference_time(context: ValidationContext) -> dt.datetime:
    raw = _root(context).get("reference_time")
    if isinstance(raw, dt.datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=dt.UTC)
    if raw:
        try:
            parsed = dt.datetime.fromisoformat(_text(raw).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
        except ValueError:
            pass
    return dt.datetime.now(dt.UTC)


@functools.lru_cache(maxsize=16)
def _issues(text: str, vat: str, reference: str, fields_json: str) -> tuple[checks.ZatcaIssue, ...]:
    """All findings about one document, parsed once for the nine rules that read it."""
    return tuple(
        checks.check_document(
            text,
            profile_vat=vat,
            now=dt.datetime.fromisoformat(reference),
            zatca_fields=json.loads(fields_json),
        )
    )


def _document_issues(context: ValidationContext) -> tuple[checks.ZatcaIssue, ...]:
    payload = _section(context, "payload")
    if _text(payload.get("format")) not in ("", ZATCA_FORMAT):
        return ()
    text = _text(payload.get("text"))
    if not text:
        return ()
    return _issues(
        text,
        _text(_section(context, "profile").get("tax_registration_id")),
        _reference_time(context).isoformat(),
        json.dumps(_zatca_fields(context), sort_keys=True, default=str),
    )


class _ZatcaRule(ValidationRule):
    standard = "ZATCA"

    def _ok(self) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message="OK",
        )

    def _fail(
        self,
        message: str,
        *,
        element_ref: str | None = None,
        suggestion: str | None = None,
        severity: Severity | None = None,
        details: dict[str, Any] | None = None,
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


class _GroupRule(_ZatcaRule):
    """One group of the shared checks."""

    groups: tuple[str, ...] = ()
    suggestion = "Rebuild the document from the invoice, or correct the invoice and the registration it reads."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_saudi(context) or _intent(context) == "cancel":
            return [self._ok()]
        found = [i for i in _document_issues(context) if i.group in self.groups]
        if not found:
            return [self._ok()]
        document_id = _text(_section(context, "document").get("id")) or None
        results = []
        for issue in found:
            severity = Severity.ERROR if issue.severity == checks.SEVERITY_ERROR else Severity.WARNING
            results.append(
                self._fail(
                    f"{issue.code}: {issue.message}",
                    element_ref=document_id,
                    suggestion=self.suggestion,
                    severity=severity,
                    details={"code": issue.code, "path": issue.path, "group": issue.group},
                )
            )
        return results


class ZatcaDocumentReadable(_GroupRule):
    rule_id = "einvoice_clearance.zatca_document_readable"
    name = "ZATCA Document Is One Readable UBL Invoice"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "The payload is a UBL 2.1 Invoice in the namespaces the KSA profile uses."
    groups = (checks.GROUP_READABLE,)


class ZatcaHeader(_GroupRule):
    rule_id = "einvoice_clearance.zatca_header"
    name = "ZATCA Document Header Is Complete"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Profile, UUID, dates, type code, the seven KSA-2 subtype flags, the counter and the previous hash."
    groups = (checks.GROUP_HEADER,)


class ZatcaParties(_GroupRule):
    rule_id = "einvoice_clearance.zatca_parties"
    name = "ZATCA Parties Carry What ZATCA Requires"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The seller's VAT number and address, and the buyer's on a standard invoice."
    groups = (checks.GROUP_PARTIES,)


class ZatcaLinesTotals(_GroupRule):
    rule_id = "einvoice_clearance.zatca_lines_totals"
    name = "ZATCA Lines And Totals Add Up"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "VAT categories and exemption codes, the line and document equations at two decimals."
    groups = (checks.GROUP_LINES,)


class ZatcaStamp(_GroupRule):
    rule_id = "einvoice_clearance.zatca_stamp"
    name = "ZATCA Cryptographic Stamp Verifies"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "The recomputed hash, the signature, the certificate digests and the QR agree with the document."
    groups = (checks.GROUP_STAMP,)


class ZatcaConstructionVat(_GroupRule):
    rule_id = "einvoice_clearance.zatca_construction_vat"
    name = "Construction VAT Treatment Follows The Contracting Guideline"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "Retention, advances, liquidated damages and government claims, read from the document's ZATCA fields."
    )
    groups = (checks.GROUP_CONSTRUCTION,)


class ZatcaAdvisory(_GroupRule):
    rule_id = "einvoice_clearance.zatca_advisory"
    name = "ZATCA Accepts These With A Warning"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Findings ZATCA's validator reports as warnings; the document is still accepted."
    groups = (checks.GROUP_ADVISORY,)


class ZatcaReportingDeadline(_ZatcaRule):
    rule_id = "einvoice_clearance.zatca_reporting_deadline"
    name = "Simplified Invoice Is Reported Within 24 Hours"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A simplified tax invoice is reported to ZATCA within 24 hours of its issue time."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_saudi(context) or _intent(context) != "submit":
            return [self._ok()]
        text = _text(_section(context, "payload").get("text"))
        if not text:
            return [self._ok()]
        try:
            _, subtype_code = checks.read_identity(text)
        except Exception:  # noqa: BLE001 - unreadable documents are the readable rule's finding
            return [self._ok()]
        from app.modules.einvoice_zatca.codes import parse_subtype

        subtype = parse_subtype(subtype_code)
        issued = checks.issue_moment(text)
        if subtype is None or not subtype.simplified or issued is None:
            return [self._ok()]
        late_by = _reference_time(context) - issued - data.REPORTING_DEADLINE
        if late_by <= dt.timedelta(0):
            return [self._ok()]
        hours = int(late_by.total_seconds() // 3600)
        return [
            self._fail(
                f"This simplified invoice was issued at {issued.isoformat(timespec='seconds')} and is more than "
                f"{hours} hour(s) past the 24-hour reporting limit.",
                element_ref=_text(_section(context, "document").get("id")) or None,
                suggestion="Report it now; late reporting is a penalty matter, not an invalid invoice.",
                details={"issued_at": issued.isoformat(), "limit_hours": 24},
            )
        ]


class ZatcaProfile(_ZatcaRule):
    rule_id = "einvoice_clearance.zatca_profile"
    name = "Saudi Registration Carries A VAT Number"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The registration's tax registration id is a 15-digit VAT number starting and ending with 3."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        profile = _section(context, "profile")
        if _text(profile.get("adapter_key")) != ZATCA_ADAPTER_KEY or _intent(context) == "cancel":
            return [self._ok()]
        vat = _text(profile.get("tax_registration_id"))
        if checks.is_vat_number(vat):
            return [self._ok()]
        return [
            self._fail(
                f"The registration's tax registration id {vat!r} is not a Saudi VAT number: ZATCA needs 15 digits "
                "starting and ending with 3.",
                element_ref=_text(profile.get("id")) or None,
                suggestion="Enter the VAT registration number from the taxpayer's ZATCA certificate.",
            )
        ]


_RULES: tuple[ValidationRule, ...] = (
    ZatcaDocumentReadable(),
    ZatcaHeader(),
    ZatcaParties(),
    ZatcaLinesTotals(),
    ZatcaStamp(),
    ZatcaConstructionVat(),
    ZatcaAdvisory(),
    ZatcaReportingDeadline(),
    ZatcaProfile(),
)


def register_zatca_rules() -> None:
    """Register the rules. Idempotent: the registry overwrites by id."""
    for rule in _RULES:
        rule_registry.register(rule, [EINVOICE_CLEARANCE_RULE_SET])
    logger.debug("Registered %d ZATCA rules", len(_RULES))


__all__ = [
    "ZATCA_FORMAT",
    "ZatcaAdvisory",
    "ZatcaConstructionVat",
    "ZatcaDocumentReadable",
    "ZatcaHeader",
    "ZatcaLinesTotals",
    "ZatcaParties",
    "ZatcaProfile",
    "ZatcaReportingDeadline",
    "ZatcaStamp",
    "register_zatca_rules",
]
