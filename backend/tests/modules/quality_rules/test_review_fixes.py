"""Edge cases found in review: time-zone day skew, wildcard patterns, closing a serious NCR."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.bim_requirements.validators import PatternCompilesRule
from app.modules.construction_control.validators import EvidenceDatesRule
from app.modules.site_prep.validators import CompletedNotInFutureRule
from app.modules.site_supervision.rules import VisitNotInFutureRule

TODAY = "2026-11-04"


def _ctx(data):
    return ValidationContext(data=data, metadata={"locale": "en", "today": TODAY})


@pytest.mark.asyncio
async def test_a_record_dated_with_the_local_day_east_of_utc_is_not_in_the_future():
    # UTC+14 is already 2026-11-05 while UTC is still 2026-11-04.
    item = {"item": {"completed_date": "2026-11-05"}}
    assert (await CompletedNotInFutureRule().validate(_ctx(item)))[0].passed
    visit = {"visit": {"status": "conducted", "actual_date": "2026-11-05"}}
    assert (await VisitNotInFutureRule().validate(_ctx(visit)))[0].passed
    insp = {"inspection": {"id": "i", "performed_at": "2026-11-05"}}
    assert (await EvidenceDatesRule().validate(_ctx(insp)))[0].passed


@pytest.mark.asyncio
async def test_two_days_ahead_is_still_in_the_future():
    visit = {"visit": {"status": "conducted", "actual_date": "2026-11-06"}}
    assert not (await VisitNotInFutureRule().validate(_ctx(visit)))[0].passed
    item = {"item": {"completed_date": "2026-11-06"}}
    assert not (await CompletedNotInFutureRule().validate(_ctx(item)))[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pattern", "passes"),
    [
        ("*concrete*", True),
        ("300*", True),
        (r"^[A-Z]{2}\d+$", True),
        (r"\p{L}+", True),
        ("(unclosed", False),
        ("a{2", True),
        ("(?P<x", False),
    ],
)
async def test_pattern_rule_accepts_wildcards_and_xsd_classes(pattern, passes):
    row = {"row": 1, "property_name": "Material", "constraint_def": {"pattern": pattern}}
    results = await PatternCompilesRule().validate(_ctx({"requirements": [row]}))
    assert all(r.passed for r in results) is passes


@pytest.mark.asyncio
async def test_closing_a_serious_ncr_without_root_cause_is_refused_even_after_its_actions_moved_it_on(
    client, admin_auth, project_id
):
    _, h = admin_auth
    body = {"project_id": project_id, "title": "Cracked slab", "description": "S3", "severity": "major"}
    made = await client.post("/api/v1/qms/ncrs", json=body, headers=h)
    assert made.status_code == 201, made.text
    ncr_id = made.json()["id"]
    action = await client.post(f"/api/v1/qms/ncrs/{ncr_id}/actions", json={"description": "Core and repair"}, headers=h)
    assert action.status_code == 201, action.text
    await client.patch(f"/api/v1/qms/ncrs/{ncr_id}", json={"status": "action_pending"}, headers=h)
    done = await client.post(f"/api/v1/qms/ncrs/{ncr_id}/actions/{action.json()['id']}/verify", headers=h)
    assert done.status_code == 200, done.text
    closed = await client.post(f"/api/v1/qms/ncrs/{ncr_id}/close", headers=h)
    assert closed.status_code == 422, closed.text
    assert [e["rule_id"] for e in closed.json()["detail"]["errors"]] == ["qms.ncr_root_cause"]
    fixed = await client.patch(f"/api/v1/qms/ncrs/{ncr_id}", json={"root_cause": "Early formwork removal"}, headers=h)
    assert fixed.status_code == 200, fixed.text
    assert (await client.post(f"/api/v1/qms/ncrs/{ncr_id}/close", headers=h)).status_code == 200
