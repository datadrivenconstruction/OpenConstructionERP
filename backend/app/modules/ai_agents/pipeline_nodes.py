# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pipeline node that runs a project catalogue agent (autodiscovered by the module loader).

``action.run_project_agent`` lets a pipeline produce an agent draft, for
example a daily report draft every evening. It writes only the draft, which
still waits for a person, and it obeys the same kill switch, enablement and
token limit as a run from the catalogue page.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.core.pipeline.registry import NodeContext, register_node

MODULE = "oe_ai_agents"


async def _run_project_agent(ctx: NodeContext) -> dict[str, Any]:
    from app.modules.ai_agents.catalogue_service import CatalogueError, CatalogueService

    params = ctx.params or {}
    try:
        project_id = uuid.UUID(str(params.get("project_id") or ctx.project_id))
        user_id = uuid.UUID(str(ctx.actor_id))
    except (TypeError, ValueError):
        return {"ok": False, "error": "project_or_actor_missing"}
    inputs = dict(params.get("inputs")) if isinstance(params.get("inputs"), dict) else {}
    if params.get("agent_name") == "daily_reporter" and not inputs.get("date"):
        inputs["date"] = date.today().isoformat()
    try:
        run, draft = await CatalogueService(ctx.db).run(
            project_id=project_id,
            agent_name=str(params.get("agent_name") or ""),
            inputs=inputs,
            user_id=user_id,
            role="viewer",
            use_ai=bool(params.get("use_ai", True)),
        )
    except CatalogueError as exc:
        return {"ok": False, "error": exc.code}
    return {
        "ok": draft is not None,
        "run_id": str(run.id),
        "draft_id": str(draft.id) if draft else None,
        "confidence": draft.confidence if draft else None,
        "summary": run.final_output or run.failure_reason or "",
    }


def register_ai_agent_pipeline_nodes() -> None:
    """Register the catalogue node. Idempotent."""
    register_node(
        type="action.run_project_agent",
        module=MODULE,
        category="action",
        label="Run project agent",
        description="Run a catalogue agent enabled on the project and keep its output as a draft for review.",
        runner=_run_project_agent,
        inputs=["trigger"],
        outputs=["draft"],
        params_schema={
            "agent_name": {
                "type": "string",
                "title": "Agent",
                "enum": ["rfi_drafter", "daily_reporter", "clause_reviewer", "submittal_checker"],
            },
            "project_id": {"type": "string", "title": "Project id (optional)"},
            "inputs": {"type": "object", "title": "Agent inputs"},
            "use_ai": {"type": "boolean", "title": "Let the AI provider add a summary"},
        },
        side_effecting=True,
    )


register_ai_agent_pipeline_nodes()
