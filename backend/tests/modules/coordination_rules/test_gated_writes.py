"""Coordination writes go through the shared gate: coded 422, warnings, legacy records stay editable."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _doc(project_id, **over):
    body = {
        "project_id": project_id,
        "doc_type": "insurance_general_liability",
        "name": "Liability",
        "policy_number": "POL-1",
        "coverage_amount": "500000",
        "currency": "EUR",
        "effective_date": _day(-30),
        "expires_at": _day(300),
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_compliance_doc_create_rejects_missing_cover_and_bad_currency(client, admin_auth, project_id):
    _, h = admin_auth
    bad = await client.post("/api/v1/compliance_docs/", json=_doc(project_id, coverage_amount=None), headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"compliance_docs.coverage_amount"}
    assert bad.json()["detail"]["code"] == "compliance_docs.coverage_amount"
    bad = await client.post("/api/v1/compliance_docs/", json=_doc(project_id, currency="E1R"), headers=h)
    assert bad.status_code == 422 and "compliance_docs.currency_code" in _codes(bad)


@pytest.mark.asyncio
async def test_compliance_doc_valid_passes_and_warning_does_not_block(client, admin_auth, project_id):
    _, h = admin_auth
    ok = await client.post("/api/v1/compliance_docs/", json=_doc(project_id), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    warn = await client.post("/api/v1/compliance_docs/", json=_doc(project_id, policy_number=None), headers=h)
    assert warn.status_code == 201, warn.text
    assert [w["rule_id"] for w in warn.json()["validation_warnings"]] == ["compliance_docs.policy_number"]


@pytest.mark.asyncio
async def test_legacy_compliance_doc_stays_editable_but_not_worse(client, admin_auth, project_id):
    _, h = admin_auth
    doc = (await client.post("/api/v1/compliance_docs/", json=_doc(project_id), headers=h)).json()
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.compliance_docs.models import ComplianceDoc

    async with async_session_factory() as s:
        await s.execute(update(ComplianceDoc).where(ComplianceDoc.id == uuid.UUID(doc["id"])).values(currency="E1R"))
        await s.commit()
    edit = await client.patch(f"/api/v1/compliance_docs/{doc['id']}/", json={"name": "Renamed"}, headers=h)
    assert edit.status_code == 200, edit.text
    worse = await client.patch(f"/api/v1/compliance_docs/{doc['id']}/", json={"coverage_amount": "0"}, headers=h)
    assert worse.status_code == 422 and _codes(worse) == {"compliance_docs.coverage_amount"}


@pytest.mark.asyncio
async def test_threshold_inverted_is_a_coded_422_and_disable_warns(client, admin_auth, project_id):
    _, h = admin_auth
    url = f"/api/v1/coordination/projects/{project_id}/thresholds/open_clashes_total"
    bad = await client.put(url, json={"warn_value": "40", "error_value": "10"}, headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"coordination_hub.threshold_order"}
    neg = await client.put(url, json={"warn_value": "-5"}, headers=h)
    assert neg.status_code == 422 and _codes(neg) == {"coordination_hub.threshold_value"}
    ok = await client.put(url, json={"warn_value": "10", "error_value": "40"}, headers=h)
    assert ok.status_code == 200, ok.text
    off = await client.put(url, json={"enabled": False}, headers=h)
    assert off.status_code == 200, off.text
    assert [w["rule_id"] for w in off.json()["validation_warnings"]] == ["coordination_hub.threshold_enabled"]


@pytest.mark.asyncio
async def test_approval_route_unknown_role_rejected_and_missing_sla_warns(client, admin_auth):
    _, h = admin_auth

    def body(**step):
        return {"name": f"R-{uuid.uuid4().hex[:6]}", "target_kind": "rfi", "steps": [{"ordinal": 1, **step}]}

    bad = await client.post("/api/v1/approval-routes/routes", json=body(approver_role="nobody_role_x"), headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"approval_routes.approver_role_known"}
    ok = await client.post("/api/v1/approval-routes/routes", json=body(approver_role="admin", sla_hours=24), headers=h)
    assert ok.status_code == 201, ok.text
    warn = await client.post("/api/v1/approval-routes/routes", json=body(approver_role="admin"), headers=h)
    assert warn.status_code == 201, warn.text
    assert [w["rule_id"] for w in warn.json()["validation_warnings"]] == ["approval_routes.step_sla"]


@pytest.mark.asyncio
async def test_delegation_in_the_past_is_rejected_open_ended_warns(client, admin_auth):
    _, h = admin_auth
    from tests.modules.coordination_rules.conftest import _register_user

    other, _, _ = await _register_user(client, role="viewer")
    url = "/api/v1/approval-routes/delegations"
    past = await client.post(url, json={"delegate_user_id": other, "ends_at": f"{_day(-3)}T00:00:00Z"}, headers=h)
    assert past.status_code == 422 and _codes(past) == {"approval_routes.delegation_ended"}
    open_ended = await client.post(url, json={"delegate_user_id": other}, headers=h)
    assert open_ended.status_code == 201, open_ended.text
    assert [w["rule_id"] for w in open_ended.json()["validation_warnings"]] == ["approval_routes.delegation_open_ended"]
