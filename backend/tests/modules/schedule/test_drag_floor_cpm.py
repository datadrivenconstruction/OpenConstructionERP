"""A bar dragged later keeps its place through CPM; logic still clamps a drag that is too early."""

from __future__ import annotations

import pytest

from app.core.cpm import calculate_cpm

RELS = [
    {"predecessor_id": "A", "successor_id": "B", "type": "FS", "lag": 0},
    {"predecessor_id": "B", "successor_id": "C", "type": "FS", "lag": 0},
]


def _acts(b_extra: dict):
    seven = {"work_days": [0, 1, 2, 3, 4, 5, 6], "exceptions": []}
    return [
        {"id": "A", "name": "A", "duration": 5, "calendar": seven},
        {"id": "B", "name": "B", "duration": 3, "calendar": seven, **b_extra},
        {"id": "C", "name": "C", "duration": 2, "calendar": seven},
    ]


async def _run(b_extra: dict):
    rows = await calculate_cpm(_acts(b_extra), RELS)
    return {r["name"]: r for r in rows}


@pytest.mark.asyncio
async def test_without_a_floor_the_successor_follows_its_predecessor():
    got = await _run({})
    assert got["B"]["early_start"] == 5
    assert got["C"]["early_start"] == 8


@pytest.mark.asyncio
async def test_start_no_earlier_holds_the_dragged_bar_and_pushes_its_successors():
    got = await _run({"constraint_type": "start_no_earlier", "constraint_offset": 20})
    assert got["B"]["early_start"] == 20
    assert got["C"]["early_start"] == 23


@pytest.mark.asyncio
async def test_a_floor_earlier_than_the_logic_allows_is_clamped_by_the_predecessor():
    got = await _run({"constraint_type": "start_no_earlier", "constraint_offset": 2})
    assert got["B"]["early_start"] == 5
    assert got["C"]["early_start"] == 8
