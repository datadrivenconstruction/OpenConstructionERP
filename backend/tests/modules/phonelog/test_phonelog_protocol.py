# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-logic tests for the recording-to-protocol path (phonelog.transcription).

These cover the parts that must be right without a provider or a database:
upload format/size validation, structured-protocol assembly (both when the LLM
extraction ran and the degrade path when it did not), the action-item / list
cleaners, the confidence rule, and the transcription coroutine with the provider
mocked (success, empty result, transport failure). No network, no DB, no app
config is touched, so this runs on the local py3.11 interpreter too.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.modules.phonelog import transcription
from app.modules.phonelog.normalize import NormalizedPhoneLog


def _normalized(
    *,
    parties: tuple[str, ...] = (),
    direction: str = "unknown",
    channel: str = "voice_note",
    duration_seconds: int | None = None,
    summary: str = "",
    instructions: tuple[str, ...] = (),
    word_count: int = 0,
) -> NormalizedPhoneLog:
    return NormalizedPhoneLog(
        parties=parties,
        direction=direction,
        channel=channel,
        duration_seconds=duration_seconds,
        summary=summary,
        instructions=instructions,
        word_count=word_count,
    )


# --------------------------------------------------------------------------------------
# audio_extension / mime_for
# --------------------------------------------------------------------------------------


def test_audio_extension_basic():
    assert transcription.audio_extension("call.MP3") == "mp3"
    assert transcription.audio_extension("a/b/site talk.webm") == "webm"
    assert transcription.audio_extension("noext") == ""
    assert transcription.audio_extension("") == ""


def test_mime_for_known_and_unknown():
    assert transcription.mime_for("x.mp3") == "audio/mpeg"
    assert transcription.mime_for("x.m4a") == "audio/mp4"
    assert transcription.mime_for("x.mp4") == "video/mp4"
    assert transcription.mime_for("x.bin") == "application/octet-stream"


# --------------------------------------------------------------------------------------
# check_audio_upload (format + size validation)
# --------------------------------------------------------------------------------------


def test_check_audio_upload_accepts_supported_formats():
    for name in ("call.mp3", "vn.m4a", "rec.wav", "clip.webm", "meet.mp4", "x.mpeg", "y.mpga"):
        assert transcription.check_audio_upload(name, 1024) is None


def test_check_audio_upload_rejects_unsupported_format():
    problem = transcription.check_audio_upload("drawing.pdf", 1024)
    assert problem is not None
    status_code, message = problem
    assert status_code == 400
    assert "mp3" in message and "wav" in message  # lists the accepted formats


def test_check_audio_upload_rejects_missing_extension():
    problem = transcription.check_audio_upload("voicememo", 1024)
    assert problem is not None
    assert problem[0] == 400


def test_check_audio_upload_rejects_empty_file():
    problem = transcription.check_audio_upload("call.mp3", 0)
    assert problem is not None
    assert problem[0] == 400
    assert "empty" in problem[1].lower()


def test_check_audio_upload_rejects_oversized_file():
    problem = transcription.check_audio_upload("call.mp3", transcription.MAX_UPLOAD_BYTES + 1)
    assert problem is not None
    assert problem[0] == 413
    assert "too large" in problem[1].lower()


def test_check_audio_upload_allows_exactly_max_size():
    assert transcription.check_audio_upload("call.mp3", transcription.MAX_UPLOAD_BYTES) is None


# --------------------------------------------------------------------------------------
# _clean_str_list
# --------------------------------------------------------------------------------------


def test_clean_str_list_from_comma_and_newline_string():
    assert transcription._clean_str_list("Alice, Bob\nCarol") == ["Alice", "Bob", "Carol"]


def test_clean_str_list_from_list_drops_empties_and_stringifies():
    assert transcription._clean_str_list(["  A ", "", None, 3]) == ["A", "3"]


def test_clean_str_list_rejects_non_sequence():
    assert transcription._clean_str_list(42) == []
    assert transcription._clean_str_list(None) == []


def test_clean_str_list_caps_length():
    assert len(transcription._clean_str_list([f"p{i}" for i in range(200)])) == 50


