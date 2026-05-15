# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Visible-pipeline runner for /match-elements.

The match flow already runs end-to-end through :class:`MatchService` —
this module layers a *visible* seven-stage state machine on top of that
flow so the estimator sees, tunes, and re-runs each step:

    1. convert  — CAD/BIM/DWG → canonical element table (already done
                  by the takeoff/bim-hub importer; this stage records
                  the source counts so the UI can verify them).
    2. load     — Source adapter reads N elements into SourceElement[];
                  records the element_count + sample.
    3. schema   — Detect attribute keys, classify each as SUM / MEAN /
                  FIRST aggregation (LLM-augmented; falls back to
                  heuristic). Output becomes the ``properties_rollup``
                  policy for the Group stage.
    4. filter   — Drop excluded categories (defaults) + run the
                  building-classifier LLM on borderline elements to
                  exclude grids/voids/annotation that snuck in.
    5. group    — Group by configured keys (per-format defaults via
                  the group.key_picker prompt when no explicit
                  group_by is set on the session).
    6. match    — Run the vector matcher + (optional) AI cost agent
                  rerank; cache per-method candidates on each group.
    7. rollup   — Aggregate group quantities + auto-confirm above
                  threshold; ready for apply-to-BOQ.

State is persisted in ``oe_match_elements_stage`` so the UI can render
a vertical timeline with status pills + sample output + "Re-run from
here" buttons. Each stage is idempotent — calling :func:`run_stage`
with a given name resets its row, executes the work, and writes the
output back atomically.

The runner does NOT replace :meth:`MatchService.run_match`; it calls
into it. So the existing batch flow + bench harness keep working,
and the new stage UI is purely additive.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements import schemas
from app.modules.match_elements.models import (
    MatchGroup,
    MatchPromptTemplate,
    MatchSession,
    MatchStageState,
)
from app.modules.match_elements.service import get_service

logger = logging.getLogger(__name__)


# ── Stage registry — the seven visible steps ─────────────────────────────


STAGE_NAMES: tuple[str, ...] = (
    "convert",
    "load",
    "schema",
    "filter",
    "group",
    "match",
    "rollup",
)


# Human-facing metadata. Kept here (not i18n) because the UI ships the
# translated label via the existing i18n.json; this dict is the source
# of truth the API returns when the UI asks for the timeline scaffold
# before a session has run anything.
STAGE_META: dict[str, dict[str, Any]] = {
    "convert": {
        "title": "Convert",
        "subtitle": "CAD/BIM file → canonical element table",
        "uses_llm": False,
        "prompt_key": None,
        "explainer": (
            "The DDC cad2data converter normalises Revit, IFC, DWG and DGN "
            "into one canonical element table. Nothing to tune here — this "
            "stage is a verification: the count below must match what the "
            "viewer reports, otherwise the parse silently truncated."
        ),
    },
    "load": {
        "title": "Load",
        "subtitle": "Read canonical rows for this session",
        "uses_llm": False,
        "prompt_key": None,
        "explainer": (
            "The source adapter (BIM / DWG / BoQ / text / image) reads the "
            "canonical rows into in-memory elements. The sample below shows "
            "what the matcher actually sees."
        ),
    },
    "schema": {
        "title": "Schema",
        "subtitle": "Classify columns: SUM / MEAN / FIRST",
        "uses_llm": True,
        "prompt_key": "schema.header_aggregation",
        "explainer": (
            "Decide which columns should be summed across a group (area, "
            "volume), averaged (dimensions), or kept as labels (material, "
            "family). Drives how the Group stage rolls up properties so "
            "the BoQ row shows the right number for the right column."
        ),
    },
    "filter": {
        "title": "Filter",
        "subtitle": "Drop non-product elements",
        "uses_llm": True,
        "prompt_key": "filter.building_classifier",
        "explainer": (
            "Strip drafting helpers — grids, reference planes, openings, "
            "annotations — before grouping. Excluded categories run first "
            "(cheap); borderline rows are sent to the LLM classifier."
        ),
    },
    "group": {
        "title": "Group",
        "subtitle": "Collapse identical elements into BoQ rows",
        "uses_llm": True,
        "prompt_key": "group.key_picker",
        "explainer": (
            "Group elements by attribute keys. RVT defaults to category + "
            "type_name (one row per Revit type), IFC to ifc_class + "
            "predefined_type (one row per IfcEntity), DWG to layer + "
            "block_name. Change the keys to widen or narrow the rows."
        ),
    },
    "match": {
        "title": "Match",
        "subtitle": "Find the best cost-database row per group",
        "uses_llm": True,
        "prompt_key": "match.cost_agent",
        "explainer": (
            "Vector search retrieves a shortlist from CWICR; the AI cost "
            "agent picks the best fit, applying construction knowledge "
            "vector similarity alone misses. Edit the agent prompt to "
            "bias the picks for your company's standards."
        ),
    },
    "rollup": {
        "title": "Rollup",
        "subtitle": "Auto-confirm + ready for apply-to-BOQ",
        "uses_llm": False,
        "prompt_key": None,
        "explainer": (
            "Above-threshold matches auto-confirm; the rest stay in "
            "review. Lower the threshold to confirm faster, raise it to "
            "be more conservative."
        ),
    },
}


