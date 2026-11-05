"""The ``cde`` rule set: each rule fires, a valid container passes, writes are gated."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.cde.validators import (
    CDE_RULE_SET,
    ContainerCodeFormatRule,
    RevisionFileSizeRule,
    RevisionHashFormatRule,
    SharedHasSuitabilityRule,
    register_cde_validation_rules,
)

SHA = "a" * 64


async def _run(rule, key, record, locale="en"):
    context = ValidationContext(data={key: record}, metadata={"locale": locale})
    return await rule().validate(context)


CASES = [
    (ContainerCodeFormatRule, "container", {"id": "c", "container_code": "ARC 01"}, "cde.container_code_format"),
    (ContainerCodeFormatRule, "container", {"id": "c", "container_code": "ARC/01"}, "cde.container_code_format"),
    (
        SharedHasSuitabilityRule,
        "container",
        {"id": "c", "cde_state": "shared", "suitability_code": ""},
        "cde.shared_has_suitability",
    ),
    (RevisionFileSizeRule, "revision", {"id": "r", "file_size": "12 KB"}, "cde.revision_file_size"),
    (RevisionFileSizeRule, "revision", {"id": "r", "file_size": "-4"}, "cde.revision_file_size"),
    (RevisionHashFormatRule, "revision", {"id": "r", "content_hash": "abc123"}, "cde.revision_hash_format"),
]
VALID = {
    "container": {"id": "c", "container_code": "PRJ-ARC-01", "cde_state": "shared", "suitability_code": "S2"},
    "revision": {"id": "r", "file_size": "20480", "content_hash": SHA},
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, key, bad, rule_id):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, VALID[key]))


@pytest.mark.asyncio
async def test_severities_and_wip_containers_need_no_suitability():
    failed = await _run(SharedHasSuitabilityRule, "container", {"cde_state": "published"})
    assert failed[0].severity == Severity.WARNING
    assert all(r.passed for r in await _run(SharedHasSuitabilityRule, "container", {"cde_state": "wip"}))
    assert all(r.passed for r in await _run(RevisionFileSizeRule, "revision", {}))
    assert all(r.passed for r in await _run(RevisionHashFormatRule, "revision", {"content_hash": None}))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [
        r for r in await _run(ContainerCodeFormatRule, "container", {"container_code": "A B"}, "ru") if not r.passed
    ]
    assert "контейнер" in failed[0].message.lower()


def test_rule_set_is_registered():
    register_cde_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([CDE_RULE_SET])}) == 4


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


def _body(project_id, **over):
    body = {"project_id": project_id, "container_code": f"PRJ-ARC-{uuid.uuid4().hex[:6]}", "title": "Ground floor plan"}
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_blocking_rule_rejects_api_create_with_code(client, admin_auth, project_id):
    _, h = admin_auth
    r = await client.post("/api/v1/cde/containers/", json=_body(project_id, container_code="PRJ ARC 01"), headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "cde_rules_failed"
    assert _codes(r) == {"cde.container_code_format"}


@pytest.mark.asyncio
async def test_valid_container_is_is_clean(client, admin_auth, project_id):
    _, h = admin_auth
    ok = await client.post("/api/v1/cde/containers/", json=_body(project_id), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_update_blocks_an_introduced_error_and_keeps_the_container(client, admin_auth, project_id):
    _, h = admin_auth
    box = (await client.post("/api/v1/cde/containers/", json=_body(project_id), headers=h)).json()
    bad = await client.patch(f"/api/v1/cde/containers/{box['id']}", json={"container_code": "with space"}, headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"cde.container_code_format"}
    stored = (await client.get(f"/api/v1/cde/containers/{box['id']}", headers=h)).json()
    assert stored["container_code"] == box["container_code"]


@pytest.mark.asyncio
async def test_revision_size_and_hash_are_gated(client, admin_auth, project_id):
    _, h = admin_auth
    box = (await client.post("/api/v1/cde/containers/", json=_body(project_id), headers=h)).json()
    url = f"/api/v1/cde/containers/{box['id']}/revisions/"
    bad = await client.post(url, json={"file_name": "plan.pdf", "file_size": "12 KB"}, headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"cde.revision_file_size"}
    bad = await client.post(url, json={"file_name": "plan.pdf", "content_hash": "not-a-hash"}, headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"cde.revision_hash_format"}
    ok = await client.post(url, json={"file_name": "plan.pdf", "file_size": "20480", "content_hash": SHA}, headers=h)
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_legacy_container_with_a_spaced_code_stays_editable(client, admin_auth, project_id):
    _, h = admin_auth
    from app.database import async_session_factory
    from app.modules.cde.repository import ContainerRepository

    box = (await client.post("/api/v1/cde/containers/", json=_body(project_id), headers=h)).json()
    async with async_session_factory() as s:
        await ContainerRepository(s).update_fields(uuid.UUID(box["id"]), container_code="LEGACY 01")
        await s.commit()
    edit = await client.patch(f"/api/v1/cde/containers/{box['id']}", json={"title": "Renamed sheet"}, headers=h)
    assert edit.status_code == 200, edit.text
    worse = await client.patch(f"/api/v1/cde/containers/{box['id']}", json={"container_code": "LEGACY/02"}, headers=h)
    assert worse.status_code == 422, worse.text
