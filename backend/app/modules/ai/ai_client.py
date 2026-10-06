# OpenConstructionERP - DataDrivenConstruction (DDC)
# CWICR AI Estimation Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""AI API client - async calls to Anthropic, OpenAI, and Google Gemini.

All calls use httpx for async HTTP. No SDK dependencies required.
Each function takes an API key, prompt, optional image, and returns raw text.
JSON extraction is handled separately.
"""

import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
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

#: The runtimes a user hosts themselves rather than calling over the internet.
#: Naming the pair once is not tidiness: three separate decisions read it, and
#: while it was written out as a literal at four call sites nothing tied them
#: together. These are the only providers that accept a base URL supplied by
#: the user, the only ones allowed to run with no stored key, and the ones that
#: have to be matched before the generic "llama" keyword, since "ollama"
#: contains it. A fifth runtime added to three of the four would have looked
#: like it worked.
SELF_HOSTED_PROVIDERS: tuple[str, ...] = ("ollama", "vllm")


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


# Built-in timeout for AI API calls (4 minutes - large BOQ generation can be
# slow). Used only when neither the caller, the user's settings nor the
# environment names one; see :func:`effective_ai_timeout`.
AI_TIMEOUT = 240.0

# The user's per-provider timeout for the settings resolved in this request,
# bound next to the self-hosted endpoints (issue #499). None means the user set
# none, which is different from the built-in value: an explicit timeout also
# lifts caps that exist only to bound the built-in one (the agents' step cap).
_USER_AI_TIMEOUT: ContextVar[float | None] = ContextVar("oe_ai_user_timeout", default=None)


def _saved_timeouts(saved_meta: dict | None) -> dict[str, float]:
    """The per-provider timeouts one user's settings metadata names, in range."""
    from app.config import AI_TIMEOUT_MAX_S, AI_TIMEOUT_MIN_S

    raw = saved_meta.get("timeouts") if isinstance(saved_meta, dict) else None
    found: dict[str, float] = {}
    if isinstance(raw, dict):
        for provider, seconds in raw.items():
            if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds > 0:
                found[str(provider)] = min(max(float(seconds), AI_TIMEOUT_MIN_S), AI_TIMEOUT_MAX_S)
    return found


def user_ai_timeout() -> float | None:
    """The timeout the current user saved for the provider being called, if any."""
    return _USER_AI_TIMEOUT.get()


def configured_ai_timeout() -> float | None:
    """The timeout someone chose: the user's for this provider, else ``OE_AI_TIMEOUT``.

    None when nobody did, so callers can tell a chosen value from the default.
    """
    user = _USER_AI_TIMEOUT.get()
    if user is not None:
        return user
    from app.config import get_settings

    return get_settings().ai_timeout


def effective_ai_timeout(timeout: float | None = None) -> float:
    """Seconds to wait for a provider: explicit argument, then user, then env, then built-in."""
    if timeout is not None:
        return timeout
    configured = configured_ai_timeout()
    return configured if configured is not None else AI_TIMEOUT


# ── Anthropic Claude ─────────────────────────────────────────────────────────


async def call_anthropic(
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    model: str | None = None,
    max_tokens: int = 4096,
    timeout: float | None = None,
) -> tuple[str, int]:
    """Call Anthropic Claude API.

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
            timeout=effective_ai_timeout(timeout),
        )
        response.raise_for_status()
        data = response.json()

    text = data["content"][0]["text"]
    tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0)
    return text, tokens


# ── OpenAI-shaped response extraction (shared) ───────────────────────────────


def _http_error_detail(response: httpx.Response) -> str:
    """Best-effort human-readable detail out of a provider error response.

    Args:
        response: The non-2xx response carried by an ``httpx.HTTPStatusError``.

    Returns:
        The provider's error message, or the raw body prefix when the body is
        not the usual ``{"error": {"message": ...}}`` envelope.
    """
    try:
        body = response.json()
        return body.get("error", {}).get("message", "") or str(body)
    except Exception:
        return response.text[:200]


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
    timeout: float | None = None,
) -> tuple[str, int]:
    """Call OpenAI API (ChatCompletions).

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
            timeout=effective_ai_timeout(timeout),
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
    timeout: float | None = None,
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
            timeout=effective_ai_timeout(timeout),
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
    # Self-hosted endpoints - OpenAI-compatible REST API. Override the base URL
    # via OE_OLLAMA_URL / OE_VLLM_URL env vars to point at a non-default host
    # (default Ollama :11434, default VLLM :8001 to avoid colliding with our
    # backend on :8000). "vllm" doubles as the generic OpenAI-compatible
    # endpoint (issue #499): its optional key is the one saved in Settings > AI
    # or OE_VLLM_API_KEY, sent as a bearer token. Without a key the
    # Authorization header is omitted entirely. Ollama takes no key.
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


