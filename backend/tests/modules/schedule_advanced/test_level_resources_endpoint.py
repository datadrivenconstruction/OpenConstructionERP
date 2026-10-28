# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``POST /schedule-advanced/{id}/level-resources`` levels the whole logic.

The endpoint used to run an FS-only leveler while ``/level-preview`` and
``/level-apply`` already ran the engine that honours all four PDM link types.
A schedule built on SS, FF or SF therefore came back from this one endpoint
with starts that break its own logic, and nothing in the response said so: the
shifts look exactly like shifts computed correctly.

These tests pin the two halves. First that the defect was real, by running both
levelers over the same SS network and showing the old one violating the link
the new one respects. Then that the endpoint is on the new engine, by calling
the handler with the rows it would have read and checking the answer.

The handler is exercised directly with a stub session rather than over HTTP:
what is under test is which arithmetic it runs, and the auth and loading it
does around that are covered where they are defined.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.resources.resource_engine import level_preview
from app.modules.schedule_advanced.cpm import Activity, TaskNetwork, compute_cpm
from app.modules.schedule_advanced.leveling import level_by_resource_max
from app.modules.schedule_advanced.schemas import LevelResourcesRequest

# ── Pure engines: the defect this change closes ──────────────────────────────


def _ss_network() -> TaskNetwork:
    """A and B share one crew; C must start with B and needs no crew.

    Leveling has to push B off A, and C is tied to B start-to-start, so C has
    to follow. Nothing about C's own resources forces it anywhere, which is
    what makes this network tell the two levelers apart: only the link moves C.
    """
    return TaskNetwork(
        [
            Activity(id="A", duration=2, predecessors=[], required_resources={"crew": 1}),
            Activity(id="B", duration=2, predecessors=[], required_resources={"crew": 1}),
            Activity(id="C", duration=2, predecessors=[("B", "SS", 0)], required_resources={}),
        ]
    )


def test_the_fs_only_leveler_walks_through_an_ss_link() -> None:
    """It moves B and leaves C behind, on a link that says they start together."""
    net = _ss_network()

    old = level_by_resource_max(net, compute_cpm(net), {"crew": 1})

    assert old == {"B": 2}, "B is pushed off A"
    assert "C" not in old, "C stays at 0 while the activity it must start with sits at 2"


def test_the_engine_the_endpoint_now_uses_respects_the_ss_link() -> None:
    """Same network, the leveler that reads the link: C follows B."""
    preview = level_preview(_ss_network(), {"crew": 1})

    moved = {s.activity_id: s.new_es for s in preview.shifts}
    assert moved == {"B": 2, "C": 2}


# ── The endpoint ─────────────────────────────────────────────────────────────

# Fixed ids, because the leveler breaks priority ties on the id as a string and
# random uuids would decide which of two equal activities moves.
ID_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ID_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
ID_C = uuid.UUID("00000000-0000-0000-0000-0000000000c3")


def _row(aid: uuid.UUID, duration: int, resource: str | None = "crew", count: int = 1) -> SimpleNamespace:
    """One schedule activity row as the endpoint reads it."""
    resources = [{"name": resource, "count": count}] if resource else []
    return SimpleNamespace(id=aid, duration_days=duration, resources=resources)


def _rel(pred: uuid.UUID, succ: uuid.UUID, dep_type: str, lag: int = 0) -> SimpleNamespace:
    """One relationship row as the endpoint reads it."""
    return SimpleNamespace(predecessor_id=pred, successor_id=succ, relationship_type=dep_type, lag_days=lag)


