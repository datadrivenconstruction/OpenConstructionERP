# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Minutes from audio, end to end over HTTP with the speech service and the AI mocked.

Covers the order a meeting secretary goes through and the guards on each step:
consent before audio, transcription with glossary hints and alias correction,
graceful degrade with no provider, proposals reviewed one by one, confirmed
actions landing in the action register and the task list, audio deletion and
retention, the localized minutes PDF, and tenant isolation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.modules.phonelog.transcription import TranscriptionResult


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.meetings import models as _meetings_models  # noqa: F401
        from app.modules.tasks import models as _tasks_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


async def _user(client: AsyncClient, role: str) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"mtg-audio-{uuid.uuid4().hex[:8]}@example.io"
    password = f"MeetAudio{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Minutes Writer"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email).values(is_active=True, role=role))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}", "user_id": reg.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def ctx(client: AsyncClient) -> dict[str, Any]:
    owner = await _user(client, "admin")
    other = await _user(client, "editor")
    h = {"Authorization": owner["Authorization"]}
    proj = await client.post(
        "/api/v1/projects/", json={"name": f"Audio {uuid.uuid4().hex[:6]}", "currency": "EUR"}, headers=h
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]
    mtg = await client.post(
        "/api/v1/meetings/",
        json={
            "project_id": project_id,
            "meeting_type": "progress",
            "title": "Site progress 7",
            "meeting_date": "2026-10-21",
            "status": "scheduled",
            "attendees": [
                {"name": "Anna Berg", "company": "Mueller Bau GmbH", "status": "present"},
                {"name": "Tomasz Nowak", "company": "", "status": "present"},
            ],
        },
        headers=h,
    )
    assert mtg.status_code == 201, mtg.text
    return {
        "h": h,
        "other": {"Authorization": other["Authorization"]},
        "project_id": project_id,
        "meeting_id": mtg.json()["id"],
    }


class _FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, result: TranscriptionResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def transcribe(self, content: bytes, filename: str, *, language=None, prompt=None):  # noqa: ANN001
        self.calls.append({"filename": filename, "language": language, "prompt": prompt, "size": len(content)})
        return self.result


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider | None) -> None:
    from app.modules.voice import speech

    async def resolve(_session: Any, _user: Any) -> _FakeProvider | None:
        return provider

    monkeypatch.setattr(speech, "resolve_speech_provider", resolve)


def _use_llm(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any] | None) -> list[str]:
    from app.modules.meetings import audio_service

    prompts: list[str] = []

    async def fake(_session: Any, _user: Any, prompt: str) -> dict[str, Any] | None:
        prompts.append(prompt)
        return result

    monkeypatch.setattr(audio_service, "run_proposal_llm", fake)
    return prompts


