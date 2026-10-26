# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Speech provider selection, minutes validation rules and the localized minutes PDF."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.meetings import validators
from app.modules.voice import speech

# ── Speech providers ─────────────────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (speech.PROVIDER_ENV, speech.BASE_URL_ENV, speech.API_KEY_ENV, speech.MODEL_ENV):
        monkeypatch.delenv(name, raising=False)

    async def no_key(_session: Any, _user: Any) -> None:
        return None

    monkeypatch.setattr(speech.phonelog_transcription, "resolve_openai_key", no_key)
    return monkeypatch


@pytest.mark.asyncio
async def test_no_provider_configured_degrades_to_none(clean_env: pytest.MonkeyPatch) -> None:
    assert await speech.resolve_speech_provider(None, None) is None


@pytest.mark.asyncio
async def test_self_hosted_endpoint_wins_in_auto(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv(speech.BASE_URL_ENV, "http://speech.internal:9000/v1/")
    clean_env.setenv(speech.MODEL_ENV, "large-v3")
    provider = await speech.resolve_speech_provider(None, None)
    assert provider is not None and provider.name == "self_hosted"
    assert provider.url == "http://speech.internal:9000/v1/audio/transcriptions"  # type: ignore[attr-defined]
    assert provider.model == "large-v3"


@pytest.mark.asyncio
async def test_hosted_needs_a_key_and_none_switches_everything_off(clean_env: pytest.MonkeyPatch) -> None:
    async def key(_session: Any, _user: Any) -> str:
        return "sk-test"

    clean_env.setattr(speech.phonelog_transcription, "resolve_openai_key", key)
    provider = await speech.resolve_speech_provider(None, "u")
    assert provider is not None and provider.name == "hosted"
    clean_env.setenv(speech.PROVIDER_ENV, "none")
    assert await speech.resolve_speech_provider(None, "u") is None


@pytest.mark.asyncio
async def test_registered_provider_is_pluggable_and_a_broken_one_degrades(clean_env: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class Fake:
        name = "fake"
        model = "m"

        async def transcribe(self, content: bytes, filename: str, *, language=None, prompt=None):  # noqa: ANN001
            calls.append({"language": language, "prompt": prompt})
            return speech.TranscriptionResult(text="hello", available=True)

    async def fake(_s: Any, _u: Any) -> Fake:
        return Fake()

    async def broken(_s: Any, _u: Any) -> None:
        raise RuntimeError("boom")

    speech.register_speech_provider("fake", fake)
    speech.register_speech_provider("broken", broken)
    try:
        clean_env.setenv(speech.PROVIDER_ENV, "fake")
        provider = await speech.resolve_speech_provider(None, None)
        assert provider is not None
        result = await provider.transcribe(b"x", "a.webm", language="de", prompt="Anna Berg")
        assert result.text == "hello" and calls == [{"language": "de", "prompt": "Anna Berg"}]
        clean_env.setenv(speech.PROVIDER_ENV, "broken")
        assert await speech.resolve_speech_provider(None, None) is None
    finally:
        speech._REGISTRY.pop("fake", None)
        speech._REGISTRY.pop("broken", None)


@pytest.mark.asyncio
async def test_transcribe_audio_sends_hints_language_and_keeps_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.phonelog import transcription

    sent: dict[str, Any] = {}

    class Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "text": "Pour on Friday.",
                "language": "german",
                "duration": 12.4,
                "segments": [{"start": 0, "end": 2.5, "text": " Pour on Friday. ", "speaker": "S1"}, {"text": ""}, 5],
            }

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_a: object) -> bool:
            return False

        async def post(self, url: str, **kwargs: Any) -> Resp:
            sent["url"] = url
            sent.update(kwargs)
            return Resp()

    monkeypatch.setattr(transcription.httpx, "AsyncClient", Client)
    result = await transcription.transcribe_audio(
        b"x", "m.webm", api_key="", prompt="Anna Berg, WU", language="de-DE", url="http://h/x", model="small"
    )
    assert sent["url"] == "http://h/x"
    assert sent["data"] == {
        "model": "small",
        "response_format": "verbose_json",
        "prompt": "Anna Berg, WU",
        "language": "de",
    }
    assert sent["headers"] == {}
    assert result.segments == [{"start": 0.0, "end": 2.5, "text": "Pour on Friday.", "speaker": "S1"}]


