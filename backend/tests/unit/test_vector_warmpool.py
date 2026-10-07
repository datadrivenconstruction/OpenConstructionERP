# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the embedding warm-pool (Phase-4 perf fix).

These exercise the pool wiring without spinning up real torch — the
``encode_texts`` import inside the worker is stubbed by setting
``OE_VECTOR_POOL_WORKERS=0`` so we just verify the dispatch helpers,
fallback path, and lifecycle.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.core import embedding_pool


def test_executor_creation_does_not_wait_for_slow_model_when_warmup_disabled(monkeypatch):
    from app.core import vector

    embedding_pool.reset_for_tests()
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "1")
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "thread")
    loading = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    results = []

    def slow_load():
        loading.set()
        release.wait(timeout=10)

    def construct():
        results.append(embedding_pool.init_pool(warmup=False))
        returned.set()

    monkeypatch.setattr(vector, "get_embedder", slow_load)
    worker = threading.Thread(target=construct, daemon=True)
    try:
        worker.start()
        assert returned.wait(timeout=5), "executor construction waited for the blocked model loader"
        assert not loading.is_set()
        assert results == [1]
        assert embedding_pool.get_pool() is not None
    finally:
        release.set()
        worker.join(timeout=5)
        embedding_pool.shutdown_pool()


@pytest.mark.parametrize("replace", [False, True])
def test_shutdown_during_parent_load_cannot_submit_or_republish_pool(monkeypatch, replace):
    from app.core import vector

    embedding_pool.reset_for_tests()
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "1")
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "thread")
    loading = threading.Event()
    release = threading.Event()
    submitted = []
    results = []

    def slow_load():
        loading.set()
        release.wait(timeout=10)

    monkeypatch.setattr(vector, "get_embedder", slow_load)
    monkeypatch.setattr(embedding_pool, "encode_in_worker", lambda texts: submitted.append(texts) or [])
    embedding_pool.init_pool(warmup=False)
    old_pool = embedding_pool.get_pool()
    original_submit = old_pool.submit

    def track_submit(*args, **kwargs):
        submitted.append("submit")
        return original_submit(*args, **kwargs)

    monkeypatch.setattr(old_pool, "submit", track_submit)
    worker = threading.Thread(target=lambda: results.append(embedding_pool.warm_pool()), daemon=True)
    try:
        worker.start()
        assert loading.wait(timeout=5)
        embedding_pool.shutdown_pool()
        replacement = None
        if replace:
            embedding_pool.init_pool(warmup=False)
            replacement = embedding_pool.get_pool()
            assert replacement is not old_pool
        release.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert results == [False]
        assert submitted == []
        assert embedding_pool.get_pool() is replacement
        assert embedding_pool.pool_size() == (1 if replace else 0)
    finally:
        release.set()
        worker.join(timeout=5)
        embedding_pool.shutdown_pool()


def test_warm_after_shutdown_never_loads_a_model_or_recreates_executor(monkeypatch):
    from app.core import vector

    embedding_pool.reset_for_tests()
    calls = []
    monkeypatch.setattr(vector, "get_embedder", lambda: calls.append("load"))
    assert embedding_pool.warm_pool() is False
    assert embedding_pool.get_pool() is None
    assert calls == []


def test_wrong_expected_pool_returns_without_model_load_or_jobs(monkeypatch):
    from app.core import vector

    embedding_pool.reset_for_tests()
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "1")
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "thread")
    calls = []
    monkeypatch.setattr(vector, "get_embedder", lambda: calls.append("load"))
    embedding_pool.init_pool(warmup=False)
    old_pool = embedding_pool.get_pool()
    embedding_pool.shutdown_pool()
    embedding_pool.init_pool(warmup=False)
    replacement = embedding_pool.get_pool()
    monkeypatch.setattr(replacement, "submit", lambda *args, **kwargs: calls.append("submit"))
    try:
        assert embedding_pool.warm_pool(expected_pool=old_pool) is False
        assert calls == []
        assert embedding_pool.get_pool() is replacement
        assert embedding_pool.pool_size() == 1
    finally:
        embedding_pool.shutdown_pool()


# ── Pool size resolution ────────────────────────────────────────────────


def test_resolve_pool_size_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default = min(4, cpu_count()), capped at 4."""
    monkeypatch.delenv("OE_VECTOR_POOL_WORKERS", raising=False)
    n = embedding_pool._resolve_pool_size()
    assert 1 <= n <= 4


def test_resolve_pool_kind_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default kind is 'thread' — process pool is opt-in."""
    monkeypatch.delenv("OE_VECTOR_POOL_KIND", raising=False)
    assert embedding_pool._resolve_pool_kind() == "thread"