@pytest.mark.asyncio
async def test_capabilities_report_no_provider(client, ctx, monkeypatch) -> None:
    _use_provider(monkeypatch, None)
    resp = await client.get("/api/v1/meetings/speech/capabilities/", headers=ctx["h"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["server_transcription"] is False and body["provider"] is None
    assert body["max_upload_mb"] == 25 and "webm" in body["accepted_formats"]


@pytest.mark.asyncio
async def test_glossary_seed_and_crud(client, ctx) -> None:
    pid = ctx["project_id"]
    seed = await client.post(f"/api/v1/meetings/glossary/seed/?project_id={pid}", headers=ctx["h"])
    assert seed.status_code == 200, seed.text
    terms = {t["term"]: t for t in seed.json()["terms"]}
    assert {"Anna Berg", "Tomasz Nowak", "Mueller Bau GmbH"} <= set(terms)
    assert terms["Anna Berg"]["source"] == "attendees"
    again = await client.post(f"/api/v1/meetings/glossary/seed/?project_id={pid}", headers=ctx["h"])
    assert again.json()["added"] == 0

    add = await client.post(
        f"/api/v1/meetings/glossary/?project_id={pid}",
        json={"term": "WU-Beton", "kind": "term", "expansion": "watertight concrete", "aliases": ["view beton"]},
        headers=ctx["h"],
    )
    assert add.status_code == 201, add.text
    dup = await client.post(f"/api/v1/meetings/glossary/?project_id={pid}", json={"term": "wu-beton"}, headers=ctx["h"])
    assert dup.status_code == 409
    patched = await client.patch(
        f"/api/v1/meetings/glossary/{terms['Tomasz Nowak']['id']}",
        json={"aliases": ["Tomas Novak", "Tomasz Nowak"]},
        headers=ctx["h"],
    )
    assert patched.status_code == 200 and patched.json()["aliases"] == ["Tomas Novak"]


@pytest.mark.asyncio
async def test_audio_without_consent_is_refused(client, ctx, monkeypatch) -> None:
    _use_provider(monkeypatch, _FakeProvider(TranscriptionResult(text="x", available=True)))
    resp = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
        data={"source": "upload"},
        files={"file": ("m.webm", b"audio-bytes", "audio/webm")},
        headers=ctx["h"],
    )
    assert resp.status_code == 422
    assert "agreed" in resp.text


@pytest.mark.asyncio
async def test_upload_transcribes_with_hints_corrects_aliases_and_deletes_audio(client, ctx, monkeypatch) -> None:
    provider = _FakeProvider(
        TranscriptionResult(
            text="Tomas Novak: we pour the view beton slab on Friday.",
            language="german",
            duration_seconds=42,
            available=True,
            segments=[{"start": 0.0, "end": 4.0, "text": "we pour the view beton slab on Friday.", "speaker": "S1"}],
        )
    )
    _use_provider(monkeypatch, provider)
    resp = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
        data={"source": "browser_record", "consent_confirmed": "true", "delete_audio_after_transcription": "true"},
        files={"file": ("meeting.webm", b"audio-bytes", "audio/webm")},
        headers=ctx["h"],
    )
    assert resp.status_code == 201, resp.text
    rec = resp.json()
    assert rec["status"] == "transcribed" and rec["provider"] == "fake"
    assert rec["language"] == "de" and rec["duration_seconds"] == 42
    assert "Tomasz Nowak" in rec["transcript"] and "WU-Beton" in rec["transcript"]
    assert rec["segments"][0]["text"] == "we pour the WU-Beton slab on Friday."
    assert rec["glossary_replacements"] >= 2
    assert rec["has_audio"] is False and rec["audio_deleted_at"] is not None
    assert rec["consent_confirmed_at"] is not None
    assert "Anna Berg" in provider.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_no_provider_keeps_audio_waiting_for_a_transcript(client, ctx, monkeypatch) -> None:
    _use_provider(monkeypatch, None)
    resp = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
        data={"source": "upload", "consent_confirmed": "true", "retention_days": "7"},
        files={"file": ("m.m4a", b"audio-bytes", "audio/mp4")},
        headers=ctx["h"],
    )
    assert resp.status_code == 201, resp.text
    rec = resp.json()
    assert rec["status"] == "awaiting_transcript" and rec["has_audio"] is True
    expires = datetime.fromisoformat(rec["audio_expires_at"])
    assert timedelta(days=6) < expires - datetime.now(UTC) <= timedelta(days=7)

    edited = await client.patch(
        f"/api/v1/meetings/recordings/{rec['id']}",
        json={"transcript": "S1: hello\nS2: answer RFI 3"},
        headers=ctx["h"],
    )
    assert edited.status_code == 200 and edited.json()["status"] == "transcribed"
    named = await client.patch(
        f"/api/v1/meetings/recordings/{rec['id']}",
        json={"speakers": {"S1": {"name": "Anna Berg"}, "S9": {"name": "nobody"}}},
        headers=ctx["h"],
    )
    assert named.json()["speakers"] == {"S1": {"name": "Anna Berg", "contact_id": None}}

    audio = await client.get(f"/api/v1/meetings/recordings/{rec['id']}/audio", headers=ctx["h"])
    assert audio.status_code in (200, 307)
    gone = await client.delete(f"/api/v1/meetings/recordings/{rec['id']}/audio", headers=ctx["h"])
    assert gone.status_code == 200 and gone.json()["has_audio"] is False
    again = await client.get(f"/api/v1/meetings/recordings/{rec['id']}/audio", headers=ctx["h"])
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_audio_format_is_refused(client, ctx, monkeypatch) -> None:
    _use_provider(monkeypatch, None)
    resp = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
        data={"source": "upload", "consent_confirmed": "true"},
        files={"file": ("m.ogg", b"audio", "audio/ogg")},
        headers=ctx["h"],
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_propose_review_lands_in_register_tasks_and_minutes(client, ctx, monkeypatch) -> None:
    _use_llm(
        monkeypatch,
        {
            "summary": "Slab pour confirmed for Friday.",
            "decisions": [{"text": "Pour the slab on Friday", "confidence": 0.9}],
            "action_items": [
                {"task": "Send revised rebar drawings", "owner": "Anna", "due": "next week", "confidence": 0.8},
                {"task": "Book the crane", "owner": "", "due": None, "confidence": 0.6},
            ],
            "open_questions": [{"text": "Who pays the extra crane day?", "confidence": 0.7}],
            "confidence": 0.8,
        },
    )
    rec = (
        await client.post(
            f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
            data={"source": "manual", "transcript": "Anna: I send the rebar drawings next week.\nTomasz: crane?"},
            headers=ctx["h"],
        )
    ).json()
    assert rec["consent_confirmed_at"] is None

    proposed = await client.post(f"/api/v1/meetings/recordings/{rec['id']}/propose/", headers=ctx["h"])
    assert proposed.status_code == 200, proposed.text
    items = {i["kind"] + ":" + i["text"][:10]: i for i in proposed.json()["proposals"]["items"]}
    assert proposed.json()["proposals"]["ai_generated"] is True
    send = items["action:Send revis"]
    crane = items["action:Book the c"]
    assert send["due_date"] == "2026-10-28" and send["owner_name"] == "Anna Berg"

    blocked = await client.post(
        f"/api/v1/meetings/recordings/{rec['id']}/review/",
        json={"items": [{"id": crane["id"], "decision": "confirm"}]},
        headers=ctx["h"],
    )
    assert blocked.status_code == 200
    assert blocked.json()["confirmed"] == 0 and "owner" in blocked.json()["errors"][0]["error"]

    review = await client.post(
        f"/api/v1/meetings/recordings/{rec['id']}/review/",
        json={
            "items": [
                {"id": send["id"], "decision": "confirm"},
                {"id": crane["id"], "decision": "confirm", "owner_name": "Tomasz Nowak", "due_date": "2026-10-23"},
                {"id": items["summary:Slab pour "]["id"], "decision": "confirm"},
                {
                    "id": items["decision:Pour the s"]["id"],
                    "decision": "confirm",
                    "text": "Pour the slab on Friday 7am",
                },
                {"id": items["question:Who pays t"]["id"], "decision": "reject"},
            ],
            "create_tasks": True,
        },
        headers=ctx["h"],
    )
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["confirmed"] == 4 and body["rejected"] == 1 and body["errors"] == []
    assert len(body["actions_created"]) == 2 and len(body["tasks_created"]) == 2
    statuses = {i["id"]: i["status"] for i in body["recording"]["proposals"]["items"]}
    assert statuses[send["id"]] == "confirmed" and statuses[items["question:Who pays t"]["id"]] == "rejected"

    actions = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/actions/", headers=ctx["h"])
    assert actions.status_code == 200, actions.text
    assert {"Send revised rebar drawings", "Book the crane"} <= {a["description"] for a in actions.json()["own"]}

    tasks = await client.get(f"/api/v1/tasks/?project_id={ctx['project_id']}", headers=ctx["h"])
    assert tasks.status_code == 200, tasks.text
    rows = tasks.json() if isinstance(tasks.json(), list) else tasks.json().get("items", [])
    assert any(t["title"] == "Book the crane" and t["meeting_id"] == ctx["meeting_id"] for t in rows)

    again = await client.post(
        f"/api/v1/meetings/recordings/{rec['id']}/review/",
        json={"items": [{"id": send["id"], "decision": "confirm"}]},
        headers=ctx["h"],
    )
    assert again.json()["confirmed"] == 0

    minutes = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/generate/", json={"regenerate": True}, headers=ctx["h"]
    )
    assert minutes.status_code == 200, minutes.text
    content = minutes.json()["content"]
    assert "Pour the slab on Friday 7am" in content["decisions"]
    assert "Slab pour confirmed for Friday." in content["summary"]
    assert content["language"] == "de"

    pdf = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/minutes/export/pdf/", headers=ctx["h"])
    assert pdf.status_code == 200 and pdf.headers["content-language"] == "de"
    pdf_en = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/minutes/export/pdf/?locale=en", headers=ctx["h"])
    assert pdf_en.headers["content-language"] == "en"


