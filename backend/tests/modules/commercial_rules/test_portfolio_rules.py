"""The ``portfolio`` rule set: each rule fires, a valid record passes, writes are gated."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.portfolio.validators import (
    PORTFOLIO_RULE_SET,
    CrossLinkEndpointsRule,
    CrossLinkLagRule,
    CrossLinkNoLoopRule,
    NodeCodeUniqueRule,
    NodeLevelOrderRule,
    register_portfolio_validation_rules,
)


def _n(**kw):
    base = {
        "id": "n1",
        "node_type": "programme",
        "code": "P-01",
        "parent_type": "portfolio",
        "child_types": ["subprogramme"],
        "sibling_codes": ["P-02"],
    }
    base.update(kw)
    return {"node": base}


def _l(**kw):
    base = {
        "id": "l1",
        "predecessor_schedule_id": "s1",
        "predecessor_activity_id": "a1",
        "successor_schedule_id": "s2",
        "successor_activity_id": "a2",
        "lag_days": 5,
        "duplicate": False,
        "reverse_exists": False,
    }
    base.update(kw)
    return {"cross_link": base}


async def _run(rule, data, locale="en"):
    return await rule().validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (NodeCodeUniqueRule, _n(code="p-02 "), "portfolio.node_code_unique", Severity.ERROR, _n()),
    (NodeLevelOrderRule, _n(parent_type="subprogramme"), "portfolio.node_level_order", Severity.ERROR, _n()),
    (NodeLevelOrderRule, _n(child_types=["portfolio"]), "portfolio.node_level_order", Severity.ERROR, _n()),
    (
        CrossLinkEndpointsRule,
        _l(successor_activity_id="a1", successor_schedule_id="s9"),
        "portfolio.link_endpoints_distinct",
        Severity.ERROR,
        _l(),
    ),
    (
        CrossLinkEndpointsRule,
        _l(successor_schedule_id="s1"),
        "portfolio.link_endpoints_distinct",
        Severity.WARNING,
        _l(),
    ),
    (CrossLinkNoLoopRule, _l(duplicate=True), "portfolio.link_no_duplicate_or_loop", Severity.ERROR, _l()),
    (CrossLinkNoLoopRule, _l(reverse_exists=True), "portfolio.link_no_duplicate_or_loop", Severity.ERROR, _l()),
    (CrossLinkLagRule, _l(lag_days=-500), "portfolio.link_lag_sane", Severity.WARNING, _l()),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "rule_id", "severity", "good"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, bad, rule_id, severity, good):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, good))


@pytest.mark.asyncio
async def test_a_rule_passes_when_its_section_is_absent_and_blank_codes_never_collide():
    assert all(r.passed for r in await _run(NodeCodeUniqueRule, _l()))
    assert all(r.passed for r in await _run(CrossLinkLagRule, _n()))
    assert all(r.passed for r in await _run(NodeCodeUniqueRule, _n(code="", sibling_codes=[""])))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(NodeCodeUniqueRule, _n(code="P-02"), "de") if not r.passed]
    assert "Knoten" in failed[0].message


def test_rule_set_is_registered():
    register_portfolio_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([PORTFOLIO_RULE_SET])}) == 5


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


@pytest.mark.asyncio
async def test_blocking_rules_reject_node_writes_with_code(client, admin_auth):
    _, h = admin_auth
    code = f"PF-{uuid.uuid4().hex[:6]}"
    root = await client.post(
        "/api/v1/portfolio/nodes/", json={"name": "Group", "node_type": "portfolio", "code": code}, headers=h
    )
    assert root.status_code == 201, root.text
    assert root.json()["validation_warnings"] == []
    rid = root.json()["id"]
    dup = await client.post(
        "/api/v1/portfolio/nodes/", json={"name": "Group 2", "node_type": "portfolio", "code": code}, headers=h
    )
    assert dup.status_code == 422, dup.text
    assert dup.json()["detail"]["error"] == "portfolio_rules_failed"
    assert _codes(dup) == {"portfolio.node_code_unique"}
    sub = await client.post(
        "/api/v1/portfolio/nodes/",
        json={"name": "Sub", "node_type": "subprogramme", "code": "S1", "parent_id": rid},
        headers=h,
    )
    assert sub.status_code == 201, sub.text
    upside = await client.post(
        "/api/v1/portfolio/nodes/",
        json={"name": "Big", "node_type": "portfolio", "code": "B1", "parent_id": sub.json()["id"]},
        headers=h,
    )
    assert upside.status_code == 422 and _codes(upside) == {"portfolio.node_level_order"}


@pytest.mark.asyncio
async def test_node_patch_blocks_an_introduced_error_and_spares_a_legacy_one(client, admin_auth):
    _, h = admin_auth
    tag = uuid.uuid4().hex[:6]
    a = (await client.post("/api/v1/portfolio/nodes/", json={"name": "A", "code": f"A-{tag}"}, headers=h)).json()
    b = (await client.post("/api/v1/portfolio/nodes/", json={"name": "B", "code": f"B-{tag}"}, headers=h)).json()
    clash = await client.patch(f"/api/v1/portfolio/nodes/{b['id']}/", json={"code": f"A-{tag}"}, headers=h)
    assert clash.status_code == 422 and _codes(clash) == {"portfolio.node_code_unique"}
    # a stored duplicate (written before the rules existed) does not freeze the node
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.portfolio.models import PortfolioNode

    async with async_session_factory() as s:
        await s.execute(update(PortfolioNode).where(PortfolioNode.id == uuid.UUID(b["id"])).values(code=f"A-{tag}"))
        await s.commit()
    renamed = await client.patch(f"/api/v1/portfolio/nodes/{b['id']}/", json={"name": "B renamed"}, headers=h)
    assert renamed.status_code == 200, renamed.text
    assert a["id"] != b["id"]


async def _schedule(client, h, label):
    proj = await client.post(
        "/api/v1/projects/", json={"name": f"PF-{label} {uuid.uuid4().hex[:6]}", "currency": "EUR"}, headers=h
    )
    assert proj.status_code == 201, proj.text
    sched = await client.post(
        "/api/v1/schedule/schedules/",
        json={"project_id": proj.json()["id"], "name": label, "start_date": "2026-05-01", "end_date": "2026-09-30"},
        headers=h,
    )
    assert sched.status_code == 201, sched.text
    sid = sched.json()["id"]
    acts = []
    for i, n in enumerate(("one", "two")):
        act = await client.post(
            f"/api/v1/schedule/schedules/{sid}/activities/",
            json={
                "name": f"{label} {n}",
                "wbs_code": f"01.0{i}",
                "start_date": "2026-05-04",
                "end_date": "2026-05-15",
                "activity_type": "task",
            },
            headers=h,
        )
        assert act.status_code == 201, act.text
        acts.append(act.json()["id"])
    return sid, acts


@pytest_asyncio.fixture(scope="module")
async def two_schedules(client, admin_auth):
    _, h = admin_auth
    a_sched, a_acts = await _schedule(client, h, "alpha")
    b_sched, b_acts = await _schedule(client, h, "beta")
    return {"h": h, "a": a_sched, "a_acts": a_acts, "b": b_sched, "b_acts": b_acts}


def _link(s, **over):
    body = {
        "predecessor_schedule_id": s["a"],
        "predecessor_activity_id": s["a_acts"][0],
        "successor_schedule_id": s["b"],
        "successor_activity_id": s["b_acts"][0],
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_cross_link_rules_gate_the_write(client, two_schedules):
    s = two_schedules
    ok = await client.post("/api/v1/portfolio/cross-links/", json=_link(s), headers=s["h"])
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    dup = await client.post("/api/v1/portfolio/cross-links/", json=_link(s), headers=s["h"])
    assert dup.status_code == 422, dup.text
    assert dup.json()["detail"]["error"] == "portfolio_rules_failed"
    assert _codes(dup) == {"portfolio.link_no_duplicate_or_loop"}
    back = await client.post(
        "/api/v1/portfolio/cross-links/",
        json=_link(
            s,
            predecessor_schedule_id=s["b"],
            predecessor_activity_id=s["b_acts"][0],
            successor_schedule_id=s["a"],
            successor_activity_id=s["a_acts"][0],
        ),
        headers=s["h"],
    )
    assert back.status_code == 422 and _codes(back) == {"portfolio.link_no_duplicate_or_loop"}


@pytest.mark.asyncio
async def test_cross_link_self_link_is_blocked_and_odd_lag_or_same_schedule_only_warn(client, two_schedules):
    s = two_schedules
    selfie = await client.post(
        "/api/v1/portfolio/cross-links/",
        json=_link(s, successor_schedule_id=s["a"], successor_activity_id=s["a_acts"][0]),
        headers=s["h"],
    )
    assert selfie.status_code == 422 and _codes(selfie) == {"portfolio.link_endpoints_distinct"}
    inside = await client.post(
        "/api/v1/portfolio/cross-links/",
        json=_link(s, successor_schedule_id=s["a"], successor_activity_id=s["a_acts"][1], lag_days=900),
        headers=s["h"],
    )
    assert inside.status_code == 201, inside.text
    assert {w["rule_id"] for w in inside.json()["validation_warnings"]} == {
        "portfolio.link_endpoints_distinct",
        "portfolio.link_lag_sane",
    }
