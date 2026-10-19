# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice clearance validation rules.

These are not schema checks. A document that satisfies every Pydantic
constraint can still be the one that gets a company fined: a Mexican CFDI with
no Uso CFDI, a live registration pointed at a test endpoint, a cancellation
attempted eleven months after clearance, the same payload sent twice because
somebody clicked twice on a slow morning. None of that is expressible in a type.

Rules, all registered under the ``einvoice_clearance`` rule set:

* ``einvoice_clearance.profile_complete``    - ERROR.   The registration is
      missing something the declared country needs, named.
* ``einvoice_clearance.mandatory_fields``    - ERROR.   The document is missing
      a field the regime requires, named.
* ``einvoice_clearance.settled_immutable``   - ERROR.   A document the platform
      has answered for may not be edited or sent again.
* ``einvoice_clearance.cancellation_allowed``- ERROR.   A cancellation needs a
      reason and has to fall inside the country's window.
* ``einvoice_clearance.payload_not_reused``  - ERROR.   The same payload may not
      be submitted twice.
* ``einvoice_clearance.identifier_present``  - ERROR.   A cleared document under
      a clearance regime has to carry the identifier that makes it valid.
* ``einvoice_clearance.sandbox_profile``     - WARNING. A sandbox registration
      is in use on a real invoice.

The context
===========
Every rule reads one dict, assembled by the service:

    {"intent": "save" | "submit" | "cancel",
     "profile": {...},   "document": {...},   "regime": {...},
     "duplicate": {...} | None,
     "invoice_is_real": bool,
     "reference_time": ISO-8601 string}

Rules stay pure - no session, no I/O - so the same rule answers identically from
the router, from a background retry and from a test. Anything that needs the
database (the duplicate lookup) is resolved into the context before the engine
runs, which is the shape ``authority_submission`` already uses.
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
    validation_engine,
)
from app.modules.einvoice_clearance.mentions import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    check_mentions,
    facts_from_context,
)
from app.modules.einvoice_clearance.models import SETTLED_STATUSES
from app.modules.einvoice_clearance.regimes import CANCELLATION_BASIS_AUTHORITY, REGIME_CLEARANCE

logger = logging.getLogger(__name__)

EINVOICE_CLEARANCE_RULE_SET = "einvoice_clearance"

INTENT_SAVE = "save"
INTENT_SUBMIT = "submit"
INTENT_CANCEL = "cancel"


# ── Context readers ──────────────────────────────────────────────────────────


