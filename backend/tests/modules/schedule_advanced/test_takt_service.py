# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Orchestration tests for :class:`TaktScheduleService`.

The pure line-of-balance geometry is locked in ``test_takt.py`` with string
ids ("L1", "F"). Those never exercise the *service* seam, where the geometry
output is hydrated back into Pydantic response models that demand real
``UUID`` activity / location ids:

    * ``LineOfBalanceBar(activity_id: UUID, location_id: UUID, ...)``
    * ``TaktViolation(activity_id: UUID, ...)``
    * ``LineOfBalanceResponse.critical_path: list[UUID]`` built via
      ``[uuid.UUID(x) for x in geom["critical_path"]]``

A regression where the geometry returns a name/code instead of the row id
would pass every pure test yet 500 here on UUID parsing. These tests drive
the real service against in-memory repo stubs (no DB), pinning:

    * create_takt_schedule persists the schedule + its location sequence and
      stamps ``location_sequence_count``;
    * add_location recounts the sequence;
    * import_activities is additive;
    * compute_line_of_balance wires locations + activities through the
      geometry and round-trips real UUIDs into the response models, including
      the ``actual_cycle_duration_days`` Decimal -> float conversion that
      drives rhythm-break detection;
    * detect_violations surfaces just the violations;
    * the parent-master existence guard (404).

Mirrors the stub style of ``tests/unit/test_schedule_advanced.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.modules.schedule_advanced.schemas import (
    LocationCreate,
    TaktActivityCreate,
    TaktScheduleCreate,
)
from app.modules.schedule_advanced.service import TaktScheduleService

MASTER_ID = uuid.uuid4()


