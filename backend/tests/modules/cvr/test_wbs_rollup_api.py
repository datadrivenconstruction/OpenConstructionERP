# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""GET /api/v1/cvr/reports/{id}/wbs-rollup/ over HTTP: access, permission and figures.

The owner and a team member read the roll-up, a manager of another project gets
404 (never a hint the report exists), an unknown id is 404, and a role without
``cvr.read`` is refused with 403. Lines with no WBS, or with a WBS element that
has since been deleted, land in the unallocated bucket.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.tenant_isolation

D = Decimal


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.cvr import models as _cvr_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register(client: AsyncClient, *, tag: str, role: str) -> tuple[dict[str, str], str]:
    """Register and activate a user with ``role``; return its auth headers and id."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"{tag}-{uuid.uuid4().hex[:8]}@cvr-wbs.io"
    password = f"CvrWbs{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"CVR {tag}"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role=role))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return {"Authorization": f"Bearer {token}"}, me.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def world(http_client):
    """Owner A with a report on a two-level WBS; B owns another project; M and F are on A's team."""
    from app.database import async_session_factory
    from app.modules.cvr.models import CvrLine
    from app.modules.projects.models import ProjectWBS
    from app.modules.teams.models import Team, TeamMembership

    a_headers, _ = await _register(http_client, tag="a", role="manager")
    b_headers, _ = await _register(http_client, tag="b", role="manager")
    m_headers, m_id = await _register(http_client, tag="m", role="viewer")
    f_headers, f_id = await _register(http_client, tag="f", role="field_worker")

    proj = await http_client.post(
        "/api/v1/projects/", json={"name": f"CVR A {uuid.uuid4().hex[:6]}", "currency": "EUR"}, headers=a_headers
    )
    assert proj.status_code == 201, proj.text
    pid = proj.json()["id"]
    rep = await http_client.post(
        "/api/v1/cvr/reports/", json={"project_id": pid, "period": "2026-11", "currency": "EUR"}, headers=a_headers
    )
    assert rep.status_code == 201, rep.text
    report_id = rep.json()["id"]

    async with async_session_factory() as s:
        root = ProjectWBS(project_id=uuid.UUID(pid), code="1", name="Building", level=0)
        s.add(root)
        await s.flush()
        sub = ProjectWBS(project_id=uuid.UUID(pid), parent_id=root.id, code="1.1", name="Sub", level=1, sort_order=1)
        sup = ProjectWBS(project_id=uuid.UUID(pid), parent_id=root.id, code="1.2", name="Sup", level=1, sort_order=2)
        gone = ProjectWBS(project_id=uuid.UUID(pid), code="9", name="Removed", level=0)
        s.add_all([sub, sup, gone])
        await s.flush()
        gone_id = gone.id

        def line(wbs, cost, value):
            return CvrLine(
                report_id=uuid.UUID(report_id),
                wbs_id=wbs,
                cost_to_date=D(cost),
                value_to_date=D(value),
                forecast_cost=D(cost),
                forecast_value=D(value),
            )

        s.add_all(
            [
                line(sub.id, "30000", "35000"),
                line(sup.id, "60000", "70000"),
                line(None, "1000", "0"),
                line(gone_id, "500", "0"),
            ]
        )
        team = Team(project_id=uuid.UUID(pid), name="Site")
        s.add(team)
        await s.flush()
        s.add(TeamMembership(team_id=team.id, user_id=uuid.UUID(m_id)))
        s.add(TeamMembership(team_id=team.id, user_id=uuid.UUID(f_id)))
        # The WBS element goes away after its line was booked to it.
        await s.delete(await s.get(ProjectWBS, gone_id))
        await s.commit()

    return {"a": a_headers, "b": b_headers, "m": m_headers, "f": f_headers, "report_id": report_id, "pid": pid}


def _url(report_id: str) -> str:
    return f"/api/v1/cvr/reports/{report_id}/wbs-rollup/"


@pytest.mark.asyncio
async def test_owner_reads_parent_as_own_plus_children(http_client, world):
    resp = await http_client.get(_url(world["report_id"]), headers=world["a"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    nodes = {n["code"]: n for n in body["nodes"]}
    assert list(nodes) == ["1", "1.1", "1.2"]
    top = nodes["1"]
    assert D(top["own"]["cost_to_date"]) == 0
    assert D(top["total"]["cost_to_date"]) == D("90000")
    assert D(top["total"]["value_to_date"]) == D("105000")
    assert top["child_count"] == 2 and top["line_count"] == 2
    assert D(top["total"]["cost_to_date"]) == sum(D(nodes[c]["total"]["cost_to_date"]) for c in ("1.1", "1.2"))
    assert body["report_id"] == world["report_id"] and body["project_id"] == world["pid"]


@pytest.mark.asyncio
async def test_lines_without_wbs_or_with_a_deleted_wbs_are_unallocated(http_client, world):
    body = (await http_client.get(_url(world["report_id"]), headers=world["a"])).json()
    assert body["unallocated"]["line_count"] == 2
    assert D(body["unallocated"]["total"]["cost_to_date"]) == D("1500")
    assert body["line_count"] == 4 and body["wbs_count"] == 3
    assert D(body["totals"]["cost_to_date"]) == D("91500")
    assert body["findings"] == []


@pytest.mark.asyncio
async def test_a_team_member_reads_the_rollup(http_client, world):
    resp = await http_client.get(_url(world["report_id"]), headers=world["m"])
    assert resp.status_code == 200, resp.text
    assert D(resp.json()["totals"]["cost_to_date"]) == D("91500")


@pytest.mark.asyncio
async def test_a_user_of_another_project_gets_404(http_client, world):
    resp = await http_client.get(_url(world["report_id"]), headers=world["b"])
    assert resp.status_code == 404, resp.text
    assert "nodes" not in resp.json()


@pytest.mark.asyncio
async def test_an_unknown_report_is_404(http_client, world):
    resp = await http_client.get(_url(str(uuid.uuid4())), headers=world["a"])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_a_role_without_cvr_read_is_403_even_as_project_member(http_client, world):
    resp = await http_client.get(_url(world["report_id"]), headers=world["f"])
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_no_token_is_401(http_client, world):
    resp = await http_client.get(_url(world["report_id"]))
    assert resp.status_code == 401, resp.text
