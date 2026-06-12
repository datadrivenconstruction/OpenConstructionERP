# OpenConstructionERP - DataDrivenConstruction (DDC)
# CWICR AI Estimation Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""‌⁠‍AI API client - async calls to Anthropic, OpenAI, and Google Gemini.

All calls use httpx for async HTTP. No SDK dependencies required.
Each function takes an API key, prompt, optional image, and returns raw text.
JSON extraction is handled separately.
"""

import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Model defaults ───────────────────────────────────────────────────────────

# UI model-choice aliases → current Anthropic API model ids. The Settings > AI
# dropdown (router._AI_PROVIDERS["anthropic"]["model_choices"]) and the stored
# AISettings.preferred_model use the short aliases ("claude-sonnet" / "-opus" /
# "-haiku"); the Anthropic API needs the full versioned id. Mapping here is the
# single source of truth so picking Opus/Haiku in the UI actually sends
# Opus/Haiku (previously every choice collapsed to one hardcoded Sonnet id).
# A user free-text override that is already a real API id (e.g.
# "claude-opus-4-8") is NOT an alias and passes through unchanged - see
# resolve_anthropic_model().
ANTHROPIC_MODELS: dict[str, str] = {
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus": "claude-opus-4-8",
    "claude-haiku": "claude-haiku-4-5-20251001",
}

# Default Anthropic model id (the resolved id for the "claude-sonnet" alias).
ANTHROPIC_MODEL = ANTHROPIC_MODELS["claude-sonnet"]


def resolve_anthropic_model(model: str | None) -> str:
    """Resolve a UI model choice / override to a current Anthropic API id.

    ``None``/blank returns the default. A known UI alias ("claude-sonnet",
    "claude-opus", "claude-haiku") is mapped to its current versioned id.
    Anything else (a user free-text override that is already a real API id)
    passes through unchanged so power users keep full control.
    """
    choice = (model or "").strip()
    if not choice:
        return ANTHROPIC_MODEL
    return ANTHROPIC_MODELS.get(choice, choice)


# gpt-4.1 is OpenAI's current flagship general model (vision + tool-calling,
# 1M-token context, not deprecated). gpt-4o still works but is older - using
# the current id by default reduces "deprecated model" failures (issue #129).
# Users can override per-provider via Settings > AI without an app release.
OPENAI_MODEL = "gpt-4.1"
GEMINI_MODEL = "gemini-2.5-flash"
# Moonshot's rolling alias that always points at the current Kimi release.
KIMI_MODEL = "kimi-latest"
# OpenRouter uses date-less, vendor-prefixed slugs. The dated Anthropic id
# ("...-20250514") is NOT a valid OpenRouter model - passing it makes even a
# perfectly valid OpenRouter key fail with HTTP 400 "not a valid model ID".
OPENROUTER_MODEL = "anthropic/claude-sonnet-4"
MISTRAL_MODEL = "mistral-large-latest"
GROQ_MODEL = "llama-3.3-70b-versatile"
DEEPSEEK_MODEL = "deepseek-chat"

# Per-provider default model id. This is the single source of truth for the
# model name sent to each provider's API. Users can override any of these via
# Settings > AI (stored in AISettings.metadata_["model_overrides"][provider])
# so that when a provider renames or retires a model the user can point the
# integration at a current model id WITHOUT waiting for an app release.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_MODEL,
    "openai": OPENAI_MODEL,
    "gemini": GEMINI_MODEL,
    "kimi": KIMI_MODEL,
    "openrouter": OPENROUTER_MODEL,
    "mistral": MISTRAL_MODEL,
    "groq": GROQ_MODEL,
    "deepseek": DEEPSEEK_MODEL,
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "fireworks": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    "perplexity": "sonar-pro",
    "cohere": "command-r-plus",
    "ai21": "jamba-1.5-large",
    "xai": "grok-2",
    "zhipu": "glm-4-plus",
    "baidu": "ernie-4.0-8k",
    "yandex": "yandexgpt/latest",
    "gigachat": "GigaChat-Pro",
    "ollama": os.environ.get("OE_OLLAMA_MODEL", "llama3.1"),
    "vllm": os.environ.get("OE_VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
}


def default_model_for(provider: str) -> str:
    """Return the built-in default model id for a provider (or empty string)."""
    return DEFAULT_MODELS.get(provider, "")


# Stable, provider-managed fallback model ids that are tried AUTOMATICALLY
# when the configured/overridden model name is rejected (renamed, retired,
# or - for aggregators like OpenRouter - simply not a currently valid slug).
#
# Issue #148: providers such as openrouter.ai continuously rename and retire
# model slugs. The chat must keep working when that happens instead of
# dead-ending the user with a "go fix Settings" error. OpenRouter exposes a
# meta-model, ``openrouter/auto``, that always resolves to an available
# model - using it as the fallback fully decouples the integration from any
# specific OpenRouter naming convention (exactly the user's request).
FALLBACK_MODELS: dict[str, str] = {
    "openrouter": "openrouter/auto",
    # Anthropic: if a stale/over-specific id is rejected, self-heal onto the
    # current default Sonnet id rather than dead-ending the user.
    "anthropic": "claude-sonnet-4-6",
}


def fallback_models_for(provider: str, attempted: str) -> list[str]:
    """Ordered, de-duplicated safe model ids to retry after a model-name
    rejection.

    Never includes ``attempted`` (the id that just failed). Combines the
    provider-managed meta-model (e.g. ``openrouter/auto``) with the built-in
    default - the latter helps when the failing id was a stale *user
    override* and the shipped default is still valid.
    """
    candidates = [
        FALLBACK_MODELS.get(provider, ""),
        default_model_for(provider),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for raw in candidates:
        c = (raw or "").strip()
        if c and c != (attempted or "").strip() and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# Timeout for AI API calls (2 minutes - large BOQ generation can be slow)
AI_TIMEOUT = 240.0


# ── Anthropic Claude ─────────────────────────────────────────────────────────


async def call_anthropic(
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    model: str | None = None,
    max_tokens: int = 4096,
) -> tuple[str, int]:
    """‌⁠‍Call Anthropic Claude API.

    Args:
        api_key: Anthropic API key.
        system: System prompt.
        prompt: User message text.
        image_base64: Optional base64-encoded image data.
        image_media_type: MIME type of the image.
        model: Model identifier.
        max_tokens: Maximum response tokens.

    Returns:
        Tuple of (response_text, tokens_used).

    Raises:
        httpx.HTTPStatusError: On API errors.
    """
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    content: list[dict[str, Any]] = []
    if image_base64:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": image_base64,
                },
            }
        )
    content.append({"type": "text", "text": prompt})

    payload = {
        # Map the UI alias / stored preferred_model to a current Anthropic API
        # id (or pass a real-id free-text override through unchanged).
        "model": resolve_anthropic_model(model),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=AI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

    text = data["content"][0]["text"]
    tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0)
    return text, tokens


# ── OpenAI-shaped response extraction (shared) ───────────────────────────────


def _extract_openai_message_text(provider: str, data: Any) -> str:
    """Pull assistant text out of an OpenAI chat-completions response.

    Hardened against the failure modes behind issue #138, where a request
    billed tokens upstream (confirmed on the provider dashboard) yet the
    user saw "no response": an HTTP-200 in-body ``error``, an empty
    ``choices`` array, ``content`` returned as a list of typed parts, or
    the model emitting only a ``reasoning`` trace. Every shape is reduced
    to a non-empty string or a precise, actionable ``ValueError`` - a paid
    completion is never silently discarded.
    """
    if isinstance(data, dict) and data.get("error") and not data.get("choices"):
        err = data["error"]
        detail = err.get("message") if isinstance(err, dict) else str(err)
        msg = f"{provider} returned an error: {detail or err}"
        raise ValueError(msg)

    choices = (data or {}).get("choices") or []
    if not choices:
        msg = (
            f"{provider} returned no choices - the model may have refused or "
            f"the request was filtered. Raw: {str(data)[:200]}"
        )
        raise ValueError(msg)

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, list):
        text = "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in (None, "text", "output_text")
        ).strip()
    elif isinstance(content, str):
        text = content.strip()
    else:
        text = ""

    if not text:
        reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            text = reasoning.strip()

    if not text:
        finish = choices[0].get("finish_reason") or "unknown"
        msg = (
            f"{provider} returned an empty message (finish_reason={finish}). "
            f"If 'length', raise max tokens; if 'content_filter', rephrase; "
            f"otherwise pick a different model in Settings > AI."
        )
        raise ValueError(msg)

    return text


# ── OpenAI ───────────────────────────────────────────────────────────────────


async def call_openai(
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    model: str | None = None,
    max_tokens: int = 4096,
) -> tuple[str, int]:
    """‌⁠‍Call OpenAI API (ChatCompletions).

    Args:
        api_key: OpenAI API key.
        system: System prompt.
        prompt: User message text.
        image_base64: Optional base64-encoded image data.
        image_media_type: MIME type of the image.
        model: Model identifier.
        max_tokens: Maximum response tokens.

    Returns:
        Tuple of (response_text, tokens_used).
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    user_content: list[dict[str, Any]] = []
    if image_base64:
        data_url = f"data:{image_media_type};base64,{image_base64}"
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            }
        )
    user_content.append({"type": "text", "text": prompt})

    payload = {
        "model": model or OPENAI_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=AI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

    text = _extract_openai_message_text("openai", data)
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return text, tokens


# ── Google Gemini ────────────────────────────────────────────────────────────


async def call_gemini(
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    model: str | None = None,
    max_tokens: int = 4096,
) -> tuple[str, int]:
    """Call Google Gemini API (generateContent).

    Args:
        api_key: Google AI / Gemini API key.
        system: System instruction.
        prompt: User message text.
        image_base64: Optional base64-encoded image data.
        image_media_type: MIME type of the image.
        model: Model identifier.
        max_tokens: Maximum response tokens.

    Returns:
        Tuple of (response_text, tokens_used).
    """
    model = model or GEMINI_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    parts: list[dict[str, Any]] = []
    if image_base64:
        parts.append(
            {
                "inline_data": {
                    "mime_type": image_media_type,
                    "data": image_base64,
                },
            }
        )
    parts.append({"text": prompt})

    payload: dict[str, Any] = {
        "contents": [{"parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            timeout=AI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    usage = data.get("usageMetadata", {})
    tokens = usage.get("promptTokenCount", 0) + usage.get("candidatesTokenCount", 0)
    return text, tokens


# ── OpenAI-compatible providers (OpenRouter, Mistral, Groq, DeepSeek) ───────


_OPENAI_COMPAT_CONFIG = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": OPENROUTER_MODEL,
        "extra_headers": {"HTTP-Referer": "https://openconstructionerp.com"},
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "model": MISTRAL_MODEL,
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": GROQ_MODEL,
    },
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "model": DEEPSEEK_MODEL,
    },
    "together": {
        "url": "https://api.together.xyz/v1/chat/completions",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "fireworks": {
        "url": "https://api.fireworks.ai/inference/v1/chat/completions",
        "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    },
    "perplexity": {
        "url": "https://api.perplexity.ai/chat/completions",
        "model": "sonar-pro",
    },
    "cohere": {
        "url": "https://api.cohere.com/v2/chat",
        "model": "command-r-plus",
    },
    "ai21": {
        "url": "https://api.ai21.com/studio/v1/chat/completions",
        "model": "jamba-1.5-large",
    },
    "xai": {
        "url": "https://api.x.ai/v1/chat/completions",
        "model": "grok-2",
    },
    # Zhipu AI (GLM) - OpenAI-compatible chat completions endpoint.
    "zhipu": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-plus",
    },
    # Baidu Qianfan (ERNIE) - OpenAI-compatible v2 endpoint.
    "baidu": {
        "url": "https://qianfan.baidubce.com/v2/chat/completions",
        "model": "ernie-4.0-8k",
    },
    # Yandex Cloud Foundation Models - OpenAI-compatible endpoint. The
    # model id must be the bare alias here; the user typically configures
    # the fully-qualified ``gpt://<folder-id>/yandexgpt/latest`` id as a
    # per-provider model override in Settings > AI.
    "yandex": {
        "url": "https://llm.api.cloud.yandex.net/v1/chat/completions",
        "model": "yandexgpt/latest",
    },
    # Sber GigaChat - OpenAI-compatible chat completions endpoint.
    "gigachat": {
        "url": "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        "model": "GigaChat-Pro",
    },
    # Moonshot AI (Kimi) - hosted, OpenAI-compatible chat completions.
    "kimi": {
        "url": "https://api.moonshot.cn/v1/chat/completions",
        "model": KIMI_MODEL,
    },
    # Local LLM runtimes - OpenAI-compatible REST API, no key required.
    # Override base URL via OE_OLLAMA_URL / OE_VLLM_URL env vars to point at
    # a non-default host (default Ollama :11434, default VLLM :8001 to avoid
    # colliding with our backend on :8000). An "api_key" stored in user
    # settings is sent as bearer when present; without one the Authorization
    # header is omitted entirely (vLLM may still require a key depending on
    # its `--api-key` startup flag).
    "ollama": {
        "url": os.environ.get("OE_OLLAMA_URL", "http://localhost:11434/v1/chat/completions"),
        "model": os.environ.get("OE_OLLAMA_MODEL", "llama3.1"),
        "api_key_optional": True,
    },
    "vllm": {
        "url": os.environ.get("OE_VLLM_URL", "http://localhost:8001/v1/chat/completions"),
        "model": os.environ.get("OE_VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
        "api_key_optional": True,
    },
}


def update_provider_config(saved_meta: dict | None = None) -> None:
    """Refresh the Ollama/vLLM endpoints from the saved settings metadata.
    Invoked once after settings are persisted so every subsequent AI call in
    the app reuses the user's endpoint without that URL having to be threaded
    through each individual call site (no per-call URL threading required)."""
    meta = saved_meta or {}
    for provider in ("ollama", "vllm"):  # only self-hosted runtimes are tunable
        candidate = meta.get(f"{provider}_base_url") if isinstance(meta, dict) else None
        if not (isinstance(candidate, str) and candidate.strip()):
            continue
        endpoint = candidate.strip().rstrip("/")
        if not endpoint.endswith("/v1/chat/completions"):
            endpoint += "/v1/chat/completions"
        _OPENAI_COMPAT_CONFIG[provider]["url"] = endpoint


async def call_openai_compatible(
    provider: str,
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    max_tokens: int = 4096,
    model: str | None = None,
    base_url: str | None = None,  # self-hosted endpoint override
) -> tuple[str, int]:
    """Call any OpenAI-compatible API (OpenRouter, Mistral, Groq, DeepSeek).

    These providers all implement the OpenAI chat completions format.

    Args:
        model: Optional model id override. When falsy, the provider's
            built-in default model is used.
        base_url: Optional endpoint override for self-hosted backends
            (Ollama/vLLM); takes precedence over the configured URL.
    """
    config = _OPENAI_COMPAT_CONFIG.get(provider)
    if not config:
        msg = f"Unknown OpenAI-compatible provider: {provider}"
        raise ValueError(msg)

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    # Keyless self-hosted runtimes (Ollama, vLLM without auth) resolve to an
    # empty api_key; an "Authorization: Bearer " header with an empty token is
    # an illegal header value for httpx and gets rejected by some servers, so
    # only send the header when there is an actual credential.
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key}"
    if "extra_headers" in config:
        headers.update(config["extra_headers"])

    user_content: list[dict[str, Any]] = []
    if image_base64:
        data_url = f"data:{image_media_type};base64,{image_base64}"
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            }
        )
    user_content.append({"type": "text", "text": prompt})

    payload = {
        "model": model or config["model"],
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }

    # Prefer the caller-supplied endpoint, otherwise fall back to the config.
    endpoint = base_url or config["url"]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=AI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

    text = _extract_openai_message_text(provider, data)
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return text, tokens