@pytest.mark.asyncio
async def test_without_ai_the_heuristic_proposes_at_low_confidence(client, ctx, monkeypatch) -> None:
    _use_llm(monkeypatch, None)
    rec = (
        await client.post(
            f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
            data={
                "source": "manual",
                "transcript": "Anna: We agreed to pour on Friday.\nTomasz: I will check the formwork.",
            },
            headers=ctx["h"],
        )
    ).json()
    proposed = (await client.post(f"/api/v1/meetings/recordings/{rec['id']}/propose/", headers=ctx["h"])).json()
    items = proposed["proposals"]["items"]
    assert proposed["proposals"]["ai_generated"] is False
    assert any(i["kind"] in ("decision", "action") for i in items)
    assert all(i["confidence"] <= 0.35 for i in items if i["kind"] != "correction")


@pytest.mark.asyncio
async def test_other_tenant_sees_nothing(client, ctx) -> None:
    other = ctx["other"]
    assert (await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/recordings/", headers=other)).status_code == 404
    assert (
        await client.get(f"/api/v1/meetings/glossary/?project_id={ctx['project_id']}", headers=other)
    ).status_code == 404
    resp = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
        data={"source": "manual", "transcript": "inject"},
        headers=other,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_retention_sweep_deletes_expired_audio_only(client, ctx, monkeypatch) -> None:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.meetings.audio_service import prune_expired_meeting_audio
    from app.modules.meetings.models import MeetingRecording

    _use_provider(monkeypatch, None)
    rec = (
        await client.post(
            f"/api/v1/meetings/{ctx['meeting_id']}/recordings/",
            data={"source": "upload", "consent_confirmed": "true", "transcript": "kept text"},
            files={"file": ("m.mp3", b"audio-bytes", "audio/mpeg")},
            headers=ctx["h"],
        )
    ).json()
    async with async_session_factory() as s:
        row = (
            await s.execute(select(MeetingRecording).where(MeetingRecording.id == uuid.UUID(rec["id"])))
        ).scalar_one()
        row.audio_expires_at = datetime.now(UTC) - timedelta(hours=1)
        await s.commit()
    async with async_session_factory() as s:
        removed = await prune_expired_meeting_audio(s)
        await s.commit()
    assert removed >= 1
    rows = (await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/recordings/", headers=ctx["h"])).json()
    swept = next(r for r in rows if r["id"] == rec["id"])
    assert swept["has_audio"] is False and swept["transcript"] == "kept text"


@pytest.mark.asyncio
async def test_meeting_validation_flags_unreviewed_proposals(client, ctx) -> None:
    resp = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/validation/", headers=ctx["h"])
    assert resp.status_code == 200, resp.text
    by_rule: dict[str, list[bool]] = {}
    for result in resp.json()["results"]:
        by_rule.setdefault(result["rule_id"], []).append(result["passed"])
    assert False in by_rule["meetings.proposals_reviewed"]
    assert all(by_rule["meetings.recording_consent"])
    assert all(by_rule["meetings.audio_retention"])
    other = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/validation/", headers=ctx["other"])
    assert other.status_code == 404