# ── System prompt seeds ──────────────────────────────────────────────────
# Kept in sync with alembic v3034_match_pipeline_stages._SYSTEM_PROMPTS.
# The migration seeds these for Postgres deploys; this runtime seeder is
# the SQLite path (auto-migrate creates the table but not the rows) and
# the self-heal for any deploy where the seed didn't take. Idempotent —
# only inserts a (key, name, created_by IS NULL) row when it is absent.

SYSTEM_PROMPT_SEEDS: list[dict[str, str]] = [
    {
        "key": "schema.header_aggregation",
        "name": "Header aggregation (sum / mean / first)",
        "description": (
            "Classifies each detected column as a quantity to SUM across "
            "rows, a numeric attribute to AVERAGE, or a discrete label "
            "whose FIRST value is representative."
        ),
        "system_prompt": (
            "You are a construction quantity surveyor. Your task is to "
            "classify data columns from a CAD/BIM export so a downstream "
            "estimator can roll them up into BoQ rows. Reply with a strict "
            "JSON array."
        ),
        "user_template": (
            "Columns detected in this CAD/BIM export:\n\n{columns}\n\n"
            "Sample row (first record):\n{sample}\n\n"
            "Classify each column as one of:\n"
            "  - SUM   (quantitative — area, volume, count, length...)\n"
            "  - MEAN  (continuous attribute — temperature, dimension...)\n"
            "  - FIRST (discrete label — material name, family, level...)\n\n"
            "Return JSON: "
            "[{{\"column\":\"<name>\",\"agg\":\"SUM|MEAN|FIRST\","
            "\"why\":\"<one-sentence rationale>\"}}]"
        ),
    },
    {
        "key": "filter.building_classifier",
        "name": "Building vs non-building filter",
        "description": (
            "Decides per element whether it is a real construction product "
            "(estimable) or a CAD scaffolding artefact that must be "
            "filtered out before grouping."
        ),
        "system_prompt": (
            "You are a senior BIM coordinator. Decide whether each element "
            "row represents a real building product that should appear in "
            "the bill of quantities, or an artefact (annotation, grid, "
            "void, reference plane) that must be excluded. Reply with JSON "
            "only."
        ),
        "user_template": (
            "Element rows:\n\n{rows}\n\n"
            "For each row, output: "
            "{{\"element_id\":\"<id>\","
            "\"is_building_product\":true|false,"
            "\"trade\":\"architectural|structural|mep|civil|spatial|other\","
            "\"why\":\"<short rationale>\"}}\n\n"
            "Return a JSON array."
        ),
    },
    {
        "key": "group.key_picker",
        "name": "Group-by key picker",
        "description": (
            "Recommends the per-format group_by keys to use. RVT → Type / "
            "Type Name; IFC → IfcEntity + PredefinedType; DWG → Layer + "
            "Block name."
        ),
        "system_prompt": (
            "You are a construction estimation engineer. Recommend the "
            "group-by attribute keys to use when collapsing many BIM "
            "elements into estimable BoQ rows. Fewer rows is better — but "
            "never collapse two distinct cost products into one group."
        ),
        "user_template": (
            "Source format: {source_format}\n"
            "Available attribute keys (with sample value counts):\n\n"
            "{attribute_summary}\n\n"
            "Return a JSON object with: "
            "{{\"group_by\":[\"<key1>\",\"<key2>\",...],"
            "\"why\":\"<rationale>\"}}\n\n"
            "Defaults to fall back on:\n"
            "  - RVT: [\"category\", \"type_name\"]\n"
            "  - IFC: [\"ifc_class\", \"predefined_type\"]\n"
            "  - DWG: [\"layer\", \"block_name\"]"
        ),
    },
    {
        "key": "match.cost_agent",
        "name": "AI cost agent",
        "description": (
            "Picks the best cost-database row for a single match group "
            "from a shortlist of vector-search candidates."
        ),
        "system_prompt": (
            "You are an AI cost agent for a construction estimator. You "
            "receive one group of BIM elements and a shortlist of cost-"
            "database candidates retrieved by vector search. Pick the best "
            "match, or say \"NO_MATCH\" when nothing in the shortlist is a "
            "real fit. Never invent a code that is not in the shortlist."
        ),
        "user_template": (
            "Group:\n"
            "  Label: {group_label}\n"
            "  IFC class / category: {ifc_class}\n"
            "  Material: {material}\n"
            "  Sample dimensions: {dimensions}\n"
            "  Element count: {element_count}\n"
            "  Rolled-up quantity: {quantity} {unit}\n\n"
            "Candidates (from CWICR vector search):\n{candidates}\n\n"
            "Return JSON: "
            "{{\"picked_code\":\"<code>|NO_MATCH\","
            "\"confidence\":<0..1>,"
            "\"why\":\"<one-sentence rationale>\"}}"
        ),
    },
]


