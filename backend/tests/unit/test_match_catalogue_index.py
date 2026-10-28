"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An imported catalogue indexed for CAD-BIM Match (``costs.match_index``).

The store and the encoder are faked: neither the vector client nor the
embedding model is installed in the test environment, and what is under test
is the bookkeeping around them - which rows get embedded, which only get a new
payload, which points go, where a search is routed and what a refusal says.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.costs import match_index, qdrant_adapter
from app.modules.costs.match_index import IndexJob, MatchIndexError

# ── Fakes ─────────────────────────────────────────────────────────────────


class _PointStruct:
    def __init__(self, id: str, vector: dict, payload: dict) -> None:  # noqa: A002
        self.id = id
        self.vector = vector
        self.payload = payload


class _PointIdsList:
    def __init__(self, points: list[str]) -> None:
        self.points = points


_MODELS = SimpleNamespace(
    PointStruct=_PointStruct,
    PointIdsList=_PointIdsList,
    VectorParams=lambda **kw: kw,
    SparseVectorParams=lambda **kw: kw,
    Distance=SimpleNamespace(COSINE="Cosine"),
)


class _Store:
    """The handful of client calls the indexer makes, over plain dicts."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict]] = {}
        self.created: list[str] = []
        self.payload_rewrites = 0

    def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.collections])

    def get_collection(self, name: str) -> Any:
        if name not in self.collections:
            raise RuntimeError(f"collection {name} not found")
        return SimpleNamespace(points_count=len(self.collections[name]))

    def create_collection(self, collection_name: str, **_: Any) -> None:
        self.collections[collection_name] = {}
        self.created.append(collection_name)

    def retrieve(self, collection_name: str, ids: list[str], **_: Any) -> list[Any]:
        col = self.collections[collection_name]
        return [SimpleNamespace(id=i, payload=dict(col[i]["payload"])) for i in ids if i in col]

    def upsert(self, collection_name: str, points: list[_PointStruct]) -> None:
        for p in points:
            self.collections[collection_name][p.id] = {"payload": dict(p.payload), "vector": p.vector}

    def overwrite_payload(self, collection_name: str, payload: dict, points: list[str]) -> None:
        self.payload_rewrites += 1
        for pid in points:
            self.collections[collection_name][pid]["payload"] = dict(payload)

    def scroll(self, collection_name: str, limit: int, offset: Any = None, **_: Any) -> tuple[list[Any], Any]:
        ids = sorted(self.collections[collection_name])
        start = int(offset or 0)
        page = ids[start : start + limit]
        nxt = start + limit if start + limit < len(ids) else None
        points = [SimpleNamespace(id=i, payload=self.collections[collection_name][i]["payload"]) for i in page]
        return points, nxt

    def delete(self, collection_name: str, points_selector: _PointIdsList) -> None:
        for pid in points_selector.points:
            self.collections[collection_name].pop(pid, None)


def _row(code: str, description: str, rate: str = "10.00", unit: str = "m2") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        code=code,
        description=description,
        unit=unit,
        rate=rate,
        currency="EUR",
        classification={"section": "Opere murarie"},
    )


class _Env:
    """Rows in the "database", the fake store, and the encoder's call log."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.store = _Store()
        self.encoded: list[str] = []
        self.fail_after: int | None = None

        async def fetch_page(_factory: Any, _region: str, last_id: Any) -> list[Any]:
            ordered = sorted(self.rows, key=lambda r: r.id)
            if last_id is not None:
                ordered = [r for r in ordered if r.id > last_id]
            return ordered[: match_index.PAGE_SIZE]

        def encode(texts: list[str]) -> dict[str, Any]:
            if self.fail_after is not None and len(self.encoded) >= self.fail_after:
                raise RuntimeError("CWICR encoder unavailable: the [semantic] extra is not installed.")
            self.encoded.extend(texts)
            return {"dense": [[0.1, 0.2, 0.3] for _ in texts], "sparse": [None for _ in texts]}

        monkeypatch.setattr(match_index, "_fetch_page", fetch_page)
        monkeypatch.setattr(match_index, "_models", lambda: _MODELS)
        monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: self.store)
        monkeypatch.setattr(qdrant_adapter, "_encode", encode)

    def points(self, region: str) -> dict[str, dict]:
        return self.store.collections.get(match_index.collection_for_region(region), {})


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    match_index.reset_state()
    yield
    match_index.reset_state()


