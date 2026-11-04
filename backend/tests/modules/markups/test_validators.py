# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Markup rules: each rule firing, a valid record passing, and the API refusing a blocking write."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.validation.engine import ValidationContext, rule_registry
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.markups.permissions import register_markups_permissions
from app.modules.markups.router import router as markups_router
from app.modules.markups.validators import (
    MARKUPS_RULE_SET,
    LinkNeedsMeasurementRule,
    MeasurementHasScaleRule,
    MeasurementInRangeRule,
    ScaleUnitIsLengthRule,
    UnitMatchesTypeRule,
    register_markups_validation_rules,
    unit_class,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


def _m(**kw: object) -> dict:
    return {"markup": {"id": "m1", "type": "distance", "measurement_value": "12.5", "measurement_unit": "m", **kw}}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (MeasurementInRangeRule, _m(), _m(measurement_value="-3")),
    (UnitMatchesTypeRule, _m(), _m(measurement_unit="m2")),
    (UnitMatchesTypeRule, _m(type="area", measurement_unit="m2"), _m(type="area", measurement_unit="m")),
    (UnitMatchesTypeRule, _m(type="count", measurement_unit="pcs"), _m(type="count", measurement_unit="m")),
    (LinkNeedsMeasurementRule, _m(operation="link"), _m(operation="link", measurement_value=None)),
    (MeasurementHasScaleRule, _m(has_scale=True), _m(has_scale=False)),
    (
        ScaleUnitIsLengthRule,
        {"scale": {"id": "s1", "unit_label": "m"}},
        {"scale": {"id": "s1", "unit_label": "m2"}},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "cost_rules." not in failed[0].message
    assert "money." not in failed[0].message


@pytest.mark.asyncio
async def test_drafts_and_partial_records_pass() -> None:
    plain = {"markup": {"id": "m", "type": "cloud"}}  # a cloud or arrow carries no measurement
    unitless = _m(measurement_unit=None)  # unit not given yet
    odd_unit = _m(measurement_unit="lfm")  # unrecognised units are not judged
    for rule_cls, _, _ in CASES:
        for data in ({}, plain, unitless, odd_unit):
            assert all(r.passed for r in await _run(rule_cls(), data)), (rule_cls.__name__, data)
    # scale unknown (None) is not "no scale"
    assert all(r.passed for r in await _run(MeasurementHasScaleRule(), _m(has_scale=None)))
    # a zero distance drawn but not yet measured is not flagged for the missing scale
    assert all(r.passed for r in await _run(MeasurementHasScaleRule(), _m(has_scale=False, measurement_value="0")))


def test_unit_classes() -> None:
    assert unit_class("m²") == "area"
    assert unit_class(" Sq M ") == "area"
    assert unit_class("lfm") is None  # not in the table, so not judged
    assert unit_class("LM") == "length"
    assert unit_class("шт") == "count"


@pytest.mark.asyncio
async def test_unit_message_follows_locale() -> None:
    de = (await _run(UnitMatchesTypeRule(), _m(measurement_unit="m2"), locale="de"))[0]
    assert "m2" in de.message
    assert "Einheit" in de.message


def test_registered_under_rule_set() -> None:
    register_markups_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([MARKUPS_RULE_SET])}
    assert "markups.unit_matches_type" in ids
    assert len(ids) == 5


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ctx() -> AsyncIterator[tuple[AsyncClient, uuid.UUID]]:
    register_markups_permissions()
    register_markups_validation_rules()
    async with transactional_session() as session:
        user = User(email=f"mk-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        project = Project(name="Markup test", owner_id=user.id, currency="EUR")
        session.add(project)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(markups_router, prefix="/v1/markups")

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user_id] = lambda: str(user.id)
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": str(user.id),
            "role": "admin",
            "permissions": [],
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, project.id


def _body(project_id: uuid.UUID, **kw: object) -> dict:
    return {
        "project_id": str(project_id),
        "type": "distance",
        "geometry": {"points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]},
        "measurement_value": 12.5,
        "measurement_unit": "m",
        **kw,
    }


@pytest.mark.asyncio
async def test_api_blocks_unit_that_does_not_fit_the_type(ctx: tuple[AsyncClient, uuid.UUID]) -> None:
    c, pid = ctx
    ok = await c.post("/v1/markups/", json=_body(pid))
    assert ok.status_code == 201, ok.text
    assert ok.json()["warnings"] == []

    r = await c.post("/v1/markups/", json=_body(pid, measurement_unit="m2"))
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "markups.unit_matches_type"
    assert r.json()["detail"]["error"] == "markups_rules_failed"

    neg = await c.post("/v1/markups/", json=_body(pid, measurement_value=-4))
    assert neg.status_code == 422
    assert neg.json()["detail"]["code"] == "markups.measurement_in_range"


@pytest.mark.asyncio
async def test_api_reports_missing_scale_as_warning_and_gates_link(ctx: tuple[AsyncClient, uuid.UUID]) -> None:
    c, pid = ctx
    r = await c.post("/v1/markups/", json=_body(pid, document_id="drawing-1"))
    assert r.status_code == 201, r.text
    assert [w["rule_id"] for w in r.json()["warnings"]] == ["markups.measurement_has_scale"]

    cloud = await c.post(
        "/v1/markups/", json={"project_id": str(pid), "type": "cloud", "geometry": {}, "measurement_value": None}
    )
    assert cloud.status_code == 201, cloud.text
    link = await c.post(f"/v1/markups/{cloud.json()['id']}/link-to-boq/", json={"position_id": "pos-1"})
    assert link.status_code == 422, link.text
    assert link.json()["detail"]["code"] == "markups.link_needs_measurement"

    good = await c.post(f"/v1/markups/{r.json()['id']}/link-to-boq/", json={"position_id": "pos-1"})
    assert good.status_code == 200, good.text


@pytest.mark.asyncio
async def test_api_scale_must_be_calibrated_in_a_length(ctx: tuple[AsyncClient, uuid.UUID]) -> None:
    c, _ = ctx
    body = {"document_id": "drawing-1", "pixels_per_unit": 12.0, "unit_label": "m2", "real_distance": 5.0}
    r = await c.post("/v1/markups/scales/", json=body)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "markups.scale_unit_is_length"
    ok = await c.post("/v1/markups/scales/", json={**body, "unit_label": "m"})
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_api_colour_edit_of_an_old_measurement_is_not_refused(ctx: tuple[AsyncClient, uuid.UUID]) -> None:
    c, pid = ctx
    made = await c.post("/v1/markups/", json=_body(pid))
    mid = made.json()["id"]
    r = await c.patch(f"/v1/markups/{mid}", json={"color": "#ff0000"})
    assert r.status_code == 200, r.text
    bad = await c.patch(f"/v1/markups/{mid}", json={"measurement_unit": "m2"})
    assert bad.status_code == 422
