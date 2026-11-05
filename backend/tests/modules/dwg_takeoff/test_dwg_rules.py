# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""DWG takeoff rule set: every rule fires, a valid annotation passes, and the write points enforce it."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.core.validation.engine import ValidationContext
from app.database import async_session_factory
from app.modules.dwg_takeoff.models import DwgAnnotation, DwgDrawing
from app.modules.dwg_takeoff.validators import (
    DwgCountIsWholeRule,
    DwgMeasurementInRangeRule,
    DwgScaleConfirmedRule,
    DwgScalePlausibleRule,
    DwgUnitStatedRule,
)
from tests.modules.ncr.conftest import admin_auth, app_instance, client, project_id  # noqa: F401


def _ctx(ann: dict | None = None, drawing: dict | None = None) -> dict:
    a = {
        "id": "a1",
        "annotation_type": "distance",
        "measurement_value": 12.5,
        "measurement_unit": "m",
        "scale_override": None,
        "linked_boq_position_id": None,
    }
    d = {"id": "d1", "scale_denominator": 50, "scale_mode": "calibrated"}
    a.update(ann or {})
    d.update(drawing or {})
    return {"annotation": a, "drawing": d}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (DwgMeasurementInRangeRule, _ctx(), _ctx({"measurement_value": 5e9})),
    (DwgMeasurementInRangeRule, _ctx(), _ctx({"measurement_value": -1})),
    (
        DwgCountIsWholeRule,
        _ctx({"annotation_type": "count", "measurement_value": 4}),
        _ctx({"annotation_type": "count", "measurement_value": 2.5}),
    ),
    (DwgUnitStatedRule, _ctx(), _ctx({"measurement_unit": ""})),
    (DwgScalePlausibleRule, _ctx(), _ctx(drawing={"scale_denominator": 250000})),
    (DwgScaleConfirmedRule, _ctx(), _ctx(drawing={"scale_denominator": 1, "scale_mode": "preset"})),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "estimating." not in failed[0].message


async def test_scale_override_and_markup_types_need_no_confirmed_scale() -> None:
    untouched = {"scale_denominator": 1, "scale_mode": "preset"}
    assert (await _run(DwgScaleConfirmedRule(), _ctx({"scale_override": 100}, untouched)))[0].passed
    assert (await _run(DwgScaleConfirmedRule(), _ctx({"annotation_type": "text_pin"}, untouched)))[0].passed
    assert (await _run(DwgScalePlausibleRule(), {"annotation": {}, "drawing": {"scale_denominator": 0.5}}))[0].passed


async def test_message_follows_locale() -> None:
    de = await _run(DwgCountIsWholeRule(), _ctx({"annotation_type": "count", "measurement_value": 2.5}), locale="de")
    assert "ganze Zahl" in de[0].message


async def _drawing(project_id: str, **kw: object) -> str:
    row = DwgDrawing(
        project_id=uuid.UUID(project_id), name="Plan", filename="plan.dxf", file_path="plan.dxf", status="ready", **kw
    )
    async with async_session_factory() as session:
        session.add(row)
        await session.commit()
        return str(row.id)


def _body(project_id: str, drawing_id: str, **kw: object) -> dict:
    base = {
        "project_id": project_id,
        "drawing_id": drawing_id,
        "annotation_type": "distance",
        "geometry": {"points": [[0, 0], [10, 0]]},
        "measurement_value": 12.5,
        "measurement_unit": "m",
    }
    base.update(kw)
    return base


async def test_valid_annotation_on_a_calibrated_drawing_has_no_findings(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    did = await _drawing(project_id, scale_denominator=Decimal("50"), scale_mode="calibrated")
    resp = await client.post("/api/v1/dwg-takeoff/annotations/", json=_body(project_id, did), headers=header)
    assert resp.status_code == 201, resp.text
    assert resp.json()["validation_warnings"] == []


async def test_blocking_rule_rejects_api_create_with_its_code(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    did = await _drawing(project_id)
    resp = await client.post(
        "/api/v1/dwg-takeoff/annotations/", json=_body(project_id, did, measurement_value=5e9), headers=header
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "dwg_takeoff_rules_failed"
    assert detail["errors"][0]["rule_id"] == "dwg_takeoff.measurement_in_range"
    count = await client.post(
        "/api/v1/dwg-takeoff/annotations/",
        json=_body(project_id, did, annotation_type="count", measurement_value=2.5, measurement_unit="pcs"),
        headers=header,
    )
    assert count.status_code == 422
    assert count.json()["detail"]["errors"][0]["rule_id"] == "dwg_takeoff.count_is_whole"


async def test_warnings_are_reported_and_do_not_block(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    did = await _drawing(project_id)
    resp = await client.post(
        "/api/v1/dwg-takeoff/annotations/", json=_body(project_id, did, measurement_unit=None), headers=header
    )
    assert resp.status_code == 201, resp.text
    assert {w["rule_id"] for w in resp.json()["validation_warnings"]} == {
        "dwg_takeoff.unit_stated",
        "dwg_takeoff.scale_confirmed",
    }


async def test_update_that_introduces_an_error_is_rejected(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    did = await _drawing(project_id, scale_denominator=Decimal("50"), scale_mode="calibrated")
    created = (
        await client.post("/api/v1/dwg-takeoff/annotations/", json=_body(project_id, did), headers=header)
    ).json()
    resp = await client.patch(
        f"/api/v1/dwg-takeoff/annotations/{created['id']}", json={"measurement_value": -4}, headers=header
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["rule_id"] == "dwg_takeoff.measurement_in_range"


async def test_legacy_annotation_with_existing_violation_stays_editable(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    did = await _drawing(project_id, scale_denominator=Decimal("50"), scale_mode="calibrated")
    created = (
        await client.post("/api/v1/dwg-takeoff/annotations/", json=_body(project_id, did), headers=header)
    ).json()
    async with async_session_factory() as session:
        await session.execute(
            update(DwgAnnotation).where(DwgAnnotation.id == uuid.UUID(created["id"])).values(measurement_value=5e9)
        )
        await session.commit()
    resp = await client.patch(f"/api/v1/dwg-takeoff/annotations/{created['id']}", json={"text": "Beam"}, headers=header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "Beam"


async def test_unusual_drawing_scale_is_reported(client, admin_auth, project_id) -> None:  # noqa: F811
    _, header = admin_auth
    did = await _drawing(project_id)
    resp = await client.patch(
        f"/api/v1/dwg-takeoff/drawings/{did}/scale/",
        json={"scale_denominator": 0.001, "scale_mode": "calibrated"},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    assert [w["rule_id"] for w in resp.json()["validation_warnings"]] == ["dwg_takeoff.scale_plausible"]


async def test_count_off_by_float_noise_is_still_whole() -> None:
    noisy = _ctx({"annotation_type": "count", "measurement_value": 3.0000000000000004})
    assert all(r.passed for r in await _run(DwgCountIsWholeRule(), noisy))
