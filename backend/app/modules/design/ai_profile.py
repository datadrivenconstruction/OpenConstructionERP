"""AI profile handoff (R14): what the linked editor may use for the session, from the user's own ERP settings.

The profile is built per request from the settings the caller saved in the ERP (Settings > AI). It is never stored
by this module, never logged, and sent only with ``Cache-Control: no-store``. A key the user did not save themselves
(a server-wide key from the environment) is never handed out. Endpoints come from the ERP's own provider table; a
provider the table does not name needs an entry in ``OE_DESIGN_AI_ENDPOINTS`` or it yields no profile.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from .auth import now_utc
from .settings import get_design_settings

logger = logging.getLogger(__name__)
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _is_loopback(host: str | None) -> bool:
    return (host or "").lower() in LOOPBACK


def _endpoint(provider: str, settings: Any) -> tuple[str, str] | None:
    """``(protocol, endpoint)`` for a provider, or None when nothing names one."""
    from app.modules.ai import ai_client

    configured = get_design_settings().ai_endpoints.get(provider)
    if configured:
        return configured["protocol"], configured["endpoint"]
    if provider in ai_client.SELF_HOSTED_PROVIDERS:
        url = ai_client.self_hosted_endpoints(getattr(settings, "metadata_", None)).get(provider)
        return ("chat-completions", url) if url else None
    entry = ai_client._OPENAI_COMPAT_CONFIG.get(provider)
    return ("chat-completions", entry["url"]) if entry else None


async def build_profile(session, user_id: uuid.UUID, client_host: str | None) -> dict[str, Any] | None:
    """The ``ai`` block of ``ddc-context/1`` for ``user_id``, or None when there is nothing usable and safe to hand over."""
    from app.modules.ai import ai_client
    from app.modules.ai.repository import AISettingsRepository

    settings = await AISettingsRepository(session).get_by_user_id(user_id)
    if settings is None:
        return None
    try:
        provider, key, model = ai_client.resolve_provider_key_model(settings)
    except ValueError:
        return None
    self_hosted = provider in ai_client.SELF_HOSTED_PROVIDERS
    if not self_hosted and not getattr(settings, f"{provider}_api_key", None):
        logger.info("design: AI profile withheld, the key is not one the user saved")
        return None
    found = _endpoint(provider, settings)
    if found is None:
        logger.info("design: AI profile withheld, no endpoint is known for provider %s", provider)
        return None
    protocol, endpoint = found
    loopback = _is_loopback(urlsplit(endpoint).hostname)
    if loopback and not _is_loopback(client_host):
        # A model on the ERP host's own loopback is unreachable from another machine.
        logger.info("design: AI profile withheld, the endpoint is local to the ERP host")
        return None
    if loopback:
        protocol = "local"
    ttl = get_design_settings().ai_profile_ttl_seconds
    return {
        "protocol": protocol,
        "endpoint": endpoint,
        "model": model or ai_client.default_model_for(provider) or provider,
        "api_key": key or None,
        "local_only": loopback,
        "expires_at": (now_utc() + timedelta(seconds=ttl)).isoformat().replace("+00:00", "Z"),
    }
