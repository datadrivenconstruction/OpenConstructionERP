"""Enforced single sign-on for chosen email domains (setting ``sso_enforced_domains``)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

SSO_REQUIRED_CODE = "auth.sso_required"


def enforced_domains(settings: Any) -> frozenset[str]:
    """Lowercased domains from the comma separated setting, without a leading ``@``."""
    raw = getattr(settings, "sso_enforced_domains", "") or ""
    return frozenset(d.strip().lstrip("@").lower() for d in raw.split(",") if d.strip())


def is_break_glass(user: Any) -> bool:
    """An admin explicitly flagged as the emergency account that may still use a password."""
    if user is None or getattr(user, "role", None) != "admin":
        return False
    return (getattr(user, "metadata_", None) or {}).get("break_glass") is True


def assert_password_allowed(settings: Any, email: str, user: Any = None) -> None:
    """Raise 403 ``auth.sso_required`` when *email* is on an enforced domain and not break-glass."""
    domains = enforced_domains(settings)
    if not domains:
        return
    domain = (email or "").rpartition("@")[2].strip().lower()
    if domain not in domains or is_break_glass(user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": SSO_REQUIRED_CODE,
            "message_key": SSO_REQUIRED_CODE,
            "message": "Your organisation requires single sign-on. Use the SSO button to sign in.",
        },
    )


def warn_if_misconfigured(settings: Any) -> None:
    """Startup hint: enforcing SSO while OIDC is off would lock these users out."""
    if enforced_domains(settings) and not getattr(settings, "oidc_enabled", False):
        logger.warning(
            "SSO_ENFORCED_DOMAINS is set but OIDC_ENABLED is false: users on %s have no way to sign in "
            "except break-glass admins.",
            ", ".join(sorted(enforced_domains(settings))),
        )
