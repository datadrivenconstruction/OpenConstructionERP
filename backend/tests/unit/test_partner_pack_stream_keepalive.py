# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The pack install stream keeps talking while a long step runs.

The docker nginx closes an /api/ read that is silent for 120 s, and loading a
large cost base takes minutes. The stream used to say nothing between
``step_start`` and ``step_done``, so every big import was cut mid-step. It now
sends an SSE comment every ``STREAM_KEEPALIVE_SECONDS`` while a step runs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.partner_pack import full_install as fi
from app.core.partner_pack.full_install import FullInstallRequest, full_install_stream


def _slow_demos(seconds: float, started: asyncio.Event | None = None, cancelled: list[bool] | None = None):
    async def _run(*_a: Any, **_k: Any) -> fi.StepResult:
        if started is not None:
            started.set()
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            if cancelled is not None:
                cancelled.append(True)
            raise
        return fi.StepResult(step="demos", status="ok", detail={"installed": ["x"]})

    return _run


async def _frames(req: FullInstallRequest) -> list[str]:
    return [frame async for frame in full_install_stream(req)]


@pytest.mark.asyncio
async def test_a_long_step_sends_keepalives_between_its_start_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fi, "STREAM_KEEPALIVE_SECONDS", 0.05)
    monkeypatch.setattr(fi, "_step_demos", _slow_demos(0.4))

    frames = await _frames(FullInstallRequest(slug="any-pack", only_steps=["demos"]))

    kinds = [f.split("\n", 1)[0] for f in frames]
    start = kinds.index("event: step_start")
    done = kinds.index("event: step_done")
    between = kinds[start + 1 : done]
    assert between, "a step that runs past the keepalive interval must not be silent"
    assert all(k == ": keepalive" for k in between)
    # A keepalive is an SSE comment: no event name, no data, ignored by clients.
    assert all(f == ": keepalive\n\n" for f in frames[start + 1 : done])
    assert '"ok": true' in frames[-1]


@pytest.mark.asyncio
async def test_a_quick_step_sends_no_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fi, "STREAM_KEEPALIVE_SECONDS", 5.0)
    monkeypatch.setattr(fi, "_step_demos", _slow_demos(0.0))

    frames = await _frames(FullInstallRequest(slug="any-pack", only_steps=["demos"]))

    assert not any(f.startswith(":") for f in frames)


def test_the_default_interval_stays_well_under_the_proxy_timeout() -> None:
    # nginx proxy_read_timeout on /api/ is 120 s; the brief asks for <= 20 s.
    assert 0 < fi.STREAM_KEEPALIVE_SECONDS <= 20


@pytest.mark.asyncio
async def test_a_client_that_leaves_mid_step_stops_the_step(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    cancelled: list[bool] = []
    monkeypatch.setattr(fi, "STREAM_KEEPALIVE_SECONDS", 0.05)
    monkeypatch.setattr(fi, "_step_demos", _slow_demos(30.0, started, cancelled))

    stream = full_install_stream(FullInstallRequest(slug="any-pack", only_steps=["demos"]))
    async for frame in stream:
        if frame.startswith(":"):
            break
    assert started.is_set()
    await stream.aclose()
    await asyncio.sleep(0)
    assert cancelled == [True]
