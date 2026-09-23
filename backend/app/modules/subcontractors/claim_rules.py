# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The subcontract half of the ``pay_application`` rule set.

The contracts module owns the rule set that checks one GC progress claim as
the payment application it becomes, and runs it when the claim is submitted
(errors block) and on the claim's validation route. It never imports this
module: :func:`register_sub_rollup_context` hands it
:func:`app.modules.subcontractors.rollup.claim_rule_context` through the
provider registry in ``contracts.claim_context``, and contracts places the
answer under ``context.data["subcontract_rollup"]``. The rules here read that
entry and nothing else.

The checks themselves are the pure functions at the bottom of
:mod:`app.modules.subcontractors.validators`, which has to stay standard
library only. These classes are the thin layer that turns a
:class:`~app.modules.subcontractors.validators.Finding` into a worded
``RuleResult`` through this module's message bundle, which is why they live in
their own file rather than beside the checks.

An absent or empty rollup is a claim with no subcontract data (a GC that self
performs, or a contract nobody has linked a subcontract to), and every rule
returns no result for it. Two of these rules are errors, and an error blocks
the claim's submission, so "nothing to judge" must never read as a failure.
A rule that did judge and found nothing wrong returns one passing row, so the
dashboard shows "checked, fine" rather than silence; a rule with nothing to
judge on this claim (no prior payments, no period end for the certificates)
returns nothing, because a green row there would claim a check that never ran.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.currency_registry import sentence_amount
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.subcontractors import validators as checks
from app.modules.subcontractors.messages import is_key_present, translate

logger = logging.getLogger(__name__)

#: The set these rules join when the contracts module cannot be imported.
#: Spelled the same as ``contracts.validators.PAY_APPLICATION_RULE_SET``; the
#: import is preferred so a rename there carries over here, and this literal
#: only matters on an install without contracts, where nothing runs the set.
_PAY_APPLICATION_RULE_SET_FALLBACK = "pay_application"

#: Key in the claim's rule context that carries the subcontract rollup.
ROLLUP_KEY = "subcontract_rollup"


def pay_application_rule_set() -> str:
    """The name of the rule set submission runs, asked of the contracts module."""
    try:
        from app.modules.contracts.validators import PAY_APPLICATION_RULE_SET  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        # Only the absence of the contracts module is a normal install; an
        # import error inside it is a defect and must surface.
        if exc.name not in ("app.modules.contracts", "app.modules.contracts.validators"):
            raise
        return _PAY_APPLICATION_RULE_SET_FALLBACK
    return PAY_APPLICATION_RULE_SET


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _rollup(context: ValidationContext) -> dict[str, Any]:
    data = context.data if isinstance(context.data, dict) else {}
    rollup = data.get(ROLLUP_KEY)
    return rollup if isinstance(rollup, dict) else {}


def _rows(rollup: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = rollup.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _token(key_prefix: str, token: str, locale: str) -> str:
    """Word a status or document token, or print it as it is when the bundle has no word for it.

    A token the bundle does not know (a certificate type a newer pack added)
    still has to appear in the message; the raw token is ugly but true, where
    the raw message key the bundle would fall back to is neither.
    """
    key = f"{key_prefix}.{token}"
    return translate(key, locale=locale) if token and is_key_present(key, "en") else token


class _SubRollupRule(ValidationRule):
    """Shared body: run one pure check over the rollup and word its findings.

    Subclasses name the check (:attr:`check_name`) and may override
    :meth:`_judged` (whether the check had anything to look at),
    :meth:`_fail_key`, :meth:`_params` and :meth:`_severity_of`.
    """

    standard = _PAY_APPLICATION_RULE_SET_FALLBACK

    #: Name of the ``subcontractors.validators`` function this rule runs.
    check_name: str = ""

    def _judged(self, rollup: dict[str, Any]) -> bool:
        """Whether this rule had anything to check on this claim."""
        return bool(_rows(rollup, "included"))

    def _fail_key(self, finding: checks.Finding) -> str:
        return f"{self.rule_id}.fail"

    def _params(self, finding: checks.Finding, locale: str) -> dict[str, str]:
        return dict(finding.params)

    def _severity_of(self, finding: checks.Finding) -> Severity:
        return self.severity

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rollup = _rollup(context)
        if not rollup:
            return []
        findings = getattr(checks, self.check_name)(rollup)
        locale = _locale(context)
        if not findings:
            if not self._judged(rollup):
                return []
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate("common.ok", locale=locale),
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self._severity_of(finding),
                category=self.category,
                passed=False,
                message=translate(self._fail_key(finding), locale=locale, **self._params(finding, locale)),
                element_ref=finding.element_ref,
                details=dict(finding.details),
                suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
            )
            for finding in findings
        ]


