# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dictation for the assistant composer: one short recording in, its text out, nothing kept.

The routes are mounted on a bare app with the user and the session overridden,
and the speech provider replaced, so no network and no database is touched.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user_id, get_session
from app.modules.phonelog.transcription import TranscriptionResult
from app.modules.voice import router as voice_router
from app.modules.voice import service as voice_service
from app.modules.voice import speech


class _Provider:
    name = "hosted"
    model = "whisper-1"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def transcribe(self, content: bytes, filename: str, *, language=None, prompt=None) -> TranscriptionResult:
        self.calls.append({"size": len(content), "filename": filename, "language": language})
        return TranscriptionResult(text="  set the unit rate of position 01.10 to 200  ", language="en", available=True)


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(voice_router.router, prefix="/api/v1/voice")
    app.dependency_overrides[get_current_user_id] = lambda: "00000000-0000-0000-0000-0000000000a1"

    async def _session():
        yield None

    app.dependency_overrides[get_session] = _session
    return app


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voice_router.upload_limiter, "is_allowed", lambda key, max_requests=None: (True, 0))


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> _Provider:
    instance = _Provider()

    async def _resolve(session: Any, user_id: str | None) -> _Provider:
        return instance

    monkeypatch.setattr(speech, "resolve_speech_provider", _resolve)
    return instance


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _resolve(session: Any, user_id: str | None) -> None:
        return None

    monkeypatch.setattr(speech, "resolve_speech_provider", _resolve)


async def _post(app: FastAPI, path: str, **kwargs: Any):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, **kwargs)


async def _get(app: FastAPI, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.parametrize(
    ("locale", "expected"),
    [("de", "de"), ("pt-BR", "pt"), ("zh_CN", "zh"), ("fil", "fil"), ("", None), ("x1", None), (None, None)],
)
def test_the_ui_locale_becomes_the_language_the_speech_provider_takes(locale: str | None, expected: str | None):
    assert voice_router.dictation_language(locale) == expected


@pytest.mark.asyncio
async def test_a_dictated_message_comes_back_as_trimmed_text_in_the_users_language(app, provider) -> None:
    response = await _post(
        app,
        "/api/v1/voice/transcribe?language=de-DE",
        files={"file": ("dictation.webm", b"\x1a\x45\xdf\xa3" + b"0" * 2048, "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "text": "set the unit rate of position 01.10 to 200",
        "language": "en",
        "available": True,
        "error": None,
    }
    assert provider.calls == [{"size": 2052, "filename": "dictation.webm", "language": "de"}]


@pytest.mark.asyncio
async def test_without_a_speech_provider_dictation_says_so_and_capabilities_say_browser_only(app, no_provider) -> None:
    response = await _post(app, "/api/v1/voice/transcribe", files={"file": ("dictation.webm", b"0" * 64, "audio/webm")})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]

    caps = await _get(app, "/api/v1/voice/capabilities")
    assert caps.status_code == 200
    assert caps.json() == {"server_transcription": False, "provider": None, "max_upload_bytes": 0, "max_seconds": 0}


@pytest.mark.asyncio
async def test_capabilities_name_the_provider_and_the_dictation_limits(app, provider) -> None:
    caps = (await _get(app, "/api/v1/voice/capabilities")).json()
    assert caps["server_transcription"] is True and caps["provider"] == "hosted"
    assert caps["max_seconds"] == voice_router.DICTATION_MAX_SECONDS
    assert caps["max_upload_bytes"] == voice_router.DICTATION_MAX_BYTES


@pytest.mark.asyncio
async def test_a_recording_that_is_not_audio_or_too_long_is_refused_before_the_provider(
    app, provider, monkeypatch
) -> None:
    wrong = await _post(app, "/api/v1/voice/transcribe", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert wrong.status_code == 400

    monkeypatch.setattr(voice_router, "DICTATION_MAX_BYTES", 1024)
    long = await _post(app, "/api/v1/voice/transcribe", files={"file": ("d.webm", b"0" * 2048, "audio/webm")})
    assert long.status_code == 413
    assert provider.calls == []


@pytest.mark.asyncio
async def test_the_recording_is_never_stored(app, provider, monkeypatch) -> None:
    import builtins

    opened: list[str] = []
    real_open = builtins.open

    def _spy_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x")):
            opened.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _spy_open)
    stored: list[Any] = []

    async def _no_storage(*args: Any, **kwargs: Any) -> None:
        stored.append(args)

    monkeypatch.setattr(voice_service, "build_draft", _no_storage)
    response = await _post(app, "/api/v1/voice/transcribe", files={"file": ("d.webm", b"0" * 256, "audio/webm")})
    assert response.status_code == 200
    assert opened == [] and stored == []
