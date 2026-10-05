# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""A client sees a progress report only after a person published it.

Before ``published_at`` existed, the portal listed and served every generated
progress report of a project, so a draft carrying internal notes reached the
client the moment anyone generated it.

Surface (portal-session-gated):
    GET /api/v1/portal/projects/{project_id}/progress-reports
    GET /api/v1/portal/projects/{project_id}/progress-reports/{report_id}/content

Tests:
* The list holds the published report and not the draft.
* The draft's content answers 404, exactly like a missing id, never 410.
* The published report passes every gate (its body is not rendered here, so
  the answer is 410, which only a report the client may see can reach).
* Publishing keeps the first release time; unpublishing takes the report back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _no_detached_events(monkeypatch):
    from app.core import events

    monkeypatch.setattr(events.event_bus, "publish_detached", lambda *a, **k: None)


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.portal import models as _portal_models  # noqa: F401
        from app.modules.reporting import models as _reporting_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def seeded(http_client):
    """One project, one client portal user with view access, a draft and a
    published progress report, and a published report on another project."""
    from app.database import async_session_factory
    from app.modules.portal.models import PortalAccessRule, PortalSession, PortalUser
    from app.modules.portal.service import generate_token, hash_token
    from app.modules.projects.models import Project
    from app.modules.reporting.models import GeneratedReport
    from app.modules.users.models import User

    now = datetime.now(UTC)
    out: dict = {}
    async with async_session_factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:8]}@reports.io",
            full_name="Builder",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(owner)
        await s.flush()

        projects = []
        for label in ("mine", "other"):
            proj = Project(name=f"Reports-{label}-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="EUR")
            s.add(proj)
            await s.flush()
            projects.append(proj)
        mine, other = projects

        def report(project_id: uuid.UUID, title: str, published: bool) -> GeneratedReport:
            return GeneratedReport(
                project_id=project_id,
                report_type="progress_report",
                title=title,
                generated_at=now.isoformat(),
                format="html",
                storage_key=None,
                published_at=now if published else None,
                published_by=owner.id if published else None,
            )

        draft = report(mine.id, "Week 40 draft with internal notes", published=False)
        released = report(mine.id, "Week 39 progress", published=True)
        foreign = report(other.id, "Other project progress", published=True)
        s.add_all([draft, released, foreign])
        await s.flush()

        client = PortalUser(
            id=uuid.uuid4(),
            email=f"client-{uuid.uuid4().hex[:6]}@reports.io",
            portal_role="client",
            full_name="Home Owner",
            status="active",
        )
        s.add(client)
        await s.flush()
        s.add(
            PortalAccessRule(
                portal_user_id=client.id,
                resource_type="project",
                resource_id=mine.id,
                permission="view",
            )
        )
        token = generate_token()
        s.add(
            PortalSession(
                portal_user_id=client.id,
                session_token_hash=hash_token(token),
                ip_address="127.0.0.1",
                user_agent="pytest",
                started_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        await s.commit()

        out.update(
            project_id=str(mine.id),
            draft_id=str(draft.id),
            released_id=str(released.id),
            foreign_id=str(foreign.id),
            owner_id=owner.id,
            token=token,
        )
    return out


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_the_list_holds_only_the_published_report(http_client, seeded):
    resp = await http_client.get(
        f"/api/v1/portal/projects/{seeded['project_id']}/progress-reports",
        headers=_auth(seeded["token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [seeded["released_id"]]
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_a_draft_answers_like_a_missing_report(http_client, seeded):
    base = f"/api/v1/portal/projects/{seeded['project_id']}/progress-reports"
    draft = await http_client.get(f"{base}/{seeded['draft_id']}/content", headers=_auth(seeded["token"]))
    missing = await http_client.get(f"{base}/{uuid.uuid4()}/content", headers=_auth(seeded["token"]))
    assert draft.status_code == 404
    assert missing.status_code == 404
    assert draft.json() == missing.json()


@pytest.mark.asyncio
async def test_a_published_report_passes_every_gate(http_client, seeded):
    base = f"/api/v1/portal/projects/{seeded['project_id']}/progress-reports"
    resp = await http_client.get(f"{base}/{seeded['released_id']}/content", headers=_auth(seeded["token"]))
    # The body was never rendered in this test, so a report the client may
    # see answers 410; anything the client may not see stops at 404 first.
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_another_projects_published_report_stays_hidden(http_client, seeded):
    base = f"/api/v1/portal/projects/{seeded['project_id']}/progress-reports"
    resp = await http_client.get(f"{base}/{seeded['foreign_id']}/content", headers=_auth(seeded["token"]))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_publishing_keeps_the_first_release_and_unpublishing_takes_it_back(seeded):
    from app.database import async_session_factory
    from app.modules.reporting.service import ReportingService

    report_id = uuid.UUID(seeded["draft_id"])
    async with async_session_factory() as s:
        svc = ReportingService(s)
        first = await svc.set_published(report_id, published=True, user_id=seeded["owner_id"])
        first_at = first.published_at
        assert first_at is not None
        assert first.published_by == seeded["owner_id"]

        again = await svc.set_published(report_id, published=True, user_id=uuid.uuid4())
        assert again.published_at == first_at
        assert again.published_by == seeded["owner_id"]

        back = await svc.set_published(report_id, published=False, user_id=None)
        assert back.published_at is None
        assert back.published_by is None
        await s.rollback()
