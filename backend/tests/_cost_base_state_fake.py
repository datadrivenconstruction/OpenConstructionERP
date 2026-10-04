"""A dict-backed stand-in for ``oe_costs_base_state`` for tests without a database.

The costs router reads and writes a base's market and language only through
``app.modules.costs.base_state``. Tests that drive the router with
``session=None`` install this store over that module's read and write calls;
the real table is exercised in ``tests/unit/test_cost_base_state.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.costs import base_state


class FakeStateStore:
    """Same read/write surface as ``base_state``, kept in a dict."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.writes: list[tuple[str, dict[str, Any]]] = []

    async def read(self, session: Any, region: str) -> base_state.BaseState | None:
        row = self.rows.get(region)
        if row is None:
            return None
        return base_state.BaseState(
            region=region,
            text_language=row.get("text_language"),
            active_market=row.get("active_market"),
            switching_to=row.get("switching_to"),
            updated_at=None,
        )

    async def write(self, session: Any, region: str, **fields: Any) -> None:
        fields.pop("commit", None)
        fields.pop("updated_by", None)
        self.writes.append((region, dict(fields)))
        self.rows.setdefault(region, {}).update(fields)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeStateStore:
        monkeypatch.setattr(base_state, "read_base_state", self.read)
        monkeypatch.setattr(base_state, "write_base_state", self.write)
        return self
