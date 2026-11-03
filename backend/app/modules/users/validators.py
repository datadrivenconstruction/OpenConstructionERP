# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules an API key must satisfy before it is issued, and the scope catalogue.

Pure functions: no database, no request. The service feeds them the facts
(existing keys, the clock) and turns a :class:`ApiKeyRuleError` into an HTTP
response, so every rule is testable on its own.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from app.core.permissions import permission_registry

MAX_ACTIVE_KEYS_PER_USER = 25
MAX_EXPIRY_DAYS = 730  # two years
ROTATION_OVERLAP = timedelta(hours=24)

SCOPE_I18N_PREFIX = "developer.scope."


class ApiKeyRuleError(ValueError):
    """An API key rule failed; ``code`` is stable, ``status`` is the HTTP status."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def scope_catalogue() -> list[dict[str, str]]:
    """Every scope a key can carry, generated from the permission registry.

    The scope name is the permission name. ``i18n_key`` lets the UI show a
    translated label; it falls back to the name when no label is shipped.
    """
    rows: list[dict[str, str]] = []
    for name, role in sorted(permission_registry.list_all().items()):
        module, _, action = name.partition(".")
        rows.append(
            {
                "name": name,
                "module": module,
                "action": action,
                "min_role": str(role),
                "i18n_key": f"{SCOPE_I18N_PREFIX}{name}",
            }
        )
    return rows


def validate_scopes(scopes: Iterable[str]) -> list[str]:
    """Return the scopes de-duplicated in order; reject any name the registry does not know."""
    known = set(permission_registry.list_all())
    out: list[str] = []
    unknown: list[str] = []
    for scope in scopes:
        if scope not in known:
            unknown.append(scope)
        elif scope not in out:
            out.append(scope)
    if unknown:
        raise ApiKeyRuleError("api_key.unknown_scope", f"Unknown scope: {', '.join(sorted(set(unknown)))}")
    return out


def validate_expiry(expires_at: datetime | None, now: datetime) -> None:
    """Expiry must lie in the future and at most two years ahead. ``None`` never expires."""
    if expires_at is None:
        return
    if expires_at <= now:
        raise ApiKeyRuleError("api_key.expiry_in_past", "Expiry must be in the future")
    if expires_at > now + timedelta(days=MAX_EXPIRY_DAYS):
        raise ApiKeyRuleError("api_key.expiry_too_far", "Expiry must be at most 2 years ahead")


def validate_name_unique(name: str, active_names: Iterable[str]) -> None:
    """A user may not hold two active keys with the same name (case-insensitive)."""
    wanted = name.strip().casefold()
    if any(existing.strip().casefold() == wanted for existing in active_names):
        raise ApiKeyRuleError("api_key.name_taken", "An active key with this name already exists", status=409)


def validate_active_cap(active_count: int) -> None:
    """At most :data:`MAX_ACTIVE_KEYS_PER_USER` active keys per user."""
    if active_count >= MAX_ACTIVE_KEYS_PER_USER:
        raise ApiKeyRuleError(
            "api_key.too_many",
            f"At most {MAX_ACTIVE_KEYS_PER_USER} active keys per user",
            status=409,
        )


def ip_allowed(client_ip: str | None, cidrs: Sequence[str] | None) -> bool:
    """True when the key has no allow-list, or ``client_ip`` lies inside one of its networks.

    An unparsable or missing address is refused whenever a list is set. An
    IPv4-mapped IPv6 address (``::ffff:203.0.113.7``) is checked as IPv4.
    """
    if not cidrs:
        return True
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip.strip().strip("[]"))
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    for raw in cidrs:
        try:
            if addr in ipaddress.ip_network(raw, strict=False):
                return True
        except ValueError:
            continue
    return False
