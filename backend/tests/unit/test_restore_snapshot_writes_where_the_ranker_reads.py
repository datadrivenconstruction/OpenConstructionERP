"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A snapshot restore creates the collection on the server it uploads to.

The restore handler used to take its Qdrant client from
``app.core.vector._get_qdrant``, which resolves on ``qdrant_url``, and then
push the snapshot bytes through the CWICR path, which resolves on
``cwicr_qdrant_url``. Wherever those two differ the operator was left with an
empty collection created on the general server, a ``vectors_count`` read back
from that empty collection, and a success message describing a restore the
ranker could not see. Fixed in e0ec5d179; nothing tested it, in either
direction.

What makes this defect awkward to test is that it is invisible to any single
server. Point one client at one recorder and every assertion passes both
before and after the fix, because the calls all land somewhere and the
somewhere is never compared. So these tests set the two stores to DISAGREE -
``QDRANT_URL`` at one host, ``CWICR_QDRANT_URL`` at another - and give each a
separately identifiable client. The question they ask is not "was a collection
created" but "created WHERE, and is that the same place the bytes went".

Both directions are asserted deliberately. A suite of only negative assertions
("the general store was not touched") passes just as happily when the handler
refuses everything and does nothing at all, which is how nineteen dead routes
once counted as healthy here. So the positive half - the collection really is
created on the CWICR server, the loader really is pointed at it, the count
really is read back from it - carries equal weight.

Hermetic by construction, and under ``_no_outbound_http`` without asking for
an exemption: the downloader is replaced by one that writes bytes to the cache
path, ``Path.home`` is redirected into ``tmp_path`` so the real home is never
touched, and the uploader is replaced by a recorder. Nothing here opens a
socket, so there is no transport for that fixture to reject.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import Settings

CWICR_URL = "http://cwicr-host:6333"
GENERAL_URL = "http://general-host:6333"


def _settings(**kw: Any) -> Settings:
    """Class defaults plus the overrides, never the developer's ``backend/.env``.

    That file sets ``CWICR_QDRANT_URL`` on this machine, which would supply the
    very value under test and make these pass by describing the machine.
    """
    return Settings(_env_file=None, **kw)


class _Collection:
    def __init__(self, name: str) -> None:
        self.name = name


class _Collections:
    def __init__(self, names: list[str]) -> None:
        self.collections = [_Collection(n) for n in names]


class _RecordingClient:
    """A Qdrant stand-in that knows which server it is and remembers everything."""

    def __init__(self, url: str, points: int) -> None:
        self.url = url
        self.points = points
        self.calls: list[str] = []
        self.created: list[str] = []

    def get_collections(self) -> _Collections:
        self.calls.append("get_collections")
        return _Collections([])

    def create_collection(self, name: str, **_kw: Any) -> None:
        self.calls.append(f"create_collection:{name}")
        self.created.append(name)

    def get_collection(self, name: str) -> Any:
        self.calls.append(f"get_collection:{name}")
        return type("Info", (), {"points_count": self.points})()

    def count(self, name: str) -> Any:
        self.calls.append(f"count:{name}")
        return type("C", (), {"count": self.points})()


