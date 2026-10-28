# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Voice-capture service - transcribe a recording and structure a note into a draft.

This orchestrates the two AI-optional passes that sit behind the voice module's
single ``/voice/draft`` endpoint:

1. Transcription (audio -> text). Reused wholesale from the phone-log module's
   ``transcription`` helpers (the same speech-to-text path, upload validation,
   and key resolution) so there is one implementation, not two.
2. Structuring (text -> structured draft). One LLM pass through the shared
   ``app.modules.ai.ai_client`` provider layer that refines/translates the note
   and extracts the target's fields, then the pure ``voice.structuring`` engine
   cleans and clamps the result.

Both passes degrade gracefully: a missing key or a provider failure never raises
into the request path - transcription returns an unavailable result and
structuring falls back to the deterministic heuristic in ``voice.structuring``.
No database rows are written; the module is stateless by design.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.modules.phonelog import transcription as phonelog_transcription
from app.modules.voice import structuring

logger = logging.getLogger(__name__)

# The structuring pass is a short JSON extraction, so a modest cap keeps latency
# and cost down while leaving room for a tidied description in a longer note.
_STRUCTURE_MAX_TOKENS = 1200


async def transcribe(
    session: Any,
    content: bytes,
    filename: str,
    user_id: str | None,
) -> phonelog_transcription.TranscriptionResult:
    """Transcribe a recording, degrading to an unavailable result with no provider.

    Goes through the pluggable provider layer in :mod:`app.modules.voice.speech`
    (same 25 MB / format guardrails applied by the router). Never raises: with no
    provider it returns an unavailable result so the caller can fall back to the
    typed-transcript path.
    """
    from app.modules.voice.speech import resolve_speech_provider

    provider = await resolve_speech_provider(session, user_id)
    if provider is None:
        return phonelog_transcription.TranscriptionResult(
            available=False,
            error="no transcription provider configured",
        )
    return await provider.transcribe(content, filename)


async def build_draft(
    session: Any,
    *,
    target_type: str,
    text: str,
    target_language: str | None,
    user_id: str | None,
    transcription_language: str | None = None,
) -> dict[str, Any]:
    """Build a structured draft for ``target_type`` from ``text``.

    Runs the optional LLM extraction and then the pure structuring assembly. When
    no LLM provider is configured, the text is empty, or the call fails, the
    returned draft is built by the deterministic heuristic (``ai_generated`` is
    False). ``target_type`` is assumed already validated by the caller.
    """
    spec = structuring.target_spec(target_type)
    if spec is None:  # defensive: router validates, but never structure blind
        msg = f"Unknown voice target type: {target_type}"
        raise ValueError(msg)

    llm_result = await _extract_structured(session, spec, text, target_language, user_id)
    return structuring.assemble_draft(
        spec=spec,
        llm_result=llm_result,
        text=text,
        detected_language_hint=transcription_language,
    )


async def _extract_structured(
    session: Any,
    spec: structuring.TargetSpec,
    text: str,
    target_language: str | None,
    user_id: str | None,
) -> dict[str, Any] | None:
    """Run one LLM pass to refine + structure the note, or None on any degrade.

    Returns the parsed extraction dict, or None when no LLM provider is
    configured, the text is empty, or the call/parse fails. Every one of those
    degrades to a heuristic draft upstream - none of them raise. Mirrors
    ``phonelog.transcription.extract_protocol`` so the two AI paths behave alike.
    """
    if not text or not text.strip():
        return None

    try:
        from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
    except Exception as exc:  # noqa: BLE001 - AI module optional; degrade if unavailable
        logger.debug("AI client import failed: %s", exc)
        return None

    settings_row = None
    if session is not None and user_id:
        try:
            settings_row = await AISettingsRepository(session).get_by_user_id(uuid.UUID(str(user_id)))
        except Exception as exc:  # noqa: BLE001 - never let a settings lookup break capture
            logger.debug("AI settings lookup failed: %s", exc)

    try:
        provider, api_key, model_override = resolve_provider_key_model(settings_row)
    except ValueError:
        # No AI provider configured - the deterministic heuristic still runs.
        return None

    try:
        raw_response, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=structuring.structuring_system_prompt(spec, target_language),
            prompt=structuring.build_structuring_prompt(spec, text, target_language),
            max_tokens=_STRUCTURE_MAX_TOKENS,
            model=model_override,
        )
    except Exception as exc:  # noqa: BLE001 - provider error must degrade, not crash
        logger.warning("Voice structuring call failed: %s", type(exc).__name__)
        return None

    parsed = extract_json(raw_response)
    return parsed if isinstance(parsed, dict) else None
