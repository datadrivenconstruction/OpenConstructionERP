# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MCP business logic: the protocol methods for a token caller, and the settings surface for a signed-in person."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.modules.mcp.auth import SCOPE_ACCESS, SCOPE_PROPOSE, McpPrincipal, tool_call_limiter
from app.modules.mcp.models import DEFAULT_RATE_LIMIT_PER_MINUTE
from app.modules.mcp.protocol import (
    INVALID_PARAMS,
    RATE_LIMITED,
    SUPPORTED_PROTOCOL_VERSIONS,
    Dispatcher,
    JsonRpcError,
    negotiate_version,
)
from app.modules.mcp.repository import (
    MCP_AUDIT_ENTITY,
    MCP_AUDIT_MODULE,
    McpCallLogRepository,
    McpSettingsRepository,
    McpTokenRepository,
    is_mcp_key,
)
from app.modules.mcp.schemas import (
    McpSettingsResponse,
    McpSettingsUpdate,
    McpTokenCreate,
    McpTokenCreatedResponse,
    McpTokenResponse,
    McpToolCallResponse,
    McpToolInfo,
    McpValidationFinding,
    McpValidationReport,
)
from app.modules.mcp.tools import (
    ToolError,
    ToolOutcome,
    all_tools,
    find_tool,
    tool_allowed,
    tool_is_available,
    tools_for,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "openconstructionerp"
SERVER_TITLE = "OpenConstructionERP"
MAX_TEXT_CHARS = 60_000
SERVER_INSTRUCTIONS = (
    "Construction estimating and project data of the signed-in person. Start with list_projects, then pass a "
    "project_id to the other read tools. Money values are decimal strings in the project currency. Tools named "
    "propose_* never change data: they create a proposal the person reviews and applies in the app, so always "
    "give an honest confidence between 0 and 1 and a one-line rationale."
)


def _app_version() -> str:
    try:
        from app.config import get_settings

        return str(get_settings().app_version)
    except Exception:
        return "0"


def _tool_result(outcome: ToolOutcome) -> dict[str, Any]:
    """MCP ``CallToolResult``: a text block for every client, structured content for those that read it."""
    body = json.dumps(outcome.data, ensure_ascii=False, default=str)
    text = f"{outcome.summary}\n{body}" if outcome.summary else body
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n[truncated: narrow the request with limit or filters]"
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": outcome.data,
        "isError": outcome.is_error,
    }