@pytest.fixture
def qdrant_models_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``from qdrant_client.models import ...`` resolve, real or stubbed.

    ``qdrant-client`` ships in the optional ``[semantic-clients]`` extra and is
    absent here. Skipping without it would leave this file silently absent from
    most runs, and a skip inside a green summary reads exactly like a pass. The
    two names are only constructed and handed to the client, never inspected,
    which is what makes standing in for them honest in this test.
    """
    try:
        import qdrant_client.models  # noqa: F401
    except ModuleNotFoundError:
        import sys
        import types

        pkg = types.ModuleType("qdrant_client")
        models = types.ModuleType("qdrant_client.models")
        for name in ("Distance", "VectorParams"):
            setattr(models, name, type(name, (), {"__init__": lambda self, **kw: None, "COSINE": "cosine"}))
        pkg.models = models
        monkeypatch.setitem(sys.modules, "qdrant_client", pkg)
        monkeypatch.setitem(sys.modules, "qdrant_client.models", models)


@pytest.fixture
def two_disagreeing_servers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qdrant_models_available: None):
    """CWICR store on one host, general store on another, both identifiable.

    Returns the two recorders, the list the uploader records into, and the
    db_id under test. The general client is a booby trap: the handler has no
    business resolving it at all, so any call recorded on it is a failure.
    """
    from app.core import vector as vector_module
    from app.modules.costs import qdrant_adapter, qdrant_snapshot_loader
    from app.modules.costs import router as costs_router

    cwicr = _RecordingClient(CWICR_URL, points=4242)
    general = _RecordingClient(GENERAL_URL, points=7)

    settings = _settings(cwicr_qdrant_url=CWICR_URL, qdrant_url=GENERAL_URL)
    monkeypatch.setattr(qdrant_adapter, "get_settings", lambda: settings)
    monkeypatch.setattr(qdrant_adapter, "_get_client", lambda: cwicr)
    monkeypatch.setattr(vector_module, "_get_qdrant", lambda: general)

    # No socket is opened anywhere in this test. The downloader writes the
    # bytes the handler expects to find, straight to the path it asked for.
    def _fake_download(url: str, dest: Path, timeout: float) -> None:
        dest.write_bytes(b"snapshot" * 4096)

    monkeypatch.setattr(costs_router, "_download_to_file", _fake_download)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    uploads: list[dict[str, Any]] = []

    def _fake_restore(**kwargs: Any) -> bool:
        uploads.append(kwargs)
        return True

    monkeypatch.setattr(qdrant_snapshot_loader, "restore_snapshot_file", _fake_restore)

    db_id = sorted(costs_router._GITHUB_SNAPSHOT_FILES)[0]
    return cwicr, general, uploads, db_id


async def _restore(db_id: str) -> dict:
    from app.modules.costs.router import restore_qdrant_snapshot

    return await restore_qdrant_snapshot(db_id=db_id, _user_id="00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
async def test_the_collection_is_created_on_the_cwicr_server(two_disagreeing_servers) -> None:
    """POSITIVE half: the collection appears on the store the ranker opens."""
    cwicr, _general, _uploads, db_id = two_disagreeing_servers

    result = await _restore(db_id)

    assert result["restored"] is True
    assert cwicr.created == [f"cwicr_{db_id.lower()}"], (
        f"the CWICR server did not receive the create; it recorded {cwicr.calls}"
    )


@pytest.mark.asyncio
async def test_the_collection_is_not_created_on_the_general_server(two_disagreeing_servers) -> None:
    """NEGATIVE half: nothing is left behind on the server nobody reads.

    This is the empty collection the operator used to find on the wrong host.
    """
    _cwicr, general, _uploads, db_id = two_disagreeing_servers

    result = await _restore(db_id)

    # A negative assertion on its own cannot tell "went to the right place"
    # from "went nowhere": a handler that rejects the request early leaves the
    # general store just as untouched. So this test states the restore really
    # happened before it says where it did not happen.
    assert result["restored"] is True, "the restore did not run at all, so an untouched general store proves nothing"

    assert general.created == [], f"an empty collection was left on the general server: {general.created}"
    assert general.calls == [], f"the general vector store was consulted at all: {general.calls}"


@pytest.mark.asyncio
async def test_the_upload_goes_to_the_server_that_holds_the_collection(two_disagreeing_servers) -> None:
    """The invariant, stated without naming either host.

    Asserting "created on CWICR" and "uploaded to CWICR" separately would both
    still hold if someone later repointed the pair together at a third place.
    What actually has to be true is that the two are the SAME server, so this
    reads the create off the recorders and compares it to the URL the uploader
    was handed, rather than to a constant.
    """
    cwicr, general, uploads, db_id = two_disagreeing_servers

    await _restore(db_id)

    assert len(uploads) == 1, f"expected exactly one upload, got {len(uploads)}"
    created_on = [c for c in (cwicr, general) if c.created]
    assert len(created_on) == 1, f"the collection was created on {len(created_on)} servers, not one"

    assert uploads[0]["qdrant_url"] == created_on[0].url, (
        f"the snapshot was uploaded to {uploads[0]['qdrant_url']} but the collection was created on "
        f"{created_on[0].url}. Those are different servers, so the upload lands in a collection the "
        "reader never sees and an empty one is left behind on the other host."
    )
    assert uploads[0]["collection_name"] == cwicr.created[0]


@pytest.mark.asyncio
async def test_the_reported_count_comes_from_the_collection_that_was_filled(two_disagreeing_servers) -> None:
    """The success message has to describe the store that received the data.

    The two recorders deliberately hold different counts, 4242 and 7, so a
    number read from the wrong server cannot coincide with the right answer.
    That is what made the old behaviour reportable as success: the count came
    back from a collection that had just been created empty on another host.
    """
    _cwicr, _general, _uploads, db_id = two_disagreeing_servers

    result = await _restore(db_id)

    assert result["vectors_count"] == 4242, (
        f"vectors_count is {result['vectors_count']}; 7 would mean it was read from the general server"
    )
    assert result["collection"] == f"cwicr_{db_id.lower()}"
