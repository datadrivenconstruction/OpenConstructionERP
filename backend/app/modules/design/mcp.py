"""MCP entry point of the Design module (card R15): ``POST /api/v1/design/mcp``.

The ERP's own MCP server (``oe_mcp``) answers here with the same protocol layer, MCP-token auth, per-person switch,
rate limit and audit, plus the Design read tools. Write tools are the Design action specs in the assistant registry
(:mod:`.mcp_actions`): they store a pending proposal and nothing else; a person applies it in the Changes view.

Off unless ``OE_DESIGN_MCP_ENABLED`` is true (404 otherwise). No tool returns the ``ai`` block of the project context:
the person's AI key stays out of every response and every log line.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.dependencies import SessionDep

from .settings import get_design_settings

router = APIRouter()
MODULE = "oe_design"


# ── Read tools ──────────────────────────────────────────────────────────────


def _args_uuid(args: dict[str, Any], key: str) -> uuid.UUID:
    from app.modules.mcp.tools import ToolError

    try:
        return uuid.UUID(str(args.get(key)))
    except (TypeError, ValueError):
        raise ToolError("invalid_arguments", f"'{key}' must be a UUID.") from None


async def _project(session, args, principal):
    from app.modules.mcp.tools import require_project

    return await require_project(session, _args_uuid(args, "project_id"), principal)


async def _revision(session, args, principal):
    from app.modules.mcp.tools import ToolError, require_project

    from .models import DesignRevision
    from .revisions import VISIBLE

    rev = await session.get(DesignRevision, _args_uuid(args, "revision_id"))
    if rev is None or rev.status not in VISIBLE:
        raise ToolError("revision_not_found", "Revision not found or not accessible.")
    try:
        await require_project(session, rev.project_id, principal)
    except ToolError:
        raise ToolError("revision_not_found", "Revision not found or not accessible.") from None
    return rev


def _revision_row(rev) -> dict[str, Any]:
    return {
        "revision_id": str(rev.id),
        "number": rev.number,
        "status": rev.status,
        "parent_revision_id": str(rev.parent_id) if rev.parent_id else None,
        "source_kind": rev.source_kind,
        "depth_level": rev.depth_level or None,
        "message": rev.message,
        "brief_version": ((rev.manifest or {}).get("source") or {}).get("brief_version"),
        "created_at": rev.created_at.isoformat() if rev.created_at else None,
        "decided_at": rev.decided_at.isoformat() if rev.decided_at else None,
        "decision_comment": rev.decision_comment,
    }


async def _get_project(session, args, principal):
    from sqlalchemy import select

    from app.modules.mcp.tools import ToolOutcome

    from .brief import current_brief
    from .models import DesignRevision
    from .revisions import VISIBLE
    from .router import _can_accept, _can_publish, _lock_view

    project = await _project(session, args, principal)
    latest = (
        await session.execute(
            select(DesignRevision)
            .where(DesignRevision.project_id == project.id, DesignRevision.status.in_(VISIBLE))
            .order_by(DesignRevision.number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    lock = await _lock_view(session, project.id, principal.user_id)
    brief = await current_brief(session, project.id)
    prov = (brief or {}).get("provenance") or {}
    data = {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "country": project.country_code or None,
            "currency": project.currency or None,
            "locale": project.locale or "en",
        },
        "permissions": {
            "can_accept": await _can_accept(session, principal.user_id, project),
            "can_publish": await _can_publish(session, principal.user_id),
        },
        "lock": None if lock is None else lock.model_dump(mode="json"),
        "latest_revision": None if latest is None else _revision_row(latest),
        "brief": None
        if brief is None
        else {
            "version": brief.get("version"),
            "confirmed": sum(1 for p in prov.values() if (p or {}).get("status") == "confirmed"),
            "proposed": sum(1 for p in prov.values() if (p or {}).get("status") == "proposed"),
            "open_questions": len(brief.get("questions") or []),
        },
    }
    return ToolOutcome(data=data, summary=f"Design state of project {project.name}.", project_id=str(project.id))


async def _get_brief(session, args, principal):
    from sqlalchemy import select

    from app.modules.mcp.tools import ToolError, ToolOutcome

    from .brief import _head
    from .brief_models import DesignBriefVersion

    project = await _project(session, args, principal)
    head = await _head(session, project.id)
    if head is None:
        return ToolOutcome(
            data={"brief": None, "version": 0}, summary="No brief yet (version 0).", project_id=str(project.id)
        )
    version = args.get("version")
    doc = head.document
    if version is not None and version != head.version:
        if not isinstance(version, int) or isinstance(version, bool):
            raise ToolError("invalid_arguments", "'version' must be an integer.")
        row = (
            await session.execute(
                select(DesignBriefVersion).where(
                    DesignBriefVersion.brief_id == head.id, DesignBriefVersion.version == version
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ToolError("not_found", "No such brief version.")
        doc = row.document
    return ToolOutcome(
        data={"brief": doc, "version": doc.get("version")},
        summary=f"Brief version {doc.get('version')} (latest {head.version}).",
        project_id=str(project.id),
    )


async def _list_revisions(session, args, principal):
    from sqlalchemy import select

    from app.modules.mcp.tools import ToolOutcome

    from .models import DesignRevision
    from .revisions import VISIBLE

    project = await _project(session, args, principal)
    rows = (
        (
            await session.execute(
                select(DesignRevision)
                .where(DesignRevision.project_id == project.id, DesignRevision.status.in_(VISIBLE))
                .order_by(DesignRevision.number.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return ToolOutcome(
        data={"revisions": [_revision_row(r) for r in rows]},
        summary=f"{len(rows)} revision(s).",
        project_id=str(project.id),
    )


async def _get_job(session, args, principal):
    from sqlalchemy import select

    from app.modules.mcp.tools import ToolOutcome

    from . import jobs
    from .models import DesignJob

    project = await _project(session, args, principal)
    await jobs.sweep_stale(session, project.id)
    job = (
        await session.execute(
            select(DesignJob).where(DesignJob.project_id == project.id).order_by(DesignJob.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    _, reason = jobs.cli_state()
    return ToolOutcome(
        data={"enabled": reason is None, "reason": reason, "job": jobs.job_view(job) if job else None},
        summary="No generation yet." if job is None else f"Latest generation: {job.status}.",
        project_id=str(project.id),
    )


async def _revision_impact(session, args, principal):
    from app.modules.mcp.tools import ToolOutcome

    from . import estimate as est

    rev = await _revision(session, args, principal)
    data = await est.impact(session, rev)
    return ToolOutcome(
        data=json.loads(json.dumps(data, default=str)),
        summary=f"Estimate impact of R{rev.number}.",
        project_id=str(rev.project_id),
    )


async def _get_estimate(session, args, principal):
    from app.modules.mcp.tools import ToolOutcome

    from . import estimate as est

    project = await _project(session, args, principal)
    data = await est.summary(session, project.id)
    return ToolOutcome(
        data=json.loads(json.dumps(data, default=str)), summary="Model-driven estimate.", project_id=str(project.id)
    )


async def _extract_brief(session, args, principal):
    from app.modules.mcp.tools import ToolError, ToolOutcome

    from .brief_api import ExtractRequest, run_extraction

    project = await _project(session, args, principal)
    try:
        req = ExtractRequest(
            document_ids=args.get("document_ids") or [],
            text=args.get("text"),
            use_ai=bool(args.get("use_ai", False)),
            base=args.get("base"),
        )
        data = await run_extraction(session, project.id, principal.user_id, req)
    except HTTPException as exc:
        raise ToolError("unavailable", str(exc.detail)[:500]) from None
    except ValueError as exc:
        raise ToolError("invalid_arguments", str(exc)[:500]) from None
    data["status"] = "proposal"
    data["detail"] = "Nothing was saved. Propose values with propose_design_brief_values; a person applies them."
    return ToolOutcome(
        data=data, summary="Draft brief with citations and questions (not saved).", project_id=str(project.id)
    )


_PID = {"type": "string", "format": "uuid", "description": "Project UUID (see list_projects)."}
_RID = {"type": "string", "format": "uuid", "description": "Revision UUID (see design_list_revisions)."}


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def design_tools() -> tuple:
    from app.modules.mcp.tools import McpTool

    def tool(name, title, description, props, required, handler):
        return McpTool(
            name=name,
            title=title,
            description=description,
            input_schema=_schema(props, required),
            kind="read",
            handler=handler,
            modules=(MODULE,),
        )

    return (
        tool(
            "design_get_project",
            "Design state",
            "Design state of a project: permissions, editing lock, latest model revision, brief progress.",
            {"project_id": _PID},
            ["project_id"],
            _get_project,
        ),
        tool(
            "design_get_brief",
            "Design brief",
            "The project's design brief (ddc-brief/1) with provenance per value; optionally an older version.",
            {"project_id": _PID, "version": {"type": "integer", "minimum": 1}},
            ["project_id"],
            _get_brief,
        ),
        tool(
            "design_list_revisions",
            "Model revisions",
            "Model revisions of a project, newest first, with status (shared = awaiting a decision).",
            {"project_id": _PID},
            ["project_id"],
            _list_revisions,
        ),
        tool(
            "design_get_job",
            "Generation job",
            "Whether server generation is available and the latest generation job: status, progress, log tail, "
            "the revision it produced.",
            {"project_id": _PID},
            ["project_id"],
            _get_job,
        ),
        tool(
            "design_get_revision_impact",
            "Revision estimate impact",
            "What accepting a revision would change in the estimate: per-position quantity and cost deltas.",
            {"revision_id": _RID},
            ["revision_id"],
            _revision_impact,
        ),
        tool(
            "design_get_estimate",
            "Model-driven estimate",
            "The project's model-driven estimate: positions, totals, benchmark range, flags.",
            {"project_id": _PID},
            ["project_id"],
            _get_estimate,
        ),
        tool(
            "design_extract_brief_draft",
            "Extract brief draft",
            "Read attached project documents and/or a description and return a draft brief: each value cited, "
            "plus clarifying questions. Saves nothing. use_ai runs the person's configured AI model.",
            {
                "project_id": _PID,
                "document_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "text": {"type": "string", "maxLength": 200000},
                "use_ai": {"type": "boolean"},
                "base": {"type": "object"},
            },
            ["project_id"],
            _extract_brief,
        ),
    )


# ── Server ──────────────────────────────────────────────────────────────────


def _server_class():
    from app.modules.mcp.auth import tool_call_limiter
    from app.modules.mcp.protocol import INVALID_PARAMS, RATE_LIMITED, JsonRpcError
    from app.modules.mcp.service import McpServer, _tool_result
    from app.modules.mcp.tools import ToolError, ToolOutcome, tool_allowed

    class DesignMcpServer(McpServer):
        """The ERP MCP server with the Design read tools added; core tools and proposals behave as on /mcp."""

        def _design(self):
            return {t.name: t for t in design_tools()}

        async def tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
            core = await super().tools_list(params)
            extra = [t.definition() for t in self._design().values() if tool_allowed(t, self.principal)]
            return {"tools": [*core["tools"], *extra]}

        async def tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
            name = params.get("name")
            tool = self._design().get(name) if isinstance(name, str) else None
            if tool is None:
                return await super().tools_call(params)
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise JsonRpcError(INVALID_PARAMS, "'arguments' must be an object.")
            started = time.monotonic()
            if not tool_call_limiter.allow(self.principal.token_id, self.principal.rate_limit_per_minute):
                await self._audit(name, tool.kind, "rate_limited", started, arguments, error="rate_limited")
                raise JsonRpcError(
                    RATE_LIMITED,
                    "Rate limit exceeded.",
                    {"limit_per_minute": self.principal.rate_limit_per_minute, "retry_after_seconds": 60},
                )
            if not tool_allowed(tool, self.principal):
                msg = "The Design module is switched off on this server."
                await self._audit(name, tool.kind, "denied", started, arguments, error="module_disabled")
                return _tool_result(
                    ToolOutcome(
                        data={"error": "module_disabled", "message": msg},
                        summary=msg,
                        is_error=True,
                        error_code="module_disabled",
                    )
                )
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
                # The exception text may quote request data; only the tool name is logged.
                import logging

                logging.getLogger(__name__).error("design mcp: tool %s failed", name)
                outcome = ToolOutcome(
                    data={"error": "tool_failed", "message": "The tool failed on the server."},
                    summary="The tool failed on the server.",
                    is_error=True,
                    error_code="tool_failed",
                )
            denied = outcome.error_code in ("project_not_found", "revision_not_found")
            await self._audit(
                name,
                tool.kind,
                "denied" if denied else ("error" if outcome.is_error else "ok"),
                started,
                arguments,
                error=outcome.error_code,
                project_id=outcome.project_id,
            )
            return _tool_result(outcome)

    return DesignMcpServer


def mcp_available() -> bool:
    try:
        from app.modules.erp_chat.actions.registry import module_available

        return module_available("oe_mcp")
    except ImportError:
        return False


@router.post("/mcp", response_model=None, summary="MCP endpoint of the Design module")
async def design_mcp(request: Request, session: SessionDep) -> Response:
    """The ERP MCP endpoint plus Design tools; same token, switch, rate limit and audit as /api/v1/mcp."""
    if not get_design_settings().mcp_enabled or not mcp_available():
        raise HTTPException(404, "Not Found")
    from app.core import cost_scope, rls
    from app.core.tenant_scope import resolve_tenant_id
    from app.modules.mcp.auth import McpAuthError, resolve_principal
    from app.modules.mcp.protocol import INVALID_REQUEST, PARSE_ERROR, SUPPORTED_PROTOCOL_VERSIONS
    from app.modules.mcp.router import _AUTH_ERROR, MAX_BODY_BYTES, _origin_allowed, _rpc_error

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
    await session.commit()
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return _rpc_error(413, INVALID_REQUEST, "Request body too large.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _rpc_error(400, PARSE_ERROR, "Parse error.")

    tenant_token = rls.set_request_tenant(resolve_tenant_id({"sub": str(principal.user_id)}))
    owned = cost_scope.in_request()
    cost_token = cost_scope.bind_caller(principal.user_id)
    try:
        dispatcher = _server_class()(session, principal).dispatcher()
        answer = await dispatcher.handle_body(body)
    finally:
        if not owned:
            cost_scope.reset_caller(cost_token)
        rls.reset_request_tenant(tenant_token)
    if answer is None:
        return Response(status_code=202)
    status_code = 429 if dispatcher.rate_limited and not isinstance(answer, list) else 200
    return JSONResponse(status_code=status_code, content=answer)
