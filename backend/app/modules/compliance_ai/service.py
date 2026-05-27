"""‌⁠‍Compliance-AI service — verdict pipeline + LLM cost controls.

Wraps :func:`app.core.validation.dsl.nl_builder.parse_nl_to_dsl` with:

* **Structured verdict logging** — every call emits a single INFO line
  with ``rule_id`` / ``used_method`` / ``confidence`` / ``lang`` /
  ``ai_used`` / ``elapsed_ms`` / ``text_len`` / ``user_id``. Lets ops
  spot prompt-injection probes and unhealthy AI fallback rates without
  shipping a separate metrics pipeline.
* **Safe AI caller construction** — never raises. If the user has no
  API key, ``use_ai=True`` silently degrades to pattern-only matching.
  The wrapper uses a bounded ``max_tokens=1024`` so a malformed prompt
  can't drive runaway cost on a single call.
* **Detached event publishing wrapped in** :func:`_log_failures` — the
  ``compliance.nl_rule.generated`` event fires only on a successful
  parse, never blocks the request handler, and never leaves a silent
  failure if the subscriber crashes (see ``feedback`` v4.2.2 — "no
  silent task drops").

The service stays stateless: no DB writes, no globals. The router
hands it a session for the AI-settings lookup and nothing else.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, _log_failures, event_bus
from app.core.validation.dsl.nl_builder import (
    NlBuildResult,
    parse_nl_to_dsl,
)
from app.modules.compliance_ai.events import (
    NL_RULE_GENERATED,
    SOURCE_MODULE,
)
from app.modules.compliance_ai.schemas import (
    NlVerifyRequest,
    NlVerifyResponse,
)

logger = logging.getLogger(__name__)

# Bound on tokens the AI fallback may emit. The NL → DSL output is a
# single short YAML block; 1 KB of tokens is generous. Capping here
# means a runaway model can't bill a single call for thousands of
# tokens of hallucinated prose.
_AI_MAX_TOKENS = 1024


async def _build_ai_caller(
    user_id: str | None,
    session: AsyncSession,
) -> Any | None:
    """‌⁠‍Build a bound ``(system, prompt) -> str`` callable, or ``None``.

    Mirrors the helper in :mod:`app.modules.compliance.router` but is
    duplicated here so the compliance_ai module stays decoupled from
    its sibling. Never raises — any failure returns ``None`` and the
    NL builder falls back to deterministic pattern matching only.
    """
    if not user_id:
        return None
    try:
        uid = uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None

    try:
        # Lazy imports keep this module importable without the AI
        # provider stack present.
        from app.modules.ai.ai_client import (
            call_ai,
            resolve_provider_key_model,
        )
        from app.modules.ai.repository import AISettingsRepository

        settings_obj = await AISettingsRepository(session).get_by_user_id(uid)
        provider, api_key, model_override = resolve_provider_key_model(settings_obj)
    except Exception:  # pragma: no cover — defensive
        return None

    async def _caller(system: str, prompt: str) -> str:
        text, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=system,
            prompt=prompt,
            max_tokens=_AI_MAX_TOKENS,
            model=model_override,
        )
        return text

    return _caller


def _render_yaml(definition: dict[str, Any]) -> str | None:
    """Best-effort YAML rendering — failures degrade to None, not 500."""
    if not definition:
        return None
    try:
        return yaml.safe_dump(
            definition,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    except yaml.YAMLError:  # pragma: no cover — defensive
        logger.warning(
            "compliance_ai: YAML render failed for rule_id=%s",
            definition.get("rule_id"),
            exc_info=True,
        )
        return None


def _publish_generated(
    result: NlBuildResult,
    *,
    text: str,
    user_id: str | None,
) -> None:
    """Fire ``compliance.nl_rule.generated`` without awaiting subscribers.

    Wrapped in :func:`_log_failures` so a subscriber crash is visible in
    the WARNING log instead of vanishing as an unawaited task exception.
    """
    if not result.dsl_definition:
        return  # nothing to announce — the call produced no rule

    event = Event(
        name=NL_RULE_GENERATED,
        data={
            "suggested_rule_id_candidate": result.dsl_definition.get("rule_id"),
            "requirement_excerpt_first_200_chars": text[:200],
            "warnings_count": len(result.errors),
            "used_method": result.used_method,
            "confidence": result.confidence,
            "user_id": user_id,
        },
        source_module=SOURCE_MODULE,
    )
    _log_failures(
        event_bus.publish(
            event.name,
            event.data,
            source_module=SOURCE_MODULE,
        ),
        name=f"{SOURCE_MODULE}.nl_rule_generated",
    )


async def verify_nl_rule(
    body: NlVerifyRequest,
    *,
    user_id: str | None,
    session: AsyncSession,
) -> NlVerifyResponse:
    """Run the NL → DSL pipeline with cost-controlled LLM fallback.

    The function is safe to call without an AI key configured: when
    ``body.use_ai`` is true and no key is available, ``ai_caller`` is
    ``None`` and the deterministic pattern matcher carries the request.

    Verdicts are logged structured (single INFO line). Successful rules
    are announced via :data:`NL_RULE_GENERATED`.
    """
    start = time.perf_counter()

    ai_caller = None
    if body.use_ai:
        ai_caller = await _build_ai_caller(user_id, session)

    result = await parse_nl_to_dsl(
        body.text,
        lang=body.lang,
        use_ai=body.use_ai,
        ai_caller=ai_caller,
    )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    rule_id = result.dsl_definition.get("rule_id") if result.dsl_definition else None

    # Structured verdict log — single line, machine-parseable. See module
    # docstring for the rationale.
    logger.info(
        "compliance_ai.verdict rule_id=%s used_method=%s confidence=%.2f "
        "lang=%s ai_used=%s elapsed_ms=%d text_len=%d errors=%d user_id=%s",
        rule_id or "-",
        result.used_method,
        result.confidence,
        body.lang,
        bool(ai_caller),
        elapsed_ms,
        len(body.text),
        len(result.errors),
        user_id or "-",
    )

    _publish_generated(result, text=body.text, user_id=user_id)

    return NlVerifyResponse(
        dsl_definition=result.dsl_definition,
        dsl_yaml=_render_yaml(result.dsl_definition),
        confidence=result.confidence,
        used_method=result.used_method,
        matched_pattern=result.matched_pattern,
        errors=list(result.errors),
        suggestions=list(result.suggestions),
    )


__all__ = ["verify_nl_rule"]
