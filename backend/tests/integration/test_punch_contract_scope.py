"""Explicit punch contract links are validated and never inferred from a project."""

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user_payload, get_session
from app.modules.contracts.models import Contract
from app.modules.projects.models import Project
from app.modules.punchlist.permissions import register_punchlist_permissions
from app.modules.punchlist.router import router
from app.modules.users.models import User
from tests._pg import transactional_session


@asynccontextmanager
async def api():
    register_punchlist_permissions()
    async with transactional_session() as session:
        user = User(email=f"punch-contract-{uuid.uuid4()}@example.test", hashed_password="x", role="editor")
        session.add(user)
        await session.flush()
        project = Project(name="Own project", owner_id=user.id)
        other_project = Project(name="Other project", owner_id=user.id)
        session.add_all([project, other_project])
        await session.flush()
        contracts = [
            Contract(project_id=p.id, code=f"C{index}", title=f"Contract {index}")
            for index, p in enumerate((project, project, other_project))
        ]
        session.add_all(contracts)
        await session.flush()
        app = FastAPI()
        app.include_router(router, prefix="/punchlist")

        async def current_session():
            yield session

        app.dependency_overrides[get_session] = current_session
        app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user.id), "role": "editor"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, project, contracts


@pytest.mark.asyncio
async def test_contract_assignment_can_be_set_changed_and_explicitly_cleared():
    async with api() as (client, project, contracts):
        response = await client.post("/punchlist/items/", json={"project_id": str(project.id), "title": "Old snag"})
        assert response.status_code == 201, response.text
        assert response.json()["contract_id"] is None
        item_id = response.json()["id"]
        for contract_id in (str(contracts[0].id), str(contracts[1].id), None):
            updated = await client.patch(f"/punchlist/items/{item_id}", json={"contract_id": contract_id})
            assert updated.status_code == 200, updated.text
            assert updated.json()["contract_id"] == contract_id


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_foreign_or_missing_contract_is_rejected_on_create_and_update(missing):
    async with api() as (client, project, contracts):
        bad_id = str(uuid.uuid4() if missing else contracts[2].id)
        body = {"project_id": str(project.id), "title": "Scoped snag", "contract_id": bad_id}
        refused = await client.post("/punchlist/items/", json=body)
        assert refused.status_code == 404, refused.text
        assert refused.json()["detail"] == "Contract not found"
        body["contract_id"] = str(contracts[0].id)
        created = await client.post("/punchlist/items/", json=body)
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]
        refused = await client.patch(f"/punchlist/items/{item_id}", json={"contract_id": bad_id})
        assert refused.status_code == 404, refused.text
        unchanged = await client.get(f"/punchlist/items/{item_id}")
        assert unchanged.json()["contract_id"] == str(contracts[0].id)
