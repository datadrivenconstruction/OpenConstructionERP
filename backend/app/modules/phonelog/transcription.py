# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Recording-to-protocol helpers for the phone-log module.

This is the audio/video ingestion path that sits in front of the pure
``phonelog.normalize`` engine. A user uploads a recording of a call, meeting, or
site conversation; we transcribe it with a speech-to-text provider and, when an
LLM provider is configured, run one extraction pass that turns the transcript
into a structured, dispute-ready protocol (participants, a short summary, key
decisions, and action items with an owner and an optional due date).

Design rules that this module keeps:

* AI is optional and degrades gracefully. If no provider is configured, or a
  provider call fails, we never raise into the request path - the recording is
  still stored and the record is created with an empty transcript so the user
  can paste a transcript by hand. Nothing here blocks or crashes on a missing
  key or a provider hiccup.
* AI suggests, a human confirms. Everything produced here is a *draft* the user
  reviews and edits before it is saved as a normal phone-log record.
* Lightweight. Transcription is a direct multipart POST to the provider's REST
  audio endpoint (no vendor SDK, no local model, no ffmpeg); the extraction pass
  reuses the platform's existing provider layer in ``app.modules.ai.ai_client``.

The pure helpers (:func:`audio_extension`, :func:`check_audio_upload`,
:func:`build_protocol` and the cleaners it calls) do no I/O and no framework or
database work, so they are independently unit-testable with the provider mocked.
The provider-calling coroutines keep their ``app`` imports local so importing
this module stays cheap and free of a database dependency.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.modules.phonelog.normalize import NormalizedPhoneLog

logger = logging.getLogger(__name__)

# Formats a speech-to-text provider accepts directly, so no ffmpeg transcode is
# needed. Kept as bare, lower-case extensions (no dot). "mp4"/"mpeg" cover the
# common phone-recorded video containers whose audio track transcribes directly.
ACCEPTED_AUDIO_EXTENSIONS: frozenset[str] = frozenset({"mp3", "m4a", "wav", "webm", "mp4", "mpeg", "mpga"})

# The provider's own hard limit for a single audio upload is 25 MB, so we reject
# anything larger up-front with a clear message rather than let the provider 413.
MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024

# Speech-to-text (transcription) endpoint and model. This is the one place that
# is provider-specific: only this provider exposes a directly-callable audio
# transcription REST endpoint, and the platform reads its key from OPENAI_API_KEY
# (or the per-user AI settings), matching the rest of the AI stack.
TRANSCRIBE_MODEL: str = "whisper-1"
_TRANSCRIBE_URL: str = "https://api.openai.com/v1/audio/transcriptions"
_TRANSCRIBE_TIMEOUT: float = 300.0

# The extraction pass is a normal text completion through the shared provider
# layer, so it works with whatever provider the user configured.
_EXTRACTION_MAX_TOKENS: int = 1500
# Cap the transcript we send to the extraction model so a very long recording
# cannot run up an unbounded bill; the head of a call carries the protocol.
_EXTRACTION_TRANSCRIPT_CHARS: int = 24000

_MIME_BY_EXT: dict[str, str] = {
    "mp3": "audio/mpeg",
    "mpga": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "m4a": "audio/mp4",
    "mp4": "video/mp4",
    "wav": "audio/wav",
    "webm": "audio/webm",
}

PROTOCOL_SYSTEM_PROMPT: str = (
    "You turn a transcript of a construction project call, meeting, or site "
    "conversation into a structured, dispute-ready protocol. Extract only what is "
    "actually stated in the transcript. Never invent names, decisions, dates, or "
    "tasks. If something is not in the transcript, leave it out. Respond with a "
    "single JSON object and nothing else."
)


@dataclass
class TranscriptionResult:
    """Outcome of a transcription attempt.

    ``available`` is True only when a usable transcript came back. On any failure
    (no key, provider error, empty result) ``available`` is False, ``text`` is
    empty, and ``error`` carries a short, non-sensitive reason for the record.
    """

    text: str = ""
    language: str | None = None
    duration_seconds: int | None = None
    available: bool = False
    error: str | None = None
    # Timed segments ``{start, end, text, speaker}`` when the provider returns them.
    segments: list[dict[str, Any]] = field(default_factory=list)