# ── Unified dispatcher ───────────────────────────────────────────────────────


async def call_ai(
    provider: str,
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    max_tokens: int = 4096,
    model: str | None = None,
    base_url: str | None = None,  # self-hosted endpoint override
) -> tuple[str, int]:
    """Route an AI call to the correct provider.

    Args:
        provider: One of "anthropic", "openai", "gemini".
        api_key: Provider API key.
        system: System prompt.
        prompt: User prompt.
        image_base64: Optional base64 image.
        image_media_type: Image MIME type.
        max_tokens: Max response tokens.
        model: Optional model id override. When falsy, the provider's
            built-in default model is used.
        base_url: Optional endpoint override for self-hosted backends
            (Ollama/vLLM); takes precedence over the configured URL.

    Returns:
        Tuple of (response_text, tokens_used).

    Raises:
        ValueError: If provider is unknown.
        httpx.HTTPStatusError: On API errors.
    """
    callers = {
        "anthropic": call_anthropic,
        "openai": call_openai,
        "gemini": call_gemini,
    }

    # Build the provider coroutine for a given model id. Parameterising the
    # model (rather than closing over the single configured one) lets the
    # error path transparently retry with a fallback id - issue #148.
    if provider in _OPENAI_COMPAT_CONFIG:

        def _make_call(model_id: str | None):
            async def _call() -> tuple[str, int]:
                return await call_openai_compatible(
                    provider,
                    api_key,
                    system,
                    prompt,
                    image_base64,
                    image_media_type,
                    max_tokens=max_tokens,
                    base_url=base_url,  # forward any self-hosted endpoint
                    model=model_id,
                )

            return _call

    elif provider in callers:
        caller = callers[provider]

        def _make_call(model_id: str | None):
            async def _call() -> tuple[str, int]:
                return await caller(
                    api_key,
                    system,
                    prompt,
                    image_base64,
                    image_media_type,
                    model=model_id,
                    max_tokens=max_tokens,
                )

            return _call

    else:
        msg = f"Unknown AI provider: {provider}"
        raise ValueError(msg)

    # The actual model id this call will use (override or built-in default) -
    # surfaced in "model not found" errors so the user knows exactly what to
    # change in Settings > AI.
    effective_model = model or default_model_for(provider)

    # Unified error handling for all providers
    try:
        return await _make_call(model)()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        # Try to extract error detail from response body
        try:
            body = exc.response.json()
            detail = body.get("error", {}).get("message", "") or str(body)
        except Exception:
            detail = exc.response.text[:200]

        # Detect "unknown / deprecated / unsupported model" responses. Every
        # provider phrases this differently and returns it under 400/404 (and
        # OpenRouter sometimes 400 with "not a valid model ID"). When the
        # provider rejects the *model* (not the key), tell the user exactly
        # which model id failed and that they can override it in Settings -
        # this is the core fix for issue #129 (stale hardcoded model names).
        low = detail.lower()
        model_keywords = (
            "model not found",
            "not a valid model",
            "is not a valid model",
            "unknown model",
            "model does not exist",
            "no such model",
            "unsupported model",
            "model_not_found",
            "invalid model",
            "deprecated",
            "has been deprecated",
            "decommissioned",
            "not supported for generatecontent",
            "is not found for api version",
        )
        is_model_error = status_code in (400, 404) and any(k in low for k in model_keywords)
        if is_model_error:
            # ── Issue #148: self-heal instead of dead-ending the user ───────
            # Providers (notably openrouter.ai) continuously rename/retire
            # model slugs. Rather than failing the chat outright, transparently
            # retry with provider-stable fallbacks - OpenRouter's auto-router
            # (``openrouter/auto``) and the shipped default - so the
            # integration is decoupled from any specific model naming.
            for fb_model in fallback_models_for(provider, effective_model):
                try:
                    result = await _make_call(fb_model)()
                except httpx.HTTPStatusError:
                    continue
                except (ValueError, KeyError, httpx.HTTPError):
                    continue
                logger.warning(
                    "call_ai: model %r rejected by %s (HTTP %s); auto-recovered with fallback model %r",
                    effective_model,
                    provider,
                    status_code,
                    fb_model,
                )
                return result
            msg = (
                f'The AI model "{effective_model}" was rejected by {provider} '
                f"(HTTP {status_code}) and the automatic fallbacks did not "
                f"succeed. Providers rename and retire models over time - open "
                f"Settings > AI, set the model name to a currently valid "
                f"{provider} model id, and save. Provider said: {detail[:200]}"
            )
            raise ValueError(msg) from exc

        if status_code == 400 and image_base64:
            msg = "The image could not be processed by the AI. Please upload a clearer building photo (JPEG/PNG, at least 200x200 pixels)."
            raise ValueError(msg) from exc
        if status_code == 401:
            msg = f"AI API key is invalid or expired ({provider}). Please update your API key in Settings."
            raise ValueError(msg) from exc
        if status_code in (403,) and ("model" in low or "access" in low):
            msg = (
                f'{provider} denied access to model "{effective_model}" with '
                f"this API key. Pick a model your account/plan can use in "
                f"Settings > AI. Provider said: {detail[:200]}"
            )
            raise ValueError(msg) from exc
        if status_code == 429:
            msg = f"AI rate limit exceeded ({provider}). Please wait a moment and try again."
            raise ValueError(msg) from exc

        msg = f"AI provider error ({provider}, HTTP {status_code}): {detail[:200]}"
        raise ValueError(msg) from exc


