"""A position without a direct cost item: the ERP's Cost Match and assemblies are offered, a person confirms, the
source is recorded; unit or currency mismatches are listed but never applied."""

from __future__ import annotations

import uuid

import pytest

from .conftest import make_user
from .ddcrev import example_rows
from .test_design_revisions import BASE, _linked_project
from .test_estimate_costdb import _install, _set_project_region
from .test_estimate_edges import _publish, _summary
from .test_estimate_rules import D

pytestmark = pytest.mark.asyncio


async def _assembly(word, owner, *, unit="m2", currency="EUR", rate="150"):
    from app.database import async_session_factory
    from app.modules.assemblies.models import Assembly

    async with async_session_factory() as s:
        a = Assembly(
            code=f"ASM-{uuid.uuid4().hex[:8]}",
            name=f"{word} complete",
            description="",
            unit=unit,
            total_rate=rate,
            currency=currency,
            is_template=True,
            is_active=True,
            owner_id=owner,
        )
        s.add(a)
        await s.flush()
        aid = str(a.id)
        await s.commit()
    return aid


async def _setup(client):
    uid, h, pid, tok = await _linked_project(client)
    region, token = f"DE_T{uuid.uuid4().hex[:6]}", f"zq{uuid.uuid4().hex[:8]}"
    await _set_project_region(pid, region)
    await _publish(client, h, tok, pid, example_rows())
    est = await _install(client, h, pid, f"nomatch{uuid.uuid4().hex[:10]}")  # the estimate's own search finds nothing
    await client.post(f"{est}/run", headers=h)
    w = (await _summary(client, h, pid))["wall_ext"]
    assert D(w["unit_rate"]) == 0 and "cost_no_match" in w["flags"]
    return uid, h, pid, region, est, w


async def test_cost_match_suggestion_is_confirmed_by_a_person_and_the_source_is_kept(client):
    uid, h, pid, region, est, w = await _setup(client)
    pos = w["position_id"]
    word = max((x for x in w_description(await _estimate(client, h, pid), pos).split() if x.isalpha()), key=len)
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        good = CostItem(
            code=f"DSG-{uuid.uuid4().hex[:8]}",
            description=f"{word}",
            unit=w["unit"],
            rate="321.5",
            currency="EUR",
            source="custom",
            region=region,
            is_active=True,
        )
        wrong = CostItem(
            code=f"DSG-{uuid.uuid4().hex[:8]}",
            description=f"{word}",
            unit="m3" if w["unit"] != "m3" else "m2",
            rate="9",
            currency="EUR",
            source="custom",
            region=region,
            is_active=True,
        )
        s.add_all([good, wrong])
        await s.flush()
        good_id, wrong_id = str(good.id), str(wrong.id)
        await s.commit()
    s1 = await client.post(f"{est}/positions/{pos}/suggestions", headers=h)
    assert s1.status_code == 200, s1.text
    cm = s1.json()["cost_match"]
    assert cm is not None and cm["region"] == region and cm["result_id"] and cm["run_id"]
    by_id = {c["cost_item_id"]: c for c in cm["candidates"]}
    assert good_id in by_id and by_id[good_id]["usable"] is True
    if wrong_id in by_id:  # listed, never applied
        assert by_id[wrong_id]["usable"] is False and by_id[wrong_id]["unusable_reason"] == "unit"
    # asking applied nothing
    assert D((await _summary(client, h, pid))["wall_ext"]["unit_rate"]) == 0
    if wrong_id in by_id:
        bad = await client.post(
            f"{est}/positions/{pos}/confirm-suggestion",
            headers=h,
            json={"result_id": cm["result_id"], "cost_item_id": wrong_id},
        )
        assert bad.status_code == 422
    r = await client.post(
        f"{est}/positions/{pos}/confirm-suggestion",
        headers=h,
        json={"result_id": cm["result_id"], "cost_item_id": good_id},
    )
    assert r.status_code == 204, r.text
    w2 = (await _summary(client, h, pid))["wall_ext"]
    assert D(w2["unit_rate"]) == D("321.5") and "unpriced" not in w2["flags"]
    ci = w2["provenance"]["cost_item"]
    assert ci["cost_item_id"] == good_id and ci["auto"] is False
    assert ci["via"]["kind"] == "cost_match" and ci["via"]["result_id"] == cm["result_id"]
    assert ci["via"]["decision"] in ("confirmed", "overridden")

    from sqlalchemy import select

    from app.modules.cost_match.models import MatchDecision

    async with async_session_factory() as s:
        rows = (
            (await s.execute(select(MatchDecision).where(MatchDecision.result_id == uuid.UUID(cm["result_id"]))))
            .scalars()
            .all()
        )
    assert len(rows) == 1 and str(rows[0].decided_by) == str(uid) and str(rows[0].decided_cost_item_id) == good_id


async def _estimate(client, h, pid):
    return (await client.get(f"{BASE}/projects/{pid}/estimate", headers=h)).json()


def w_description(est_view, pos):
    return next(p["description"] for p in est_view["positions"] if p["position_id"] == pos)


async def test_assembly_is_offered_and_priced_only_on_confirmation_with_matching_unit_and_currency(client):
    uid, h, pid, region, est, w = await _setup(client)
    pos = w["position_id"]
    word = max((x for x in w_description(await _estimate(client, h, pid), pos).split() if x.isalpha()), key=len)
    good = await _assembly(word, uid)
    wrong_unit = await _assembly(word, uid, unit="m3" if w["unit"] != "m3" else "m2")
    wrong_cur = await _assembly(word, uid, currency="USD")
    s = (await client.post(f"{est}/positions/{pos}/suggestions", headers=h)).json()
    got = {a["assembly_id"]: a for a in s["assemblies"]}
    assert good in got and got[good]["usable"] is True and D(got[good]["rate"]) == 150
    assert wrong_unit not in got  # listed by the position's unit
    assert got[wrong_cur]["usable"] is False and got[wrong_cur]["unusable_reason"] == "currency"
    assert D((await _summary(client, h, pid))["wall_ext"]["unit_rate"]) == 0  # asking applied nothing
    bad = await client.post(f"{est}/positions/{pos}/confirm-suggestion", json={"assembly_id": wrong_cur}, headers=h)
    assert bad.status_code == 422
    ok = await client.post(f"{est}/positions/{pos}/confirm-suggestion", json={"assembly_id": good}, headers=h)
    assert ok.status_code == 204, ok.text
    w2 = (await _summary(client, h, pid))["wall_ext"]
    assert D(w2["unit_rate"]) == 150
    ci = w2["provenance"]["cost_item"]
    assert ci["assembly_id"] == good and ci["auto"] is False and ci["database"] == "assemblies"
    assert (await client.post(f"{est}/positions/{pos}/confirm-suggestion", json={}, headers=h)).status_code == 422


async def test_only_a_manager_asks_for_or_confirms_suggestions(client):
    uid, h, pid, region, est, w = await _setup(client)
    pos = w["position_id"]
    _, stranger = await make_user(client)
    assert (await client.post(f"{est}/positions/{pos}/suggestions", headers=stranger)).status_code in (403, 404)
    assert (
        await client.post(
            f"{est}/positions/{pos}/confirm-suggestion", json={"assembly_id": str(uuid.uuid4())}, headers=stranger
        )
    ).status_code in (403, 404)
