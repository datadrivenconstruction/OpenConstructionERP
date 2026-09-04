# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Many threads asking for the embedder at once must build exactly one.

``get_embedder`` is a lazy singleton whose construction takes seconds, and it is
reachable from several threads at once: the embedding pool's workers, the
default asyncio executor, any request handler that needs a vector. It used to
check ``_embedder_instance is None`` and then build, with nothing in between, so
every thread that arrived during the build started its own. They all assigned to
the same global and all but the last were discarded, so the work and the memory
were spent for nothing.

The startup path did not merely allow that race, it guaranteed it.
``init_pool`` submits one warm-up job per worker, all at the same instant, and
the comment above them said the parent had already loaded the model via
``maybe_preload_in_process`` - which only runs under ``OE_VECTOR_PRELOAD=1`` and
is off by default. So on a default startup the warm-up jobs were the first
callers, and there were ``min(4, os.cpu_count())`` of them.

Measured on macos-latest in desktop-release run 33841183277: three simultaneous
constructions, three "Loaded sentence-transformers model" lines within 138 ms,
then SIGSEGV before the pool logged itself initialised. The desktop app died on
its second launch, because the first launch seeds and something on that path
loads the model before the pool asks.

These tests prove the race is gone. They cannot prove the crash is gone - only
the macOS gate can say that, because neither the segfault nor the memory
ceiling that may be behind it exists on this machine.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from types import ModuleType
from typing import Any

import pytest

import app.core.embedding_pool as embedding_pool
import app.core.vector as vector

# More than any runner's core count, so the test is not accidentally passing
# because only one thread got scheduled.
CONCURRENT_CALLERS = 6


class _SlowModel:
    """Stands in for ``SentenceTransformer``. Slow on purpose."""

    built = 0
    _counter_lock = threading.Lock()

    def __init__(self, source: str) -> None:
        with _SlowModel._counter_lock:
            _SlowModel.built += 1
        self.source = source
        # Long enough that every other caller is inside get_embedder while this
        # one is still constructing. Without the lock they all build their own.
        time.sleep(0.2)

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]


class _BrokenModel:
    """Stands in for a model that cannot be loaded at all."""

    attempts = 0
    _counter_lock = threading.Lock()

    def __init__(self, source: str) -> None:
        with _BrokenModel._counter_lock:
            _BrokenModel.attempts += 1
        time.sleep(0.05)
        raise RuntimeError("no weights here")


@pytest.fixture
def cold_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cold, hermetic embedder singleton.

    ``reset_embedder`` deliberately refuses to clear a working instance, so the
    globals are set directly. monkeypatch restores them afterwards, which is
    what keeps this test from leaking a fake model into the rest of the run.
    """
    monkeypatch.setattr(vector, "_embedder_instance", None, raising=False)
    monkeypatch.setattr(vector, "_embedder_tried", False, raising=False)
    monkeypatch.setattr(vector, "_active_model_name", None, raising=False)
    monkeypatch.setattr(vector, "_resolve_active_model", lambda: ("a-test-model", 384))
    monkeypatch.setattr(vector, "_candidate_sources", lambda name: [f"local/{name}"])
    _SlowModel.built = 0
    _BrokenModel.attempts = 0


def _install_fake_library(monkeypatch: pytest.MonkeyPatch, model_cls: type) -> None:
    """Put a fake ``sentence_transformers`` where the function-body import looks.

    ``get_embedder`` imports the library inside its own body, so patching an
    attribute on ``app.core.vector`` would never be consulted.
    """
    fake = ModuleType("sentence_transformers")
    fake.SentenceTransformer = model_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake)


def _call_from_threads(count: int) -> list[Any]:
    """Have ``count`` threads call ``get_embedder`` at the same instant."""
    gate = threading.Barrier(count)
    results: list[Any] = [None] * count
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            gate.wait(timeout=10)
            results[index] = vector.get_embedder()
        except BaseException as exc:  # noqa: BLE001 - re-raised by the assertions below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,), name=f"asker-{i}") for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, f"a caller raised: {errors[0]!r}"
    assert not [t for t in threads if t.is_alive()], "a caller never returned"
    return results


def test_six_threads_asking_at_once_build_one_model(cold_singleton: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect, stated as a number. On the previous commit this is 6."""
    _install_fake_library(monkeypatch, _SlowModel)

    results = _call_from_threads(CONCURRENT_CALLERS)

    assert _SlowModel.built == 1, (
        f"{_SlowModel.built} models were built for one singleton; every copy but the last is "
        "discarded, and on macOS the process does not survive doing this three times at once"
    )
    assert all(r is results[0] for r in results), "callers got different objects back"
    assert vector._embedder_instance is results[0]


