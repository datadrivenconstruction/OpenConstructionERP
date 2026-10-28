# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``list_all_for_document`` must page out a complete, stable row set.

The revision compare depends on getting every measurement of a document, so
the paging loop is worth pinning on its own. Two properties matter:

    * every row comes back, across as many chunks as it takes, with no
      duplicate and no gap;
    * the ceiling is respected, because it is the signal the compare uses to
      decide it must report itself as truncated.

The SQLAlchemy session is faked. What is exercised is the loop, not the SQL.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

_PREVIOUS_DATA_DIR = os.environ.get("DATA_DIR")
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-takeoff-paging-"))
os.environ["DATA_DIR"] = str(_TMP_DIR)

from app.modules.takeoff.repository import MeasurementRepository  # noqa: E402

# Put it back. DATA_DIR is process wide and only the import above reads it, so
# left set it answers every later module that asks resolve_data_dir() where the
# platform writes, and the failure surfaces in whichever unrelated test asks.
if _PREVIOUS_DATA_DIR is None:
    os.environ.pop("DATA_DIR", None)
else:
    os.environ["DATA_DIR"] = _PREVIOUS_DATA_DIR


pytestmark = pytest.mark.unit


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Serves a fixed row list through OFFSET / LIMIT, recording the slices."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.slices: list[tuple[int, int]] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        offset = stmt._offset or 0  # noqa: SLF001 - reading the compiled clause is the point
        limit = stmt._limit
        if limit is None:
            # The COUNT(*) statement.
            return _FakeResult([len(self.rows)])
        self.slices.append((offset, limit))
        return _FakeResult(self.rows[offset : offset + limit])


async def test_paging_returns_every_row_across_chunks() -> None:
    """2500 rows in chunks of 1000 come back whole and in order."""
    rows = list(range(2500))
    session = _FakeSession(rows)
    repo = MeasurementRepository(session)  # type: ignore[arg-type]

    out = await repo.list_all_for_document(uuid.uuid4(), "doc", max_rows=10000, chunk_size=1000)

    assert out == rows
    assert session.slices == [(0, 1000), (1000, 1000), (2000, 1000)]


async def test_paging_stops_at_the_ceiling() -> None:
    """The last chunk is trimmed so the ceiling is never overshot."""
    session = _FakeSession(list(range(500)))
    repo = MeasurementRepository(session)  # type: ignore[arg-type]

    out = await repo.list_all_for_document(uuid.uuid4(), "doc", max_rows=120, chunk_size=50)

    assert out == list(range(120))
    assert session.slices == [(0, 50), (50, 50), (100, 20)]


async def test_paging_short_document_makes_one_round_trip() -> None:
    """A partial first chunk ends the loop - no pointless second query."""
    session = _FakeSession(list(range(7)))
    repo = MeasurementRepository(session)  # type: ignore[arg-type]

    out = await repo.list_all_for_document(uuid.uuid4(), "doc", max_rows=10000, chunk_size=1000)

    assert out == list(range(7))
    assert session.slices == [(0, 1000)]


async def test_paging_with_a_zero_ceiling_reads_nothing() -> None:
    """Guard against a caller passing a nonsense ceiling."""
    session = _FakeSession(list(range(10)))
    repo = MeasurementRepository(session)  # type: ignore[arg-type]

    assert await repo.list_all_for_document(uuid.uuid4(), "doc", max_rows=0) == []
    assert session.slices == []


async def test_count_for_document_returns_the_true_total() -> None:
    """The count is what makes a truncated compare able to say how much it missed."""
    session = _FakeSession(list(range(1234)))
    repo = MeasurementRepository(session)  # type: ignore[arg-type]

    assert await repo.count_for_document(uuid.uuid4(), "doc") == 1234
