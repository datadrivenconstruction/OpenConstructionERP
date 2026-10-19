# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ETA pre-submit rules, registered into the ``einvoice_clearance`` rule set.

Registering into that set, rather than a set of their own, is what makes them
a gate: the clearance service runs every ERROR rule of the set before it hands
a document to an adapter, so an ETA document with a wrong total never reaches
ETA. On saving, the same rules come back as findings, so the operator sees what
ETA would say while the document is still a draft.

Each rule reports one finding per problem, with the JSON path of the member
concerned, because "the totals are wrong" is not something anyone can fix and
"invoiceLines[1].T1.amount is 140.00 but T1 rate x (...) gives 140.70" is.

Every rule applies only to documents in the ETA format; on any other country's
document it passes without reading anything.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
from app.modules.einvoice_eta.adapter import ETA_ADAPTER_KEY, settings_problems
from app.modules.einvoice_eta.checks import (
    GROUP_ADVISORY,
    GROUP_HEADER,
    GROUP_LINES,
    GROUP_PARTIES,
    GROUP_READABLE,
    GROUP_TOTALS,
    EtaIssue,
    check_eta_document,
)

logger = logging.getLogger(__name__)

ETA_DOCUMENT_FORMAT = "eta_json_1_0"


def _root(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _section(context: ValidationContext, key: str) -> dict[str, Any]:
    value = _root(context).get(key)
    return value if isinstance(value, dict) else {}


def _is_eta(context: ValidationContext) -> bool:
    regime = _section(context, "regime")
    payload = _section(context, "payload")
    return ETA_DOCUMENT_FORMAT in (str(regime.get("document_format") or ""), str(payload.get("format") or ""))


def _intent(context: ValidationContext) -> str:
    return str(_root(context).get("intent") or "save").strip().lower()


def _reference_time(context: ValidationContext) -> datetime:
    value = _root(context).get("reference_time")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


class _EtaGroupRule(ValidationRule):
    """One group of :func:`check_eta_document` findings, reported one by one."""

    group: str = ""
    standard = "ETA"
    suggestion = ""

    def _ok(self, message: str = "OK") -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message=message,
        )

    def _issue(self, issue: EtaIssue, document_id: str) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=issue.message,
            element_ref=document_id or None,
            suggestion=self.suggestion or None,
            details={"code": issue.code, "path": issue.path, "group": issue.group},
        )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is_eta(context) or _intent(context) == "cancel":
            return [self._ok()]
        text = str(_section(context, "payload").get("text") or "")
        profile = _section(context, "profile")
        document_id = str(_section(context, "document").get("id") or "")
        issues = [
            issue
            for issue in check_eta_document(
                text,
                profile_rin=str(profile.get("tax_registration_id") or ""),
                now=_reference_time(context),
            )
            if issue.group == self.group
        ]
        if not issues:
            return [self._ok()]
        return [self._issue(issue, document_id) for issue in issues]


class EtaDocumentReadable(_EtaGroupRule):
    rule_id = "einvoice_clearance.eta_document_readable"
    name = "ETA Document Is One JSON Object"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "ETA accepts a JSON document object; anything else is refused before it is read."
    group = GROUP_READABLE
    suggestion = "Rebuild the document from the invoice, or paste the ETA JSON document itself."


class EtaParties(_EtaGroupRule):
    rule_id = "einvoice_clearance.eta_parties"
    name = "ETA Issuer And Receiver Complete"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Issuer RIN, branch and address; receiver type, id and address as ETA requires them."
    group = GROUP_PARTIES
    suggestion = (
        "The issuer comes from the registration settings (settings.eta.issuer) and its RIN; the receiver from the "
        "invoice contact or the document's ETA fields."
    )


class EtaHeader(_EtaGroupRule):
    rule_id = "einvoice_clearance.eta_header"
    name = "ETA Document Header Valid"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Document type and version, issue time in UTC and not in the future, activity code, internal id."
    group = GROUP_HEADER
    suggestion = "Set the activity code once on the registration (settings.eta.activity_code), for example 4100."


class EtaLines(_EtaGroupRule):
    rule_id = "einvoice_clearance.eta_lines"
    name = "ETA Invoice Lines Valid"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Item code type GS1 or EGS, ETA unit codes, quantities, currency, tax types and subtypes."
    group = GROUP_LINES
    suggestion = (
        "Register EGS codes for your services with ETA and set the default item code on the registration "
        "(settings.eta.default_item), or per line in the document's ETA fields."
    )


class EtaTotals(_EtaGroupRule):
    rule_id = "einvoice_clearance.eta_totals"
    name = "ETA Line And Document Totals Add Up"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The line and document equations ETA's validator checks, at the precision the document uses."
    group = GROUP_TOTALS
    suggestion = "Let the platform build the document from the invoice; it computes every figure the way ETA does."


class EtaAdvisory(_EtaGroupRule):
    rule_id = "einvoice_clearance.eta_advisory"
    name = "ETA Points To Check"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Things ETA may refuse on facts it does not publish, and text that signs ambiguously."
    group = GROUP_ADVISORY


class EtaProfileReady(ValidationRule):
    rule_id = "einvoice_clearance.eta_profile"
    name = "ETA Registration Ready To Submit"
    standard = "ETA"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Environment, base URLs, credential variables and signer for a registration on the ETA adapter."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        profile = _section(context, "profile")
        applies = str(profile.get("adapter_key") or "") == ETA_ADAPTER_KEY and _intent(context) in ("submit", "cancel")
        problems = settings_problems(profile) if applies else []
        if not problems:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message="The ETA registration is not ready: " + "; ".join(problems) + ".",
                element_ref=str(profile.get("id") or "") or None,
                suggestion=(
                    "Complete settings.eta on the registration. Credentials are never stored: name the environment "
                    "variables that hold them."
                ),
                details={"problems": problems},
            )
        ]


ETA_RULES: tuple[ValidationRule, ...] = (
    EtaDocumentReadable(),
    EtaParties(),
    EtaHeader(),
    EtaLines(),
    EtaTotals(),
    EtaAdvisory(),
    EtaProfileReady(),
)


def register_eta_rules() -> None:
    """Register the ETA rules into the clearance rule set. Idempotent."""
    for rule in ETA_RULES:
        rule_registry.register(rule, [EINVOICE_CLEARANCE_RULE_SET])
    logger.debug("Registered %d ETA e-invoice rules", len(ETA_RULES))


__all__ = [
    "ETA_DOCUMENT_FORMAT",
    "ETA_RULES",
    "EtaAdvisory",
    "EtaDocumentReadable",
    "EtaHeader",
    "EtaLines",
    "EtaParties",
    "EtaProfileReady",
    "EtaTotals",
    "register_eta_rules",
]
