# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The tools an MCP client may call.

Two kinds, and nothing in between:

* **read** tools answer from the owner's data under the owner's rights: the
  owner's role must carry the module's ``*.read`` permission, the module must
  be enabled, and every project-scoped tool checks project access (404 posture,
  so a client cannot probe which ids exist). Where the in-app assistant already
  has a read handler that fits, it is reused as is.
* **propose** tools are the assistant's ``propose_*`` actions from
  :mod:`app.modules.erp_chat.actions.registry`. They store a proposal with the
  client's confidence and rationale and write nothing else; a person applies it
  in the Changes view under the record's own REST gates.

A tool returns a :class:`ToolOutcome`; the protocol layer turns it into MCP
``content`` and ``structuredContent``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp.auth import McpPrincipal

logger = logging.getLogger(__name__)

ToolKind = Literal["read", "propose"]


class ToolError(Exception):
    """A tool-level failure the client should read and act on (MCP ``isError``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolOutcome:
    """What a tool produced: structured data, a one-line summary, and what it touched."""

    data: dict[str, Any]
    summary: str
    is_error: bool = False
    error_code: str | None = None
    project_id: str | None = None
    action_id: str | None = None


Handler = Callable[[AsyncSession, dict[str, Any], McpPrincipal], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class McpTool:
    """One tool: its MCP definition plus who may call it."""

    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    kind: ToolKind
    handler: Handler
    permissions: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    annotations: dict[str, Any] = field(default_factory=dict)

    def definition(self) -> dict[str, Any]:
        """The tool as ``tools/list`` returns it."""
        read = self.kind == "read"
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": read,
                "destructiveHint": False,
                "idempotentHint": read,
                "openWorldHint": False,
                **self.annotations,
            },
        }


# ── Argument helpers ────────────────────────────────────────────────────────

_PROJECT_ID = {"type": "string", "format": "uuid", "description": "UUID of the project (see list_projects)."}


def _uuid_arg(args: dict[str, Any], key: str, *, required: bool = True) -> uuid.UUID | None:
    raw = args.get(key)
    if raw in (None, ""):
        if required:
            raise ToolError("invalid_arguments", f"'{key}' is required.")
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError, AttributeError):
        raise ToolError("invalid_arguments", f"'{key}' must be a UUID.") from None


def _int_arg(args: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    raw = args.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ToolError("invalid_arguments", f"'{key}' must be an integer.") from None
    return max(lo, min(value, hi))


def _str_arg(args: dict[str, Any], key: str, max_length: int = 200) -> str | None:
    raw = args.get(key)
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise ToolError("invalid_arguments", f"'{key}' must be a string.")
    return raw.strip()[:max_length] or None


def _money(value: Any) -> str | None:
    """Decimal money as a JSON string, never a float."""
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except (ArithmeticError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


async def require_project(session: AsyncSession, project_id: uuid.UUID, principal: McpPrincipal) -> Any:
    """The project row when the owner may open it; ``project_not_found`` otherwise (missing or foreign)."""
    from app.dependencies import verify_project_access
    from app.modules.projects.models import Project

    try:
        await verify_project_access(project_id, str(principal.user_id), session)
    except HTTPException:
        raise ToolError("project_not_found", "Project not found or not accessible.") from None
    project = await session.get(Project, project_id)
    if project is None:
        raise ToolError("project_not_found", "Project not found or not accessible.")
    return project


def _from_chat_result(result: dict[str, Any], project_id: str | None = None) -> ToolOutcome:
    """Adapt an in-app assistant read handler's ``{renderer, data, summary}`` result."""
    data = result.get("data") or {}
    if result.get("renderer") == "error":
        message = str(data.get("error") or result.get("summary") or "Tool failed.")
        code = "project_not_found" if ("not found" in message or "Access denied" in message) else "tool_failed"
        if code == "project_not_found":
            message = "Project not found or not accessible."
        return ToolOutcome(data={"error": code, "message": message}, summary=message, is_error=True, error_code=code)
    return ToolOutcome(data=data, summary=str(result.get("summary") or ""), project_id=project_id)


