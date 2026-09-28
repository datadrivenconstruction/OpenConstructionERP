# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Phase-1 node runners for the Pipeline Builder.

This file is autodiscovered by the module loader (the same mechanism it
uses for ``hooks.py`` / ``events.py``): importing it at module-load time
registers every Phase-1 node type into the global Node Capability
Registry. The executor only ever calls *registered* runners (§3.5).

The spine ``trigger.manual → source.boq → gate.validation →
action.export.excel`` plus a wider working set of estimator-facing nodes:

    trigger.manual        entry / no-op seed
    source.project        load project meta (IDs + name only)
    source.boq            load a project's BOQ positions (IDs + counts +
                          a small sample - NEVER the full universe)
    source.cost_catalog   load priced cost-catalog items as rows
    transform.filter      filter the upstream rows by a simple predicate
    transform.markup      raise / discount every unit rate by a percent
    transform.aggregate   group rows by a field and total each group
    transform.rollup      sum quantity x unit_rate into one total
    transform.sort        order rows by a field (numeric or alphabetic)
    transform.limit       keep only the first N rows (top-N with sort)
    transform.dedupe      drop rows repeating a value in a key field
    gate.validation       run the validation engine; continue unless errors
    gate.budget           stop the run if the total exceeds a budget ceiling
    gate.completeness     flag / stop on rows missing a quantity or a rate
    gate.count            stop the run unless the row count is in range
    flow.merge            combine the rows from two branches into one set
    action.export.excel   reuse the existing openpyxl util → a file ref
                          (side_effecting=False - it writes a file, not DB)
    action.export.csv     write the rows to a .csv file reference

Plus a broader data-shaping set layered on the same envelope contract:

    transform.round             round a numeric field to N decimals
    transform.currency_convert  restate a money field by an FX rate
    transform.map_values        remap a field via a from/to dictionary
    transform.split             partition rows matched vs unmatched
    transform.join              merge two branches on a shared key
    transform.running_total     cumulative sum of a field, in row order
    transform.percent_of_total  each row's share (%) of a field total
    transform.fill_missing      default blank / missing values
    transform.clamp             constrain a numeric field to [min, max]
    transform.concat            join several fields into one text column
    source.constant             emit fixed literal rows from a param
    enrich.lookup               fold reference fields on from a lookup table

Aggregates, totals and gates compute over the FULL row set: a BOQ
envelope carries ``row_ids`` and ``_resolve_full_rows`` re-reads the
positions, so a total is never just the 25-row preview. Money stays
Decimal-as-string end to end. Every envelope still obeys §3.2 hard rule
1: IDs + small previews on the wire, the big payload stays in its table.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.core.pipeline.registry import NodeContext, register_node

logger = logging.getLogger(__name__)

MODULE = "oe_pipelines"

# A small, bounded sample size - never stream the element universe through
# the run rows (this is what protects the 3 GB-RAM target).
_SAMPLE_LIMIT = 25
# Hard cap on the id-list that node-state envelopes can carry. Without
# this a 100k-position project would JSON-encode 100k UUIDs into the
# oe_pipeline_node_state.output column on every node hop - a slow
# memory-bomb. ``count`` keeps the honest cardinality.
_ROW_IDS_CAP = 5000


def _resolve_project_id(ctx: NodeContext) -> uuid.UUID | None:
    """Resolve the project id from node params or the run scope."""
    raw = ctx.params.get("project_id") or ctx.project_id
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    return uuid.UUID(str(raw))


# ── money / row helpers (Decimal-as-string end to end) ───────────────────


def _to_decimal(value: Any) -> Decimal | None:
    """Parse a money / quantity value into a Decimal, or None.

    Accepts the platform's Decimal-as-string wire values, native Decimals
    (as they come straight off an ORM row) and ints; anything blank or
    non-numeric returns None so callers can decide the fallback. The value
    is never rounded here - precision is preserved.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _line_total(row: dict[str, Any]) -> Decimal:
    """quantity x unit_rate for a row, treating missing parts as zero."""
    qty = _to_decimal(row.get("quantity")) or Decimal(0)
    rate = _to_decimal(row.get("unit_rate")) or Decimal(0)
    return qty * rate


def _row_value(row: dict[str, Any], path: str) -> Any:
    """Read a possibly dotted key path from a row (e.g. ``classification.din276``)."""
    cur: Any = row
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _position_row(p: Any) -> dict[str, Any]:
    """Wire shape for one BOQ position, shared by every path that reads them."""
    return {
        "id": str(p.id),
        "ordinal": p.ordinal,
        "description": p.description,
        "unit": p.unit,
        "quantity": p.quantity,
        "unit_rate": p.unit_rate,
        "classification": dict(p.classification or {}),
    }


async def _resolve_full_rows(ctx: NodeContext, upstream: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the full row set behind an envelope, not just the wire sample.

    A node only receives a bounded ``rows`` preview on the wire, but a BOQ
    envelope also carries ``row_ids`` (the real, capped universe). So an
    aggregate / total / gate can re-read the full positions from the
    database and compute over every row rather than the 25-row sample.

    Order of preference:
      1. ``mutated`` envelopes (a what-if transform such as markup changed
         the values in place) - use the rows as given, re-reading the DB
         would throw the change away.
      2. ``row_ids`` present - re-read those BOQ positions in full.
      3. otherwise - fall back to the wire sample (e.g. a non-BOQ source).
    """
    if upstream.get("mutated"):
        return list(upstream.get("rows") or [])

    from app.modules.boq.models import Position

    # The id list is capped at _ROW_IDS_CAP so the node-state JSON stays small.
    # Re-reading by that capped list is what made an aggregate silently short:
    # a project past the cap reported a total over the first 5000 positions and
    # called it the project total. When the source told us it had to cut the
    # list, go back to the scope it came from and read the real set.
    if upstream.get("row_ids_truncated"):
        scope_ids: list[uuid.UUID] = []
        for raw_id in upstream.get("source_boq_ids") or []:
            try:
                scope_ids.append(uuid.UUID(str(raw_id)))
            except (ValueError, TypeError):
                continue
        if scope_ids:
            scoped = (
                (
                    await ctx.db.execute(
                        select(Position).where(Position.boq_id.in_(scope_ids)).order_by(Position.sort_order.asc())
                    )
                )
                .scalars()
                .all()
            )
            return [_position_row(p) for p in scoped]

    row_ids = upstream.get("row_ids") or []
    if not row_ids:
        return list(upstream.get("rows") or [])

    ids: list[uuid.UUID] = []
    for rid in row_ids:
        try:
            ids.append(uuid.UUID(str(rid)))
        except (ValueError, TypeError):
            continue
    if not ids:
        return list(upstream.get("rows") or [])

    positions = (await ctx.db.execute(select(Position).where(Position.id.in_(ids)))).scalars().all()
    return [_position_row(p) for p in positions]


# ── trigger.manual ───────────────────────────────────────────────────────


async def _run_trigger_manual(ctx: NodeContext) -> dict[str, Any]:
    """Entry node - seeds the run with the trigger context. No I/O."""
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
    rows = [_position_row(p) for p in positions]
    all_ids = [r["id"] for r in rows]
    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": all_ids[:_ROW_IDS_CAP],
        "row_ids_truncated": len(all_ids) > _ROW_IDS_CAP,
        # The id list is capped to keep the node-state JSON small, which used to
        # mean every downstream total was capped with it. Carrying the source
        # scope instead costs a handful of ids and lets _resolve_full_rows
        # re-read the real set when the id list was cut.
        "source_boq_ids": [str(b) for b in boq_ids],
        "count": len(rows),
        "sample_truncated": len(rows) > _SAMPLE_LIMIT,
        "summary": f"{len(rows)} BOQ positions across {len(boq_ids)} BOQ(s)",
    }


# ── transform.filter ─────────────────────────────────────────────────────


