# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Credentials-registry validation rules.

A register of tickets is only worth keeping if something reads it and objects.
These rules are that reader. They run over one project's credentials, the
requirements the project sets, and the compliance report joining the two, and
they answer the questions a site manager would ask on a Monday morning:

* ``credentials.blocking_gap``          - ERROR. Somebody on the register cannot
                                          work today: a blocking requirement is
                                          unmet, expired past its grace window,
                                          suspended or revoked.
* ``credentials.notification_overdue``  - ERROR. A statutory notification window
                                          has closed with nothing recorded
                                          against it.
* ``credentials.expiring_window``       - WARNING. A credential has entered its
                                          own reminder window and needs renewing.
* ``credentials.no_expiry_recorded``    - WARNING. A credential of a family that
                                          normally lapses carries no expiry date,
                                          so nothing can ever warn about it.
* ``credentials.unverified_blocking``   - WARNING. A blocking requirement is
                                          satisfied only by a credential nobody
                                          has checked against its authority.
* ``credentials.duplicate_identifier``  - WARNING. One authority and identifier
                                          recorded twice, which double-counts a
                                          holder's cover.
* ``credentials.unmatched_requirement`` - WARNING. A requirement that binds
                                          nobody on the register: usually a
                                          discipline typo, and always a rule that
                                          silently measures nothing.

Every rule is jurisdiction-neutral. None of them knows what a country requires;
they read the requirements the project itself has recorded. The one date rule
that looks statutory (``notification_overdue``) reads the window off the row.

The rules take their input as a plain dict rather than ORM instances so they
stay unit-testable without a session:

    {
        "today": date,
        "credentials": [Credential, ...],
        "requirements": [CredentialRequirement, ...],
        "compliance": ComplianceReport,
    }

Registration follows the module convention: :func:`register_credentials_rules`
is idempotent and is called from the module's ``on_startup`` hook, and from the
test suite's session fixture because no test process runs application startup.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from datetime import timedelta
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

# The rule set every credentials rule registers under.
CREDENTIALS_RULE_SET = "credentials"

# Credential families that are expected to carry an expiry date. An
# accreditation or a one-off training record may legitimately be perpetual, so
# they are excluded rather than nagged about.
_EXPIRING_FAMILIES: frozenset[str] = frozenset(
    {
        "professional_license",
        "certification",
        "statutory_membership",
        "professional_indemnity",
        "registration",
    }
)

# Metadata key a caller sets once the statutory notification has been sent.
_NOTIFIED_KEY = "notification_sent_at"


def _payload(context: ValidationContext) -> dict[str, Any]:
    """Read the rule payload out of the context, tolerating an empty run."""
    data = context.data
    return data if isinstance(data, dict) else {}


def _today(payload: dict[str, Any]) -> _date:
    value = payload.get("today")
    return value if isinstance(value, _date) else _date.today()


