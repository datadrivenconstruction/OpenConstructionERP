# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost Classifier - maps free-text scope items to standard cost codes.

Tools (declarative - wired into the global registry on import):

* ``classify_item(description, region)`` - the primary tool. Runs the same
  ``costs.matcher.match_cwicr_items`` lookup the BOQ drafter uses, then for
  each top catalogue match loads the underlying :class:`CostItem` and reads
  its real ``classification`` JSON (the column that holds ``din276`` /
  ``nrm`` / ``masterformat`` / ``category`` / ``code`` keys when the
  catalogue row carries them). It returns the matched catalogue code,
  description, unit, currency, score and whatever classification codes the
  data *actually* exposes.
* ``search_costs(q, region)`` - re-uses the globally-registered tool the
  BOQ drafter installs (raw cost-catalogue lookup without classification
  enrichment). It is declared in ``allowed_tools`` so the LLM can fall back
  to it, but ``classify_item`` is the primary tool.

Data integrity (no-stubs rule): every suggested standard code MUST be
grounded in a real catalogue match the agent cites. If the matched
catalogue row does NOT expose a DIN 276 / MasterFormat / NRM classification
field, the tool returns the matched code + description and explicitly flags
``classification_available=False`` with a note that a standard code has to
be *inferred from the catalogue code* - it never fabricates a DIN /
MasterFormat number. If the cost database is unreachable the tool returns
an explicit ``{"error": "unavailable"}`` observation rather than guessing.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core import cost_scope
from app.modules.ai_agents.base import (
    Agent,
    FunctionTool,
    global_tool_registry,
    register_agent,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a construction cost classifier. The user gives you free-text "
    "scope items and you map each one to standard cost codes (e.g. DIN 276 "
    "cost groups, MasterFormat divisions, NRM elements). For every item, call "
    "classify_item to find real catalogue matches, then ground each suggested "
    "code in those matches and cite the matched catalogue code and "
    "description. Only state a DIN 276 / MasterFormat / NRM code when a "
    "matched catalogue row actually carries that classification field "
    "(classification_available=true). When the match exposes no standard "
    "classification, say so plainly: report the matched catalogue code and "
    "description and explain that a standard code would have to be inferred "
    "from the catalogue code, rather than inventing a number. If "
    "classify_item returns an error or no matches for an item, say no "
    "supporting match was found rather than guessing a code. Reply with a "
    "concise markdown table: one row per scope item with the matched "
    "catalogue code, the standard classification code(s) found (or 'none - "
    "infer from code'), and the match score."
)


# ── Tool implementations ────────────────────────────────────────────────────


# Classification standards we surface from the catalogue's ``classification``
# JSON, in the order they are most useful for cost-coding. These are the keys
# real CWICR rows populate (see costs.vector_adapter / costs.schemas).
_CLASSIFICATION_STANDARDS = ("din276", "masterformat", "nrm")
# Auxiliary classification keys some catalogue rows carry instead of (or in
# addition to) a recognised standard code. Surfaced as context so the LLM can
# still anchor a suggestion to the catalogue without us fabricating a number.
_CLASSIFICATION_CONTEXT_KEYS = ("collection", "department", "section", "category", "code")


def _extract_classification(raw: Any) -> tuple[dict[str, str], dict[str, str]]:
    """Split a CostItem.classification dict into (standards, context).

    ``standards`` holds only recognised standard codes (din276 / masterformat
    / nrm) that are actually populated. ``context`` holds the auxiliary
    category/collection keys some rows carry. Both are plain ``str``-valued
    dicts; empty/None values are dropped so callers never see blanks.
    Returns two empty dicts when the row has no usable classification.
    """
    if not isinstance(raw, dict):
        return {}, {}
    standards: dict[str, str] = {}
    for key in _CLASSIFICATION_STANDARDS:
        val = raw.get(key)
        if val not in (None, ""):
            standards[key] = str(val).strip()
    context: dict[str, str] = {}
    for key in _CLASSIFICATION_CONTEXT_KEYS:
        val = raw.get(key)
        if val not in (None, ""):
            context[key] = str(val).strip()
    return standards, context