def _matches(row: dict[str, Any], field: str, op: str, value: Any) -> bool:
    """Tiny, safe predicate - no eval, just a fixed operator set."""
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
    # Filter over the FULL row set, not the wire preview. ``rows`` on an
    # envelope is a bounded sample (``_SAMPLE_LIMIT``, 25) that exists for the
    # UI, so reading it here silently reduced every downstream aggregate to at
    # most 25 positions: a source -> filter -> rollup chain reported a grand
    # total over a preview and presented it as the project total. Every other
    # aggregate and gate in this module already resolves the full set the same
    # way.
    rows: list[dict[str, Any]] = await _resolve_full_rows(ctx, upstream)
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
    downstream (write) node is skipped - the structural "AI proposes,
    human confirms" contract enforced at run time.
    """
    from app.core.validation.engine import validation_engine
    from app.core.validation.project_context import with_project_context

    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    rule_sets = ctx.params.get("rule_sets") or ["boq_quality"]

    report = await validation_engine.validate(
        data=await with_project_context(ctx.db, ctx.project_id, {"positions": rows}),
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


def _render_export_xlsx(rows: list[dict[str, Any]], columns: list[Any]) -> int:
    """Write the upstream rows to an in-memory .xlsx and return its size in bytes."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append([str(c) for c in columns])
    for r in rows:
        ws.append([r.get(c, "") for c in columns])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.tell()


async def _run_action_export_excel(ctx: NodeContext) -> dict[str, Any]:
    """Export the upstream rows to an .xlsx using the EXISTING openpyxl dep.

    No new dependency (LIGHTWEIGHT is a hard rule): ``openpyxl`` is already
    used by ``boq.cad_import`` / ``requirements.excel_io`` / many routers.
    ``side_effecting=False`` - it produces a downloadable file, it does not
    mutate any DB row, so it does not require a preceding gate.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    columns = ctx.params.get("columns") or [
        "ordinal",
        "description",
        "unit",
        "quantity",
        "unit_rate",
    ]

    # Building and zipping the workbook is pure CPU (the save alone costs a few
    # milliseconds even for the capped sample), so it runs in a worker thread.
    size = await asyncio.to_thread(_render_export_xlsx, rows, columns)

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


# ── source.cost_catalog ──────────────────────────────────────────────────


async def _run_source_cost_catalog(ctx: NodeContext) -> dict[str, Any]:
    """Load cost-catalog items as rows (code, description, unit, rate).

    Params: ``query`` (optional text match on code or description),
    ``limit`` (optional int, default 200). Rates cross the wire as
    Decimal-as-string, like every other money value. Lets a pipeline pull
    priced reference items to compare against or price a BOQ from.
    """
    from app.modules.costs.models import CostItem

    query = (ctx.params.get("query") or "").strip()
    try:
        limit = int(ctx.params.get("limit") or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, _ROW_IDS_CAP))

    stmt = select(CostItem)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(CostItem.code.ilike(like) | CostItem.description.ilike(like))
    stmt = stmt.order_by(CostItem.code.asc()).limit(limit)

    items = (await ctx.db.execute(stmt)).scalars().all()
    rows = [
        {
            "id": str(it.id),
            "code": it.code,
            "description": it.description,
            "unit": it.unit,
            "unit_rate": it.rate,
            "currency": it.currency,
            "classification": dict(it.classification or {}),
        }
        for it in items
    ]
    all_ids = [r["id"] for r in rows]
    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": all_ids[:_ROW_IDS_CAP],
        "count": len(rows),
        "sample_truncated": len(rows) > _SAMPLE_LIMIT,
        "summary": (f"{len(rows)} cost items" + (f" matching '{query}'" if query else "")),
    }


# ── transform.markup ─────────────────────────────────────────────────────


async def _run_transform_markup(ctx: NodeContext) -> dict[str, Any]:
    """Apply a percentage markup (or discount) to every row's unit rate.

    Params: ``percent`` (number, negative = discount). Recomputes each
    row's ``total`` from the new rate. A what-if transform: it changes the
    rows in place (``mutated``) for preview and downstream totals, it does
    not write back to the BOQ. Money stays Decimal-as-string.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    pct = _to_decimal(ctx.params.get("percent")) or Decimal(0)
    factor = Decimal(1) + pct / Decimal(100)

    out: list[dict[str, Any]] = []
    for r in rows:
        new = dict(r)
        rate = _to_decimal(r.get("unit_rate"))
        if rate is not None:
            new_rate = rate * factor
            new["unit_rate"] = str(new_rate)
            qty = _to_decimal(r.get("quantity"))
            if qty is not None:
                new["total"] = str(qty * new_rate)
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "markup_percent": str(pct),
        "summary": f"Applied {pct}% markup to {len(out)} sample rows",
    }


# ── transform.aggregate ──────────────────────────────────────────────────


async def _run_transform_aggregate(ctx: NodeContext) -> dict[str, Any]:
    """Group rows by a field and sum quantity x unit_rate per group.

    Params: ``group_by`` (a row key, dotted for nested e.g.
    ``classification.din276``; default ``unit``). Computes over the FULL
    row set (re-reading the BOQ when the envelope carries ids), so the
    breakdown reflects every position, not just the sample.
    """
    upstream = ctx.first_input()
    rows = await _resolve_full_rows(ctx, upstream)
    group_by = ctx.params.get("group_by") or "unit"

    buckets: dict[str, dict[str, Any]] = {}
    grand = Decimal(0)
    for r in rows:
        key = _row_value(r, group_by)
        key_str = "(none)" if key in (None, "") else str(key)
        bucket = buckets.setdefault(key_str, {"group": key_str, "count": 0, "_total": Decimal(0)})
        bucket["count"] += 1
        line = _line_total(r)
        bucket["_total"] += line
        grand += line

    grouped = sorted(buckets.values(), key=lambda b: b["_total"], reverse=True)
    out_rows = [{"group": b["group"], "count": b["count"], "total": str(b["_total"])} for b in grouped]
    return {
        "rows": out_rows[:_SAMPLE_LIMIT],
        "count": len(out_rows),
        "group_by": group_by,
        "grand_total": str(grand),
        "row_count": len(rows),
        "mutated": True,
        "summary": (f"{len(out_rows)} groups by '{group_by}' over {len(rows)} rows, total {grand}"),
    }


# ── transform.rollup ─────────────────────────────────────────────────────


async def _run_transform_rollup(ctx: NodeContext) -> dict[str, Any]:
    """Sum quantity x unit_rate across all rows into a single total.

    Computes over the FULL row set (re-reads the BOQ when the envelope
    carries ids). Emits one summary row plus a ``total`` on the envelope so
    a gate or export downstream can use it. Money stays Decimal-as-string.
    """
    upstream = ctx.first_input()
    rows = await _resolve_full_rows(ctx, upstream)

    total = Decimal(0)
    priced = 0
    for r in rows:
        line = _line_total(r)
        total += line
        if line != 0:
            priced += 1

    return {
        "rows": [
            {
                "metric": "Total",
                "count": len(rows),
                "priced": priced,
                "total": str(total),
            }
        ],
        "count": len(rows),
        "priced": priced,
        "total": str(total),
        "mutated": True,
        "summary": f"Total across {len(rows)} rows = {total} ({priced} priced)",
    }


# ── gate.budget ──────────────────────────────────────────────────────────


