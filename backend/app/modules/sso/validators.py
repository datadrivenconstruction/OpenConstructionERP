# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SSO provider validation rules (rule set ``sso``).

* ``sso.slug_format`` - ERROR. Slug is 2-64 chars of a-z, 0-9 and dashes (it is part of URLs).
* ``sso.protocol_fields`` - ERROR. OIDC needs an https issuer and a client ID; SAML needs the IdP
  entity ID, an https SSO URL and a PEM certificate.
* ``sso.saml_available`` - ERROR. A SAML provider needs the optional ``[sso]`` extra installed.
* ``sso.idp_certificate`` - ERROR when the certificate does not parse, WARNING when it expires in
  under 30 days, ERROR when it has expired.
* ``sso.clock_skew`` - ERROR. Clock skew is 0-600 seconds.
* ``sso.role_mapping`` - ERROR. Mapped and default roles must exist; default is never admin;
  a group maps to admin only with ``allow_admin_mapping``.
* ``sso.email_domains`` - ERROR. Domains look like ``example.com``.

Rules read the plain snapshot built by :class:`~app.modules.sso.service.SsoService`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

RULE_SET = "sso"
VALID_ROLES = ("admin", "manager", "editor", "viewer")
MAX_CLOCK_SKEW = 600

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
_DOMAIN = re.compile(r"^(?=.{3,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    ref: str | None = None,
    severity: Severity | None = None,
    **details: Any,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=severity or rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


class SlugFormat(ValidationRule):
    rule_id = "sso.slug_format"
    name = "Provider Slug Is URL Safe"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "The slug appears in login and metadata URLs: lowercase letters, digits and dashes."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        slug = str(_data(context).get("slug") or "")
        ok = bool(_SLUG.match(slug))
        return [_result(self, ok, "OK" if ok else f"Slug '{slug[:64]}' is not URL safe.", slug[:64])]


def _https(url: Any) -> bool:
    return isinstance(url, str) and url.startswith("https://") and len(url) > 8


class ProtocolFields(ValidationRule):
    rule_id = "sso.protocol_fields"
    name = "Provider Has Its Protocol Settings"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "OIDC: https issuer and client ID. SAML: IdP entity ID, https SSO URL and certificate."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        proto = d.get("protocol")
        missing: list[str] = []
        if proto == "oidc":
            if not _https(d.get("oidc_issuer")):
                missing.append("oidc_issuer")
            if not d.get("oidc_client_id"):
                missing.append("oidc_client_id")
        elif proto == "saml":
            if not d.get("saml_idp_entity_id"):
                missing.append("saml_idp_entity_id")
            if not _https(d.get("saml_idp_sso_url")):
                missing.append("saml_idp_sso_url")
            if not d.get("saml_idp_cert"):
                missing.append("saml_idp_cert")
        else:
            missing.append("protocol")
        ok = not missing
        msg = "OK" if ok else f"Missing or invalid: {', '.join(missing)}."
        return [_result(self, ok, msg, d.get("slug"), missing=missing)]


class SamlAvailable(ValidationRule):
    rule_id = "sso.saml_available"
    name = "SAML Support Is Installed"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "SAML providers need the optional [sso] extra (signxml) on the server."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        if d.get("protocol") != "saml":
            return []
        ok = bool(d.get("saml_available"))
        msg = "OK" if ok else "SAML is not installed on this server: pip install 'openconstructionerp[sso]'."
        return [_result(self, ok, msg, d.get("slug"))]


def load_certificate(pem: str) -> Any:
    """Parse a PEM (or bare base64) X.509 certificate; raise ValueError when it is not one."""
    from cryptography import x509

    text = pem.strip()
    if "BEGIN CERTIFICATE" not in text:
        body = "".join(text.split())
        text = "-----BEGIN CERTIFICATE-----\n" + body + "\n-----END CERTIFICATE-----"
    return x509.load_pem_x509_certificate(text.encode("ascii", "ignore"))


def normalise_certificate(pem: str) -> str:
    """Return the certificate as PEM text."""
    from cryptography.hazmat.primitives.serialization import Encoding

    return load_certificate(pem).public_bytes(Encoding.PEM).decode("ascii")


class IdpCertificate(ValidationRule):
    rule_id = "sso.idp_certificate"
    name = "IdP Signing Certificate Is Valid"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "The IdP certificate must parse and be within its validity period."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        pem = d.get("saml_idp_cert")
        if d.get("protocol") != "saml" or not pem:
            return []
        try:
            cert = load_certificate(str(pem))
        except ValueError:
            return [_result(self, False, "IdP certificate is not a valid X.509 certificate.", d.get("slug"))]
        expires = cert.not_valid_after_utc
        now = datetime.now(UTC)
        if expires <= now:
            return [_result(self, False, "IdP certificate has expired.", d.get("slug"), expires=expires.isoformat())]
        if expires - now < timedelta(days=30):
            return [
                _result(
                    self,
                    False,
                    "IdP certificate expires within 30 days.",
                    d.get("slug"),
                    severity=Severity.WARNING,
                    expires=expires.isoformat(),
                )
            ]
        return [_result(self, True, "OK", d.get("slug"))]


class ClockSkew(ValidationRule):
    rule_id = "sso.clock_skew"
    name = "Clock Skew Is Bounded"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = f"Allowed clock skew is 0-{MAX_CLOCK_SKEW} seconds; more widens the replay window."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        try:
            skew = int(d.get("clock_skew_seconds", 0))
        except (TypeError, ValueError):
            skew = -1
        ok = 0 <= skew <= MAX_CLOCK_SKEW
        return [_result(self, ok, "OK" if ok else f"Clock skew {skew}s is outside 0-{MAX_CLOCK_SKEW}.", d.get("slug"))]


class RoleMapping(ValidationRule):
    rule_id = "sso.role_mapping"
    name = "Group Role Mapping Is Safe"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Roles must exist, the default role is never admin, admin groups need an explicit switch."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        problems: list[str] = []
        default = d.get("default_role")
        if default not in VALID_ROLES or default == "admin":
            problems.append(f"default_role '{default}'")
        mapping = d.get("group_role_map") or {}
        if not isinstance(mapping, dict):
            problems.append("group_role_map is not an object")
            mapping = {}
        for group, role in mapping.items():
            if role not in VALID_ROLES:
                problems.append(f"group '{group}' -> unknown role '{role}'")
            elif role == "admin" and not d.get("allow_admin_mapping"):
                problems.append(f"group '{group}' -> admin needs allow_admin_mapping")
        ok = not problems
        return [_result(self, ok, "OK" if ok else "; ".join(problems), d.get("slug"), problems=problems)]


class EmailDomains(ValidationRule):
    rule_id = "sso.email_domains"
    name = "Email Domains Are Well Formed"
    standard = "universal"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Each routed email domain looks like example.com."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        bad = [x for x in (d.get("email_domains") or []) if not _DOMAIN.match(str(x))]
        ok = not bad
        return [_result(self, ok, "OK" if ok else f"Invalid domains: {', '.join(map(str, bad))}.", d.get("slug"))]


_RULES: tuple[ValidationRule, ...] = (
    SlugFormat(),
    ProtocolFields(),
    SamlAvailable(),
    IdpCertificate(),
    ClockSkew(),
    RoleMapping(),
    EmailDomains(),
)


def register_sso_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])