def _chat_handler(name: str, *, project_scoped: bool) -> Handler:
    async def run(session: AsyncSession, args: dict[str, Any], principal: McpPrincipal) -> ToolOutcome:
        from app.modules.erp_chat.tools import TOOL_HANDLER_MAP

        project_id = None
        if project_scoped:
            project_id = str(_uuid_arg(args, "project_id"))
        result = await TOOL_HANDLER_MAP[name](session, args, str(principal.user_id))
        return _from_chat_result(result, project_id)

    return run


# ── Read tools written for MCP ──────────────────────────────────────────────


async def _get_boq(session: AsyncSession, args: dict[str, Any], principal: McpPrincipal) -> ToolOutcome:
    from app.modules.boq.models import BOQ
    from app.modules.boq.service import BOQService

    project_id = _uuid_arg(args, "project_id")
    boq_id = _uuid_arg(args, "boq_id", required=False)
    limit = _int_arg(args, "limit", 500, 1, 2000)
    project = await require_project(session, project_id, principal)
    svc = BOQService(session)
    boqs, _total = await svc.list_boqs_for_project(project_id, limit=100)
    bills = [{"id": str(b.id), "name": b.name, "status": b.status} for b in boqs]
    if boq_id is None:
        if not boqs:
            return ToolOutcome(
                data={"project_id": str(project_id), "boqs": [], "boq": None},
                summary="This project has no bill of quantities yet.",
                project_id=str(project_id),
            )
        boq_id = boqs[0].id
    boq_row = await session.get(BOQ, boq_id)
    if boq_row is None or boq_row.project_id != project_id:
        raise ToolError("boq_not_found", "Bill of quantities not found in this project.")
    full = await svc.get_boq_with_positions(boq_id)
    positions = [
        {
            "id": str(p.id),
            "parent_id": str(p.parent_id) if p.parent_id else None,
            "ordinal": p.ordinal,
            "description": p.description,
            "unit": p.unit,
            "quantity": _money(p.quantity),
            "unit_rate": _money(p.unit_rate),
            "total": _money(p.total),
            "classification": p.classification or {},
            "source": p.source,
            "validation_status": p.validation_status,
        }
        for p in full.positions[:limit]
    ]
    currency = getattr(project, "currency", "") or ""
    return ToolOutcome(
        data={
            "project_id": str(project_id),
            "currency": currency,
            "boqs": bills,
            "boq": {
                "id": str(full.id),
                "name": full.name,
                "status": full.status,
                "position_count": len(full.positions),
                "positions_returned": len(positions),
                "direct_cost_total": _money(full.direct_cost_total),
                "markups_total": _money(full.markups_total),
                "grand_total": _money(full.grand_total),
                "positions": positions,
            },
        },
        summary=(
            f"BOQ '{full.name}': {len(full.positions)} positions, grand total {_money(full.grand_total)} {currency}"
        ).strip(),
        project_id=str(project_id),
    )


