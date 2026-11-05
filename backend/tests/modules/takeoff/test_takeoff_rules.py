# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Takeoff measurement rule set: every rule fires, a valid measurement passes, and the write points enforce it."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import ValidationContext
from app.database import async_session_factory
from app.modules.takeoff.models import TakeoffMeasurement
from app.modules.takeoff.validators import (
    TakeoffGeometryMatchesTypeRule,
    TakeoffLinkNeedsConfirmedRule,
    TakeoffScaleStatedRule,
    TakeoffUnitMatchesTypeRule,
    TakeoffValueInRangeRule,
    unit_family,
)
from tests.modules.ncr.conftest import admin_auth, app_instance, client, project_id  # noqa: F401

SQUARE = [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}, {"x": 0, "y": 100}]


def _m(**kw: object) -> dict:
    base = {
        "id": "m1",
        "type": "area",
        "review_status": "confirmed",
        "measurement_value": 12.5,
        "measurement_unit": "m2",
        "volume": None,
        "points": SQUARE,
        "scale_pixels_per_unit": 10,
        "linked_boq_position_id": None,
    }
    base.update(kw)
    return {"measurement": base}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (TakeoffValueInRangeRule, _m(), _m(measurement_value=5e9)),
    (TakeoffValueInRangeRule, _m(), _m(measurement_value=-3)),
    (TakeoffGeometryMatchesTypeRule, _m(), _m(points=SQUARE[:2])),
    (
        TakeoffLinkNeedsConfirmedRule,
        _m(linked_boq_position_id="p1"),
        _m(linked_boq_position_id="p1", review_status="proposed"),
    ),
    (TakeoffScaleStatedRule, _m(), _m(scale_pixels_per_unit=None)),
    (TakeoffUnitMatchesTypeRule, _m(), _m(measurement_unit="m")),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "estimating." not in failed[0].message


async def test_markup_types_carry_no_quantity_and_unreviewed_rows_need_no_link() -> None:
    assert (await _run(TakeoffValueInRangeRule(), _m(type="cloud", measurement_value=5e9)))[0].passed
    assert (await _run(TakeoffLinkNeedsConfirmedRule(), _m(review_status="proposed")))[0].passed
    assert (await _run(TakeoffGeometryMatchesTypeRule(), _m(type="count", points=[])))[0].passed


def test_unit_family_reads_common_spellings() -> None:
    assert unit_family("m²") == "area"
    assert unit_family("Sq Ft") == "area"
    assert unit_family("cu.yd") == "volume"
    assert unit_family("ft3") == "volume"
    assert unit_family("pcs") == "count"
    assert unit_family("furlong") is None


async def test_message_follows_locale() -> None:
    de = await _run(TakeoffScaleStatedRule(), _m(scale_pixels_per_unit=None), locale="de")
    assert "maßstab" in de[0].message.lower()


def _payload(project_id: str, **kw: object) -> dict:
    base = {
        "project_id": project_id,
        "type": "area",
        "points": SQUARE,
        "scale_pixels_per_unit": 10,
        "measurement_unit": "m2",
    }
    base.update(kw)
    return base


async def test_valid_measurement_is_created_without_findings(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    resp = await client.post("/api/v1/takeoff/measurements/", json=_payload(project_id), headers=header)
    assert resp.status_code == 201, resp.text
    assert resp.json()["validation_warnings"] == []


async def test_blocking_rule_rejects_api_create_with_its_code(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    resp = await client.post(
        "/api/v1/takeoff/measurements/", json=_payload(project_id, points=SQUARE[:2]), headers=header
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "takeoff_rules_failed"
    assert "takeoff.geometry_matches_type" in {e["rule_id"] for e in detail["errors"]}


async def test_unit_slip_is_rejected(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    body = _payload(project_id, points=[], scale_pixels_per_unit=None, measurement_value=5e9)
    resp = await client.post("/api/v1/takeoff/measurements/", json=body, headers=header)
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["rule_id"] == "takeoff.value_in_range"


async def test_warnings_are_reported_and_do_not_block(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    body = _payload(project_id, type="distance", points=SQUARE[:2], scale_pixels_per_unit=None, measurement_unit="m2")
    resp = await client.post("/api/v1/takeoff/measurements/", json=body, headers=header)
    assert resp.status_code == 201, resp.text
    assert {w["rule_id"] for w in resp.json()["validation_warnings"]} == {
        "takeoff.scale_stated",
        "takeoff.unit_matches_type",
    }


async def test_bulk_import_rejects_the_batch_on_a_blocking_row(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    body = {"measurements": [_payload(project_id), _payload(project_id, points=SQUARE[:2])]}
    resp = await client.post("/api/v1/takeoff/measurements/bulk/", json=body, headers=header)
    assert resp.status_code == 422
    ok = await client.post(
        "/api/v1/takeoff/measurements/bulk/", json={"measurements": [_payload(project_id)]}, headers=header
    )
    assert ok.status_code == 201, ok.text


async def _insert(project_id: str, **kw: object) -> str:
    row = TakeoffMeasurement(project_id=uuid.UUID(project_id), type="area", points=[], measurement_unit="m2", **kw)
    async with async_session_factory() as session:
        session.add(row)
        await session.commit()
        return str(row.id)


async def test_unreviewed_proposal_cannot_be_linked_to_the_boq(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    mid = await _insert(project_id, review_status="proposed", source="ai_takeoff", measurement_value=4)
    resp = await client.patch(
        f"/api/v1/takeoff/measurements/{mid}", json={"linked_boq_position_id": "pos-1"}, headers=header
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["rule_id"] == "takeoff.link_needs_confirmed"


async def test_legacy_measurement_with_existing_violation_stays_editable(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    mid = await _insert(project_id, measurement_value=5e9)
    resp = await client.patch(f"/api/v1/takeoff/measurements/{mid}", json={"annotation": "Slab"}, headers=header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["annotation"] == "Slab"
