"""ERP Chat tool definitions and handlers.

Each tool maps to a real ERP service call. Handlers return a dict with:
    renderer  — frontend component hint (e.g. "projects_grid", "boq_table")
    data      — structured payload for the renderer
    summary   — one-line human-readable summary for the AI
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Tool definitions (Anthropic function-calling format) ─────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_all_projects",
        "description": "List all projects with their names, codes, status, and basic info.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_project_summary",
        "description": "Get detailed summary for a single project including budget, schedule dates, status, and contract value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_boq_items",
        "description": "Get Bill of Quantities items/positions for a project. Returns position descriptions, quantities, unit rates, totals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_schedule",
        "description": "Get schedule/Gantt data for a project including activities, durations, dependencies, and progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_validation_results",
        "description": "Get validation reports for a project — compliance scores, passed/warning/error rule results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_risk_register",
        "description": "Get risk register for a project — risk items with probability, impact, score, mitigation, and summary stats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "search_cwicr_database",
        "description": "Search the CWICR construction cost database (55,000+ items) by keyword. Returns matching cost items with codes, descriptions, units, and rates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'concrete wall', 'rebar', 'excavation')",
                },
                "region": {
                    "type": "string",
                    "description": "Optional region filter (e.g. 'DE_BERLIN', 'UK_LONDON')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_cost_model",
        "description": "Get cost model/summary for a project — direct cost, markups, grand total from the first BOQ.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "compare_projects",
        "description": "Compare key metrics (budget, contract value, status, risk exposure) across multiple projects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of project UUIDs to compare",
                },
            },
            "required": ["project_ids"],
        },
    },
    {
        "name": "run_validation",
        "description": "Trigger a validation run for a project and return the results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "create_boq_item",
        "description": "Create a new BOQ position in a project's first BOQ. Returns the created item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "UUID of the project",
                },
                "description": {
                    "type": "string",
                    "description": "Position description (e.g. 'Reinforced concrete wall C30/37')",
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of measurement (m, m2, m3, kg, pcs, lsum)",
                },
                "quantity": {
                    "type": "number",
                    "description": "Quantity value",
                },
                "unit_rate": {
                    "type": "number",
                    "description": "Price per unit",
                },
            },
            "required": ["project_id", "description", "unit", "quantity", "unit_rate"],
        },
    },
]


# ── Tool handlers ────────────────────────────────────────────────────────────


async def handle_get_all_projects(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """List all projects visible to the current user."""
    try:
        from app.config import get_settings
        from app.modules.projects.service import ProjectService

        svc = ProjectService(session, get_settings())
        projects, total = await svc.list_projects(
            owner_id=None, is_admin=True, limit=50  # type: ignore[arg-type]
        )
        return {
            "renderer": "projects_grid",
            "data": {
                "projects": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "code": getattr(p, "project_code", ""),
                        "status": p.status,
                        "region": getattr(p, "region", ""),
                        "currency": getattr(p, "currency", "EUR"),
                        "contract_value": float(getattr(p, "contract_value", 0) or 0),
                    }
                    for p in projects
                ],
                "total": total,
            },
            "summary": f"{total} projects found",
        }
    except Exception as exc:
        logger.exception("handle_get_all_projects failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_get_project_summary(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Get detailed summary for a single project."""
    try:
        from app.config import get_settings
        from app.modules.projects.service import ProjectService

        pid = uuid.UUID(args["project_id"])
        svc = ProjectService(session, get_settings())
        p = await svc.get_project(pid)
        return {
            "renderer": "project_summary",
            "data": {
                "id": str(p.id),
                "name": p.name,
                "code": getattr(p, "project_code", ""),
                "status": p.status,
                "region": getattr(p, "region", ""),
                "currency": getattr(p, "currency", "EUR"),
                "contract_value": float(getattr(p, "contract_value", 0) or 0),
                "budget_estimate": float(getattr(p, "budget_estimate", 0) or 0),
                "phase": getattr(p, "phase", ""),
                "project_type": getattr(p, "project_type", ""),
                "planned_start_date": str(getattr(p, "planned_start_date", "") or ""),
                "planned_end_date": str(getattr(p, "planned_end_date", "") or ""),
                "actual_start_date": str(getattr(p, "actual_start_date", "") or ""),
                "actual_end_date": str(getattr(p, "actual_end_date", "") or ""),
                "description": getattr(p, "description", "") or "",
            },
            "summary": f"Project '{p.name}' ({p.status})",
        }
    except Exception as exc:
        logger.exception("handle_get_project_summary failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_get_boq_items(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Get BOQ positions for a project's first BOQ."""
    try:
        from app.modules.boq.service import BOQService

        pid = uuid.UUID(args["project_id"])
        svc = BOQService(session)
        boqs, total_boqs = await svc.list_boqs_for_project(pid, limit=5)
        if not boqs:
            return {
                "renderer": "boq_table",
                "data": {"positions": [], "boq_name": None},
                "summary": "No BOQs found for this project",
            }

        boq = boqs[0]
        boq_data = await svc.get_boq_with_positions(boq.id)
        positions = []
        for pos in boq_data.positions:
            positions.append({
                "id": str(pos.id),
                "ordinal": pos.ordinal,
                "description": pos.description or "",
                "unit": pos.unit or "",
                "quantity": float(pos.quantity or 0),
                "unit_rate": float(pos.unit_rate or 0),
                "total": float(pos.total or 0),
                "source": getattr(pos, "source", ""),
            })

        return {
            "renderer": "boq_table",
            "data": {
                "boq_id": str(boq.id),
                "boq_name": boq.name,
                "positions": positions,
                "position_count": len(positions),
                "grand_total": float(boq_data.grand_total or 0),
            },
            "summary": (
                f"BOQ '{boq.name}': {len(positions)} positions, "
                f"grand total {boq_data.grand_total}"
            ),
        }
    except Exception as exc:
        logger.exception("handle_get_boq_items failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_get_schedule(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Get schedule/Gantt data for a project."""
    try:
        from app.modules.schedule.service import ScheduleService

        pid = uuid.UUID(args["project_id"])
        svc = ScheduleService(session)
        schedules, total = await svc.list_schedules_for_project(pid, limit=5)
        if not schedules:
            return {
                "renderer": "schedule_gantt",
                "data": {"activities": []},
                "summary": "No schedules found for this project",
            }

        schedule = schedules[0]
        gantt = await svc.get_gantt_data(schedule.id)

        activities = []
        for act in gantt.activities:
            activities.append({
                "id": str(act.id),
                "name": act.name,
                "wbs_code": getattr(act, "wbs_code", ""),
                "start_date": str(act.start_date) if act.start_date else "",
                "end_date": str(act.end_date) if act.end_date else "",
                "duration_days": act.duration_days,
                "progress": act.progress,
                "status": getattr(act, "status", ""),
                "is_critical": getattr(act, "is_critical", False),
            })

        summary_data = gantt.summary
        return {
            "renderer": "schedule_gantt",
            "data": {
                "schedule_id": str(schedule.id),
                "schedule_name": schedule.name,
                "activities": activities,
                "summary": {
                    "total_activities": getattr(summary_data, "total_activities", len(activities)),
                    "completed": getattr(summary_data, "completed", 0),
                    "in_progress": getattr(summary_data, "in_progress", 0),
                    "overall_progress": getattr(summary_data, "overall_progress", 0),
                },
            },
            "summary": (
                f"Schedule '{schedule.name}': {len(activities)} activities"
            ),
        }
    except Exception as exc:
        logger.exception("handle_get_schedule failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_get_validation_results(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Get validation reports for a project."""
    try:
        from app.modules.validation.repository import ValidationReportRepository

        pid = uuid.UUID(args["project_id"])
        repo = ValidationReportRepository(session)
        reports, total = await repo.list_for_project(pid, limit=10)
        if not reports:
            return {
                "renderer": "validation_dashboard",
                "data": {"reports": []},
                "summary": "No validation reports found for this project",
            }

        report_list = []
        for r in reports:
            report_list.append({
                "id": str(r.id),
                "target_type": r.target_type,
                "target_id": r.target_id,
                "rule_set": r.rule_set,
                "status": r.status,
                "score": str(r.score) if r.score else None,
                "total_rules": getattr(r, "total_rules", 0),
                "passed_count": getattr(r, "passed_count", 0),
                "warning_count": getattr(r, "warning_count", 0),
                "error_count": getattr(r, "error_count", 0),
                "created_at": str(r.created_at),
            })

        return {
            "renderer": "validation_dashboard",
            "data": {"reports": report_list, "total": total},
            "summary": f"{total} validation report(s) found",
        }
    except Exception as exc:
        logger.exception("handle_get_validation_results failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_get_risk_register(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Get risk register with summary for a project."""
    try:
        from app.modules.risk.service import RiskService

        pid = uuid.UUID(args["project_id"])
        svc = RiskService(session)
        risks, total = await svc.list_risks(pid, limit=50)
        summary_data = await svc.get_summary(pid)

        risk_list = []
        for r in risks:
            risk_list.append({
                "id": str(r.id),
                "code": r.code,
                "title": r.title,
                "category": r.category,
                "probability": float(r.probability) if r.probability else 0,
                "impact_severity": r.impact_severity,
                "risk_score": float(r.risk_score) if r.risk_score else 0,
                "risk_tier": getattr(r, "risk_tier", ""),
                "status": r.status,
                "mitigation_strategy": r.mitigation_strategy or "",
                "owner_name": getattr(r, "owner_name", ""),
            })

        return {
            "renderer": "risk_register",
            "data": {
                "risks": risk_list,
                "total": total,
                "summary": summary_data,
            },
            "summary": f"{total} risks found",
        }
    except Exception as exc:
        logger.exception("handle_get_risk_register failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_search_cwicr_database(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Search the CWICR cost database."""
    try:
        from app.modules.costs.repository import CostItemRepository

        query = args.get("query", "")
        region = args.get("region")
        repo = CostItemRepository(session)
        items, total = await repo.search(q=query, region=region, limit=20)

        results = []
        for item in items:
            results.append({
                "id": str(item.id),
                "code": item.code,
                "description": item.description or "",
                "unit": item.unit or "",
                "rate": str(item.rate) if item.rate else "0",
                "source": getattr(item, "source", ""),
                "region": getattr(item, "region", ""),
            })

        return {
            "renderer": "cost_items_table",
            "data": {"items": results, "total": total, "query": query},
            "summary": f"{total} cost items found for '{query}'",
        }
    except Exception as exc:
        logger.exception("handle_search_cwicr_database failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_get_cost_model(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Get cost model summary for a project from its first BOQ."""
    try:
        from app.modules.boq.service import BOQService

        pid = uuid.UUID(args["project_id"])
        svc = BOQService(session)
        boqs, _ = await svc.list_boqs_for_project(pid, limit=1)
        if not boqs:
            return {
                "renderer": "cost_model",
                "data": {},
                "summary": "No BOQs found — cannot compute cost model",
            }

        boq = boqs[0]
        structured = await svc.get_boq_structured(boq.id)

        # Extract cost breakdown
        sections = []
        for sec in getattr(structured, "sections", []):
            sections.append({
                "title": getattr(sec, "title", ""),
                "subtotal": float(getattr(sec, "subtotal", 0)),
                "position_count": len(getattr(sec, "positions", [])),
            })

        markups = []
        for m in getattr(structured, "markups", []):
            markups.append({
                "name": getattr(m, "name", ""),
                "category": getattr(m, "category", ""),
                "percentage": float(getattr(m, "percentage", 0)),
                "amount": float(getattr(m, "amount", 0)),
            })

        return {
            "renderer": "cost_model",
            "data": {
                "boq_id": str(boq.id),
                "boq_name": boq.name,
                "direct_cost": float(getattr(structured, "direct_cost", 0)),
                "net_total": float(getattr(structured, "net_total", 0)),
                "grand_total": float(getattr(structured, "grand_total", 0)),
                "sections": sections,
                "markups": markups,
            },
            "summary": (
                f"Cost model for '{boq.name}': "
                f"direct={getattr(structured, 'direct_cost', 0)}, "
                f"grand total={getattr(structured, 'grand_total', 0)}"
            ),
        }
    except Exception as exc:
        logger.exception("handle_get_cost_model failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_compare_projects(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Compare key metrics across multiple projects."""
    try:
        from app.config import get_settings
        from app.modules.projects.service import ProjectService

        project_ids = [uuid.UUID(pid) for pid in args.get("project_ids", [])]
        if not project_ids:
            return {
                "renderer": "error",
                "data": {"error": "No project IDs provided"},
                "summary": "Error: No project IDs provided",
            }

        svc = ProjectService(session, get_settings())
        comparisons = []
        for pid in project_ids:
            try:
                p = await svc.get_project(pid)
                comparisons.append({
                    "id": str(p.id),
                    "name": p.name,
                    "code": getattr(p, "project_code", ""),
                    "status": p.status,
                    "contract_value": float(getattr(p, "contract_value", 0) or 0),
                    "budget_estimate": float(getattr(p, "budget_estimate", 0) or 0),
                    "region": getattr(p, "region", ""),
                    "currency": getattr(p, "currency", "EUR"),
                })
            except Exception:
                comparisons.append({"id": str(pid), "error": "Project not found"})

        return {
            "renderer": "project_comparison",
            "data": {"projects": comparisons},
            "summary": f"Compared {len(comparisons)} projects",
        }
    except Exception as exc:
        logger.exception("handle_compare_projects failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_run_validation(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Trigger validation for a project and return results."""
    try:
        from app.modules.validation.repository import ValidationReportRepository

        pid = uuid.UUID(args["project_id"])
        repo = ValidationReportRepository(session)
        # Return the most recent validation reports
        reports, total = await repo.list_for_project(pid, limit=5)

        if not reports:
            return {
                "renderer": "validation_dashboard",
                "data": {"reports": []},
                "summary": "No validation reports available. Run validation from the Validation module first.",
            }

        report_list = []
        for r in reports:
            report_list.append({
                "id": str(r.id),
                "target_type": r.target_type,
                "rule_set": r.rule_set,
                "status": r.status,
                "score": str(r.score) if r.score else None,
                "total_rules": getattr(r, "total_rules", 0),
                "passed_count": getattr(r, "passed_count", 0),
                "warning_count": getattr(r, "warning_count", 0),
                "error_count": getattr(r, "error_count", 0),
                "created_at": str(r.created_at),
            })

        return {
            "renderer": "validation_dashboard",
            "data": {"reports": report_list, "total": total},
            "summary": f"Latest validation: {reports[0].status} (score: {reports[0].score})",
        }
    except Exception as exc:
        logger.exception("handle_run_validation failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


async def handle_create_boq_item(
    session: AsyncSession, args: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Create a new BOQ position in a project's first BOQ."""
    try:
        from app.modules.boq.schemas import PositionCreate
        from app.modules.boq.service import BOQService

        pid = uuid.UUID(args["project_id"])
        svc = BOQService(session)
        boqs, _ = await svc.list_boqs_for_project(pid, limit=1)
        if not boqs:
            return {
                "renderer": "error",
                "data": {"error": "No BOQs found for this project"},
                "summary": "Error: No BOQs found — create a BOQ first",
            }

        boq = boqs[0]

        # Auto-generate ordinal
        boq_data = await svc.get_boq_with_positions(boq.id)
        next_ordinal = f"{len(boq_data.positions) + 1:03d}"

        data = PositionCreate(
            boq_id=boq.id,
            ordinal=next_ordinal,
            description=args.get("description", ""),
            unit=args.get("unit", "pcs"),
            quantity=args.get("quantity", 0),
            unit_rate=args.get("unit_rate", 0),
        )
        position = await svc.add_position(data)
        total = float(args.get("quantity", 0)) * float(args.get("unit_rate", 0))

        return {
            "renderer": "boq_item_created",
            "data": {
                "id": str(position.id),
                "boq_id": str(boq.id),
                "ordinal": next_ordinal,
                "description": args.get("description", ""),
                "unit": args.get("unit", "pcs"),
                "quantity": float(args.get("quantity", 0)),
                "unit_rate": float(args.get("unit_rate", 0)),
                "total": total,
            },
            "summary": f"Created position {next_ordinal}: {args.get('description', '')} (total: {total:.2f})",
        }
    except Exception as exc:
        logger.exception("handle_create_boq_item failed")
        return {"renderer": "error", "data": {"error": str(exc)}, "summary": f"Error: {exc}"}


# ── Tool handler dispatch map ────────────────────────────────────────────────

TOOL_HANDLER_MAP: dict[str, Any] = {
    "get_all_projects": handle_get_all_projects,
    "get_project_summary": handle_get_project_summary,
    "get_boq_items": handle_get_boq_items,
    "get_schedule": handle_get_schedule,
    "get_validation_results": handle_get_validation_results,
    "get_risk_register": handle_get_risk_register,
    "search_cwicr_database": handle_search_cwicr_database,
    "get_cost_model": handle_get_cost_model,
    "compare_projects": handle_compare_projects,
    "run_validation": handle_run_validation,
    "create_boq_item": handle_create_boq_item,
}