async def _get_schedule(session: AsyncSession, args: dict[str, Any], principal: McpPrincipal) -> ToolOutcome:
    from app.modules.schedule.models import Activity, Schedule

    project_id = _uuid_arg(args, "project_id")
    schedule_id = _uuid_arg(args, "schedule_id", required=False)
    limit = _int_arg(args, "limit", 500, 1, 2000)
    await require_project(session, project_id, principal)
    schedules = list(
        (
            await session.execute(
                select(Schedule).where(Schedule.project_id == project_id).order_by(Schedule.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    listing = [{"id": str(s.id), "name": s.name, "status": s.status} for s in schedules]
    if not schedules:
        return ToolOutcome(
            data={"project_id": str(project_id), "schedules": [], "schedule": None},
            summary="This project has no schedule yet.",
            project_id=str(project_id),
        )
    chosen = next((s for s in schedules if s.id == schedule_id), None) if schedule_id else schedules[0]
    if chosen is None:
        raise ToolError("schedule_not_found", "Schedule not found in this project.")
    activities = list(
        (
            await session.execute(
                select(Activity)
                .where(Activity.schedule_id == chosen.id)
                .order_by(Activity.sort_order.asc(), Activity.start_date.asc())
            )
        )
        .scalars()
        .all()
    )

    def row(a: Any) -> dict[str, Any]:
        return {
            "id": str(a.id),
            "code": a.activity_code,
            "name": a.name,
            "wbs_code": a.wbs_code,
            "start_date": a.start_date,
            "end_date": a.end_date,
            "duration_days": a.duration_days,
            "progress_pct": a.progress_pct,
            "status": a.status,
            "total_float": a.total_float,
            "is_critical": bool(a.is_critical),
        }

    # The critical path is what the last CPM run persisted; this tool never recalculates (reads only).
    cpm_calculated = any(a.total_float is not None for a in activities)
    critical = sorted((a for a in activities if a.is_critical), key=lambda a: a.early_start or a.start_date or "")
    return ToolOutcome(
        data={
            "project_id": str(project_id),
            "schedules": listing,
            "schedule": {
                "id": str(chosen.id),
                "name": chosen.name,
                "start_date": chosen.start_date,
                "end_date": chosen.end_date,
                "data_date": chosen.data_date,
                "activity_count": len(activities),
                "activities": [row(a) for a in activities[:limit]],
                "cpm_calculated": cpm_calculated,
                "critical_path": [row(a) for a in critical],
            },
        },
        summary=(
            f"Schedule '{chosen.name}': {len(activities)} activities, {len(critical)} on the critical path"
            + ("" if cpm_calculated else " (CPM not calculated yet)")
        ),
        project_id=str(project_id),
    )


# Statuses after which an item no longer needs anybody's attention.
_RFI_DONE = frozenset({"closed", "void"})
_SUBMITTAL_DONE = frozenset({"closed", "approved", "approved_as_noted", "rejected", "void"})
_PUNCH_DONE = frozenset({"closed", "verified"})


async def _issue_section(
    session: AsyncSession,
    model: Any,
    project_id: uuid.UUID,
    done: frozenset[str],
    *,
    number_attr: str | None,
    title_attr: str,
    due_attr: str | None,
    limit: int,
) -> dict[str, Any]:
    counts_rows = (
        await session.execute(
            select(model.status, func.count(model.id)).where(model.project_id == project_id).group_by(model.status)
        )
    ).all()
    by_status = {str(s): int(n) for s, n in counts_rows}
    open_rows = list(
        (
            await session.execute(
                select(model)
                .where(model.project_id == project_id, model.status.notin_(list(done)))
                .order_by(model.created_at.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    today = datetime.now(UTC).date().isoformat()
    items = []
    overdue = 0
    for r in open_rows:
        due = getattr(r, due_attr, None) if due_attr else None
        due_iso = _iso(due)
        is_overdue = bool(due_iso and due_iso[:10] < today)
        overdue += int(is_overdue)
        items.append(
            {
                "id": str(r.id),
                "number": getattr(r, number_attr, None) if number_attr else None,
                "title": getattr(r, title_attr, ""),
                "status": r.status,
                "priority": getattr(r, "priority", None),
                "due_date": due_iso,
                "overdue": is_overdue,
            }
        )
    return {
        "total": sum(by_status.values()),
        "open": sum(n for s, n in by_status.items() if s not in done),
        "by_status": by_status,
        "open_items": items,
        "overdue_in_list": overdue,
    }


async def _get_site_issues_summary(session: AsyncSession, args: dict[str, Any], principal: McpPrincipal) -> ToolOutcome:
    from app.core.permissions import permission_registry

    project_id = _uuid_arg(args, "project_id")
    limit = _int_arg(args, "limit", 20, 1, 100)
    await require_project(session, project_id, principal)
    data: dict[str, Any] = {"project_id": str(project_id)}
    parts: list[str] = []

    def allowed(permission: str, module: str) -> bool:
        return permission_registry.role_has_permission(principal.role, permission) and module_available(module)

    if allowed("rfi.read", "oe_rfi"):
        from app.modules.rfi.models import RFI

        data["rfis"] = await _issue_section(
            session,
            RFI,
            project_id,
            _RFI_DONE,
            number_attr="rfi_number",
            title_attr="subject",
            due_attr="response_due_date",
            limit=limit,
        )
        parts.append(f"{data['rfis']['open']} open RFIs")
    if allowed("submittals.read", "oe_submittals"):
        from app.modules.submittals.models import Submittal

        data["submittals"] = await _issue_section(
            session,
            Submittal,
            project_id,
            _SUBMITTAL_DONE,
            number_attr="submittal_number",
            title_attr="title",
            due_attr=None,
            limit=limit,
        )
        parts.append(f"{data['submittals']['open']} open submittals")
    if allowed("punchlist.read", "oe_punchlist"):
        from app.modules.punchlist.models import PunchItem

        data["punch_items"] = await _issue_section(
            session,
            PunchItem,
            project_id,
            _PUNCH_DONE,
            number_attr=None,
            title_attr="title",
            due_attr="due_date",
            limit=limit,
        )
        parts.append(f"{data['punch_items']['open']} open punch items")
    if not parts:
        raise ToolError("permission_denied", "Your role cannot read RFIs, submittals or punch items.")
    return ToolOutcome(data=data, summary=", ".join(parts), project_id=str(project_id))


async def _list_documents(session: AsyncSession, args: dict[str, Any], principal: McpPrincipal) -> ToolOutcome:
    from app.modules.documents.folder_permissions_service import (
        effective_permissions_for,
        is_project_owner,
        kind_and_path_for_document,
        restricted_scopes_for_project,
    )
    from app.modules.documents.service import DocumentService

    project_id = _uuid_arg(args, "project_id")
    category = _str_arg(args, "category", 50)
    search = _str_arg(args, "query", 200)
    limit = _int_arg(args, "limit", 100, 1, 500)
    await require_project(session, project_id, principal)
    docs, total = await DocumentService(session).list_documents(
        project_id, limit=limit, category=category, search=search
    )
    # Same folder rule as GET /documents/: owners and admins see all, members only open or granted folders.
    if principal.role != "admin" and not await is_project_owner(session, project_id, principal.user_id):
        grants = await effective_permissions_for(session, project_id=project_id, user_id=principal.user_id)
        restricted = await restricted_scopes_for_project(session, project_id)
        visible = []
        for doc in docs:
            kind, path = kind_and_path_for_document(doc.category)
            if (kind, path) in restricted or (kind, None) in restricted:
                if (kind, path) not in grants and (kind, None) not in grants:
                    continue
            visible.append(doc)
        docs = visible
    items = [
        {
            "id": str(d.id),
            "name": d.name,
            "description": d.description,
            "category": d.category,
            "discipline": d.discipline,
            "mime_type": d.mime_type,
            "file_size": d.file_size,
            "version": d.version,
            "revision_code": d.revision_code,
            "drawing_number": d.drawing_number,
            "cde_state": d.cde_state,
            "tags": list(d.tags or []),
            "created_at": _iso(d.created_at),
            "updated_at": _iso(d.updated_at),
        }
        for d in docs
    ]
    return ToolOutcome(
        data={"project_id": str(project_id), "documents": items, "returned": len(items)},
        summary=f"{len(items)} document(s)" + (f" matching '{search}'" if search else ""),
        project_id=str(project_id),
    )


# ── Registry ────────────────────────────────────────────────────────────────


def module_available(name: str) -> bool:
    """Whether a module is loaded and enabled (the assistant registry's rule, reused)."""
    from app.modules.erp_chat.actions.registry import module_available as _available

    return _available(name)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


READ_TOOLS: tuple[McpTool, ...] = (
    McpTool(
        name="list_projects",
        title="List projects",
        description="Projects you own or are a team member of: id, name, code, status, region, currency.",
        input_schema=_schema({}, []),
        kind="read",
        handler=_chat_handler("get_all_projects", project_scoped=False),
        permissions=("projects.read",),
        modules=("oe_projects",),
    ),
    McpTool(
        name="get_project_summary",
        title="Project summary",
        description="One project's status, phase, dates, budget and contract value.",
        input_schema=_schema({"project_id": _PROJECT_ID}, ["project_id"]),
        kind="read",
        handler=_chat_handler("get_project_summary", project_scoped=True),
        permissions=("projects.read",),
        modules=("oe_projects",),
    ),
    McpTool(
        name="get_boq",
        title="Bill of quantities",
        description=(
            "Positions and totals of a bill of quantities. Without boq_id the project's first bill is "
            "returned; 'boqs' lists all bills. Money values are decimal strings in the project currency."
        ),
        input_schema=_schema(
            {
                "project_id": _PROJECT_ID,
                "boq_id": {"type": "string", "format": "uuid", "description": "UUID of the bill (optional)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 500},
            },
            ["project_id"],
        ),
        kind="read",
        handler=_get_boq,
        permissions=("boq.read",),
        modules=("oe_boq",),
    ),
    McpTool(
        name="search_cost_database",
        title="Search cost database",
        description="Search cost items (code, description, unit, rate) by text, optionally within a region.",
        input_schema=_schema(
            {
                "query": {"type": "string", "description": "Words to search for, e.g. 'concrete wall C30/37'."},
                "region": {"type": "string", "description": "Region code of the cost database (optional)."},
            },
            ["query"],
        ),
        kind="read",
        handler=_chat_handler("search_cwicr_database", project_scoped=False),
        permissions=("costs.read",),
        modules=("oe_costs",),
    ),
    McpTool(
        name="get_schedule",
        title="Schedule and critical path",
        description=(
            "Activities of a project schedule and its critical path as of the last CPM calculation. "
            "Without schedule_id the project's first schedule is returned."
        ),
        input_schema=_schema(
            {
                "project_id": _PROJECT_ID,
                "schedule_id": {"type": "string", "format": "uuid", "description": "UUID of the schedule (optional)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 500},
            },
            ["project_id"],
        ),
        kind="read",
        handler=_get_schedule,
        permissions=("schedule.read",),
        modules=("oe_schedule",),
    ),
    McpTool(
        name="get_validation_results",
        title="Validation results",
        description="The project's latest validation reports: rule sets, status, score, error and warning counts.",
        input_schema=_schema({"project_id": _PROJECT_ID}, ["project_id"]),
        kind="read",
        handler=_chat_handler("get_validation_results", project_scoped=True),
        permissions=("validation.read",),
        modules=("oe_validation",),
    ),
    McpTool(
        name="get_site_issues_summary",
        title="RFIs, submittals and punch items",
        description=(
            "Counts by status and the oldest open items for RFIs, submittals and punch items of a project, "
            "with due dates and an overdue flag. Sections your role cannot read are left out."
        ),
        input_schema=_schema(
            {
                "project_id": _PROJECT_ID,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            ["project_id"],
        ),
        kind="read",
        handler=_get_site_issues_summary,
        permissions=(),
        modules=(),
    ),
    McpTool(
        name="list_documents",
        title="Documents",
        description=(
            "Document metadata of a project (name, category, discipline, type, size, revision, CDE state). "
            "File contents are not returned. Folder permissions apply."
        ),
        input_schema=_schema(
            {
                "project_id": _PROJECT_ID,
                "category": {"type": "string", "description": "Only this category (optional)."},
                "query": {"type": "string", "description": "Text to look for in name or description (optional)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
            ["project_id"],
        ),
        kind="read",
        handler=_list_documents,
        permissions=("documents.read",),
        modules=("oe_documents",),
    ),
    McpTool(
        name="get_risk_register",
        title="Risk register",
        description="The project's risks with probability, impact, score, status and mitigation.",
        input_schema=_schema({"project_id": _PROJECT_ID}, ["project_id"]),
        kind="read",
        handler=_chat_handler("get_risk_register", project_scoped=True),
        permissions=("risk.read",),
        modules=("oe_risk",),
    ),
)

_PROPOSE_NOTE = (
    " This only creates a proposal: nothing changes until a person reviews it in the app and clicks Apply. "
    "Always give your confidence (0 to 1) and a one-line rationale."
)


def _propose_handler(tool_name: str) -> Handler:
    async def run(session: AsyncSession, args: dict[str, Any], principal: McpPrincipal) -> ToolOutcome:
        from app.modules.erp_chat.actions.service import propose_tool_result

        if args.get("confidence") is None or not str(args.get("rationale") or "").strip():
            raise ToolError("invalid_arguments", "'confidence' and 'rationale' are required for every proposal.")
        result = await propose_tool_result(
            session,
            tool_name=tool_name,
            args=dict(args),
            user_id=principal.user_id,
            batch_id=f"mcp:{uuid.uuid4().hex}",
            source="mcp",
        )
        data = result.get("data") or {}
        if result.get("renderer") == "error":
            code = str(data.get("error") or "proposal_refused")
            return ToolOutcome(data=data, summary=str(result.get("summary") or code), is_error=True, error_code=code)
        project_id = data.get("project_id")
        return ToolOutcome(
            data={
                "action_id": data.get("id"),
                "status": data.get("status"),
                "title": data.get("title"),
                "project_id": project_id,
                "confidence": data.get("confidence"),
                "fields": data.get("fields", []),
            },
            summary=str(result.get("summary") or ""),
            project_id=str(project_id) if project_id else None,
            action_id=str(data.get("id")) if data.get("id") else None,
        )

    return run


def propose_tools() -> list[McpTool]:
    """The assistant's proposal actions whose modules are enabled now, as MCP tools."""
    from app.modules.erp_chat.actions.registry import all_specs

    tools = []
    for spec in all_specs(available_only=True):
        schema = spec.input_schema()
        schema["required"] = sorted({*schema.get("required", []), "confidence", "rationale"})
        tools.append(
            McpTool(
                name=spec.tool_name,
                title=spec.title,
                description=spec.tool_description.rstrip() + _PROPOSE_NOTE,
                input_schema=schema,
                kind="propose",
                handler=_propose_handler(spec.tool_name),
                modules=tuple(spec.modules),
            )
        )
    return tools


def all_tools() -> list[McpTool]:
    """Every tool this build knows, read tools first."""
    return [*READ_TOOLS, *propose_tools()]


def tool_is_available(tool: McpTool) -> bool:
    """Whether every module the tool reads or writes is enabled."""
    return all(module_available(m) for m in tool.modules)


def tool_allowed(tool: McpTool, principal: McpPrincipal) -> bool:
    """Whether this caller may see and call ``tool``: scope, role permission and module state."""
    from app.core.permissions import permission_registry

    if tool.kind == "propose" and not principal.can_propose:
        return False
    if not tool_is_available(tool):
        return False
    return all(permission_registry.role_has_permission(principal.role, p) for p in tool.permissions)


def tools_for(principal: McpPrincipal) -> list[McpTool]:
    """The tools ``tools/list`` shows this caller."""
    return [t for t in all_tools() if tool_allowed(t, principal)]


def find_tool(name: str) -> McpTool | None:
    """A tool by name, whether or not this caller may use it."""
    return next((t for t in all_tools() if t.name == name), None)