# The self-hosted endpoints belonging to the settings currently being
# resolved. Empty means "nobody named one", which is the env / localhost
# default in _OPENAI_COMPAT_CONFIG above and never another user's host.
_SELF_HOSTED_ENDPOINTS: ContextVar[dict[str, str] | None] = ContextVar("oe_ai_self_hosted_endpoints", default=None)


def _normalise_self_hosted_url(candidate: str) -> str:
    """Return *candidate* as a full chat-completions endpoint.

    Users save the runtime's root ("http://gpu-box:11434") far more often than
    its chat path, so the path is completed when it is missing. Gateways are
    usually written with their API root ("https://gw.example/v1"), which only
    lacks the last two segments, and a full ".../chat/completions" path is
    taken as given. Kept separate from any storage so the same normalisation
    applies to a row that was written before it existed, and shared with the
    connection test so a test cannot pass on a URL the real call never uses.
    """
    endpoint = candidate.strip().rstrip("/")
    if endpoint.endswith("/chat/completions"):
        return endpoint
    if endpoint.endswith("/v1"):
        return endpoint + "/chat/completions"
    return endpoint + "/v1/chat/completions"


def self_hosted_endpoints(saved_meta: dict | None) -> dict[str, str]:
    """Extract the Ollama / vLLM endpoints one user's settings metadata names.

    Only these two runtimes are tunable: every other provider is a fixed
    vendor URL, and letting a user rewrite those would be an open redirect for
    their own API key.
    """
    meta = saved_meta if isinstance(saved_meta, dict) else {}
    found: dict[str, str] = {}
    for provider in SELF_HOSTED_PROVIDERS:
        candidate = meta.get(f"{provider}_base_url")
        if isinstance(candidate, str) and candidate.strip():
            found[provider] = _normalise_self_hosted_url(candidate)
    return found


def use_self_hosted_endpoints(saved_meta: dict | None) -> None:
    """Bind the self-hosted endpoints of the settings being resolved right now.

    The binding is a context variable, so it reaches the dispatch below
    without every intermediate signature having to carry a URL, and it reaches
    nothing else: an asyncio task inherits a copy of the context, so one
    request cannot see - or overwrite - what another request bound.

    This used to be a module-global dictionary that the settings endpoint
    mutated in place (GHSA-wfpw-cv5v-64j5). Saving an Ollama URL therefore
    repointed the runtime for every user sharing the worker process, and the
    next person to run an estimate sent their project to whatever host the
    last person to touch their own settings had named. Both halves of that are
    fixed here: the value is bound per call rather than per process, and it is
    always bound, so settings without an endpoint clear whatever the previous
    resolution in this task left behind.

    The tool calling modes saved for those endpoints travel with them, for the
    same reason and with the same clearing rule.
    """
    _SELF_HOSTED_ENDPOINTS.set(self_hosted_endpoints(saved_meta))
    _SELF_HOSTED_TOOL_MODES.set(_saved_tool_modes(saved_meta))


# ── Tool calling on self-hosted endpoints (issue #499) ───────────────────────

