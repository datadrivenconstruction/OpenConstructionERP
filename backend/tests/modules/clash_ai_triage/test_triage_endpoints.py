# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP integration tests for the clash AI triage endpoints.

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
per-module temp SQLite file BEFORE ``app`` is first imported, mirroring
the convention used by ``test_clash_cost_endpoints``.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-triage-ep-"))
_TMP_DB = _TMP_DIR / "triage_ep.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

_VALID_VERDICT_JSON = json.dumps(
    {
        "category": "real_design_flaw",
        "confidence": 0.85,
        "severity_suggested": "high",
        "explanation": "Pipe through beam — coordinate.",
        "suggested_action": "add_sleeve",
        "model_evidence_used": ["material_a=DN200", "trade_pair=mep/struct"],
    }
)


async def _mock_call_ai(*args, **kwargs):
    return _VALID_VERDICT_JSON, 200


# ── App / auth fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_admin(client: AsyncClient) -> tuple[str, dict[str, str]]:
    from tests.integration._auth_helpers import promote_to_admin

    tag = uuid.uuid4().hex[:8]
    email = f"clash-triage-{tag}@test.io"
    password = f"ClashTriageTest{tag}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Triage Tester {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    await promote_to_admin(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return reg.json()["id"], {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def auth_pair(client: AsyncClient) -> tuple[str, dict[str, str]]:
    return await _register_admin(client)


@pytest_asyncio.fixture(scope="module")
async def auth(auth_pair):
    return auth_pair[1]


@pytest_asyncio.fixture(scope="module")
async def admin_user_id(auth_pair) -> str:
    return auth_pair[0]


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Triage EP Test Project", "description": ""},
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── Seeding helpers ─────────────────────────────────────────────────────────


async def _seed_ai_settings(user_id: str) -> None:
    """Plant an encrypted Anthropic key against the test user.

    The mocked ``call_ai`` never reaches the real provider, so the key
    value is a placeholder — the resolver only checks that decrypt_secret
    yields a non-empty string.
    """
    from sqlalchemy import select

    from app.core.crypto import encrypt_secret
    from app.database import async_session_factory
    from app.modules.ai.models import AISettings

    async with async_session_factory() as session:
        existing = (
            await session.execute(select(AISettings).where(AISettings.user_id == uuid.UUID(user_id)))
        ).scalar_one_or_none()
        if existing is not None:
            existing.anthropic_api_key = encrypt_secret("sk-test-fake-key")
        else:
            session.add(
                AISettings(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id),
                    anthropic_api_key=encrypt_secret("sk-test-fake-key"),
                    preferred_model="claude-haiku",
                )
            )
        await session.commit()


