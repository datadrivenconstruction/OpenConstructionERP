# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An imported price list can be indexed for CAD-BIM Match.

Reported by a user with an Italian regional prezzario: Match only ever searched
the published CWICR collections, so an imported catalogue never appeared. The
indexer walks the catalogue's rows by primary key, a page at a time. That walk
is the part only a real database can check: keyset paging over UUIDs relies on
the database ordering and comparing them the same way, and a page boundary that
skips or repeats a row would leave a hole in the index nobody sees until a
match comes back without the obvious line.

The vector store and the encoder are faked; the rows and the paging are real.
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.costs import match_index, qdrant_adapter
from app.modules.costs.models import CostCatalog, CostItem

_REGION = "Prezzario Lazio 2024"


class _Store:
    def __init__(self) -> None:
        self.points: dict[str, dict[str, dict]] = {}

    def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.points])

    def get_collection(self, name: str) -> Any:
        if name not in self.points:
            raise RuntimeError("not found")
        return SimpleNamespace(points_count=len(self.points[name]))

    def create_collection(self, collection_name: str, **_: Any) -> None:
        self.points[collection_name] = {}

    def retrieve(self, collection_name: str, ids: list[str], **_: Any) -> list[Any]:
        col = self.points[collection_name]
        return [SimpleNamespace(id=i, payload=col[i]) for i in ids if i in col]

    def upsert(self, collection_name: str, points: list[Any]) -> None:
        for p in points:
            self.points[collection_name][p.id] = dict(p.payload)

    def overwrite_payload(self, collection_name: str, payload: dict, points: list[str]) -> None:
        for pid in points:
            self.points[collection_name][pid] = dict(payload)

    def scroll(self, collection_name: str, limit: int, offset: Any = None, **_: Any) -> tuple[list[Any], Any]:
        ids = sorted(self.points[collection_name])
        start = int(offset or 0)
        nxt = start + limit if start + limit < len(ids) else None
        return [SimpleNamespace(id=i, payload=self.points[collection_name][i]) for i in ids[start : start + limit]], nxt

    def delete(self, collection_name: str, points_selector: Any) -> None:
        for pid in points_selector.points:
            self.points[collection_name].pop(pid, None)


_MODELS = SimpleNamespace(
    PointStruct=lambda id, vector, payload: SimpleNamespace(id=id, vector=vector, payload=payload),  # noqa: A006
    PointIdsList=lambda points: SimpleNamespace(points=points),
    VectorParams=lambda **kw: kw,
    SparseVectorParams=lambda **kw: kw,
    Distance=SimpleNamespace(COSINE="Cosine"),
)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    fake = _Store()
    monkeypatch.setattr(match_index, "_models", lambda: _MODELS)
    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: fake)
    monkeypatch.setattr(
        qdrant_adapter,
        "_encode",
        lambda texts: {"dense": [[0.1, 0.2] for _ in texts], "sparse": [None for _ in texts]},
    )
    # Three pages for seven rows: the boundaries are what is under test.
    monkeypatch.setattr(match_index, "PAGE_SIZE", 3)
    match_index.reset_state()
    yield fake
    match_index.reset_state()


def _same_session(session: Any) -> Any:
    @contextlib.asynccontextmanager
    async def factory() -> Any:
        yield session

    return factory


async def _seed(session: Any) -> list[CostItem]:
    items = [
        CostItem(
            id=uuid.uuid4(),
            code=f"LAZ.{i:03d}",
            description=f"Voce di prezzario {i}",
            unit="m2",
            rate=f"{10 + i}.50",
            currency="EUR",
            region=_REGION,
            source="custom",
            is_active=True,
        )
        for i in range(7)
    ]
    # Rows the index must not pick up: another catalogue, and a retired line.
    items.append(
        CostItem(
            id=uuid.uuid4(),
            code="OTHER.001",
            description="Another book",
            unit="m2",
            rate="1",
            currency="EUR",
            region="Another catalogue",
            is_active=True,
        )
    )
    items.append(
        CostItem(
            id=uuid.uuid4(),
            code="LAZ.OLD",
            description="Voce soppressa",
            unit="m2",
            rate="1",
            currency="EUR",
            region=_REGION,
            is_active=False,
        )
    )
    session.add_all(items)
    await session.flush()
    return items[:7]


