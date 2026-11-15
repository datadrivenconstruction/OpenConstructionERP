"""Enforced single sign-on for chosen email domains (setting ``sso_enforced_domains``)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _provider_serves(session: AsyncSession, domain: str) -> bool:
    """True when an enabled SSO provider has the domain routed to it or routes every domain."""
    from app.modules.sso.repository import SsoRepository

    for p in await SsoRepository(session).list_providers(enabled_only=True):
        domains = {str(d).strip().lower() for d in (p.email_domains or [])}
        if not domains or domain in domains:
            return True
    return False


async def assert_password_allowed(settings: Any, email: str, session: AsyncSession, user: Any = None) -> None:
    """Raise 403 ``auth.sso_required`` for an enforced domain that has an enabled provider.

    Break-glass admins are exempt. Without an enabled provider the password stays allowed
    (a warning is logged) so a misconfigured install cannot lock everyone out.
    """
    domains = enforced_domains(settings)
    if not domains:
        return
    domain = (email or "").rpartition("@")[2].strip().lower()
    if domain not in domains or is_break_glass(user):
        return
    if not await _provider_serves(session, domain):
        logger.warning("sso_enforced_domains lists %s but no enabled SSO provider serves it; password allowed", domain)
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": SSO_REQUIRED_CODE,
            "message_key": SSO_REQUIRED_CODE,
            "message": "Your organisation requires single sign-on. Use the SSO button to sign in.",
        },
    )
