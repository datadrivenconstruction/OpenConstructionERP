"""‌⁠‍AI Advisor — generates project recommendations using the LLM service.

Reuses the existing AI client from app.modules.ai.ai_client.
Falls back to rule-based recommendations when no LLM is configured.

Cost discipline (v4.2.2+):
    * Every LLM call is structured-logged with (provider, model, operation,
      tokens, duration_ms, outcome) so cost runaway is observable.
    * Recommendations / chat / gap explanations are de-duplicated through a
      bounded TTL cache (key = sha256 of system+prompt+model+max_tokens),
      so refresh-spam from the dashboard can't fan out to fresh LLM calls.
"""

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_intelligence.collector import ProjectState
from app.modules.project_intelligence.scorer import CriticalGap, ProjectScore

logger = logging.getLogger(__name__)

# ── Bounded LLM-response cache (debounce refresh-spam) ────────────────────
# Identical prompt + system + model + max_tokens → cached for LLM_CACHE_TTL.
# Bounded LRU so memory can't leak. Keys are sha256 hashes; values are
# (timestamp, response_text). Multi-user safe: the key is derived from the
# fully-rendered prompt which already includes the per-project context, so
# cross-project replies cannot mix.
LLM_CACHE_TTL_SECONDS = 60
LLM_CACHE_MAX_ENTRIES = 256
_llm_cache: "OrderedDict[str, tuple[float, str]]" = OrderedDict()


def _llm_cache_key(*, provider: str, model: str | None, system: str, prompt: str, max_tokens: int) -> str:
    """Stable cache key for (provider, model, system, prompt, max_tokens)."""
    h = hashlib.sha256()
    h.update(provider.encode("utf-8"))
    h.update(b"|")
    h.update((model or "").encode("utf-8"))
    h.update(b"|")
    h.update(str(max_tokens).encode("utf-8"))
    h.update(b"|")
    h.update(system.encode("utf-8"))
    h.update(b"|")
    h.update(prompt.encode("utf-8"))
    return h.hexdigest()


def _llm_cache_get(key: str) -> str | None:
    entry = _llm_cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if (time.time() - ts) > LLM_CACHE_TTL_SECONDS:
        _llm_cache.pop(key, None)
        return None
    # Refresh LRU order on hit
    _llm_cache.move_to_end(key)
    return value


def _llm_cache_put(key: str, value: str) -> None:
    _llm_cache[key] = (time.time(), value)
    _llm_cache.move_to_end(key)
    while len(_llm_cache) > LLM_CACHE_MAX_ENTRIES:
        _llm_cache.popitem(last=False)


async def _call_ai_logged(
    *,
    operation: str,
    provider: str,
    api_key: str,
    model: str | None,
    system: str,
    prompt: str,
    max_tokens: int,
) -> str:
    """Wrap ``call_ai`` with cache + structured cost/outcome logging.

    Logs one record per call with provider, model, operation, tokens used,
    duration, and cache_hit/error flags so an operator can chart LLM spend.
    Raises whatever ``call_ai`` raises so the caller's existing
    try/except → rule-based-fallback path keeps working.
    """
    from app.modules.ai.ai_client import call_ai

    cache_key = _llm_cache_key(
        provider=provider,
        model=model,
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
    )
    cached = _llm_cache_get(cache_key)
    if cached is not None:
        logger.info(
            "project_intelligence.llm_call",
            extra={
                "operation": operation,
                "provider": provider,
                "model": model or "default",
                "tokens": 0,
                "duration_ms": 0,
                "cache_hit": True,
                "outcome": "ok",
            },
        )
        return cached

    started = time.monotonic()
    try:
        text_response, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            model=model,
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 — observability point, re-raised
        logger.info(
            "project_intelligence.llm_call",
            extra={
                "operation": operation,
                "provider": provider,
                "model": model or "default",
                "tokens": 0,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "cache_hit": False,
                "outcome": "error",
                "error_type": type(exc).__name__,
            },
        )
        raise

    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "project_intelligence.llm_call",
        extra={
            "operation": operation,
            "provider": provider,
            "model": model or "default",
            "tokens": int(tokens or 0),
            "duration_ms": duration_ms,
            "cache_hit": False,
            "outcome": "ok",
        },
    )
    _llm_cache_put(cache_key, text_response)
    return text_response


