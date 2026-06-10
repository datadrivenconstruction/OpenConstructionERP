"""Integration tests for the resumable BIM CAD upload flow.

The goal is to prove that large files can move through the app in small
chunks, update resumable session state, and finalise into the normal BIM
upload response without relying on a single large multipart body.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def resumable_client():
    app = create_app()

    from app.modules.bim_hub import router as bim_router

    async def _noop_process_cad_in_background(*_args, **_kwargs):
        return None

    patcher = pytest.MonkeyPatch()
    patcher.setattr(bim_router, "_process_cad_in_background", _noop_process_cad_in_background)

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    patcher.undo()


@pytest_asyncio.fixture(scope="module")
async def resumable_auth(resumable_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"bimresumable-{unique}@test.io"
    password = f"BimResumable{unique}9"

    reg = await resumable_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BIM Resumable Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    token = ""
    data: dict[str, str] = {}
    for attempt in range(3):
        resp = await resumable_client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def resumable_project(resumable_client: AsyncClient, resumable_auth: dict[str, str]) -> str:
    resp = await resumable_client.post(
        "/api/v1/projects/",
        json={
            "name": f"BIMResumable Project {uuid.uuid4().hex[:6]}",
            "description": "BIM resumable upload test project",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=resumable_auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_resumable_upload_init_chunk_status_and_complete(
    resumable_client: AsyncClient,
    resumable_auth: dict[str, str],
    resumable_project: str,
):
    file_size = 9 * 1024 * 1024 + 1
    first_chunk = 8 * 1024 * 1024
    second_chunk = file_size - first_chunk

    init_resp = await resumable_client.post(
        "/api/v1/bim_hub/upload-cad/resumable/",
        json={
            "project_id": resumable_project,
            "name": "Big model",
            "discipline": "architecture",
            "filename": "big.ifc",
            "file_size": file_size,
            "chunk_size_bytes": first_chunk,
            "conversion_depth": "standard",
        },
        headers=resumable_auth,
    )
    assert init_resp.status_code == 201, init_resp.text
    init = init_resp.json()
    assert init["status"] == "uploading"
    assert init["model_id"]
    assert init["upload_id"]
    assert init["next_part_number"] == 1

    model_id = init["model_id"]

    part1 = await resumable_client.put(
        f"/api/v1/bim_hub/models/{model_id}/upload/parts/1/",
        content=b"a" * first_chunk,
        headers=resumable_auth,
    )
    assert part1.status_code == 200, part1.text
    part1_data = part1.json()
    assert part1_data["part_number"] == 1
    assert part1_data["next_part_number"] == 2
    assert part1_data["uploaded_bytes"] == first_chunk

    part2 = await resumable_client.put(
        f"/api/v1/bim_hub/models/{model_id}/upload/parts/2/",
        content=b"b" * second_chunk,
        headers=resumable_auth,
    )
    assert part2.status_code == 200, part2.text
    part2_data = part2.json()
    assert part2_data["part_number"] == 2
    assert part2_data["uploaded_bytes"] == file_size
    assert part2_data["next_part_number"] == 3

    status_resp = await resumable_client.get(
        f"/api/v1/bim_hub/models/{model_id}/upload/",
        headers=resumable_auth,
    )
    assert status_resp.status_code == 200, status_resp.text
    status = status_resp.json()
    assert status["uploaded_bytes"] == file_size
    assert status["next_part_number"] == 3
    assert len(status["uploaded_parts"]) == 2

    complete_resp = await resumable_client.post(
        f"/api/v1/bim_hub/models/{model_id}/upload/complete/",
        headers=resumable_auth,
    )
    assert complete_resp.status_code == 202, complete_resp.text
    complete = complete_resp.json()
    assert complete["model_id"] == model_id
    assert complete["status"] == "processing"
    assert complete["file_size"] == file_size
    assert complete["element_count"] == 0
