"""LLM tier — translates a single term via the configured AI provider.

Reuses :func:`app.modules.ai.ai_client.call_ai` so we automatically get
support for every provider the rest of the platform supports (Anthropic,
OpenAI, Gemini, OpenRouter, Mistral, Groq, DeepSeek, …) and pick up new
providers as they're added there.

Cost estimation is approximate — providers expose token counts on
response, but the per-token rate varies by model and cannot be discovered
from the API. We use a conservative blended rate (input + output) per
provider and clamp by a per-call cap so a runaway cascade can't mint a
huge bill on a single document.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Per-1k-token blended rate (input ~30% + output ~70%) in USD. Numbers
# are intentionally conservative — better to slightly overestimate cost
# than to under-report it on the audit trail.
_BLENDED_RATES_USD_PER_1K: dict[str, float] = {
    "anthropic": 0.012,   # claude-sonnet-4 ~$3/$15 per M, blended
    "openai": 0.010,      # gpt-4o ~$2.5/$10 per M
    "gemini": 0.0009,     # gemini-2.5-flash ~$0.30/$2.50 per M
    "openrouter": 0.012,
    "mistral": 0.005,
    "groq": 0.0007,
    "deepseek": 0.001,
    "together": 0.003,
    "fireworks": 0.003,
    "perplexity": 0.005,
    "cohere": 0.005,
    "ai21": 0.005,
    "xai": 0.010,
    "ollama": 0.0,        # local, no API cost
    "vllm": 0.0,          # local, no API cost
}

# Hard cap per call. Construction term translation is at most ~20 tokens
# input + ~20 tokens output; even a confused LLM running 4096 max_tokens
# can't spend more than a fraction of a cent on a single call.
_MAX_COST_PER_CALL_USD = 0.05

_PROMPT_TEMPLATE = (
    "Translate the following construction term from {src} to {tgt}.\n"
    "Domain: {domain}.\n"
    "Return ONLY the translation, no explanation, no quotes, no prefix.\n"
    "If the term is a code (e.g. 'C30/37', 'IPE100', 'B25') keep it unchanged.\n"
    "Term: {text}"
)

_SYSTEM = (
    "You are a precise construction-domain translator. You output only the "
    "translation of the input term. No commentary, no quotes, no rephrasing."
)


def _estimate_cost_usd(provider: str, tokens: int) -> float:
    rate = _BLENDED_RATES_USD_PER_1K.get(provider, 0.005)
    cost = (tokens / 1000.0) * rate
    return min(cost, _MAX_COST_PER_CALL_USD)


def _clean_response(text: str) -> str:
    """Strip quotes / leading punctuation that LLMs occasionally add."""
    if not text:
        return text
    out = text.strip()
    # Remove a trailing period from a single-line term, keep mid-text dots
    # (e.g. "C30/37" or "Stahlbetonwand 24cm"). Simple heuristic: only
    # strip wrapping quote-pairs and leading bullets.
    while out and out[0] in "\"'`«»“”„":
        out = out[1:]
    while out and out[-1] in "\"'`«»“”„":
        out = out[:-1]
    out = out.lstrip("-*•").strip()
    # If the model returned multiple lines (e.g. citations) keep only the
    # first non-empty line.
    for line in out.splitlines():
        line = line.strip()
        if line:
            return line
    return out


async def llm_translate(
    text: str,
    src: str,
    tgt: str,
    *,
    domain: str = "construction",
    user_settings: Any = None,
) -> tuple[str, float, float] | None:
    """Translate via LLM. Returns ``(translation, cost_usd, confidence)``.

    Returns ``None`` if no API key is configured, the network fails, or
    the response is unusable. Callers must treat ``None`` as a tier miss
    and fall through.
    """
    # Local imports — keeps the cascade module cheap to import in
    # environments where AI deps aren't wired in.
    try:
        from app.modules.ai.ai_client import (
            call_ai,
            resolve_provider_and_key,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("AI client import failed: %s", exc)
        return None

    if user_settings is None:
        # No settings = no key. The cascade will fall through to fallback.
        logger.debug("LLM translate skipped: no user_settings provided")
        return None

    try:
        provider, api_key = resolve_provider_and_key(user_settings)
    except ValueError as exc:
        logger.debug("LLM translate skipped: %s", exc)
        return None

    prompt = _PROMPT_TEMPLATE.format(
        src=src, tgt=tgt, domain=domain, text=text
    )

    try:
        raw, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=_SYSTEM,
            prompt=prompt,
            # Construction terms are short — cap response length so a
            # confused LLM can't generate paragraphs and inflate cost.
            max_tokens=128,
        )
    except Exception as exc:
        # Includes httpx errors, ValueError-wrapped 401/429 from the
        # client, etc. Fail closed — the cascade falls through to fallback.
        logger.debug("LLM call failed: %s", exc)
        return None

    cleaned = _clean_response(raw)
    if not cleaned:
        return None

    # Heuristic confidence: shorter, single-line responses with no
    # special control characters are more likely to be a clean
    # translation than a chatty one.
    confidence = 0.85 if "\n" not in raw.strip() else 0.75
    # If the LLM echoed the input verbatim (same string), confidence drops.
    if cleaned.strip().lower() == text.strip().lower():
        confidence = 0.5

    cost_usd = _estimate_cost_usd(provider, tokens)
    return cleaned, cost_usd, confidence
