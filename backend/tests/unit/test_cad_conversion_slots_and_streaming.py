"""CAD conversion path: conversion slots, blob streaming and the placeholder reason.

DB-free. Covers what happens when two uploads convert at once (they queue for a
slot instead of running two converters on a 3 GB host), that the stored CAD file
reaches the converter's temp folder without being read into memory whole, and
why a converted model shows boxes.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.core.storage import copy_stored_blob_to_path
from app.modules.bim_hub.quantity_warning import (
    PLACEHOLDER_CONVERTER_FAILED,
    PLACEHOLDER_CONVERTER_MISSING,
    PLACEHOLDER_CONVERTER_NO_MESH,
    placeholder_reason,
)
from app.modules.boq import ddc_runner


@pytest.fixture(autouse=True)
def _fresh_slots(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OE_CONVERT_MAX_PARALLEL", raising=False)
    ddc_runner._reset_converter_slots()
    yield
    ddc_runner._reset_converter_slots()


# ── Placeholder reason ─────────────────────────────────────────────────────


def test_converter_that_ran_without_mesh_is_not_told_to_install() -> None:
    # The Windows IFC converter 2.0.0 writes the element workbook but no GLB.
    result = {"geometry_quality": "placeholder", "converter_used": True}
    assert placeholder_reason(result) == PLACEHOLDER_CONVERTER_NO_MESH


def test_missing_and_failed_converter_are_told_apart() -> None:
    result = {"geometry_quality": "placeholder"}
    assert placeholder_reason(result) == PLACEHOLDER_CONVERTER_MISSING
    assert placeholder_reason(result, converter_failed=True) == PLACEHOLDER_CONVERTER_FAILED


# ── Conversion slots ───────────────────────────────────────────────────────


@pytest.mark.parametrize(("raw", "expected"), [(None, 1), ("", 1), ("2", 2), ("0", 1), ("-3", 1), ("two", 1)])
def test_max_parallel_conversions_reads_a_positive_integer(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int
) -> None:
    if raw is None:
        monkeypatch.delenv("OE_CONVERT_MAX_PARALLEL", raising=False)
    else:
        monkeypatch.setenv("OE_CONVERT_MAX_PARALLEL", raw)
    assert ddc_runner.max_parallel_conversions() == expected


def test_second_conversion_waits_for_the_first_and_reports_busy() -> None:
    order: list[str] = []
    first_in = threading.Event()
    release_first = threading.Event()

    def first() -> None:
        with ddc_runner.converter_slot():
            order.append("first-start")
            first_in.set()
            release_first.wait(5)
            order.append("first-end")

    def second() -> None:
        with ddc_runner.converter_slot():
            order.append("second-start")

    t1 = threading.Thread(target=first)
    t1.start()
    assert first_in.wait(5)
    assert ddc_runner.converter_slots_busy() is True
    t2 = threading.Thread(target=second)
    t2.start()
    time.sleep(0.2)
    assert order == ["first-start"], "the second conversion must wait for a free slot"
    release_first.set()
    t1.join(5)
    t2.join(5)
    assert order == ["first-start", "first-end", "second-start"]
    assert ddc_runner.converter_slots_busy() is False


def test_slot_hook_fires_once_the_slot_is_held() -> None:
    calls: list[bool] = []

    def hook() -> None:
        calls.append(ddc_runner.converter_slots_busy())

    token = ddc_runner.slot_acquired_hook.set(hook)
    try:
        with ddc_runner.converter_slot():
            pass
    finally:
        ddc_runner.slot_acquired_hook.reset(token)
    assert calls == [True]


def test_a_failing_hook_never_stops_the_conversion() -> None:
    def hook() -> None:
        raise RuntimeError("progress write failed")

    token = ddc_runner.slot_acquired_hook.set(hook)
    ran = False
    try:
        with ddc_runner.converter_slot():
            ran = True
    finally:
        ddc_runner.slot_acquired_hook.reset(token)
    assert ran
    assert ddc_runner.converter_slots_busy() is False


def test_run_converter_never_runs_two_converters_at_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_run(argv, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.15)
        with lock:
            active -= 1
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ddc_runner.subprocess, "run", fake_run)
    src = tmp_path / "a.dwg"
    src.write_bytes(b"AC1032")

    def convert(i: int) -> None:
        ddc_runner.run_converter("dwg", tmp_path / "DwgExporter.exe", src, tmp_path / f"w{i}")

    threads = [threading.Thread(target=convert, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert peak == 1


def test_a_converter_timeout_releases_the_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(ddc_runner.subprocess, "run", fake_run)
    src = tmp_path / "a.dwg"
    src.write_bytes(b"AC1032")
    with pytest.raises(subprocess.TimeoutExpired):
        ddc_runner.run_converter("dwg", tmp_path / "DwgExporter.exe", src, tmp_path / "w")
    assert ddc_runner.converter_slots_busy() is False


# ── Streaming the stored CAD file ──────────────────────────────────────────


class _StreamOnlyBackend:
    """A remote-style backend: no local path, the blob only arrives in chunks."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.get_called = False

    def local_path(self, key: str) -> Path | None:
        return None

    async def get(self, key: str) -> bytes:
        self.get_called = True
        return b"".join(self.chunks)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk


class _LocalBackend(_StreamOnlyBackend):
    def __init__(self, path: Path) -> None:
        super().__init__([])
        self.path = path

    def local_path(self, key: str) -> Path | None:
        return self.path


def test_remote_blob_is_streamed_not_read_whole(tmp_path: Path) -> None:
    backend = _StreamOnlyBackend([b"ISO-10303-21;", b"\nDATA;", b"\nENDSEC;"])
    dest = tmp_path / "original.ifc"
    written = asyncio.run(copy_stored_blob_to_path(backend, "k", dest))  # type: ignore[arg-type]
    assert written == len(b"ISO-10303-21;\nDATA;\nENDSEC;")
    assert dest.read_bytes() == b"ISO-10303-21;\nDATA;\nENDSEC;"
    assert backend.get_called is False


def test_local_blob_is_copied_file_to_file(tmp_path: Path) -> None:
    src = tmp_path / "stored.rvt"
    src.write_bytes(b"\xd0\xcf\x11\xe0" + b"x" * 4096)
    backend = _LocalBackend(src)
    dest = tmp_path / "original.rvt"
    assert asyncio.run(copy_stored_blob_to_path(backend, "k", dest)) == src.stat().st_size  # type: ignore[arg-type]
    assert dest.read_bytes() == src.read_bytes()
    assert backend.get_called is False