#: "auto" sends the tool schema and falls back to a plain request when the
#: endpoint refuses it, remembering the refusal; "on" always sends it; "off"
#: never does.
TOOL_CALLING_MODES: tuple[str, ...] = ("auto", "on", "off")

_SELF_HOSTED_TOOL_MODES: ContextVar[dict[str, str] | None] = ContextVar("oe_ai_self_hosted_tool_modes", default=None)


def _saved_tool_modes(saved_meta: dict | None) -> dict[str, str]:
    """The tool calling modes one user's settings name for their self-hosted endpoints."""
    raw = saved_meta.get("tool_calling") if isinstance(saved_meta, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        provider: mode
        for provider, mode in raw.items()
        if provider in SELF_HOSTED_PROVIDERS and mode in TOOL_CALLING_MODES
    }


def default_tool_calling_mode(provider: str) -> str:
    """The server default: "auto" for providers listed in ``OE_AI_TOOLS_SELF_HOSTED``, else "off"."""
    if provider not in SELF_HOSTED_PROVIDERS:
        return "off"
    from app.config import get_settings

    listed = {p.strip().lower() for p in (get_settings().ai_tools_self_hosted or "").split(",")}
    return "auto" if provider in listed else "off"


def tool_calling_mode(provider: str) -> str:
    """Whether the assistant offers its tools to *provider* for the settings resolved now.

    Only the self-hosted endpoints are configurable; every other provider is
    "off" here and keeps the routing the assistant decides on by name.
    """
    if provider not in SELF_HOSTED_PROVIDERS:
        return "off"
    return (_SELF_HOSTED_TOOL_MODES.get() or {}).get(provider) or default_tool_calling_mode(provider)


# ── Optional key of the OpenAI-compatible endpoint (issue #499) ──────────────

#: Server-wide fallback key per self-hosted provider, for headless deploys.
_SELF_HOSTED_KEY_ENV: dict[str, str] = {"vllm": "OE_VLLM_API_KEY"}


def self_hosted_api_key(settings: Any, provider: str) -> str:
    """The bearer key for a self-hosted endpoint, or "" when it takes none.

    The key saved in Settings > AI wins over the environment one. A saved key
    that no longer decrypts is an error, not a silent anonymous request: the
    gateway would answer 401 and the user would be told their key is wrong
    when it is the server's encryption key that changed.

    Raises:
        ValueError: If a saved key cannot be decrypted.
    """
    from app.core.crypto import decrypt_secret

    raw = getattr(settings, f"{provider}_api_key", None) if settings else None
    if isinstance(raw, str) and raw:
        decrypted = decrypt_secret(raw)
        if decrypted:
            return decrypted
        msg = (
            "The saved key of the OpenAI-compatible endpoint could not be decrypted - the backend "
            "encryption key has rotated since it was saved. Please re-enter it in Settings > AI."
        )
        raise ValueError(msg)
    env_name = _SELF_HOSTED_KEY_ENV.get(provider)
    return (os.environ.get(env_name) or "").strip() if env_name else ""


def _openai_compat_endpoint(provider: str, base_url: str | None = None) -> str:
    """The URL a call to *provider* goes to.

    An explicit argument wins, then the endpoint bound for the settings this
    call was resolved from, then the process default. The middle term is what
    makes one user's self-hosted runtime theirs alone.
    """
    return base_url or (_SELF_HOSTED_ENDPOINTS.get() or {}).get(provider) or _OPENAI_COMPAT_CONFIG[provider]["url"]


