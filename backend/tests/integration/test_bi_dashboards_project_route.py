# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The BI list endpoints honour the project in the address bar.

``/projects/{id}/bi-dashboards`` and ``/bi-dashboards`` used to render the
same page from the same data: the list endpoints took no project at all. This
drives the fix through the real ASGI app so the wiring is proved end to end,
not just in the service:

    GET /dashboards?project_id=A  -> that project's rows plus company-wide
    GET /dashboards               -> unchanged, everything the caller owns
    GET /dashboards?project_id=S  -> 404 for a project the caller cannot see
    POST /dashboards {project_id: S} -> 404, the column cannot pin an asset
                                        to somebody else's project
    PATCH /dashboards/{id} {project_id: S} -> 404, nor repoint one that is
                                        already owned

The caller is a ``manager``, not an ``admin``, on purpose: admins bypass
``verify_project_access`` entirely, so an admin would prove nothing about the
access check.

Run:
    cd backend
    python -m pytest tests/integration/test_bi_dashboards_project_route.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.bi_dashboards.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401

_BASE = "/api/v1/bi-dashboards"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login(client: AsyncClient, *, tenant: str, role: str) -> tuple[str, dict[str, str]]:
    """Register, activate, set role, log in. Returns (user_id, headers)."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"{tenant}-{uuid.uuid4().hex[:8]}@bi-project-route.io"
    password = f"BiRoute{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": tenant},
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_project(*, owner_id: str) -> uuid.UUID:
    """Create a bare project owned by ``owner_id``."""
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        project = Project(
            id=uuid.uuid4(),
            name=f"BI-{uuid.uuid4().hex[:6]}",
            owner_id=uuid.UUID(owner_id),
            currency="EUR",
            region="DACH",
            classification_standard="din276",
            metadata_={},
            fx_rates=[],
        )
        s.add(project)
        await s.commit()
        return project.id


@pytest.mark.asyncio
async def test_project_route_lists_the_project_and_the_company_wide_only(
    http_client: AsyncClient,
) -> None:
    user_id, headers = await _register_login(http_client, tenant="manager", role="manager")
    project_a = await _seed_project(owner_id=user_id)
    project_b = await _seed_project(owner_id=user_id)

    suffix = uuid.uuid4().hex[:6]
    for label, pid in (("a", str(project_a)), ("b", str(project_b)), ("company", None)):
        body: dict[str, object] = {"name": f"board-{label}-{suffix}", "scope": "personal"}
        if pid is not None:
            body["project_id"] = pid
        created = await http_client.post(f"{_BASE}/dashboards", json=body, headers=headers)
        assert created.status_code == 201, created.text

    scoped = await http_client.get(f"{_BASE}/dashboards?project_id={project_a}", headers=headers)
    assert scoped.status_code == 200, scoped.text
    names = {d["name"] for d in scoped.json()}
    assert names == {f"board-a-{suffix}", f"board-company-{suffix}"}

    # The plain module route is untouched - it still answers for everything.
    unscoped = await http_client.get(f"{_BASE}/dashboards", headers=headers)
    assert unscoped.status_code == 200, unscoped.text
    all_names = {d["name"] for d in unscoped.json()}
    assert all_names == {
        f"board-a-{suffix}",
        f"board-b-{suffix}",
        f"board-company-{suffix}",
    }


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_naming_an_inaccessible_project_is_a_404_not_a_listing(
    http_client: AsyncClient,
) -> None:
    """A project the caller cannot reach must not answer with the company page."""
    stranger_id, _ = await _register_login(http_client, tenant="stranger", role="manager")
    strangers_project = await _seed_project(owner_id=stranger_id)

    _caller_id, headers = await _register_login(http_client, tenant="caller", role="manager")

    for path in ("dashboards", "reports", "report-schedules", "saved-filters", "kpis"):
        denied = await http_client.get(
            f"{_BASE}/{path}?project_id={strangers_project}",
            headers=headers,
        )
        assert denied.status_code == 404, f"{path}: {denied.status_code} {denied.text}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_a_dashboard_cannot_be_pinned_to_someone_elses_project(
    http_client: AsyncClient,
) -> None:
    stranger_id, _ = await _register_login(http_client, tenant="stranger2", role="manager")
    strangers_project = await _seed_project(owner_id=stranger_id)

    _caller_id, headers = await _register_login(http_client, tenant="caller2", role="manager")
    created = await http_client.post(
        f"{_BASE}/dashboards",
        json={
            "name": f"smuggled-{uuid.uuid4().hex[:6]}",
            "scope": "personal",
            "project_id": str(strangers_project),
        },
        headers=headers,
    )
    assert created.status_code == 404, created.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_an_owned_asset_cannot_be_repointed_at_someone_elses_project(
    http_client: AsyncClient,
) -> None:
    """Owning the row is not the same as reaching the project it moves to.

    The create endpoints refuse a project the caller cannot see, but the
    update endpoints take the same column, so the same refusal has to hold
    there. Both assets are created company-wide first, which is the shape an
    owner would already have on hand to repoint.
    """
    stranger_id, _ = await _register_login(http_client, tenant="stranger3", role="manager")
    strangers_project = await _seed_project(owner_id=stranger_id)

    _caller_id, headers = await _register_login(http_client, tenant="caller3", role="manager")
    suffix = uuid.uuid4().hex[:6]

    board = await http_client.post(
        f"{_BASE}/dashboards",
        json={"name": f"own-board-{suffix}", "scope": "personal"},
        headers=headers,
    )
    assert board.status_code == 201, board.text
    board_id = board.json()["id"]

    moved = await http_client.patch(
        f"{_BASE}/dashboards/{board_id}",
        json={"project_id": str(strangers_project)},
        headers=headers,
    )
    assert moved.status_code == 404, moved.text

    # And the refusal has to be a refusal, not a 404 reported after the write
    # already landed. There is no single-dashboard GET, so read it back out of
    # the list the caller owns.
    after = await http_client.get(f"{_BASE}/dashboards", headers=headers)
    assert after.status_code == 200, after.text
    stored = next(d for d in after.json() if d["id"] == board_id)
    assert stored["project_id"] is None, "the update was refused but the move was written anyway"

    report = await http_client.post(
        f"{_BASE}/reports",
        json={"code": f"own-report-{suffix}", "name": f"Own report {suffix}"},
        headers=headers,
    )
    assert report.status_code == 201, report.text

    schedule = await http_client.post(
        f"{_BASE}/report-schedules",
        json={"report_definition_id": report.json()["id"], "frequency": "daily"},
        headers=headers,
    )
    assert schedule.status_code == 201, schedule.text

    moved_schedule = await http_client.patch(
        f"{_BASE}/report-schedules/{schedule.json()['id']}",
        json={"project_id": str(strangers_project)},
        headers=headers,
    )
    assert moved_schedule.status_code == 404, moved_schedule.text
