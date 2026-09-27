# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Actor / capture-context middleware for Epic H universal audit trail.

Sets the per-request :class:`~app.core.audit_log.AuditContext` on a
ContextVar so :func:`app.core.audit_log.log_activity` can persist the
peer IP, User-Agent, and correlation ID without service-layer callers
having to thread the values manually.

Identity (``actor_id`` / ``tenant_id``) is **not** resolved here -
authentication happens later in the request lifecycle via the
``get_current_user_id`` dependency. The dependency
:func:`app.dependencies.audit_context_dep` enriches the same ContextVar
with the resolved IDs once the request handler runs. The middleware
covers everything that does NOT require auth (peer IP, UA, request-id),
which is enough for the unauthenticated paths (CSRF probe, register,
login) so even those leave a row in ``oe_activity_log``.

Order in the middleware stack: this MUST be installed **after**
:class:`app.middleware.request_id.RequestIDMiddleware` so the
correlation ID is already on the request-id ContextVar when we read it
back here.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.audit_log import (
    AuditContext,
    reset_audit_context,
    set_audit_context,
)
from app.middleware.request_id import get_request_id

logger = logging.getLogger(__name__)

# Soft cap on UA length captured into the ContextVar. The DB column also
# caps at 500 but trimming early keeps the in-memory snapshot small.
_MAX_UA_LEN = 500


def _client_ip(request: Request) -> str | None:
    """Best-effort peer IP extraction.

    Honours ``X-Forwarded-For`` and ``X-Real-IP`` only when the direct peer
    is a configured trusted proxy (see ``app.core.rate_limiter.client_ip``),
    otherwise records the ASGI peer, so an audit row cannot be stamped with
    an address the caller made up. Returns ``None`` when no value is
    available.
    """
    from app.core.rate_limiter import client_ip

    ip = client_ip(request)
    return ip[:45] if ip else None  # 45 = IPv6 max length


class ActorContextMiddleware(BaseHTTPMiddleware):
    """Populate the per-request AuditContext ContextVar.

    Identity fields (``actor_id``, ``tenant_id``) stay ``None`` here -
    they are filled in by
    :func:`app.dependencies.audit_context_dep` once auth has resolved
    the user. Capture fields (``ip_address``, ``user_agent``,
    ``request_id``) are written up-front so even unauthenticated
    handlers (or 401-rejected requests) still leave a trail.

    Failure to set the context never breaks the request - the
    ContextVar is best-effort capture, not part of the request contract.
    """

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        try:
            ip = _client_ip(request)
            ua_raw = request.headers.get("user-agent")
            ua = ua_raw[:_MAX_UA_LEN] if ua_raw else None
            rid = get_request_id()
        except Exception:  # pragma: no cover - defensive
            logger.exception("actor_context: capture failed; continuing without context")
            return await call_next(request)

        ctx = AuditContext(
            actor_id=None,  # filled in by audit_context_dep after auth
            tenant_id=None,
            ip_address=ip,
            user_agent=ua,
            request_id=rid,
        )
        token = set_audit_context(ctx)
        try:
            response: Response = await call_next(request)
        finally:
            reset_audit_context(token)
        return response