def audio_extension(filename: str) -> str:
    """Return the lower-case extension of ``filename`` without the dot ("" if none)."""
    name = (filename or "").strip()
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def mime_for(filename: str) -> str:
    """Return a best-effort media type for a recording filename or storage key."""
    return _MIME_BY_EXT.get(audio_extension(filename), "application/octet-stream")


def check_audio_upload(filename: str, size_bytes: int) -> tuple[int, str] | None:
    """Validate a recording upload before it is stored or transcribed.

    Returns ``None`` when the upload is acceptable, otherwise an
    ``(http_status, message)`` pair the router raises as an ``HTTPException``.
    The message names the accepted formats so the user can fix the input.
    """
    ext = audio_extension(filename)
    if ext not in ACCEPTED_AUDIO_EXTENSIONS:
        accepted = ", ".join(sorted(ACCEPTED_AUDIO_EXTENSIONS))
        got = f".{ext}" if ext else "that file"
        return (
            400,
            f"Cannot transcribe {got}. Upload an audio or video recording as one of: {accepted}.",
        )
    if size_bytes <= 0:
        return (400, "The uploaded recording is empty.")
    if size_bytes > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        got_mb = size_bytes / (1024 * 1024)
        return (
            413,
            f"Recording is too large ({got_mb:.1f} MB). The maximum is {max_mb} MB.",
        )
    return None


def _clean_text(value: Any, *, limit: int = 2000) -> str:
    """Coerce a value to a trimmed string capped at ``limit`` characters."""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()) if "\n" not in value else value.strip()
    return text[:limit].strip()


def _clean_str_list(value: Any, *, limit: int = 50, item_limit: int = 500) -> list[str]:
    """Coerce a value to a clean list of non-empty strings.

    Accepts a list (of strings or stringifiable items) or a single string with
    comma or newline separators. Items are trimmed, empties dropped, and the list
    is capped at ``limit`` entries and each entry at ``item_limit`` characters.
    """
    if isinstance(value, str):
        candidates: list[Any] = [part for chunk in value.split("\n") for part in chunk.split(",")]
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
    else:
        return []

    result: list[str] = []
    for candidate in candidates:
        if candidate is None:
            continue  # a JSON null in the list must drop out, not become "None"
        item = str(candidate).strip()
        if not item:
            continue
        result.append(item[:item_limit])
        if len(result) >= limit:
            break
    return result


def _clean_action_items(value: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    """Normalize action items into ``{owner, task, due}`` dicts.

    Tolerates the shapes an LLM realistically returns: a list of plain strings
    (each becomes a task), or a list of dicts using any of several common key
    spellings for owner / task / due. Items with no task text are dropped.
    """
    if not isinstance(value, (list, tuple)):
        return []

    owner_keys = ("owner", "assignee", "responsible", "who", "assigned_to")
    task_keys = ("task", "action", "item", "description", "what", "detail")
    due_keys = ("due", "due_date", "deadline", "by", "when", "date")

    result: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, str):
            task = raw.strip()
            owner = ""
            due: str | None = None
        elif isinstance(raw, dict):
            task = _first_key(raw, task_keys)
            owner = _first_key(raw, owner_keys)
            due_val = _first_key(raw, due_keys)
            due = due_val or None
        else:
            continue
        if not task:
            continue
        result.append({"owner": owner[:200], "task": task[:1000], "due": (due[:100] if due else None)})
        if len(result) >= limit:
            break
    return result