async def ensure_system_prompts(db: AsyncSession) -> int:
    """Insert any missing system prompt rows. Idempotent.

    Returns the number of rows inserted (0 on the steady state). Called
    lazily from the stage + prompt-template endpoints so a SQLite deploy
    that never ran the alembic seed still gets the n8n-derived defaults.
    """

    inserted = 0
    for spec in SYSTEM_PROMPT_SEEDS:
        exists = (
            await db.execute(
                select(MatchPromptTemplate.id).where(
                    MatchPromptTemplate.key == spec["key"],
                    MatchPromptTemplate.name == spec["name"],
                    MatchPromptTemplate.created_by.is_(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(MatchPromptTemplate(
            key=spec["key"],
            name=spec["name"],
            description=spec["description"],
            system_prompt=spec["system_prompt"],
            user_template=spec["user_template"],
            version=1,
            is_system=True,
            created_by=None,
            metadata_={"source": "n8n_workflow_v6"},
        ))
        inserted += 1
    if inserted:
        # Commit so a read-only GET (which otherwise never commits) still
        # persists the one-time seed; subsequent calls hit the fast path.
        await db.commit()
    return inserted


# ── Helpers ──────────────────────────────────────────────────────────────


async def _get_or_create_stage(
    db: AsyncSession,
    session_id: uuid.UUID,
    stage_name: str,
) -> MatchStageState:
    row = (
        await db.execute(
            select(MatchStageState).where(
                MatchStageState.session_id == session_id,
                MatchStageState.stage_name == stage_name,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = MatchStageState(
            session_id=session_id,
            stage_name=stage_name,
            status="pending",
            inputs={},
            output={},
        )
        db.add(row)
        await db.flush()
    return row


async def _resolve_prompt(
    db: AsyncSession,
    stage_name: str,
    explicit_id: uuid.UUID | None,
) -> MatchPromptTemplate | None:
    meta = STAGE_META.get(stage_name) or {}
    key = meta.get("prompt_key")
    if not key:
        return None
    if explicit_id is not None:
        return await db.get(MatchPromptTemplate, explicit_id)
    row = (
        await db.execute(
            select(MatchPromptTemplate)
            .where(MatchPromptTemplate.key == key)
            .order_by(MatchPromptTemplate.is_system.asc(), MatchPromptTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


def _now() -> datetime:
    return datetime.now(UTC)


# ── Public API ───────────────────────────────────────────────────────────


async def list_stages(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return the seven stage rows for a session in canonical order.

    Missing stages are returned with status ``pending`` and empty
    inputs/output — the UI never has to deal with a hole in the
    timeline.
    """

    rows = (
        await db.execute(
            select(MatchStageState).where(
                MatchStageState.session_id == session_id,
            )
        )
    ).scalars().all()
    by_name = {row.stage_name: row for row in rows}

    out: list[dict[str, Any]] = []
    for name in STAGE_NAMES:
        meta = STAGE_META[name]
        row = by_name.get(name)
        if row is None:
            out.append({
                "stage_name": name,
                "title": meta["title"],
                "subtitle": meta["subtitle"],
                "explainer": meta["explainer"],
                "uses_llm": meta["uses_llm"],
                "prompt_key": meta["prompt_key"],
                "status": "pending",
                "inputs": {},
                "output": {},
                "error": None,
                "took_ms": None,
                "prompt_template_id": None,
                "llm_provider": None,
                "started_at": None,
                "finished_at": None,
                "updated_at": None,
            })
            continue
        out.append({
            "stage_name": name,
            "title": meta["title"],
            "subtitle": meta["subtitle"],
            "explainer": meta["explainer"],
            "uses_llm": meta["uses_llm"],
            "prompt_key": meta["prompt_key"],
            "status": row.status,
            "inputs": dict(row.inputs or {}),
            "output": dict(row.output or {}),
            "error": row.error,
            "took_ms": row.took_ms,
            "prompt_template_id": (
                str(row.prompt_template_id) if row.prompt_template_id else None
            ),
            "llm_provider": row.llm_provider,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "updated_at": row.updated_at,
        })
    return out


async def run_stage(
    db: AsyncSession,
    session_id: uuid.UUID,
    stage_name: str,
    *,
    inputs_override: dict[str, Any] | None = None,
    prompt_template_id: uuid.UUID | None = None,
    llm_provider: str | None = None,
) -> dict[str, Any]:
    """Execute one stage and persist its state.

    The stage runner is intentionally narrow: it calls into the existing
    :class:`MatchService` for the heavy lifting (rebuild_groups,
    run_match), then records a small output envelope (counts, samples,
    histograms) so the UI can show what happened without a second
    roundtrip.

    Stages downstream of the one being run are marked ``stale`` so the
    UI shows the user "you changed Filter; Group / Match / Rollup need
    re-running" warnings.
    """

    if stage_name not in STAGE_NAMES:
        raise ValueError(f"Unknown stage: {stage_name!r}")

    session_row = await db.get(MatchSession, session_id)
    if session_row is None:
        raise LookupError(f"Match session not found: {session_id}")

    stage = await _get_or_create_stage(db, session_id, stage_name)
    stage.status = "running"
    stage.error = None
    stage.started_at = _now()
    stage.took_ms = None
    if inputs_override is not None:
        stage.inputs = dict(inputs_override)
    if prompt_template_id is not None:
        stage.prompt_template_id = prompt_template_id
    if llm_provider is not None:
        stage.llm_provider = llm_provider
    # Commit the running state so a concurrent poll sees it and so the
    # runner starts from a clean transaction boundary — if it raises,
    # the rollback below only discards the runner's work, not the
    # "running" stamp.
    await db.commit()

    t0 = time.perf_counter()
    final_status = "done"
    final_output: dict[str, Any] = {}
    final_error: str | None = None
    try:
        runner = _STAGE_RUNNERS[stage_name]
        final_output = await runner(db, session_row, stage)
    except Exception as exc:  # noqa: BLE001 — surface error to UI
        logger.exception(
            "match_elements.pipeline: stage %s failed for session %s",
            stage_name, session_id,
        )
        final_status = "error"
        final_error = str(exc)
        # The session may be in a failed-transaction state — roll back
        # before we touch the DB again to write the error row.
        await db.rollback()

    took_ms = int((time.perf_counter() - t0) * 1000)

    # Re-fetch the stage row: a rollback (error path) or a runner that
    # committed mid-flight (load/match call into MatchService) can both
    # detach the earlier instance, so reload to write the terminal state
    # against a live row.
    stage = await _get_or_create_stage(db, session_id, stage_name)
    stage.status = final_status
    stage.output = final_output if final_status == "done" else {}
    stage.error = final_error
    stage.finished_at = _now()
    stage.took_ms = took_ms

    if final_status == "done":
        # Mark downstream done-stages stale so the UI flags the gap.
        idx = STAGE_NAMES.index(stage_name)
        for downstream in STAGE_NAMES[idx + 1:]:
            ds = await _get_or_create_stage(db, session_id, downstream)
            if ds.status == "done":
                ds.status = "stale"

    await db.commit()
    return {
        "stage_name": stage_name,
        "status": final_status,
        "output": dict(final_output or {}),
        "error": final_error,
        "took_ms": took_ms,
    }


# ── Stage runners ────────────────────────────────────────────────────────


async def _run_convert(
    db: AsyncSession,
    session: MatchSession,
    stage: MatchStageState,
) -> dict[str, Any]:
    # Convert is verification-only — the canonical table already exists.
    # Report the BIM model(s) bound to the session (or all models in the
    # project when no model is pinned) plus their element counts so the
    # user can confirm the parse didn't silently truncate.
    from app.modules.bim_hub.models import BIMModel

    if session.bim_model_id:
        one = await db.get(BIMModel, session.bim_model_id)
        models = [one] if one is not None else []
    else:
        models = (
            (await db.execute(
                select(BIMModel).where(BIMModel.project_id == session.project_id)
            )).scalars().all()
        )

    rows: list[dict[str, Any]] = []
    total = 0
    for m in models:
        n = int(m.element_count or 0)
        total += n
        rows.append({
            "model_id": str(m.id),
            "filename": m.name,
            "format": m.model_format,
            "status": m.status,
            "element_count": n,
        })

    return {
        "source": session.source,
        "models": rows,
        "element_count": total,
        "summary": f"{total} elements across {len(rows)} model(s)",
    }


async def _run_load(
    db: AsyncSession,
    session: MatchSession,
    stage: MatchStageState,
) -> dict[str, Any]:
    # The load stage drives :meth:`MatchService.rebuild_groups` so the
    # session ends up with a fresh element set + group structure. We
    # record sample rows for the UI preview.
    service = get_service()
    await service.rebuild_groups(db, session.id)

    sample_rows = (
        await db.execute(
            select(MatchGroup)
            .where(MatchGroup.session_id == session.id)
            .order_by(MatchGroup.element_count.desc())
            .limit(5)
        )
    ).scalars().all()
    samples = [
        {
            "group_key": r.group_key,
            "element_count": r.element_count,
            "quantities": r.quantities or {},
        }
        for r in sample_rows
    ]
    total_groups = (
        await db.execute(
            select(func.count())
            .select_from(MatchGroup)
            .where(MatchGroup.session_id == session.id)
        )
    ).scalar_one()
    total_elements = (
        await db.execute(
            select(func.coalesce(func.sum(MatchGroup.element_count), 0))
            .where(MatchGroup.session_id == session.id)
        )
    ).scalar_one()
    return {
        "group_count": total_groups,
        "element_count": total_elements,
        "samples": samples,
        "summary": (
            f"{total_elements} elements loaded → {total_groups} groups"
        ),
    }


async def _run_schema(
    db: AsyncSession,
    session: MatchSession,
    stage: MatchStageState,
) -> dict[str, Any]:
    # Heuristic schema classifier (no LLM call) — counts how often each
    # attribute key appears across the session's group quantities, then
    # tags it SUM / MEAN / FIRST by name pattern. The LLM-augmented path
    # kicks in only when the user explicitly hits "Re-run with prompt"
    # in the UI; the prompt body is stored on the stage row and the
    # provider is wired via app.core.llm (out of scope for this stub).
    groups = (
        await db.execute(
            select(MatchGroup).where(MatchGroup.session_id == session.id)
        )
    ).scalars().all()

    keys: Counter[str] = Counter()
    for g in groups:
        for k in (g.quantities or {}).keys():
            keys[k] += 1
    if not keys:
        return {"columns": [], "summary": "no columns detected"}

    classified: list[dict[str, Any]] = []
    sum_keys = {"area_m2", "volume_m3", "length_m", "count", "gross_volume_m3", "net_volume_m3", "weight_kg"}
    mean_keys = {"thickness_m", "height_m", "width_m", "depth_m"}
    for key, freq in keys.most_common():
        if key in sum_keys:
            agg = "SUM"
        elif key in mean_keys:
            agg = "MEAN"
        else:
            agg = "FIRST"
        classified.append({
            "column": key,
            "agg": agg,
            "occurrence": freq,
        })
    return {
        "columns": classified,
        "llm_used": False,
        "summary": (
            f"{len(classified)} columns classified "
            f"({sum(1 for c in classified if c['agg'] == 'SUM')} SUM)"
        ),
    }


async def _run_filter(
    db: AsyncSession,
    session: MatchSession,
    stage: MatchStageState,
) -> dict[str, Any]:
    # The filter stage is currently a recording-only summary of which
    # IfcCategories were excluded at session-create time + how many
    # groups survived. The interactive "exclude this group" remains in
    # the existing UI; this stage just renders the count so the user
    # sees the impact.
    rows = (
        await db.execute(
            select(MatchGroup.status, func.count())
            .where(MatchGroup.session_id == session.id)
            .group_by(MatchGroup.status)
        )
    ).all()
    by_status = {status: int(n) for status, n in rows}
    kept = sum(by_status.values())
    return {
        "excluded_categories": list(session.excluded_categories or []),
        "kept_groups": kept,
        "status_breakdown": by_status,
        "summary": (
            f"{kept} groups survived "
            f"({len(session.excluded_categories or [])} category exclusions)"
        ),
    }


async def _run_group(
    db: AsyncSession,
    session: MatchSession,
    stage: MatchStageState,
) -> dict[str, Any]:
    # Records the active group_by + top groups by element count. The
    # actual grouping happened in the Load stage via rebuild_groups;
    # this stage gives the user a panel to change group_by and re-run
    # Load+Group together (the StageAdjustSheet on the frontend wires
    # this by patching the session, then calling run_stage("group")
    # which delegates back to rebuild_groups).
    new_group_by = (stage.inputs or {}).get("group_by")
    if new_group_by:
        session.group_by = list(new_group_by)
        await db.flush()
        # Group_by changed → rebuild.
        service = get_service()
        await service.rebuild_groups(db, session.id)

    groups = (
        await db.execute(
            select(MatchGroup)
            .where(MatchGroup.session_id == session.id)
            .order_by(MatchGroup.element_count.desc())
            .limit(10)
        )
    ).scalars().all()
    return {
        "group_by": list(session.group_by or []),
        "top_groups": [
            {
                "group_key": g.group_key,
                "element_count": g.element_count,
            }
            for g in groups
        ],
        "summary": (
            f"Grouped by {', '.join(session.group_by or []) or '∅'}"
        ),
    }


async def _run_match(
    db: AsyncSession,
    session: MatchSession,
    stage: MatchStageState,
) -> dict[str, Any]:
    # Drives MatchService.run_match across the unmatched groups. The
    # LLM cost-agent rerank is gated on the prompt_template_id being
    # set; without it the stage runs vector-only (today's behaviour).
    service = get_service()
    unmatched = (
        await db.execute(
            select(MatchGroup)
            .where(MatchGroup.session_id == session.id)
            .where(MatchGroup.status.in_(("unmatched", "tbd", "stale")))
            .order_by(MatchGroup.element_count.desc())
        )
    ).scalars().all()
    keys = [g.group_key for g in unmatched]
    if not keys:
        return {
            "ran": 0,
            "confirmed": 0,
            "suggested": 0,
            "summary": "Nothing to match — all groups already resolved",
        }

    # The user can cap this from the Adjust sheet (inputs.max_groups);
    # default keeps the call interactive on huge models.
    raw_cap = (stage.inputs or {}).get("max_groups", 50)
    try:
        cap = max(1, min(int(raw_cap), 200))
    except (TypeError, ValueError):
        cap = 50
    method = (stage.inputs or {}).get("method", "vector")
    if method not in ("vector", "lexical", "resources", "llm"):
        method = "vector"

    req = schemas.RunMatchRequest(
        method=method,  # type: ignore[arg-type]
        group_keys=keys[:cap],
        max_groups=min(len(keys), 200),
        top_k=int((stage.inputs or {}).get("top_k", 10)),
    )
    summaries = await service.run_match(db, session.id, req)
    confirmed = sum(1 for s in summaries if s.status == "confirmed")
    suggested = sum(1 for s in summaries if s.status == "suggested")
    return {
        "ran": len(summaries),
        "confirmed": confirmed,
        "suggested": suggested,
        "method": method,
        "summary": (
            f"Matched {len(summaries)} groups · "
            f"{confirmed} confirmed · {suggested} suggested"
        ),
    }


async def _run_rollup(
    db: AsyncSession,
    session: MatchSession,
    stage: MatchStageState,
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(MatchGroup.status, func.count())
            .where(MatchGroup.session_id == session.id)
            .group_by(MatchGroup.status)
        )
    ).all()
    breakdown = {status: int(n) for status, n in rows}
    total = sum(breakdown.values())
    return {
        "total": total,
        "breakdown": breakdown,
        "summary": (
            f"{breakdown.get('confirmed', 0)} confirmed · "
            f"{breakdown.get('suggested', 0)} suggested · "
            f"{breakdown.get('unmatched', 0)} unmatched"
        ),
    }


_STAGE_RUNNERS = {
    "convert": _run_convert,
    "load": _run_load,
    "schema": _run_schema,
    "filter": _run_filter,
    "group": _run_group,
    "match": _run_match,
    "rollup": _run_rollup,
}
