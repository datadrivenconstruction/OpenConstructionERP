"""Performance contract for the BIM Hub model list endpoint.

The list endpoint used to issue an ``asyncio.gather`` of
``compute_artifact_size_bytes`` + ``has_original_cad`` + ``find_geometry_key``
probes per model — 3-5 storage round-trips per row, or 150-250 HEAD
requests for a 50-model page on S3 (classic N+1 against storage).

This module pins two contracts:

1. The bulk ``StorageBackend.list_prefix`` primitive returns one entry
   per file under the given prefix, in a *single* backend operation.
2. ``bulk_model_storage_summary`` uses that single operation to fill in
   artifact size / original presence / geometry presence for every
   model under a project — regardless of how many models exist.

A counting fake backend asserts the round-trip budget so future
refactors can't silently regress.
"""

from __future__ import annotations

import uuid

import pytest

from app.core import storage as storage_module
from app.core.storage import LocalStorageBackend, StorageBackend
from app.modules.bim_hub import file_storage as bim_file_storage

# ──────────────────────────────────────────────────────────────────────────
# Fake counting backend — counts every method invocation so the test can
# assert the bulk path issues *exactly one* list_prefix call and zero
# per-key exists/size probes.
# ──────────────────────────────────────────────────────────────────────────


class CountingStorageBackend(StorageBackend):
    """In-memory storage backend that tallies every method call.

    Used by the perf test to assert the BIM list endpoint reaches into
    storage exactly once via ``list_prefix`` instead of fanning out
    ``exists`` / ``size`` probes per model row.
    """

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self.calls: dict[str, int] = {
            "list_prefix": 0,
            "exists": 0,
            "size": 0,
            "put": 0,
            "get": 0,
            "delete": 0,
            "delete_prefix": 0,
        }

    # -- writes (used only by test setup) --

    async def put(self, key: str, content: bytes) -> None:
        self.calls["put"] += 1
        self._blobs[key] = content

    async def get(self, key: str) -> bytes:
        self.calls["get"] += 1
        if key not in self._blobs:
            raise FileNotFoundError(key)
        return self._blobs[key]

    async def exists(self, key: str) -> bool:
        self.calls["exists"] += 1
        return key in self._blobs

    async def delete(self, key: str) -> None:
        self.calls["delete"] += 1
        self._blobs.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        self.calls["delete_prefix"] += 1
        removed = [k for k in self._blobs if k.startswith(prefix)]
        for k in removed:
            del self._blobs[k]
        return len(removed)

    async def size(self, key: str) -> int:
        self.calls["size"] += 1
        if key not in self._blobs:
            raise FileNotFoundError(key)
        return len(self._blobs[key])

    async def list_prefix(self, prefix: str) -> list[tuple[str, int]]:
        self.calls["list_prefix"] += 1
        return [(key, len(blob)) for key, blob in self._blobs.items() if key.startswith(prefix)]


@pytest.fixture
def counting_backend(monkeypatch: pytest.MonkeyPatch) -> CountingStorageBackend:
    """Swap the storage singleton for an instance the test can inspect."""
    backend = CountingStorageBackend()

    # The cached factory is what the rest of the code calls — point it
    # at the fake.  Reset the lru_cache before AND after the test so a
    # subsequent test sees the real backend again.
    real_get = storage_module.get_storage_backend
    real_get.cache_clear()
    monkeypatch.setattr(
        storage_module,
        "get_storage_backend",
        lambda: backend,
    )
    # ``bim_file_storage`` calls ``_backend()`` which itself calls
    # ``get_storage_backend()`` — make sure we patch the symbol it sees.
    monkeypatch.setattr(
        bim_file_storage,
        "get_storage_backend",
        lambda: backend,
    )
    yield backend
    # monkeypatch's own teardown restores the original symbol; just
    # clear the lru_cache so the real factory rebuilds its singleton
    # against whatever the next test wants.
    real_get.cache_clear()


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_prefix_supported_for_local_backend(tmp_path) -> None:
    """LocalStorageBackend MUST implement list_prefix (the bulk path)."""
    backend = LocalStorageBackend(tmp_path)
    # New row in storage layout; confirm list_prefix returns it via a
    # single roundtrip.
    await backend.put("bim/p/m/geometry.glb", b"hello")
    entries = await backend.list_prefix("bim/p/m")
    keys = sorted(k for k, _ in entries)
    assert "bim/p/m/geometry.glb" in keys


@pytest.mark.asyncio
async def test_list_prefix_supported_capability_flag(
    counting_backend: CountingStorageBackend,
) -> None:
    """list_prefix_supported MUST return True for any backend that
    overrides the abstract default."""
    assert bim_file_storage.list_prefix_supported() is True