def _first_key(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first present, non-empty string value among ``keys`` in ``data``."""
    for key in keys:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _protocol_confidence(llm_result: dict[str, Any] | None, transcript: str) -> float | None:
    """Confidence (0-1) for the extracted protocol, or None when AI did not run.

    A model-reported ``confidence`` wins when present and in range; otherwise a
    small heuristic rewards a longer transcript and each protocol section that
    was actually populated, so a thin extraction reads as lower confidence. None
    is returned only when no extraction ran at all (``llm_result is None``).
    """
    if llm_result is None:
        return None
    raw = llm_result.get("confidence")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return round(max(0.0, min(1.0, float(raw))), 2)

    score = 0.5
    if _clean_str_list(llm_result.get("participants")):
        score += 0.15
    if _clean_str_list(llm_result.get("decisions")):
        score += 0.15
    if _clean_action_items(llm_result.get("action_items")):
        score += 0.1
    if len((transcript or "").split()) >= 40:
        score += 0.1
    return round(min(1.0, score), 2)


def build_protocol(
    *,
    llm_result: dict[str, Any] | None,
    normalized: NormalizedPhoneLog,
    transcript: str,
) -> dict[str, Any]:
    """Assemble the structured protocol stored under ``metadata_["protocol"]``.

    Pure and deterministic. When ``llm_result`` is a dict (the extraction pass
    ran) its fields are cleaned and used, falling back to the deterministic
    ``normalize`` outputs where the model gave nothing. When ``llm_result`` is
    None (no LLM provider, or the call failed) the protocol is built from the
    normalize outputs alone and ``ai_generated`` is False, so the UI can be
    honest that only the deterministic pass ran.
    """
    ai_generated = isinstance(llm_result, dict)
    src: dict[str, Any] = llm_result if isinstance(llm_result, dict) else {}

    participants = _clean_str_list(src.get("participants")) or list(normalized.parties)
    summary = _clean_text(src.get("summary")) or normalized.summary
    decisions = _clean_str_list(src.get("decisions"))
    action_items = _clean_action_items(src.get("action_items"))
    instructions = list(normalized.instructions)

    return {
        "participants": participants,
        "summary": summary,
        "decisions": decisions,
        "action_items": action_items,
        "instructions": instructions,
        "confidence": _protocol_confidence(llm_result, transcript),
        "ai_generated": ai_generated,
    }


def _build_extraction_prompt(transcript: str) -> str:
    """Build the user prompt for the structured-protocol extraction pass."""
    clipped = transcript.strip()
    if len(clipped) > _EXTRACTION_TRANSCRIPT_CHARS:
        clipped = clipped[:_EXTRACTION_TRANSCRIPT_CHARS] + "\n[transcript truncated]"
    return (
        "Read the transcript below and return a JSON object with exactly these keys:\n"
        '- "participants": array of the names or roles of people on the call. '
        "Empty array if none are named.\n"
        '- "summary": a short, neutral summary of the conversation, 2 to 4 sentences.\n'
        '- "decisions": array of clear decisions that were made. Empty array if none.\n'
        '- "action_items": array of objects, each '
        '{"owner": who is responsible (string, "" if unclear), '
        '"task": what must be done (string), '
        '"due": a date or timeframe only if explicitly stated, otherwise null}.\n'
        '- "confidence": a number between 0 and 1 for how well this protocol '
        "reflects the transcript.\n"
        "Use only information present in the transcript. Do not add anything that "
        "was not said.\n\n"
        'Transcript:\n"""\n'
        f"{clipped}\n"
        '"""'
    )


async def resolve_openai_key(session: Any, user_id: str | None) -> str | None:
    """Find an OpenAI key for transcription, or None when none is configured.

    Looks first at the requesting user's stored AI settings (encrypted key,
    decrypted here), then falls back to the app-level ``OPENAI_API_KEY`` env /
    config value. Returns None rather than raising when nothing is available, so
    the caller can degrade to the manual-transcript path.
    """
    from app.config import get_settings
    from app.core.crypto import decrypt_secret

    if session is not None and user_id:
        try:
            from app.modules.ai.repository import AISettingsRepository

            settings_row = await AISettingsRepository(session).get_by_user_id(uuid.UUID(str(user_id)))
        except Exception as exc:  # noqa: BLE001 - never let settings lookup break ingestion
            logger.debug("AI settings lookup failed: %s", exc)
            settings_row = None
        raw = getattr(settings_row, "openai_api_key", None) if settings_row else None
        if raw:
            decrypted = decrypt_secret(raw)
            if decrypted:
                return decrypted

    app_key = getattr(get_settings(), "openai_api_key", None)
    if app_key and app_key.strip():
        return app_key.strip()
    return None