class _StubSession:
    """Answers the endpoint's two selects in the order it issues them."""

    def __init__(self, act_rows: list[Any], rel_rows: list[Any]) -> None:
        self._answers = [act_rows, rel_rows]

    async def execute(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        rows = self._answers.pop(0) if self._answers else []
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


@pytest.fixture
def _open_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the ownership checks; they are tested where they live."""
    from app.modules.schedule_advanced import router as sa_router

    async def _project_id(_schedule_id: Any, _session: Any) -> uuid.UUID:
        return uuid.uuid4()

    async def _verify(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(sa_router, "_project_id_for_schedule", _project_id)
    monkeypatch.setattr(sa_router, "verify_project_access", _verify)


async def _level(act_rows: list[Any], rel_rows: list[Any], limits: dict[str, int]) -> Any:
    """Call the handler the way FastAPI would."""
    from app.modules.schedule_advanced.router import level_resources_for_schedule

    return await level_resources_for_schedule(
        schedule_id=uuid.uuid4(),
        data=LevelResourcesRequest(resource_limits=limits),
        session=_StubSession(act_rows, rel_rows),  # type: ignore[arg-type]
        user_id=uuid.uuid4(),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("_open_access")
async def test_an_ss_link_is_honoured_by_the_endpoint() -> None:
    """The response no longer contradicts the schedule it was computed from.

    Same network as the pure test above: the crew moves B, and C has to follow
    because it is tied to B's start. The old wiring returned B alone, which
    described a schedule where C runs before the work it starts with.
    """
    result = await _level(
        [_row(ID_A, 2), _row(ID_B, 2), _row(ID_C, 2, resource=None)],
        [_rel(ID_B, ID_C, "SS")],
        {"crew": 1},
    )

    shifted = {s.activity_id: s.shifted_es for s in result.shifts}
    assert shifted == {ID_B: 2, ID_C: 2}
    assert result.num_shifted == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("_open_access")
async def test_an_ff_link_is_honoured_by_the_endpoint() -> None:
    """Finish-to-finish binds the finish, so the bound is read through duration.

    C finishes with B. The crew pushes B to day 2, so B now finishes on day 4
    and C, two days long, cannot start before day 2 either. Ignoring the link
    leaves C at 0, finishing two days before the activity it finishes with.
    """
    result = await _level(
        [_row(ID_A, 2), _row(ID_B, 2), _row(ID_C, 2, resource=None)],
        [_rel(ID_B, ID_C, "FF")],
        {"crew": 1},
    )

    shifted = {s.activity_id: s.shifted_es for s in result.shifts}
    assert shifted == {ID_B: 2, ID_C: 2}


@pytest.mark.asyncio
@pytest.mark.usefixtures("_open_access")
async def test_an_fs_only_schedule_gets_the_same_answer_as_before() -> None:
    """Back-compat is the point of keeping this endpoint, so it has to hold."""
    result = await _level(
        [_row(ID_A, 2), _row(ID_B, 2), _row(ID_C, 2, resource=None)],
        [_rel(ID_B, ID_C, "FS")],
        {"crew": 1},
    )

    net = TaskNetwork(
        [
            Activity(id=ID_A, duration=2, predecessors=[], required_resources={"crew": 1}),
            Activity(id=ID_B, duration=2, predecessors=[], required_resources={"crew": 1}),
            Activity(id=ID_C, duration=2, predecessors=[(ID_B, "FS", 0)], required_resources={}),
        ]
    )
    old = level_by_resource_max(net, compute_cpm(net), {"crew": 1})

    assert {s.activity_id: s.shifted_es for s in result.shifts} == old
    assert old, "an FS network that levels to no shifts at all would prove nothing"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_open_access")
async def test_an_activity_that_cannot_fit_is_named_rather_than_hidden() -> None:
    """A crew of six against a ceiling of two is not a scheduling problem.

    No start clears it, so the activity is placed at its earliest legal start
    and reported. It is absent from ``shifts`` either way, which on its own
    reads exactly like an activity that needed no shift.
    """
    a = uuid.uuid4()

    result = await _level([_row(a, 2, count=6)], [], {"crew": 2})

    assert [u.activity_id for u in result.unresolvable] == [a]
    assert result.unresolvable[0].required == 6.0
    assert result.unresolvable[0].limit == 2.0
    assert result.shifts == [], "there is no start that would help, so no shift is proposed"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_open_access")
async def test_nothing_is_split_on_this_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """This response carries starts, so a split activity could not be described.

    ``/level-preview`` returns the day-runs and may split. Here a start on its
    own would be only part of the truth, so splitting stays off. The handler
    imports the engine when it runs, so patching the engine module catches the
    call the endpoint actually makes.
    """
    from app.modules.resources import resource_engine as engine

    seen: dict[str, Any] = {}
    original = engine.level_preview

    def _spy(network: Any, limits: Any, *, splittable: Any = None) -> Any:
        seen["splittable"] = splittable
        return original(network, limits, splittable=splittable)

    monkeypatch.setattr(engine, "level_preview", _spy)

    await _level([_row(uuid.uuid4(), 2)], [], {"crew": 1})

    assert seen["splittable"] == set()
