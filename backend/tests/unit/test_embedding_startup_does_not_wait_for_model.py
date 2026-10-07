"""A stalled optional encoder must not prevent the HTTP server from starting."""

import asyncio
import threading
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from app.core import embedding_pool, vector
from app.main import _start_embedding_pool_warmup


@pytest.mark.asyncio
@pytest.mark.parametrize(("workers", "preload"), [(2, "0"), (2, "1"), (0, "1")])
async def test_http_ready_while_encoder_load_is_stalled(monkeypatch, workers, preload):
    embedding_pool.reset_for_tests()
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", str(workers))
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "thread")
    monkeypatch.setenv("OE_VECTOR_PRELOAD", preload)
    monkeypatch.delenv("OE_TEST_FAST_STARTUP", raising=False)
    started = threading.Event()
    release = threading.Event()
    load_threads = []

    def slow_model():
        load_threads.append(threading.get_ident())
        started.set()
        assert release.wait(5), "startup waited for the encoder instead of serving HTTP"
        return

    monkeypatch.setattr(vector, "get_embedder", slow_model)
    monkeypatch.setattr(embedding_pool, "encode_in_worker", lambda texts: [])
    task = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal task
        task = _start_embedding_pool_warmup()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    try:
        async with app.router.lifespan_context(app):
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)
            assert not task.done()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                response = await asyncio.wait_for(client.get("/health"), timeout=1)
            assert response.json() == {"status": "ok"}
            assert not release.is_set()
            assert all(ident != threading.get_ident() for ident in load_threads)
    finally:
        release.set()
        if task is not None:
            await asyncio.wait_for(task, timeout=2)
        embedding_pool.reset_for_tests()


@pytest.mark.asyncio
async def test_failed_background_preload_does_not_fail_startup(monkeypatch):
    embedding_pool.reset_for_tests()
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "0")

    def broken_preload():
        raise RuntimeError("unavailable model")

    monkeypatch.setattr(embedding_pool, "maybe_preload_in_process", broken_preload)
    task = _start_embedding_pool_warmup()
    await asyncio.wait_for(task, timeout=2)
    assert task.exception() is None
