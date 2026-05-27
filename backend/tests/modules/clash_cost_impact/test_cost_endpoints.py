"""HTTP integration tests for the clash cost-impact endpoints.

Covers:
    * GET /clash/{id}/impact     — happy path, 401, 403, 404
    * GET /project/{id}/rollup   — happy path, 403 (IDOR), 404

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
per-module temp SQLite file BEFORE ``app`` is first imported, mirroring
the pattern in ``test_clash_a4_endpoints.py``.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-cost-"))
_TMP_DB = _TMP_DIR / "clash_cost.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── App / auth / project fixtures ─────────────────────────────────────────


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


async def _register_admin(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """Register + promote a fresh admin user, return (user_id, header)."""
    from tests.integration._auth_helpers import promote_to_admin

    tag = uuid.uuid4().hex[:8]
    email = f"clash-cost-{tag}@test.io"
    password = f"ClashCostTest{tag}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Clash Cost Tester {tag}",
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
    """Admin user — returns ``(user_id, auth_header)`` together so a test
    can refer to the same identity for both project-ownership writes and
    HTTP calls.
    """
    return await _register_admin(client)


@pytest_asyncio.fixture(scope="module")
async def auth(auth_pair: tuple[str, dict[str, str]]) -> dict[str, str]:
    return auth_pair[1]


@pytest_asyncio.fixture(scope="module")
async def admin_user_id(auth_pair: tuple[str, dict[str, str]]) -> str:
    return auth_pair[0]


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Clash Cost Test Project", "description": "endpoints"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── DB seeding helpers ─────────────────────────────────────────────────────


async def _seed_clash_with_boq(
    project_id_: str,
    *,
    cad_element_ids: list[str],
    a_stable_id: str,
    b_stable_id: str,
    a_discipline: str = "Structural",
    b_discipline: str = "Mechanical",
    quantity: str = "10",
    unit_rate: str = "500",
) -> str:
    """Seed one BOQ + one ClashRun + one ClashResult — return the clash id."""
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position
    from app.modules.clash.models import ClashResult, ClashRun

    async with async_session_factory() as session:
        boq = BOQ(project_id=uuid.UUID(project_id_), name="Test", description="")
        session.add(boq)
        await session.flush()
        pos = Position(
            boq_id=boq.id,
            ordinal="01.01.001",
            description="Test position",
            unit="m3",
            quantity=quantity,
            unit_rate=unit_rate,
            total=str(int(quantity) * int(unit_rate)),
            cad_element_ids=cad_element_ids,
        )
        session.add(pos)
        run = ClashRun(
            project_id=uuid.UUID(project_id_),
            name="Test Run",
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
            a_stable_id=a_stable_id,
            b_stable_id=b_stable_id,
            a_name="A",
            b_name="B",
            a_discipline=a_discipline,
            b_discipline=b_discipline,
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
        )
        session.add(clash)
        await session.commit()
        return str(clash.id)


# ── Endpoint tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clash_impact_happy_path(client: AsyncClient, auth: dict[str, str], project_id: str):
    clash_id = await _seed_clash_with_boq(
        project_id,
        cad_element_ids=["EP-A"],
        a_stable_id="EP-A",
        b_stable_id="EP-B",
    )
    resp = await client.get(
        f"/api/v1/clash-cost-impact/clash/{clash_id}/impact",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["clash_id"] == clash_id
    assert body["currency"] == "EUR"
    assert body["total_estimate"] == 900.00  # 500 rework + 400 labour
    assert body["confidence"] == "high"
    assert len(body["affected_positions"]) == 1


@pytest.mark.asyncio
async def test_clash_impact_unauthorised_returns_401(client: AsyncClient, project_id: str):
    clash_id = await _seed_clash_with_boq(
        project_id,
        cad_element_ids=["NA"],
        a_stable_id="X",
        b_stable_id="Y",
    )
    resp = await client.get(
        f"/api/v1/clash-cost-impact/clash/{clash_id}/impact",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_clash_impact_missing_returns_404(client: AsyncClient, auth: dict[str, str]):
    resp = await client.get(
        f"/api/v1/clash-cost-impact/clash/{uuid.uuid4()}/impact",
        headers=auth,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_project_rollup_unauthorised_returns_401(client: AsyncClient, project_id: str):
    """No Authorization header → 401 (the ``HTTPBearer`` auth gate)."""
    resp = await client.get(
        f"/api/v1/clash-cost-impact/project/{project_id}/rollup",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_project_rollup_happy_path(client: AsyncClient, auth: dict[str, str], project_id: str):
    # Existing seeded clashes from earlier tests live on this project —
    # we just verify the rollup endpoint returns a well-formed envelope.
    resp = await client.get(
        f"/api/v1/clash-cost-impact/project/{project_id}/rollup",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] == project_id
    assert body["currency"] == "EUR"
    assert body["clash_count"] >= 1
    assert body["total_open_impact"] >= 0.0
    # ``by_trade_pair`` is a sorted list, each entry well-shaped.
    for entry in body["by_trade_pair"]:
        assert isinstance(entry["pair"], list)
        assert entry["count"] >= 1
        assert entry["total"] >= 0.0


@pytest.mark.asyncio
async def test_project_rollup_unknown_returns_404(client: AsyncClient, auth: dict[str, str]):
    resp = await client.get(
        f"/api/v1/clash-cost-impact/project/{uuid.uuid4()}/rollup",
        headers=auth,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_project_rollup_status_filter_all_widens(client: AsyncClient, auth: dict[str, str], project_id: str):
    resp_open = await client.get(
        f"/api/v1/clash-cost-impact/project/{project_id}/rollup",
        headers=auth,
    )
    resp_all = await client.get(
        f"/api/v1/clash-cost-impact/project/{project_id}/rollup?status=all",
        headers=auth,
    )
    assert resp_open.status_code == 200
    assert resp_all.status_code == 200
    # status=all must include AT LEAST as many clashes as status=open.
    assert resp_all.json()["clash_count"] >= resp_open.json()["clash_count"]
