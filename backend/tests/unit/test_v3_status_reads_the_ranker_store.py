"""``/vector/v3-status/`` answers about the store the ranker actually opens.

The endpoint assembled its answer from two different servers. The collection
NAME came from ``country_to_collection``, which is CWICR naming, but
``engine``, ``connected`` and the collection probe all came from the general
vector store. On a default install those are not the same place: the ranker
opens the embedded CWICR store while the general store resolves to
``http://localhost:6333``. So a catalogue that was installed and matching
perfectly well could be reported ``disconnected`` or ``missing``.

That is why the central test here does not mock a client and read back the
return value. Doing so proves the handler can format a payload, not that it
asked the right server. These tests set the two stores to DISAGREE - the
general one unreachable, the CWICR one holding the collection - and assert
the answer follows the CWICR one. Under the old code the general store's
verdict arrived first and the handler returned before ever looking at the
collection, so every one of them fails.

The second defect was a confident answer produced without looking: when
``get_collection`` raised, the handler set the band to ``ready``. "Could not
read it" was reported with the one word that means "go ahead". There is now a
third outcome, ``unreadable``, distinct from both ``missing`` and ``ready``,
and it carries a reason.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.modules.costs.router import vector_v3_status

DE_COLLECTION = "cwicr_de_v3"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["get_collections", "get_collection", "count"])
async def test_health_progresses_during_status_reads(monkeypatch, stage):
    from app.modules.costs import qdrant_adapter

    started, release = threading.Event(), threading.Event()
    released_by_health = []
    threads = []
    loop_thread = threading.get_ident()
    initialization_threads = []

    class Client:
        def record(self, name):
            threads.append(threading.get_ident())
            if name == stage:
                started.set()
                released_by_health.append(release.wait(5))

        def get_collections(self):
            self.record("get_collections")
            return _Collections([DE_COLLECTION])

        def get_collection(self, name):
            self.record("get_collection")
            return type("Info", (), {"points_count": None})()

        def count(self, name):
            self.record("count")
            return type("Count", (), {"count": 7})()

    monkeypatch.setattr(qdrant_adapter, "get_settings", lambda: _settings(cwicr_qdrant_url="http://qdrant.invalid"))
    def get_client():
        initialization_threads.append(threading.get_ident())
        return Client()

    monkeypatch.setattr(qdrant_adapter, "_get_client", get_client)
    monkeypatch.setattr(qdrant_adapter, "country_to_collection", lambda country: DE_COLLECTION)
    app = FastAPI()

    @app.get("/status")
    async def status():
        return await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    @app.get("/health")
    async def health():
        release.set()
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = asyncio.create_task(client.get("/status"))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert (await client.get("/health")).json() == {"ok": True}
            payload = (await pending).json()
            assert payload["status_band"] == "ready"
            assert payload["points_count"] == 7
            assert released_by_health == [True]
            assert len(set(threads)) == 1
            assert threads[0] != loop_thread
            assert initialization_threads == [loop_thread]
        finally:
            release.set()
            await pending


def _settings(**kw: Any) -> Settings:
    """Class defaults, never the developer's ``backend/.env``.

    ``backend/.env`` sets ``CWICR_QDRANT_URL`` on this machine, which would
    quietly turn the default-install case into the configured-server case and
    make these tests describe the machine instead of the product.
    """
    return Settings(_env_file=None, **kw)


class _Collection:
    def __init__(self, name: str) -> None:
        self.name = name


class _Collections:
    def __init__(self, names: list[str]) -> None:
        self.collections = [_Collection(n) for n in names]


class _RecordingClient:
    """A Qdrant stand-in that remembers what was asked of it."""

    def __init__(self, names: list[str], points: int | None = 7, readable: bool = True) -> None:
        self._names = names
        self._points = points
        self._readable = readable
        self.calls: list[str] = []

    def get_collections(self) -> _Collections:
        self.calls.append("get_collections")
        return _Collections(self._names)

    def get_collection(self, name: str) -> Any:
        self.calls.append(f"get_collection:{name}")
        if not self._readable:
            raise TimeoutError("collection read timed out")
        return type("Info", (), {"points_count": self._points})()

    def count(self, name: str) -> Any:
        self.calls.append(f"count:{name}")
        return type("C", (), {"count": self._points or 0})()


class _UnreachableClient:
    def get_collections(self) -> _Collections:
        raise ConnectionError("connection refused")


@pytest.fixture
def two_disagreeing_stores(monkeypatch: pytest.MonkeyPatch):
    """The default install: general store down, CWICR store holding the data.

    Returns the CWICR recorder plus a list that stays empty for as long as
    nothing reaches for the general store's client.
    """
    from app.core import vector as vector_module
    from app.modules.costs import qdrant_adapter

    cwicr = _RecordingClient([DE_COLLECTION], points=1234)
    general_reached: list[str] = []

    def _general_client():
        general_reached.append("_get_qdrant")
        return _UnreachableClient()

    def _general_status() -> dict[str, Any]:
        general_reached.append("vector_status")
        return {"engine": "qdrant", "connected": False, "error": "Qdrant not available"}

    monkeypatch.setattr(qdrant_adapter, "get_settings", _settings)
    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: cwicr)
    monkeypatch.setattr(vector_module, "_get_qdrant", _general_client)
    monkeypatch.setattr(vector_module, "vector_status", _general_status)
    return cwicr, general_reached


@pytest.mark.asyncio
async def test_an_installed_catalogue_is_not_reported_missing_on_a_default_install(
    two_disagreeing_stores,
) -> None:
    """The symptom, stated as the two stores disagreeing.

    Matching works, because the ranker opens the CWICR store and the
    collection is there with 1234 points. The general store is down. The
    endpoint has to report what the ranker sees.
    """
    cwicr, _ = two_disagreeing_stores

    payload = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert payload["status_band"] == "ready"
    assert payload["exists"] is True
    assert payload["points_count"] == 1234
    assert payload["collection"] == DE_COLLECTION
    assert "get_collections" in cwicr.calls


@pytest.mark.asyncio
async def test_the_general_store_is_never_consulted(two_disagreeing_stores) -> None:
    """Not one field may come from the other server.

    The strongest form of the claim, and the one a return-value assertion
    cannot make: the general store's client and its status function are both
    booby-trapped, and neither is touched.
    """
    _, general_reached = two_disagreeing_stores

    await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert general_reached == []


@pytest.mark.asyncio
async def test_connected_describes_the_cwicr_store(two_disagreeing_stores) -> None:
    """``connected`` answers for the store the rest of the payload is about.

    It used to be copied from the general store's status, so it could report
    False while the collection it sits beside was present and readable.
    """
    payload = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert payload["connected"] is True


@pytest.mark.asyncio
async def test_a_lancedb_general_backend_no_longer_suppresses_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VECTOR_BACKEND says nothing about the CWICR store.

    The old ``non_qdrant`` band gated the probe on the general store's
    engine, so a LanceDB install was told the v3 layout did not apply while
    its CWICR collections sat there working.
    """
    from app.core import vector as vector_module
    from app.modules.costs import qdrant_adapter

    cwicr = _RecordingClient([DE_COLLECTION], points=5)
    monkeypatch.setattr(qdrant_adapter, "get_settings", _settings)
    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: cwicr)
    monkeypatch.setattr(vector_module, "vector_status", lambda: {"engine": "lancedb", "connected": True})

    payload = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert payload["status_band"] == "ready"
    assert payload["engine"] in {"qdrant", "qdrant-embedded"}