# ── Stubs ──────────────────────────────────────────────────────────────────


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, inst: Any) -> Any:
        if getattr(inst, "id", None) is None:
            inst.id = uuid.uuid4()
        now = datetime.now(UTC)
        inst.created_at = now
        inst.updated_at = now
        self.rows[inst.id] = inst
        return inst

    async def get_by_id(self, inst_id: uuid.UUID) -> Any:
        return self.rows.get(inst_id)

    async def delete(self, inst_id: uuid.UUID) -> None:
        self.rows.pop(inst_id, None)

    async def update_fields(self, inst_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(inst_id)
        if row is not None:
            for k, v in fields.items():
                setattr(row, k, v)


class _StubMasterRepo(_StubRepo):
    pass


class _StubTaktRepo(_StubRepo):
    async def list_for_master(self, master_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.master_schedule_id == master_id]


class _StubLocationRepo(_StubRepo):
    async def list_for_takt(self, takt_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.takt_schedule_id == takt_id]


class _StubTaktActivityRepo(_StubRepo):
    async def list_for_takt(self, takt_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.takt_schedule_id == takt_id]


class _StubSession:
    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


def _make_service(*, with_master: bool = True) -> TaktScheduleService:
    svc = TaktScheduleService.__new__(TaktScheduleService)
    svc.session = _StubSession()
    svc.master_repo = _StubMasterRepo()
    svc.takt_repo = _StubTaktRepo()
    svc.location_repo = _StubLocationRepo()
    svc.activity_repo = _StubTaktActivityRepo()
    if with_master:
        svc.master_repo.rows[MASTER_ID] = SimpleNamespace(id=MASTER_ID, project_id=uuid.uuid4(), name="MS")
    return svc


def _patch_event_bus() -> Any:
    return patch(
        "app.modules.schedule_advanced.service.event_bus",
        MagicMock(publish_detached=MagicMock(return_value=None)),
    )


# ── create_takt_schedule ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_takt_schedule_persists_locations_and_count() -> None:
    svc = _make_service()
    with _patch_event_bus() as bus:
        ts = await svc.create_takt_schedule(
            TaktScheduleCreate(
                master_schedule_id=MASTER_ID,
                name="Tower L1-L3",
                target_cycle_days=5,
                locations=[
                    {"sequence_order": 1, "name": "L1"},
                    {"sequence_order": 2, "name": "L2"},
                    {"sequence_order": 3, "name": "L3"},
                ],
            ),
            user_id=str(uuid.uuid4()),
        )
    assert ts.status == "draft"
    assert ts.location_sequence_count == 3
    # Three Location rows were written against this takt.
    locs = await svc.location_repo.list_for_takt(ts.id)
    assert {loc.name for loc in locs} == {"L1", "L2", "L3"}
    assert bus.publish_detached.call_args.args[0] == "schedule_advanced.takt.schedule.created"


@pytest.mark.asyncio
async def test_create_takt_schedule_404_when_master_missing() -> None:
    from fastapi import HTTPException

    svc = _make_service(with_master=False)
    with pytest.raises(HTTPException) as exc, _patch_event_bus():
        await svc.create_takt_schedule(
            TaktScheduleCreate(
                master_schedule_id=uuid.uuid4(),
                name="Orphan",
                locations=[{"sequence_order": 1, "name": "L1"}],
            )
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_takt_schedule_invalid_user_id_is_tolerated() -> None:
    """A non-UUID ``user_id`` must not blow up create - it stores NULL."""
    svc = _make_service()
    with _patch_event_bus():
        ts = await svc.create_takt_schedule(
            TaktScheduleCreate(
                master_schedule_id=MASTER_ID,
                name="X",
                locations=[{"sequence_order": 1, "name": "L1"}],
            ),
            user_id="not-a-uuid",
        )
    assert ts.created_by is None


@pytest.mark.asyncio
async def test_add_location_recounts_sequence() -> None:
    svc = _make_service()
    with _patch_event_bus():
        ts = await svc.create_takt_schedule(
            TaktScheduleCreate(
                master_schedule_id=MASTER_ID,
                name="Tower",
                locations=[{"sequence_order": 1, "name": "L1"}],
            )
        )
    assert ts.location_sequence_count == 1
    await svc.add_location(ts.id, LocationCreate(sequence_order=2, name="L2"))
    refreshed = await svc.get_takt_schedule(ts.id)
    assert refreshed.location_sequence_count == 2


@pytest.mark.asyncio
async def test_import_activities_is_additive() -> None:
    svc = _make_service()
    with _patch_event_bus():
        ts = await svc.create_takt_schedule(
            TaktScheduleCreate(
                master_schedule_id=MASTER_ID,
                name="Tower",
                locations=[{"sequence_order": 1, "name": "L1"}],
            )
        )
    created = await svc.import_activities(
        ts.id,
        [
            TaktActivityCreate(name="Formwork", sequence_order=1, planned_cycle_duration_days=5),
            TaktActivityCreate(name="Concrete", sequence_order=2, planned_cycle_duration_days=3),
        ],
    )
    assert len(created) == 2
    rows = await svc.activity_repo.list_for_takt(ts.id)
    assert {r.name for r in rows} == {"Formwork", "Concrete"}
    # A second import appends rather than replacing (documented import semantics).
    await svc.import_activities(
        ts.id,
        [TaktActivityCreate(name="MEP", sequence_order=3, planned_cycle_duration_days=4)],
    )
    rows = await svc.activity_repo.list_for_takt(ts.id)
    assert len(rows) == 3


# ── compute_line_of_balance: the UUID round-trip seam ──────────────────────


async def _seed_takt_with_geometry(
    svc: TaktScheduleService,
    *,
    tolerance_days: int = 1,
) -> Any:
    """Two locations + two trades, with an actual cycle that breaks rhythm."""
    from app.modules.schedule_advanced.models import (
        Location,
        TaktActivity,
        TaktSchedule,
    )

    ts = await svc.takt_repo.create(
        TaktSchedule(
            master_schedule_id=MASTER_ID,
            name="LoB",
            takt_rhythm_tolerance_days=tolerance_days,
            location_sequence_count=2,
            status="draft",
        )
    )
    for order, name in ((1, "L1"), (2, "L2")):
        await svc.location_repo.create(Location(takt_schedule_id=ts.id, sequence_order=order, name=name))
    # Formwork 5d (the longest -> critical). Concrete 3d with an observed 5.5d
    # actual cycle -> deviation 2.5 > tolerance -> rhythm break, error severity.
    await svc.activity_repo.create(
        TaktActivity(
            takt_schedule_id=ts.id,
            name="Formwork",
            sequence_order=1,
            planned_cycle_duration_days=5,
            crew_size=4,
            crew_skill_codes=[],
            buffer_days_before=0,
            status="planned",
        )
    )
    await svc.activity_repo.create(
        TaktActivity(
            takt_schedule_id=ts.id,
            name="Concrete",
            sequence_order=2,
            planned_cycle_duration_days=3,
            crew_size=3,
            crew_skill_codes=[],
            buffer_days_before=0,
            actual_cycle_duration_days=Decimal("5.5"),
            status="planned",
        )
    )
    return ts


@pytest.mark.asyncio
async def test_compute_line_of_balance_round_trips_real_uuids() -> None:
    svc = _make_service()
    ts = await _seed_takt_with_geometry(svc)

    with _patch_event_bus() as bus:
        lob = await svc.compute_line_of_balance(ts.id)

    # 2 locations x 2 trades = 4 bars; counts come off the live row lists.
    assert len(lob.bars) == 4
    assert lob.total_locations == 2
    assert lob.total_activities == 2

    # Every bar id parsed as a real UUID (the seam the pure test can't hit).
    act_ids = {a.id for a in await svc.activity_repo.list_for_takt(ts.id)}
    loc_ids = {loc.id for loc in await svc.location_repo.list_for_takt(ts.id)}
    for bar in lob.bars:
        assert isinstance(bar.activity_id, uuid.UUID)
        assert isinstance(bar.location_id, uuid.UUID)
        assert bar.activity_id in act_ids
        assert bar.location_id in loc_ids

    # Critical path = the single longest trade (Formwork), as a UUID.
    formwork_id = next(a.id for a in await svc.activity_repo.list_for_takt(ts.id) if a.name == "Formwork")
    assert lob.critical_path == [formwork_id]
    assert all(b.is_critical == (b.activity_id == formwork_id) for b in lob.bars)

    # Rhythm break detected from the Decimal actual cycle -> float conversion.
    # The break is evaluated per (activity, location) bar, so a trade that
    # repeats across both locations is flagged once per location.
    assert len(lob.violations) == 2
    concrete_id = next(a.id for a in await svc.activity_repo.list_for_takt(ts.id) if a.name == "Concrete")
    for v in lob.violations:
        assert v.violation_type == "rhythm_break"
        assert v.deviation_days == 2.5
        assert v.severity == "error"  # 2.5 > 2 * tolerance(1)
        assert isinstance(v.activity_id, uuid.UUID)
        assert v.activity_id == concrete_id

    assert lob.total_makespan_days > 0
    assert bus.publish_detached.call_args.args[0] == "schedule_advanced.takt.cycle_updated"


@pytest.mark.asyncio
async def test_compute_line_of_balance_empty_takt_is_clean() -> None:
    """A takt with no locations / activities returns an empty, valid response."""
    from app.modules.schedule_advanced.models import TaktSchedule

    svc = _make_service()
    ts = await svc.takt_repo.create(
        TaktSchedule(
            master_schedule_id=MASTER_ID,
            name="Empty",
            takt_rhythm_tolerance_days=1,
            location_sequence_count=0,
            status="draft",
        )
    )
    with _patch_event_bus():
        lob = await svc.compute_line_of_balance(ts.id)
    assert lob.bars == []
    assert lob.violations == []
    assert lob.critical_path == []
    assert lob.total_makespan_days == 0
    assert lob.total_locations == 0
    assert lob.total_activities == 0


@pytest.mark.asyncio
async def test_detect_violations_returns_only_violations() -> None:
    svc = _make_service()
    ts = await _seed_takt_with_geometry(svc)
    with _patch_event_bus():
        violations = await svc.detect_violations(ts.id)
    # One rhythm break per location the offending trade repeats in (2 locations).
    assert len(violations) == 2
    assert all(v.violation_type == "rhythm_break" for v in violations)


@pytest.mark.asyncio
async def test_compute_line_of_balance_404_for_unknown_takt() -> None:
    from fastapi import HTTPException

    svc = _make_service()
    with pytest.raises(HTTPException) as exc, _patch_event_bus():
        await svc.compute_line_of_balance(uuid.uuid4())
    assert exc.value.status_code == 404