async def transcribe_audio(
    content: bytes,
    filename: str,
    *,
    api_key: str,
    prompt: str | None = None,
    language: str | None = None,
    url: str | None = None,
    model: str | None = None,
) -> TranscriptionResult:
    """Transcribe recording bytes through the speech-to-text provider.

    ``prompt`` carries vocabulary hints (names, terms) and ``language`` an ISO
    639-1 code; ``url``/``model`` point at any endpoint speaking the same
    multipart protocol. Never raises: any transport, HTTP, or parsing failure is
    caught and returned as an unavailable :class:`TranscriptionResult` with a
    short reason, so the ingestion path can carry on and store the recording.
    """
    files = {"file": (filename or "recording", content, mime_for(filename))}
    data = {"model": model or TRANSCRIBE_MODEL, "response_format": "verbose_json"}
    if prompt and prompt.strip():
        data["prompt"] = prompt.strip()
    if language and language.strip():
        data["language"] = language.strip().lower().split("-")[0]
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url or _TRANSCRIBE_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=_TRANSCRIBE_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Transcription provider returned HTTP %s", exc.response.status_code)
        return TranscriptionResult(available=False, error=f"provider returned HTTP {exc.response.status_code}")
    except Exception as exc:  # noqa: BLE001 - transport/JSON failures must degrade, not crash
        logger.warning("Transcription failed: %s", type(exc).__name__)
        return TranscriptionResult(available=False, error=f"transcription failed ({type(exc).__name__})")

    text = str(payload.get("text") or "").strip()
    if not text:
        return TranscriptionResult(available=False, error="empty transcript")

    duration_raw = payload.get("duration")
    duration = int(round(duration_raw)) if isinstance(duration_raw, (int, float)) else None
    language = payload.get("language") if isinstance(payload.get("language"), str) else None
    return TranscriptionResult(
        text=text,
        language=language,
        duration_seconds=duration,
        available=True,
        segments=_clean_segments(payload.get("segments")),
    )


def _clean_segments(value: Any, *, limit: int = 5000) -> list[dict[str, Any]]:
    """Keep the timed segments a verbose transcription returns, dropping malformed ones."""
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in value[:limit]:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        start = raw.get("start")
        end = raw.get("end")
        result.append(
            {
                "start": float(start) if isinstance(start, (int, float)) and not isinstance(start, bool) else None,
                "end": float(end) if isinstance(end, (int, float)) and not isinstance(end, bool) else None,
                "text": text[:4000],
                "speaker": str(raw.get("speaker") or "").strip()[:100],
            }
        )
    return result


async def extract_protocol(transcript: str, session: Any, user_id: str | None) -> dict[str, Any] | None:
    """Run one LLM pass to extract a structured protocol from a transcript.

    Returns the parsed protocol dict, or None when no LLM provider is configured,
    the transcript is empty, or the call/parse fails. All of those degrade to a
    normalize-only protocol upstream - none of them raise.
    """
    if not transcript or not transcript.strip():
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
        except Exception as exc:  # noqa: BLE001
            logger.debug("AI settings lookup failed: %s", exc)

    try:
        provider, api_key, model_override = resolve_provider_key_model(settings_row)
    except ValueError:
        # No AI provider configured - the deterministic normalize pass still runs.
        return None

    try:
        raw_response, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=PROTOCOL_SYSTEM_PROMPT,
            prompt=_build_extraction_prompt(transcript),
            max_tokens=_EXTRACTION_MAX_TOKENS,
            model=model_override,
        )
    except Exception as exc:  # noqa: BLE001 - provider error must degrade, not crash
        logger.warning("Protocol extraction call failed: %s", type(exc).__name__)
        return None

    parsed = extract_json(raw_response)
    return parsed if isinstance(parsed, dict) else None