class McpServer:
    """The protocol methods for one authenticated MCP request."""

    def __init__(self, session: AsyncSession, principal: McpPrincipal) -> None:
        self.session = session
        self.principal = principal

    def dispatcher(self) -> Dispatcher:
        """A dispatcher bound to this caller."""
        return Dispatcher(
            {
                "initialize": self.initialize,
                "ping": self.ping,
                "tools/list": self.tools_list,
                "tools/call": self.tools_call,
            }
        )

    async def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Version negotiation and capabilities (tools only)."""
        return {
            "protocolVersion": negotiate_version(params.get("protocolVersion")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": SERVER_TITLE, "version": _app_version()},
            "instructions": SERVER_INSTRUCTIONS,
        }

    async def ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Liveness check."""
        return {}

    async def tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """The tools this caller may use now (one page; the list is short)."""
        return {"tools": [t.definition() for t in tools_for(self.principal)]}

    async def tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run one tool under the caller's rights, rate limit it and audit it."""
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise JsonRpcError(INVALID_PARAMS, "'name' is required.")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "'arguments' must be an object.")
        tool = find_tool(name)
        if tool is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {name}")

        started = time.monotonic()
        if not tool_call_limiter.allow(self.principal.token_id, self.principal.rate_limit_per_minute):
            await self._audit(name, tool.kind, "rate_limited", started, arguments, error="rate_limited")
            raise JsonRpcError(
                RATE_LIMITED,
                "Rate limit exceeded.",
                {"limit_per_minute": self.principal.rate_limit_per_minute, "retry_after_seconds": 60},
            )
        if not tool_allowed(tool, self.principal):
            code = "proposals_not_allowed" if tool.kind == "propose" and not self.principal.can_propose else None
            if code is None:
                code = "module_disabled" if not tool_is_available(tool) else "permission_denied"
            message = {
                "proposals_not_allowed": "This token may only read. Create a token that may propose changes.",
                "module_disabled": "The module behind this tool is switched off on this server.",
                "permission_denied": "Your role does not allow this tool.",
            }[code]
            outcome = ToolOutcome(
                data={"error": code, "message": message}, summary=message, is_error=True, error_code=code
            )
            await self._audit(name, tool.kind, "denied", started, arguments, error=code)
            return _tool_result(outcome)

        try:
            async with self.session.begin_nested():
                outcome = await tool.handler(self.session, arguments, self.principal)
        except ToolError as exc:
            outcome = ToolOutcome(
                data={"error": exc.code, "message": exc.message},
                summary=exc.message,
                is_error=True,
                error_code=exc.code,
            )
        except Exception:
            logger.exception("mcp: tool %s failed", name)
            outcome = ToolOutcome(
                data={"error": "tool_failed", "message": "The tool failed on the server."},
                summary="The tool failed on the server.",
                is_error=True,
                error_code="tool_failed",
            )
        result_outcome = "denied" if outcome.error_code in ("project_not_found", "permission_denied") else None
        await self._audit(
            name,
            tool.kind,
            result_outcome or ("error" if outcome.is_error else "ok"),
            started,
            arguments,
            error=outcome.error_code,
            project_id=outcome.project_id,
            action_id=outcome.action_id,
        )
        return _tool_result(outcome)

    async def _audit(
        self,
        tool: str,
        kind: str,
        outcome: str,
        started: float,
        arguments: dict[str, Any],
        *,
        error: str | None = None,
        project_id: str | None = None,
        action_id: str | None = None,
    ) -> None:
        """One ``oe_activity_log`` row per call; argument values are not stored, only their names."""
        if project_id is None and isinstance(arguments.get("project_id"), str):
            project_id = arguments["project_id"][:64]
        await log_activity(
            self.session,
            actor_id=self.principal.user_id,
            entity_type=MCP_AUDIT_ENTITY,
            entity_id=str(self.principal.token_id),
            action="tool_call",
            to_status=outcome,
            module=MCP_AUDIT_MODULE,
            metadata={
                "tool": tool,
                "kind": kind,
                "outcome": outcome,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "token_prefix": self.principal.token_prefix,
                "project_id": project_id,
                "action_id": action_id,
                "error": error,
                "argument_names": sorted(str(k) for k in arguments)[:20],
            },
        )


# ── Settings surface (signed-in person) ─────────────────────────────────────


def _token_dto(key: Any) -> McpTokenResponse:
    return McpTokenResponse(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        is_active=bool(key.is_active),
        can_propose=SCOPE_PROPOSE in list(key.permissions or []),
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        created_at=key.created_at,
    )