@pytest.mark.asyncio
async def test_every_active_row_is_indexed_once_across_pages(pg_session: Any, store: _Store) -> None:
    active = await _seed(pg_session)

    job = match_index.IndexJob(region=_REGION, language="it", country="IT")
    await match_index.index_catalogue(job, session_factory=_same_session(pg_session))

    points = store.points[match_index.collection_for_region(_REGION)]
    assert sorted(points) == sorted(str(i.id) for i in active)
    assert job.processed == 7
    assert job.embedded == 7
    assert {p["catalogue_region"] for p in points.values()} == {_REGION}

    # Retiring a line and re-running removes it and embeds nothing new.
    active[3].is_active = False
    await pg_session.flush()
    again = match_index.IndexJob(region=_REGION, language="it", country="IT")
    await match_index.index_catalogue(again, session_factory=_same_session(pg_session))
    assert again.embedded == 0
    assert again.removed == 1
    assert str(active[3].id) not in points


@pytest.mark.asyncio
async def test_the_costs_page_lists_the_imported_catalogue(pg_session: Any, store: _Store) -> None:
    await _seed(pg_session)
    job = match_index.IndexJob(region=_REGION, language="it", country="IT")
    await match_index.index_catalogue(job, session_factory=_same_session(pg_session))

    overview = {c["region"]: c for c in await match_index.catalogue_overview(pg_session)}
    assert overview[_REGION]["count"] == 7
    assert overview[_REGION]["indexed"] == 7
    assert overview[_REGION]["language"] == "it"
    assert overview["Another catalogue"]["indexed"] == 0


@pytest.mark.asyncio
async def test_a_request_counts_only_active_rows(
    pg_session: Any, store: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(pg_session)
    monkeypatch.setattr(match_index, "embedder_installed", lambda: True)
    monkeypatch.setattr(match_index, "indexer_enabled", lambda: True)
    monkeypatch.setattr(match_index, "_ensure_running", lambda: None)

    job = await match_index.request_index(pg_session, _REGION, "it", "IT")
    assert job.total == 7
    with pytest.raises(match_index.MatchIndexError) as caught:
        await match_index.request_index(pg_session, "No such book", "it", None)
    assert caught.value.code == match_index.ERR_NOT_FOUND


@pytest.mark.asyncio
async def test_another_users_price_list_stays_out_of_sight(
    pg_session: Any, store: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An imported price list is a user-owned catalogue, and so is its index.

    The list and the index action follow the ``/catalogs/`` rule: shared rows
    are everyone's, catalogue rows belong to whoever created the catalogue,
    and admins see all. One foreign row hides the whole region, so a name
    shared with a public book still does not leak the private part.
    """
    await _seed(pg_session)
    alice, bob = uuid.uuid4(), uuid.uuid4()
    catalog = CostCatalog(id=uuid.uuid4(), name="Prezzario Toscana 2025", currency="EUR", created_by=alice)
    pg_session.add(catalog)
    await pg_session.flush()
    rows = [
        CostItem(
            id=uuid.uuid4(),
            code=f"TOS.{i:03d}",
            description=f"Voce toscana {i}",
            unit="m2",
            rate="5",
            currency="EUR",
            region=catalog.name,
            catalog_id=catalog.id,
            is_active=True,
        )
        for i in range(2)
    ]
    # A shared row under the same name must not open the region to Bob.
    rows.append(
        CostItem(
            id=uuid.uuid4(),
            code="TOS.PUB",
            description="Voce pubblica",
            unit="m2",
            rate="5",
            currency="EUR",
            region=catalog.name,
            is_active=True,
        )
    )
    pg_session.add_all(rows)
    await pg_session.flush()
    monkeypatch.setattr(match_index, "embedder_installed", lambda: True)
    monkeypatch.setattr(match_index, "indexer_enabled", lambda: True)
    monkeypatch.setattr(match_index, "_ensure_running", lambda: None)

    async def regions(owner: uuid.UUID | None, admin: bool = False) -> set[str]:
        overview = await match_index.catalogue_overview(pg_session, owner_id=owner, is_admin=admin)
        return {c["region"] for c in overview}

    assert catalog.name in await regions(alice)
    assert catalog.name in await regions(None, admin=True)
    assert catalog.name not in await regions(bob)
    assert catalog.name not in await regions(None)
    # Shared catalogues stay visible to everyone.
    assert _REGION in await regions(bob)

    with pytest.raises(match_index.MatchIndexError) as caught:
        await match_index.request_index(pg_session, catalog.name, "it", "IT", owner_id=bob)
    assert caught.value.code == match_index.ERR_NOT_FOUND
    assert match_index.job_for(catalog.name) is None

    job = await match_index.request_index(pg_session, catalog.name, "it", "IT", owner_id=alice)
    assert job.total == 3
