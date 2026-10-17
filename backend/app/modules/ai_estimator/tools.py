# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Precise-rate matching agent + its tools for the AI Estimate Builder.

Stage 3 of the pipeline lets the user-selected agent reason over REAL
retrieval candidates and decide how to ground a group's rate. The agent NEVER
invents a rate or a code: every tool returns candidates straight from the cost
database (grounded vector/lexical search, the resources matcher, an LLM rerank
of a shortlist, or a CWICR resource breakdown), and the agent may only pick
among the ids the tools returned.

The tools wrap the existing, verified retrieval stack as a library:

* ``search_rates`` / ``refine_query`` -> ``ranker_qdrant.rank`` (full grounded
  pipeline: search plan -> Qdrant fallback ladder -> parquet attach -> boosts
  -> BGE rerank).
* ``try_resources_matcher`` -> ``costs.matcher.match_cwicr_items`` (lexical /
  hybrid fallback for custom single-line rates and the no-Qdrant degraded
  path).
* ``escalate_llm_rerank`` -> ``reranker_ai.rerank_top_k`` (cost-gated LLM
  re-ordering of the current shortlist).
* ``get_resource_breakdown`` -> reads ``CostItem.components`` for a candidate.
* ``flag_for_human`` -> records that no candidate is a genuine match.

The tools are stateless and side-effect-free (read-only over the cost DB);
they open their own session per call because the agent runner has no DB handle.
The service ALSO calls ``rank()`` directly for the deterministic (no-agent and
no-AI-key) path, so the module works end-to-end with no LLM. This module only
adds the agentic reasoning layer on top.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core import cost_scope
from app.modules.ai_agents.base import (
    Agent,
    FunctionTool,
    global_tool_registry,
    register_agent,
)
from app.modules.ai_estimator.prompts import MATCH_REASONING_SYSTEM

logger = logging.getLogger(__name__)

# Agent slug the module registers. A run may target this agent (the grounded
# precise-rate reasoner) or any user-selected custom agent; both reason over
# the same tools.
PRECISE_MATCH_AGENT = "precise_estimate_matcher"

# Tool slugs (kept as constants so the agent's allowed_tools and the
# permissions registration stay in sync).
TOOL_SEARCH_RATES = "estimator_search_rates"
TOOL_REFINE_QUERY = "estimator_refine_query"
TOOL_RESOURCES_MATCHER = "estimator_resources_matcher"
TOOL_LLM_RERANK = "estimator_llm_rerank"
TOOL_RESOURCE_BREAKDOWN = "estimator_resource_breakdown"
TOOL_FLAG_FOR_HUMAN = "estimator_flag_for_human"

ALL_TOOL_NAMES: tuple[str, ...] = (
    TOOL_SEARCH_RATES,
    TOOL_REFINE_QUERY,
    TOOL_RESOURCES_MATCHER,
    TOOL_LLM_RERANK,
    TOOL_RESOURCE_BREAKDOWN,
    TOOL_FLAG_FOR_HUMAN,
)

# Cap candidates returned to the LLM so a tool observation never blows up the
# next-step prompt cost (the runner also truncates, but a tight cap keeps the
# JSON readable for the model).
_MAX_CANDIDATES_TO_LLM = 8


def _candidate_to_brief(c: Any) -> dict[str, Any]:
    """Reduce a MatchCandidate to the fields the LLM needs to reason + pick.

    Crucially carries the candidate ``id`` (the only legal thing the agent may
    select) and the honest score / band so the model can judge quality.
    """
    return {
        "candidate_id": getattr(c, "id", None),
        "code": getattr(c, "code", "") or "",
        "description": (getattr(c, "description", "") or "")[:200],
        "unit": getattr(c, "unit", "") or "",
        "unit_rate": getattr(c, "unit_rate", 0.0),
        "currency": getattr(c, "currency", "") or "",
        "score": round(float(getattr(c, "score", 0.0) or 0.0), 4),
        "confidence_band": getattr(c, "confidence_band", "low"),
    }


def _context_user(ctx: dict[str, Any]) -> uuid.UUID | None:
    """The user the agent runs for, from its context; ``None`` when absent."""
    try:
        return uuid.UUID(str(ctx.get("user_id") or ""))
    except (ValueError, TypeError):
        return None


