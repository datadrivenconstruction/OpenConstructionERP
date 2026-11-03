# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data feed HTTP surface, mounted at ``/api/v1/bi-feed`` (and ``/api/v1/bi_feed``).

    GET /feeds                    - the feeds the caller can read, with column lists and row counts
    GET /feeds/{id}.csv           - one feed as CSV (UTF-8 with BOM, opens in Excel)
    GET /feeds/{id}.parquet       - the same as Parquet with exact decimals
    GET /feeds/{id}.json          - the same as JSON
    GET /sql-status               - whether the opt-in PostgreSQL schema exists

Query parameters of a feed file: ``project_id``, ``updated_since``, ``limit`` (at most 50000),
``offset`` and ``after``. Everything is read-only; no write verb is registered.

Callers: a Bearer token, or an ``X-API-Key`` whose permissions list contains ``bi:read``.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.dependencies import SessionDep, get_optional_user_payload, key_scopes_allow
from app.modules.bi_feed.schemas import FeedInfo, SqlAccessStatus
from app.modules.bi_feed.service import BiFeedService
from app.modules.bi_feed.validators import BiFeedError, parse_params

logger = logging.getLogger(__name__)

router = APIRouter()

SCOPE_READ = "bi:read"


@dataclass(frozen=True)
class FeedCaller:
    """Who is reading: the user id and the role that decides which feeds are open."""

    user_id: str
    role: str


async def bi_feed_caller(
    request: Request,
    session: SessionDep,
    payload: Annotated[dict[str, Any] | None, Depends(get_optional_user_payload)],
) -> AsyncIterator[FeedCaller]:
    """The id of the person reading: the bearer token's subject, or the owner of a ``bi:read`` key.

    A key authenticates as its owner and is bound to the owner's tenant for the request, so it
    reaches exactly what the owner reaches. A key that declares no scopes is refused: feeds are
    opt-in per key.
    """
    if payload is not None:
        yield FeedCaller(str(payload["sub"]), str(payload.get("role") or ""))
        return
    raw = request.headers.get("x-api-key")
    if not raw:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "ApiKey"})
    from app.core import rls
    from app.core.tenant_scope import resolve_tenant_id
    from app.modules.users.models import User
    from app.modules.users.repository import APIKeyRepository

    keys = APIKeyRepository(session)
    api_key = await keys.get_by_hash(hashlib.sha256(raw.encode()).hexdigest())
    if api_key is None:
        raise HTTPException(401, "Invalid API key", headers={"WWW-Authenticate": "ApiKey"})
    user = await session.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "User not found or inactive")
    if not key_scopes_allow(list(api_key.permissions or []), SCOPE_READ, require_declared=True):
        raise HTTPException(403, f"API key does not carry permission: {SCOPE_READ}")
    await keys.update_last_used(api_key.id)
    token = rls.set_request_tenant(resolve_tenant_id({"sub": str(user.id)}))
    try:
        yield FeedCaller(str(user.id), str(user.role or ""))
    finally:
        rls.reset_request_tenant(token)


Caller = Annotated[FeedCaller, Depends(bi_feed_caller, scope="function")]


def _error(exc: BiFeedError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": {"code": exc.code, "message": exc.message}})


@router.get("/feeds", response_model=list[FeedInfo])
async def list_feeds(session: SessionDep, caller: Caller) -> Any:
    """The feeds the caller can read."""
    try:
        return await BiFeedService(session).list_feeds(caller.user_id, caller.role)
    except BiFeedError as exc:
        return _error(exc)


@router.get("/sql-status", response_model=SqlAccessStatus)
async def sql_status(session: SessionDep, caller: Caller) -> Any:  # noqa: ARG001 - authentication only
    """Whether SQL access (the ``oe_bi`` schema) has been enabled on this instance."""
    return await BiFeedService(session).sql_status()


async def _serve(request: Request, session: Any, caller: FeedCaller, feed_id: str, fmt: str) -> Response:
    try:
        params = parse_params(dict(request.query_params))
        result = await BiFeedService(session).export(feed_id, fmt, caller.user_id, caller.role, params)
    except BiFeedError as exc:
        return _error(exc)
    headers = {
        "X-Total-Count": str(result.total),
        "Cache-Control": "no-store",
        "Content-Disposition": f'inline; filename="{feed_id}.{fmt}"',
        "Access-Control-Expose-Headers": "X-Total-Count, X-Next-Offset, X-Next-After",
    }
    if result.next_offset is not None:
        headers["X-Next-Offset"] = str(result.next_offset)
    if result.next_after is not None:
        headers["X-Next-After"] = result.next_after
    return Response(content=result.body, media_type=result.media_type, headers=headers)


@router.get("/feeds/{feed_id}.csv")
async def feed_csv(feed_id: str, request: Request, session: SessionDep, caller: Caller) -> Response:
    """A feed as CSV."""
    return await _serve(request, session, caller, feed_id, "csv")


@router.get("/feeds/{feed_id}.parquet")
async def feed_parquet(feed_id: str, request: Request, session: SessionDep, caller: Caller) -> Response:
    """A feed as Parquet."""
    return await _serve(request, session, caller, feed_id, "parquet")


@router.get("/feeds/{feed_id}.json")
async def feed_json(feed_id: str, request: Request, session: SessionDep, caller: Caller) -> Response:
    """A feed as JSON."""
    return await _serve(request, session, caller, feed_id, "json")
