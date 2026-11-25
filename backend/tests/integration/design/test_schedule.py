"""R10: a schedule from model revisions, written into the ERP's schedule module with sourced productivity rates."""

from __future__ import annotations

import copy
import json
import math
import uuid
from decimal import Decimal

import pytest

from .conftest import make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, WALL, _linked_project, _upload

pytestmark = pytest.mark.asyncio
WALL_1OG = "b1/s01/wall-ext-N/0"


def _rates_doc():
    from app.modules.design import schedule as sch

    return json.loads((sch.DATA / "de_residential_multi.json").read_text(encoding="utf-8"))


# ── rates file and formula: no app needed ───────────────────────────────────


async def test_shipped_rates_are_sourced_or_flagged():
    from app.modules.design import rules
    from app.modules.design import schedule as sch

    doc = sch.rates_for("DE", "residential_multi")
    assert doc is not None and sch.rates_for("FR", "residential_multi") is None
    rule_ids = {r["id"] for r in rules.starter_set("DE")["rules"]}
    assert set(doc["rates"]) == rule_ids  # every estimate rule is either rated, flagged missing or not scheduled
    sourced = missing = 0
    for code, e in doc["rates"].items():
        if "not_scheduled" in e:
            continue
        r = e["labour_h_per_unit"]
        if r is None:
            missing += 1
            assert e["missing"].strip()
            continue
        sourced += 1
        src = r["source"]
        assert src["url"].startswith("https://") and src["retrieved"] == "2026-11-13" and src["published"]
        # the number used is printed in the quote, in the source's own decimal notation
        nums = [r["value"]] if "value" in r else [r["low"], r["high"]]
        for n in nums:
            shown = (f"{n:.2f}" if isinstance(n, float) else str(n)).replace(".", ",")
            assert shown in src["quote"], (code, shown)
    assert (sourced, missing) == (4, 8)
    text = json.dumps(doc, ensure_ascii=False).lower()
    for banned in ("poroton", "filigran", "plümecke", "arh-tabellen"):
        assert banned not in text  # no product or handbook brand names in shipped data


@pytest.mark.parametrize(
    "edit, msg",
    [
        (lambda d: d["rates"]["wall_ext"]["labour_h_per_unit"]["source"].pop("url"), "source.url"),
        (lambda d: d["rates"]["wall_ext"]["labour_h_per_unit"]["source"].update(quote=""), "source.quote"),
        (lambda d: d["rates"]["wall_ext"]["labour_h_per_unit"]["source"].update(published="recently"), "dates"),
        (lambda d: d["rates"]["wall_ext"]["labour_h_per_unit"].update(value=-1), "positive"),
        (lambda d: d["rates"]["slab"]["labour_h_per_unit"].update(use="mid"), "use = low | high"),
        (lambda d: d["rates"]["door"].update(missing=""), "needs a reason"),
        (lambda d: d["rates"]["door"].pop("labour_h_per_unit"), "is required"),
        (lambda d: d["logic"]["slab"].update(after=["nonsense"]), "unknown rule"),
        (lambda d: d["logic"]["roof"].update(after_below=["slab"]), "after_below"),
    ],
)
async def test_rates_without_a_source_are_refused(edit, msg):
    from app.modules.design import schedule as sch

    doc = copy.deepcopy(_rates_doc())
    edit(doc)
    with pytest.raises(sch.RatesError, match=msg):
        sch.validate_rates(doc)


async def test_duration_formula():
    from app.modules.design.schedule import duration_days

    assert duration_days(Decimal("82.5"), Decimal("0.78"), 4, 8) == 3  # 64.35 h / 32 h = 2.01 -> 3
    assert duration_days(Decimal("80.24"), Decimal("6"), 4, 8) == 16  # 481.44 h / 32 h = 15.05 -> 16
    assert duration_days(Decimal("0.01"), Decimal("0.78"), 4, 8) == 1
    assert duration_days(Decimal(0), Decimal("0.78"), 4, 8) == 0