class SubUnapprovedIncludedRule(_SubRollupRule):
    """An included subcontractor pay application must be approved for payment."""

    rule_id = "pay_application.sub_unapproved_included"
    name = "Included subcontractor pay applications are approved"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a subcontractor pay application billed on the claim that has not been approved for payment"
    check_name = "check_sub_unapproved_included"

    def _params(self, finding: checks.Finding, locale: str) -> dict[str, str]:
        params = dict(finding.params)
        params["status"] = _token(f"{self.rule_id}.statuses", params.get("status", ""), locale)
        return params


class SubWaiverMissingRule(_SubRollupRule):
    """An included pay application needs a lien waiver covering its net for the period.

    An error when the subcontract agreement requires waivers, because the
    module's own payment gate would then refuse to pay the sub and the GC would
    be billing money it cannot release. A warning when only the national pack
    expects one. The check says which per finding; the class severity is the
    stricter of the two so the registry lists the rule as able to block.
    """

    rule_id = "pay_application.sub_waiver_missing"
    name = "Included subcontractor pay applications carry a lien waiver"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Flags an included subcontractor pay application without a lien waiver covering its net amount"
    check_name = "check_sub_waiver_missing"

    def _judged(self, rollup: dict[str, Any]) -> bool:
        included = _rows(rollup, "included")
        if not included:
            return False
        return bool(rollup.get("pack_requires_lien_waiver")) or any(row.get("requires_lien_waiver") for row in included)

    def _fail_key(self, finding: checks.Finding) -> str:
        reason = "through_date" if finding.details.get("reason") == "through_date" else "amount"
        return f"{self.rule_id}.fail_{reason}"

    def _severity_of(self, finding: checks.Finding) -> Severity:
        return Severity.ERROR if finding.details.get("severity") == "error" else Severity.WARNING


class SubPriorUnconditionalMissingRule(_SubRollupRule):
    """A sub paid on an earlier claim should have released that work unconditionally."""

    rule_id = "pay_application.sub_prior_unconditional_missing"
    name = "Earlier subcontractor payments are released unconditionally"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags a subcontractor paid on an earlier claim without an unconditional waiver through that period"
    check_name = "check_sub_prior_unconditional_missing"

    def _judged(self, rollup: dict[str, Any]) -> bool:
        return bool(_rows(rollup, "prior_paid"))


class SubLineUnmappedRule(_SubRollupRule):
    """Every included subcontract line must land on a billable line of the GC's schedule of values."""

    rule_id = "pay_application.sub_line_unmapped"
    name = "Included subcontract lines map to the schedule of values"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags an included subcontractor pay application line that resolves to no billable SOV line"
    check_name = "check_sub_line_unmapped"

    def _fail_key(self, finding: checks.Finding) -> str:
        reason = str(finding.details.get("reason") or "none")
        if reason not in ("none", "foreign_line", "parent_line"):
            reason = "none"
        return f"{self.rule_id}.fail_{reason}"


class SubExceedsGcLineRule(_SubRollupRule):
    """Subcontract approvals to date must fit inside the GC line's scheduled value."""

    rule_id = "pay_application.sub_exceeds_gc_line"
    name = "Subcontract approvals fit the scheduled value"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags an SOV line whose subcontract approvals to date exceed its scheduled value"
    check_name = "check_sub_exceeds_gc_line"

    def _judged(self, rollup: dict[str, Any]) -> bool:
        return bool(_rows(rollup, "lines"))


class SubCertificateLapsedRule(_SubRollupRule):
    """Each included sub must hold its required certificates at the claim's period end."""

    rule_id = "pay_application.sub_certificate_lapsed"
    name = "Included subcontractors hold their required certificates"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Flags an included subcontractor whose required certificate was not valid at the period end"
    check_name = "check_sub_certificate_lapsed"

    def _judged(self, rollup: dict[str, Any]) -> bool:
        # Without a period end nothing was checked, so no green row either.
        return bool(_rows(rollup, "included")) and checks.parse_date(rollup.get(checks.AS_OF_KEY)) is not None

    def _fail_key(self, finding: checks.Finding) -> str:
        state = str(finding.details.get("state") or "missing")
        if state not in ("missing", "expired", "revoked"):
            state = "missing"
        return f"{self.rule_id}.fail_{state}"

    def _params(self, finding: checks.Finding, locale: str) -> dict[str, str]:
        params = dict(finding.params)
        params["document"] = _token(f"{self.rule_id}.documents", params.get("document", ""), locale)
        return params


