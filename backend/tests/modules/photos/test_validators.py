"""Rule set ``photos``: each rule passes on good data and fails on bad data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.photos import validators as v

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def _ctx(photos=None, suggestions=None, **extra) -> ValidationContext:
    data = {"now": NOW.isoformat(), "photos": photos or [], "suggestions": suggestions or [], **extra}
    return ValidationContext(data=data)


def _photo(pid="p1", **kw):
    return {"id": pid, "filename": f"{pid}.jpg", "links": [], **kw}


async def _passed(rule, ctx) -> list[bool]:
    return [r.passed for r in await rule.validate(ctx)]


@pytest.mark.asyncio
async def test_taken_at_present() -> None:
    rule = v.TakenAtPresent()
    assert await _passed(rule, _ctx([_photo(taken_at=NOW.isoformat())])) == [True]
    (result,) = await rule.validate(_ctx([_photo(taken_at=None)]))
    assert not result.passed and result.severity == Severity.WARNING
    assert "p1.jpg" in result.message


@pytest.mark.asyncio
async def test_taken_at_plausible() -> None:
    rule = v.TakenAtPlausible()
    start = (NOW - timedelta(days=100)).isoformat()
    ok = _photo(taken_at=(NOW - timedelta(days=3)).isoformat())
    tz_skew = _photo("p2", taken_at=(NOW + timedelta(hours=20)).isoformat())
    future = _photo("p3", taken_at=(NOW + timedelta(days=3)).isoformat())
    ancient = _photo("p4", taken_at=(NOW - timedelta(days=800)).isoformat())
    assert await _passed(rule, _ctx([ok, tz_skew, future, ancient], project_start=start)) == [True, True, False, False]
    assert (await rule.validate(_ctx([future])))[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_gps_in_project_area() -> None:
    rule = v.GpsInProjectArea()
    anchor = {"lat": 52.52, "lon": 13.405}
    near = _photo(gps_lat=52.521, gps_lon=13.406, gps_accuracy_m=8)
    far = _photo("p2", gps_lat=48.137, gps_lon=11.575)
    vague = _photo("p3", gps_lat=52.52, gps_lon=13.405, gps_accuracy_m=120)
    assert await _passed(rule, _ctx([near, far, vague], anchor=anchor)) == [True, False, False]
    # Without a site anchor only the accuracy can be judged.
    assert await _passed(rule, _ctx([far, vague])) == [False]


@pytest.mark.asyncio
async def test_link_target_exists() -> None:
    rule = v.LinkTargetExists()
    good = _photo(links=[{"target_kind": "punch_item", "target_id": "a", "target_exists": True}])
    bad = _photo("p2", links=[{"target_kind": "boq_position", "target_id": "b", "target_exists": False}])
    results = await rule.validate(_ctx([good, bad]))
    assert [r.passed for r in results] == [True, False]
    assert results[1].severity == Severity.ERROR
    assert results[1].details["target_id"] == "b"


@pytest.mark.asyncio
async def test_duplicate_sha256() -> None:
    rule = v.DuplicateSha256()
    photos = [_photo("a", sha256="x"), _photo("b", sha256="x"), _photo("c", sha256="y"), _photo("d")]
    results = await rule.validate(_ctx(photos))
    assert [(r.element_ref, r.passed) for r in results] == [("a", False), ("b", False), ("c", True)]
    assert results[0].severity == Severity.INFO


@pytest.mark.asyncio
async def test_evidence_grade_warns_only_on_punch_or_inspection_proof() -> None:
    rule = v.EvidenceGrade()
    full = {
        "sha256": "x",
        "captured_at": {"source": "device"},
        "location": {"source": "device", "accuracy_m": 5},
    }
    ok = _photo(evidence=full)
    loose = _photo("p2", evidence=None)
    proof = _photo("p3", evidence=None, links=[{"target_kind": "punch_item", "target_id": "i"}])
    results = await rule.validate(_ctx([ok, loose, proof]))
    assert [r.passed for r in results] == [True, False, False]
    assert [r.severity for r in results[1:]] == [Severity.INFO, Severity.WARNING]


@pytest.mark.asyncio
async def test_ai_unreviewed() -> None:
    rule = v.AIUnreviewed()
    fresh = {"id": "s1", "photo_id": "p", "kind": "tags", "status": "pending", "created_at": NOW.isoformat()}
    stale = {**fresh, "id": "s2", "created_at": (NOW - timedelta(days=9)).isoformat()}
    done = {**stale, "id": "s3", "status": "accepted"}
    assert await _passed(rule, _ctx(suggestions=[fresh, stale, done])) == [True, False]


@pytest.mark.asyncio
async def test_hazard_open() -> None:
    rule = v.HazardOpen()
    hazard = {"id": "s1", "photo_id": "p1", "kind": "hazard", "status": "accepted", "payload": {"hazard": "Open edge"}}
    pending = {**hazard, "id": "s2", "status": "pending"}
    without = _ctx([_photo()], [hazard, pending])
    assert await _passed(rule, without) == [False]
    observed = _photo(links=[{"target_kind": "safety_obs", "target_id": "o"}])
    assert await _passed(rule, _ctx([observed], [hazard])) == [True]


@pytest.mark.asyncio
async def test_file_reachable() -> None:
    rule = v.FileReachable()
    remote = _photo("p3")  # a URL photo carries no reachability verdict
    results = await rule.validate(_ctx([_photo(file_reachable=True), _photo("p2", file_reachable=False), remote]))
    assert [r.passed for r in results] == [True, False]
    assert results[1].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_rule_set_registers_and_reports_a_traffic_light() -> None:
    from app.core.validation.engine import rule_registry

    v.register_photos_rules()
    registered = {r.rule_id for r in rule_registry.get_rules_for_sets([v.RULE_SET])}
    assert set(v.RULE_IDS) <= registered
    report = await v.evaluate(
        {"now": NOW.isoformat(), "photos": [_photo(taken_at=None, file_reachable=False)], "suggestions": []}
    )
    assert report["status"] == "errors"
    assert {f["rule_id"] for f in report["findings"]} >= {"photos.taken_at_present", "photos.file_reachable"}
