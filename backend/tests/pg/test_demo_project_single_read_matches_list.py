# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The single-project read answers what the list answers, for an installed demo.

A demo project listed with its currency and its tags must read back the same
way on ``GET /projects/{id}``: the project page, the header and the dashboard
all open it by id. Both routes serialise through one schema, so a difference
between them is a defect in what the record holds, which is what this pins for
the hospital demo.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.demo_projects import install_demo_project
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.projects.router import router as projects_router

pytestmark = pytest.mark.asyncio

_DEMO_ID = "medical-us"


@pytest_asyncio.fixture
async def client(pg_session):
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1/projects")

    async def _session():
        yield pg_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid.uuid4())
    app.dependency_overrides[get_current_user_payload] = lambda: {"role": "admin", "sub": str(uuid.uuid4())}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_single_read_keeps_currency_and_metadata_the_list_shows(pg_session, client) -> None:
    result = await install_demo_project(pg_session, _DEMO_ID)
    await pg_session.flush()
    project_id = str(result["project_id"])

    listed = (await client.get("/api/v1/projects/", params={"limit": 500})).json()
    from_list = next(p for p in listed if p["id"] == project_id)
    single = (await client.get(f"/api/v1/projects/{project_id}")).json()

    assert from_list["currency"] == "USD"
    assert single["currency"] == from_list["currency"], "the single read lost the currency the list shows"
    assert single["metadata"] == from_list["metadata"], "the single read lost the metadata the list shows"
    assert single["metadata"].get("demo_id") == _DEMO_ID
