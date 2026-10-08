"""The DAE->GLB conversion runs once per distinct input."""

from __future__ import annotations

import asyncio

import pytest

from app.modules.bim_hub import glb_cache


@pytest.fixture(autouse=True)
def _clean():
    glb_cache.clear()
    yield
    glb_cache.clear()


def test_same_bytes_convert_once_even_concurrently() -> None:
    calls: list[bytes] = []

    def convert(data: bytes) -> bytes:
        calls.append(data)
        return b"glb:" + data

    async def run():
        return await asyncio.gather(*(glb_cache.convert_dae_once(b"model-a", convert) for _ in range(5)))

    results = asyncio.run(run())
    assert results == [b"glb:model-a"] * 5
    assert calls == [b"model-a"]


def test_distinct_bytes_convert_separately_and_cache_is_bounded() -> None:
    calls: list[bytes] = []

    def convert(data: bytes) -> bytes:
        calls.append(data)
        return data

    async def run():
        for i in range(glb_cache._MAX_ENTRIES + 2):
            await glb_cache.convert_dae_once(str(i).encode(), convert)
        await glb_cache.convert_dae_once(b"0", convert)

    asyncio.run(run())
    # "0" was evicted, so it converts a second time.
    assert calls.count(b"0") == 2
    assert len(glb_cache._results) == glb_cache._MAX_ENTRIES


def test_exception_is_not_cached() -> None:
    attempts = 0

    def convert(data: bytes) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        return b"ok"

    async def run():
        with pytest.raises(RuntimeError):
            await glb_cache.convert_dae_once(b"x", convert)
        return await glb_cache.convert_dae_once(b"x", convert)

    assert asyncio.run(run()) == b"ok"
    assert attempts == 2


def test_ensure_glb_goes_through_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cache only helps if the service calls it.

    Two showcase models carry the same DAE bytes. Each gets its own GLB saved,
    but trimesh converts once.
    """
    from pathlib import Path

    from app.modules.bim_hub import file_storage, ifc_processor
    from app.modules.bim_hub.service import BIMHubService

    conversions: list[str] = []
    saved: dict[str, bytes] = {}

    async def find_geometry_key(project_id: str, model_id: str, prefer_ext: str = ".glb"):
        if model_id in saved:
            return (f"{model_id}.glb", ".glb")
        return (f"{model_id}.dae", ".dae")

    async def save_geometry(*, project_id: str, model_id: str, ext: str, content: bytes) -> None:
        saved[model_id] = content

    async def read_blob_bytes(self: BIMHubService, key: str) -> bytes:
        return b"<COLLADA>same demo model</COLLADA>"

    def convert_dae_to_glb(dae_path: Path, out_dir: Path) -> Path:
        conversions.append(dae_path.read_text())
        glb = out_dir / "geometry.glb"
        glb.write_bytes(b"glTF-binary")
        return glb

    monkeypatch.setattr(file_storage, "find_geometry_key", find_geometry_key)
    monkeypatch.setattr(file_storage, "save_geometry", save_geometry)
    monkeypatch.setattr(BIMHubService, "_read_blob_bytes", read_blob_bytes)
    monkeypatch.setattr(ifc_processor, "_convert_dae_to_glb", convert_dae_to_glb)

    async def run() -> list[bool]:
        service = BIMHubService(None)  # type: ignore[arg-type]
        return [await service._ensure_glb("proj", mid) for mid in ("model-a", "model-b")]

    assert asyncio.run(run()) == [True, True]
    assert saved == {"model-a": b"glTF-binary", "model-b": b"glTF-binary"}
    assert len(conversions) == 1
