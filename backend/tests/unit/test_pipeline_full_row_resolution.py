# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# Regression tests for two ways the Pipeline Builder used to compute money over
# a subset of the data while presenting the answer as the whole.
#
# 1. ``transform.filter`` read ``upstream["rows"]``. That key is a bounded
#    PREVIEW capped at ``_SAMPLE_LIMIT`` (25) and exists for the run UI, not for
#    arithmetic. A source -> filter -> rollup graph therefore reported a grand
#    total over at most 25 positions and labelled it the project total.
#
# 2. ``_resolve_full_rows`` re-read positions by ``row_ids``, which the source
#    caps at ``_ROW_IDS_CAP`` (5000) to keep the node-state JSON small. A
#    project past the cap got a total over its first 5000 positions, again with
#    nothing marking it short. The envelope now carries the source scope so the
#    real set can be re-read.
#
# Both are exercised with a stub session rather than the module's PostgreSQL
# harness: the defect is in which rows the code chooses to read, so the test
# only has to observe the query it issues.

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.pipeline.registry import NodeContext
from app.modules.pipelines.pipeline_nodes import (
    _ROW_IDS_CAP,
    _SAMPLE_LIMIT,
    _run_transform_filter,
)


class _StubPosition:
    """Minimal stand-in carrying the attributes the row mapper reads."""

    def __init__(self, index: int) -> None:
        self.id = uuid.uuid4()
        self.ordinal = index
        self.description = f"Position {index}"
        self.unit = "m3"
        self.quantity = 2
        self.unit_rate = 100
        self.classification: dict[str, Any] = {}


class _StubResult:
    def __init__(self, rows: list[_StubPosition]) -> None:
        self._rows = rows

    def scalars(self) -> _StubResult:
        return self

    def all(self) -> list[_StubPosition]:
        return self._rows


class _StubSession:
    """Records every statement so a test can assert WHICH read was issued."""

    def __init__(self, rows: list[_StubPosition]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _StubResult:
        self.statements.append(statement)
        return _StubResult(self._rows)


def _context(db: Any, upstream: dict[str, Any], params: dict[str, Any] | None = None) -> NodeContext:
    return NodeContext(
        db=db,
        node_id="n1",
        node_type="transform.filter",
        params=params or {},
        inputs={"src": upstream},
    )


@pytest.mark.asyncio
async def test_filter_operates_on_the_full_set_not_the_preview_sample() -> None:
    """A filter must see every row, not the 25-row envelope preview."""
    total = _SAMPLE_LIMIT * 4
    positions = [_StubPosition(i) for i in range(total)]
    db = _StubSession(positions)

    upstream = {
        # What the wire actually carries: a truncated preview plus the id list.
        "rows": [{"id": str(p.id)} for p in positions[:_SAMPLE_LIMIT]],
        "row_ids": [str(p.id) for p in positions],
        "count": total,
        "sample_truncated": True,
    }

    out = await _run_transform_filter(_context(db, upstream))

    assert out["count"] == total, (
        "the filter counted the preview rather than the full set, so every "
        "downstream total would be computed over at most "
        f"{_SAMPLE_LIMIT} rows instead of {total}"
    )
    assert len(out["rows"]) == _SAMPLE_LIMIT, "the OUTPUT preview should still be bounded"


@pytest.mark.asyncio
async def test_a_truncated_id_list_is_re_read_from_the_source_scope() -> None:
    """Past the id-list cap, fall back to the source scope, not the cut list."""
    boq_id = uuid.uuid4()
    positions = [_StubPosition(i) for i in range(_ROW_IDS_CAP + 10)]
    db = _StubSession(positions)

    upstream = {
        "rows": [],
        # The source had to cut the list, and says so.
        "row_ids": [str(p.id) for p in positions[:_ROW_IDS_CAP]],
        "row_ids_truncated": True,
        "source_boq_ids": [str(boq_id)],
        "count": len(positions),
    }

    out = await _run_transform_filter(_context(db, upstream))

    assert out["count"] == len(positions), (
        "a truncated id list must be resolved from the source scope; reading "
        "the capped list back caps the total with it"
    )
    rendered = str(db.statements[0])
    assert "boq_id" in rendered, (
        f"expected a re-read scoped by boq_id; the query still filtered by the truncated id list instead: {rendered}"
    )


@pytest.mark.asyncio
async def test_a_mutated_envelope_is_never_re_read() -> None:
    """A what-if transform's in-place values must survive; re-reading loses them."""
    db = _StubSession([])
    upstream = {
        "mutated": True,
        "rows": [{"id": str(uuid.uuid4()), "unit_rate": 999}],
        "row_ids": [],
    }

    out = await _run_transform_filter(_context(db, upstream))

    assert out["count"] == 1
    assert db.statements == [], "a mutated envelope must not hit the database at all"
