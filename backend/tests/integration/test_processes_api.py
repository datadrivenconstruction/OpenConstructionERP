"""Processes center API against the real app and database."""

import pytest

from tests.integration.test_api_smoke import auth_headers, client  # noqa: F401


@pytest.mark.asyncio
async def test_processes_list_and_semantic_stack(client, auth_headers) -> None:  # noqa: F811
    resp = await client.get("/api/v1/processes/", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {p["id"] for p in body["processes"]}
    assert {"vector_db", "embedding_model", "embedding_pool", "vector_backfill", "embedding_model_download"} <= ids
    assert isinstance(body["first_run_done"], bool)
    emb = next(p for p in body["processes"] if p["id"] == "embedding_model")
    assert emb["status"] in {"disabled", "idle"}
    assert emb["name_key"] == "processes.embedding_model.name"

    logs = await client.get("/api/v1/processes/embedding_model/logs", headers=auth_headers)
    assert logs.status_code == 200
    rec = await client.get("/api/v1/processes/recommendations?modules=search", headers=auth_headers)
    assert "embedding_model" in rec.json()["process_ids"]
    assert (await client.post("/api/v1/processes/nope/restart", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_processes_requires_auth(client) -> None:  # noqa: F811
    resp = await client.get("/api/v1/processes/")
    assert resp.status_code in (401, 403)