# ── Validation rules ─────────────────────────────────────────────────────────


def _ctx(recordings: list[dict[str, Any]]) -> ValidationContext:
    return ValidationContext(data={"recordings": recordings})


@pytest.mark.asyncio
async def test_consent_rule_flags_audio_without_consent() -> None:
    rule = validators.MeetingRecordingConsentRule()
    results = await rule.validate(
        _ctx(
            [
                {"id": "a", "source": "upload", "audio_storage_key": "k", "consent_confirmed_at": None},
                {"id": "b", "source": "manual", "audio_storage_key": ""},
                {"id": "c", "source": "browser_speech", "consent_confirmed_at": "2026-10-25T10:00:00Z"},
            ]
        )
    )
    assert [r.passed for r in results] == [False, True, True]
    assert results[0].element_ref == "a"


@pytest.mark.asyncio
async def test_retention_rule_flags_overdue_audio() -> None:
    rule = validators.MeetingAudioRetentionRule()
    past = datetime.now(UTC) - timedelta(days=1)
    results = await rule.validate(
        _ctx([{"id": "a", "audio_storage_key": "k", "audio_expires_at": past}, {"id": "b", "audio_storage_key": ""}])
    )
    assert [r.passed for r in results] == [False, True]


@pytest.mark.asyncio
async def test_proposals_rule_flags_unreviewed_items() -> None:
    rule = validators.MeetingProposalsReviewedRule()
    results = await rule.validate(
        _ctx(
            [
                {"id": "a", "proposals": {"items": [{"status": "pending"}, {"status": "confirmed"}]}},
                {"id": "b", "proposals": {"items": [{"status": "rejected"}]}},
            ]
        )
    )
    assert [r.passed for r in results] == [False, True]
    assert "1 proposal" in results[0].message


def test_all_meeting_rules_register() -> None:
    from app.core.validation.engine import rule_registry

    validators.register_meetings_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets(["meetings"])}
    assert {"meetings.recording_consent", "meetings.audio_retention", "meetings.proposals_reviewed"} <= ids


# ── Minutes PDF language ─────────────────────────────────────────────────────


@pytest.fixture
def translations() -> None:
    from app.core.i18n import load_translations

    load_translations()


def test_minutes_locale_prefers_request_then_meeting_language(translations: None) -> None:
    from app.modules.meetings.pdf import minutes_pdf_languages, resolve_minutes_locale

    langs = minutes_pdf_languages()
    assert "de" in langs and "en" in langs
    assert "ar" not in langs and "bn" not in langs
    assert resolve_minutes_locale("fr-CA", {"language": "de"}) == "fr"
    assert resolve_minutes_locale(None, {"language": "de"}) == "de"
    assert resolve_minutes_locale(None, {"language": "ar"}) == "en"
    assert resolve_minutes_locale("xx", {}) == "en"


def test_minutes_pdf_prints_labels_in_the_meeting_language(translations: None) -> None:
    from app.modules.meetings.pdf import build_minutes_pdf, minutes_label

    assert minutes_label("de", "title") != minutes_label("en", "title")
    content = {
        "title": "Baubesprechung 7",
        "meeting_number": "7",
        "meeting_type": "progress",
        "meeting_date": "2026-10-21",
        "attendees_present": [{"name": "Anna Berg"}],
        "attendees_absent": [],
        "agenda": [],
        "action_items": [{"description": "Bewehrungsplan senden", "owner": "Anna Berg", "status": "open"}],
        "decisions": ["Betonage am Freitag"],
        "open_questions": ["Wer zahlt den Kran?"],
        "summary": "Kurz.",
        "language": "de",
    }
    meeting = SimpleNamespace(title="Baubesprechung 7", meeting_date="2026-10-21", meeting_number="7")
    minutes = SimpleNamespace(content=content, status="draft", issued_at=None)
    pdf = build_minutes_pdf(meeting, minutes, "Wohnpark Nord")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