# ── with the ERP ────────────────────────────────────────────────────────────


def _days(qty, rate, crew):
    return math.ceil(Decimal(str(qty)) * Decimal(str(rate)) / (crew * 8))


def _rows_upper():
    """R2: the ground-floor wall plus the same wall on the first floor."""
    rows = example_rows()
    w = copy.deepcopy(next(r for r in rows if r["element_key"] == WALL))
    w.update(
        id=WALL_1OG,
        stable_id=WALL_1OG,
        element_key=WALL_1OG,
        storey="1.OG",
        bbox_min_z=3.0,
        bbox_max_z=5.8,
        geometry_hash="aa11bb22cc33dd44",
    )
    return [*rows, w]


async def _activities(schedule_id):
    from app.database import async_session_factory
    from app.modules.schedule.service import ScheduleService

    async with async_session_factory() as s:
        acts, _ = await ScheduleService(s).activity_repo.list_for_schedule(uuid.UUID(schedule_id), limit=None)
        return acts


async def _set_duration(activity_id, days):
    from app.database import async_session_factory
    from app.modules.schedule.schemas import ActivityUpdate
    from app.modules.schedule.service import ScheduleService

    async with async_session_factory() as s:
        svc = ScheduleService(s)
        a = await svc.get_activity(uuid.UUID(activity_id))
        sched = await svc.get_schedule(a.schedule_id)
        end = await svc.working_end_date(sched.project_id, None, a.start_date[:10], days)
        await svc.update_activity(a.id, ActivityUpdate(duration_days=days, end_date=end))
        await s.commit()


async def _project_with_schedule(client, *, mode=None):
    """R1 accepted, estimate rules run, design schedule set up from R1; R2 (wall on 1.OG added) shared."""
    uid, h, pid, tok = await _linked_project(client)
    if mode:
        assert (
            await client.put(f"{BASE}/projects/{pid}/change-orders/settings", json={"mode": mode}, headers=h)
        ).status_code == 200
    rows1 = example_rows()
    d1, m1 = package(pid, rows1)
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=h)).status_code == 200
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    s = await client.post(f"{BASE}/projects/{pid}/schedule/setup", json={"start_date": "2027-03-01"}, headers=h)
    assert s.status_code == 201, s.text
    d2, _ = package(pid, _rows_upper(), parent_id=m1["revision_id"], parent_rows=rows1)
    r2 = (await _upload(client, pid, tok, d2)).json()["revision_id"]
    return uid, h, pid, tok, r1, r2, s.json(), (await client.get(est, headers=h)).json()


async def test_setup_plans_activities_from_the_estimate_positions(client):
    uid, h, pid, tok, r1, r2, sch, est = await _project_with_schedule(client)
    pos = {p["rule"]: p["position_id"] for p in est["positions"]}
    assert sch["schedule"] is True and sch["start"] == "2027-03-01" and sch["complete"] is False
    acts = {(a["rule"], a["storey"]): a for a in sch["activities"]}
    assert set(acts) == {("wall_ext", "EG"), ("slab", "EG")}
    wall, slab = acts[("wall_ext", "EG")], acts[("slab", "EG")]
    assert wall["days"] == _days("82.5", "0.78", 4) == 3 and wall["boq_position_ids"] == [pos["wall_ext"]]
    # the slab is scheduled on its concrete volume (the rate is per m3), at the upper end of the published range
    assert slab["days"] == _days("80.24", 6, 4) == 16 and slab["boq_position_ids"] == [pos["slab"]]
    pv = slab["provenance"]
    assert pv["assumption"] is True and pv["crew_source"] == "erp_default_gang" and pv["quantity_field"] == "volume_m3"
    assert pv["range"] == {"low": 4, "high": 6, "use": "high"} and pv["source"]["url"].startswith("https://")
    assert wall["provenance"]["crew_source"] == "source" and "ceil(82.5" in wall["provenance"]["worked"]
    # links: the slab waits for the walls of its storey
    [a_wall] = [a for a in await _activities(sch["schedule_id"]) if a.name.startswith("Außenwände")]
    [a_slab] = [a for a in await _activities(sch["schedule_id"]) if a.name.startswith("Decken")]
    assert [d["activity_id"] for d in a_slab.dependencies] == [str(a_wall.id)]
    assert a_slab.start_date > a_wall.start_date and a_wall.start_date[:10] == "2027-03-01"
    assert a_wall.metadata_["design"]["rule"] == "wall_ext"
    # nothing guessed: rules without a sourced rate get no activity and are listed
    assert {m["rule"] for m in sch["rate_missing"]} == {
        "site_prep",
        "window",
        "door",
        "stair",
        "roof",
        "finishes",
        "services",
        "site_works",
    }
    assert {n["rule"] for n in sch["not_scheduled"]} == {"reinforcement", "ancillary"}
    # a second setup is refused
    again = await client.post(f"{BASE}/projects/{pid}/schedule/setup", headers=h)
    assert again.status_code == 409