def test_resolve_pool_kind_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "process")
    assert embedding_pool._resolve_pool_kind() == "process"


def test_resolve_pool_kind_invalid_falls_back_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "fork")
    assert embedding_pool._resolve_pool_kind() == "thread"


def test_resolve_pool_size_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env var explicitly sets the worker count."""
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "2")
    assert embedding_pool._resolve_pool_size() == 2


def test_resolve_pool_size_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """OE_VECTOR_POOL_WORKERS=0 → pool disabled."""
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "0")
    assert embedding_pool._resolve_pool_size() == 0


def test_resolve_pool_size_invalid_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage env var falls back to default."""
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "not-a-number")
    n = embedding_pool._resolve_pool_size()
    assert 1 <= n <= 4


# ── init / shutdown lifecycle ───────────────────────────────────────────


def test_init_pool_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_pool returns 0 and leaves _pool=None when disabled."""
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "0")
    embedding_pool.reset_for_tests()
    assert embedding_pool.init_pool() == 0
    assert embedding_pool.get_pool() is None
    assert embedding_pool.pool_size() == 0


def test_init_pool_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_pool called twice returns the same size and doesn't re-create."""
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "0")
    embedding_pool.reset_for_tests()
    n1 = embedding_pool.init_pool()
    n2 = embedding_pool.init_pool()
    assert n1 == n2 == 0


def test_shutdown_pool_idempotent() -> None:
    """shutdown_pool() is safe to call when pool is None or already down."""
    embedding_pool.reset_for_tests()
    embedding_pool.shutdown_pool()  # already None
    embedding_pool.shutdown_pool()  # second call still no-op
    assert embedding_pool.get_pool() is None


# ── Pooled dispatch (disabled = None) ───────────────────────────────────


@pytest.mark.asyncio
async def test_encode_texts_pooled_returns_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the pool is down, the helper returns None so caller falls back."""
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "0")
    embedding_pool.reset_for_tests()
    embedding_pool.init_pool()
    result = await embedding_pool.encode_texts_pooled(["hello"])
    assert result is None


# ── Preload ─────────────────────────────────────────────────────────────


def test_maybe_preload_in_process_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without OE_VECTOR_PRELOAD=1, preload is a no-op."""
    monkeypatch.delenv("OE_VECTOR_PRELOAD", raising=False)
    assert embedding_pool.maybe_preload_in_process() is False


def test_maybe_preload_when_no_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """If get_embedder returns None, preload returns False without raising."""
    monkeypatch.setenv("OE_VECTOR_PRELOAD", "1")

    import app.core.vector as vector_mod

    monkeypatch.setattr(vector_mod, "get_embedder", lambda: None)
    assert embedding_pool.maybe_preload_in_process() is False


# ── Single-call latency overhead with mocked embedder ───────────────────


@pytest.mark.asyncio
async def test_encode_texts_async_falls_back_when_pool_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """encode_texts_async: pool=disabled → uses asyncio.to_thread fallback.

    Verifies the in-process thread fallback runs and returns the right
    shape. We monkey-patch the module-level encode_texts to a deterministic
    stub so we don't need a real model on the test machine.
    """
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "0")
    embedding_pool.reset_for_tests()
    embedding_pool.init_pool()

    import app.core.vector as vector_mod

    def _stub_encode(texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(vector_mod, "encode_texts", _stub_encode)
    out = await vector_mod.encode_texts_async(["a", "b"])
    assert out == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_encode_texts_async_empty_input_short_circuits() -> None:
    """Empty list returns [] without invoking the pool or embedder."""
    import app.core.vector as vector_mod

    out = await vector_mod.encode_texts_async([])
    assert out == []


@pytest.mark.asyncio
async def test_single_call_latency_under_200ms_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a stubbed encoder, end-to-end async overhead < 200 ms."""
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "0")
    embedding_pool.reset_for_tests()
    embedding_pool.init_pool()

    import app.core.vector as vector_mod

    monkeypatch.setattr(
        vector_mod,
        "encode_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )

    started = time.perf_counter()
    await vector_mod.encode_texts_async(["query: a single short text"])
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < 200, f"async overhead too high: {elapsed_ms:.1f}ms"


# ── Cleanup hook so tests don't leak state ──────────────────────────────


@pytest.fixture(autouse=True)
def _reset_pool_state() -> None:
    embedding_pool.reset_for_tests()
    yield
    embedding_pool.reset_for_tests()
