# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Recalculating the critical path keeps what else an activity's metadata holds.

The CPM write merges its figures into ``metadata_``, but it read the existing
metadata from a snapshot that never carried it, so every recalculation left
only ``{"cpm": ...}``. That erased a milestone's reached marker (the guard
against announcing it twice), the sales contract a milestone names, and the
sheet row an imported activity came from.
"""

from __future__ import annotations

import pytest

from tests.unit.test_schedule_dependency_unification import _create_activity, _create_schedule, _make_service


@pytest.mark.asyncio
async def test_a_recalculation_keeps_the_other_metadata_keys() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    act = await _create_activity(svc, sched.id, name="Frame complete", start_date="2026-05-01", end_date="2026-05-06")
    row = svc.activity_repo.rows[act.id]
    row.metadata_ = {"milestone_reached_at": "2026-05-06", "sales_contract_id": "spa-1", "import": {"row": 7}}

    await svc.calculate_critical_path(sched.id)

    meta = svc.activity_repo.rows[act.id].metadata_
    assert meta["milestone_reached_at"] == "2026-05-06"
    assert meta["sales_contract_id"] == "spa-1"
    assert meta["import"] == {"row": 7}
    assert "cpm" in meta


@pytest.mark.asyncio
async def test_a_recalculation_replaces_the_previous_cpm_figures() -> None:
    svc = _make_service()
    sched = await _create_schedule(svc)
    act = await _create_activity(svc, sched.id, name="Pour", start_date="2026-05-01", end_date="2026-05-06")
    svc.activity_repo.rows[act.id].metadata_ = {"cpm": {"es": 99, "stale": True}}

    await svc.calculate_critical_path(sched.id)

    cpm = svc.activity_repo.rows[act.id].metadata_["cpm"]
    assert "stale" not in cpm
    assert cpm["es"] == 0