def test_a_failing_load_is_also_attempted_once(cold_singleton: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other direction, and the one that costs the most when it goes wrong.

    A model that cannot load is the slow case: the primary and then the
    fallback are tried before the failure latch is set, so one cascade is two
    attempts here. Six callers racing meant six cascades, twelve attempts, and
    twelve trips down the download path - which is the behaviour the latch was
    added to stop in the first place.
    """
    _install_fake_library(monkeypatch, _BrokenModel)

    results = _call_from_threads(CONCURRENT_CALLERS)

    assert _BrokenModel.attempts == 2, (
        f"the failing load ran {_BrokenModel.attempts} times; one cascade is 2 (primary, fallback)"
    )
    assert all(r is None for r in results)
    assert vector._embedder_tried is True, "the failure latch was not set"


def test_a_warm_singleton_is_returned_without_taking_the_lock(
    cold_singleton: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The steady state must not serialise. This is why the check is doubled.

    Holding the load lock here stands in for a thread that is loading a
    different model, or for ``reset_embedder`` running. A caller that already
    has an answer must not wait behind it.
    """
    _install_fake_library(monkeypatch, _SlowModel)
    first = vector.get_embedder()
    assert first is not None

    answered = threading.Event()

    def ask() -> None:
        vector.get_embedder()
        answered.set()

    with vector._embedder_load_lock:
        thread = threading.Thread(target=ask, name="warm-asker")
        thread.start()
        assert answered.wait(timeout=5), "a warm caller blocked on the load lock"
    thread.join(timeout=5)


# ── The startup path that turned the race into a certainty ──────────────────


class _StubProcessPool:
    """Enough of an executor for ``init_pool`` to drive, with no processes.

    A real ``ProcessPoolExecutor`` in a unit test would spawn interpreters and
    import the world; the point here is only which jobs get submitted.
    """

    def __init__(self, max_workers: int = 1, initializer: Any = None, **kwargs: Any) -> None:
        self.max_workers = max_workers
        if initializer is not None:
            initializer()

    def submit(self, fn: Any, *args: Any) -> Future:
        future: Future = Future()
        future.set_result(fn(*args))
        return future

    def shutdown(self, **kwargs: Any) -> None:
        return None


@pytest.fixture
def pool_events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the order of everything ``init_pool`` does that matters."""
    events: list[str] = []
    monkeypatch.setattr(embedding_pool, "_pool", None, raising=False)
    monkeypatch.setattr(embedding_pool, "_pool_size", 0, raising=False)
    monkeypatch.setattr(embedding_pool, "_pool_kind", "", raising=False)
    monkeypatch.setattr(embedding_pool, "encode_in_worker", lambda texts: events.append("job") or [])
    monkeypatch.setattr(embedding_pool, "_warm_worker", lambda: events.append("worker-init"))
    monkeypatch.setattr(vector, "get_embedder", lambda: events.append("parent-load") or object())
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "3")
    return events


def test_the_thread_pool_loads_the_model_before_it_submits_anything(
    pool_events: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the previous commit ``parent-load`` never happens at all.

    Three jobs then arrived at a cold singleton simultaneously, which is the
    stampede the macOS build died in.
    """
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "thread")

    workers = embedding_pool.init_pool()

    assert workers == 3
    assert pool_events[0] == "parent-load", f"the pool submitted work before loading the model: {pool_events}"
    assert pool_events.count("parent-load") == 1
    assert pool_events.count("job") == 3, "one warm-up per worker thread, as before"

    embedding_pool.shutdown_pool()


def test_the_process_pool_is_left_alone(pool_events: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The control, and it must keep passing.

    Process workers each hold their own model and load it in their own
    initialiser, so warming the parent would load a model the parent has no use
    for. Nothing about that path changed.
    """
    monkeypatch.setenv("OE_VECTOR_POOL_KIND", "process")
    monkeypatch.setattr(embedding_pool, "ProcessPoolExecutor", _StubProcessPool)

    workers = embedding_pool.init_pool()

    assert workers == 3
    assert "parent-load" not in pool_events, "the parent loaded a model only the workers need"
    assert pool_events.count("worker-init") == 1, "the stub runs the initialiser once"
    assert pool_events.count("job") == 6, "size * 2 jobs, as before"

    embedding_pool.shutdown_pool()