# --------------------------------------------------------------------------------------
# _clean_action_items
# --------------------------------------------------------------------------------------


def test_clean_action_items_from_strings():
    assert transcription._clean_action_items(["Send the RFI", "Order rebar"]) == [
        {"owner": "", "task": "Send the RFI", "due": None},
        {"owner": "", "task": "Order rebar", "due": None},
    ]


def test_clean_action_items_from_dicts_with_alt_keys():
    raw = [
        {"assignee": "Site engineer", "action": "Revise the slab detail", "deadline": "Friday"},
        {"owner": "Acme", "task": "Confirm the pour date", "due": None},
    ]
    assert transcription._clean_action_items(raw) == [
        {"owner": "Site engineer", "task": "Revise the slab detail", "due": "Friday"},
        {"owner": "Acme", "task": "Confirm the pour date", "due": None},
    ]


def test_clean_action_items_drops_items_without_a_task():
    raw = [{"owner": "Bob"}, {"task": ""}, "  ", {"task": "Keep this"}]
    assert transcription._clean_action_items(raw) == [{"owner": "", "task": "Keep this", "due": None}]


def test_clean_action_items_rejects_non_list():
    assert transcription._clean_action_items({"task": "x"}) == []
    assert transcription._clean_action_items(None) == []


# --------------------------------------------------------------------------------------
# _protocol_confidence
# --------------------------------------------------------------------------------------


def test_confidence_is_none_without_llm():
    assert transcription._protocol_confidence(None, "anything") is None


def test_confidence_uses_model_value_clamped():
    assert transcription._protocol_confidence({"confidence": 0.83}, "t") == 0.83
    assert transcription._protocol_confidence({"confidence": 5}, "t") == 1.0
    assert transcription._protocol_confidence({"confidence": -2}, "t") == 0.0


def test_confidence_ignores_bool_and_falls_back_to_heuristic():
    # A bare {} extraction with a short transcript is low-ish (base 0.5).
    assert transcription._protocol_confidence({}, "few words") == 0.5


def test_confidence_heuristic_rewards_populated_sections():
    rich = {
        "participants": ["A", "B"],
        "decisions": ["Do X"],
        "action_items": [{"task": "Do Y"}],
    }
    long_transcript = " ".join(["word"] * 60)
    assert transcription._protocol_confidence(rich, long_transcript) == 1.0


# --------------------------------------------------------------------------------------
# build_protocol (assembly + degrade)
# --------------------------------------------------------------------------------------


def test_build_protocol_with_llm_result():
    normalized = _normalized(parties=("Fallback",), summary="Fallback summary", instructions=("Please do X",))
    llm = {
        "participants": ["Site engineer", "Acme site office"],
        "summary": "Discussed the slab pour and agreed a new date.",
        "decisions": ["Pour date moved to Monday"],
        "action_items": [{"owner": "Acme", "task": "Send revised drawing", "due": "tomorrow"}],
        "confidence": 0.9,
    }
    protocol = transcription.build_protocol(llm_result=llm, normalized=normalized, transcript="a real transcript")

    assert protocol["ai_generated"] is True
    assert protocol["participants"] == ["Site engineer", "Acme site office"]
    assert protocol["summary"] == "Discussed the slab pour and agreed a new date."
    assert protocol["decisions"] == ["Pour date moved to Monday"]
    assert protocol["action_items"] == [{"owner": "Acme", "task": "Send revised drawing", "due": "tomorrow"}]
    # instructions always come from the deterministic normalize pass.
    assert protocol["instructions"] == ["Please do X"]
    assert protocol["confidence"] == 0.9


def test_build_protocol_degrades_without_llm():
    """The degrade path: no LLM result -> protocol built from normalize alone."""
    normalized = _normalized(
        parties=("Site engineer", "Acme"),
        summary="Agreed to hold the pour.",
        instructions=("Please hold the pour",),
    )
    protocol = transcription.build_protocol(llm_result=None, normalized=normalized, transcript="Please hold the pour.")

    assert protocol["ai_generated"] is False
    assert protocol["confidence"] is None
    assert protocol["participants"] == ["Site engineer", "Acme"]
    assert protocol["summary"] == "Agreed to hold the pour."
    assert protocol["decisions"] == []
    assert protocol["action_items"] == []
    assert protocol["instructions"] == ["Please hold the pour"]