async def _post_openai_compat(
    provider: str,
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    tools: list[dict[str, Any]] | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST one OpenAI-shaped chat completion and return the parsed body.

    The single transport choke point for every OpenAI-compatible provider.
    Header assembly, the per-provider ``extra_headers`` (OpenRouter's
    ``HTTP-Referer``), endpoint resolution and the self-hosted SSRF guard all
    live here, so a new caller cannot acquire the transport without them.

    Args:
        provider: Provider id present in :data:`_OPENAI_COMPAT_CONFIG`.
        api_key: Provider API key; the header is omitted when blank.
        messages: Full chat messages array, system turn included.
        model: Model id override. When falsy the provider default is used.
        max_tokens: Maximum response tokens.
        tools: OpenAI-format tool schema. Omitted from the payload entirely
            when falsy, which keeps the plain-text request byte-identical.
        base_url: Endpoint override for self-hosted runtimes.
        timeout: Request timeout in seconds.

    Returns:
        The parsed JSON response body.

    Raises:
        ValueError: If the provider is unknown.
        httpx.HTTPStatusError: On a non-2xx response.
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

    payload: dict[str, Any] = {
        "model": model or config["model"],
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    endpoint = _openai_compat_endpoint(provider, base_url)
    # SSRF guard for self-hosted runtimes: their endpoint is user-supplied, so
    # re-resolve and re-check it at this single dispatch choke point (every
    # Ollama / vLLM call funnels through here). Loopback / private stay allowed;
    # link-local and cloud-metadata are blocked, plus any configured allowlist.
    if provider in SELF_HOSTED_PROVIDERS:
        from app.config import get_settings
        from app.core.url_safety import resolve_and_validate_ai_provider_url

        await resolve_and_validate_ai_provider_url(endpoint, get_settings().ai_provider_allowlist_hosts)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=effective_ai_timeout(timeout),
        )
        response.raise_for_status()
        return response.json()


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
    timeout: float | None = None,
) -> tuple[str, int]:
    """Call any OpenAI-compatible API (OpenRouter, Mistral, Groq, DeepSeek).

    These providers all implement the OpenAI chat completions format.

    Args:
        model: Optional model id override. When falsy, the provider's
            built-in default model is used.
        base_url: Optional endpoint override for self-hosted backends
            (Ollama/vLLM); takes precedence over the configured URL.
    """
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

    data = await _post_openai_compat(
        provider,
        api_key,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        model=model,
        max_tokens=max_tokens,
        base_url=base_url,
        timeout=timeout,
    )

    text = _extract_openai_message_text(provider, data)
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return text, tokens


# ── Tool-carrying calls over the OpenAI protocol ─────────────────────────────

# Keyword fragments that identify a provider refusing the ``tools`` FIELD, as
# opposed to refusing the model id (``model_keywords`` in :func:`call_ai`).
# Every entry names a tool/function noun on purpose: a bare "unsupported" or
# "not supported" also matches a model rejection, and overlapping the two sets
# would fire a redundant request before the issue #148 recovery could run.
_TOOLS_REJECTED_KEYWORDS = (
    "does not support tools",
    "does not support tool",
    "no endpoints found that support tool use",
    "tool use is not supported",
    "tool calling is not supported",
    "tools are not supported",
    "tools is not supported",
    "function calling is not supported",
    "functions are not supported",
    "unsupported parameter: 'tools'",
    "unsupported parameter: 'tool_choice'",
    "unknown parameter: 'tools'",
    "invalid parameter: 'tools'",
    "tool_choice",
    # vLLM started without a tool parser, verbatim from
    # vllm/renderers/online_renderer.py (HTTP 400): '"auto" tool choice
    # requires --enable-auto-tool-choice and --tool-call-parser to be set'.
    # Spelled with a space, so "tool_choice" above never matched it and the
    # retry did not fire (issue #499).
    "tool choice requires",
    "enable-auto-tool-choice",
)

#: How long an endpoint's refusal of the tool schema is remembered in "auto"
#: mode before it is asked again, in seconds. Long enough that a chat does not
#: pay a refused request per turn, short enough that restarting the runtime
#: with a tool parser takes effect within the hour without a backend restart.
TOOLS_REFUSAL_TTL_S = 3600.0

# (endpoint URL, model id) -> monotonic time the refusal expires. Keyed by the
# endpoint and model rather than the provider id: two users can point "vllm"
# at different hosts, and one gateway serves models with and without tools.
# In-process on purpose - losing it on restart costs one refused request.
_TOOLS_REFUSED: dict[tuple[str, str], float] = {}