async def test_impact_equals_schedule_after_accept_and_overrides_survive(client):
    uid, h, pid, tok, r1, r2, sch, _ = await _project_with_schedule(client)
    slab_id = next(a["activity_id"] for a in sch["activities"] if a["rule"] == "slab")
    await _set_duration(slab_id, 20)  # a person plans the slab longer
    imp = (await client.get(f"{BASE}/revisions/{r2}/schedule-impact", headers=h)).json()
    assert imp["schema"] == "ddc-schedule-impact/1" and imp["schedule"] is True and imp["complete"] is False
    rows = {(r["rule"], r["storey"]): r for r in imp["rows"]}
    new_wall = rows[("wall_ext", "1.OG")]
    assert new_wall["new_activity"] and new_wall["new_days"] == 3 and new_wall["current_days"] is None
    slab = rows[("slab", "EG")]
    assert slab["override"] and slab["new_days"] == 20 and slab["model_days_new"] == 16 and "override" in slab["flags"]
    t = imp["totals"]
    assert t["delta_days"] > 0 and t["after_finish"] > t["current_finish"] and t["activities_added"] == 1
    assert t["overrides_kept"] == 1

    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/schedule", headers=h)).json()
    assert after["revision_id"] == r2 and after["finish"] == t["after_finish"] and after["days"] == t["after_days"]
    acts = {(a["rule"], a["storey"]): a for a in after["activities"]}
    assert acts[("slab", "EG")]["days"] == 20 and acts[("slab", "EG")]["model_days"] == 16
    assert acts[("slab", "EG")]["override"] and "override" in acts[("slab", "EG")]["flags"]
    up = acts[("wall_ext", "1.OG")]
    assert up["days"] == 3 and up["start"] >= acts[("slab", "EG")]["end"]  # after the slab below
    # nothing is pending any more: the same revision has no delta against itself
    again = (await client.get(f"{BASE}/revisions/{r2}/schedule-impact", headers=h)).json()
    assert again["totals"]["delta_days"] == 0


