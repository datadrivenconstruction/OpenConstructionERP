"""Completeness contract for the project-detail widget rollup keys (W23 P0).

The frontend's ``ProjectWidgets.tsx`` consolidates 8 of its 13 widgets
behind ``GET /api/v1/dashboard/rollup/`` via the ``ProjectWidgetsRollupProvider``.
Each widget reads its slice keyed by the widget id; if a key is missing
the widget silently falls through to its own ``useGracefulQuery``,
re-introducing the per-widget fan-out the rollup is meant to kill.

These tests guard the contract:

1. Every project-detail widget id we shipped is in ``KNOWN_WIDGETS`` and
   has a matching compute function in ``_COMPUTE_MAP``.
2. The HTTP endpoint accepts every project-detail widget id and returns
   the corresponding key in the response body.
3. A request scoped to a single ``project_ids=<id>`` returns all
   requested project-detail widgets — none silently dropped.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-dashroll-completeness-"))
_TMP_DB = _TMP_DIR / "dashroll-completeness.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# Canonical id list the ProjectWidgets refactor relies on. Mirrors
# ``PROJECT_DETAIL_WIDGET_IDS`` in
# ``frontend/src/shared/api/dashboardRollup.ts``. Adding a key here must
# come with both a backend aggregator AND a frontend widget that reads
# the slice.
PROJECT_DETAIL_WIDGET_IDS: list[str] = [
    "project_rfi_inbox",
    "project_change_orders_pulse",
    "project_daily_diary",
    "project_hse_incidents",
    "project_variations",
    "project_quality_ncr",
    "project_compliance_summary",
    "project_budget_burn",
]


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


async def _register(client: AsyncClient) -> tuple[str, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    email = f"completeness-{tag}@test.io"
    password = f"Complete{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Completeness Tester {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]
    await _force_set_role(email, "admin")

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return user_id, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> tuple[str, dict[str, str]]:
    return await _register(client)


@pytest_asyncio.fixture(scope="module")
async def project_id(
    client: AsyncClient,
    auth: tuple[str, dict[str, str]],
) -> str:
    _, header = auth
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Completeness Tower", "description": "fixture"},
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def test_service_registry_covers_every_widget() -> None:
    """Static contract: every widget id has a compute fn AND is in KNOWN_WIDGETS.

    Catches the "added the widget id to the frontend but forgot the
    backend aggregator" regression at unit-test time, without standing
    up the full app.
    """
    from app.modules.dashboard.service import (
        _COMPUTE_MAP,
        KNOWN_WIDGETS,
    )

    missing_from_known = [w for w in PROJECT_DETAIL_WIDGET_IDS if w not in KNOWN_WIDGETS]
    missing_from_map = [w for w in PROJECT_DETAIL_WIDGET_IDS if w not in _COMPUTE_MAP]
    assert not missing_from_known, f"Widget id(s) missing from KNOWN_WIDGETS: {missing_from_known}"
    assert not missing_from_map, f"Widget id(s) missing from _COMPUTE_MAP: {missing_from_map}"


@pytest.mark.asyncio
async def test_rollup_returns_every_project_detail_widget(
    client: AsyncClient,
    auth: tuple[str, dict[str, str]],
    project_id: str,
) -> None:
    """HTTP contract: GET /rollup/ with our 8 widget ids returns all 8."""
    _, header = auth
    csv = ",".join(PROJECT_DETAIL_WIDGET_IDS)
    resp = await client.get(
        f"/api/v1/dashboard/rollup/?widgets={csv}&project_ids={project_id}",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    missing = [w for w in PROJECT_DETAIL_WIDGET_IDS if w not in body]
    assert not missing, f"Rollup response missing project-detail widget(s): {missing}. Got keys: {sorted(body.keys())}"

    # Envelope correctness — widgets_requested reflects exactly what we asked.
    assert set(body["widgets_requested"]) == set(PROJECT_DETAIL_WIDGET_IDS)
    assert body["project_count"] >= 1


@pytest.mark.asyncio
async def test_rollup_payloads_are_dict_shaped(
    client: AsyncClient,
    auth: tuple[str, dict[str, str]],
    project_id: str,
) -> None:
    """Smoke test on payload shape: every returned widget is a dict, not None.

    The frontend reads ``data?.items`` / ``data?.open`` etc — if the
    aggregator ever started returning ``None`` for a key we'd silently
    break the widget without a TS-level error.
    """
    _, header = auth
    csv = ",".join(PROJECT_DETAIL_WIDGET_IDS)
    resp = await client.get(
        f"/api/v1/dashboard/rollup/?widgets={csv}&project_ids={project_id}",
        headers=header,
    )
    body = resp.json()
    for wid in PROJECT_DETAIL_WIDGET_IDS:
        payload = body.get(wid)
        assert isinstance(payload, dict), f"Widget {wid} should be a dict payload; got {type(payload).__name__}"
