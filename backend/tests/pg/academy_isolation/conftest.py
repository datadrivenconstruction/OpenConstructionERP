# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared rows and switches for the academy isolation gate tests.

Every gate is asked the same three questions: with the flag on an outsider is
refused, with the flag on an insider still gets through, and with the flag off
the outsider gets exactly what they got before the gate existed.

The flag is flipped through the environment and ``get_settings.cache_clear()``,
the way an install sets it, so the tests exercise the real read path rather
than a patched helper.

Events are recorded instead of delivered. Several of the events these paths
publish have application subscribers that open their own session from
``async_session_factory``, which is not bound to the embedded cluster; letting
them run would poison the loop for every later test (see ``tests/pg/conftest``).
The recording is also what the on/off comparisons assert on.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from app.config import get_settings
from app.core.events import event_bus

_FLAG_NAMES = ("OE_ACADEMY_MODE", "ACADEMY_MODE")


@pytest.fixture
def academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[bool], None]]:
    """Switch the academy flag; the install default (off) is restored afterwards."""

    def _set(on: bool) -> None:
        for name in _FLAG_NAMES:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OE_ACADEMY_MODE", "true" if on else "false")
        get_settings.cache_clear()
        assert get_settings().academy_mode is on

    try:
        yield _set
    finally:
        for name in _FLAG_NAMES:
            monkeypatch.delenv(name, raising=False)
        get_settings.cache_clear()


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Every event published during the test, in order, with no subscriber run."""
    seen: list[tuple[str, dict[str, Any]]] = []

    def _detached(name: str, data: dict[str, Any] | None = None, source_module: str | None = None, **_: Any):
        seen.append((name, dict(data or {})))

    async def _publish(name: str, data: dict[str, Any] | None = None, source_module: str | None = None, **_: Any):
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(event_bus, "publish_detached", _detached)
    monkeypatch.setattr(event_bus, "publish", _publish)
    return seen
