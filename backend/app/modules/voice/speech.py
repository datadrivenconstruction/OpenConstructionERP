# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pluggable speech-to-text providers.

The application server never runs a speech model itself: a model that turns an
hour of audio into text needs more memory than the whole server budget. Speech
is therefore always a remote call, and which remote is a deployment choice:

* ``hosted`` - the hosted transcription endpoint keyed by the user's (or the
  app's) OpenAI-compatible key, the path the phone log and voice capture use.
* ``self_hosted`` - any server that speaks the same multipart
  ``/audio/transcriptions`` protocol, configured with ``OE_SPEECH_BASE_URL``
  (plus optional ``OE_SPEECH_API_KEY`` and ``OE_SPEECH_MODEL``). The operator
  runs it on another machine, so the speech model never shares this server.
* ``none`` - no server-side transcription. Callers degrade to the browser's own
  speech recognition or to minutes typed by hand.

``OE_SPEECH_PROVIDER`` picks one (``auto`` by default: self-hosted when a URL is
set, else hosted when a key exists, else none). Modules add their own provider
with :func:`register_speech_provider`; nothing here imports a vendor SDK.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.phonelog import transcription as phonelog_transcription

logger = logging.getLogger(__name__)

TranscriptionResult = phonelog_transcription.TranscriptionResult

#: Provider names with a built-in resolver, in ``auto`` preference order.
BUILTIN_PROVIDERS: tuple[str, ...] = ("self_hosted", "hosted")
PROVIDER_ENV = "OE_SPEECH_PROVIDER"
BASE_URL_ENV = "OE_SPEECH_BASE_URL"
API_KEY_ENV = "OE_SPEECH_API_KEY"
MODEL_ENV = "OE_SPEECH_MODEL"


class SpeechProvider(Protocol):
    """A configured speech-to-text backend."""

    name: str
    model: str

    async def transcribe(
        self,
        content: bytes,
        filename: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        """Return a transcript; never raise on a provider failure."""
        ...


@dataclass
class HttpSpeechProvider:
    """Multipart ``/audio/transcriptions`` client shared by both built-ins."""

    name: str
    api_key: str
    model: str
    url: str | None = None

    async def transcribe(
        self,
        content: bytes,
        filename: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        return await phonelog_transcription.transcribe_audio(
            content,
            filename,
            api_key=self.api_key,
            prompt=prompt,
            language=language,
            url=self.url,
            model=self.model,
        )


Resolver = Callable[[Any, str | None], Awaitable[SpeechProvider | None]]
_REGISTRY: dict[str, Resolver] = {}


def register_speech_provider(name: str, resolver: Resolver) -> None:
    """Register (or replace) a provider resolver under ``name``.

    The resolver receives ``(session, user_id)`` and returns a ready provider,
    or None when it is not configured for that caller.
    """
    _REGISTRY[name.strip().lower()] = resolver


def registered_providers() -> list[str]:
    """Names of every registered provider."""
    return sorted(_REGISTRY)


def configured_choice() -> str:
    """The operator's provider choice (``auto`` when unset)."""
    return (os.environ.get(PROVIDER_ENV) or "auto").strip().lower() or "auto"


def self_hosted_url() -> str | None:
    """Full transcription URL of the self-hosted endpoint, or None."""
    base = (os.environ.get(BASE_URL_ENV) or "").strip().rstrip("/")
    if not base:
        return None
    if base.endswith("/audio/transcriptions"):
        return base
    return f"{base}/audio/transcriptions"


async def _resolve_self_hosted(_session: Any, _user_id: str | None) -> SpeechProvider | None:
    url = self_hosted_url()
    if not url:
        return None
    return HttpSpeechProvider(
        name="self_hosted",
        api_key=(os.environ.get(API_KEY_ENV) or "").strip(),
        model=(os.environ.get(MODEL_ENV) or "").strip() or phonelog_transcription.TRANSCRIBE_MODEL,
        url=url,
    )


async def _resolve_hosted(session: Any, user_id: str | None) -> SpeechProvider | None:
    key = await phonelog_transcription.resolve_openai_key(session, user_id)
    if not key:
        return None
    return HttpSpeechProvider(name="hosted", api_key=key, model=phonelog_transcription.TRANSCRIBE_MODEL)


register_speech_provider("self_hosted", _resolve_self_hosted)
register_speech_provider("hosted", _resolve_hosted)


async def resolve_speech_provider(session: Any, user_id: str | None) -> SpeechProvider | None:
    """Return the provider this caller should use, or None for no server speech.

    Never raises: a resolver that fails is logged and treated as unconfigured.
    """
    choice = configured_choice()
    if choice in ("none", "off", "disabled", "browser"):
        return None
    names = list(BUILTIN_PROVIDERS) if choice == "auto" else [choice]
    for name in names:
        resolver = _REGISTRY.get(name)
        if resolver is None:
            logger.warning("Speech provider %r is not registered", name)
            continue
        try:
            provider = await resolver(session, user_id)
        except Exception as exc:  # noqa: BLE001 - a broken provider must degrade, not crash
            logger.warning("Speech provider %r failed to resolve: %s", name, type(exc).__name__)
            continue
        if provider is not None:
            return provider
    return None
