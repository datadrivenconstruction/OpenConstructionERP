# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for a person's MCP setup.

An open door to an AI client is only as safe as the keys hanging next to it.
These rules read the person's settings, their MCP tokens and the denied calls
of the last day, and flag what a careful administrator would:

* ``mcp.rate_limit_range``     - ERROR. The per-minute budget is outside the
                                 range the endpoint enforces.
* ``mcp.token_without_expiry`` - WARNING. An active token never expires.
* ``mcp.token_unused``         - WARNING. An active token has not been used for
                                 a long time (or never, weeks after it was made).
* ``mcp.too_many_tokens``      - WARNING. More active tokens than clients a
                                 person plausibly runs.
* ``mcp.denied_calls``         - WARNING. Many calls were refused in the last
                                 24 hours: a misconfigured client or a probe.
* ``mcp.enabled_without_token``- INFO. MCP is on but no token can use it.

The rules take a plain dict so they are testable without a session::

    {"now": datetime, "settings": McpSettingsResponse, "tokens": [McpTokenResponse], "denied_last_24h": int}
"""

from __future__ import annotations

import logging
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
from app.modules.mcp.models import MAX_RATE_LIMIT_PER_MINUTE, MIN_RATE_LIMIT_PER_MINUTE

logger = logging.getLogger(__name__)

MCP_RULE_SET = "mcp"
UNUSED_AFTER_DAYS = 90
NEVER_USED_GRACE_DAYS = 30
MAX_ACTIVE_TOKENS = 5
DENIED_CALLS_THRESHOLD = 10


def _payload(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _now(payload: dict[str, Any]) -> datetime:
    value = payload.get("now")
    return value if isinstance(value, datetime) else datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _active(payload: dict[str, Any]) -> list[Any]:
    now = _now(payload)
    return [
        t
        for t in payload.get("tokens", [])
        if t.is_active and (t.expires_at is None or _aware(t.expires_at) > now)  # type: ignore[operator]
    ]


def _result(rule: ValidationRule, passed: bool, message: str, **kwargs: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        **kwargs,
    )


class RateLimitRangeRule(ValidationRule):
    """The per-minute budget must be one the endpoint enforces."""

    rule_id = "mcp.rate_limit_range"
    name = "MCP rate limit within range"
    standard = "mcp"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The per-minute call budget is between the minimum and maximum the endpoint accepts."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        settings = _payload(context).get("settings")
        if settings is None:
            return [_result(self, True, "No settings supplied.")]
        value = int(settings.rate_limit_per_minute)
        ok = MIN_RATE_LIMIT_PER_MINUTE <= value <= MAX_RATE_LIMIT_PER_MINUTE
        return [
            _result(
                self,
                ok,
                "Rate limit is within range."
                if ok
                else f"Rate limit {value} is outside {MIN_RATE_LIMIT_PER_MINUTE}-{MAX_RATE_LIMIT_PER_MINUTE}.",
                details={"value": value, "min": MIN_RATE_LIMIT_PER_MINUTE, "max": MAX_RATE_LIMIT_PER_MINUTE},
                suggestion=None if ok else "Set a rate limit inside the allowed range.",
            )
        ]


class TokenWithoutExpiryRule(ValidationRule):
    """An active token that never expires."""

    rule_id = "mcp.token_without_expiry"
    name = "MCP token without expiry"
    standard = "mcp"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Every active MCP token has an expiry date, so a forgotten client loses access by itself."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results = [
            _result(
                self,
                False,
                f"Token '{t.name}' never expires.",
                element_ref=str(t.id),
                details={"name": t.name, "prefix": t.key_prefix},
                suggestion="Revoke it and create a token with an expiry date.",
            )
            for t in _active(_payload(context))
            if t.expires_at is None
        ]
        return results or [_result(self, True, "Every active token expires.")]


class TokenUnusedRule(ValidationRule):
    """An active token nobody has used for a long time."""

    rule_id = "mcp.token_unused"
    name = "Unused MCP token"
    standard = "mcp"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        f"An active token unused for {UNUSED_AFTER_DAYS} days, or never used {NEVER_USED_GRACE_DAYS} days after "
        "it was created, is a key nobody is watching."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        now = _now(payload)
        results = []
        for t in _active(payload):
            last = _aware(t.last_used_at)
            created = _aware(t.created_at) or now
            if last is not None:
                idle = (now - last).days
                stale = idle >= UNUSED_AFTER_DAYS
            else:
                idle = (now - created).days
                stale = now - created >= timedelta(days=NEVER_USED_GRACE_DAYS)
            if stale:
                results.append(
                    _result(
                        self,
                        False,
                        f"Token '{t.name}' has not been used for {idle} days.",
                        element_ref=str(t.id),
                        details={"name": t.name, "prefix": t.key_prefix, "days": idle},
                        suggestion="Revoke tokens of clients you no longer use.",
                    )
                )
        return results or [_result(self, True, "Every active token is in use.")]


class TooManyTokensRule(ValidationRule):
    """More active tokens than one person plausibly needs."""

    rule_id = "mcp.too_many_tokens"
    name = "Too many MCP tokens"
    standard = "mcp"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = f"At most {MAX_ACTIVE_TOKENS} active MCP tokens per person; one per client is enough."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        count = len(_active(_payload(context)))
        ok = count <= MAX_ACTIVE_TOKENS
        return [
            _result(
                self,
                ok,
                f"{count} active tokens." if ok else f"{count} active tokens, more than {MAX_ACTIVE_TOKENS}.",
                details={"active": count, "max": MAX_ACTIVE_TOKENS},
                suggestion=None if ok else "Revoke the tokens of clients you no longer use.",
            )
        ]


class DeniedCallsRule(ValidationRule):
    """Many refused calls in the last day."""

    rule_id = "mcp.denied_calls"
    name = "Refused MCP calls"
    standard = "mcp"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        f"{DENIED_CALLS_THRESHOLD} or more calls refused in 24 hours point to a misconfigured client or a probe."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        count = int(_payload(context).get("denied_last_24h") or 0)
        ok = count < DENIED_CALLS_THRESHOLD
        return [
            _result(
                self,
                ok,
                f"{count} refused calls in 24 hours.",
                details={"refused": count, "threshold": DENIED_CALLS_THRESHOLD},
                suggestion=None if ok else "Check the recent calls below and revoke a token you do not recognise.",
            )
        ]


class EnabledWithoutTokenRule(ValidationRule):
    """MCP is switched on but nothing can use it."""

    rule_id = "mcp.enabled_without_token"
    name = "MCP enabled without a token"
    standard = "mcp"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "MCP is on, so at least one active token is expected."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        settings = payload.get("settings")
        enabled = bool(settings and settings.enabled)
        ok = not enabled or bool(_active(payload))
        return [
            _result(
                self,
                ok,
                "MCP setup is complete." if ok else "MCP is enabled but no active token exists.",
                suggestion=None if ok else "Create a token and paste the client configuration into your AI client.",
            )
        ]


MCP_RULES: tuple[type[ValidationRule], ...] = (
    RateLimitRangeRule,
    TokenWithoutExpiryRule,
    TokenUnusedRule,
    TooManyTokensRule,
    DeniedCallsRule,
    EnabledWithoutTokenRule,
)


def register_mcp_rules() -> None:
    """Register every MCP rule under the ``mcp`` rule set (idempotent: the registry keys on rule id)."""
    for rule_cls in MCP_RULES:
        rule_registry.register(rule_cls(), [MCP_RULE_SET])
    logger.debug("Registered %d MCP validation rules", len(MCP_RULES))


__all__ = [
    "MCP_RULES",
    "MCP_RULE_SET",
    "register_mcp_rules",
]