async def _run_gate_budget(ctx: NodeContext) -> dict[str, Any]:
    """Stop the run when the rows' total exceeds a budget ceiling.

    Params: ``max_total`` (number, required to gate; 0 / blank = no cap).
    Computes the total over the FULL row set. On breach it raises, so the
    run records an error and downstream nodes are skipped - the same
    "human confirms" contract as the validation gate.
    """
    upstream = ctx.first_input()
    rows = await _resolve_full_rows(ctx, upstream)
    total = sum((_line_total(r) for r in rows), Decimal(0))
    cap = _to_decimal(ctx.params.get("max_total"))

    if cap is not None and cap > 0 and total > cap:
        over = total - cap
        raise ValueError(f"Budget gate failed: total {total} exceeds cap {cap} by {over} (over {len(rows)} rows)")

    return {
        "rows": (upstream.get("rows") or [])[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": len(rows),
        "total": str(total),
        "budget": str(cap) if cap is not None else None,
        "summary": (f"Within budget: total {total}" + (f" of {cap}" if cap is not None and cap > 0 else "")),
    }


# ── gate.completeness ────────────────────────────────────────────────────


async def _run_gate_completeness(ctx: NodeContext) -> dict[str, Any]:
    """Flag rows with a missing quantity or a zero / missing unit rate.

    Params: ``mode`` (``warn`` (default) or ``block``). Computes over the
    FULL row set. In ``block`` mode any incomplete row raises and stops the
    run; in ``warn`` mode the run continues but the counts and the first
    offending ordinals are reported so the estimator can fix them.
    """
    upstream = ctx.first_input()
    rows = await _resolve_full_rows(ctx, upstream)
    mode = (ctx.params.get("mode") or "warn").strip().lower()

    missing_qty: list[str] = []
    missing_rate: list[str] = []
    for r in rows:
        label = str(r.get("ordinal") or r.get("code") or r.get("id") or "?")
        qty = _to_decimal(r.get("quantity"))
        rate = _to_decimal(r.get("unit_rate"))
        if qty is None or qty <= 0:
            missing_qty.append(label)
        if rate is None or rate <= 0:
            missing_rate.append(label)

    incomplete = len(set(missing_qty) | set(missing_rate))
    if mode == "block" and incomplete > 0:
        raise ValueError(
            f"Completeness gate failed: {len(missing_qty)} rows missing quantity, "
            f"{len(missing_rate)} missing a unit rate (e.g. {(missing_qty + missing_rate)[:5]})"
        )

    return {
        "rows": (upstream.get("rows") or [])[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": len(rows),
        "missing_quantity": len(missing_qty),
        "missing_unit_rate": len(missing_rate),
        "complete": incomplete == 0,
        "summary": (
            f"Complete: all {len(rows)} rows have a quantity and a rate"
            if incomplete == 0
            else (
                f"{incomplete} of {len(rows)} rows incomplete ({len(missing_qty)} no qty, {len(missing_rate)} no rate)"
            )
        ),
    }


# ── flow.merge ───────────────────────────────────────────────────────────


async def _run_flow_merge(ctx: NodeContext) -> dict[str, Any]:
    """Combine the rows from every connected upstream node into one set.

    Params: ``dedupe`` (bool, default true - drop rows whose ``id`` was
    already seen). Fills the ``flow`` category so two branches (e.g. two
    filtered subsets, or a BOQ plus catalog rows) can be brought back
    together before an export or total.
    """
    dedupe = ctx.params.get("dedupe", True)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    all_ids: list[str] = []
    total_count = 0

    for env in ctx.inputs.values():
        if not isinstance(env, dict):
            continue
        rows = env.get("rows") or []
        total_count += int(env.get("count", len(rows)) or 0)
        for rid in env.get("row_ids") or []:
            all_ids.append(str(rid))
        for r in rows:
            rid = r.get("id")
            if dedupe and rid:
                if rid in seen:
                    continue
                seen.add(rid)
            merged.append(r)

    return {
        "rows": merged[:_SAMPLE_LIMIT],
        "row_ids": all_ids[:_ROW_IDS_CAP],
        "count": len(merged) if dedupe else total_count,
        "inputs_merged": len(ctx.inputs),
        "summary": f"Merged {len(ctx.inputs)} inputs into {len(merged)} rows",
    }


# ── transform.sort ───────────────────────────────────────────────────────


async def _run_transform_sort(ctx: NodeContext) -> dict[str, Any]:
    """Sort rows by a field, numerically when possible else alphabetically.

    Params: ``field`` (row key, dotted allowed), ``descending`` (bool).
    Marks the envelope ``mutated`` so the order (and any downstream top-N)
    is preserved. Pass-through when no field is given.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    desc = bool(ctx.params.get("descending", False))

    if field:

        def _key(r: dict[str, Any]) -> tuple[int, Any]:
            value = _row_value(r, field)
            num = _to_decimal(value)
            if num is not None:
                return (0, num)
            return (1, str(value).lower() if value is not None else "")

        rows = sorted(rows, key=_key, reverse=desc)

    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(rows)),
        "mutated": True,
        "summary": (
            f"Sorted by {field} ({'high to low' if desc else 'low to high'})"
            if field
            else f"No sort field ({len(rows)} rows)"
        ),
    }


# ── transform.limit ──────────────────────────────────────────────────────


async def _run_transform_limit(ctx: NodeContext) -> dict[str, Any]:
    """Keep only the first N rows (pair with sort for a top-N).

    Params: ``count`` (int, default 10).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    try:
        n = int(ctx.params.get("count") or 10)
    except (TypeError, ValueError):
        n = 10
    n = max(0, n)
    kept = rows[:n]
    kept_ids = [r.get("id") for r in kept if r.get("id")]
    return {
        "rows": kept[:_SAMPLE_LIMIT],
        "row_ids": kept_ids[:_ROW_IDS_CAP],
        "count": len(kept),
        "mutated": True,
        "summary": f"Kept first {len(kept)} of {len(rows)} rows",
    }


# ── transform.dedupe ─────────────────────────────────────────────────────


async def _run_transform_dedupe(ctx: NodeContext) -> dict[str, Any]:
    """Drop rows that repeat a value in a key field.

    Params: ``field`` (row key, default ``id``). Keeps first occurrence.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field") or "id"

    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for r in rows:
        key = str(_row_value(r, field))
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)

    kept_ids = [r.get("id") for r in kept if r.get("id")]
    return {
        "rows": kept[:_SAMPLE_LIMIT],
        "row_ids": kept_ids[:_ROW_IDS_CAP],
        "count": len(kept),
        "dropped": len(rows) - len(kept),
        "mutated": True,
        "summary": f"Kept {len(kept)} unique of {len(rows)} rows by {field}",
    }


# ── gate.count ───────────────────────────────────────────────────────────


async def _run_gate_count(ctx: NodeContext) -> dict[str, Any]:
    """Require the row count to sit within a range, else stop the run.

    Params: ``min_rows`` (int, default 1), ``max_rows`` (int, 0 = no cap).
    Uses the envelope's full ``count`` (not just the preview), so an empty
    or oversized upstream is caught before a downstream action.
    """
    upstream = ctx.first_input()
    count = int(upstream.get("count") or len(upstream.get("rows") or []))
    raw_min = ctx.params.get("min_rows")
    try:
        min_rows = int(raw_min if raw_min is not None else 1)
    except (TypeError, ValueError):
        min_rows = 1
    try:
        max_rows = int(ctx.params.get("max_rows") or 0)
    except (TypeError, ValueError):
        max_rows = 0

    if count < min_rows:
        raise ValueError(f"Count gate failed: {count} rows is below the minimum {min_rows}")
    if max_rows and count > max_rows:
        raise ValueError(f"Count gate failed: {count} rows is above the maximum {max_rows}")

    return {
        "rows": (upstream.get("rows") or [])[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": count,
        "summary": f"Count OK: {count} rows",
    }


# ── action.export.csv ────────────────────────────────────────────────────


async def _run_action_export_csv(ctx: NodeContext) -> dict[str, Any]:
    """Export the upstream rows to a CSV file using the stdlib csv module.

    No new dependency. Like the Excel action it returns a file reference +
    metadata (the bytes are persisted by a later phase), so it does not
    mutate the database and needs no preceding gate.
    """
    import csv

    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    columns = ctx.params.get("columns") or [
        "ordinal",
        "description",
        "unit",
        "quantity",
        "unit_rate",
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([str(c) for c in columns])
    for r in rows:
        writer.writerow([r.get(c, "") for c in columns])
    size = len(buf.getvalue().encode("utf-8"))

    return {
        "file": {
            "filename": ctx.params.get("filename", "pipeline-export.csv"),
            "content_type": "text/csv",
            "size_bytes": size,
            "row_count": len(rows),
            "columns": list(columns),
        },
        "summary": f"Exported {len(rows)} rows → CSV ({size} bytes)",
    }


# ── transform.compute ────────────────────────────────────────────────────


async def _run_transform_compute(ctx: NodeContext) -> dict[str, Any]:
    """Add a derived numeric column computed from two operands per row.

    Params: ``target`` (new field name), ``left`` (a row field name),
    ``op`` (add|subtract|multiply|divide), ``right`` (a row field name OR a
    numeric literal - resolved as a field first, then parsed as a number).
    Arithmetic uses Decimal; a divide-by-zero (or any unparseable operand)
    leaves the target ``None`` for that row rather than crashing. A what-if
    transform: it changes the rows in place (``mutated``) for preview and
    downstream totals, it does not write back to the BOQ.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    target = ctx.params.get("target")
    left = ctx.params.get("left")
    op = (ctx.params.get("op") or "add").strip().lower()
    right = ctx.params.get("right")

    def _operand(row: dict[str, Any], spec: Any) -> Decimal | None:
        """Resolve an operand as a row field first, else a numeric literal."""
        if isinstance(spec, str):
            field_val = _row_value(row, spec)
            if field_val is not None:
                return _to_decimal(field_val)
        return _to_decimal(spec)

    out: list[dict[str, Any]] = []
    computed = 0
    for r in rows:
        new = dict(r)
        a = _operand(r, left) if left else None
        b = _operand(r, right)
        result: Decimal | None = None
        if a is not None and b is not None:
            if op == "add":
                result = a + b
            elif op == "subtract":
                result = a - b
            elif op == "multiply":
                result = a * b
            elif op == "divide":
                result = a / b if b != 0 else None
        if target:
            new[target] = str(result) if result is not None else None
        if result is not None:
            computed += 1
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "summary": (f"Computed '{target}' = {left} {op} {right} for {computed} of {len(out)} rows"),
    }


# ── transform.group ──────────────────────────────────────────────────────


async def _run_transform_group(ctx: NodeContext) -> dict[str, Any]:
    """Group rows by a field and emit one summary row per group.

    Params: ``by`` (a row field, dotted allowed), ``sum_field`` (optional
    numeric field to total per group). Each output row is
    ``{id, group, count, sum}`` where ``sum`` is the group total (or None
    when no ``sum_field`` is given). Computes over the FULL row set (re-reads
    the BOQ when the envelope carries ids). A summarising transform, so it
    marks the envelope ``mutated``.
    """
    upstream = ctx.first_input()
    rows = await _resolve_full_rows(ctx, upstream)
    by = ctx.params.get("by")
    sum_field = ctx.params.get("sum_field")

    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = _row_value(r, by) if by else None
        key_str = "(none)" if key in (None, "") else str(key)
        bucket = buckets.setdefault(key_str, {"group": key_str, "count": 0, "_sum": Decimal(0)})
        bucket["count"] += 1
        if sum_field:
            val = _to_decimal(_row_value(r, sum_field))
            if val is not None:
                bucket["_sum"] += val

    out_rows = [
        {
            "id": b["group"],
            "group": b["group"],
            "count": b["count"],
            "sum": (str(b["_sum"]) if sum_field else None),
        }
        for b in buckets.values()
    ]
    return {
        "rows": out_rows[:_SAMPLE_LIMIT],
        "count": len(out_rows),
        "group_by": by,
        "row_count": len(rows),
        "mutated": True,
        "summary": f"Grouped into {len(out_rows)} groups by {by!r}",
    }


# ── transform.rename ─────────────────────────────────────────────────────


async def _run_transform_rename(ctx: NodeContext) -> dict[str, Any]:
    """Copy or rename a field on every row.

    Params: ``from`` (source field name), ``to`` (destination field name),
    ``keep_original`` (bool, default false - drop the source field after the
    copy). Missing source values copy through as-is (None). A what-if
    transform: it changes the rows in place (``mutated``).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    src = ctx.params.get("from")
    dst = ctx.params.get("to")
    keep_original = bool(ctx.params.get("keep_original", False))

    out: list[dict[str, Any]] = []
    renamed = 0
    for r in rows:
        new = dict(r)
        if src and dst:
            new[dst] = new.get(src)
            if not keep_original and src != dst and src in new:
                del new[src]
            renamed += 1
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "summary": (
            f"Renamed '{src}' to '{dst}' on {renamed} rows"
            if src and dst
            else f"No rename fields given ({len(out)} rows)"
        ),
    }


# ── gate.threshold ───────────────────────────────────────────────────────


async def _run_gate_threshold(ctx: NodeContext) -> dict[str, Any]:
    """Aggregate a numeric field across rows and stop when a limit is broken.

    Params: ``field`` (a row field; when empty the envelope ``count`` is
    used), ``agg`` (sum|avg|max|min|count, default sum), ``op`` (lt|lte|gt|
    gte - the ALLOWED condition), ``value`` (the comparison number). The
    aggregate is computed over the FULL row set; when the aggregate FAILS the
    allowed condition the gate raises, so the run records an error and every
    downstream node is skipped - the same "human confirms" contract as the
    budget gate. Rows pass through unchanged on success.
    """
    upstream = ctx.first_input()
    rows = await _resolve_full_rows(ctx, upstream)
    field = ctx.params.get("field")
    agg = (ctx.params.get("agg") or "sum").strip().lower()
    op = (ctx.params.get("op") or "gte").strip().lower()
    limit = _to_decimal(ctx.params.get("value"))

    if not field:
        aggregate = Decimal(int(upstream.get("count") or len(rows)))
    else:
        nums = [n for n in (_to_decimal(_row_value(r, field)) for r in rows) if n is not None]
        if agg == "count":
            aggregate = Decimal(len(rows))
        elif not nums:
            aggregate = Decimal(0)
        elif agg == "avg":
            aggregate = sum(nums, Decimal(0)) / Decimal(len(nums))
        elif agg == "max":
            aggregate = max(nums)
        elif agg == "min":
            aggregate = min(nums)
        else:  # sum (default)
            aggregate = sum(nums, Decimal(0))

    field_label = field or "count"
    if limit is not None:
        allowed = {
            "lt": aggregate < limit,
            "lte": aggregate <= limit,
            "gt": aggregate > limit,
            "gte": aggregate >= limit,
        }.get(op, True)
        if not allowed:
            raise ValueError(
                f"Threshold gate failed: {agg}({field_label}) = {aggregate} is not {op} {limit} (over {len(rows)} rows)"
            )

    return {
        "rows": (upstream.get("rows") or [])[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(rows)),
        "aggregate": str(aggregate),
        "summary": (
            f"Threshold OK: {agg}({field_label}) = {aggregate}" + (f" {op} {limit}" if limit is not None else "")
        ),
    }


# ── source.validation_findings ───────────────────────────────────────────


async def _run_source_validation_findings(ctx: NodeContext) -> dict[str, Any]:
    """Load the latest validation report's findings for the project as rows.

    Reads the most recent :class:`ValidationReport` for the bound project and
    emits each stored result as a row ``{id, rule_id, status, message}`` so a
    pipeline can filter, count or export the outstanding findings. The report
    ``results`` column already holds the per-rule outcomes, so no re-run of
    the validation engine is needed. Returns an empty set (never raises) when
    the project has no report yet.
    """
    from app.modules.validation.models import ValidationReport

    pid = _resolve_project_id(ctx)
    if pid is None:
        return {"rows": [], "row_ids": [], "count": 0, "summary": "No project bound"}

    report = (
        await ctx.db.execute(
            select(ValidationReport)
            .where(ValidationReport.project_id == pid)
            .order_by(ValidationReport.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if report is None:
        return {"rows": [], "row_ids": [], "count": 0, "summary": "No validation report yet"}

    rows: list[dict[str, Any]] = []
    for idx, result in enumerate(report.results or []):
        if not isinstance(result, dict):
            continue
        rows.append(
            {
                "id": str(result.get("element_ref") or f"finding-{idx}"),
                "rule_id": result.get("rule_id"),
                "status": result.get("status"),
                "message": result.get("message"),
            }
        )
    all_ids = [r["id"] for r in rows]
    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": all_ids[:_ROW_IDS_CAP],
        "count": len(rows),
        "sample_truncated": len(rows) > _SAMPLE_LIMIT,
        "summary": (f"{len(rows)} findings from the latest {report.status} report"),
    }


# ── flow.tee ─────────────────────────────────────────────────────────────


async def _run_flow_tee(ctx: NodeContext) -> dict[str, Any]:
    """Pass rows straight through unchanged (an explicit fan-out marker).

    A documentation / branching node: it does nothing to the rows but makes a
    template's intent clear when one source feeds two downstream chains.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    count = int(upstream.get("count") or len(rows))
    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": count,
        "mutated": False,
        "summary": f"Passed {count} rows through",
    }


