# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠MCP HTTP surface.

Mounted at ``/api/v1/mcp``:

    POST   /                 - the MCP endpoint (JSON-RPC, MCP token auth)
    GET    /                 - 405: this server offers no server-initiated stream
    GET    /settings/        - the caller's switch and rate limit
    PUT    /settings/        - change them
    GET    /tokens/          - the caller's MCP tokens
    POST   /tokens/          - create one (secret shown once)
    DELETE /tokens/{id}/     - revoke one
    GET    /calls/           - the caller's recent tool calls
    GET    /tools/           - every tool the server offers
    GET    /validation/      - the ``mcp`` rule set over the caller's setup
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.mcp.auth import McpAuthError, resolve_principal
from app.modules.mcp.protocol import (
    INVALID_REQUEST,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    error_message,
)
from app.modules.mcp.schemas import (
    McpSettingsResponse,
    McpSettingsUpdate,
    McpTokenCreate,
    McpTokenCreatedResponse,
    McpTokenListResponse,
    McpToolCallListResponse,
    McpToolInfo,
    McpValidationReport,
)
from app.modules.mcp.service import McpServer, McpService

logger = logging.getLogger(__name__)

router = APIRouter()

_AUTH_ERROR = -32000
_USE = Depends(RequirePermission("mcp.use"))
# A JSON-RPC batch of tool calls is small; 1 MB leaves room without letting a client fill memory.
MAX_BODY_BYTES = 1024 * 1024


def _origin_allowed(request: Request) -> bool:
    """Reject browser requests from foreign origins (DNS rebinding); clients without Origin pass."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    try:
        from app.config import get_settings

        if origin in get_settings().cors_origins:
            return True
    except Exception:
        logger.debug("mcp: could not read CORS origins", exc_info=True)
    return urlsplit(origin).netloc.lower() == (request.headers.get("host") or "").lower()


def _rpc_error(status_code: int, code: int, message: str, data: Any = None, **headers: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_message(None, code, message, data), headers=headers)


@router.post("", include_in_schema=False, response_model=None)
@router.post("/", response_model=None, summary="MCP endpoint (streamable HTTP, JSON responses)")
async def mcp_endpoint(request: Request, session: SessionDep) -> Response:
    """Answer one JSON-RPC message or batch from an MCP client authenticated by an MCP token."""
    if not _origin_allowed(request):
        return _rpc_error(403, INVALID_REQUEST, "Origin not allowed.")
    version = request.headers.get("mcp-protocol-version")
    if version and version not in SUPPORTED_PROTOCOL_VERSIONS:
        return _rpc_error(
            400, INVALID_REQUEST, f"Unsupported MCP-Protocol-Version: {version}", list(SUPPORTED_PROTOCOL_VERSIONS)
        )
    try:
        principal = await resolve_principal(request, session)
    except McpAuthError as exc:
        headers = {"WWW-Authenticate": 'Bearer realm="mcp"'} if exc.status_code == 401 else {}
        return _rpc_error(exc.status_code, _AUTH_ERROR, exc.message, {"code": exc.code}, **headers)
    # End the auth transaction so the next one starts with the owner bound as RLS tenant.
    await session.commit()

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return _rpc_error(413, INVALID_REQUEST, "Request body too large.")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return _rpc_error(413, INVALID_REQUEST, "Request body too large.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _rpc_error(400, PARSE_ERROR, "Parse error.")

    from app.core import cost_scope, rls
    from app.core.tenant_scope import resolve_tenant_id

    tenant_token = rls.set_request_tenant(resolve_tenant_id({"sub": str(principal.user_id)}))
    owned_by_middleware = cost_scope.in_request()
    cost_token = cost_scope.bind_caller(principal.user_id)
    try:
        dispatcher = McpServer(session, principal).dispatcher()
        answer = await dispatcher.handle_body(body)
    finally:
        if not owned_by_middleware:
            cost_scope.reset_caller(cost_token)
        rls.reset_request_tenant(tenant_token)

    if answer is None:
        return Response(status_code=202)
    status_code = 429 if dispatcher.rate_limited and not isinstance(answer, list) else 200
    return JSONResponse(status_code=status_code, content=answer)


@router.get("", include_in_schema=False, response_model=None)
@router.get("/", response_model=None, summary="Server-initiated stream (not offered)")
@router.delete("", include_in_schema=False, response_model=None)
@router.delete("/", response_model=None, include_in_schema=False)
async def mcp_no_stream() -> Response:
    """This server is stateless and never pushes messages, so GET and DELETE are 405."""
    return Response(status_code=405, headers={"Allow": "POST"})


# ── Settings surface ────────────────────────────────────────────────────────


@router.get("/settings/", response_model=McpSettingsResponse, dependencies=[_USE])
async def get_settings_route(user_id: CurrentUserId, session: SessionDep) -> McpSettingsResponse:
    """The caller's MCP switch and rate limit."""
    return await McpService(session).get_settings(uuid.UUID(user_id))


@router.put("/settings/", response_model=McpSettingsResponse, dependencies=[_USE])
async def update_settings_route(
    data: McpSettingsUpdate, user_id: CurrentUserId, session: SessionDep
) -> McpSettingsResponse:
    """Switch MCP on or off, or change the rate limit."""
    return await McpService(session).update_settings(uuid.UUID(user_id), data)


@router.get("/tokens/", response_model=McpTokenListResponse, dependencies=[_USE])
async def list_tokens_route(user_id: CurrentUserId, session: SessionDep) -> McpTokenListResponse:
    """The caller's MCP tokens, without secrets."""
    items = await McpService(session).list_tokens(uuid.UUID(user_id))
    return McpTokenListResponse(items=items, total=len(items), limit=len(items))


@router.post("/tokens/", response_model=McpTokenCreatedResponse, status_code=201, dependencies=[_USE])
async def create_token_route(
    data: McpTokenCreate, user_id: CurrentUserId, session: SessionDep
) -> McpTokenCreatedResponse:
    """Create an MCP token; the response is the only place the secret appears."""
    return await McpService(session).create_token(uuid.UUID(user_id), data)


@router.delete("/tokens/{token_id}/", status_code=204, response_model=None, dependencies=[_USE])
async def revoke_token_route(token_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> Response:
    """Revoke one of the caller's MCP tokens."""
    await McpService(session).revoke_token(uuid.UUID(user_id), token_id)
    return Response(status_code=204)


@router.get("/calls/", response_model=McpToolCallListResponse, dependencies=[_USE])
async def recent_calls_route(
    user_id: CurrentUserId,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> McpToolCallListResponse:
    """The caller's latest tool calls, newest first."""
    service = McpService(session)
    items = await service.recent_calls(uuid.UUID(user_id), limit=limit)
    total = await service.count_calls(uuid.UUID(user_id))
    return McpToolCallListResponse(items=items, total=total, limit=limit)


@router.get("/tools/", response_model=list[McpToolInfo], dependencies=[_USE])
async def tools_route(session: SessionDep) -> list[McpToolInfo]:
    """Every tool this server offers and whether its module is on."""
    return McpService(session).tool_catalogue()


@router.get("/validation/", response_model=McpValidationReport, dependencies=[_USE])
async def validation_route(user_id: CurrentUserId, session: SessionDep) -> McpValidationReport:
    """Validation findings for the caller's MCP setup."""
    return await McpService(session).validate(uuid.UUID(user_id))