_REGION = "Prezzario Lazio 2024"


def _job(region: str = _REGION) -> IndexJob:
    return IndexJob(region=region, language="it", country="IT")


# ── Naming and routing ────────────────────────────────────────────────────


def test_collection_name_is_stable_and_outside_the_cwicr_family() -> None:
    name = match_index.collection_for_region(_REGION)
    assert name == match_index.collection_for_region(f"  {_REGION} ")
    assert name != match_index.collection_for_region("Prezzario Veneto 2024")
    # Not ``cwicr_*`` (the language fallback picks from those) and no ``_v``
    # that the adapter's versioned-name retry could cut.
    assert name.startswith("oecat_")
    assert "_v" not in name


def test_an_indexed_catalogue_routes_to_its_own_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    region = "IT_LAZIO_2024"
    name = match_index.collection_for_region(region)
    monkeypatch.setattr(qdrant_adapter, "_available_cwicr_collections", lambda: frozenset({"cwicr_it_v3"}))
    monkeypatch.setattr(qdrant_adapter, "_available_custom_collections", frozenset({name}))

    # Outside the caller's scope the catalogue routes as if it had no index.
    assert qdrant_adapter.country_to_collection(region) != name
    assert qdrant_adapter.is_custom_catalogue(region) is False

    token = qdrant_adapter.bind_custom_scope({region})
    try:
        assert qdrant_adapter.country_to_collection(region) == name
        # ``IT`` here is part of a name; pinning it would filter on a field the
        # catalogue's points may not carry.
        assert qdrant_adapter.country_filter_for(region) is None
        assert qdrant_adapter.is_custom_catalogue(region) is True
        assert qdrant_adapter.is_custom_catalogue("IT_ROME") is False
    finally:
        qdrant_adapter.reset_custom_scope(token)


def test_an_unindexed_catalogue_keeps_the_old_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qdrant_adapter, "_available_cwicr_collections", lambda: frozenset({"cwicr_it_v3"}))
    monkeypatch.setattr(qdrant_adapter, "_available_custom_collections", frozenset())
    assert not qdrant_adapter.country_to_collection("IT_ROME").startswith("oecat_")


def test_a_candidate_from_an_imported_catalogue_names_its_cost_item() -> None:
    from app.core.match_service.ranker_qdrant import _hit_to_candidate

    item_id = str(uuid.uuid4())
    hit = qdrant_adapter.QdrantHit(
        rate_code="A.01.001",
        country="IT",
        score=0.8,
        payload={
            "rate_code": "A.01.001",
            "cost_item_id": item_id,
            "description": "Muratura in mattoni pieni",
            "rate_unit": "m3",
            "unit_cost": 312.5,
            "currency": "EUR",
            "source": "catalogue",
        },
    )
    candidate = _hit_to_candidate(hit, None)
    # Confirm and apply-to-BOQ resolve ``CostItem.id``; a rate code there
    # would never price the position.
    assert candidate.id == item_id
    assert candidate.code == "A.01.001"
    assert candidate.unit_rate == pytest.approx(312.5)

    cwicr = qdrant_adapter.QdrantHit(rate_code="KAMA_01", country="DE", score=0.5, payload={"rate_code": "KAMA_01"})
    assert _hit_to_candidate(cwicr, None).id == "KAMA_01"


