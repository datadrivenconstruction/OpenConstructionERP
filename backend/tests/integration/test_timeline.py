# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""ACAP timeline generator tests.

Two layers:
  * PURE (no DB) — duration arithmetic + DAG scheduling (finish-to-start +
    independent-parallel). These are the money-adjacent deterministic core.
  * INTEGRATION (real PostgreSQL) — generate_timeline reads labour OH from the
    seeded AHSP coefficient DB and reuses the RAB take-off quantities, so a
    project's schedule is derived from the SAME geometry as its RAB.

NOTE: the integration tests need PostgreSQL (run in Docker, like test_rab.py).
The pure tests run anywhere.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.acap.layout.schema import FloorPlan, Kavling, Level, Opening, Point, Room
from app.modules.acap.seed import seed_ahsp
from app.modules.acap.timeline.generator import (
    StageSpec,
    _duration_days,
    build_schedule,
    generate_timeline,
)
from tests._pg import transactional_session


# ═══════════════════════════════════════════════════════════════════════════
# PURE — duration arithmetic
# ═══════════════════════════════════════════════════════════════════════════


def test_duration_days_worked_example():
    """Plan spec: volume 100 m2 plesteran, koef 0.3 OH/m2, crew 3 -> 10 hari.

    man_days = 100 * 0.3 = 30 ; duration = ceil(30 / 3) = 10.
    """
    man_days = Decimal("100") * Decimal("0.3")
    assert _duration_days(man_days, 3) == 10


def test_duration_days_rounds_up():
    """A partial crew-day still occupies a whole calendar day."""
    assert _duration_days(Decimal("31"), 3) == 11  # 10.33 -> 11
    assert _duration_days(Decimal("0.5"), 3) == 1  # never rounds a real task to 0


def test_duration_days_zero_qty_is_zero():
    """No work -> no bar (a 0-day task is dropped, not shown as 1 day)."""
    assert _duration_days(Decimal("0"), 3) == 0


# ═══════════════════════════════════════════════════════════════════════════
# PURE — DAG scheduling (finish-to-start + independent-parallel)
# ═══════════════════════════════════════════════════════════════════════════


def test_build_schedule_finish_to_start_and_parallel():
    """pondasi finishes before struktur starts; two stages that both depend
    only on pondasi (and not on each other) run in PARALLEL."""
    specs = [
        StageSpec(name="pondasi", depends_on=(), crew=4, lead_days=0, elements=("pondasi",)),
        StageSpec(name="struktur", depends_on=("pondasi",), crew=4, lead_days=0, elements=("kolom",)),
        StageSpec(name="atap", depends_on=("pondasi",), crew=4, lead_days=0, elements=("atap",)),
    ]
    durations = {"pondasi": 5, "kolom": 3, "atap": 4}

    sched = build_schedule(specs, durations)

    p_start, p_end = sched.stage_windows["pondasi"]
    s_start, _ = sched.stage_windows["struktur"]
    a_start, _ = sched.stage_windows["atap"]

    assert (p_start, p_end) == (0, 5)
    # finish-to-start: struktur cannot begin until pondasi is done
    assert s_start == p_end == 5
    # independent-parallel: struktur & atap both wait only on pondasi -> same start
    assert a_start == s_start == 5
    # total = pondasi(5) + longest downstream branch (atap 4 > kolom 3) = 9
    assert sched.total_days == 9


def test_build_schedule_drops_zero_duration_stage_but_keeps_dependency():
    """A stage whose only element has no quantity contributes 0 days yet still
    passes its start through to dependants (no phantom 1-day bar)."""
    specs = [
        StageSpec(name="a", depends_on=(), crew=4, lead_days=0, elements=("x",)),
        StageSpec(name="b", depends_on=("a",), crew=4, lead_days=0, elements=("y",)),
    ]
    sched = build_schedule(specs, {"x": 0, "y": 4})
    assert sched.stage_windows["a"] == (0, 0)
    assert sched.stage_windows["b"] == (0, 4)
    assert [t["element"] for t in sched.tasks] == ["y"]  # zero-duration task 'x' dropped


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION — generate_timeline off the seeded AHSP DB
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def session():
    async with transactional_session(disable_fks=True) as s:
        yield s


def _one_room_plan() -> FloorPlan:
    """One 4x4 room + a wet room + one door — exercises dinding/plesteran/acian
    (matches the schema fields exactly: Opening = type/room/width_m)."""
    ruang = Room(
        name="Ruang",
        type="ruang_keluarga",
        polygon=[Point(x=0.0, y=0.0), Point(x=4.0, y=0.0), Point(x=4.0, y=4.0), Point(x=0.0, y=4.0)],
        area_m2=16.0,
    )
    km = Room(
        name="KM",
        type="kamar_mandi",
        polygon=[Point(x=0.0, y=4.0), Point(x=2.0, y=4.0), Point(x=2.0, y=6.0), Point(x=0.0, y=6.0)],
        area_m2=4.0,
    )
    door = Opening(type="door", room="Ruang", width_m=0.9)
    level = Level(level=1, rooms=[ruang, km], walls=[], openings=[door])
    return FloorPlan(kavling=Kavling(width_m=10.0, length_m=15.0), levels=[level])


@pytest.mark.asyncio
async def test_generate_timeline_derives_durations_and_order(session):
    # Real AHSP labour coefficients — every kode in ELEMENT_KODE_MAP present.
    await seed_ahsp(session)

    result = await generate_timeline(session, _one_room_plan())

    tasks = {t["element"]: t for t in result.tasks}
    assert "dinding" in tasks
    # dinding qty = net wall area; man_days = qty * (0.3+0.1); duration > 0
    assert tasks["dinding"]["duration_days"] >= 1
    assert tasks["dinding"]["man_days"] > 0

    # ordering: plesteran depends (transitively) on dinding -> starts after it
    assert tasks["plesteran"]["start_day"] >= tasks["dinding"]["end_day"]
    assert result.total_days >= tasks["plesteran"]["end_day"]
    # unpriced/undeclared trades never crash — every task has a crew + kode
    for t in result.tasks:
        assert t["crew"] >= 1
        assert t["kode"].startswith("ACAP.")
