"""AI Advisor — generates project recommendations using the LLM service.

Reuses the existing AI client from app.modules.ai.ai_client.
Falls back to rule-based recommendations when no LLM is configured.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_intelligence.collector import ProjectState
from app.modules.project_intelligence.scorer import CriticalGap, ProjectScore

logger = logging.getLogger(__name__)


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
    """Build the system prompt for the given role."""
    template = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["estimator"])
    return template.format(language=language, standard=standard or "international")


def _build_context_prompt(state: ProjectState, score: ProjectScore) -> str:
    """Serialize project state into a token-efficient prompt context."""
    lines = [
        f"Project: \"{state.project_name}\" | Type: {state.project_type or 'unspecified'} "
        f"| Standard: {state.standard or 'unspecified'} | Region: {state.region or 'unspecified'} "
        f"| Currency: {state.currency or 'unspecified'}",
        f"Overall Score: {score.overall:.0f}/100 (Grade {score.overall_grade})",
        "",
    ]

    # Domain scores
    lines.append("DOMAIN SCORES:")
    for domain, dscore in sorted(
        score.domain_scores.items(), key=lambda x: -x[1]
    ):
        bar = "#" * int(dscore / 10) + "." * (10 - int(dscore / 10))
        lines.append(f"  {domain:12s} [{bar}] {dscore:.0f}%")
    lines.append("")

    # Critical gaps
    if score.critical_gaps:
        lines.append("CRITICAL GAPS:")
        for gap in score.critical_gaps:
            count_str = f" ({gap.affected_count} items)" if gap.affected_count else ""
            lines.append(
                f"  [{gap.severity.upper()}] {gap.domain}: {gap.title}{count_str}"
            )
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

        row = (
            await session.execute(
                text("SELECT * FROM oe_ai_settings LIMIT 1")
            )
        ).first()
        return row
    except Exception:
        return None


async def _resolve_provider(session: AsyncSession) -> tuple[str, str] | None:
    """Resolve AI provider and key. Returns None if no LLM configured."""
    try:
        from app.modules.ai.ai_client import resolve_provider_and_key

        settings = await _get_ai_settings(session)
        if settings is None:
            return None
        provider, key = resolve_provider_and_key(settings)
        return (provider, key)
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
            from app.modules.ai.ai_client import call_ai

            provider, api_key = provider_info
            system = _build_system_prompt(role, language, state.standard)
            context = _build_context_prompt(state, score)
            prompt = (
                f"Analyze this project and provide prioritized recommendations:\n\n"
                f"{context}\n\n"
                f"Give me your top 5 recommendations for improving this project."
            )

            text_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=system,
                prompt=prompt,
                max_tokens=2048,
            )
            return text_response
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
            from app.modules.ai.ai_client import call_ai

            provider, api_key = provider_info
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

            text_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=system,
                prompt=prompt,
                max_tokens=1024,
            )
            return text_response
        except Exception:
            logger.warning("LLM gap explanation failed", exc_info=True)

    # Fallback
    return (
        f"{gap.description}\n\n"
        f"Impact: {gap.impact}\n\n"
        f"To fix this, navigate to the relevant module in OpenConstructionERP "
        f"and address the {gap.affected_count or ''} affected items."
    )


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
            from app.modules.ai.ai_client import call_ai

            provider, api_key = provider_info
            system = _build_system_prompt(role, language, state.standard)
            context = _build_context_prompt(state, score)
            prompt = (
                f"Project context:\n{context}\n\n"
                f"User question: {question}\n\n"
                f"Provide a clear, specific answer based on the project data above."
            )

            text_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=system,
                prompt=prompt,
                max_tokens=1024,
            )
            return text_response
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

    lines.append(
        f"Project \"{state.project_name}\" scores {score.overall:.0f}/100 "
        f"(Grade {score.overall_grade})."
    )
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
            lines.append(f"   Action available: use the button to resolve this.")
        lines.append("")

    if score.achievements:
        lines.append("What's working well:")
        for ach in score.achievements[:3]:
            lines.append(f"  - {ach.title}")

    return "\n".join(lines)
