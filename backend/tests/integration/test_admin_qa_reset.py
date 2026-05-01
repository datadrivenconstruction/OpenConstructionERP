"""Integration tests for the qa-reset admin endpoint.

Covers all three safety gates plus the happy path and idempotency. Tests
explicitly toggle the env vars so the suite is self-contained — never
relies on a developer's outer shell having ``QA_RESET_ALLOWED`` set.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from contextvars import copy_context

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    """Test client with full app lifespan (startup seeds demo accounts)."""
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
            yield ac


@pytest.fixture
def gate_env(monkeypatch):
    """Open the env-var gate for the test, restore on exit."""
    monkeypatch.setenv("QA_RESET_ALLOWED", "1")
    monkeypatch.setenv("QA_RESET_TOKEN", "test-token-xyz")
    yield
    # monkeypatch undoes both keys automatically.


# ── Gate tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_env_off_rejects(client, monkeypatch):
    """Without QA_RESET_ALLOWED, the endpoint refuses even with a valid token."""
    monkeypatch.delenv("QA_RESET_ALLOWED", raising=False)
    monkeypatch.setenv("QA_RESET_TOKEN", "test-token-xyz")

    res = await client.post(
        "/api/v1/admin/qa-reset",
        json={"tenant": "demo", "confirm_token": "test-token-xyz"},
    )
    assert res.status_code == 403
    body = res.json()["detail"]
    assert body["code"] == "qa_reset_disabled"


@pytest.mark.asyncio
async def test_gate_token_mismatch_rejects(client, gate_env):
    """Wrong confirm_token is rejected with the dedicated mismatch code."""
    res = await client.post(
        "/api/v1/admin/qa-reset",
        json={"tenant": "demo", "confirm_token": "definitely-not-the-token"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "qa_reset_token_mismatch"


@pytest.mark.asyncio
async def test_gate_token_unset_rejects(client, monkeypatch):
    """Server with no QA_RESET_TOKEN configured refuses (no token == no auth)."""
    monkeypatch.setenv("QA_RESET_ALLOWED", "1")
    monkeypatch.delenv("QA_RESET_TOKEN", raising=False)

    res = await client.post(
        "/api/v1/admin/qa-reset",
        json={"tenant": "demo", "confirm_token": "anything"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "qa_reset_token_unset"


@pytest.mark.asyncio
async def test_gate_bad_tenant_rejects(client, gate_env):
    """Only the 'demo' tenant is resettable."""
    res = await client.post(
        "/api/v1/admin/qa-reset",
        json={"tenant": "production", "confirm_token": "test-token-xyz"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "qa_reset_bad_tenant"


@pytest.mark.asyncio
async def test_gate_production_hostname_rejects(gate_env):
    """A production-looking hostname is refused even with all other gates open."""
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        # Use a hostname without any safe substring (no localhost/staging/test/qa/dev).
        async with AsyncClient(
            transport=transport, base_url="http://app.openestimator.io"
        ) as ac:
            res = await ac.post(
                "/api/v1/admin/qa-reset",
                json={"tenant": "demo", "confirm_token": "test-token-xyz"},
            )
            assert res.status_code == 403
            assert res.json()["detail"]["code"] == "qa_reset_production_hostname"


# ── Happy-path tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_resets_and_reseeds(client, gate_env):
    """All gates open, demo tenant, dev hostname → reset succeeds + reseeds."""
    res = await client.post(
        "/api/v1/admin/qa-reset",
        json={"tenant": "demo", "confirm_token": "test-token-xyz"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reset"] is True
    assert "demo@openestimator.io" in body["demo_users"]
    assert body["seeded_projects"] >= 1  # at least one demo project re-installed
    assert body["took_ms"] >= 0


@pytest.mark.asyncio
async def test_idempotency_stable_across_runs(client, gate_env):
    """Calling qa-reset 3 times in a row gives the same seeded_projects count."""
    counts: list[int] = []
    for _ in range(3):
        res = await client.post(
            "/api/v1/admin/qa-reset",
            json={"tenant": "demo", "confirm_token": "test-token-xyz"},
        )
        assert res.status_code == 200, res.text
        counts.append(res.json()["seeded_projects"])

    # All three runs must seed the same number of projects.
    assert len(set(counts)) == 1, f"non-idempotent: {counts}"


@pytest.mark.asyncio
async def test_audit_log_entry_written(client, gate_env):
    """Every successful reset writes an audit entry tagged 'qa_reset'."""
    res = await client.post(
        "/api/v1/admin/qa-reset",
        json={"tenant": "demo", "confirm_token": "test-token-xyz"},
    )
    assert res.status_code == 200

    from sqlalchemy import select

    from app.core.audit import AuditEntry
    from app.database import async_session_factory

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(AuditEntry).where(AuditEntry.action == "qa_reset")
            )
        ).scalars().all()
    assert len(rows) >= 1
    latest = rows[-1]
    assert latest.entity_type == "tenant"
    assert latest.entity_id == "demo"
    assert "demo@openestimator.io" in (latest.details or {}).get("demo_users", [])
