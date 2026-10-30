# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Confine module page tokens to their module, and let sandboxed module pages call it.

A hosted module page runs in an iframe without ``allow-same-origin``, so it has
an opaque origin: no shell cookies, no shell storage, and its requests carry
``Origin: null``. The shell hands it a short-lived token whose ``oe_mod`` claim
names the module. This middleware refuses such a token on any path outside
that module's API, and answers CORS for ``Origin: null`` only on the API of
modules that declared a hosted page. Bearer tokens, never cookies, so allowing
the null origin there grants nothing without the token.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

SCOPE_CLAIM = "oe_mod"


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


def _under(path: str, prefixes: list[str] | tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def token_scope(authorization: str | None) -> str | None:
    """The module a bearer token is confined to, or ``None`` for a normal token or none."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        from jose import jwt

        claims: dict[str, Any] = jwt.get_unverified_claims(authorization[7:].strip())
    except Exception:
        return None
    value = claims.get(SCOPE_CLAIM)
    # The signature is checked later by the normal auth dependency; a forged
    # claim only narrows what a token may reach, never widens it.
    return value if isinstance(value, str) and value else ("" if SCOPE_CLAIM in claims else None)


class ModuleUiScopeMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from app.core.module_package import hosted_prefixes, module_api_prefixes

        path: str = scope.get("path", "")
        module = token_scope(_header(scope, b"authorization"))
        if module is not None and (not module or not _under(path, module_api_prefixes(module))):
            await _send_plain(send, 403, b'{"detail":"This token is limited to one module page."}')
            return

        null_origin = _header(scope, b"origin") == "null" and path.startswith("/api/v1/")
        if not null_origin or not _under(path, hosted_prefixes()):
            await self.app(scope, receive, send)
            return

        cors = [
            (b"access-control-allow-origin", b"null"),
            (b"access-control-allow-headers", b"authorization, content-type, accept-language"),
            (b"access-control-allow-methods", b"GET, POST, PUT, PATCH, DELETE"),
            (b"access-control-max-age", b"600"),
            (b"vary", b"Origin"),
        ]
        if scope.get("method") == "OPTIONS" and _header(scope, b"access-control-request-method"):
            await send({"type": "http.response.start", "status": 204, "headers": cors})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if not k.startswith(b"access-control-")]
                message = {**message, "headers": headers + cors}
            await send(message)

        await self.app(scope, receive, send_with_cors)


async def _send_plain(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
