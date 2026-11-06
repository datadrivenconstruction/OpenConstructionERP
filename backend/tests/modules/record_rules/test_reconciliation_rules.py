"""The ``reconciliation`` rule set: each rule fires, a valid decision passes, writes are gated."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.reconciliation import service as recon_service
from app.modules.reconciliation.models import RecordLink
from app.modules.reconciliation.validators import (
    RECONCILIATION_RULE_SET,
    RECORD_TYPES,
    ConfirmedConfidenceRule,
    LinkConfidenceRule,
    LinkEndpointsRule,
    LinkRecordTypeRule,
    register_reconciliation_validation_rules,
)

KEY = "link"


def _link(**kw):
    base = {
        "id": "l1",
        "left_type": "correspondence",
        "left_id": "a1",
        "right_type": "change_order",
        "right_id": "b1",
        "relation": "same_event",
        "status": "confirmed",
        "confidence": "0.8",
    }
    return base | kw


async def _run(rule, record, locale="en"):
    context = ValidationContext(data={KEY: record}, metadata={"locale": locale})
    return await rule().validate(context)


CASES = [
    (LinkEndpointsRule, _link(right_id=""), "reconciliation.link_endpoints", Severity.ERROR),
    (
        LinkEndpointsRule,
        _link(right_type="correspondence", right_id="a1"),
        "reconciliation.link_endpoints",
        Severity.ERROR,
    ),
    (LinkRecordTypeRule, _link(left_type="invoice"), "reconciliation.record_type", Severity.ERROR),
    (LinkConfidenceRule, _link(confidence=1.5), "reconciliation.confidence_range", Severity.ERROR),
    (LinkConfidenceRule, _link(confidence=-0.1), "reconciliation.confidence_range", Severity.ERROR),
    (ConfirmedConfidenceRule, _link(confidence="0.2"), "reconciliation.confirmed_confidence", Severity.WARNING),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, bad, rule_id, severity):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, _link()))


@pytest.mark.asyncio
async def test_an_unscored_or_rejected_link_is_not_flagged_as_weak():
    assert all(r.passed for r in await _run(ConfirmedConfidenceRule, _link(confidence=None)))
    assert all(r.passed for r in await _run(ConfirmedConfidenceRule, _link(confidence="0")))
    assert all(r.passed for r in await _run(ConfirmedConfidenceRule, _link(confidence="0.2", status="rejected")))


def test_known_record_types_are_the_ones_the_service_gathers():
    gathered = {
        recon_service.TYPE_CORRESPONDENCE,
        recon_service.TYPE_CHANGE_ORDER,
        recon_service.TYPE_VARIATION_REQUEST,
        recon_service.TYPE_VARIATION_ORDER,
        recon_service.TYPE_NOTICE,
        recon_service.TYPE_MOC,
    }
    assert gathered == RECORD_TYPES


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(LinkEndpointsRule, CASES[0][1], "de") if not r.passed]
    assert "Datensätze" in failed[0].message


def test_rule_set_is_registered():
    register_reconciliation_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([RECONCILIATION_RULE_SET])}) == 4


# -- write points --------------------------------------------------------------------------------------


def _url(project_id):
    return f"/api/v1/reconciliation/projects/{project_id}/record-links"


def _body(**over):
    return {
        "left_type": "correspondence",
        "left_id": str(uuid.uuid4()),
        "right_type": "change_order",
        "right_id": str(uuid.uuid4()),
        "status": "confirmed",
        "confidence": 0.8,
    } | over


@pytest.mark.asyncio
async def test_a_link_of_a_record_to_itself_is_refused_with_its_code(client, admin_auth, project_id):
    _, h = admin_auth
    same = str(uuid.uuid4())
    resp = await client.post(
        _url(project_id), json=_body(left_id=same, right_type="correspondence", right_id=same), headers=h
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "reconciliation_rules_failed"
    assert detail["code"] == "reconciliation.link_endpoints"


@pytest.mark.asyncio
async def test_an_unknown_record_type_and_a_confidence_out_of_range_are_refused(client, admin_auth, project_id):
    _, h = admin_auth
    typed = await client.post(_url(project_id), json=_body(left_type="invoice"), headers=h)
    assert typed.status_code == 422, typed.text
    assert typed.json()["detail"]["code"] == "reconciliation.record_type"
    ranged = await client.post(_url(project_id), json=_body(confidence=7), headers=h)
    assert ranged.status_code == 422, ranged.text
    assert ranged.json()["detail"]["code"] == "reconciliation.confidence_range"


@pytest.mark.asyncio
async def test_a_valid_decision_passes_and_a_weak_confirmation_carries_a_warning(client, admin_auth, project_id):
    _, h = admin_auth
    ok = await client.post(_url(project_id), json=_body(), headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["validation_warnings"] == []
    weak = await client.post(_url(project_id), json=_body(confidence=0.2), headers=h)
    assert weak.status_code == 200, weak.text
    assert [w["rule_id"] for w in weak.json()["validation_warnings"]] == ["reconciliation.confirmed_confidence"]


@pytest.mark.asyncio
async def test_a_legacy_link_with_an_unknown_type_can_still_be_ruled_on(client, admin_auth, project_id):
    from app.database import async_session_factory

    _, h = admin_auth
    left, right = str(uuid.uuid4()), str(uuid.uuid4())
    async with async_session_factory() as session:
        session.add(
            RecordLink(
                project_id=uuid.UUID(project_id),
                left_type="bogus",
                left_id=left,
                right_type="change_order",
                right_id=right,
                status="suggested",
            )
        )
        await session.commit()
    resp = await client.post(
        _url(project_id),
        json=_body(left_type="bogus", left_id=left, right_id=right, status="rejected", confidence=None),
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"
