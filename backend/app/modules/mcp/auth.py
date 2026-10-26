# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who is calling the MCP endpoint, and may they call it now.

An MCP token is an ordinary row of ``oe_users_api_key`` (same SHA-256 hash,
same expiry and revocation, same ``last_used_at``) whose declared scopes carry
``mcp.access``. Two consequences follow from the existing key semantics in
:func:`app.dependencies.key_scopes_allow`:

* a general-purpose key (no declared scopes) cannot reach MCP, because the
  endpoint checks with ``require_declared=True``;
* an MCP token cannot reach any REST route gated by
  :class:`app.dependencies.RequirePermissionOrApiKey`, because its declared
  list names none of those permissions.

Clients send the token either as ``X-API-Key`` or as ``Authorization: Bearer``;
most MCP clients only let a user configure the latter.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass, field

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import RateLimiter
from app.dependencies import key_scopes_allow

SCOPE_ACCESS = "mcp.access"
SCOPE_PROPOSE = "mcp.propose"
TOKEN_PREFIX = "oe_"


class McpAuthError(Exception):
    """The request carries no usable MCP credential (HTTP 401) or may not use MCP (HTTP 403)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class McpPrincipal:
    """The person behind a valid MCP token, with the token's own identity and scopes."""

    user_id: uuid.UUID
    role: str
    token_id: uuid.UUID
    token_prefix: str
    scopes: tuple[str, ...] = field(default_factory=tuple)
    rate_limit_per_minute: int = 60

    @property
    def can_propose(self) -> bool:
        """Whether the token was issued with the proposal scope."""
        return key_scopes_allow(self.scopes, SCOPE_PROPOSE, require_declared=True)


def extract_token(request: Request) -> str | None:
    """The raw token from ``X-API-Key`` or a bearer header that looks like an API key."""
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    auth = request.headers.get("authorization") or ""
    scheme, _, value = auth.partition(" ")
    value = value.strip()
    # A JWT never starts with the API-key prefix, so the two cannot be confused.
    if scheme.lower() == "bearer" and value.startswith(TOKEN_PREFIX):
        return value
    return None


async def resolve_principal(request: Request, session: AsyncSession) -> McpPrincipal:
    """Resolve the MCP caller or raise :class:`McpAuthError`.

    Order matters for what the client learns: an unknown token is 401 whatever
    else is true, a valid key without the MCP scope is 403, and a valid MCP
    token whose owner has switched MCP off is 403 with its own code so the
    client can tell the person what to do.
    """
    from app.modules.mcp.repository import McpSettingsRepository
    from app.modules.users.models import User
    from app.modules.users.repository import APIKeyRepository

    raw = extract_token(request)
    if not raw:
        raise McpAuthError(401, "missing_token", "Send an MCP token as a Bearer token or X-API-Key header.")
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    keys = APIKeyRepository(session)
    api_key = await keys.get_by_hash(key_hash)
    if api_key is None:
        raise McpAuthError(401, "invalid_token", "The token is unknown, revoked or expired.")
    scopes = tuple(api_key.permissions or ())
    if not key_scopes_allow(scopes, SCOPE_ACCESS, require_declared=True):
        raise McpAuthError(403, "not_an_mcp_token", "This API key was not issued for MCP.")
    user = await session.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise McpAuthError(401, "inactive_user", "The token's owner does not exist or is inactive.")
    settings = await McpSettingsRepository(session).get(user.id)
    if settings is None or not settings.enabled:
        raise McpAuthError(403, "mcp_disabled", "MCP access is switched off in this person's settings.")
    await keys.update_last_used(api_key.id)
    return McpPrincipal(
        user_id=user.id,
        role=str(getattr(user, "role", "") or ""),
        token_id=api_key.id,
        token_prefix=api_key.key_prefix,
        scopes=scopes,
        rate_limit_per_minute=int(settings.rate_limit_per_minute),
    )


class TokenRateLimiter:
    """Sliding-window budget per token, reusing the platform's in-process limiter.

    One :class:`RateLimiter` per distinct limit value, keyed by token id, so a
    person who changes their limit gets the new budget on the next call.
    """

    def __init__(self) -> None:
        self._by_limit: dict[int, RateLimiter] = {}
        self._lock = threading.Lock()

    def allow(self, token_id: uuid.UUID, per_minute: int) -> bool:
        """Count one call against the token; False when the budget is spent."""
        limit = max(1, int(per_minute))
        with self._lock:
            limiter = self._by_limit.get(limit)
            if limiter is None:
                limiter = RateLimiter(max_requests=limit, window_seconds=60)
                self._by_limit[limit] = limiter
        allowed, _remaining = limiter.is_allowed(str(token_id))
        return allowed

    def reset(self) -> None:
        """Forget every window (tests)."""
        with self._lock:
            self._by_limit.clear()


tool_call_limiter = TokenRateLimiter()