async def test_activity_no_longer_in_the_model_is_kept_at_zero(client):
    uid, h, pid, tok, r1, r2, sch, _ = await _project_with_schedule(client)
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    # R3 drops the first-floor wall again
    rows2 = _rows_upper()
    d3, _ = package(pid, example_rows(), parent_id=r2, parent_rows=rows2)
    r3 = (await _upload(client, pid, tok, d3)).json()["revision_id"]
    imp = (await client.get(f"{BASE}/revisions/{r3}/schedule-impact", headers=h)).json()
    row = next(r for r in imp["rows"] if (r["rule"], r["storey"]) == ("wall_ext", "1.OG"))
    assert row["new_days"] == 0 and "no_match" in row["flags"] and row["delta_days"] == -3
    assert imp["totals"]["delta_days"] < 0
    assert (await client.post(f"{BASE}/revisions/{r3}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/schedule", headers=h)).json()
    up = next(a for a in after["activities"] if (a["rule"], a["storey"]) == ("wall_ext", "1.OG"))
    assert up["days"] == 0 and "no_match" in up["flags"]  # kept, never deleted
    # R4 brings the wall back: the same activity works again for its full duration
    d4, _ = package(pid, _rows_upper(), parent_id=r3, parent_rows=example_rows())
    r4 = (await _upload(client, pid, tok, d4)).json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r4}/accept", headers=h)).status_code == 200
    back = (await client.get(f"{BASE}/projects/{pid}/schedule", headers=h)).json()
    again = next(a for a in back["activities"] if (a["rule"], a["storey"]) == ("wall_ext", "1.OG"))
    assert again["activity_id"] == up["activity_id"] and again["days"] == 3 and "no_match" not in again["flags"]
    [act] = [a for a in await _activities(sch["schedule_id"]) if str(a.id) == up["activity_id"]]
    assert act.activity_type == "task"


async def test_crew_setting_and_roles(client):
    uid, h, pid, tok, r1, r2, sch, _ = await _project_with_schedule(client)
    url = f"{BASE}/projects/{pid}/schedule/settings"
    assert (await client.put(url, json={"crews": {"slab": 8}}, headers=tok)).status_code == 403
    _, other = await make_user(client)
    assert (await client.put(url, json={"crews": {"slab": 8}}, headers=other)).status_code in (403, 404)
    assert (await client.get(f"{BASE}/projects/{pid}/schedule", headers=other)).status_code in (403, 404)
    assert (await client.put(url, json={"crews": {"nonsense": 2}}, headers=h)).status_code == 422
    assert (await client.put(url, json={"crews": {"slab": 99}}, headers=h)).status_code == 422
    ok = await client.put(url, json={"crews": {"slab": 8}}, headers=h)
    assert ok.status_code == 200 and ok.json() == {"crews": {"slab": 8}}
    imp = (await client.get(f"{BASE}/revisions/{r2}/schedule-impact", headers=tok)).json()  # the editor may read
    slab = next(r for r in imp["rows"] if r["rule"] == "slab")
    assert (
        slab["model_days_new"] == _days("80.24", 6, 8) == 8 and slab["provenance"]["crew_source"] == "project_setting"
    )
    # setup needs a manager and an estimate
    uid2, h2, pid2, tok2 = await _linked_project(client)
    assert (await client.post(f"{BASE}/projects/{pid2}/schedule/setup", headers=tok2)).status_code == 403
    assert (await client.post(f"{BASE}/projects/{pid2}/schedule/setup", headers=h2)).status_code == 409
    assert (await client.get(f"{BASE}/projects/{pid2}/schedule", headers=h2)).json() == {
        "schedule": False,
        "estimate": False,
        "rates_available": False,
    }


async def test_change_order_carries_the_schedule_delta(client):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.changeorders.models import ChangeOrder

    uid, h, pid, tok, r1, r2, sch, _ = await _project_with_schedule(client, mode="always")
    imp = (await client.get(f"{BASE}/revisions/{r2}/schedule-impact", headers=h)).json()
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    async with async_session_factory() as s:
        order = (
            await s.execute(
                select(ChangeOrder).where(ChangeOrder.project_id == pid, ChangeOrder.title.like("Design revision R2%"))
            )
        ).scalar_one()
    meta = order.metadata_["design"]["schedule"]
    assert meta["delta_days"] == imp["totals"]["delta_days"] > 0
    assert order.schedule_impact_days == imp["totals"]["delta_days"]
    assert meta["complete"] is False and "roof" in meta["rate_missing"]
    assert "Schedule: finish" in order.description and "no sourced productivity rate" in order.description


async def test_no_schedule_means_no_delta(client):
    uid, h, pid, tok = await _linked_project(client)
    d1, _ = package(pid, example_rows())
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    imp = (await client.get(f"{BASE}/revisions/{r1}/schedule-impact", headers=h)).json()
    assert imp == {"schema": "ddc-schedule-impact/1", "revision_id": r1, "schedule": False}