def test_build_protocol_falls_back_to_normalize_for_missing_llm_fields():
    normalized = _normalized(parties=("Normalized party",), summary="Normalized summary")
    # LLM ran but returned nothing usable for participants/summary.
    protocol = transcription.build_protocol(
        llm_result={"participants": [], "summary": "   "},
        normalized=normalized,
        transcript="t",
    )
    assert protocol["ai_generated"] is True
    assert protocol["participants"] == ["Normalized party"]
    assert protocol["summary"] == "Normalized summary"


# --------------------------------------------------------------------------------------
# _build_extraction_prompt
# --------------------------------------------------------------------------------------


def test_extraction_prompt_contains_schema_and_transcript():
    prompt = transcription._build_extraction_prompt("Please confirm the rebar spacing.")
    assert "participants" in prompt
    assert "action_items" in prompt
    assert "Please confirm the rebar spacing." in prompt


def test_extraction_prompt_truncates_long_transcript():
    long_text = "x" * (transcription._EXTRACTION_TRANSCRIPT_CHARS + 5000)
    prompt = transcription._build_extraction_prompt(long_text)
    assert "[transcript truncated]" in prompt
    assert len(prompt) < len(long_text) + 2000


# --------------------------------------------------------------------------------------
# transcribe_audio (provider mocked) + extract_protocol degrade
# --------------------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Stand-in for httpx.AsyncClient that returns a canned response or raises."""

    def __init__(self, *, payload: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self._payload = payload or {}
        self._exc = exc

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    async def post(self, *_args: object, **_kwargs: object) -> _FakeResponse:
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload)


@pytest.mark.asyncio
async def test_transcribe_audio_success(monkeypatch: pytest.MonkeyPatch):
    payload = {"text": "  Please change the door schedule.  ", "duration": 65.4, "language": "en"}
    monkeypatch.setattr(transcription.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload=payload))

    result = await transcription.transcribe_audio(b"bytes", "call.mp3", api_key="sk-test")

    assert result.available is True
    assert result.text == "Please change the door schedule."
    assert result.duration_seconds == 65
    assert result.language == "en"
    assert result.error is None


@pytest.mark.asyncio
async def test_transcribe_audio_empty_text_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(transcription.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload={"text": "   "}))

    result = await transcription.transcribe_audio(b"bytes", "call.mp3", api_key="sk-test")

    assert result.available is False
    assert result.text == ""
    assert result.error == "empty transcript"


@pytest.mark.asyncio
async def test_transcribe_audio_transport_failure_degrades(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        transcription.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeClient(exc=RuntimeError("boom")),
    )

    result = await transcription.transcribe_audio(b"bytes", "call.mp3", api_key="sk-test")

    assert result.available is False
    assert result.text == ""
    assert "RuntimeError" in (result.error or "")


@pytest.mark.asyncio
async def test_transcribe_audio_http_error_degrades(monkeypatch: pytest.MonkeyPatch):
    request = httpx.Request("POST", transcription._TRANSCRIBE_URL)
    response = httpx.Response(401, request=request)
    err = httpx.HTTPStatusError("unauthorized", request=request, response=response)
    monkeypatch.setattr(transcription.httpx, "AsyncClient", lambda *a, **k: _FakeClient(exc=err))

    result = await transcription.transcribe_audio(b"bytes", "call.mp3", api_key="sk-bad")

    assert result.available is False
    assert "401" in (result.error or "")


@pytest.mark.asyncio
async def test_extract_protocol_empty_transcript_returns_none():
    """Degrade path: nothing to extract from an empty transcript, no provider call."""
    assert await transcription.extract_protocol("", None, None) is None
    assert await transcription.extract_protocol("   ", None, None) is None
