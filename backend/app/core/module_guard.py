# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""API route guard for modules a tenant's solution packages hide.

``/api/v1/<module>/...`` answers 403 ``module_disabled`` when the caller's
packages switched that module off. Nothing is deleted: switching the module
back on restores access to the same data. Tenants without packages, anonymous
calls and non-gateable modules pass through untouched (fail-open).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.solution_packages import gateable_modules, is_blocked

logger = logging.getLogger(__name__)

_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def invalidate_user(user_id: str) -> None:
    """Drop the cached package state of one user after a write."""
    _cache.pop(str(user_id), None)


def module_from_path(path: str) -> str | None:
    """The gateable module a ``/api/v1/<segment>/`` path belongs to, or ``None``."""
    if not path.startswith("/api/v1/"):
        return None
    segment = path[len("/api/v1/") :].split("/", 1)[0].replace("-", "_")
    return segment if segment in gateable_modules() else None


def _user_id_from_scope(scope: Scope) -> str | None:
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization", b"").decode("latin-1")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        from app.config import get_settings
        from app.core.jwt_keys import decode_jwt

        payload = decode_jwt(auth[7:].strip(), get_settings())
    except Exception:  # an invalid token is the auth layer's to answer, not ours
        return None
    sub = payload.get("tenant_id") or payload.get("sub")
    return str(sub) if sub else None


async def _load_metadata(user_id: str) -> dict[str, Any] | None:
    hit = _cache.get(user_id)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    try:
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as session:
            meta = (await session.execute(select(User.metadata_).where(User.id == uuid.UUID(user_id)))).scalar()
    except Exception:
        logger.debug("module guard: metadata lookup failed, passing through", exc_info=True)
        return None
    _cache[user_id] = (now + _TTL_SECONDS, meta)
    return meta


class ModuleGuardMiddleware:
    """Pure ASGI middleware; costs nothing on paths outside gateable modules."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            module = module_from_path(scope.get("path", ""))
            if module is not None:
                user_id = _user_id_from_scope(scope)
                if user_id is not None and is_blocked(await _load_metadata(user_id), module):
                    body = json.dumps({"detail": "module_disabled", "module": module}).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 403,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)
