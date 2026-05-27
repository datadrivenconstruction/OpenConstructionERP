"""Integration tests for ``GET /api/v1/dashboard/rollup/``.

Verifies the four key contracts:

1. Basic shape — known widget keys present in the response.
2. Widget filter respected — only requested widgets come back.
3. Project-scope IDOR closed — request scoped to another user's project
   silently drops it (200 with that widget's by_project empty / no leak).
4. Money fields are strings (Decimal-safe), never floats.

Per ``feedback_test_isolation.md`` we redirect DATABASE_URL to a
per-module temp SQLite file BEFORE the app is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-dashroll-"))
_TMP_DB = _TMP_DIR / "dashroll.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the temp SQLite."""
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


async def _force_set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()


async def _register_user(
    client: AsyncClient,
    *,
    role: str = "admin",
    tag: str | None = None,
) -> tuple[str, str, dict[str, str]]:
    tag = tag or uuid.uuid4().hex[:8]
    email = f"dashroll-{tag}@test.io"
    password = f"DashRoll{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"DashRoll Tester {tag}",
            "role": role,
        },
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]
    await _force_set_role(email, role)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return user_id, email, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def alice_auth(client: AsyncClient) -> tuple[str, dict[str, str]]:
    uid, _email, header = await _register_user(client, role="admin", tag="alice")
    return uid, header


@pytest_asyncio.fixture(scope="module")
async def alice_project(
    client: AsyncClient,
    alice_auth: tuple[str, dict[str, str]],
) -> str:
    _, header = alice_auth
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Alice Tower", "description": "fixture"},
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def bob_auth(client: AsyncClient) -> tuple[str, dict[str, str]]:
    # Bob is intentionally non-admin so he can only see his own projects.
    # ``viewer`` is the registration role for read-only users; the
    # IDOR check is at ``Project.owner_id`` not at the role, so the
    # specific role doesn't change the behaviour we're verifying.
    uid, _email, header = await _register_user(client, role="viewer", tag="bob")
    return uid, header


@pytest_asyncio.fixture(scope="module")
async def bob_project(
    client: AsyncClient,
    bob_auth: tuple[str, dict[str, str]],
) -> str:
    _, header = bob_auth
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Bob Plaza", "description": "fixture"},
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── Test 1: basic shape ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollup_returns_all_widgets_by_default(
    client: AsyncClient,
    alice_auth: tuple[str, dict[str, str]],
    alice_project: str,  # noqa: ARG001 — ensures alice owns >= 1 project
) -> None:
    """No filter → every known widget id is present in the response."""
    _, header = alice_auth
    resp = await client.get("/api/v1/dashboard/rollup/", headers=header)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The 10 wave-2 dashboard widgets — frozen contract, can grow but
    # never shrink. W23 P0 added 8 more project-detail widget ids
    # (project_rfi_inbox, project_change_orders_pulse, …) which are
    # also surfaced by the same rollup endpoint, so we check for
    # *subset* containment rather than exact equality.
    expected = {
        "boq_summary",
        "validation_score",
        "clash_health",
        "schedule_critical",
        "risk_top",
        "hse_scorecard",
        "procurement_pipeline",
        "budget_variance",
        "change_orders",
        "weather_site",
    }
    assert expected.issubset(body.keys()), f"Missing widgets: {expected - body.keys()}"
    # Envelope metadata
    assert "generated_at" in body
    assert body["project_count"] >= 1
    assert expected.issubset(set(body["widgets_requested"])), (
        "widgets_requested must include every wave-2 dashboard widget id"
    )

    # ETag + Cache-Control headers ship.
    assert "etag" in {k.lower() for k in resp.headers.keys()}
    cache = resp.headers.get("cache-control", "")
    assert "max-age=60" in cache


# ── Test 2: widget filter respected ────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollup_widget_filter(
    client: AsyncClient,
    alice_auth: tuple[str, dict[str, str]],
    alice_project: str,  # noqa: ARG001
) -> None:
    """``?widgets=boq_summary,clash_health`` returns ONLY those two."""
    _, header = alice_auth
    resp = await client.get(
        "/api/v1/dashboard/rollup/?widgets=boq_summary,clash_health",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The two requested widgets are present...
    assert "boq_summary" in body
    assert "clash_health" in body
    # ...and the eight others are NOT.
    for widget in (
        "validation_score",
        "schedule_critical",
        "risk_top",
        "hse_scorecard",
        "procurement_pipeline",
        "budget_variance",
        "change_orders",
        "weather_site",
    ):
        assert widget not in body, f"Unrequested widget leaked: {widget}"


# ── Test 3: IDOR — caller can't pull another user's project ────────────────


@pytest.mark.asyncio
async def test_rollup_idor_silently_drops_unaccessible_project(
    client: AsyncClient,
    bob_auth: tuple[str, dict[str, str]],
    bob_project: str,
    alice_project: str,
) -> None:
    """Bob requests Alice's project id → it's silently dropped; only his own is reflected.

    The response is 200 (NOT 403 — per IDOR posture), and ``project_count``
    counts only the projects Bob actually owns.
    """
    _, header = bob_auth
    resp = await client.get(
        f"/api/v1/dashboard/rollup/?project_ids={alice_project},{bob_project}",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Bob owns exactly his project — Alice's was silently dropped.
    assert body["project_count"] == 1

    # Per-project rollups in widgets that expose them must only reference Bob's.
    for widget_id in ("boq_summary", "clash_health", "hse_scorecard"):
        widget = body.get(widget_id) or {}
        by_project = widget.get("by_project") or []
        ids = {row.get("project_id") for row in by_project}
        assert alice_project not in ids, f"Widget {widget_id} leaked alice's project_id"
        if by_project:
            assert ids == {bob_project}


# ── Test 4: money fields are Decimal-as-string ─────────────────────────────


@pytest.mark.asyncio
async def test_rollup_money_fields_are_strings(
    client: AsyncClient,
    alice_auth: tuple[str, dict[str, str]],
    alice_project: str,  # noqa: ARG001
) -> None:
    """Money fields must be strings, never floats (JS Number precision)."""
    _, header = alice_auth
    resp = await client.get("/api/v1/dashboard/rollup/", headers=header)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # boq_summary
    boq = body["boq_summary"]
    assert isinstance(boq["total_value_eur"], str), boq["total_value_eur"]
    for row in boq["by_project"]:
        assert isinstance(row["total_value"], str), row

    # change_orders
    co = body["change_orders"]
    assert isinstance(co["total_impact"], str), co["total_impact"]
    for row in co.get("top_pending", []):
        assert isinstance(row["cost_impact"], str), row

    # budget_variance
    bv = body["budget_variance"]
    for row in bv.get("top_over", []):
        assert isinstance(row["planned"], str)
        assert isinstance(row["actual"], str)
        assert isinstance(row["variance"], str)