# ── System prompts per role ────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "estimator": (
        "You are an expert construction cost estimator reviewing a project in "
        "OpenConstructionERP. You are precise, technical, and focused on cost accuracy. "
        "Respond in {language}. "
        "When reviewing the project state, prioritize: "
        "1. BOQ completeness and price accuracy "
        "2. CWICR database matching for zero-price items "
        "3. Validation compliance with {standard} "
        "4. Resource and assembly completeness "
        "Be specific: cite exact numbers from the project data. Give actionable next steps. "
        "Format: numbered priority list, each item max 3 sentences."
    ),
    "manager": (
        "You are a senior project manager reviewing project readiness in "
        "OpenConstructionERP. You see the big picture: is this project ready for "
        "the next phase? Respond in {language}. "
        "When reviewing the project state, prioritize: "
        "1. Overall readiness score and what's blocking progress "
        "2. Schedule alignment with cost model "
        "3. Risk exposure and contingency adequacy "
        "4. Reporting and documentation completeness "
        "Speak in terms of business impact, not technical details. "
        "Format: executive summary (2 sentences), then numbered priority list."
    ),
    "explorer": (
        "You are a friendly guide helping a new user understand OpenConstructionERP. "
        "Explain everything clearly, assume no prior knowledge of construction ERP software. "
        "Respond in {language}. "
        "When reviewing the project state: "
        "1. Celebrate what they've already done "
        "2. Explain WHY each next step matters in plain language "
        "3. Tell them exactly where to click "
        "4. Never overwhelm: suggest maximum 3 next steps at a time "
        "Be warm, encouraging, and specific."
    ),
}


def _build_system_prompt(role: str, language: str, standard: str) -> str:
    """‌⁠‍Build the system prompt for the given role."""
    template = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["estimator"])
    return template.format(language=language, standard=standard or "international")


def _build_context_prompt(state: ProjectState, score: ProjectScore) -> str:
    """‌⁠‍Serialize project state into a token-efficient prompt context."""
    lines = [
        f'Project: "{state.project_name}" | Type: {state.project_type or "unspecified"} '
        f"| Standard: {state.standard or 'unspecified'} | Region: {state.region or 'unspecified'} "
        f"| Currency: {state.currency or 'unspecified'}",
        f"Overall Score: {score.overall:.0f}/100 (Grade {score.overall_grade})",
        "",
    ]

    # Domain scores
    lines.append("DOMAIN SCORES:")
    for domain, dscore in sorted(score.domain_scores.items(), key=lambda x: -x[1]):
        bar = "#" * int(dscore / 10) + "." * (10 - int(dscore / 10))
        lines.append(f"  {domain:12s} [{bar}] {dscore:.0f}%")
    lines.append("")

    # Critical gaps
    if score.critical_gaps:
        lines.append("CRITICAL GAPS:")
        for gap in score.critical_gaps:
            count_str = f" ({gap.affected_count} items)" if gap.affected_count else ""
            lines.append(f"  [{gap.severity.upper()}] {gap.domain}: {gap.title}{count_str}")
            lines.append(f"    Impact: {gap.impact}")
        lines.append("")

    # Achievements
    if score.achievements:
        lines.append("COMPLETED:")
        for ach in score.achievements:
            lines.append(f"  OK {ach.title}")
        lines.append("")

    # BOQ details
    if state.boq.exists:
        lines.append("BOQ DETAILS:")
        lines.append(
            f"  {state.boq.total_items} items, {state.boq.sections_count} sections, "
            f"{state.boq.items_with_zero_price} zero-price, "
            f"{state.boq.items_with_zero_quantity} zero-quantity"
        )
        lines.append("")

    # Schedule details
    if state.schedule.exists:
        lines.append("SCHEDULE DETAILS:")
        lines.append(
            f"  {state.schedule.activities_count} activities, "
            f"duration: {state.schedule.duration_days or 'unknown'} days, "
            f"baseline: {'yes' if state.schedule.baseline_set else 'no'}"
        )
        lines.append("")

    return "\n".join(lines)