async def _model_of(revision_id):
    from app.database import async_session_factory
    from app.modules.design.models import DesignRevision

    async with async_session_factory() as s:
        return (await s.get(DesignRevision, uuid.UUID(revision_id))).bim_model_id


async def test_design_activities_drive_4d_and_5d(client):
    """Each design activity links the elements it builds (4D) and carries its position money (5D)."""
    from datetime import date as _date

    from app.database import async_session_factory
    from app.modules.boq.models import Position
    from app.modules.schedule.service_4d import ScheduleSnapshotService

    uid, h, pid, tok, r1, r2, sch, est = await _project_with_schedule(client)
    wall_pos = next(a for a in sch["activities"] if a["rule"] == "wall_ext")["boq_position_ids"][0]
    async with async_session_factory() as s:
        pos = await s.get(Position, uuid.UUID(wall_pos))
        pos.unit_rate = "50"  # a priced wall: EUR 50 per unit
        await s.commit()
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/schedule", headers=h)).json()
    acts = {(a["rule"], a["storey"]): a for a in after["activities"]}
    eg, og = acts[("wall_ext", "EG")], acts[("wall_ext", "1.OG")]
    model_id = await _model_of(r2)
    sid = uuid.UUID(after["schedule_id"])
    async with async_session_factory() as s:
        snap = ScheduleSnapshotService(s)
        before = await snap.snapshot(sid, _date.fromisoformat("2027-02-01"), model_id)
        assert before[WALL] == "not_started" and before[WALL_1OG] == "not_started"
        mid = await snap.snapshot(sid, _date.fromisoformat(og["start"][:10]), model_id)
        assert mid[WALL_1OG] == "in_progress" and mid[WALL] == "delayed"  # EG wall finished on paper, 0 % recorded
        cost = await snap.cost_snapshot(sid, _date.fromisoformat("2030-01-01"), model_id)
        by_act = {str(a.id): a for a in await _list_acts(s, sid)}
        pos = await s.get(Position, uuid.UUID(eg["boq_position_ids"][0]))
        total = Decimal(str(pos.total))
    # one wall position, two storeys: the money splits by quantity and adds back to the position total
    eg_cost, og_cost = by_act[eg["activity_id"]].cost_planned, by_act[og["activity_id"]].cost_planned
    assert total > 0 and abs(eg_cost + og_cost - total) <= Decimal("0.01")
    q_eg, q_og = Decimal(eg["provenance"]["quantity"]), Decimal(og["provenance"]["quantity"])
    assert eg_cost == (total * q_eg / (q_eg + q_og)).quantize(Decimal("0.01"))
    assert cost["has_cost_data"] is True and Decimal(str(cost["totals"]["bac"])) >= total - Decimal("0.01")


async def _list_acts(s, sid):
    from app.modules.schedule.service import ScheduleService

    acts, _ = await ScheduleService(s).activity_repo.list_for_schedule(sid, limit=None)
    return acts


async def test_bill_quantity_edit_leaves_design_durations_to_the_model(client):
    """A BOQ quantity edit must not rescale a model-planned activity (it would read as a person's override)."""
    from app.database import async_session_factory
    from app.modules.schedule.boq_followup import follow_position_quantity

    uid, h, pid, tok, r1, r2, sch, est = await _project_with_schedule(client)
    slab = next(a for a in sch["activities"] if a["rule"] == "slab")
    async with async_session_factory() as s:
        moved = await follow_position_quantity(s, uuid.UUID(slab["boq_position_ids"][0]), old_quantity="1")
        await s.commit()
    assert moved == []
    again = (await client.get(f"{BASE}/projects/{pid}/schedule", headers=h)).json()
    now = next(a for a in again["activities"] if a["activity_id"] == slab["activity_id"])
    assert now["days"] == slab["days"] and not now["override"]