def _tools_refused(key: tuple[str, str]) -> bool:
    expires = _TOOLS_REFUSED.get(key)
    if expires is None:
        return False
    if time.monotonic() >= expires:
        _TOOLS_REFUSED.pop(key, None)
        return False
    return True


def _is_tools_rejection(status_code: int, detail: str) -> bool:
    """Return True when a provider refused the request BECAUSE of ``tools``.

    Args:
        status_code: HTTP status the provider returned.
        detail: Provider error message, already pulled out of the body.

    Returns:
        True when the request is worth retrying without a tool schema.
    """
    if status_code not in (400, 404, 422):
        return False
    low = (detail or "").lower()
    return any(k in low for k in _TOOLS_REJECTED_KEYWORDS)


async def call_openai_compatible_tools(
    provider: str,
    api_key: str,
    system: str,
    system_without_tools: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    timeout: float | None = None,
    remember_refusal: bool = False,
) -> tuple[dict[str, Any], int]:
    """Call an OpenAI-compatible provider WITH a tool schema on the wire.

    Issue #424: tool access used to be an allowlist of two provider names, so
    a provider speaking this exact protocol was called as plain text and told
    the user it had no way to read their data. The default is inverted here -
    assume an OpenAI-compatible endpoint takes tools, and degrade when it says
    otherwise: a provider that refuses the ``tools`` field is retried ONCE
    without it, and that retry also swaps ``system`` for
    ``system_without_tools``. The two always move together, because a
    tool-advertising prompt with no schema on the wire is issue #417.

    Args:
        provider: Provider id present in :data:`_OPENAI_COMPAT_CONFIG`.
        api_key: Provider API key.
        system: System prompt used while the tool schema is on the wire.
        system_without_tools: System prompt for the degraded retry.
        messages: Chat messages WITHOUT the system turn - it is prepended here
            so the retry can swap it.
        tools: OpenAI-format tool schema.
        model: Model id override. When falsy the provider default is used.
        max_tokens: Maximum response tokens.
        timeout: Request timeout in seconds.
        remember_refusal: Remember a refusal for this endpoint and model for
            :data:`TOOLS_REFUSAL_TTL_S`, and while it is remembered send the
            plain request straight away. The "auto" mode of a self-hosted
            endpoint (issue #499); other callers ask every time.

    Returns:
        Tuple of (raw response body, tokens_used). The body is returned
        unparsed because the caller reads tool calls out of it.

    Raises:
        httpx.HTTPStatusError: On a non-2xx response that is not a tools
            rejection, and on a failed retry.
    """
    config = _OPENAI_COMPAT_CONFIG.get(provider) or {}
    refusal_key = (_openai_compat_endpoint(provider), model or config.get("model", ""))
    if remember_refusal and _tools_refused(refusal_key):
        data = await _post_openai_compat(
            provider,
            api_key,
            [{"role": "system", "content": system_without_tools}, *messages],
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return data, int((data.get("usage") or {}).get("total_tokens", 0) or 0)

    try:
        data = await _post_openai_compat(
            provider,
            api_key,
            [{"role": "system", "content": system}, *messages],
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            timeout=timeout,
        )
    except httpx.HTTPStatusError as exc:
        detail = _http_error_detail(exc.response)
        if not _is_tools_rejection(exc.response.status_code, detail):
            raise
        logger.warning(
            "call_openai_compatible_tools: %s refused the tool schema (HTTP %s: %s); retrying once without tools",
            provider,
            exc.response.status_code,
            detail[:200],
        )
        if remember_refusal:
            _TOOLS_REFUSED[refusal_key] = time.monotonic() + TOOLS_REFUSAL_TTL_S
        data = await _post_openai_compat(
            provider,
            api_key,
            [{"role": "system", "content": system_without_tools}, *messages],
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    tokens = int((data.get("usage") or {}).get("total_tokens", 0) or 0)
    return data, tokens


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
    timeout: float | None = None,
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
                    timeout=timeout,
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
                    timeout=timeout,
                )

            return _call

    else:
        msg = f"Unknown AI provider: {provider}"
        raise ValueError(msg)

    return await _call_with_model_recovery(provider, _make_call, model, image_base64=image_base64)


async def _call_with_model_recovery[T](
    provider: str,
    make_call: Callable[[str | None], Callable[[], Awaitable[T]]],
    model: str | None,
    *,
    image_base64: str | None = None,
) -> T:
    """Run a provider call, self-healing a rejected model id, then map errors.

    Shared by :func:`call_ai` and :func:`call_ai_tools` so both the plain-text
    and the tool-carrying paths get the issue #148 dead-slug retry and the same
    user-facing error wording. Generic over the call's return type: the text
    path returns ``(text, tokens)`` and the tool path returns
    ``(raw_body, tokens)``.

    Args:
        provider: Provider id, used in every user-facing message.
        make_call: Builds the awaitable for a given model id. Parameterising
            the model (rather than closing over one) is what lets the error
            path retry with a fallback slug.
        model: The configured/overridden model id, or None for the default.
        image_base64: Present only so a 400 on an image request keeps its
            specific message.

    Returns:
        Whatever ``make_call`` returns.

    Raises:
        ValueError: With an actionable message for every mapped provider error.
    """
    # The actual model id this call will use (override or built-in default) -
    # surfaced in "model not found" errors so the user knows exactly what to
    # change in Settings > AI.
    effective_model = model or default_model_for(provider)

    # Unified error handling for all providers
    try:
        return await make_call(model)()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        # Try to extract error detail from response body
        detail = _http_error_detail(exc.response)

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
                    result = await make_call(fb_model)()
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


async def call_ai_tools(
    provider: str,
    api_key: str,
    system: str,
    system_without_tools: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    timeout: float | None = None,
    remember_refusal: bool = False,
) -> tuple[dict[str, Any], int]:
    """Route a tool-carrying call to an OpenAI-compatible provider (issue #424).

    The tool-schema sibling of :func:`call_ai`, deliberately a separate entry
    point rather than a flag: :func:`call_ai` returns text, and an agent loop
    needs the raw body to read tool calls out of. Both go through
    :func:`_call_with_model_recovery`, so a retired model slug self-heals onto
    a provider-stable fallback here exactly as it does on the plain-text path
    (issue #148). That matters most on aggregators like OpenRouter, whose
    dated slugs are retired continuously - the very slug class in the #424
    report. The tools-rejection retry lives one layer down, in
    :func:`call_openai_compatible_tools`, so it also applies to the fallback
    slug the recovery lands on.

    Args:
        provider: Provider id that speaks the OpenAI chat-completions protocol.
        api_key: Provider API key.
        system: System prompt used while the tool schema is on the wire.
        system_without_tools: System prompt for the degraded retry.
        messages: Chat messages without the system turn.
        tools: OpenAI-format tool schema.
        model: Model id override. When falsy the provider default is used.
        max_tokens: Maximum response tokens.
        timeout: Request timeout in seconds.
        remember_refusal: See :func:`call_openai_compatible_tools`.

    Returns:
        Tuple of (raw response body, tokens_used).

    Raises:
        ValueError: If the provider does not speak this protocol, or for any
            mapped provider error.
    """
    if provider not in _OPENAI_COMPAT_CONFIG:
        msg = f"Provider does not speak the OpenAI tool protocol: {provider}"
        raise ValueError(msg)

    def _make_call(model_id: str | None):
        async def _call() -> tuple[dict[str, Any], int]:
            return await call_openai_compatible_tools(
                provider,
                api_key,
                system,
                system_without_tools,
                messages,
                tools,
                model=model_id,
                max_tokens=max_tokens,
                timeout=timeout,
                remember_refusal=remember_refusal,
            )

        return _call

    return await _call_with_model_recovery(provider, _make_call, model)


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

    Also binds, for the rest of this request, what these settings say about
    how to call the provider: the self-hosted endpoints and their tool calling
    modes, and the user's timeout for the provider resolved (issue #499).

    Args:
        settings: AISettings ORM object with api key fields.
        preferred_model: Optional model preference override.

    Returns:
        Tuple of (provider_name, api_key).

    Raises:
        ValueError: If no API key is configured.
    """
    meta = getattr(settings, "metadata_", None) if settings else None
    # Bind before resolving: whichever provider this resolves to, the dispatch
    # that follows in this task must use THESE settings' endpoints, and a
    # failed resolution must not leave the previous user's timeout behind.
    use_self_hosted_endpoints(meta)
    _USER_AI_TIMEOUT.set(None)
    provider, api_key = _resolve_provider_and_key(settings, preferred_model)
    _USER_AI_TIMEOUT.set(_saved_timeouts(meta).get(provider))
    return provider, api_key


def _resolve_provider_and_key(settings: Any, preferred_model: str | None) -> tuple[str, str]:
    """The provider choice behind :func:`resolve_provider_and_key`, without the bindings."""
    from app.core.crypto import decrypt_secret

    model = preferred_model or (settings.preferred_model if settings else "claude-sonnet")

    # Map model preferences to providers
    # The key slot is ``str | None``: the self-hosted runtimes below have no
    # REQUIRED key, and that is the thing the loop branches on - their optional
    # one comes from :func:`self_hosted_api_key`. An empty string here would be
    # worse than no annotation - it reads the same as None to ``if key_attr:``
    # but not to ``getattr``.
    _MODEL_PROVIDER_MAP: list[tuple[list[str], str, str | None]] = [
        (["claude", "anthropic"], "anthropic", "anthropic_api_key"),
        (["gpt", "openai"], "openai", "openai_api_key"),
        (["gemini", "google"], "gemini", "gemini_api_key"),
        (["openrouter", "router"], "openrouter", "openrouter_api_key"),
        (["mistral"], "mistral", "mistral_api_key"),
        # Self-hosted keyless runtimes must be matched BEFORE the generic
        # "llama" keyword below: "ollama" contains "llama", so a user picking
        # preferred_model=ollama would otherwise be routed to Groq.
        *[([name], name, None) for name in SELF_HOSTED_PROVIDERS],
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
            if key_attr is None:  # self-hosted provider, key optional
                return provider_name, self_hosted_api_key(settings, provider_name)
            raw = getattr(settings, key_attr, None) if settings else None
            if raw:
                decrypted = decrypt_secret(raw)
                if decrypted:
                    return provider_name, decrypted
                # key exists but is undecryptable (JWT_SECRET rotated) -
                # fall through so the fallback loop can try other providers
            break  # matched model but no (usable) key - fall through to fallback

    # Fallback: try any available key (in priority order)
    _FALLBACK_ORDER: list[tuple[str, str | None]] = [
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
        *[(name, None) for name in SELF_HOSTED_PROVIDERS],  # keyless, skipped below
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

    # Local-runtime fallback: a user who configured ONLY Ollama / vLLM (saved a
    # base_url, no cloud key) keeps the default preferred_model="claude-sonnet",
    # so the primary model->provider match above never routes to them. Honour
    # the saved local endpoint here - with its optional key, empty when it has
    # none - so a local-only setup is genuinely usable rather than collapsing into the
    # "No AI API key configured" error. An explicit cloud key still wins (above).
    if settings:
        # Read through the same helper the dispatch uses rather than walking
        # the metadata a second time here. The two copies could disagree about
        # what counts as a configured endpoint, and the one that decides
        # whether a local-only setup works at all is this one.
        configured = self_hosted_endpoints(getattr(settings, "metadata_", None))
        for local_provider in SELF_HOSTED_PROVIDERS:
            if local_provider in configured:
                return local_provider, self_hosted_api_key(settings, local_provider)

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
