# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Phase-1 node runners for the Pipeline Builder.

This file is autodiscovered by the module loader (the same mechanism it
uses for ``hooks.py`` / ``events.py``): importing it at module-load time
registers every Phase-1 node type into the global Node Capability
Registry. The executor only ever calls *registered* runners (§3.5).

Six nodes — the smallest set that exercises the whole spine
``trigger.manual → source.boq → gate.validation → action.export.excel``
plus the helpers the design lists for Phase 1:

    trigger.manual        entry / no-op seed
    source.project        load project meta (IDs + name only)
    source.boq            load a project's BOQ positions (IDs + counts +
                          a small sample — NEVER the full universe)
    transform.filter      filter the upstream rows by a simple predicate
    gate.validation       run the validation engine; continue unless errors
    action.export.excel   reuse the existing openpyxl util → a file ref
                          (side_effecting=False — it writes a file, not DB)

Every envelope obeys §3.2 hard rule 1: IDs + small previews on the wire,
the big payload stays in its owning table.
"""

from __future__ import annotations

import io
import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.core.pipeline.registry import NodeContext, register_node

logger = logging.getLogger(__name__)

MODULE = "oe_pipelines"

# A small, bounded sample size — never stream the element universe through
# the run rows (this is what protects the 2 GB-RAM / SQLite target).
_SAMPLE_LIMIT = 25
# Hard cap on the id-list that node-state envelopes can carry. Without
# this a 100k-position project would JSON-encode 100k UUIDs into the
# oe_pipeline_node_state.output column on every node hop — a slow
# memory-bomb. ``count`` keeps the honest cardinality.
_ROW_IDS_CAP = 5000


def _resolve_project_id(ctx: NodeContext) -> uuid.UUID | None:
    """‌⁠‍Resolve the project id from node params or the run scope."""
    raw = ctx.params.get("project_id") or ctx.project_id
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    return uuid.UUID(str(raw))


# ── trigger.manual ───────────────────────────────────────────────────────


async def _run_trigger_manual(ctx: NodeContext) -> dict[str, Any]:
    """‌⁠‍Entry node — seeds the run with the trigger context. No I/O."""
    return {
        "trigger": "manual",
        "actor_id": ctx.actor_id,
        "summary": "Manual run started",
    }


# ── source.project ───────────────────────────────────────────────────────


async def _run_source_project(ctx: NodeContext) -> dict[str, Any]:
    """Load minimal project metadata (id + name)."""
    from app.modules.projects.models import Project

    pid = _resolve_project_id(ctx)
    if pid is None:
        return {"project": None, "summary": "No project bound"}
    project = await ctx.db.get(Project, pid)
    if project is None:
        return {"project": None, "summary": f"Project {pid} not found"}
    return {
        "project": {"id": str(project.id), "name": project.name},
        "summary": f"Project: {project.name}",
    }


# ── source.boq ───────────────────────────────────────────────────────────


async def _run_source_boq(ctx: NodeContext) -> dict[str, Any]:
    """Load a project's BOQ positions as rows (IDs + counts + sample).

    The envelope carries ``row_ids`` (every position id) so a downstream
    write node can act on the full set, plus a bounded ``sample`` for the
    UI preview. The full Position payload stays in ``oe_boq_position``.
    """
    from app.modules.boq.models import BOQ, Position

    pid = _resolve_project_id(ctx)
    if pid is None:
        return {"rows": [], "row_ids": [], "count": 0, "summary": "No project"}

    boq_ids = (await ctx.db.execute(select(BOQ.id).where(BOQ.project_id == pid))).scalars().all()
    if not boq_ids:
        return {"rows": [], "row_ids": [], "count": 0, "summary": "No BOQ"}

    positions = (
        (await ctx.db.execute(select(Position).where(Position.boq_id.in_(boq_ids)).order_by(Position.sort_order.asc())))
        .scalars()
        .all()
    )
    rows = [
        {
            "id": str(p.id),
            "ordinal": p.ordinal,
            "description": p.description,
            "unit": p.unit,
            "quantity": p.quantity,
            "unit_rate": p.unit_rate,
            "classification": dict(p.classification or {}),
        }
        for p in positions
    ]
    all_ids = [r["id"] for r in rows]
    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": all_ids[:_ROW_IDS_CAP],
        "row_ids_truncated": len(all_ids) > _ROW_IDS_CAP,
        "count": len(rows),
        "sample_truncated": len(rows) > _SAMPLE_LIMIT,
        "summary": f"{len(rows)} BOQ positions across {len(boq_ids)} BOQ(s)",
    }


# ── transform.filter ─────────────────────────────────────────────────────


def _matches(row: dict[str, Any], field: str, op: str, value: Any) -> bool:
    """Tiny, safe predicate — no eval, just a fixed operator set."""
    actual = row.get(field)
    if op in ("eq", "=="):
        return actual == value
    if op in ("ne", "!="):
        return actual != value
    if op == "contains":
        return value is not None and str(value).lower() in str(actual).lower()
    if op in ("gt", "gte", "lt", "lte"):
        try:
            a = float(actual)
            b = float(value)
        except (TypeError, ValueError):
            return False
        return {
            "gt": a > b,
            "gte": a >= b,
            "lt": a < b,
            "lte": a <= b,
        }[op]
    if op == "exists":
        return actual not in (None, "", [], {})
    return False


async def _run_transform_filter(ctx: NodeContext) -> dict[str, Any]:
    """Keep upstream rows matching a simple ``{field, op, value}`` predicate.

    Params: ``field`` (str), ``op`` (eq|ne|contains|gt|gte|lt|lte|exists),
    ``value`` (any). An empty predicate is an identity pass-through.
    """
    upstream = ctx.first_input()
    rows: list[dict[str, Any]] = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    op = ctx.params.get("op", "eq")
    value = ctx.params.get("value")

    if not field:
        kept = rows
    else:
        kept = [r for r in rows if _matches(r, field, op, value)]

    kept_ids = [r.get("id") for r in kept if r.get("id")]
    return {
        "rows": kept[:_SAMPLE_LIMIT],
        "row_ids": kept_ids[:_ROW_IDS_CAP],
        "row_ids_truncated": len(kept_ids) > _ROW_IDS_CAP,
        "count": len(kept),
        "dropped": len(rows) - len(kept),
        "summary": (
            f"Kept {len(kept)} of {len(rows)} rows ({field} {op} {value!r})"
            if field
            else f"Pass-through ({len(rows)} rows)"
        ),
    }


# ── gate.validation ──────────────────────────────────────────────────────


async def _run_gate_validation(ctx: NodeContext) -> dict[str, Any]:
    """Run the validation engine over the upstream rows.

    Params: ``rule_sets`` (list[str], default ``["boq_quality"]``). The
    gate *continues* (status ``done``) unless the report has blocking
    errors, in which case it raises so the run records an error and every
    downstream (write) node is skipped — the structural "AI proposes,
    human confirms" contract enforced at run time.
    """
    from app.core.validation.engine import validation_engine

    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    rule_sets = ctx.params.get("rule_sets") or ["boq_quality"]

    report = await validation_engine.validate(
        data={"positions": rows},
        rule_sets=list(rule_sets),
        target_type="pipeline.gate",
    )
    summary = report.summary()
    if report.has_errors:
        msgs = "; ".join(r.message for r in report.errors[:5])
        raise ValueError(f"Validation gate failed ({summary['counts']}): {msgs}")

    # Pass the rows through unchanged so a downstream action still has them.
    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": len(rows),
        "validation": summary,
        "summary": (
            f"Validation {summary['status']} (score={summary['score']}, warnings={summary['counts']['warnings']})"
        ),
    }


# ── action.export.excel ──────────────────────────────────────────────────


async def _run_action_export_excel(ctx: NodeContext) -> dict[str, Any]:
    """Export the upstream rows to an .xlsx using the EXISTING openpyxl dep.

    No new dependency (LIGHTWEIGHT is a hard rule): ``openpyxl`` is already
    used by ``boq.cad_import`` / ``requirements.excel_io`` / many routers.
    ``side_effecting=False`` — it produces a downloadable file, it does not
    mutate any DB row, so it does not require a preceding gate.
    """
    import openpyxl

    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    columns = ctx.params.get("columns") or [
        "ordinal",
        "description",
        "unit",
        "quantity",
        "unit_rate",
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append([str(c) for c in columns])
    for r in rows:
        ws.append([r.get(c, "") for c in columns])

    buf = io.BytesIO()
    wb.save(buf)
    size = buf.tell()

    # The bytes themselves are NOT put on the wire (§3.2). We return a
    # reference + metadata; a later phase persists the buffer to MinIO /
    # the file store and swaps this for a real download URL.
    return {
        "file": {
            "filename": ctx.params.get("filename", "pipeline-export.xlsx"),
            "content_type": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "size_bytes": size,
            "row_count": len(rows),
            "columns": list(columns),
        },
        "summary": f"Exported {len(rows)} rows → Excel ({size} bytes)",
    }


# ── Registration (import-time, autodiscovered by the module loader) ──────


def register_pipeline_nodes() -> None:
    """Register every Phase-1 node type. Idempotent (last write wins)."""
    register_node(
        type="trigger.manual",
        module=MODULE,
        category="trigger",
        label="Manual trigger",
        description="Start the pipeline from a REST call. No inputs.",
        runner=_run_trigger_manual,
        inputs=[],
        outputs=["trigger"],
        params_schema={},
        side_effecting=False,
    )
    register_node(
        type="source.project",
        module=MODULE,
        category="source",
        label="Get project",
        description="Load the bound project's id + name.",
        runner=_run_source_project,
        inputs=["trigger"],
        outputs=["project"],
        params_schema={"project_id": {"type": "string", "title": "Project id (optional)"}},
        side_effecting=False,
    )
    register_node(
        type="source.boq",
        module=MODULE,
        category="source",
        label="Get BOQ positions",
        description=("Load every BOQ position for the project as rows (ids + a small sample)."),
        runner=_run_source_boq,
        inputs=["trigger", "project"],
        outputs=["rows"],
        params_schema={"project_id": {"type": "string", "title": "Project id (optional)"}},
        side_effecting=False,
    )
    register_node(
        type="transform.filter",
        module=MODULE,
        category="transform",
        label="Filter rows",
        description="Keep only rows matching a simple field/op/value test.",
        runner=_run_transform_filter,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Field"},
            "op": {
                "type": "string",
                "title": "Operator",
                "enum": [
                    "eq",
                    "ne",
                    "contains",
                    "gt",
                    "gte",
                    "lt",
                    "lte",
                    "exists",
                ],
            },
            "value": {"title": "Value"},
        },
        side_effecting=False,
    )
    register_node(
        type="gate.validation",
        module=MODULE,
        category="gate",
        label="Validation gate",
        description=("Run the validation engine over the rows; stop the run on blocking errors."),
        runner=_run_gate_validation,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "rule_sets": {
                "type": "array",
                "title": "Rule sets",
                "items": {"type": "string"},
                "default": ["boq_quality"],
            }
        },
        side_effecting=False,
    )
    register_node(
        type="action.export.excel",
        module=MODULE,
        category="action",
        label="Export to Excel",
        description=("Write the rows to an .xlsx file (returns a download reference; does not mutate the database)."),
        runner=_run_action_export_excel,
        inputs=["rows"],
        outputs=["file"],
        params_schema={
            "filename": {"type": "string", "title": "File name"},
            "columns": {
                "type": "array",
                "title": "Columns",
                "items": {"type": "string"},
            },
        },
        # Produces a file, not a DB mutation — so it needs no preceding gate.
        side_effecting=False,
    )


register_pipeline_nodes()