@pytest.mark.asyncio
async def test_an_unreadable_collection_is_not_reported_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collection we could not read is not a collection that is ready.

    This is the exact line that was there before: ``except Exception:
    payload["status_band"] = "ready"``. The band that means "go ahead" was
    the one produced by failing to look.
    """
    from app.modules.costs import qdrant_adapter

    cwicr = _RecordingClient([DE_COLLECTION], readable=False)
    monkeypatch.setattr(qdrant_adapter, "get_settings", _settings)
    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: cwicr)

    payload = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert payload["status_band"] != "ready"
    assert payload["status_band"] == "unreadable"
    assert payload["points_count"] == 0
    assert payload["error"]


@pytest.mark.asyncio
async def test_unreadable_is_distinguishable_from_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three outcomes, not two.

    "It is not there" and "we could not look" are different facts and a
    caller must be able to act on them differently. Asserting the two bands
    differ is what stops a later simplification from folding one into the
    other.
    """
    from app.modules.costs import qdrant_adapter

    monkeypatch.setattr(qdrant_adapter, "get_settings", _settings)

    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: _RecordingClient([DE_COLLECTION], readable=False))
    unreadable = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: _RecordingClient(["cwicr_fr_v3"]))
    missing = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert unreadable["status_band"] == "unreadable"
    assert missing["status_band"] == "missing"
    assert unreadable["status_band"] != missing["status_band"]
    assert unreadable["exists"] is True
    assert missing["exists"] is False


@pytest.mark.asyncio
async def test_an_unreachable_store_says_so_and_carries_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreachable is reported as unreachable, with a cause attached.

    A band that means "we could not look" is only actionable if it says why,
    otherwise the operator is back to guessing which of the two stores is
    down.
    """
    from app.modules.costs import qdrant_adapter

    monkeypatch.setattr(qdrant_adapter, "get_settings", _settings)
    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: _UnreachableClient())

    payload = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert payload["status_band"] == "disconnected"
    assert payload["connected"] is False
    assert "ConnectionError" in payload["error"]


@pytest.mark.asyncio
async def test_the_failure_reason_does_not_leak_the_store_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason names the failure class, never the address.

    This endpoint answers anonymous callers - the IDOR tests in
    tests/modules/test_costs_security.py pin that the engine-status portion
    stays public. An error string carrying the resolved URL or the on-disk
    path would hand an unauthenticated caller a piece of the deployment.
    """
    from app.modules.costs import qdrant_adapter

    url = "http://cwicr-internal.example:6333"
    monkeypatch.setattr(qdrant_adapter, "get_settings", lambda: _settings(cwicr_qdrant_url=url))

    def _leaky() -> Any:
        raise ConnectionError(f"failed to connect to {url}")

    monkeypatch.setattr(qdrant_adapter, "_get_client", _leaky)

    payload = await vector_v3_status(db=None, user=None, country="DE", project_id=None)

    assert payload["status_band"] == "disconnected"
    assert url not in payload["error"]
    assert "cwicr-internal.example" not in payload["error"]


@pytest.mark.asyncio
async def test_no_country_still_means_the_store_was_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reachability probe runs before the no_country shortcut.

    Otherwise that band would quietly stop carrying the one thing it has
    always implied, which is that the store answered.
    """
    from app.modules.costs import qdrant_adapter

    monkeypatch.setattr(qdrant_adapter, "get_settings", _settings)
    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: _RecordingClient([DE_COLLECTION]))

    payload = await vector_v3_status(db=None, user=None, country="", project_id=None)

    assert payload["status_band"] == "no_country"
    assert payload["connected"] is True