class SubCertificatePaymentDateRule(_SubRollupRule):
    """A certificate the law reads on the payment day must be valid on that day.

    Only packs that mark a certificate ``valid_at: "payment_date"`` produce
    anything for this rule; on every other claim it returns no row at all. It
    warns and never blocks, and it deducts nothing: the finding names the
    withholding the law requires on a payment the certificate did not cover,
    and a person decides what to do about it. An unpaid pay application gets
    a note, because its payment day has not come and "met" would be a claim
    nobody checked.
    """

    rule_id = "pay_application.sub_certificate_payment_date"
    name = "Payment-date certificates cover the payment"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        "Flags an included subcontractor pay application paid while a certificate the law reads on the "
        "payment date was not valid, and notes the ones not paid yet"
    )
    check_name = "check_sub_certificate_payment_date"

    def _judged(self, rollup: dict[str, Any]) -> bool:
        # The key exists only when the pack judges a certificate on the
        # payment date; without it this rule checked nothing.
        return any("payment_date_findings" in row for row in _rows(rollup, "included"))

    def _fail_key(self, finding: checks.Finding) -> str:
        state = str(finding.details.get("state") or "missing")
        if state not in checks.PAYMENT_DATE_STATES:
            state = "missing"
        return f"{self.rule_id}.fail_{state}"

    def _severity_of(self, finding: checks.Finding) -> Severity:
        return Severity.INFO if finding.details.get("severity") == "info" else Severity.WARNING

    def _params(self, finding: checks.Finding, locale: str) -> dict[str, str]:
        params = dict(finding.params)
        params["document"] = _token(f"{SubCertificateLapsedRule.rule_id}.documents", params.get("document", ""), locale)
        params["withholding"] = self._withholding(finding.details.get("withholding"), locale)
        return params

    def _withholding(self, terms: Any, locale: str) -> str:
        """The sentence that says what the law takes from a payment the certificate does not cover."""
        base = f"{self.rule_id}.withholding"
        if not isinstance(terms, dict) or not terms.get("rate_pct"):
            return translate(f"{base}.unknown", locale=locale)
        kind = "gross" if terms.get("vat_included") else "net"
        limit = checks.parse_money(terms.get("annual_limit"))
        params = {
            "rate": str(terms["rate_pct"]),
            "reference": str(terms.get("reference") or terms.get("scheme") or "?"),
            "limit": sentence_amount(limit, str(terms.get("currency") or "")) if limit is not None else "",
        }
        key = f"{base}.{kind}_limit" if limit is not None else f"{base}.{kind}"
        return translate(key, locale=locale, **params)


#: The subcontract rules, in the order a reader meets the findings: what is
#: being billed, then the paper behind it, then how it lands on the SOV.
SUB_ROLLUP_RULES: tuple[type[ValidationRule], ...] = (
    SubUnapprovedIncludedRule,
    SubWaiverMissingRule,
    SubPriorUnconditionalMissingRule,
    SubCertificateLapsedRule,
    SubCertificatePaymentDateRule,
    SubLineUnmappedRule,
    SubExceedsGcLineRule,
)


def register_sub_rollup_rules() -> str:
    """Register the subcontract rules into the payment application rule set.

    Returns the set name they went into, so the caller can log it. Registering
    twice is harmless: the registry replaces a rule by id and keeps a set's
    membership unique.
    """
    rule_set = pay_application_rule_set()
    for rule_class in SUB_ROLLUP_RULES:
        rule_registry.register(rule_class(), [rule_set])
    logger.debug("subcontractors: registered %d rules into %s", len(SUB_ROLLUP_RULES), rule_set)
    return rule_set


def register_sub_rollup_context() -> bool:
    """Give the contracts module the rollup these rules read.

    Registered under :data:`ROLLUP_KEY`, the one key the rules above read, so
    the provider and its readers cannot drift apart. Without this the rules
    are registered but every claim arrives with no rollup, and they judge
    nothing: the sub paper is never checked, and nothing says so.

    Returns ``False`` on an install without the contracts module, where no
    claim is ever checked and there is nothing to register with. Registering
    twice replaces the provider, so a reload stays registered once.
    """
    try:
        from app.modules.contracts.claim_context import register_claim_context_provider  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        # Same line as pay_application_rule_set: only the absence of the
        # contracts module is a normal install.
        if exc.name not in ("app.modules.contracts", "app.modules.contracts.claim_context"):
            raise
        return False
    from app.modules.subcontractors.rollup import claim_rule_context  # noqa: PLC0415

    register_claim_context_provider(ROLLUP_KEY, claim_rule_context)
    return True
