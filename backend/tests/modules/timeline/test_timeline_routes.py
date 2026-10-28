# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Timeline HTTP surface: shape, filters and access control."""

from __future__ import annotations

import uuid

import pytest

from tests.modules.timeline.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_entry,
    make_project,
    make_user,
    minutes_ago,
)

pytestmark = pytest.mark.asyncio


async def _owned_project(session):
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    return owner, project


async def test_the_feed_returns_entries_and_pagination_metadata(session) -> None:
    owner, project = await _owned_project(session)
    ncr = str(uuid.uuid4())
    await make_entry(session, project_id=project.id, entity_id=ncr, action="ncr.created", module="ncr")

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 100
    assert body["offset"] == 0
    entry = body["entries"][0]
    assert entry["action"] == "ncr.created"
    assert entry["entity_id"] == ncr
    assert entry["parent_entity_id"] == str(project.id)


async def test_the_metadata_column_is_exposed_under_its_schema_name(session) -> None:
    """The ORM attribute is ``metadata_``; the payload field is ``metadata``."""
    owner, project = await _owned_project(session)
    await make_entry(session, project_id=project.id, metadata={"severity": "high"})

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}")

    assert response.json()["entries"][0]["metadata"] == {"severity": "high"}


async def test_filters_reach_the_query(session) -> None:
    owner, project = await _owned_project(session)
    await make_entry(session, project_id=project.id, action="ncr.created", module="ncr")
    await make_entry(session, project_id=project.id, action="safety.incident.created", module="safety")

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}", params={"module": "safety"})

    body = response.json()
    assert body["total"] == 1
    assert body["entries"][0]["module"] == "safety"


async def test_the_actor_filter_reaches_the_query(session) -> None:
    owner, project = await _owned_project(session)
    actor = uuid.uuid4()
    await make_entry(session, project_id=project.id, action="ncr.created", actor_id=actor)
    await make_entry(session, project_id=project.id, action="ncr.closed", actor_id=uuid.uuid4())

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}", params={"actor": str(actor)})

    body = response.json()
    assert body["total"] == 1
    assert body["entries"][0]["action"] == "ncr.created"


async def test_the_window_filter_reaches_the_query(session) -> None:
    owner, project = await _owned_project(session)
    await make_entry(session, project_id=project.id, action="old", created_at=minutes_ago(60))
    await make_entry(session, project_id=project.id, action="new", created_at=minutes_ago(1))

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(
            f"{API_PREFIX}/projects/{project.id}",
            params={"since": minutes_ago(30).isoformat()},
        )

    body = response.json()
    assert [e["action"] for e in body["entries"]] == ["new"]


async def test_limit_caps_the_page_but_not_the_total(session) -> None:
    owner, project = await _owned_project(session)
    for i in range(4):
        await make_entry(session, project_id=project.id, action=f"e{i}")

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}", params={"limit": 2})

    body = response.json()
    assert len(body["entries"]) == 2
    assert body["total"] == 4


async def test_limit_outside_its_range_is_rejected(session) -> None:
    owner, project = await _owned_project(session)

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        too_big = await client.get(f"{API_PREFIX}/projects/{project.id}", params={"limit": 5000})
        too_small = await client.get(f"{API_PREFIX}/projects/{project.id}", params={"limit": 0})

    assert too_big.status_code == 422
    assert too_small.status_code == 422


# ── access control ───────────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
async def test_a_stranger_cannot_read_the_feed(session) -> None:
    """404 rather than 403, so project existence does not leak."""
    _owner, project = await _owned_project(session)
    stranger = await make_user(session)

    app = build_app(session, caller_id=stranger.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}")

    assert response.status_code == 404


async def test_a_missing_project_answers_the_same_as_a_forbidden_one(session) -> None:
    owner, _project = await _owned_project(session)

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{uuid.uuid4()}")

    assert response.status_code == 404


# ── entity history ───────────────────────────────────────────────────────────


async def test_the_entity_endpoint_returns_one_records_history(session) -> None:
    owner, project = await _owned_project(session)
    ncr = str(uuid.uuid4())
    await make_entry(session, project_id=project.id, entity_type="ncr", entity_id=ncr, action="ncr.created")
    await make_entry(session, project_id=project.id, entity_type="ncr", entity_id=ncr, action="ncr.closed")
    await make_entry(
        session,
        project_id=project.id,
        entity_type="ncr",
        entity_id=str(uuid.uuid4()),
        action="ncr.created",
    )

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}/entities/ncr/{ncr}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert sorted(e["action"] for e in body["entries"]) == ["ncr.closed", "ncr.created"]


@pytest.mark.tenant_isolation
async def test_the_entity_endpoint_will_not_read_across_projects(session) -> None:
    """``entity_id`` is a free string, so the project clause is the only guard.

    The caller owns their own project and presents an id that also exists under
    somebody else's; they must see only their own rows.
    """
    owner, mine = await _owned_project(session)
    _other_owner, theirs = await _owned_project(session)
    shared = str(uuid.uuid4())
    await make_entry(session, project_id=mine.id, entity_type="ncr", entity_id=shared, action="mine")
    await make_entry(session, project_id=theirs.id, entity_type="ncr", entity_id=shared, action="theirs")

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{mine.id}/entities/ncr/{shared}")

    body = response.json()
    assert body["total"] == 1
    assert [e["action"] for e in body["entries"]] == ["mine"]


@pytest.mark.tenant_isolation
async def test_a_stranger_cannot_read_an_entity_history(session) -> None:
    _owner, project = await _owned_project(session)
    stranger = await make_user(session)
    await make_entry(session, project_id=project.id, entity_type="ncr", entity_id="n-1")

    app = build_app(session, caller_id=stranger.id)
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/projects/{project.id}/entities/ncr/n-1")

    assert response.status_code == 404
