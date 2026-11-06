"""The ``methodology`` rule set: each rule fires, valid records pass, writes are gated."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.methodology.models import FundingSource, Methodology
from app.modules.methodology.templates import TEMPLATES
from app.modules.methodology.validators import (
    METHODOLOGY_RULE_SET,
    CascadeBaseRule,
    CascadeRateRule,
    DimensionValuesRule,
    FundingCodeRule,
    VatRateRule,
    register_methodology_validation_rules,
)


def _step(**kw):
    return {"key": "x", "kind": "percentage", "rate": "10", "base": ["direct"]} | kw


def _meth(**kw):
    base = {
        "id": "m1",
        "vat_rate": "19",
        "base_mapping": {"material": ["material"], "labor": ["labor"]},
        "composites": {"direct": ["material", "labor"]},
        "cascade_steps": [
            {"key": "overhead", "kind": "percentage", "rate": "12", "base": ["direct"]},
            {"key": "profit", "kind": "percentage", "rate": "6", "base": ["direct", "overhead"]},
        ],
    }
    return base | kw


async def _run(rule, key, record, locale="en"):
    context = ValidationContext(data={key: record}, metadata={"locale": locale})
    return await rule().validate(context)


CASES = [
    (CascadeRateRule, "methodology", _meth(cascade_steps=[_step(rate="450")]), "methodology.cascade_rate"),
    (CascadeRateRule, "methodology", _meth(cascade_steps=[_step(rate="-1")]), "methodology.cascade_rate"),
    (
        CascadeRateRule,
        "methodology",
        _meth(cascade_steps=[_step(kind="gross_up", rate="100")]),
        "methodology.cascade_rate",
    ),
    (CascadeBaseRule, "methodology", _meth(cascade_steps=[_step(base=["nonsense"])]), "methodology.cascade_base"),
    (VatRateRule, "methodology", _meth(vat_rate="190"), "methodology.vat_rate"),
    (FundingCodeRule, "funding", {"id": "f1", "code": "EU", "code_taken": True}, "methodology.funding_code"),
    (
        DimensionValuesRule,
        "dimension",
        {"id": "d1", "key": "stage", "values": [{"code": "A"}, {"code": "A"}]},
        "methodology.dimension_values",
    ),
    (
        DimensionValuesRule,
        "dimension",
        {"id": "d1", "key": "stage", "values": [{"code": "A", "parent_code": "Z"}]},
        "methodology.dimension_values",
    ),
]
VALID = {
    "methodology": _meth(),
    "funding": {"id": "f1", "code": "EU", "code_taken": False},
    "dimension": {"id": "d1", "key": "stage", "values": [{"code": "A"}, {"code": "B", "parent_code": "A"}]},
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, key, bad, rule_id):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, VALID[key]))


@pytest.mark.asyncio
async def test_an_empty_mapping_prices_against_the_direct_base():
    bare = _meth(base_mapping={}, composites={})
    assert all(r.passed for r in await _run(CascadeBaseRule, "methodology", bare))


@pytest.mark.asyncio
async def test_every_built_in_template_passes_the_rules():
    for template in TEMPLATES:
        record = {
            "id": template["slug"],
            "vat_rate": template.get("vat_rate"),
            "base_mapping": template.get("base_mapping") or {},
            "composites": template.get("composites") or {},
            "cascade_steps": template.get("cascade_steps") or [],
        }
        for rule in (CascadeRateRule, CascadeBaseRule, VatRateRule):
            failed = [r.message for r in await _run(rule, "methodology", record) if not r.passed]
            assert not failed, (template["slug"], failed)


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(VatRateRule, "methodology", CASES[4][2], "de") if not r.passed]
    assert failed
    assert (
        failed[0].message != [r for r in await _run(VatRateRule, "methodology", CASES[4][2]) if not r.passed][0].message
    )


def test_rule_set_is_registered():
    register_methodology_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([METHODOLOGY_RULE_SET])}) == 5


# -- write points --------------------------------------------------------------------------------------

BASE = "/api/v1/methodology"


def _create(project_id, **over):
    return {
        "project_id": project_id,
        "name": "Site methodology",
        "currency": "EUR",
        "base_mapping": {"material": ["material"]},
        "composites": {"direct": ["material"]},
        "cascade_steps": [{"key": "overhead", "kind": "percentage", "rate": "12", "base": ["direct"]}],
        "vat_rate": "19",
    } | over


@pytest.mark.asyncio
async def test_a_methodology_with_a_bad_rate_or_base_is_refused_with_its_code(client, admin_auth, project_id):
    _, h = admin_auth
    step = {"key": "o", "kind": "percentage", "rate": "900", "base": ["direct"]}
    resp = await client.post(f"{BASE}/", json=_create(project_id, cascade_steps=[step]), headers=h)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "methodology_rules_failed"
    assert detail["code"] == "methodology.cascade_rate"
    step = {"key": "o", "kind": "percentage", "rate": "5", "base": ["ghost"]}
    resp = await client.post(f"{BASE}/", json=_create(project_id, cascade_steps=[step]), headers=h)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "methodology.cascade_base"
    ok = await client.post(f"{BASE}/", json=_create(project_id), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_an_edit_that_breaks_a_rate_is_refused_and_a_legacy_one_stays_editable(client, admin_auth, project_id):
    from sqlalchemy import update

    from app.database import async_session_factory

    _, h = admin_auth
    made = await client.post(f"{BASE}/", json=_create(project_id), headers=h)
    assert made.status_code == 201, made.text
    mid = made.json()["id"]
    url = f"{BASE}/{mid}?project_id={project_id}"
    refused = await client.patch(url, json={"vat_rate": "250"}, headers=h)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "methodology.vat_rate"
    async with async_session_factory() as session:
        await session.execute(update(Methodology).where(Methodology.id == uuid.UUID(mid)).values(vat_rate="250"))
        await session.commit()
    edited = await client.patch(url, json={"description": "Notes"}, headers=h)
    assert edited.status_code == 200, edited.text


@pytest.mark.asyncio
async def test_a_dimension_with_duplicate_values_is_refused(client, admin_auth, project_id):
    _, h = admin_auth
    body = {
        "project_id": project_id,
        "key": "stage",
        "label": "Stage",
        "values": [{"code": "A", "label": "A"}, {"code": "A", "label": "Again"}],
    }
    resp = await client.post(f"{BASE}/dimensions", json=body, headers=h)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "methodology.dimension_values"
    body["values"] = [{"code": "A", "label": "A"}, {"code": "B", "label": "B", "parent_code": "A"}]
    ok = await client.post(f"{BASE}/dimensions", json=body, headers=h)
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_a_duplicate_funding_code_is_refused_and_a_legacy_duplicate_stays_editable(
    client, admin_auth, project_id
):
    from sqlalchemy import update

    from app.database import async_session_factory

    _, h = admin_auth
    url = f"{BASE}/funding-sources"
    first = await client.post(url, json={"project_id": project_id, "code": "EU", "name": "EU grant"}, headers=h)
    assert first.status_code == 201, first.text
    dup = await client.post(url, json={"project_id": project_id, "code": "EU", "name": "Other"}, headers=h)
    assert dup.status_code == 422, dup.text
    assert dup.json()["detail"]["code"] == "methodology.funding_code"
    other = await client.post(url, json={"project_id": project_id, "code": "OWN", "name": "Own"}, headers=h)
    assert other.status_code == 201, other.text
    oid = other.json()["id"]
    async with async_session_factory() as session:
        await session.execute(update(FundingSource).where(FundingSource.id == uuid.UUID(oid)).values(code="EU"))
        await session.commit()
    renamed = await client.patch(f"{url}/{oid}?project_id={project_id}", json={"name": "Own 2"}, headers=h)
    assert renamed.status_code == 200, renamed.text
