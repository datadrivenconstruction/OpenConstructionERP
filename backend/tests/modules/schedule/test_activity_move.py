"""Move an activity with its subtree among siblings or into another section."""

from __future__ import annotations

import uuid

import pytest

from app.modules.schedule.activity_move import MoveError, plan_move
from app.modules.schedule.schemas import ActivityCreate, ActivityMove
from tests.modules.schedule.test_cpm_unified import _api, _perms  # noqa: F401


def _outline():
    """Two sections: 1 (1.1 with child 1.1.1, 1.2, 1.3) and 2 (2.1)."""
    ids = {name: uuid.uuid4() for name in ("s1", "a", "a1", "b", "c", "s2", "d")}
    rows = [
        (ids["s1"], None, 0, "1"),
        (ids["a"], ids["s1"], 1, "1.1"),
        (ids["a1"], ids["a"], 2, "1.1.1"),
        (ids["b"], ids["s1"], 3, "1.2"),
        (ids["c"], ids["s1"], 4, "1.3"),
        (ids["s2"], None, 5, "2"),
        (ids["d"], ids["s2"], 6, "2.1"),
    ]
    return ids, rows


def test_move_up_among_siblings_permutes_codes_and_keeps_the_subtree_together():
    ids, rows = _outline()
    plan = plan_move(ids["c"], rows, target_id=ids["a"], position="before")
    assert plan.parent_id == ids["s1"]
    assert plan.order == [ids["s1"], ids["c"], ids["a"], ids["a1"], ids["b"], ids["s2"], ids["d"]]
    assert plan.codes == {ids["c"]: "1.1", ids["a"]: "1.2", ids["a1"]: "1.2.1", ids["b"]: "1.3"}


def test_move_down_after_a_sibling_takes_its_subtree_along():
    ids, rows = _outline()
    plan = plan_move(ids["a"], rows, target_id=ids["c"], position="after")
    assert plan.order == [ids["s1"], ids["b"], ids["c"], ids["a"], ids["a1"], ids["s2"], ids["d"]]
    assert plan.codes == {ids["b"]: "1.1", ids["c"]: "1.2", ids["a"]: "1.3", ids["a1"]: "1.3.1"}


def test_move_into_another_section_takes_the_next_code_and_rewrites_descendants():
    ids, rows = _outline()
    plan = plan_move(ids["a"], rows, parent_id=ids["s2"])
    assert plan.parent_id == ids["s2"]
    assert plan.order == [ids["s1"], ids["b"], ids["c"], ids["s2"], ids["d"], ids["a"], ids["a1"]]
    assert plan.codes == {ids["a"]: "2.2", ids["a1"]: "2.2.1"}


def test_move_beside_a_target_in_another_section_lands_in_that_section():
    ids, rows = _outline()
    plan = plan_move(ids["b"], rows, target_id=ids["d"], position="before")
    assert plan.parent_id == ids["s2"]
    assert plan.order.index(ids["b"]) == plan.order.index(ids["d"]) - 1
    assert plan.codes[ids["b"]] == "2.1"
    assert plan.codes[ids["d"]] == "2.2"


def test_a_section_cannot_go_under_itself_or_a_descendant():
    ids, rows = _outline()
    with pytest.raises(MoveError, match="under itself") as under:
        plan_move(ids["s1"], rows, parent_id=ids["a1"])
    assert under.value.status == 422
    with pytest.raises(MoveError, match="next to itself"):
        plan_move(ids["s1"], rows, target_id=ids["b"], position="after")
    with pytest.raises(MoveError, match="under itself"):
        plan_move(ids["s1"], rows, parent_id=ids["s1"])


def test_unknown_ids_are_404_and_the_destination_must_be_unambiguous():
    ids, rows = _outline()
    with pytest.raises(MoveError) as missing:
        plan_move(ids["a"], rows, parent_id=uuid.uuid4())
    assert missing.value.status == 404
    with pytest.raises(MoveError, match="exactly one"):
        plan_move(ids["a"], rows)
    with pytest.raises(MoveError, match="position"):
        plan_move(ids["a"], rows, target_id=ids["b"])


def test_moving_to_the_place_it_already_holds_changes_nothing():
    ids, rows = _outline()
    plan = plan_move(ids["b"], rows, target_id=ids["c"], position="before")
    assert plan.changed is False


def test_siblings_with_mixed_codes_keep_their_codes():
    ids, rows = _outline()
    rows = [(i, p, o, "X" if i == ids["b"] else c) for i, p, o, c in rows]
    plan = plan_move(ids["c"], rows, target_id=ids["a"], position="before")
    assert plan.codes == {}


def test_to_top_level_appends_after_the_last_section():
    ids, rows = _outline()
    plan = plan_move(ids["a"], rows, to_top_level=True)
    assert plan.parent_id is None
    assert plan.order[-2:] == [ids["a"], ids["a1"]]


def test_schema_needs_exactly_one_destination():
    with pytest.raises(ValueError, match="exactly one"):
        ActivityMove()
    with pytest.raises(ValueError, match="position is required"):
        ActivityMove(target_id=uuid.uuid4())
    with pytest.raises(ValueError, match="only applies"):
        ActivityMove(parent_id=uuid.uuid4(), position="after")


async def _make(svc, sched, name, code, parent=None, order=0):
    return await svc.create_activity(
        ActivityCreate(
            schedule_id=sched.id,
            name=name,
            start_date="2026-05-01",
            end_date="2026-05-08",
            duration_days=5,
            parent_id=parent,
            wbs_code=code,
            sort_order=order,
        )
    )


@pytest.mark.asyncio
async def test_api_moves_and_renumbers_and_rejects_a_cycle():
    async with _api("editor") as (client, svc, sched):
        s1 = await _make(svc, sched, "Section", "1", order=0)
        a = await _make(svc, sched, "A", "1.1", s1.id, 1)
        b = await _make(svc, sched, "B", "1.2", s1.id, 2)
        for row in svc.activity_repo.rows.values():  # the stub has no column defaults
            row.is_critical = False
            row.client_visible = False

        moved = await client.post(
            f"/schedule/activities/{b.id}/move/", json={"target_id": str(a.id), "position": "before"}
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["wbs_code"] == "1.1"
        assert svc.activity_repo.rows[a.id].wbs_code == "1.2"
        assert svc.activity_repo.rows[b.id].sort_order < svc.activity_repo.rows[a.id].sort_order

        cycle = await client.post(f"/schedule/activities/{s1.id}/move/", json={"parent_id": str(a.id)})
        assert cycle.status_code == 422
        bad = await client.post(f"/schedule/activities/{a.id}/move/", json={})
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_a_viewer_cannot_move():
    async with _api("viewer") as (client, svc, sched):
        a = await _make(svc, sched, "A", "1")
        r = await client.post(f"/schedule/activities/{a.id}/move/", json={"to_top_level": True})
        assert r.status_code == 403