async def _run_rank(
    *,
    description: str,
    unit: str,
    project_id: str,
    top_k: int,
    use_reranker: bool,
    caller_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Call the grounded ranker once and return a JSON-safe candidate list.

    Opens its own session (the agent runner holds none). Never raises - any
    failure degrades to an empty candidate list with a structured note so the
    agent can decide to refine or flag.
    """
    from app.core.match_service.envelope import ElementEnvelope, MatchRequest
    from app.core.match_service.ranker_qdrant import rank
    from app.database import async_session_factory

    desc = (description or "").strip()
    if not desc:
        return {"candidates": [], "note": "empty_description"}
    try:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))
    except (ValueError, TypeError):
        return {"candidates": [], "note": "bad_project_id"}

    try:
        async with async_session_factory() as session:
            envelope = ElementEnvelope(
                source="text",
                description=desc[:2000],
                unit_hint=(unit or None),
            )
            req = MatchRequest(
                envelope=envelope,
                project_id=pid,
                top_k=max(1, min(int(top_k or 10), 50)),
                use_reranker=bool(use_reranker),
            )
            resp = await rank(req, db=session, caller_id=caller_id)
    except Exception as exc:  # noqa: BLE001 - tools degrade, never crash the loop
        logger.warning("estimator tool rank failed: %s", exc)
        return {"candidates": [], "note": f"rank_error:{type(exc).__name__}"}

    briefs = [_candidate_to_brief(c) for c in resp.candidates[:_MAX_CANDIDATES_TO_LLM]]
    return {"candidates": briefs, "status": resp.status, "catalogue_id": resp.catalog_id}


async def _tool_search_rates(description: str = "", unit: str = "", top_k: int = 10, **kwargs: Any) -> dict[str, Any]:
    """Grounded search: rank cost-database candidates for a group description."""
    ctx = kwargs.get("__agent_context__") or {}
    project_id = str(ctx.get("project_id") or "")
    return await _run_rank(
        description=description,
        unit=unit,
        project_id=project_id,
        top_k=top_k,
        use_reranker=True,
        caller_id=_context_user(ctx),
    )


async def _tool_refine_query(
    new_description: str = "", unit: str = "", top_k: int = 10, **kwargs: Any
) -> dict[str, Any]:
    """Re-run grounded search with a better description the agent composed."""
    ctx = kwargs.get("__agent_context__") or {}
    project_id = str(ctx.get("project_id") or "")
    return await _run_rank(
        description=new_description,
        unit=unit,
        project_id=project_id,
        top_k=top_k,
        use_reranker=True,
        caller_id=_context_user(ctx),
    )


async def _tool_resources_matcher(query: str = "", unit: str = "", top_k: int = 8, **kwargs: Any) -> dict[str, Any]:
    """Lexical/hybrid fallback over the cost DB (custom rates, no-Qdrant path)."""
    from app.database import async_session_factory
    from app.modules.costs.matcher import match_cwicr_items

    ctx = kwargs.get("__agent_context__") or {}
    region = (ctx.get("region") or "") or None
    q = (query or "").strip()
    if not q:
        return {"candidates": [], "note": "empty_query"}
    try:
        async with async_session_factory() as session:
            results = await match_cwicr_items(
                session,
                q,
                unit=(unit or None),
                region=region,
                mode="hybrid",
                top_k=max(1, min(int(top_k or 8), 25)),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("estimator resources matcher failed: %s", exc)
        return {"candidates": [], "note": f"resources_error:{type(exc).__name__}"}
    briefs = [
        {
            "candidate_id": r.cost_item_id,
            "code": r.code,
            "description": (r.description or "")[:200],
            "unit": r.unit,
            "unit_rate": r.unit_rate,
            "currency": r.currency,
            "score": round(float(r.score or 0.0), 4),
            "confidence_band": "low",
        }
        for r in results[:_MAX_CANDIDATES_TO_LLM]
    ]
    return {"candidates": briefs, "method": "resources"}


async def _tool_llm_rerank(
    description: str = "", candidate_ids: list[str] | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Cost-gated LLM rerank of a shortlist the agent already retrieved.

    The shortlist is re-fetched from the grounded ranker (so the candidate
    objects are real) and reordered by the cross-provider LLM reranker.
    """
    from app.core.match_service.envelope import ElementEnvelope, MatchRequest
    from app.core.match_service.ranker_qdrant import rank
    from app.core.match_service.reranker_ai import rerank_top_k
    from app.database import async_session_factory

    ctx = kwargs.get("__agent_context__") or {}
    project_id = str(ctx.get("project_id") or "")
    desc = (description or "").strip()
    if not desc:
        return {"candidates": [], "note": "empty_description"}
    try:
        pid = uuid.UUID(project_id)
    except (ValueError, TypeError):
        return {"candidates": [], "note": "bad_project_id"}
    try:
        async with async_session_factory() as session:
            envelope = ElementEnvelope(source="text", description=desc[:2000])
            resp = await rank(
                MatchRequest(envelope=envelope, project_id=pid, top_k=10, use_reranker=True),
                db=session,
                caller_id=_context_user(ctx),
            )
            if not resp.candidates:
                return {"candidates": [], "note": "no_candidates"}
            ranked, _cost = await rerank_top_k(resp.candidates, envelope, k=min(8, len(resp.candidates)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("estimator llm rerank failed: %s", exc)
        return {"candidates": [], "note": f"rerank_error:{type(exc).__name__}"}
    return {"candidates": [_candidate_to_brief(c) for c in ranked[:_MAX_CANDIDATES_TO_LLM]], "method": "llm"}


async def _tool_resource_breakdown(candidate_id: str = "", **_kwargs: Any) -> dict[str, Any]:
    """Read a candidate's CWICR resource components from the cost database."""
    from app.database import async_session_factory

    cid = (candidate_id or "").strip()
    if not cid:
        return {"resources": [], "note": "empty_candidate_id"}
    try:
        item_uuid = uuid.UUID(cid)
    except (ValueError, TypeError):
        return {"resources": [], "note": "bad_candidate_id"}
    try:
        async with async_session_factory() as session:
            item = await cost_scope.get_cost_item(session, item_uuid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("estimator resource breakdown failed: %s", exc)
        return {"resources": [], "note": f"lookup_error:{type(exc).__name__}"}
    if item is None:
        return {"resources": [], "note": "not_found"}
    comps = item.components if isinstance(item.components, list) else []
    return {
        "code": item.code,
        "unit": item.unit,
        "rate": item.rate,
        "currency": item.currency,
        "resources": [c for c in comps if isinstance(c, dict)][:50],
    }


async def _tool_flag_for_human(reason: str = "", **_kwargs: Any) -> dict[str, Any]:
    """Record that no candidate is a genuine match - defers to a human.

    This is intentionally a no-op side-effect-wise: the agent's final answer is
    what the service parses. The tool exists so the model has an explicit
    'I cannot ground this honestly' action instead of forcing a bad pick.
    """
    return {"flagged": True, "reason": (reason or "no_good_candidate")[:300]}


def register_precise_match_agent() -> None:
    """Register the precise-match tools + agent into the global registries.

    Idempotent (registration overwrites by name), so a hot-reload or a
    re-import is safe. Called from the module ``on_startup`` hook.
    """
    tools = (
        FunctionTool(
            name=TOOL_SEARCH_RATES,
            description=(
                "Search the cost database for grounded rate candidates matching a group "
                "description and unit. Returns real candidates with ids, codes, units, "
                "rates, currency and honest scores. Use this first."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "unit": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["description"],
            },
            func=_tool_search_rates,
        ),
        FunctionTool(
            name=TOOL_REFINE_QUERY,
            description=(
                "Re-run the grounded search with a better description when the first "
                "candidates were weak. Returns real candidates only."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "new_description": {"type": "string"},
                    "unit": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["new_description"],
            },
            func=_tool_refine_query,
        ),
        FunctionTool(
            name=TOOL_RESOURCES_MATCHER,
            description=(
                "Lexical/hybrid fallback matcher over the cost database for custom or "
                "single-line rates, and when the vector DB is unavailable. Returns real "
                "candidates only."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "unit": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "required": ["query"],
            },
            func=_tool_resources_matcher,
        ),
        FunctionTool(
            name=TOOL_LLM_RERANK,
            description=(
                "Escalate: re-order the current shortlist with an LLM reranker (cost "
                "gated). Use only when the top candidates are close and you need a "
                "tie-break. Returns the same real candidates, reordered."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "candidate_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["description"],
            },
            func=_tool_llm_rerank,
        ),
        FunctionTool(
            name=TOOL_RESOURCE_BREAKDOWN,
            description=(
                "Read the full resource breakdown (labour / material / equipment "
                "components) of a candidate by its candidate_id, to judge whether the "
                "rate is composite and complete."
            ),
            input_schema={
                "type": "object",
                "properties": {"candidate_id": {"type": "string"}},
                "required": ["candidate_id"],
            },
            func=_tool_resource_breakdown,
        ),
        FunctionTool(
            name=TOOL_FLAG_FOR_HUMAN,
            description=(
                "Flag this group for a human when no candidate is a genuine match "
                "(wrong currency, wrong dimension, or all scores too low). Honest 'no "
                "rate' beats a confidently-wrong rate."
            ),
            input_schema={
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
            func=_tool_flag_for_human,
        ),
    )
    for tool in tools:
        global_tool_registry.register(tool)

    register_agent(
        Agent(
            name=PRECISE_MATCH_AGENT,
            system_prompt=MATCH_REASONING_SYSTEM,
            description=(
                "Finds the single best grounded cost-database rate for a quantity group, "
                "reasoning over real candidates. Never invents a rate or a code."
            ),
            max_iterations=6,
            allowed_tools=list(ALL_TOOL_NAMES),
            display_name="Precise Estimate Matcher",
            category="estimating",
            icon="calculator",
            tagline="Grounds every rate in the cost database, never invents one.",
        )
    )
