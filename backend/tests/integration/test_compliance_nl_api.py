# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T13 integration tests — NL → DSL builder API.

Stands up a minimal FastAPI app with the compliance router mounted and
session/auth dependencies overridden against a per-test throwaway
PostgreSQL database. Exercises the deterministic pattern path, the
AI-disabled-when-no-key path, tenant-isolation behaviour for the listing
endpoint, and the end-to-end "build with NL → save with DSL compile" flow.
"""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.dependencies import get_current_user_payload, get_session
from tests._pg import isolated_engine

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Per-test throwaway PostgreSQL database, cloned from the schema-loaded template.

    The app under test opens its own sessions via the ``get_session`` override, so
    the test and the app run on separate connections that must see each other's
    commits - hence a real throwaway database rather than a savepoint-rolled-back
    shared session.
    """
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield engine, factory


_current_user_payload: dict[str, object] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory = temp_engine_and_factory

    from app.modules.compliance.router import router as compliance_router

    app = FastAPI()
    app.include_router(compliance_router, prefix="/api/v1/compliance")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_payload() -> dict[str, object]:
        return dict(_current_user_payload)

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload

    yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.uuid4()


def _set_acting_user(
    user_id: uuid.UUID,
    tenant_id: str | None = None,
    *,
    permissions: list[str] | None = None,
) -> None:
    """Point the auth override at a caller, optionally holding rule permissions.

    The natural-language helpers are authenticated but ungated, so the default
    caller carries no permissions at all and reaching them is what proves they
    stay open to any signed-in user. Authoring a rule is a different matter:
    v5.9.0 put the compile and delete verbs behind ``compliance.rule.create`` and
    ``compliance.rule.delete`` at manager level, on the argument that a saved DSL
    rule runs against project data and a read-only viewer must not be able to
    register one. A test that saves a rule therefore has to ask for the
    permission by name.

    The permissions are listed rather than claiming ``role="manager"`` so the
    check runs against this list instead of the shared permission registry,
    whose contents depend on which modules happen to have been imported first.
    """
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["tenant_id"] = tenant_id or str(user_id)
    if permissions:
        _current_user_payload["permissions"] = list(permissions)


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_from_nl_pattern_match_returns_yaml(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/from-nl",
        json={"text": "all walls must have fire_rating", "lang": "en"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_method"] == "pattern"
    assert body["matched_pattern"] == "must_have"
    assert body["confidence"] >= 0.85
    assert body["dsl_yaml"]
    assert "fire_rating" in body["dsl_yaml"]
    assert body["dsl_definition"]["scope"] == "wall"


@pytest.mark.asyncio
async def test_from_nl_no_match_returns_suggestions(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/from-nl",
        json={"text": "we should improve everything later", "lang": "en"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_method"] == "fallback"
    assert body["confidence"] == 0.0
    assert body["dsl_yaml"] is None
    assert body["suggestions"]


@pytest.mark.asyncio
async def test_from_nl_use_ai_without_api_key_does_not_crash(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    """AI must be optional — a request with use_ai=True and no API key
    should still respond with the deterministic outcome (pattern match
    or fallback) instead of erroring."""
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/from-nl",
        json={
            "text": "every position must have quantity greater than 0",
            "lang": "en",
            "use_ai": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Pattern matches first — AI fallback never runs even if requested.
    assert body["used_method"] == "pattern"
    assert body["dsl_yaml"]


@pytest.mark.asyncio
async def test_from_nl_empty_text_rejected_by_pydantic(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/from-nl",
        json={"text": "", "lang": "en"},
    )
    # Pydantic min_length=1 → 422.
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_list_nl_patterns_returns_catalogue(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.get("/api/v1/compliance/dsl/nl-patterns")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) >= 8
    ids = {p["pattern_id"] for p in body["items"]}
    assert "must_have" in ids
    assert "count_at_least" in ids


@pytest.mark.asyncio
async def test_from_nl_to_compile_round_trip(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    """End-to-end: NL → DSL → compile/save should succeed."""
    _set_acting_user(user_a, permissions=["compliance.rule.create"])

    nl_resp = await client.post(
        "/api/v1/compliance/dsl/from-nl",
        json={
            "text": "all positions must have description",
            "lang": "en",
        },
    )
    assert nl_resp.status_code == 200, nl_resp.text
    yaml_text = nl_resp.json()["dsl_yaml"]
    assert yaml_text

    compile_resp = await client.post(
        "/api/v1/compliance/dsl/compile",
        json={"definition_yaml": yaml_text, "activate": True},
    )
    assert compile_resp.status_code == 201, compile_resp.text
    body = compile_resp.json()
    assert body["rule_id"] == "custom.position.has_description"
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_from_nl_de_lang_alias(
    client: AsyncClient,
    user_a: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/compliance/dsl/from-nl",
        json={
            "text": "alle walls müssen fire_rating haben",
            "lang": "de",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_method"] == "pattern"
    assert body["matched_pattern"] == "must_have"