async def _clear_ai_settings(user_id: str) -> None:
    """Strip every API key so the resolver raises."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.ai.models import AISettings

    async with async_session_factory() as session:
        existing = (
            await session.execute(select(AISettings).where(AISettings.user_id == uuid.UUID(user_id)))
        ).scalar_one_or_none()
        if existing is not None:
            for attr in (
                "anthropic_api_key",
                "openai_api_key",
                "gemini_api_key",
                "openrouter_api_key",
                "mistral_api_key",
                "groq_api_key",
                "deepseek_api_key",
                "together_api_key",
                "fireworks_api_key",
                "perplexity_api_key",
                "cohere_api_key",
                "ai21_api_key",
                "xai_api_key",
            ):
                if hasattr(existing, attr):
                    setattr(existing, attr, None)
            await session.commit()


async def _seed_clash(project_id_: str) -> str:
    """Seed one ClashRun + one ClashResult; return the clash row id."""
    from app.database import async_session_factory
    from app.modules.clash.models import ClashResult, ClashRun

    async with async_session_factory() as session:
        run = ClashRun(
            project_id=uuid.UUID(project_id_),
            name="EP Test Run",
            model_ids=[str(uuid.uuid4())],
            status="completed",
            created_by=str(uuid.uuid4()),
        )
        session.add(run)
        await session.flush()
        clash = ClashResult(
            run_id=run.id,
            a_element_id=uuid.uuid4(),
            b_element_id=uuid.uuid4(),
            a_stable_id="EP-A",
            b_stable_id="EP-B",
            a_name="Pipe A",
            b_name="Beam B",
            a_discipline="Mechanical",
            b_discipline="Structural",
            a_element_type="IfcPipeSegment",
            b_element_type="IfcBeam",
            a_model_id=uuid.uuid4(),
            b_model_id=uuid.uuid4(),
            clash_type="hard",
            penetration_m=0.05,
            distance_m=0.0,
            cx=0.0,
            cy=0.0,
            cz=0.0,
            status="new",
            severity="medium",
            signature=uuid.uuid4().hex[:16],
            signature_hash=uuid.uuid4().hex.ljust(40, "0")[:40],
            tolerance_at_signature_time_mm=5.0,
        )
        session.add(clash)
        await session.commit()
        return str(clash.id)


# ── 1. POST /clashes/{clash_id} happy path ─────────────────────────────────


@pytest.mark.asyncio
async def test_post_single_triage_happy(
    client: AsyncClient,
    auth: dict[str, str],
    admin_user_id: str,
    project_id: str,
) -> None:
    await _seed_ai_settings(admin_user_id)
    clash_id = await _seed_clash(project_id)
    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock_call_ai):
        resp = await client.post(f"/api/v1/clash-ai-triage/clashes/{clash_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["category"] == "real_design_flaw"
    assert body["confidence"] == pytest.approx(0.85)
    assert body["clash_id"] == clash_id
    assert body["prompt_version"] == "v1.0"


# ── 2. POST /batch ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_batch_returns_results(
    client: AsyncClient,
    auth: dict[str, str],
    admin_user_id: str,
    project_id: str,
) -> None:
    await _seed_ai_settings(admin_user_id)
    cid1 = await _seed_clash(project_id)
    cid2 = await _seed_clash(project_id)
    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock_call_ai):
        resp = await client.post(
            "/api/v1/clash-ai-triage/batch",
            json={"clash_ids": [cid1, cid2], "max_concurrent": 2},
            headers=auth,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2


# ── 3. GET /clashes/{id}/history ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_returns_newest_first(
    client: AsyncClient,
    auth: dict[str, str],
    admin_user_id: str,
    project_id: str,
) -> None:
    await _seed_ai_settings(admin_user_id)
    clash_id = await _seed_clash(project_id)
    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock_call_ai):
        await client.post(f"/api/v1/clash-ai-triage/clashes/{clash_id}", headers=auth)
        await client.post(
            f"/api/v1/clash-ai-triage/clashes/{clash_id}?force_refresh=true",
            headers=auth,
        )

    resp = await client.get(f"/api/v1/clash-ai-triage/clashes/{clash_id}/history", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 2
    assert len(body["items"]) >= 2
    # Newest first.
    ts_first = body["items"][0]["created_at"]
    ts_last = body["items"][-1]["created_at"]
    assert ts_first >= ts_last


# ── 4. GET /prompts/current ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompts_current_returns_templates(client: AsyncClient, auth: dict[str, str]) -> None:
    resp = await client.get("/api/v1/clash-ai-triage/prompts/current", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prompt_version"] == "v1.0"
    assert "STRICT JSON" in body["system_prompt"]
    assert "{ifc_class_a}" in body["user_prompt_template"]


# ── 5. 401 missing token ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthorised_returns_401(client: AsyncClient, admin_user_id: str, project_id: str) -> None:
    clash_id = await _seed_clash(project_id)
    resp = await client.post(f"/api/v1/clash-ai-triage/clashes/{clash_id}")
    assert resp.status_code == 401


# ── 6. 503 when LLM unavailable ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_503_when_llm_not_configured(
    client: AsyncClient,
    auth: dict[str, str],
    admin_user_id: str,
    project_id: str,
) -> None:
    await _clear_ai_settings(admin_user_id)
    clash_id = await _seed_clash(project_id)
    resp = await client.post(f"/api/v1/clash-ai-triage/clashes/{clash_id}", headers=auth)
    assert resp.status_code == 503, resp.text
    # Restore the settings for any test that runs after this one.
    await _seed_ai_settings(admin_user_id)


# ── 7. 404 when clash missing ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_404_when_clash_missing(client: AsyncClient, auth: dict[str, str], admin_user_id: str) -> None:
    await _seed_ai_settings(admin_user_id)
    bogus = uuid.uuid4()
    resp = await client.post(f"/api/v1/clash-ai-triage/clashes/{bogus}", headers=auth)
    assert resp.status_code == 404


# ── 8. Replay endpoint ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_endpoint_creates_new_row(
    client: AsyncClient,
    auth: dict[str, str],
    admin_user_id: str,
    project_id: str,
) -> None:
    await _seed_ai_settings(admin_user_id)
    clash_id = await _seed_clash(project_id)
    with patch("app.modules.clash_ai_triage.service.call_ai", new=_mock_call_ai):
        original = await client.post(f"/api/v1/clash-ai-triage/clashes/{clash_id}", headers=auth)
        assert original.status_code == 200, original.text
        original_id = original.json()["id"]

        replay = await client.post(
            f"/api/v1/clash-ai-triage/replay/{original_id}",
            json={"prompt_version": "v1.1-test"},
            headers=auth,
        )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["id"] != original_id
    assert body["prompt_version"] == "v1.1-test"