async def _get_ai_settings(session: AsyncSession) -> Any:
    """Load AI settings from the database."""
    try:
        from sqlalchemy import text

        row = (await session.execute(text("SELECT * FROM oe_ai_settings LIMIT 1"))).first()
        return row
    except Exception:
        return None


async def _resolve_provider(session: AsyncSession) -> tuple[str, str, str | None] | None:
    """Resolve (provider, key, model_override). None if no LLM configured.

    The model override (Settings > AI) is returned so the advisor honors the
    user's chosen model instead of a hardcoded provider default — issue #138.
    """
    try:
        from app.modules.ai.ai_client import resolve_provider_key_model

        settings = await _get_ai_settings(session)
        if settings is None:
            return None
        provider, key, model_override = resolve_provider_key_model(settings)
        return (provider, key, model_override)
    except (ValueError, Exception):
        return None


async def generate_recommendations(
    session: AsyncSession,
    state: ProjectState,
    score: ProjectScore,
    role: str = "estimator",
    language: str = "en",
) -> str:
    """Generate AI recommendations for the project.

    Args:
        session: Database session for loading AI settings.
        state: Collected project state.
        score: Computed project score.
        role: User role (estimator, manager, explorer).
        language: Response language code.

    Returns:
        Recommendation text (from LLM or rule-based fallback).
    """
    # Try LLM first
    provider_info = await _resolve_provider(session)
    if provider_info:
        try:
            provider, api_key, model_override = provider_info
            system = _build_system_prompt(role, language, state.standard)
            context = _build_context_prompt(state, score)
            prompt = (
                f"Analyze this project and provide prioritized recommendations:\n\n"
                f"{context}\n\n"
                f"Give me your top 5 recommendations for improving this project."
            )

            return await _call_ai_logged(
                operation="recommendations",
                provider=provider,
                api_key=api_key,
                model=model_override,
                system=system,
                prompt=prompt,
                max_tokens=2048,
            )
        except Exception:
            logger.warning("LLM call failed, falling back to rule-based", exc_info=True)

    # Rule-based fallback
    return _generate_fallback_recommendations(state, score, role)


async def explain_gap(
    session: AsyncSession,
    gap: CriticalGap,
    state: ProjectState,
    language: str = "en",
) -> str:
    """Generate a detailed explanation for a specific gap.

    Args:
        session: Database session.
        gap: The gap to explain.
        state: Project state for context.
        language: Response language.

    Returns:
        Explanation text.
    """
    provider_info = await _resolve_provider(session)
    if provider_info:
        try:
            provider, api_key, model_override = provider_info
            system = (
                f"You are a construction ERP expert explaining a project issue. "
                f"Respond in {language}. Be specific, actionable, and concise."
            )
            prompt = (
                f"Project: {state.project_name} ({state.project_type or 'general'}, "
                f"{state.standard or 'standard'})\n\n"
                f"Gap: [{gap.severity.upper()}] {gap.title}\n"
                f"Description: {gap.description}\n"
                f"Impact: {gap.impact}\n"
                f"Affected items: {gap.affected_count or 'N/A'}\n\n"
                f"Explain: 1) Why this matters for this specific project type and standard, "
                f"2) What the concrete consequences are, "
                f"3) Step-by-step how to fix it in OpenConstructionERP."
            )

            return await _call_ai_logged(
                operation="explain_gap",
                provider=provider,
                api_key=api_key,
                model=model_override,
                system=system,
                prompt=prompt,
                max_tokens=1024,
            )
        except Exception:
            logger.warning("LLM gap explanation failed", exc_info=True)

    # Fallback
    return (
        f"{gap.description}\n\n"
        f"Impact: {gap.impact}\n\n"
        f"To fix this, navigate to the relevant module in OpenConstructionERP "
        f"and address the {gap.affected_count or ''} affected items."
    )


