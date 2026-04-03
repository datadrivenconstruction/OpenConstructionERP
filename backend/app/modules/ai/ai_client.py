# OpenConstructionERP — DataDrivenConstruction (DDC)
# CWICR AI Estimation Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""AI API client — async calls to Anthropic, OpenAI, and Google Gemini.

All calls use httpx for async HTTP. No SDK dependencies required.
Each function takes an API key, prompt, optional image, and returns raw text.
JSON extraction is handled separately.
"""

import base64
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Model defaults ───────────────────────────────────────────────────────────

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
OPENAI_MODEL = "gpt-4o"
GEMINI_MODEL = "gemini-2.0-flash"
OPENROUTER_MODEL = "anthropic/claude-sonnet-4-20250514"
MISTRAL_MODEL = "mistral-large-latest"
GROQ_MODEL = "llama-3.3-70b-versatile"
DEEPSEEK_MODEL = "deepseek-chat"

# Timeout for AI API calls (2 minutes — large BOQ generation can be slow)
AI_TIMEOUT = 120.0


# ── Anthropic Claude ─────────────────────────────────────────────────────────


async def call_anthropic(
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    model: str = ANTHROPIC_MODEL,
    max_tokens: int = 4096,
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
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_media_type,
                "data": image_base64,
            },
        })
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
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
    tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get(
        "output_tokens", 0
    )
    return text, tokens


# ── OpenAI ───────────────────────────────────────────────────────────────────


async def call_openai(
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    model: str = OPENAI_MODEL,
    max_tokens: int = 4096,
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
        user_content.append({
            "type": "image_url",
            "image_url": {"url": data_url},
        })
    user_content.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
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

    text = data["choices"][0]["message"]["content"]
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return text, tokens


# ── Google Gemini ────────────────────────────────────────────────────────────


async def call_gemini(
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    model: str = GEMINI_MODEL,
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
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )

    parts: list[dict[str, Any]] = []
    if image_base64:
        parts.append({
            "inline_data": {
                "mime_type": image_media_type,
                "data": image_base64,
            },
        })
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
}


async def call_openai_compatible(
    provider: str,
    api_key: str,
    system: str,
    prompt: str,
    image_base64: str | None = None,
    image_media_type: str = "image/jpeg",
    max_tokens: int = 4096,
) -> tuple[str, int]:
    """Call any OpenAI-compatible API (OpenRouter, Mistral, Groq, DeepSeek).

    These providers all implement the OpenAI chat completions format.
    """
    config = _OPENAI_COMPAT_CONFIG.get(provider)
    if not config:
        msg = f"Unknown OpenAI-compatible provider: {provider}"
        raise ValueError(msg)

    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "extra_headers" in config:
        headers.update(config["extra_headers"])

    user_content: list[dict[str, Any]] = []
    if image_base64:
        data_url = f"data:{image_media_type};base64,{image_base64}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": data_url},
        })
    user_content.append({"type": "text", "text": prompt})

    payload = {
        "model": config["model"],
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            config["url"],
            headers=headers,
            json=payload,
            timeout=AI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

    text = data["choices"][0]["message"]["content"]
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

    # OpenAI-compatible providers
    if provider in _OPENAI_COMPAT_CONFIG:
        try:
            return await call_openai_compatible(
                provider, api_key, system, prompt, image_base64, image_media_type,
                max_tokens=max_tokens,
            )
        except httpx.HTTPStatusError:
            raise  # Will be caught below
    caller = callers.get(provider)
    if caller is None:
        msg = f"Unknown AI provider: {provider}"
        raise ValueError(msg)

    try:
        return await caller(
            api_key, system, prompt, image_base64, image_media_type,
            max_tokens=max_tokens,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        # Try to extract error detail from response body
        try:
            body = exc.response.json()
            detail = body.get("error", {}).get("message", "") or str(body)
        except Exception:
            detail = exc.response.text[:200]

        if status_code == 400 and image_base64:
            msg = "The image could not be processed by the AI. Please upload a clearer building photo (JPEG/PNG, at least 200x200 pixels)."
            raise ValueError(msg) from exc
        if status_code == 401:
            msg = f"AI API key is invalid or expired ({provider}). Please update your API key in Settings."
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


def resolve_provider_and_key(
    settings: Any,
    preferred_model: str | None = None,
) -> tuple[str, str]:
    """Determine which AI provider and API key to use based on user settings.

    Args:
        settings: AISettings ORM object with api key fields.
        preferred_model: Optional model preference override.

    Returns:
        Tuple of (provider_name, api_key).

    Raises:
        ValueError: If no API key is configured.
    """
    model = preferred_model or (settings.preferred_model if settings else "claude-sonnet")

    # Map model preferences to providers
    if "claude" in model or "anthropic" in model:
        if settings and settings.anthropic_api_key:
            return "anthropic", settings.anthropic_api_key
    elif "gpt" in model or "openai" in model:
        if settings and settings.openai_api_key:
            return "openai", settings.openai_api_key
    elif "gemini" in model or "google" in model:
        if settings and settings.gemini_api_key:
            return "gemini", settings.gemini_api_key
    elif "openrouter" in model or "router" in model:
        if settings and settings.openrouter_api_key:
            return "openrouter", settings.openrouter_api_key
    elif "mistral" in model:
        if settings and settings.mistral_api_key:
            return "mistral", settings.mistral_api_key
    elif "groq" in model or "llama" in model:
        if settings and settings.groq_api_key:
            return "groq", settings.groq_api_key
    elif "deepseek" in model:
        if settings and settings.deepseek_api_key:
            return "deepseek", settings.deepseek_api_key

    # Fallback: try any available key (in priority order)
    if settings:
        if settings.anthropic_api_key:
            return "anthropic", settings.anthropic_api_key
        if settings.openai_api_key:
            return "openai", settings.openai_api_key
        if settings.gemini_api_key:
            return "gemini", settings.gemini_api_key
        if settings.openrouter_api_key:
            return "openrouter", settings.openrouter_api_key
        if settings.mistral_api_key:
            return "mistral", settings.mistral_api_key
        if settings.groq_api_key:
            return "groq", settings.groq_api_key
        if settings.deepseek_api_key:
            return "deepseek", settings.deepseek_api_key

    msg = (
        "No AI API key configured. Please add your API key in Settings > AI. "
        "Supported: Anthropic, OpenAI, Gemini, OpenRouter, Mistral, Groq, DeepSeek."
    )
    raise ValueError(msg)