def _root(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    return data if isinstance(data, dict) else {}


def _section(context: ValidationContext, key: str) -> dict[str, Any]:
    value = _root(context).get(key)
    return value if isinstance(value, dict) else {}


def _intent(context: ValidationContext) -> str:
    return str(_root(context).get("intent") or INTENT_SAVE).strip().lower()


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_datetime(value: Any) -> datetime | None:
    """Read a timestamp that may arrive as a datetime or an ISO-8601 string.

    A naive value is read as UTC. Everything this module writes is UTC, and
    treating a naive timestamp as local time would move a cancellation deadline
    by the deployment's offset.
    """
    if isinstance(value, datetime):
        stamp = value
    else:
        raw = _text(value)
        if not raw:
            return None
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


# ── Rules ────────────────────────────────────────────────────────────────────


class ProfileComplete(ValidationRule):
    rule_id = "einvoice_clearance.profile_complete"
    name = "Registration Complete For The Country"
    standard = "einvoice_clearance"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The country's platform will not accept a submission from an incomplete registration."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        profile = _section(context, "profile")
        regime = _section(context, "regime")
        country = _text(regime.get("country")) or _text(profile.get("country"))
        required = [str(name) for name in (regime.get("profile_fields") or [])]
        missing = [name for name in required if not _text(profile.get(name))]

        # An adapter is only needed when something is actually going to the
        # platform. A registration recorded for the books before a provider
        # contract is signed is a legitimate half-finished row.
        if _intent(context) in (INTENT_SUBMIT, INTENT_CANCEL) and not _text(profile.get("adapter_key")):
            missing.append("adapter_key")
        if not profile:
            missing.append("profile")

        if not missing:
            return [_result(self, True, "OK", details={"country": country})]
        return [
            _result(
                self,
                False,
                f"The {country or 'country'} registration is missing: {', '.join(missing)}.",
                element_ref=_text(profile.get("id")) or None,
                suggestion=(
                    f"Complete the registration for {country or 'this country'} before submitting. "
                    "The platform rejects on the identity of the issuer before it looks at the invoice."
                ),
                details={"country": country, "missing": missing, "required": required},
            )
        ]


class MandatoryFieldsPresent(ValidationRule):
    rule_id = "einvoice_clearance.mandatory_fields"
    name = "Mandatory Fields Present For The Regime"
    standard = "einvoice_clearance"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Each country demands fields the shared invoice model has no place for."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        document = _section(context, "document")
        regime = _section(context, "regime")
        country = _text(regime.get("country"))
        required = [str(name) for name in (regime.get("document_fields") or [])]
        carried = document.get("country_fields")
        carried = carried if isinstance(carried, dict) else {}
        missing = [name for name in required if not _text(carried.get(name))]

        if not missing:
            return [_result(self, True, "OK", details={"country": country, "required": required})]
        return [
            _result(
                self,
                False,
                f"{country or 'This country'} requires {', '.join(missing)} and the document does not carry it.",
                element_ref=_text(document.get("id")) or None,
                suggestion=(
                    "Fill the country fields on the document. These are national fields with no equivalent "
                    "in the shared invoice model, so nothing upstream can supply them."
                ),
                details={"country": country, "missing": missing, "required": required},
            )
        ]


class SettledDocumentImmutable(ValidationRule):
    rule_id = "einvoice_clearance.settled_immutable"
    name = "A Settled Document May Not Be Changed"
    standard = "einvoice_clearance"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Once the platform has answered, the document is a record of what it answered about."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        intent = _intent(context)
        if intent not in (INTENT_SAVE, INTENT_SUBMIT):
            return [_result(self, True, "OK")]

        document = _section(context, "document")
        status = _text(document.get("status"))
        if status not in SETTLED_STATUSES:
            return [_result(self, True, "OK", details={"status": status})]

        regime = _section(context, "regime")
        changed = [str(name) for name in (_root(context).get("changed_fields") or [])]
        correction = _text(regime.get("correction_mechanism")) or "a correcting document"
        what = "sent again" if intent == INTENT_SUBMIT else "changed"
        detail = f" Changed: {', '.join(changed)}." if changed else ""
        return [
            _result(
                self,
                False,
                (
                    f"This document is {status} and cannot be {what}. The authority holds a copy of exactly "
                    f"what was sent.{detail}"
                ),
                element_ref=_text(document.get("id")) or None,
                suggestion=f"Correct it the way the country allows: {correction}.",
                details={"status": status, "changed_fields": changed, "correction_mechanism": correction},
            )
        ]


class CancellationAllowed(ValidationRule):
    rule_id = "einvoice_clearance.cancellation_allowed"
    name = "Cancellation Is Reasoned And In Window"
    standard = "einvoice_clearance"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A cancellation needs a stated reason and has to fall inside the country's window."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _intent(context) != INTENT_CANCEL:
            return [_result(self, True, "OK")]

        document = _section(context, "document")
        regime = _section(context, "regime")
        country = _text(regime.get("country"))
        window = regime.get("cancellation_window_days")
        reason = _text(document.get("cancellation_reason"))
        problems: list[str] = []
        details: dict[str, Any] = {"country": country, "cancellation_window_days": window}

        if not reason:
            problems.append("no reason was given")

        if window is None and _text(regime.get("cancellation_basis")) == CANCELLATION_BASIS_AUTHORITY:
            # The platform publishes the window itself and refuses a late
            # request with its own code; the adapter reads it when it cancels.
            # Guessing a day count here would refuse cancellations the
            # authority still allows, or let through ones it does not.
            details["cancellation_basis"] = CANCELLATION_BASIS_AUTHORITY
        elif window is None:
            correction = _text(regime.get("correction_mechanism")) or "a correcting document"
            problems.append(f"{country or 'this country'} has no cancellation flow (correct with {correction})")
            details["correction_mechanism"] = correction
        else:
            cleared_at = _as_datetime(document.get("cleared_at")) or _as_datetime(document.get("submitted_at"))
            now = _as_datetime(_root(context).get("reference_time")) or datetime.now(UTC)
            if cleared_at is None:
                problems.append("the document has no clearance date to measure the window from")
            else:
                elapsed_days = (now - cleared_at).total_seconds() / 86400.0
                details["elapsed_days"] = round(elapsed_days, 3)
                if elapsed_days > float(window):
                    problems.append(f"the window closed after {window} day(s) and {elapsed_days:.1f} have passed")

        if not problems:
            return [_result(self, True, "OK", details=details)]
        details["problems"] = problems
        return [
            _result(
                self,
                False,
                f"This document cannot be cancelled: {'; '.join(problems)}.",
                element_ref=_text(document.get("id")) or None,
                suggestion=(
                    "State why the invoice is being withdrawn, and check the country's window. Outside it the "
                    "only route is a correcting document, which is a different entry in the ledger."
                ),
                details=details,
            )
        ]


class PayloadNotReused(ValidationRule):
    rule_id = "einvoice_clearance.payload_not_reused"
    name = "The Same Payload May Not Go Twice"
    standard = "einvoice_clearance"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A platform that accepts the same document twice has issued two invoices for one sale."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _intent(context) != INTENT_SUBMIT:
            return [_result(self, True, "OK")]

        duplicate = _section(context, "duplicate")
        if not duplicate:
            return [_result(self, True, "OK")]

        document = _section(context, "document")
        identifier = _text(duplicate.get("authority_identifier"))
        known_as = f" It came back as {identifier}." if identifier else ""
        return [
            _result(
                self,
                False,
                (
                    "This exact payload has already been submitted under this registration"
                    f" ({_text(duplicate.get('status')) or 'unknown status'})."
                    f"{known_as}"
                ),
                element_ref=_text(document.get("id")) or None,
                suggestion=(
                    "Open the earlier document instead of sending this one. If the invoice genuinely changed, "
                    "the payload would have changed with it."
                ),
                details={
                    "payload_hash": _text(document.get("payload_hash")),
                    "duplicate_document_id": _text(duplicate.get("id")),
                    "duplicate_status": _text(duplicate.get("status")),
                    "duplicate_authority_identifier": identifier,
                },
            )
        ]


class IdentifierPresent(ValidationRule):
    rule_id = "einvoice_clearance.identifier_present"
    name = "A Cleared Document Carries Its Identifier"
    standard = "einvoice_clearance"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Under a clearance regime the identifier is what makes the invoice legally valid."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        document = _section(context, "document")
        regime = _section(context, "regime")
        # Only clearance. Under reporting the invoice was valid before the
        # acknowledgement, and on a network there is no authority to identify
        # anything, so a missing reference there is untidy rather than invalid.
        if _text(regime.get("regime")) != REGIME_CLEARANCE:
            return [_result(self, True, "OK")]
        if _text(document.get("status")) != "cleared":
            return [_result(self, True, "OK")]
        if _text(document.get("authority_identifier")):
            return [_result(self, True, "OK")]

        label = _text(regime.get("identifier_label")) or "the authority identifier"
        return [
            _result(
                self,
                False,
                f"This document is marked cleared but carries no {label}, so nothing proves it was cleared.",
                element_ref=_text(document.get("id")) or None,
                suggestion=f"Re-read the platform response and store the {label}, or put the document back to draft.",
                details={"country": _text(regime.get("country")), "identifier_label": label},
            )
        ]


class SandboxProfileInUse(ValidationRule):
    rule_id = "einvoice_clearance.sandbox_profile"
    name = "Sandbox Registration On A Real Invoice"
    standard = "einvoice_clearance"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A sandbox registration produces identifiers no authority has ever seen."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        profile = _section(context, "profile")
        if not bool(profile.get("sandbox", False)):
            return [_result(self, True, "OK")]
        if not bool(_root(context).get("invoice_is_real", False)):
            return [_result(self, True, "OK")]

        country = _text(_section(context, "regime").get("country")) or _text(profile.get("country"))
        return [
            _result(
                self,
                False,
                (
                    f"The {country or 'country'} registration is in sandbox mode and this is a real invoice, "
                    "so whatever comes back will look like an identifier and will not be one."
                ),
                element_ref=_text(profile.get("id")) or None,
                suggestion="Switch the registration to live once the provider has confirmed the production account.",
                details={"country": country, "sandbox": True},
            )
        ]


def _mention_results(rule: ValidationRule, context: ValidationContext, severity: str) -> list[RuleResult]:
    """Findings of the country mentions catalogue at one severity. Country-neutral."""
    document = _section(context, "document")
    profile = _section(context, "profile")
    regime = _section(context, "regime")
    country = _text(regime.get("country")) or _text(profile.get("country"))
    facts = facts_from_context(document, profile)
    findings = check_mentions(
        country=country,
        document_kind=_text(document.get("document_kind")) or "invoice",
        issue_date=document.get("invoice_date"),
        facts=facts,
        company_size=_text(facts["settings"].get("company_size")) or None,
    )
    chosen = [f for f in findings if f.severity == severity]
    if not chosen:
        return [_result(rule, True, "OK")]
    return [
        _result(
            rule,
            False,
            f.message,
            element_ref=_text(document.get("id")) or None,
            suggestion=f"Fill: {', '.join(f.missing)}. Source: {f.source_url}",
            details={
                "country": f.country,
                "key": f.key,
                "missing": list(f.missing),
                "effective_date": f.effective_date,
                "size_assumed": f.size_assumed,
                "needs_expert_review": f.needs_expert_review,
                "params": f.params,
            },
        )
        for f in chosen
    ]


class InvoiceMentionsRequired(ValidationRule):
    rule_id = "einvoice_clearance.invoice_mentions"
    name = "Mandatory Invoice Mentions For The Country"
    standard = "einvoice_clearance"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Mentions the country's catalogue confirms as mandatory on the issue date."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return _mention_results(self, context, SEVERITY_ERROR)


class InvoiceMentionsUnconfirmed(ValidationRule):
    rule_id = "einvoice_clearance.invoice_mentions_unconfirmed"
    name = "Invoice Mentions Awaiting Expert Confirmation"
    standard = "einvoice_clearance"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Mentions the catalogue lists but a local expert has not yet confirmed. Never blocks."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return _mention_results(self, context, SEVERITY_WARNING)


_EINVOICE_CLEARANCE_RULES: tuple[ValidationRule, ...] = (
    ProfileComplete(),
    MandatoryFieldsPresent(),
    SettledDocumentImmutable(),
    CancellationAllowed(),
    PayloadNotReused(),
    IdentifierPresent(),
    SandboxProfileInUse(),
    InvoiceMentionsRequired(),
    InvoiceMentionsUnconfirmed(),
)


def register_einvoice_clearance_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook.
    """
    for rule in _EINVOICE_CLEARANCE_RULES:
        rule_registry.register(rule, [EINVOICE_CLEARANCE_RULE_SET])
    logger.debug("Registered %d e-invoice clearance validation rules", len(_EINVOICE_CLEARANCE_RULES))


async def evaluate(payload: dict[str, Any], *, document_id: str = "") -> list[RuleResult]:
    """Run the clearance rules and return every finding, passing ones dropped.

    Guarded the way the cases module guards its own: a broken rule must not stop
    somebody recording the state of an invoice, so a failure degrades to "no
    findings" and a log line.

    That guard is why :func:`blocking_findings` alone is not the gate on the
    consequential actions. The service checks the hard preconditions itself
    before it calls an adapter, so a silenced engine cannot become a way to
    submit an incomplete document.
    """
    try:
        report = await validation_engine.validate(
            data=payload,
            rule_sets=[EINVOICE_CLEARANCE_RULE_SET],
            target_type="einvoice_document",
            target_id=document_id,
            metadata={"intent": payload.get("intent", INTENT_SAVE)},
        )
    except Exception:  # noqa: BLE001 - validation augments the action; never break it
        logger.warning("e-invoice clearance validation failed for document %s", document_id, exc_info=True)
        return []
    return [result for result in report.results if not result.passed and not result.is_engine_error]


async def hard_blockers(payload: dict[str, Any]) -> list[RuleResult]:
    """Run the ERROR rules directly, with no engine and no guard.

    This is the gate on the consequential actions, and it exists because
    :func:`evaluate` is guarded: a rule that raises degrades to "no findings"
    there, which is right when the caller is saving a draft and catastrophic
    when the caller is about to put a document to a tax authority. A silenced
    engine must not become a way to submit an incomplete document.

    It runs the same rule *objects* as :func:`evaluate` rather than a second
    copy of the checks. A rule written once per caller gets tested at the caller
    that happened to be right.
    """
    context = ValidationContext(data=payload)
    found: list[RuleResult] = []
    for rule in _gate_rules():
        if rule.severity != Severity.ERROR:
            continue
        found.extend(result for result in await rule.validate(context) if not result.passed)
    return found


def _gate_rules() -> list[ValidationRule]:
    """The module's own rules plus every rule a plugin registered into the set.

    A country adapter package registers its
    document rules into this rule set. If the hard gate ran only the module's
    own tuple, those rules would show up as findings and still let the document
    go, which is the one outcome the gate exists to prevent.
    """
    rules: list[ValidationRule] = list(_EINVOICE_CLEARANCE_RULES)
    seen = {rule.rule_id for rule in rules}
    registered = rule_registry.get_rules_for_sets([EINVOICE_CLEARANCE_RULE_SET])
    for rule in sorted(registered, key=lambda r: r.rule_id):
        if rule.rule_id not in seen:
            seen.add(rule.rule_id)
            rules.append(rule)
    return rules


def blocking_findings(results: list[RuleResult]) -> list[RuleResult]:
    """The subset that must be cleared before the document may go anywhere."""
    return [result for result in results if result.severity == Severity.ERROR]


__all__ = [
    "EINVOICE_CLEARANCE_RULE_SET",
    "INTENT_CANCEL",
    "INTENT_SAVE",
    "INTENT_SUBMIT",
    "blocking_findings",
    "evaluate",
    "hard_blockers",
    "register_einvoice_clearance_rules",
]