# ── JSON extraction ──────────────────────────────────────────────────────────


def extract_json(text: str) -> Any:
    """Extract JSON from AI response, handling markdown code fences and partial JSON.

    Tries multiple strategies:
    1. Direct JSON parse
    2. Extract from ```json ... ``` code blocks
    3. Find first [ or { and last ] or }

    Args:
        text: Raw AI response text.

    Returns:
        Parsed JSON (list or dict), or None if extraction fails.
    """
    if not text:
        return None

    text = text.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract from markdown code blocks
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: find JSON boundaries
    for open_ch, close_ch in [("[", "]"), ("{", "}")]:
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    logger.warning("Failed to extract JSON from AI response (length=%d)", len(text))
    return None


def _model_override_for(settings: Any, provider: str) -> str | None:
    """Read the user's per-provider model id override, if any.

    Overrides live in AISettings.metadata_["model_overrides"][provider] so we
    avoid a DB migration and keep the feature LIGHTWEIGHT. A blank/whitespace
    value means "use the built-in default" (None).
    """
    if not settings:
        return None
    meta = getattr(settings, "metadata_", None) or {}
    overrides = meta.get("model_overrides") if isinstance(meta, dict) else None
    if not isinstance(overrides, dict):
        return None
    raw = overrides.get(provider)
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    return raw or None


