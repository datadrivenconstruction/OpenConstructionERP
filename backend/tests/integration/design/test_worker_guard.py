"""Broker without a worker: the generation is refused up front, with a code the panels translate."""

from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from app.modules.design import worker_guard

pytestmark = pytest.mark.asyncio


class _Conn:
    def __init__(self, up: bool):
        self.up = up

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ensure_connection(self, **_kw):
        if not self.up:
            raise ConnectionError("refused")


def _fake_app(monkeypatch, *, up=True, eager=False, replies=None, ping_raises=False):
    def ping(timeout):
        if ping_raises:
            raise RuntimeError("boom")
        return replies

    fake = types.SimpleNamespace(
        conf=types.SimpleNamespace(task_always_eager=eager),
        connection_for_write=lambda: _Conn(up),
        control=types.SimpleNamespace(ping=ping),
    )
    import app.core.jobs as jobs

    monkeypatch.setattr(jobs, "get_celery_app", lambda: fake)
    monkeypatch.setattr(worker_guard, "_worker_state", _real_state)


_real_state = worker_guard._worker_state


@pytest.mark.parametrize(
    "kw,expected",
    [
        ({"up": False}, "inline"),
        ({"eager": True}, "inline"),
        ({"replies": [{"worker1": {"ok": "pong"}}]}, "worker"),
        ({"replies": []}, "none"),
        ({"replies": None}, "none"),
        ({"ping_raises": True}, "none"),
    ],
)
async def test_state(monkeypatch, kw, expected):
    _fake_app(monkeypatch, **kw)
    assert worker_guard._worker_state() == expected


async def test_refuses_without_worker_and_passes_otherwise(monkeypatch):
    _fake_app(monkeypatch, replies=[])
    with pytest.raises(HTTPException) as e:
        await worker_guard.require_runner()
    assert e.value.status_code == 503 and e.value.detail["code"] == worker_guard.NO_WORKER
    _fake_app(monkeypatch, replies=[{"w": {}}])
    await worker_guard.require_runner()
    _fake_app(monkeypatch, up=False)
    await worker_guard.require_runner()
