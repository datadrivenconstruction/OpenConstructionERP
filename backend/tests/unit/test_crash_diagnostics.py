"""Crash log, memory probe and the memory guards around embedding work."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.core import crash_diagnostics as cd


def test_is_out_of_memory_error_recognises_commit_exhaustion() -> None:
    assert cd.is_out_of_memory_error(MemoryError())
    assert cd.is_out_of_memory_error(
        RuntimeError("The paging file is too small for this operation to complete. (os error 1455)")
    )
    assert not cd.is_out_of_memory_error(OSError("file not found"))
    assert not cd.is_out_of_memory_error(ValueError("bad config"))


def test_memory_snapshot_never_raises_and_formats() -> None:
    snap = cd.memory_snapshot()
    assert isinstance(snap, dict)
    assert isinstance(cd.format_snapshot(snap), str)
    assert cd.format_snapshot({}) == "unavailable"


def test_enable_crash_log_writes_header(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cd, "_crash_file", None)
    monkeypatch.setattr(cd, "_crash_path", None)
    enabled: list[dict] = []
    monkeypatch.setattr(cd.faulthandler, "enable", lambda **kw: enabled.append(kw))
    path = cd.enable_crash_log(tmp_path)
    try:
        assert path == tmp_path / "logs" / "backend-crash.log"
        assert enabled and enabled[0]["all_threads"] is True
        cd.write_crash_note("hello")
        text = path.read_text(encoding="utf-8")
        assert "=== backend start" in text
        assert "hello" in text
        # Idempotent: a second call does not open another file.
        assert cd.enable_crash_log(tmp_path / "other") == path
    finally:
        cd._crash_file.close()


def test_watchdog_dumps_once_per_stall(monkeypatch) -> None:
    dumps: list[int] = []
    monkeypatch.setattr(cd, "_watchdog_thread", None)
    monkeypatch.setattr(cd.faulthandler, "dump_traceback", lambda **kw: dumps.append(1))

    loop = asyncio.new_event_loop()
    runner = threading.Thread(target=loop.run_forever, daemon=True)
    runner.start()
    try:
        assert cd.start_loop_stall_watchdog(loop, threshold_s=0.5, poll_s=0.1)
        time.sleep(0.4)
        assert dumps == []
        # Block the loop the way a GIL-heavy native call would.
        loop.call_soon_threadsafe(time.sleep, 1.5)
        time.sleep(2.0)
        assert dumps == [1]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        runner.join(timeout=5)
        loop.close()


def test_watchdog_never_dumps_one_stall_twice(monkeypatch) -> None:
    """The stall is keyed on the beat it is stuck after, not on poll timing."""
    dumps: list[int] = []
    monkeypatch.setattr(cd, "_watchdog_thread", None)
    monkeypatch.setattr(cd.faulthandler, "dump_traceback", lambda **kw: dumps.append(1))
    # No running loop: the heartbeat never fires, so one stall lasts the whole
    # test and is polled dozens of times past the threshold.
    loop = asyncio.new_event_loop()
    try:
        assert cd.start_loop_stall_watchdog(loop, threshold_s=0.1, poll_s=0.02)
        time.sleep(1.0)
        assert dumps == [1]
    finally:
        loop.close()
        cd._watchdog_thread.join(timeout=2)


def test_load_embedder_skips_fallback_after_out_of_memory(monkeypatch) -> None:
    from app.core import vector

    calls: list[str] = []

    class FakeST:
        def __init__(self, source, **kw):
            calls.append(source)
            raise RuntimeError("The paging file is too small for this operation to complete. (os error 1455)")

    import sys
    import types

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeST))
    monkeypatch.setattr(vector, "_candidate_sources", lambda name: [name])
    monkeypatch.setattr(vector, "_commit_too_low_for", lambda what, floor: False)
    monkeypatch.setattr(vector, "_embedder_instance", None)
    monkeypatch.setattr(vector, "_embedder_tried", False)

    assert vector._load_embedder() is None
    assert len(calls) == 1, "the fallback model must not be loaded after an out-of-memory failure"
    assert vector._embedder_tried is True


def test_load_embedder_declines_when_commit_is_low(monkeypatch) -> None:
    from app.core import vector

    monkeypatch.setattr(cd, "available_commit_mb", lambda: 200.0)
    monkeypatch.setattr(vector, "_embedder_instance", None)
    monkeypatch.setattr(vector, "_embedder_tried", False)
    assert vector._load_embedder() is None
    assert vector._embedder_tried is True


def test_desktop_encode_is_serialised_and_small_batched(monkeypatch) -> None:
    from app.core import vector

    monkeypatch.setenv("OE_DESKTOP", "1")
    monkeypatch.setattr(cd, "available_commit_mb", lambda: 8000.0)
    active = 0
    peak = 0
    batches: list[int] = []
    guard = threading.Lock()

    class FakeModel:
        def encode(self, texts, show_progress_bar, batch_size):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            batches.append(batch_size)
            time.sleep(0.05)
            with guard:
                active -= 1

            class R:
                def tolist(self):
                    return [[0.0] for _ in texts]

            return R()

    monkeypatch.setattr(vector, "_embedder_instance", FakeModel())
    threads = [threading.Thread(target=vector.encode_texts, args=(["a"],)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1
    assert set(batches) == {vector._DESKTOP_BATCH_SIZE}


def test_desktop_encode_refuses_when_commit_is_low(monkeypatch) -> None:
    from app.core import vector

    monkeypatch.setenv("OE_DESKTOP", "1")
    monkeypatch.setattr(cd, "available_commit_mb", lambda: 100.0)
    with pytest.raises(RuntimeError, match="memory"):
        vector.encode_texts(["a"])


def test_desktop_pool_defaults_to_one_worker(monkeypatch) -> None:
    from app.core import embedding_pool

    monkeypatch.delenv("OE_VECTOR_POOL_WORKERS", raising=False)
    monkeypatch.setenv("OE_DESKTOP", "1")
    assert embedding_pool._resolve_pool_size() == 1
    monkeypatch.setenv("OE_VECTOR_POOL_WORKERS", "3")
    assert embedding_pool._resolve_pool_size() == 3