def _ok(rule: ValidationRule, message: str) -> RuleResult:
    """A single passing result, so a clean run still counts as checked."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=True,
        message=message,
    )


class BlockingGapRule(ValidationRule):
    """Somebody on the register cannot work today."""

    rule_id = "credentials.blocking_gap"
    name = "Blocking credential gap"
    standard = "credentials"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "A holder fails a blocking requirement: the credential is missing, "
        "expired beyond its grace window, suspended or revoked."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        report = payload.get("compliance")
        if report is None:
            return [_ok(self, "No compliance report supplied; nothing to check.")]

        results: list[RuleResult] = []
        for holder in report.holders:
            if not holder.is_blocked:
                continue
            for gap in holder.gaps:
                if not gap.is_blocking or gap.within_grace:
                    continue
                if gap.reason == "expiring_soon":
                    continue
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=(f"{holder.holder_name} cannot work: {gap.credential_type} is {gap.reason}."),
                        element_ref=str(gap.credential_id) if gap.credential_id else None,
                        suggestion=(
                            "Obtain or renew the credential, or relax the requirement if the rule no longer applies."
                        ),
                        details={
                            "holder_name": holder.holder_name,
                            "credential_type": gap.credential_type,
                            "reason": gap.reason,
                            "requirement_id": str(gap.requirement_id),
                        },
                    )
                )

        return results or [_ok(self, "Every holder meets the project's blocking requirements.")]


class NotificationOverdueRule(ValidationRule):
    """A statutory notification window closed with nothing recorded."""

    rule_id = "credentials.notification_overdue"
    name = "Statutory notification overdue"
    standard = "credentials"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "A credential carries a notification obligation whose window has passed without a recorded notification."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        today = _today(payload)
        results: list[RuleResult] = []

        for credential in payload.get("credentials", []):
            window = credential.notification_obligation_days
            if window is None or credential.issued_at is None:
                continue
            if (credential.metadata_ or {}).get(_NOTIFIED_KEY):
                continue
            due = credential.issued_at + timedelta(days=window)
            if today <= due:
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(
                        f"Notification for {credential.holder_name}'s "
                        f"{credential.credential_type} was due by {due.isoformat()}."
                    ),
                    element_ref=str(credential.id),
                    suggestion=(f"Send the notification and record the date under the '{_NOTIFIED_KEY}' metadata key."),
                    details={
                        "holder_name": credential.holder_name,
                        "due_on": due.isoformat(),
                        "days_overdue": (today - due).days,
                        "trigger": credential.notification_trigger,
                    },
                )
            )

        return results or [_ok(self, "No notification obligation is overdue.")]


class ExpiringWindowRule(ValidationRule):
    """A credential has entered its own reminder window."""

    rule_id = "credentials.expiring_window"
    name = "Credential expiring"
    standard = "credentials"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A credential is inside its reminder window and needs renewing."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        today = _today(payload)
        results: list[RuleResult] = []

        for credential in payload.get("credentials", []):
            if credential.valid_until is None or credential.status in {"suspended", "revoked"}:
                continue
            days_left = (credential.valid_until - today).days
            if days_left < 0 or days_left > max(0, credential.notify_days_before):
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(f"{credential.holder_name}'s {credential.credential_type} expires in {days_left} day(s)."),
                    element_ref=str(credential.id),
                    suggestion="Start the renewal before the credential lapses.",
                    details={
                        "holder_name": credential.holder_name,
                        "credential_type": credential.credential_type,
                        "valid_until": credential.valid_until.isoformat(),
                        "days_until_expiry": days_left,
                    },
                )
            )

        return results or [_ok(self, "No credential is inside its reminder window.")]


class NoExpiryRecordedRule(ValidationRule):
    """A credential that should lapse carries no expiry date."""

    rule_id = "credentials.no_expiry_recorded"
    name = "Credential has no expiry date"
    standard = "credentials"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = (
        "A credential of a family that normally expires has no valid_until, so no reminder can ever fire for it."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        results: list[RuleResult] = []

        for credential in payload.get("credentials", []):
            if credential.valid_until is not None:
                continue
            if credential.credential_type not in _EXPIRING_FAMILIES:
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(f"{credential.holder_name}'s {credential.credential_type} has no expiry date recorded."),
                    element_ref=str(credential.id),
                    suggestion=("Record the expiry date, or move the entry to a family that is genuinely perpetual."),
                    details={
                        "holder_name": credential.holder_name,
                        "credential_type": credential.credential_type,
                    },
                )
            )

        return results or [_ok(self, "Every expiring credential family carries a date.")]


class UnverifiedBlockingRule(ValidationRule):
    """A blocking requirement rests on an unchecked credential."""

    rule_id = "credentials.unverified_blocking"
    name = "Blocking requirement met by an unverified credential"
    standard = "credentials"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        "A holder satisfies a blocking requirement with a credential nobody has verified against its issuing authority."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        report = payload.get("compliance")
        if report is None:
            return [_ok(self, "No compliance report supplied; nothing to check.")]

        results: list[RuleResult] = []
        for holder in report.holders:
            if holder.unverified_count <= 0:
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(
                        f"{holder.holder_name} meets {holder.unverified_count} requirement(s) "
                        "with credentials nobody has verified."
                    ),
                    suggestion="Check the credential against the issuing authority and record it.",
                    details={
                        "holder_name": holder.holder_name,
                        "unverified_count": holder.unverified_count,
                    },
                )
            )

        return results or [_ok(self, "Every satisfied requirement rests on a verified credential.")]


class DuplicateIdentifierRule(ValidationRule):
    """One authority and identifier recorded more than once."""

    rule_id = "credentials.duplicate_identifier"
    name = "Duplicate credential identifier"
    standard = "credentials"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The same authority and identifier appear on more than one row, which double-counts a holder's cover."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        seen: dict[tuple[str, str], list[Any]] = defaultdict(list)

        for credential in payload.get("credentials", []):
            identifier = (credential.identifier or "").strip().casefold()
            if not identifier:
                continue
            authority = (credential.authority or "").strip().casefold()
            seen[(authority, identifier)].append(credential)

        results: list[RuleResult] = []
        for (authority, identifier), rows in seen.items():
            if len(rows) < 2:
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(
                        f"Identifier {identifier!r} appears on {len(rows)} credentials"
                        + (f" from {authority!r}." if authority else ".")
                    ),
                    element_ref=str(rows[0].id),
                    suggestion="Merge the duplicates or correct the identifier on one of them.",
                    details={
                        "identifier": identifier,
                        "authority": authority or None,
                        "credential_ids": [str(r.id) for r in rows],
                    },
                )
            )

        return results or [_ok(self, "No credential identifier is recorded twice.")]


class UnmatchedRequirementRule(ValidationRule):
    """A requirement that binds nobody on the register."""

    rule_id = "credentials.unmatched_requirement"
    name = "Requirement matches no holder"
    standard = "credentials"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A requirement applies to nobody on the register, so it silently measures nothing."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        report = payload.get("compliance")
        if report is None:
            return [_ok(self, "No compliance report supplied; nothing to check.")]
        if not report.holders:
            # An empty register is not a misconfigured requirement. Say so
            # rather than flagging every rule on a project nobody has staffed.
            return [_ok(self, "The register holds no credentials yet.")]

        by_id = {r.id: r for r in payload.get("requirements", [])}
        results: list[RuleResult] = []
        for requirement_id in report.unmatched_requirement_ids:
            requirement = by_id.get(requirement_id)
            label = requirement.credential_type if requirement else str(requirement_id)
            audience = requirement.applies_to if requirement else "?"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(f"The {label} requirement for {audience!r} matches nobody on the register."),
                    element_ref=str(requirement_id),
                    suggestion=(
                        "Check the audience spelling against the disciplines actually recorded, "
                        "or retire the requirement."
                    ),
                    details={
                        "requirement_id": str(requirement_id),
                        "credential_type": label,
                        "applies_to": audience,
                    },
                )
            )

        return results or [_ok(self, "Every requirement binds at least one holder.")]


CREDENTIALS_RULES: tuple[type[ValidationRule], ...] = (
    BlockingGapRule,
    NotificationOverdueRule,
    ExpiringWindowRule,
    NoExpiryRecordedRule,
    UnverifiedBlockingRule,
    DuplicateIdentifierRule,
    UnmatchedRequirementRule,
)


def register_credentials_rules() -> None:
    """Register every credentials rule under the ``credentials`` rule set.

    Idempotent: the registry keys on ``rule_id``, so calling this twice (module
    startup plus a test fixture) leaves one copy of each rule.
    """
    for rule_cls in CREDENTIALS_RULES:
        rule_registry.register(rule_cls(), [CREDENTIALS_RULE_SET])
    logger.debug("Registered %d credentials validation rules", len(CREDENTIALS_RULES))


__all__ = [
    "CREDENTIALS_RULES",
    "CREDENTIALS_RULE_SET",
    "BlockingGapRule",
    "DuplicateIdentifierRule",
    "ExpiringWindowRule",
    "NoExpiryRecordedRule",
    "NotificationOverdueRule",
    "UnmatchedRequirementRule",
    "UnverifiedBlockingRule",
    "register_credentials_rules",
]
