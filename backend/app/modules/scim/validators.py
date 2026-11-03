# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM validation rules (rule set ``scim``).

* ``scim.no_admin_escalation`` - ERROR. A group may map to the admin role only when
  the setting ``scim_allow_admin_groups`` is on.
* ``scim.unique_email`` - ERROR. The email already belongs to another account.
* ``scim.last_admin_guard`` - ERROR. The last active admin cannot be deactivated or demoted.
* ``scim.email_format`` - ERROR. userName is not a valid email address.
* ``scim.orphan_external_id`` - WARNING. An account created outside SCIM is linked to an
  IdP identity, or its externalId changes.

Rules read the plain change snapshot built by :class:`~app.modules.scim.service.ScimService`
(keys documented per rule below); they touch no database.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

RULE_SET = "scim"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# rule id -> (HTTP status, SCIM scimType) used when an ERROR finding becomes a SCIM error.
SCIM_ERROR_MAP: dict[str, tuple[int, str]] = {
    "scim.no_admin_escalation": (400, "invalidValue"),
    "scim.unique_email": (409, "uniqueness"),
    "scim.last_admin_guard": (400, "mutability"),
    "scim.email_format": (400, "invalidValue"),
}


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _result(rule: ValidationRule, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


class NoAdminEscalation(ValidationRule):
    """Snapshot keys: ``group_role``, ``allow_admin_groups``, ``group``."""

    rule_id = "scim.no_admin_escalation"
    name = "Admin Group Mapping Needs An Explicit Switch"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A group can carry the admin role only when scim_allow_admin_groups is true."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        if d.get("group_role") != "admin":
            return []
        ok = bool(d.get("allow_admin_groups"))
        msg = "OK" if ok else "Mapping a group to the admin role is disabled (set scim_allow_admin_groups)."
        return [_result(self, ok, msg, d.get("group"))]


class UniqueEmail(ValidationRule):
    """Snapshot keys: ``email``, ``email_owner_id``, ``user_id``."""

    rule_id = "scim.unique_email"
    name = "Email Belongs To One Account"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The userName email must not already belong to a different account."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        owner = d.get("email_owner_id")
        if not d.get("email") or owner is None:
            return []
        ok = owner == d.get("user_id")
        msg = "OK" if ok else f"Email {d['email']} already belongs to another account."
        return [_result(self, ok, msg, d.get("email"))]


class LastAdminGuard(ValidationRule):
    """Snapshot keys: ``loses_admin`` (deactivated or demoted), ``target_is_active_admin``, ``active_admins``."""

    rule_id = "scim.last_admin_guard"
    name = "Keep At Least One Active Admin"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The last active admin cannot be deactivated or demoted."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        if not (d.get("loses_admin") and d.get("target_is_active_admin")):
            return []
        ok = int(d.get("active_admins") or 0) > 1
        msg = "OK" if ok else "This is the last active admin and cannot be deactivated or demoted."
        return [_result(self, ok, msg, d.get("user_id"))]


class EmailFormat(ValidationRule):
    """Snapshot key: ``email`` (checked whenever present)."""

    rule_id = "scim.email_format"
    name = "UserName Is An Email Address"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "userName must be a valid email address; it is the login of the account."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        email = _data(context).get("email")
        if email is None:
            return []
        ok = bool(_EMAIL.match(str(email))) and len(str(email)) <= 255
        msg = "OK" if ok else f"userName '{str(email)[:80]}' is not a valid email address."
        return [_result(self, ok, msg, str(email)[:80])]


class OrphanExternalId(ValidationRule):
    """Snapshot keys: ``external_id``, ``previous_external_id``, ``previous_provisioned_by``, ``adopting``."""

    rule_id = "scim.orphan_external_id"
    name = "ExternalId Matches The Account Origin"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "An account made outside SCIM was linked to an IdP identity, or its externalId changed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        ext = d.get("external_id")
        if not ext:
            return []
        prev = d.get("previous_external_id")
        relinked = bool(prev) and prev != ext
        adopted = bool(d.get("adopting")) and d.get("previous_provisioned_by") != "scim"
        if not (relinked or adopted):
            return []
        what = "changed" if relinked else "linked to an existing account created outside SCIM"
        return [_result(self, False, f"externalId {what}.", d.get("user_id"), external_id=ext)]


_RULES: tuple[ValidationRule, ...] = (
    NoAdminEscalation(),
    UniqueEmail(),
    LastAdminGuard(),
    EmailFormat(),
    OrphanExternalId(),
)


def register_scim_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])
