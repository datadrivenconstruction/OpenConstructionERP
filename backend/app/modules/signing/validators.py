# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Signing validation rules (rule set ``signing``).

Rules run over a plain dict context built by the caller::

    {"session": {"id", "status", "expires_at", "signatory_map", "document_content_hash"},
     "signature": {"signed_at", "content_hash", "signatory_role"}}

``signature`` is present only when an attestation is being recorded. ``metadata["now"]`` (ISO datetime)
overrides the reference moment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section

SIGNING_RULE_SET = "signing"

#: Clock skew between a signing tool and this server that is not yet "signed in the future".
CLOCK_SKEW = timedelta(minutes=5)


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _now(context: ValidationContext) -> datetime:
    return _moment((context.metadata or {}).get("now")) or datetime.now(UTC)


class _SigningRule(MoneyRule):
    standard = SIGNING_RULE_SET
    message_section = "signing"
    own_message_keys = frozenset({"no_required_signatory", "expiry_past", "signed_in_future", "signed_other_version"})


class SessionHasRequiredSignatoryRule(_SigningRule):
    """A session that is out of draft names at least one required signatory."""

    rule_id = "signing.required_signatory_named"
    name = "Signing session names a required signatory"
    severity = Severity.WARNING
    description = "without a required signatory the session can never reach fully signed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s = section(context, "session")
        ref = str(s.get("id", ""))
        if s.get("status") == "draft":
            return [self.ok(ref)]
        if not any(e.get("required", True) for e in (s.get("signatory_map") or []) if isinstance(e, dict)):
            return [self.fail(context, "no_required_signatory", ref=ref)]
        return [self.ok(ref)]


class SessionExpiryRule(_SigningRule):
    """A session is not opened, or re-dated, to expire in the past."""

    rule_id = "signing.expiry_in_future"
    name = "Signing session expiry is ahead"
    description = "expires_at must not be earlier than now"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s = section(context, "session")
        ref = str(s.get("id", ""))
        expires = _moment(s.get("expires_at"))
        if expires is not None and expires < _now(context):
            return [self.fail(context, "expiry_past", ref=ref, date=expires.date().isoformat())]
        return [self.ok(ref)]


class SignedAtNotFutureRule(_SigningRule):
    """A signature cannot be dated after the moment it is recorded."""

    rule_id = "signing.signed_at_not_future"
    name = "Signature is not dated in the future"
    description = "signed_at may be at most a few minutes ahead of the server clock"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        sig = section(context, "signature")
        ref = str(section(context, "session").get("id", ""))
        signed = _moment(sig.get("signed_at"))
        if signed is not None and signed > _now(context) + CLOCK_SKEW:
            return [self.fail(context, "signed_in_future", ref=ref, date=signed.date().isoformat())]
        return [self.ok(ref)]


class SignedCurrentVersionRule(_SigningRule):
    """The signatory signed the version of the document the session now holds."""

    rule_id = "signing.signed_current_version"
    name = "Signature is on the current document version"
    severity = Severity.WARNING
    description = "an attestation whose content hash differs from the session hash is stale at once"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        s, sig = section(context, "session"), section(context, "signature")
        ref = str(s.get("id", ""))
        signed, current = (
            str(sig.get("content_hash") or "").strip().lower(),
            str(s.get("document_content_hash") or "").strip().lower(),
        )
        if sig and signed and current and signed != current:
            return [self.fail(context, "signed_other_version", ref=ref, role=sig.get("signatory_role", ""))]
        return [self.ok(ref)]


SIGNING_RULES = (
    SessionHasRequiredSignatoryRule,
    SessionExpiryRule,
    SignedAtNotFutureRule,
    SignedCurrentVersionRule,
)


def register_signing_validation_rules() -> None:
    """Register the signing rules with the platform rule registry."""
    for rule_class in SIGNING_RULES:
        rule_registry.register(rule_class(), [SIGNING_RULE_SET])


__all__ = ["SIGNING_RULES", "SIGNING_RULE_SET", "register_signing_validation_rules"]