# ── Indexing ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_second_run_embeds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_row("A.01", "Muratura in mattoni"), _row("A.02", "Intonaco civile")])

    first = _job()
    await match_index.index_catalogue(first, session_factory=object())
    assert first.embedded == 2
    points = env.points(_REGION)
    assert len(points) == 2
    payload = next(iter(points.values()))["payload"]
    assert payload["language"] == "it"
    assert payload["country"] == "IT"
    assert payload["catalogue_region"] == _REGION
    assert payload["is_abstract"] is False
    assert {p["payload"]["cost_item_id"] for p in points.values()} == {str(r.id) for r in env.rows}

    second = _job()
    await match_index.index_catalogue(second, session_factory=object())
    assert second.embedded == 0
    assert second.processed == 2
    assert len(env.encoded) == 2


@pytest.mark.asyncio
async def test_a_new_price_rewrites_the_payload_without_the_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_row("A.01", "Muratura in mattoni", rate="100.00")])
    await match_index.index_catalogue(_job(), session_factory=object())

    env.rows[0].rate = "120.00"
    job = _job()
    await match_index.index_catalogue(job, session_factory=object())

    assert job.embedded == 0
    assert env.store.payload_rewrites == 1
    assert next(iter(env.points(_REGION).values()))["payload"]["unit_cost"] == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_a_new_description_is_embedded_again(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_row("A.01", "Muratura in mattoni")])
    await match_index.index_catalogue(_job(), session_factory=object())

    env.rows[0].description = "Muratura in blocchi di calcestruzzo"
    job = _job()
    await match_index.index_catalogue(job, session_factory=object())
    assert job.embedded == 1


@pytest.mark.asyncio
async def test_a_removed_row_leaves_the_index(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_row("A.01", "Muratura"), _row("A.02", "Intonaco")])
    await match_index.index_catalogue(_job(), session_factory=object())

    gone = env.rows.pop()
    job = _job()
    await match_index.index_catalogue(job, session_factory=object())
    assert job.removed == 1
    assert str(gone.id) not in env.points(_REGION)
    assert len(env.points(_REGION)) == 1


@pytest.mark.asyncio
async def test_an_interrupted_run_resumes_where_it_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(match_index, "ENCODE_BATCH", 2)
    env = _Env(monkeypatch, [_row(f"A.{i:02d}", f"Voce di prezzario {i}") for i in range(5)])
    env.fail_after = 2

    broken = _job()
    with pytest.raises(MatchIndexError) as caught:
        await match_index.index_catalogue(broken, session_factory=object())
    assert caught.value.code == match_index.ERR_EMBEDDER
    assert len(env.points(_REGION)) == 2

    env.fail_after = None
    resumed = _job()
    await match_index.index_catalogue(resumed, session_factory=object())
    # Only the three rows the first run never reached are embedded.
    assert resumed.embedded == 3
    assert len(env.points(_REGION)) == 5


@pytest.mark.asyncio
async def test_an_unavailable_encoder_fails_the_job_with_a_code(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_row("A.01", "Muratura")])
    env.fail_after = 0
    monkeypatch.setattr(match_index, "index_catalogue", _bound(match_index.index_catalogue))

    match_index._jobs[_REGION] = _job()
    match_index._queue.append(_REGION)
    await match_index.run_queue()

    job = match_index.job_for(_REGION)
    assert job is not None
    assert job.status == "failed"
    # The page translates the code; the English sentence never reaches it.
    assert job.error_code == match_index.ERR_EMBEDDER


@pytest.mark.asyncio
async def test_an_empty_catalogue_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _Env(monkeypatch, [])
    with pytest.raises(MatchIndexError) as caught:
        await match_index.index_catalogue(_job(), session_factory=object())
    assert caught.value.code == match_index.ERR_EMPTY


def _bound(fn: Any) -> Any:
    async def run(job: IndexJob) -> None:
        await fn(job, session_factory=object())

    return run


# ── Requesting a run ──────────────────────────────────────────────────────