async def _tool_classify_item(description: str, region: str | None = None) -> dict[str, Any]:
    """Map a scope-item description to standard cost codes via the catalogue.

    Runs ``costs.matcher.match_cwicr_items`` exactly as the BOQ drafter does
    to find the top real catalogue matches, then loads each matched
    :class:`CostItem` to read its ``classification`` JSON. For every match it
    returns the catalogue code, description, unit, currency and score plus any
    real DIN 276 / MasterFormat / NRM codes the row exposes.

    ``classification_available`` is ``True`` only when the matched row carries
    a recognised standard code. When it is ``False`` the caller MUST NOT
    invent a DIN / MasterFormat number - the matched catalogue code is the
    only ground truth and any standard code has to be inferred from it.

    Returns ``{"error": "unavailable"}`` if the cost database cannot be
    reached in the current context (no-stubs / data-integrity rule).
    """
    desc = (description or "").strip()
    if not desc:
        return {"description": desc, "matches": [], "note": "empty description"}

    try:
        from app.database import async_session_factory
        from app.modules.costs.matcher import match_cwicr_items

        async with async_session_factory() as session:
            results = await match_cwicr_items(
                session,
                desc,
                top_k=5,
                region=region or None,
            )

            matches: list[dict[str, Any]] = []
            any_classified = False
            for r in results:
                standards: dict[str, str] = {}
                context: dict[str, str] = {}
                # MatchResult carries no classification - load the underlying
                # CostItem by its UUID to read the real classification JSON.
                try:
                    item = await cost_scope.get_cost_item(session, r.cost_item_id)
                except (ValueError, TypeError):
                    item = None
                if item is not None:
                    standards, context = _extract_classification(item.classification)

                classified = bool(standards)
                any_classified = any_classified or classified
                match: dict[str, Any] = {
                    "code": r.code,
                    "description": r.description,
                    "unit": r.unit,
                    "currency": r.currency,
                    "score": float(r.score),
                    "classification_available": classified,
                    "classification": standards,
                }
                if context:
                    match["classification_context"] = context
                if not classified:
                    match["note"] = (
                        "This catalogue match exposes no DIN 276 / MasterFormat / NRM "
                        "code. Infer a standard code from the catalogue code above; do "
                        "not fabricate a classification number."
                    )
                matches.append(match)

        return {
            "description": desc,
            "region": region or "",
            "matches": matches,
            "any_classification_available": any_classified,
        }
    except Exception as exc:  # pragma: no cover - DB unavailable
        logger.debug("classify_item unavailable: %s", exc)
        return {
            "description": desc,
            "region": region or "",
            "matches": [],
            "error": "unavailable",
            "detail": (
                "Cost database is not reachable in this context. No catalogue "
                "matches available - do not invent classification codes; report "
                "that the item could not be classified against the catalogue."
            ),
        }


# ── Registration ────────────────────────────────────────────────────────────


def register_cost_classifier() -> None:
    """Idempotent registration of the cost-classifier agent and its tool.

    ``classify_item`` is registered here. ``search_costs`` is registered by
    ``boq_drafter.register_boq_drafter`` into the same global registry; this
    agent merely lists it in ``allowed_tools`` so the LLM can use it as a
    plain catalogue-lookup fallback.
    """
    global_tool_registry.register(
        FunctionTool(
            name="classify_item",
            description=(
                "Map a free-text scope item to standard cost codes. Looks up "
                "the cost catalogue and, for the top matches, returns the "
                "matched code, description, unit, currency, score and any real "
                "DIN 276 / MasterFormat / NRM classification the catalogue row "
                "exposes. When classification_available is false the match has "
                "no standard code - infer one from the catalogue code, never "
                "fabricate a number. Returns error=unavailable if the cost DB "
                "is unreachable."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "The scope-item text to classify",
                    },
                    "region": {
                        "type": "string",
                        "description": "Optional region code (e.g. DE_BERLIN)",
                    },
                },
                "required": ["description"],
            },
            func=_tool_classify_item,
        )
    )

    register_agent(
        Agent(
            name="cost_classifier",
            display_name="Cost Classifier",
            category="estimating",
            icon="tags",
            tagline="Map scope items to standard cost codes (DIN 276 / MasterFormat)",
            description=(
                "Classifies free-text scope items into standard cost codes "
                "(DIN 276, MasterFormat, NRM), grounding every suggested code "
                "in real cost-catalogue matches it cites."
            ),
            example_prompts=[
                "Classify these scope items: reinforced concrete foundations, external brickwork, internal plastering.",
                "What DIN 276 cost groups do these belong to: roof insulation, rainwater downpipes, soffit boarding?",
                "Map to MasterFormat divisions: structural steel framing, cast-in-place concrete, exterior glazing.",
            ],
            system_prompt=SYSTEM_PROMPT,
            max_iterations=8,
            allowed_tools=["classify_item", "search_costs"],
        )
    )
