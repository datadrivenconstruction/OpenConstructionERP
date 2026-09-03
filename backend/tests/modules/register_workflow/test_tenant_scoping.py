# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Two cross-tenant leaks the security pass proved, kept closed.

Both endpoints took a user id and ignored it, so they answered with every
row in the deployment. On a construction ERP that is not an abstract
"information disclosure": a project name IS a client name, and a swept
subject line is what that client wrote to you. These are the tests that
fail the moment somebody adds a list endpoint without a project filter.

The fixture deliberately uses a NON-admin user, because the admin path is
the one that is meant to see everything - a test run as admin would pass
against the broken code.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.outlook_bridge.models import OutlookMessage
from app.modules.outlook_bridge.router import router as ob_router
from app.modules.projects.models import Project
from app.modules.register_workflow import service
from app.modules.register_workflow.router import router as rw_router
from app.modules.users.models import User
from tests._pg import isolated_engine

MINE = "00000000-0000-0000-0000-0000000000b1"

RFQ_FIELDS = {
    "Package": "Cable ladder",
    "Delivery to": "12 Site Rd",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2026-09-30",
}

#: What the leak actually handed over, spelled out so the test reads as
#: the incident it prevents.
THEIR_PROJECT = "SECRET CLIENT - Example Plant Line C"
THEIR_SUBJECT = "CONFIDENTIAL settlement figure - their job"


@pytest_asyncio.fixture
async def ctx():
    """A non-admin caller with ONE project, beside somebody else's."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            me = User(
                id=uuid.UUID(MINE),
                email=f"mine-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Site Manager",
                role="manager",  # NOT admin - admin is meant to see all
            )
            them = User(
                email=f"them-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Other Company",
                role="manager",
            )
            s.add_all([me, them])
            await s.flush()
            mine = Project(
                name=f"MY OWN JOB {uuid.uuid4().hex[:4]}",
                owner_id=me.id,
                currency="AUD",
                project_code=f"J{uuid.uuid4().hex[:6].upper()}",
            )
            theirs = Project(
                name=THEIR_PROJECT, owner_id=them.id, currency="AUD", project_code=f"J{uuid.uuid4().hex[:6].upper()}"
            )
            s.add_all([mine, theirs])
            await s.flush()

            # A register item on each, so portfolio has something to leak.
            for pid in (mine.id, theirs.id):
                await service.raise_item(session=s, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
            # And a swept message filed against THEIR project.
            s.add(
                OutlookMessage(
                    entry_id=f"e-{uuid.uuid4().hex[:8]}",
                    sender_name="Their Client",
                    sender_email="client@theirs.example",
                    subject=THEIR_SUBJECT,
                    project_id=str(theirs.id),
                    status="filed",
                    attachments=[{"filename": "settlement-deed.pdf"}],
                )
            )
            # One unfiled message, which everybody triaging SHOULD see.
            s.add(
                OutlookMessage(
                    entry_id=f"u-{uuid.uuid4().hex[:8]}",
                    sender_name="Nobody Yet",
                    sender_email="new@supplier.example",
                    subject="Unfiled - needs triage",
                    project_id=None,
                    status="unmatched",
                )
            )
            await s.commit()
            ids = (str(mine.id), str(theirs.id))

        app = FastAPI()
        app.include_router(rw_router, prefix="/api/v1/register-workflow")
        app.include_router(ob_router, prefix="/api/v1/outlook-bridge")
        app.dependency_overrides[get_current_user_id] = lambda: MINE
        # Named explicitly, not "*": RequirePermission does a literal
        # membership test, and the point of this fixture is a caller who
        # HAS the read permission and still must not see other projects.
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": MINE,
            "role": "manager",
            "permissions": [
                "register_workflow.read",
                "register_workflow.create",
                "register_workflow.update",
                "outlook_bridge.read",
            ],
        }

        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, ids


@pytest.mark.asyncio
async def test_portfolio_shows_only_the_callers_own_jobs(ctx) -> None:
    """It took a user_id and never used it - so it listed every client in
    the deployment, and which of their jobs were running hot."""
    client, (my_id, their_id) = ctx

    # The premise: this caller genuinely cannot reach the other project.
    assert (await client.get(f"/api/v1/register-workflow/items?project_id={their_id}")).status_code == 404

    resp = await client.get("/api/v1/register-workflow/portfolio")
    assert resp.status_code == 200
    rows = resp.json()["items"]
    assert {r["project_id"] for r in rows} == {my_id}
    assert all(THEIR_PROJECT not in r["project_name"] for r in rows)
    # Their job still exists - it is hidden, not deleted.
    assert rows and rows[0]["open"] >= 1