class _Db:
    """Answers the visibility query: one region, its rows, how many are hidden."""

    def __init__(self, count: int, hidden: int = 0) -> None:
        self.count = count
        self.hidden = hidden

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(all=lambda: [(_REGION, self.count, self.hidden)] if self.count else [])


@pytest.fixture
def ready(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    started: list[int] = []
    monkeypatch.setattr(match_index, "embedder_installed", lambda: True)
    monkeypatch.setattr(match_index, "indexer_enabled", lambda: True)
    monkeypatch.setattr(match_index, "_ensure_running", lambda: started.append(1))
    return started


@pytest.mark.asyncio
async def test_a_request_is_queued_once(ready: list[int]) -> None:
    job = await match_index.request_index(_Db(3), _REGION, "it-IT", "it")
    assert (job.status, job.language, job.country, job.total) == ("queued", "it", "IT", 3)
    again = await match_index.request_index(_Db(3), _REGION, "it", None)
    assert again is job
    assert match_index._queue == [_REGION]
    # Asking again does not queue twice, but it does make sure the queue runs.
    assert len(ready) == 2


@pytest.mark.asyncio
async def test_a_published_catalogue_is_refused(ready: list[int]) -> None:
    from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES

    with pytest.raises(MatchIndexError) as caught:
        await match_index.request_index(_Db(3), CWICR_V3_CATALOGUES[0].region, "en", None)
    assert caught.value.code == match_index.ERR_PUBLISHED
    assert not ready


@pytest.mark.asyncio
async def test_an_unknown_catalogue_is_refused(ready: list[int]) -> None:
    with pytest.raises(MatchIndexError) as caught:
        await match_index.request_index(_Db(0), "Nowhere", "it", None)
    assert (caught.value.code, caught.value.status_code) == (match_index.ERR_NOT_FOUND, 404)


@pytest.mark.asyncio
async def test_a_missing_embedder_is_refused_up_front(ready: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(match_index, "embedder_installed", lambda: False)
    with pytest.raises(MatchIndexError) as caught:
        await match_index.request_index(_Db(3), _REGION, "it", None)
    assert (caught.value.code, caught.value.status_code) == (match_index.ERR_EMBEDDER, 503)
    assert not ready


@pytest.mark.asyncio
async def test_a_switched_off_indexer_is_refused(ready: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(match_index, "indexer_enabled", lambda: False)
    with pytest.raises(MatchIndexError) as caught:
        await match_index.request_index(_Db(3), _REGION, "it", None)
    assert caught.value.code == match_index.ERR_DISABLED


@pytest.mark.asyncio
async def test_a_malformed_language_is_refused(ready: list[int]) -> None:
    with pytest.raises(ValueError, match="language"):
        await match_index.request_index(_Db(3), _REGION, "italiano!", None)


# ── Readiness ─────────────────────────────────────────────────────────────


def _custom(region: str, language: str = "it", country: str = "") -> dict[str, Any]:
    return {"region": region, "language": language, "country": country, "points": 10, "collection": "oecat_x"}


def test_an_indexed_prezzario_is_recommended_for_its_language() -> None:
    from app.modules.match_elements.readiness import recommend_catalogue

    rec = recommend_catalogue("it", ["IT"], {"it"}, [_custom("Prezzario Lazio")])
    assert rec is not None
    assert (rec.region, rec.custom, rec.installed) == ("Prezzario Lazio", True, True)


def test_a_prezzario_in_another_language_is_not_recommended() -> None:
    from app.modules.match_elements.readiness import recommend_catalogue

    rec = recommend_catalogue("it", ["IT"], {"it"}, [_custom("Tarifa Madrid", language="es")])
    assert rec is None or rec.custom is False


def test_a_region_too_long_to_bind_is_not_recommended() -> None:
    from app.modules.match_elements.readiness import recommend_catalogue

    long_name = "Prezzario Regione Lazio edizione 2024 aggiornato"
    assert len(long_name) > match_index.MAX_BINDABLE_REGION
    rec = recommend_catalogue("it", ["IT"], {"it"}, [_custom(long_name)])
    assert rec is None or rec.custom is False


def test_a_prezzario_for_another_country_loses_to_a_published_book_for_this_one() -> None:
    from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES
    from app.modules.match_elements.readiness import recommend_catalogue

    published = next(c for c in CWICR_V3_CATALOGUES if c.available)
    rec = recommend_catalogue(
        published.language,
        [published.country_iso],
        {published.language},
        [_custom("Other book", language=published.language, country="ZZ")],
    )
    assert rec is not None
    assert rec.custom is False


def test_the_indexer_is_off_wherever_the_ranker_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.processes import matching

    allowed = {"cwicr_ranker": False, "match_catalogue_indexer": True}
    monkeypatch.setattr(matching, "matching_model_allowed", lambda pid: allowed[pid])
    assert match_index.indexer_enabled() is False
    allowed["cwicr_ranker"] = True
    assert match_index.indexer_enabled() is True


# ── The registry process ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_encoder_that_cannot_load_fails_the_job_instead_of_leaving_it_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.processes as processes_pkg
    from app.core.processes import InMemoryProcessStore, ProcessRegistry
    from app.core.processes.matching import register_matching_processes

    monkeypatch.delenv("OE_TEST_FAST_STARTUP", raising=False)
    registry = ProcessRegistry(store=InMemoryProcessStore())
    registry.stagger_s = 0
    registry.settle_timeout_s = 30
    await registry.load(fresh_install=lambda: False)
    register_matching_processes(registry)
    monkeypatch.setattr(processes_pkg, "process_registry", registry)
    monkeypatch.setattr(qdrant_adapter, "_client", None)
    monkeypatch.setattr(qdrant_adapter, "_encoder", None)
    monkeypatch.setattr(match_index, "embedder_installed", lambda: True)

    env = _Env(monkeypatch, [_row("A.01", "Muratura"), _row("A.02", "Intonaco")])
    # The rows come from the fake page reader; keep the app's database (and
    # whatever importing it starts) out of this test.
    monkeypatch.setattr(match_index, "index_catalogue", _bound(match_index.index_catalogue))
    model = {"ok": False}

    def get_encoder() -> object:
        if not model["ok"]:
            raise RuntimeError("CWICR encoder load failed: out of memory")
        qdrant_adapter._encoder = "encoder"
        return "encoder"

    monkeypatch.setattr(qdrant_adapter, "_get_encoder", get_encoder)

    async def settled() -> IndexJob:
        for _ in range(3000):
            job = match_index.job_for(_REGION)
            if job is not None and job.status not in ("queued", "running"):
                return job
            await asyncio.sleep(0.01)
        raise AssertionError(
            f"the job never settled: {match_index.job_for(_REGION)} queue={match_index._queue} tasks={match_index._start_tasks} status={registry.status(match_index.PROCESS_ID)} ranker={registry.status('cwicr_ranker')}"
        )

    try:
        await match_index.request_index(_Db(2), _REGION, "it", None)
        failed = await settled()
        assert failed.status == "failed"
        assert failed.error_code == match_index.ERR_EMBEDDER

        # Once the model loads, asking again indexes the catalogue.
        model["ok"] = True
        await match_index.request_index(_Db(2), _REGION, "it", None)
        done = await settled()
        assert done.status == "done", done.error
        assert len(env.points(_REGION)) == 2
    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_a_catalogue_with_rows_the_caller_cannot_see_is_refused_as_missing(ready: list[int]) -> None:
    # Another user's imported price list: same answer as one that does not
    # exist, so the refusal neither confirms the name nor queues its rows.
    with pytest.raises(match_index.MatchIndexError) as caught:
        await match_index.request_index(_Db(3, hidden=1), _REGION, "it", None)
    assert caught.value.code == match_index.ERR_NOT_FOUND
    assert match_index.job_for(_REGION) is None
    assert ready == []
    assert await match_index.catalogue_overview(_Db(3, hidden=1)) == []
