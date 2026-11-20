"""R14: the ai block of the project context comes from the caller's own ERP settings and goes nowhere else."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import make_project, make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, _linked_project, _upload

pytestmark = pytest.mark.asyncio

SECRET = "sk-test-0123456789abcdefSECRETKEY"


def _provider() -> str:
    """A provider the ERP itself names an endpoint for and picks by its own model keyword."""
    from app.modules.ai import ai_client

    for name in ("mistral", "groq", "deepseek", "together", "fireworks", "xai", "perplexity"):
        if name in ai_client._OPENAI_COMPAT_CONFIG:
            return name
    pytest.skip("the ERP names no OpenAI-compatible provider the module can resolve")


async def _save_settings(user_id: uuid.UUID, provider: str | None, key: str | None = SECRET, **extra) -> None:
    from app.core.crypto import encrypt_secret
    from app.database import async_session_factory
    from app.modules.ai.models import AISettings

    values = {"user_id": user_id, "preferred_model": provider or "claude-sonnet", **extra}
    if provider and key:
        values[f"{provider}_api_key"] = encrypt_secret(key)
    async with async_session_factory() as s:
        s.add(AISettings(**values))
        await s.commit()


def _settings_with(monkeypatch, **kw):
    from app.modules.design import ai_profile
    from app.modules.design.settings import get_design_settings

    base = get_design_settings()
    patched = SimpleNamespace(
        ai_endpoints=kw.get("ai_endpoints", base.ai_endpoints),
        ai_profile_ttl_seconds=kw.get("ttl", base.ai_profile_ttl_seconds),
    )
    monkeypatch.setattr(ai_profile, "get_design_settings", lambda: patched)


async def _context(client, pid, tok, c=None):
    return await (c or client).get(f"{BASE}/projects/{pid}/context", headers=tok)


async def test_profile_is_the_users_own_and_not_cacheable(client):
    uid, h, pid, tok = await _linked_project(client)
    assert (await _context(client, pid, tok)).json()["ai"] is None  # nothing saved yet
    provider = _provider()
    await _save_settings(uid, provider)
    r = await _context(client, pid, tok)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    ai = r.json()["ai"]
    from app.modules.ai import ai_client

    assert ai["protocol"] == "chat-completions" and ai["endpoint"] == ai_client._OPENAI_COMPAT_CONFIG[provider]["url"]
    assert ai["api_key"] == SECRET and ai["local_only"] is False and ai["model"]
    assert set(ai) <= {"protocol", "endpoint", "model", "api_key", "local_only", "expires_at"}
    from datetime import datetime

    left = datetime.fromisoformat(ai["expires_at"].replace("Z", "+00:00")) - datetime.now(UTC)
    assert 0 < left.total_seconds() <= 3600


async def test_the_profile_follows_the_token_owner_only(client):
    uid, h, pid, tok = await _linked_project(client)
    other, _ = await make_user(client)
    await _save_settings(other, _provider())  # somebody else's key must not reach this editor
    assert (await _context(client, pid, tok)).json()["ai"] is None


async def test_no_server_wide_key_is_handed_out(client, monkeypatch):
    uid, h, pid, tok = await _linked_project(client)
    provider = _provider()
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "env-key-must-not-leave")
    await _save_settings(uid, provider, key=None)  # chosen provider, but the user saved no key
    r = await _context(client, pid, tok)
    assert r.json()["ai"] is None and "env-key-must-not-leave" not in r.text


async def test_provider_without_a_known_endpoint_yields_nothing(client, monkeypatch):
    from app.modules.ai import ai_client

    uid, h, pid, tok = await _linked_project(client)
    provider = _provider()
    await _save_settings(uid, provider)
    monkeypatch.delitem(ai_client._OPENAI_COMPAT_CONFIG, provider)
    assert (await _context(client, pid, tok)).json()["ai"] is None


async def test_configured_endpoint_wins_and_ttl_applies(client, monkeypatch):
    uid, h, pid, tok = await _linked_project(client)
    provider = _provider()
    await _save_settings(uid, provider)
    _settings_with(
        monkeypatch,
        ttl=120,
        ai_endpoints={provider: {"protocol": "messages", "endpoint": "https://llm.example.org/v1/m"}},
    )
    ai = (await _context(client, pid, tok)).json()["ai"]
    assert ai["protocol"] == "messages" and ai["endpoint"] == "https://llm.example.org/v1/m"
    from datetime import datetime

    left = datetime.fromisoformat(ai["expires_at"].replace("Z", "+00:00")) - datetime.now(UTC)
    assert 60 < left.total_seconds() <= 120


async def test_loopback_endpoint_only_for_a_loopback_client(client, app_instance, monkeypatch):
    uid, h, pid, tok = await _linked_project(client)
    provider = _provider()
    await _save_settings(uid, provider)
    _settings_with(
        monkeypatch,
        ai_endpoints={provider: {"protocol": "chat-completions", "endpoint": "http://127.0.0.1:11434/v1/chat"}},
    )
    local = (await _context(client, pid, tok)).json()["ai"]  # the test client connects from 127.0.0.1
    assert local["protocol"] == "local" and local["local_only"] is True
    async with AsyncClient(
        transport=ASGITransport(app=app_instance, client=("10.20.30.40", 5000)), base_url="http://test"
    ) as remote:
        r = await _context(client, pid, tok, remote)
    assert r.status_code == 200 and r.json()["ai"] is None and SECRET not in r.text


async def test_public_endpoint_is_given_to_a_remote_client_too(client, app_instance):
    uid, h, pid, tok = await _linked_project(client)
    await _save_settings(uid, _provider())
    async with AsyncClient(
        transport=ASGITransport(app=app_instance, client=("10.20.30.40", 5000)), base_url="http://test"
    ) as remote:
        r = await _context(client, pid, tok, remote)
    assert r.json()["ai"]["api_key"] == SECRET and r.headers["cache-control"] == "no-store"


async def test_token_of_project_a_gets_nothing_from_project_b(client):
    uid, h, pid, tok = await _linked_project(client)
    await _save_settings(uid, _provider())
    pid_b = await make_project(uid, name="Zweites Haus")
    r = await _context(client, pid_b, tok)
    assert r.status_code in (403, 404) and SECRET not in r.text


async def test_missing_or_garbage_token_gets_no_profile(client):
    uid, h, pid, tok = await _linked_project(client)
    await _save_settings(uid, _provider())
    for headers in ({}, {"Authorization": "Bearer ddcl_nope"}, {"Authorization": "Basic abc"}):
        r = await client.get(f"{BASE}/projects/{pid}/context", headers={**headers, "X-DDC-Link": "1"})
        assert r.status_code in (401, 403) and SECRET not in r.text


async def test_the_key_stays_out_of_tables_files_logs_and_other_responses(client, caplog):
    caplog.set_level(logging.DEBUG)
    uid, h, pid, tok = await _linked_project(client)
    await _save_settings(uid, _provider())
    seen = [(await _context(client, pid, tok))]
    rows = example_rows()
    data, manifest = package(pid, rows)
    up = await _upload(client, pid, tok, data)
    assert up.status_code in (200, 201), up.text
    seen.append(up)
    rid = up.json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{rid}/accept", headers=h)).status_code == 200
    for url in (
        f"/projects/{pid}/revisions",
        f"/revisions/{rid}",
        f"/revisions/{rid}/files",
        f"/projects/{pid}/brief",
        f"/projects/{pid}/estimate",
        f"/projects/{pid}/estimate/rules",
    ):
        seen.append(await client.get(f"{BASE}{url}", headers=tok))
    # only the first response (the context) may carry the key
    assert SECRET in seen[0].text
    assert all(SECRET not in r.text and SECRET not in json.dumps(dict(r.headers)) for r in seen[1:])

    from sqlalchemy import text

    from app.database import async_session_factory

    async with async_session_factory() as s:
        tables = (
            (
                await s.execute(
                    text("select table_name from information_schema.tables where table_name like 'oe_design_%'")
                )
            )
            .scalars()
            .all()
        )
        assert tables
        for t in tables:
            rows_ = (await s.execute(text(f'select t::text from "{t}" t'))).scalars().all()  # noqa: S608
            assert not any(SECRET in r for r in rows_), t

    from app.core.storage import get_storage_backend

    base = getattr(get_storage_backend(), "base_dir", None)
    if base is not None:
        for f in base.rglob("*"):
            if f.is_file() and f.stat().st_size < 50_000_000:
                assert SECRET.encode() not in f.read_bytes(), f
    assert SECRET not in caplog.text