async def _retrieve_relevant_chunks(
    question: str,
    project_id: str | None,
    *,
    limit: int = 12,
) -> str:
    """Pull top-K semantic hits from the unified search layer.

    Returns a markdown-formatted "Relevant context" block that can be
    appended to the advisor prompt.  Failures (vector backend down,
    empty index, etc.) return an empty string so the caller falls back
    to its existing behaviour without RAG augmentation.
    """
    if not question:
        return ""
    try:
        from app.modules.search.service import unified_search_service

        response = await unified_search_service(
            query=question,
            project_id=project_id,
            limit_per_collection=4,
            final_limit=limit,
        )
    except Exception:
        logger.debug("Advisor RAG retrieval failed", exc_info=True)
        return ""

    if not response.hits:
        return ""

    lines: list[str] = ["Relevant context (semantic retrieval — verify before quoting):"]
    for hit in response.hits:
        snippet = hit.snippet or hit.text or ""
        if len(snippet) > 280:
            snippet = snippet[:277].rstrip() + "…"
        lines.append(f"- [{hit.module}] {hit.title} (score {hit.score:.2f}): {snippet}")
    return "\n".join(lines)


async def answer_question(
    session: AsyncSession,
    state: ProjectState,
    score: ProjectScore,
    question: str,
    role: str = "estimator",
    language: str = "en",
) -> str:
    """Answer a user question about the project.

    Args:
        session: Database session.
        state: Project state.
        score: Project score.
        question: User's question.
        role: User role.
        language: Response language.

    Returns:
        Answer text.
    """
    provider_info = await _resolve_provider(session)
    if provider_info:
        try:
            provider, api_key, model_override = provider_info
            system = _build_system_prompt(role, language, state.standard)
            context = _build_context_prompt(state, score)
            # Pull semantically relevant chunks from BOQ / documents / tasks /
            # risks / BIM elements via the unified vector search layer.  This
            # turns the advisor from a structured-stats summarizer into a
            # genuine RAG agent — answers stay anchored in real evidence
            # instead of hallucinating from the structured project state alone.
            project_id = str(getattr(state, "project_id", "")) or None
            rag_context = await _retrieve_relevant_chunks(question, project_id)
            prompt_parts = [f"Project context:\n{context}"]
            if rag_context:
                prompt_parts.append(rag_context)
            prompt_parts.append(f"User question: {question}")
            prompt_parts.append(
                "Provide a clear, specific answer based on the project data above. "
                "When you cite a fact from the relevant context, mention which "
                "module it came from in square brackets, e.g. [boq] or [risks]."
            )
            prompt = "\n\n".join(prompt_parts)

            return await _call_ai_logged(
                operation="chat",
                provider=provider,
                api_key=api_key,
                model=model_override,
                system=system,
                prompt=prompt,
                max_tokens=1024,
            )
        except Exception:
            logger.warning("LLM question answering failed", exc_info=True)

    return (
        "AI recommendations require an LLM provider to be configured. "
        "Please add your API key in Settings > AI to enable this feature. "
        "The project score and gap analysis are still available without AI."
    )


def _generate_fallback_recommendations(
    state: ProjectState,
    score: ProjectScore,
    role: str,
) -> str:
    """Generate rule-based recommendations when no LLM is available."""
    lines: list[str] = []

    lines.append(f'Project "{state.project_name}" scores {score.overall:.0f}/100 (Grade {score.overall_grade}).')
    lines.append("")

    if not score.critical_gaps:
        lines.append(
            "No critical gaps detected. The project is in good shape. "
            "Consider generating a report or reviewing the schedule."
        )
        return "\n".join(lines)

    lines.append("Priority actions:")
    lines.append("")

    for i, gap in enumerate(score.critical_gaps[:5], 1):
        lines.append(f"{i}. [{gap.severity.upper()}] {gap.title}")
        lines.append(f"   {gap.description}")
        if gap.action_id:
            lines.append("   Action available: use the button to resolve this.")
        lines.append("")

    if score.achievements:
        lines.append("What's working well:")
        for ach in score.achievements[:3]:
            lines.append(f"  - {ach.title}")

    return "\n".join(lines)