# Environment-variable names per provider, mirroring exactly the names that
# app/cli.py `check_ai_provider_keys()` already probes so the doctor check and
# the live AI path agree on where keys may live. GEMINI also honours the very
# common GOOGLE_API_KEY alias. Ordering inside each list is precedence
# (first match wins). The top-level list order is also the provider-inference
# precedence - Anthropic first, per the issue request.
_ENV_KEY_NAMES: list[tuple[str, list[str]]] = [
    ("anthropic", ["ANTHROPIC_API_KEY"]),
    ("openai", ["OPENAI_API_KEY"]),
    ("gemini", ["GEMINI_API_KEY", "GOOGLE_API_KEY"]),
    ("openrouter", ["OPENROUTER_API_KEY"]),
    ("mistral", ["MISTRAL_API_KEY"]),
    ("groq", ["GROQ_API_KEY"]),
    ("deepseek", ["DEEPSEEK_API_KEY"]),
]


def _key_from_env_and_config(provider: str | None) -> tuple[str, str] | None:
    """Find an AI key in env vars / ``~/.openestimate/config.json``.

    This is the fallback used when no usable key is stored in the DB. It mirrors
    the two locations `app/cli.py check_ai_provider_keys()` reports on:

    1. Environment variables (e.g. ``ANTHROPIC_API_KEY``) - see
       :data:`_ENV_KEY_NAMES`.
    2. ``~/.openestimate/config.json`` (CLI-managed): a flat JSON object whose
       ``*_api_key`` entries hold provider keys (key name ``<provider>_api_key``).

    Args:
        provider: If given, only that provider's key is looked up. When ``None``,
            the providers are scanned in :data:`_ENV_KEY_NAMES` order and the
            first one with a key wins (Anthropic preferred).

    Returns:
        ``(provider, api_key)`` if a non-empty key is found, else ``None``.
        Environment variables take precedence over the config file.
    """
    wanted = {provider} if provider else {p for p, _ in _ENV_KEY_NAMES}

    # 1. Environment variables (highest precedence after the DB).
    for prov, env_names in _ENV_KEY_NAMES:
        if prov not in wanted:
            continue
        for env_name in env_names:
            val = os.environ.get(env_name)
            if val and val.strip():
                return prov, val.strip()

    # 2. CLI config file (~/.openestimate/config.json). Map the flat
    #    ``<provider>_api_key`` entries back to a provider id.
    config_path = os.path.join(os.path.expanduser("~"), ".openestimate", "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, ValueError):
            cfg = None
        if isinstance(cfg, dict):
            for prov, _env_names in _ENV_KEY_NAMES:
                if prov not in wanted:
                    continue
                raw = cfg.get(f"{prov}_api_key")
                if isinstance(raw, str) and raw.strip():
                    return prov, raw.strip()

    return None


def resolve_provider_and_key(
    settings: Any,
    preferred_model: str | None = None,
) -> tuple[str, str]:
    """Determine which AI provider and API key to use based on user settings.

    NOTE: kept as a 2-tuple for backward compatibility with the many call
    sites across the codebase. To also get the user's model-id override use
    :func:`resolve_provider_key_model` (or call :func:`_model_override_for`
    with the returned provider).

    Args:
        settings: AISettings ORM object with api key fields.
        preferred_model: Optional model preference override.

    Returns:
        Tuple of (provider_name, api_key).

    Raises:
        ValueError: If no API key is configured.
    """
    from app.core.crypto import decrypt_secret

    model = preferred_model or (settings.preferred_model if settings else "claude-sonnet")

    # Map model preferences to providers
    _MODEL_PROVIDER_MAP: list[tuple[list[str], str, str]] = [
        (["claude", "anthropic"], "anthropic", "anthropic_api_key"),
        (["gpt", "openai"], "openai", "openai_api_key"),
        (["gemini", "google"], "gemini", "gemini_api_key"),
        (["openrouter", "router"], "openrouter", "openrouter_api_key"),
        (["mistral"], "mistral", "mistral_api_key"),
        # Self-hosted keyless runtimes must be matched BEFORE the generic
        # "llama" keyword below: "ollama" contains "llama", so a user picking
        # preferred_model=ollama would otherwise be routed to Groq.
        (["ollama"], "ollama", None),  # self-hosted: no stored key
        (["vllm"], "vllm", None),  # self-hosted: no stored key
        (["groq", "llama"], "groq", "groq_api_key"),
        (["deepseek"], "deepseek", "deepseek_api_key"),
        (["together"], "together", "together_api_key"),
        (["fireworks"], "fireworks", "fireworks_api_key"),
        (["perplexity", "sonar"], "perplexity", "perplexity_api_key"),
        (["cohere", "command"], "cohere", "cohere_api_key"),
        (["ai21", "jamba"], "ai21", "ai21_api_key"),
        (["xai", "grok"], "xai", "xai_api_key"),
        (["zhipu", "glm"], "zhipu", "zhipu_api_key"),
        (["baidu", "ernie"], "baidu", "baidu_api_key"),
        (["yandex"], "yandex", "yandex_api_key"),
        (["gigachat"], "gigachat", "gigachat_api_key"),
        (["kimi", "moonshot"], "kimi", "kimi_api_key"),  # Moonshot AI
    ]

    # The provider the chosen model maps to (e.g. "anthropic" for any
    # claude-* choice). Remembered so the env/config.json fallback can prefer
    # this provider's key before scanning all providers.
    matched_provider: str | None = None
    for keywords, provider_name, key_attr in _MODEL_PROVIDER_MAP:
        if any(kw in model for kw in keywords):
            matched_provider = provider_name
            if key_attr is None:  # keyless self-hosted provider
                return provider_name, ""  # no credential to resolve
            raw = getattr(settings, key_attr, None) if settings else None
            if raw:
                decrypted = decrypt_secret(raw)
                if decrypted:
                    return provider_name, decrypted
                # key exists but is undecryptable (JWT_SECRET rotated) -
                # fall through so the fallback loop can try other providers
            break  # matched model but no (usable) key - fall through to fallback

    # Fallback: try any available key (in priority order)
    _FALLBACK_ORDER: list[tuple[str, str]] = [
        ("anthropic", "anthropic_api_key"),
        ("openai", "openai_api_key"),
        ("gemini", "gemini_api_key"),
        ("openrouter", "openrouter_api_key"),
        ("mistral", "mistral_api_key"),
        ("groq", "groq_api_key"),
        ("deepseek", "deepseek_api_key"),
        ("together", "together_api_key"),
        ("fireworks", "fireworks_api_key"),
        ("perplexity", "perplexity_api_key"),
        ("cohere", "cohere_api_key"),
        ("ai21", "ai21_api_key"),
        ("xai", "xai_api_key"),
        ("zhipu", "zhipu_api_key"),
        ("baidu", "baidu_api_key"),
        ("yandex", "yandex_api_key"),
        ("gigachat", "gigachat_api_key"),
        ("ollama", None),  # keyless, skipped below
        ("vllm", None),  # keyless, skipped below
        ("kimi", "kimi_api_key"),  # Moonshot AI
    ]

    undecryptable = False
    if settings:
        for provider_name, key_attr in _FALLBACK_ORDER:
            if key_attr is None:  # keyless provider, nothing to resolve
                continue  # move on to the next candidate
            key_val = getattr(settings, key_attr, None)
            if key_val:
                decrypted = decrypt_secret(key_val)
                if decrypted:
                    return provider_name, decrypted
                undecryptable = True

    # Fallback to environment variables / ~/.openestimate/config.json. Tried
    # AFTER the DB (an explicitly-saved key wins) but BEFORE raising - a working
    # env/config key should take effect even if a stale, undecryptable DB key
    # exists (telling the user to "re-enter your key" would be wrong when a
    # valid env var is present). Prefer the chosen model's provider, then scan
    # all providers (Anthropic first). Mirrors cli.py check_ai_provider_keys().
    for prov_hint in (matched_provider, None):
        found = _key_from_env_and_config(prov_hint)
        if found:
            return found

    if undecryptable:
        raise ValueError(
            "Stored AI API key could not be decrypted - the backend encryption "
            "key has rotated since the key was saved. Please re-enter and save "
            "your API key in Settings > AI."
        )

    msg = (
        "No AI API key configured. Please add your API key in Settings > AI, or "
        "set an environment variable such as ANTHROPIC_API_KEY / OPENAI_API_KEY "
        "(or add it to ~/.openestimate/config.json). "
        "Supported: Anthropic, OpenAI, Gemini, OpenRouter, Mistral, Groq, "
        "DeepSeek, Together, Fireworks, Perplexity, Cohere, AI21, xAI, Ollama, Kimi, vLLM."
    )
    raise ValueError(msg)


def resolve_provider_key_model(
    settings: Any,
    preferred_model: str | None = None,
) -> tuple[str, str, str | None]:
    """Resolve (provider, api_key, model_override) in one call.

    Thin wrapper over :func:`resolve_provider_and_key` that also reads the
    user's per-provider model-id override. New code should prefer this so the
    model name stays user-configurable (issue #129). ``model_override`` is
    ``None`` when the user has not set one - callers pass it straight to
    :func:`call_ai`, which then falls back to the built-in default.

    For Anthropic, when no explicit per-provider override is set, the UI model
    choice stored in ``settings.preferred_model`` ("claude-sonnet" /
    "claude-opus" / "claude-haiku") is returned so that picking Opus/Haiku in
    the dropdown actually sends Opus/Haiku. ``call_anthropic`` maps that alias
    to the current API id via :func:`resolve_anthropic_model`.
    """
    provider, api_key = resolve_provider_and_key(settings, preferred_model)
    model = _model_override_for(settings, provider)
    if model is None and provider == "anthropic":
        # No free-text override: honour the UI dropdown choice (alias). Any
        # unknown value passes through resolve_anthropic_model() unchanged.
        choice = preferred_model or (getattr(settings, "preferred_model", None) if settings else None)
        if isinstance(choice, str) and choice.strip():
            model = choice.strip()
    return provider, api_key, model