@pytest.mark.asyncio
async def test_bulk_summary_issues_single_list_prefix_call(
    counting_backend: CountingStorageBackend,
) -> None:
    """The perf-critical contract.

    Seed 50 models, each with a geometry.glb + an original.ifc, then
    call bulk_model_storage_summary and assert exactly ONE list_prefix
    call hit storage and ZERO per-key exists/size probes were issued.
    """
    project_id = uuid.uuid4()
    model_ids = [uuid.uuid4() for _ in range(50)]
    for mid in model_ids:
        await counting_backend.put(
            f"bim/{project_id}/{mid}/geometry.glb",
            b"GLB-bytes-" + str(mid).encode(),
        )
        await counting_backend.put(
            f"bim/{project_id}/{mid}/original.ifc",
            b"IFC-bytes-" + str(mid).encode(),
        )

    # Reset call counters after the seed writes — only probes from the
    # summary call count toward the budget.
    counting_backend.calls = dict.fromkeys(counting_backend.calls, 0)

    summary = await bim_file_storage.bulk_model_storage_summary(project_id)

    # Performance contract: exactly one backend round-trip, no fan-out.
    assert counting_backend.calls["list_prefix"] == 1, (
        f"Expected exactly 1 list_prefix call for 50-model page, "
        f"got {counting_backend.calls['list_prefix']}. The bulk path "
        f"regressed — list_models is back to per-model probes."
    )
    assert counting_backend.calls["exists"] == 0
    assert counting_backend.calls["size"] == 0
    assert counting_backend.calls["get"] == 0

    # Functional contract: every model resolved with correct shape.
    assert len(summary) == 50
    for mid in model_ids:
        info = summary[str(mid)]
        assert info["has_original"] is True
        # Artifact bytes = len("GLB-bytes-<uuid>")
        assert int(info["artifact_size_bytes"]) > 0  # type: ignore[arg-type]
        assert int(info["original_size_bytes"]) > 0  # type: ignore[arg-type]
        assert ".glb" in info["geometry_exts"]  # type: ignore[operator]


@pytest.mark.asyncio
async def test_bulk_summary_one_call_regardless_of_page_size(
    counting_backend: CountingStorageBackend,
) -> None:
    """Whether the page is 10 or 150 models, the bulk path costs 1 call."""
    for page_size in (10, 50, 150):
        # Wipe the backend between page sizes.
        counting_backend._blobs.clear()
        counting_backend.calls = dict.fromkeys(counting_backend.calls, 0)

        project_id = uuid.uuid4()
        for _ in range(page_size):
            mid = uuid.uuid4()
            await counting_backend.put(
                f"bim/{project_id}/{mid}/geometry.glb",
                b"glb",
            )
        # Reset again after the put fan-out.
        counting_backend.calls = dict.fromkeys(counting_backend.calls, 0)

        summary = await bim_file_storage.bulk_model_storage_summary(project_id)
        assert len(summary) == page_size
        assert counting_backend.calls["list_prefix"] == 1
        assert counting_backend.calls["exists"] == 0
        assert counting_backend.calls["size"] == 0


@pytest.mark.asyncio
async def test_bulk_summary_handles_empty_project(
    counting_backend: CountingStorageBackend,
) -> None:
    """A project with zero models -> empty dict, still 1 list_prefix call."""
    project_id = uuid.uuid4()
    summary = await bim_file_storage.bulk_model_storage_summary(project_id)
    assert summary == {}
    assert counting_backend.calls["list_prefix"] == 1


@pytest.mark.asyncio
async def test_bulk_summary_falls_back_when_list_prefix_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Community backends without list_prefix get the abstract base's
    NotImplementedError — bulk_model_storage_summary returns {} so the
    caller can fall back to per-model probes."""

    class LegacyBackend(StorageBackend):
        async def put(self, key: str, content: bytes) -> None:
            return

        async def get(self, key: str) -> bytes:
            raise FileNotFoundError(key)

        async def exists(self, key: str) -> bool:
            return False

        async def delete(self, key: str) -> None:
            return

        async def delete_prefix(self, prefix: str) -> int:
            return 0

        async def size(self, key: str) -> int:
            raise FileNotFoundError(key)

    real_get = storage_module.get_storage_backend
    real_get.cache_clear()
    backend = LegacyBackend()
    monkeypatch.setattr(storage_module, "get_storage_backend", lambda: backend)
    monkeypatch.setattr(bim_file_storage, "get_storage_backend", lambda: backend)

    summary = await bim_file_storage.bulk_model_storage_summary(uuid.uuid4())
    assert summary == {}
    assert bim_file_storage.list_prefix_supported() is False
    real_get.cache_clear()


@pytest.mark.asyncio
async def test_bulk_summary_separates_artifacts_from_originals(
    counting_backend: CountingStorageBackend,
) -> None:
    """``original.*`` MUST count toward original_size_bytes only;
    everything else MUST count toward artifact_size_bytes."""
    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    await counting_backend.put(
        f"bim/{project_id}/{model_id}/geometry.glb",
        b"X" * 100,
    )
    await counting_backend.put(
        f"bim/{project_id}/{model_id}/thumb.png",
        b"Y" * 30,
    )
    await counting_backend.put(
        f"bim/{project_id}/{model_id}/original.ifc",
        b"Z" * 200,
    )

    counting_backend.calls = dict.fromkeys(counting_backend.calls, 0)
    summary = await bim_file_storage.bulk_model_storage_summary(project_id)

    info = summary[str(model_id)]
    assert info["artifact_size_bytes"] == 100 + 30
    assert info["original_size_bytes"] == 200
    assert info["has_original"] is True
    assert ".glb" in info["geometry_exts"]  # type: ignore[operator]
    assert counting_backend.calls["list_prefix"] == 1