class McpService:
    """Settings, tokens, call log and validation for the signed-in person."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings_repo = McpSettingsRepository(session)
        self.token_repo = McpTokenRepository(session)
        self.call_repo = McpCallLogRepository(session)

    async def get_settings(self, user_id: uuid.UUID) -> McpSettingsResponse:
        """The caller's settings; disabled defaults when no row exists yet."""
        row = await self.settings_repo.get(user_id)
        return McpSettingsResponse(
            enabled=bool(row.enabled) if row else False,
            rate_limit_per_minute=int(row.rate_limit_per_minute) if row else DEFAULT_RATE_LIMIT_PER_MINUTE,
            protocol_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        )

    async def update_settings(self, user_id: uuid.UUID, data: McpSettingsUpdate) -> McpSettingsResponse:
        """Switch MCP on or off, or change the per-minute budget."""
        row = await self.settings_repo.get_or_create(user_id)
        before = {"enabled": row.enabled, "rate_limit_per_minute": row.rate_limit_per_minute}
        if data.enabled is not None:
            row.enabled = data.enabled
        if data.rate_limit_per_minute is not None:
            row.rate_limit_per_minute = data.rate_limit_per_minute
        await self.session.flush()
        after = {"enabled": row.enabled, "rate_limit_per_minute": row.rate_limit_per_minute}
        if after != before:
            await log_activity(
                self.session,
                actor_id=user_id,
                entity_type="mcp_settings",
                entity_id=str(row.id),
                action="updated",
                module=MCP_AUDIT_MODULE,
                before_state=before,
                after_state=after,
            )
        return await self.get_settings(user_id)

    async def list_tokens(self, user_id: uuid.UUID) -> list[McpTokenResponse]:
        """The caller's MCP tokens (never the secret)."""
        return [_token_dto(k) for k in await self.token_repo.list_for_user(user_id, SCOPE_ACCESS)]

    async def create_token(self, user_id: uuid.UUID, data: McpTokenCreate) -> McpTokenCreatedResponse:
        """Issue an MCP token through the platform's API-key service; the secret is returned once."""
        from app.config import get_settings
        from app.modules.users.schemas import APIKeyCreate
        from app.modules.users.service import UserService

        scopes = [SCOPE_ACCESS] + ([SCOPE_PROPOSE] if data.can_propose else [])
        created = await UserService(self.session, get_settings()).create_api_key(
            user_id,
            APIKeyCreate(
                name=data.name,
                description="MCP client token",
                expires_in_days=data.expires_in_days,
                permissions=scopes,
            ),
        )
        await log_activity(
            self.session,
            actor_id=user_id,
            entity_type="mcp_token",
            entity_id=str(created.id),
            action="created",
            module=MCP_AUDIT_MODULE,
            metadata={"key_prefix": created.key_prefix, "scopes": scopes, "expires_at": str(created.expires_at)},
        )
        return McpTokenCreatedResponse(
            id=created.id,
            name=created.name,
            key_prefix=created.key_prefix,
            is_active=created.is_active,
            can_propose=data.can_propose,
            expires_at=created.expires_at,
            last_used_at=created.last_used_at,
            created_at=created.created_at,
            token=created.key,
        )

    async def revoke_token(self, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
        """Deactivate one of the caller's MCP tokens; another person's id or a non-MCP key is 404."""
        from app.modules.users.repository import APIKeyRepository

        repo = APIKeyRepository(self.session)
        key = await repo.get_by_id(token_id)
        if key is None or key.user_id != user_id or not is_mcp_key(key, SCOPE_ACCESS):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP token not found")
        await repo.deactivate(token_id)
        await log_activity(
            self.session,
            actor_id=user_id,
            entity_type="mcp_token",
            entity_id=str(token_id),
            action="revoked",
            module=MCP_AUDIT_MODULE,
            metadata={"key_prefix": key.key_prefix},
        )

    async def recent_calls(self, user_id: uuid.UUID, *, limit: int = 50) -> list[McpToolCallResponse]:
        """The caller's latest audited tool calls."""
        out = []
        for row in await self.call_repo.recent_for_user(user_id, limit=limit):
            meta = row.metadata_ or {}
            outcome = str(meta.get("outcome") or row.to_status or "ok")
            out.append(
                McpToolCallResponse(
                    id=row.id,
                    tool=str(meta.get("tool") or ""),
                    kind=meta.get("kind") if meta.get("kind") in ("read", "propose") else None,
                    outcome=outcome if outcome in ("ok", "error", "denied", "rate_limited") else "error",
                    duration_ms=meta.get("duration_ms"),
                    project_id=meta.get("project_id"),
                    token_prefix=meta.get("token_prefix"),
                    action_id=meta.get("action_id"),
                    error=meta.get("error"),
                    created_at=row.created_at,
                )
            )
        return out

    def tool_catalogue(self) -> list[McpToolInfo]:
        """Every tool this server offers, for the settings page."""
        return [
            McpToolInfo(
                name=t.name,
                kind=t.kind,
                description=t.description,
                permission=t.permissions[0] if t.permissions else None,
                available=tool_is_available(t),
            )
            for t in all_tools()
        ]

    async def validate(self, user_id: uuid.UUID) -> McpValidationReport:
        """Run the ``mcp`` rule set over the caller's settings, tokens and recent calls."""
        from app.core.validation.engine import validation_engine
        from app.modules.mcp.validators import MCP_RULE_SET

        now = datetime.now(UTC)
        settings = await self.get_settings(user_id)
        tokens = await self.list_tokens(user_id)
        denied = await self.call_repo.count_outcome_since(user_id, "denied", now - timedelta(hours=24))
        report = await validation_engine.validate(
            data={"now": now, "settings": settings, "tokens": tokens, "denied_last_24h": denied},
            rule_sets=[MCP_RULE_SET],
            target_type="mcp",
            target_id=str(user_id),
        )
        findings = [
            McpValidationFinding(
                rule_id=r.rule_id,
                severity=str(r.severity),
                key=f"mcp.validation.{r.rule_id.removeprefix('mcp.')}",
                message=r.message,
                params=r.details,
                element_ref=r.element_ref,
            )
            for r in report.results
            if not r.passed
        ]
        return McpValidationReport(status=report.status.value, score=report.score, findings=findings)
