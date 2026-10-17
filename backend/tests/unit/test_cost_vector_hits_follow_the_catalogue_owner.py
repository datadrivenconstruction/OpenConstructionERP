# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hits from the ``oe_cost_items`` vector collection follow the catalogue owner.

The collection is fed by the cost event handlers and the admin reindex with
every cost row, rows of user-owned catalogues included, and its points carry
no owner and no project. The cross-collection search (``GET /search/``, the
command palette, the chat search tools and the project advisor) fences hits
by project only, so a cost hit passed the fence whoever asked, with code,
description and rate in its payload. The same holds for the cost adapter's
own ``search``.

These tests stand in a vector store that already holds a private row and a
shared row, and ask as the catalogue owner, an admin, another user and an
anonymous reader.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cost_scope
from app.core.vector_index import COLLECTION_COSTS, VectorHit
from app.modules.costs.models import CostCatalog, CostItem
from app.modules.users.models import User
from tests._pg import transactional_session

# Text the SQL track cannot match, so every hit in the answer came from the vector store.
_QUERY = "zzvectoronly"

READERS = [("alice", True), ("admin", True), ("bob", False), (None, False)]


class _SharedSession:
    """Hand the code under test the test's transaction instead of a fresh session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest_asyncio.fixture
async def world() -> AsyncIterator[dict[str, Any]]:
    async with transactional_session() as s:
        ids: dict[str, Any] = {"session": s}
        for name, role in (("alice", "manager"), ("bob", "editor"), ("admin", "admin")):
            user = User(
                id=uuid.uuid4(),
                email=f"vec-{uuid.uuid4().hex[:8]}@test.io",
                hashed_password="x" * 60,
                full_name="Vector Test",
                role=role,
                locale="en",
                is_active=True,
                metadata_={},
            )
            s.add(user)
            ids[name] = user.id
        await s.flush()
        region = f"ZZVEC{uuid.uuid4().hex[:6].upper()}"
        catalog = CostCatalog(id=uuid.uuid4(), name=region, currency="EUR", created_by=ids["alice"])
        s.add(catalog)
        await s.flush()
        private = CostItem(
            id=uuid.uuid4(),
            code="ZZVEC.PRIV",
            description="private partition wall",
            unit="m2",
            rate="77",
            currency="EUR",
            region=region,
            catalog_id=catalog.id,
            is_active=True,
        )
        shared = CostItem(
            id=uuid.uuid4(),
            code="ZZVEC.SHARED",
            description="shared partition wall",
            unit="m2",
            rate="66",
            currency="EUR",
            region=f"{region}S",
            is_active=True,
        )
        s.add_all([private, shared])
        await s.flush()
        s.expunge_all()
        ids.update(private=str(private.id), shared=str(shared.id))
        yield ids


def _stored(w: dict[str, Any]) -> list[dict[str, Any]]:
    """The points an installation's cost collection holds for the two rows."""
    return [
        {
            "id": w[key],
            "score": score,
            "text": f"{code} partition wall",
            "module": "costs",
            "project_id": "",
            "tenant_id": "",
            "payload": {"code": code, "description": f"{key} partition wall", "unit": "m2", "unit_cost": rate},
        }
        for key, code, rate, score in (("private", "ZZVEC.PRIV", 77.0, 0.9), ("shared", "ZZVEC.SHARED", 66.0, 0.8))
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("reader", "sees_private"), READERS)
async def test_cross_collection_search_drops_cost_hits_the_caller_may_not_read(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, reader: str | None, sees_private: bool
) -> None:
    from app.modules.search import service as search_service

    async def _vector_track(collection: str, *_a: object, **_k: object) -> list[VectorHit]:
        if collection != COLLECTION_COSTS:
            return []
        return [VectorHit(**{**raw, "collection": collection}) for raw in _stored(world)]

    monkeypatch.setattr(search_service, "search_collection", _vector_track)
    monkeypatch.setattr(search_service, "async_session_factory", lambda: _SharedSession(world["session"]))

    user_id = str(world[reader]) if reader else None
    with cost_scope.caller_scope(world[reader] if reader else None):
        response = await search_service.unified_search_service(_QUERY, user_id=user_id, types=[COLLECTION_COSTS])

    ids = {hit.id for hit in response.hits}
    assert world["shared"] in ids, f"{reader} lost the shared row"
    assert (world["private"] in ids) is sees_private, f"{reader}: {ids}"
    assert response.facets[COLLECTION_COSTS] == (2 if sees_private else 1), "the facet count names hidden rows"


@pytest.mark.asyncio
@pytest.mark.parametrize(("reader", "sees_private"), READERS)
async def test_the_cost_adapter_search_drops_hits_the_caller_may_not_read(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, reader: str | None, sees_private: bool
) -> None:
    import app.database as database
    from app.core import vector
    from app.modules.costs import vector_adapter

    async def _encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    monkeypatch.setattr(vector_adapter, "_vector_available", lambda: True)
    monkeypatch.setattr(vector, "encode_texts_async", _encode)
    monkeypatch.setattr(vector, "vector_search_collection", lambda *_a, **_k: _stored(world))
    monkeypatch.setattr(database, "async_session_factory", lambda: _SharedSession(world["session"]))

    with cost_scope.caller_scope(world[reader] if reader else None):
        hits = await vector_adapter.search("partition wall", limit=10)

    ids = {hit["id"] for hit in hits}
    assert world["shared"] in ids, f"{reader} lost the shared row"
    assert (world["private"] in ids) is sees_private, f"{reader}: {ids}"
