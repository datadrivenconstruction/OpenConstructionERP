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