# ── gate.non_empty ───────────────────────────────────────────────────────


async def _run_gate_non_empty(ctx: NodeContext) -> dict[str, Any]:
    """Stop the run when there are zero rows; pass through otherwise.

    A common guard so a downstream action never fires on an empty result.
    Uses the envelope's full ``count`` (not just the preview), then raises
    when it is zero - the same stop mechanism as the other gates.
    """
    upstream = ctx.first_input()
    count = int(upstream.get("count") or len(upstream.get("rows") or []))
    if count == 0:
        raise ValueError("Non-empty gate failed: the upstream produced 0 rows")
    return {
        "rows": (upstream.get("rows") or [])[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": count,
        "summary": f"Non-empty OK: {count} rows",
    }


# ── transform.round ──────────────────────────────────────────────────────


async def _run_transform_round(ctx: NodeContext) -> dict[str, Any]:
    """Round a numeric field to N decimal places on every row.

    Params: ``field`` (the numeric row key to round), ``places`` (int, how
    many decimals - default 2), ``target`` (optional destination field;
    defaults to overwriting ``field`` in place). Uses Decimal ``quantize``
    (banker's-free ROUND_HALF_UP) so money keeps its exact string form.
    Non-numeric or missing values pass through untouched. A what-if
    transform: it changes the rows in place (``mutated``).
    """
    from decimal import ROUND_HALF_UP

    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    target = ctx.params.get("target") or field
    try:
        places = int(ctx.params.get("places"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        places = 2
    places = max(0, places)
    quant = Decimal(1).scaleb(-places)  # e.g. places=2 → Decimal("0.01")

    out: list[dict[str, Any]] = []
    rounded = 0
    for r in rows:
        new = dict(r)
        if field:
            num = _to_decimal(_row_value(r, field))
            if num is not None:
                new[target] = str(num.quantize(quant, rounding=ROUND_HALF_UP))
                rounded += 1
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "summary": (
            f"Rounded '{field}' to {places} dp on {rounded} of {len(out)} rows"
            if field
            else f"No field to round ({len(out)} rows)"
        ),
    }


# ── transform.currency_convert ───────────────────────────────────────────


async def _run_transform_currency_convert(ctx: NodeContext) -> dict[str, Any]:
    """Convert a money field by a static exchange rate.

    Params: ``field`` (money row key, default ``unit_rate``), ``rate``
    (multiplier - e.g. 1.08 for EUR→USD), ``target`` (optional destination;
    defaults to overwriting ``field``), ``currency`` (optional new currency
    code to stamp on the row's ``currency`` field). When the field is
    ``unit_rate`` the row's ``total`` is recomputed from the new rate so a
    downstream rollup stays consistent. Money stays Decimal-as-string. A
    what-if transform (``mutated``): it does not write back to the BOQ.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field") or "unit_rate"
    target = ctx.params.get("target") or field
    currency = ctx.params.get("currency")
    rate = _to_decimal(ctx.params.get("rate"))

    out: list[dict[str, Any]] = []
    converted = 0
    for r in rows:
        new = dict(r)
        if rate is not None:
            money = _to_decimal(_row_value(r, field))
            if money is not None:
                new_money = money * rate
                new[target] = str(new_money)
                converted += 1
                if target == "unit_rate":
                    qty = _to_decimal(r.get("quantity"))
                    if qty is not None:
                        new["total"] = str(qty * new_money)
            if currency:
                new["currency"] = str(currency)
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "rate": str(rate) if rate is not None else None,
        "summary": (
            f"Converted '{field}' by x{rate} on {converted} of {len(out)} rows" + (f" → {currency}" if currency else "")
            if rate is not None
            else f"No rate given ({len(out)} rows)"
        ),
    }


# ── transform.map_values ─────────────────────────────────────────────────


async def _run_transform_map_values(ctx: NodeContext) -> dict[str, Any]:
    """Remap a field's values through a small ``{from: to}`` dictionary.

    Params: ``field`` (the row key to remap), ``mapping`` (dict of
    old-value → new-value; keys compared as strings), ``target`` (optional
    destination field; defaults to overwriting ``field``), ``keep_unmapped``
    (bool, default true - a value absent from the mapping passes through
    unchanged; set false to blank it). Handy to normalise unit codes or
    relabel trade names. A what-if transform (``mutated``).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    target = ctx.params.get("target") or field
    raw_mapping = ctx.params.get("mapping")
    mapping = {str(k): v for k, v in raw_mapping.items()} if isinstance(raw_mapping, dict) else {}
    keep_unmapped = bool(ctx.params.get("keep_unmapped", True))

    out: list[dict[str, Any]] = []
    remapped = 0
    for r in rows:
        new = dict(r)
        if field:
            current = _row_value(r, field)
            key = str(current)
            if key in mapping:
                new[target] = mapping[key]
                remapped += 1
            elif not keep_unmapped:
                new[target] = None
            elif target != field:
                new[target] = current
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "summary": (
            f"Remapped '{field}' on {remapped} of {len(out)} rows ({len(mapping)} rules)"
            if field
            else f"No field to map ({len(out)} rows)"
        ),
    }


# ── transform.split ──────────────────────────────────────────────────────


async def _run_transform_split(ctx: NodeContext) -> dict[str, Any]:
    """Partition rows into a matched primary set and an unmatched remainder.

    Params: ``field`` / ``op`` / ``value`` - the same predicate the Filter
    node uses (op in eq|ne|contains|gt|gte|lt|lte|exists). The rows that
    match travel out the primary ``rows`` path; the rest are exposed as
    ``unmatched_rows`` / ``unmatched_row_ids`` on the same envelope with a
    count, so a template can document a two-way branch. With no predicate
    everything is treated as matched.
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    op = ctx.params.get("op", "eq")
    value = ctx.params.get("value")

    if not field:
        matched, unmatched = rows, []
    else:
        matched = [r for r in rows if _matches(r, field, op, value)]
        unmatched = [r for r in rows if not _matches(r, field, op, value)]

    matched_ids = [r.get("id") for r in matched if r.get("id")]
    unmatched_ids = [r.get("id") for r in unmatched if r.get("id")]
    return {
        "rows": matched[:_SAMPLE_LIMIT],
        "row_ids": matched_ids[:_ROW_IDS_CAP],
        "count": len(matched),
        "unmatched_rows": unmatched[:_SAMPLE_LIMIT],
        "unmatched_row_ids": unmatched_ids[:_ROW_IDS_CAP],
        "unmatched_count": len(unmatched),
        "summary": (
            f"Split {len(rows)} rows: {len(matched)} matched, {len(unmatched)} not ({field} {op} {value!r})"
            if field
            else f"All {len(rows)} rows matched (no predicate)"
        ),
    }


# ── transform.join ───────────────────────────────────────────────────────


async def _run_transform_join(ctx: NodeContext) -> dict[str, Any]:
    """Merge two upstream branches on a shared key field.

    Params: ``key`` (field present on both sides; or ``left_key`` /
    ``right_key`` when the names differ), ``how`` (``inner`` (default) keeps
    only left rows with a right match, ``left`` keeps every left row),
    ``prefix`` (optional string prepended to the right side's field names so
    they never clobber the left's). The first connected branch is the left
    side, the second is the right - the same iteration order the Merge node
    uses. A right row's fields are folded onto the matching left row.
    """
    envelopes = [env for env in ctx.inputs.values() if isinstance(env, dict)]
    left_env = envelopes[0] if envelopes else {}
    right_env = envelopes[1] if len(envelopes) > 1 else {}
    left_rows = list(left_env.get("rows") or [])
    right_rows = list(right_env.get("rows") or [])

    key = ctx.params.get("key")
    left_key = ctx.params.get("left_key") or key
    right_key = ctx.params.get("right_key") or key
    how = (ctx.params.get("how") or "inner").strip().lower()
    prefix = ctx.params.get("prefix") or ""

    right_index: dict[str, dict[str, Any]] = {}
    if right_key:
        for rr in right_rows:
            rk = _row_value(rr, right_key)
            if rk is not None:
                right_index.setdefault(str(rk), rr)

    out: list[dict[str, Any]] = []
    joined = 0
    for lr in left_rows:
        lk = _row_value(lr, left_key) if left_key else None
        match = right_index.get(str(lk)) if lk is not None else None
        if match is None:
            if how == "left":
                out.append(dict(lr))
            continue
        merged = dict(lr)
        for k, v in match.items():
            if prefix:
                merged[f"{prefix}{k}"] = v
            elif k not in merged:
                merged[k] = v
        out.append(merged)
        joined += 1

    out_ids = [r.get("id") for r in out if r.get("id")]
    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": out_ids[:_ROW_IDS_CAP],
        "count": len(out),
        "mutated": True,
        "joined": joined,
        "summary": (f"{how} join on '{left_key}': {joined} of {len(left_rows)} left rows matched a right row"),
    }


# ── transform.running_total ──────────────────────────────────────────────


async def _run_transform_running_total(ctx: NodeContext) -> dict[str, Any]:
    """Add a cumulative running total of a numeric field, in row order.

    Params: ``field`` (numeric row key to accumulate; when blank each row
    counts as 1, giving a running row index), ``target`` (new column name,
    default ``running_total``). Order-dependent, so it accumulates over the
    rows exactly as they arrive - pair it with Sort for a meaningful cumulative
    curve. Money stays Decimal-as-string. A what-if transform (``mutated``).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    target = ctx.params.get("target") or "running_total"

    out: list[dict[str, Any]] = []
    running = Decimal(0)
    for r in rows:
        new = dict(r)
        step = _to_decimal(_row_value(r, field)) if field else Decimal(1)
        running += step if step is not None else Decimal(0)
        new[target] = str(running)
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "final_total": str(running),
        "summary": (f"Running total of '{field or 'row count'}' → '{target}' over {len(out)} rows (ends {running})"),
    }


# ── transform.percent_of_total ───────────────────────────────────────────


async def _run_transform_percent_of_total(ctx: NodeContext) -> dict[str, Any]:
    """Add each row's share (%) of a field's grand total.

    Params: ``field`` (numeric row key; when blank each row's quantity x
    unit_rate line total is used), ``target`` (new column name, default
    ``pct_of_total``), ``places`` (decimals on the percent, default 1).
    Computes the denominator over the FULL row set (re-reading the BOQ when
    the envelope carries ids) so the percentages are honest, not sample-only.
    A summarising what-if transform (``mutated``).
    """
    from decimal import ROUND_HALF_UP

    upstream = ctx.first_input()
    rows = await _resolve_full_rows(ctx, upstream)
    field = ctx.params.get("field")
    target = ctx.params.get("target") or "pct_of_total"
    try:
        places = int(ctx.params.get("places"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        places = 1
    places = max(0, places)
    quant = Decimal(1).scaleb(-places)

    def _measure(row: dict[str, Any]) -> Decimal:
        if field:
            return _to_decimal(_row_value(row, field)) or Decimal(0)
        return _line_total(row)

    total = sum((_measure(r) for r in rows), Decimal(0))

    out: list[dict[str, Any]] = []
    for r in rows:
        new = dict(r)
        share = (_measure(r) / total * Decimal(100)) if total != 0 else Decimal(0)
        new[target] = str(share.quantize(quant, rounding=ROUND_HALF_UP))
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "count": len(out),
        "grand_total": str(total),
        "mutated": True,
        "summary": (f"Added '{target}' (share of {field or 'line total'}) over {len(out)} rows, total {total}"),
    }


# ── transform.fill_missing ───────────────────────────────────────────────


async def _run_transform_fill_missing(ctx: NodeContext) -> dict[str, Any]:
    """Fill blank / missing values in a field with a default.

    Params: ``field`` (row key to fill), ``value`` (the fill value). A value
    is considered missing when it is absent, ``None`` or an empty string;
    populated values are left untouched. Useful to default a unit, a rate or
    a classification before a downstream gate. A what-if transform (``mutated``).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    fill = ctx.params.get("value")

    out: list[dict[str, Any]] = []
    filled = 0
    for r in rows:
        new = dict(r)
        if field:
            current = new.get(field)
            if current in (None, ""):
                new[field] = fill
                filled += 1
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "summary": (
            f"Filled '{field}' on {filled} of {len(out)} rows" if field else f"No field to fill ({len(out)} rows)"
        ),
    }


# ── transform.clamp ──────────────────────────────────────────────────────


async def _run_transform_clamp(ctx: NodeContext) -> dict[str, Any]:
    """Clamp a numeric field into a ``[min, max]`` range.

    Params: ``field`` (numeric row key), ``min`` (lower bound, optional),
    ``max`` (upper bound, optional), ``target`` (optional destination;
    defaults to overwriting ``field``). A value below ``min`` becomes ``min``,
    above ``max`` becomes ``max``; a blank bound is not enforced on that side.
    Non-numeric values pass through. Money stays Decimal-as-string. A what-if
    transform (``mutated``).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    field = ctx.params.get("field")
    target = ctx.params.get("target") or field
    lo = _to_decimal(ctx.params.get("min"))
    hi = _to_decimal(ctx.params.get("max"))

    out: list[dict[str, Any]] = []
    clamped = 0
    for r in rows:
        new = dict(r)
        if field:
            num = _to_decimal(_row_value(r, field))
            if num is not None:
                bounded = num
                if lo is not None and bounded < lo:
                    bounded = lo
                if hi is not None and bounded > hi:
                    bounded = hi
                new[target] = str(bounded)
                if bounded != num:
                    clamped += 1
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "summary": (
            f"Clamped '{field}' to [{lo}, {hi}] on {clamped} of {len(out)} rows"
            if field
            else f"No field to clamp ({len(out)} rows)"
        ),
    }


# ── transform.concat ─────────────────────────────────────────────────────


async def _run_transform_concat(ctx: NodeContext) -> dict[str, Any]:
    """Join several fields into one text column.

    Params: ``fields`` (list of row keys, dotted allowed, read in order),
    ``target`` (new column name, default ``combined``), ``separator`` (string
    placed between parts, default a single space). Missing / blank parts are
    skipped so the separator never doubles up. Handy to build a full position
    description from code + trade + material. A what-if transform (``mutated``).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    raw_fields = ctx.params.get("fields")
    fields = [str(f) for f in raw_fields] if isinstance(raw_fields, list) else []
    target = ctx.params.get("target") or "combined"
    sep = ctx.params.get("separator")
    sep = " " if sep is None else str(sep)

    out: list[dict[str, Any]] = []
    for r in rows:
        new = dict(r)
        parts = [str(v) for f in fields if (v := _row_value(r, f)) not in (None, "")]
        new[target] = sep.join(parts)
        out.append(new)

    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": upstream.get("row_ids") or [],
        "count": upstream.get("count", len(out)),
        "mutated": True,
        "summary": (
            f"Joined {len(fields)} fields into '{target}' on {len(out)} rows"
            if fields
            else f"No fields to join ({len(out)} rows)"
        ),
    }


# ── source.constant ──────────────────────────────────────────────────────


async def _run_source_constant(ctx: NodeContext) -> dict[str, Any]:
    """Emit a fixed set of literal rows supplied as a param.

    Params: ``rows`` (a list of dict rows to emit verbatim). Each row gets a
    generated ``id`` when it lacks one so downstream id-based nodes (dedupe,
    merge, join) still work. A no-I/O seed for demos, tests and small fixed
    lookup / reference tables - the pipeline equivalent of a literal.
    """
    raw = ctx.params.get("rows")
    source_rows = raw if isinstance(raw, list) else []

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(source_rows):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if not row.get("id"):
            row["id"] = f"const-{idx}"
        rows.append(row)

    all_ids = [r["id"] for r in rows]
    return {
        "rows": rows[:_SAMPLE_LIMIT],
        "row_ids": all_ids[:_ROW_IDS_CAP],
        "count": len(rows),
        "sample_truncated": len(rows) > _SAMPLE_LIMIT,
        "summary": f"Emitted {len(rows)} literal rows",
    }


# ── enrich.lookup ────────────────────────────────────────────────────────


async def _run_enrich_lookup(ctx: NodeContext) -> dict[str, Any]:
    """Enrich rows against an inline lookup table keyed by a field value.

    Params: ``key`` (row field whose value is the lookup key), ``table``
    (dict of key → {field: value, …} to fold onto the row), ``prefix``
    (optional string prepended to the added field names so they never clobber
    existing ones), ``keep_unmatched`` (bool, default true - a row whose key
    is absent from the table passes through unchanged; set false to drop it).
    A small dependency-free join against reference data. A what-if transform
    (``mutated``).
    """
    upstream = ctx.first_input()
    rows = list(upstream.get("rows") or [])
    key = ctx.params.get("key")
    raw_table = ctx.params.get("table")
    table = {str(k): v for k, v in raw_table.items() if isinstance(v, dict)} if isinstance(raw_table, dict) else {}
    prefix = ctx.params.get("prefix") or ""
    keep_unmatched = bool(ctx.params.get("keep_unmatched", True))

    out: list[dict[str, Any]] = []
    matched = 0
    for r in rows:
        lookup_val = _row_value(r, key) if key else None
        extra = table.get(str(lookup_val)) if lookup_val is not None else None
        if extra is None:
            if keep_unmatched:
                out.append(dict(r))
            continue
        new = dict(r)
        for k, v in extra.items():
            new[f"{prefix}{k}" if prefix else str(k)] = v
        out.append(new)
        matched += 1

    out_ids = [r.get("id") for r in out if r.get("id")]
    return {
        "rows": out[:_SAMPLE_LIMIT],
        "row_ids": out_ids[:_ROW_IDS_CAP],
        "count": len(out),
        "mutated": True,
        "matched": matched,
        "summary": (
            f"Enriched {matched} of {len(rows)} rows from a {len(table)}-entry table on '{key}'"
            if key
            else f"No lookup key given ({len(rows)} rows)"
        ),
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
        # Produces a file, not a DB mutation - so it needs no preceding gate.
        side_effecting=False,
    )
    register_node(
        type="source.cost_catalog",
        module=MODULE,
        category="source",
        label="Get cost items",
        description="Load priced cost-catalog items as rows (optionally text-filtered).",
        runner=_run_source_cost_catalog,
        inputs=["trigger"],
        outputs=["rows"],
        params_schema={
            "query": {"type": "string", "title": "Search (code or description)"},
            "limit": {"type": "number", "title": "Max items"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.markup",
        module=MODULE,
        category="transform",
        label="Apply markup",
        description="Raise (or discount) every unit rate by a percent and recompute totals.",
        runner=_run_transform_markup,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={"percent": {"type": "number", "title": "Markup %"}},
        side_effecting=False,
    )
    register_node(
        type="transform.aggregate",
        module=MODULE,
        category="transform",
        label="Group and total",
        description="Group rows by a field and sum quantity x unit rate for each group.",
        runner=_run_transform_aggregate,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "group_by": {
                "type": "string",
                "title": "Group by field",
                "description": "e.g. unit, or classification.din276",
            }
        },
        side_effecting=False,
    )
    register_node(
        type="transform.rollup",
        module=MODULE,
        category="transform",
        label="Total cost",
        description="Sum quantity x unit rate across all rows into a single total.",
        runner=_run_transform_rollup,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={},
        side_effecting=False,
    )
    register_node(
        type="gate.budget",
        module=MODULE,
        category="gate",
        label="Budget gate",
        description="Stop the run if the rows' total cost exceeds a budget ceiling.",
        runner=_run_gate_budget,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={"max_total": {"type": "number", "title": "Budget ceiling"}},
        side_effecting=False,
    )
    register_node(
        type="gate.completeness",
        module=MODULE,
        category="gate",
        label="Completeness gate",
        description="Flag or stop on rows missing a quantity or a unit rate.",
        runner=_run_gate_completeness,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "mode": {
                "type": "string",
                "title": "On incomplete",
                "enum": ["warn", "block"],
                "default": "warn",
            }
        },
        side_effecting=False,
    )
    register_node(
        type="flow.merge",
        module=MODULE,
        category="flow",
        label="Merge rows",
        description="Combine the rows from two upstream branches into one set.",
        runner=_run_flow_merge,
        inputs=["rows_a", "rows_b"],
        outputs=["rows"],
        params_schema={"dedupe": {"type": "boolean", "title": "Drop duplicate ids", "default": True}},
        side_effecting=False,
    )
    register_node(
        type="transform.sort",
        module=MODULE,
        category="transform",
        label="Sort rows",
        description="Order rows by a field, numerically or alphabetically.",
        runner=_run_transform_sort,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Sort by field"},
            "descending": {"type": "boolean", "title": "High to low", "default": False},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.limit",
        module=MODULE,
        category="transform",
        label="Keep top N",
        description="Keep only the first N rows (pair with Sort for a top-N).",
        runner=_run_transform_limit,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={"count": {"type": "number", "title": "How many rows"}},
        side_effecting=False,
    )
    register_node(
        type="transform.dedupe",
        module=MODULE,
        category="transform",
        label="Remove duplicates",
        description="Drop rows that repeat a value in a key field.",
        runner=_run_transform_dedupe,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={"field": {"type": "string", "title": "Key field (default id)"}},
        side_effecting=False,
    )
    register_node(
        type="gate.count",
        module=MODULE,
        category="gate",
        label="Count gate",
        description="Stop the run unless the row count is within a range.",
        runner=_run_gate_count,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "min_rows": {"type": "number", "title": "Minimum rows"},
            "max_rows": {"type": "number", "title": "Maximum rows (0 = no cap)"},
        },
        side_effecting=False,
    )
    register_node(
        type="action.export.csv",
        module=MODULE,
        category="action",
        label="Export to CSV",
        description="Write the rows to a .csv file (returns a download reference).",
        runner=_run_action_export_csv,
        inputs=["rows"],
        outputs=["file"],
        params_schema={
            "filename": {"type": "string", "title": "File name"},
            "columns": {"type": "array", "title": "Columns", "items": {"type": "string"}},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.compute",
        module=MODULE,
        category="transform",
        label="Compute a column",
        description="Add a new number column from two fields (or a field and a number).",
        runner=_run_transform_compute,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "target": {"type": "string", "title": "New column name"},
            "left": {"type": "string", "title": "Left field"},
            "op": {
                "type": "string",
                "title": "Operation",
                "enum": ["add", "subtract", "multiply", "divide"],
                "default": "add",
            },
            "right": {"type": "string", "title": "Right field or number"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.group",
        module=MODULE,
        category="transform",
        label="Group rows",
        description="Group rows by a field and count (and optionally total) each group.",
        runner=_run_transform_group,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "by": {"type": "string", "title": "Group by field"},
            "sum_field": {"type": "string", "title": "Field to total (optional)"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.rename",
        module=MODULE,
        category="transform",
        label="Rename a field",
        description="Copy or rename a field on every row.",
        runner=_run_transform_rename,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "from": {"type": "string", "title": "From field"},
            "to": {"type": "string", "title": "To field"},
            "keep_original": {"type": "boolean", "title": "Keep the original", "default": False},
        },
        side_effecting=False,
    )
    register_node(
        type="gate.threshold",
        module=MODULE,
        category="gate",
        label="Threshold gate",
        description="Total or average a field across the rows and stop when it breaks a limit.",
        runner=_run_gate_threshold,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Field (blank = row count)"},
            "agg": {
                "type": "string",
                "title": "How to combine",
                "enum": ["sum", "avg", "max", "min", "count"],
                "default": "sum",
            },
            "op": {
                "type": "string",
                "title": "Allowed when",
                "enum": ["lt", "lte", "gt", "gte"],
            },
            "value": {"type": "number", "title": "Limit"},
        },
        side_effecting=False,
    )
    register_node(
        type="source.validation_findings",
        module=MODULE,
        category="source",
        label="Get validation findings",
        description="Load the latest validation report's findings for the project as rows.",
        runner=_run_source_validation_findings,
        inputs=["trigger", "project"],
        outputs=["rows"],
        params_schema={"project_id": {"type": "string", "title": "Project id (optional)"}},
        side_effecting=False,
    )
    register_node(
        type="flow.tee",
        module=MODULE,
        category="flow",
        label="Tee (fan-out)",
        description="Pass the rows straight through so one source can feed two branches.",
        runner=_run_flow_tee,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={},
        side_effecting=False,
    )
    register_node(
        type="gate.non_empty",
        module=MODULE,
        category="gate",
        label="Not-empty gate",
        description="Stop the run when there are no rows; pass through otherwise.",
        runner=_run_gate_non_empty,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={},
        side_effecting=False,
    )
    register_node(
        type="transform.round",
        module=MODULE,
        category="transform",
        label="Round a number",
        description="Round a numeric field to a set number of decimal places.",
        runner=_run_transform_round,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Field to round"},
            "places": {"type": "number", "title": "Decimal places", "default": 2},
            "target": {"type": "string", "title": "New column (optional)"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.currency_convert",
        module=MODULE,
        category="transform",
        label="Convert currency",
        description="Multiply a money field by an exchange rate and relabel the currency.",
        runner=_run_transform_currency_convert,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Money field (default unit_rate)"},
            "rate": {"type": "number", "title": "Exchange rate"},
            "target": {"type": "string", "title": "New column (optional)"},
            "currency": {"type": "string", "title": "New currency code (optional)"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.map_values",
        module=MODULE,
        category="transform",
        label="Remap values",
        description="Replace a field's values through a small from/to dictionary.",
        runner=_run_transform_map_values,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Field to remap"},
            "mapping": {"type": "object", "title": "Value map (from → to)"},
            "target": {"type": "string", "title": "New column (optional)"},
            "keep_unmapped": {"type": "boolean", "title": "Keep unmapped values", "default": True},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.split",
        module=MODULE,
        category="transform",
        label="Split rows",
        description="Partition rows into a matched set and the unmatched remainder by a predicate.",
        runner=_run_transform_split,
        inputs=["rows"],
        outputs=["matched", "unmatched"],
        params_schema={
            "field": {"type": "string", "title": "Field"},
            "op": {
                "type": "string",
                "title": "Operator",
                "enum": ["eq", "ne", "contains", "gt", "gte", "lt", "lte", "exists"],
            },
            "value": {"title": "Value"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.join",
        module=MODULE,
        category="transform",
        label="Join two branches",
        description="Merge two upstream branches on a shared key field.",
        runner=_run_transform_join,
        inputs=["rows_a", "rows_b"],
        outputs=["rows"],
        params_schema={
            "key": {"type": "string", "title": "Key field (both sides)"},
            "left_key": {"type": "string", "title": "Left key (if different)"},
            "right_key": {"type": "string", "title": "Right key (if different)"},
            "how": {
                "type": "string",
                "title": "Join type",
                "enum": ["inner", "left"],
                "default": "inner",
            },
            "prefix": {"type": "string", "title": "Prefix for right fields (optional)"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.running_total",
        module=MODULE,
        category="transform",
        label="Running total",
        description="Add a cumulative running total of a field, in row order.",
        runner=_run_transform_running_total,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Field to accumulate"},
            "target": {"type": "string", "title": "New column (default running_total)"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.percent_of_total",
        module=MODULE,
        category="transform",
        label="Share of total",
        description="Add each row's percentage share of a field's grand total.",
        runner=_run_transform_percent_of_total,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Field (blank = line total)"},
            "target": {"type": "string", "title": "New column (default pct_of_total)"},
            "places": {"type": "number", "title": "Decimal places", "default": 1},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.fill_missing",
        module=MODULE,
        category="transform",
        label="Fill blanks",
        description="Fill blank or missing values in a field with a default.",
        runner=_run_transform_fill_missing,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Field to fill"},
            "value": {"title": "Fill value"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.clamp",
        module=MODULE,
        category="transform",
        label="Clamp to range",
        description="Constrain a numeric field to a minimum and maximum.",
        runner=_run_transform_clamp,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "field": {"type": "string", "title": "Numeric field"},
            "min": {"type": "number", "title": "Minimum (optional)"},
            "max": {"type": "number", "title": "Maximum (optional)"},
            "target": {"type": "string", "title": "New column (optional)"},
        },
        side_effecting=False,
    )
    register_node(
        type="transform.concat",
        module=MODULE,
        category="transform",
        label="Combine text",
        description="Join several fields into one text column with a separator.",
        runner=_run_transform_concat,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "fields": {"type": "array", "title": "Fields to join", "items": {"type": "string"}},
            "target": {"type": "string", "title": "New column (default combined)"},
            "separator": {"type": "string", "title": "Separator (default space)"},
        },
        side_effecting=False,
    )
    register_node(
        type="source.constant",
        module=MODULE,
        category="source",
        label="Constant rows",
        description="Emit a fixed set of literal rows supplied inline.",
        runner=_run_source_constant,
        inputs=["trigger"],
        outputs=["rows"],
        params_schema={"rows": {"type": "array", "title": "Rows", "items": {"type": "object"}}},
        side_effecting=False,
    )
    register_node(
        type="enrich.lookup",
        module=MODULE,
        category="transform",
        label="Lookup enrich",
        description="Fold reference fields onto rows from an inline lookup table keyed by a field.",
        runner=_run_enrich_lookup,
        inputs=["rows"],
        outputs=["rows"],
        params_schema={
            "key": {"type": "string", "title": "Lookup key field"},
            "table": {"type": "object", "title": "Lookup table (key → fields)"},
            "prefix": {"type": "string", "title": "Prefix for added fields (optional)"},
            "keep_unmatched": {"type": "boolean", "title": "Keep unmatched rows", "default": True},
        },
        side_effecting=False,
    )


register_pipeline_nodes()
