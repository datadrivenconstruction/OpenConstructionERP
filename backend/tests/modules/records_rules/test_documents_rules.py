"""The ``documents`` rule set: each rule fires, valid records pass, writes are gated."""

from __future__ import annotations

import base64
import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.documents.validators import (
    DOCUMENTS_RULE_SET,
    ArchivedNotCurrentRule,
    FileNotEmptyRule,
    PhotoLocationRule,
    PublishedDrawingIdentifiedRule,
    register_documents_validation_rules,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


async def _run(rule, key, record, locale="en"):
    context = ValidationContext(data={key: record}, metadata={"locale": locale})
    return await rule().validate(context)


CASES = [
    (FileNotEmptyRule, "document", {"id": "d", "file_size": 0}, "documents.file_not_empty", Severity.ERROR),
    (
        PublishedDrawingIdentifiedRule,
        "document",
        {"id": "d", "category": "drawing", "cde_state": "published", "drawing_number": "A-101", "revision_code": ""},
        "documents.published_drawing_identified",
        Severity.WARNING,
    ),
    (
        ArchivedNotCurrentRule,
        "document",
        {"id": "d", "cde_state": "archived", "is_current_revision": True},
        "documents.archived_not_current",
        Severity.ERROR,
    ),
    (PhotoLocationRule, "photo", {"id": "p", "gps_lat": 95, "gps_lon": 10}, "documents.photo_location", Severity.ERROR),
    (
        PhotoLocationRule,
        "photo",
        {"id": "p", "gps_lat": 10, "gps_lon": None},
        "documents.photo_location",
        Severity.ERROR,
    ),
    (
        PhotoLocationRule,
        "photo",
        {"id": "p", "gps_lat": 10, "gps_lon": 181},
        "documents.photo_location",
        Severity.ERROR,
    ),
]
VALID = {
    "document": {
        "id": "d",
        "category": "drawing",
        "file_size": 2048,
        "cde_state": "published",
        "drawing_number": "A-101",
        "revision_code": "C",
        "is_current_revision": True,
    },
    "photo": {"id": "p", "gps_lat": 52.52, "gps_lon": 13.4},
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, key, bad, rule_id, severity):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, VALID[key]))


@pytest.mark.asyncio
async def test_only_what_the_rule_guards_is_judged():
    wip = {"category": "drawing", "cde_state": "wip"}
    assert all(r.passed for r in await _run(PublishedDrawingIdentifiedRule, "document", wip))
    assert all(r.passed for r in await _run(FileNotEmptyRule, "document", {}))
    assert all(r.passed for r in await _run(PhotoLocationRule, "photo", {"gps_lat": None, "gps_lon": None}))
    contract = {"category": "contract", "cde_state": "published"}
    assert all(r.passed for r in await _run(PublishedDrawingIdentifiedRule, "document", contract))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(FileNotEmptyRule, "document", {"file_size": 0}, "de") if not r.passed]
    assert "leer" in failed[0].message


def test_rule_set_is_registered():
    register_documents_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([DOCUMENTS_RULE_SET])}) == 4


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


async def _upload(client, h, project_id, data=b"%PDF-1.4 site plan", name="plan.pdf", category="drawing"):
    return await client.post(
        f"/api/v1/documents/upload/?project_id={project_id}&category={category}",
        files={"file": (name, data, "application/pdf")},
        headers=h,
    )


async def _set(doc_id, **fields):
    from app.database import async_session_factory
    from app.modules.documents.repository import DocumentRepository

    async with async_session_factory() as s:
        await DocumentRepository(s).update_fields(uuid.UUID(doc_id), **fields)
        await s.commit()


@pytest.mark.asyncio
async def test_empty_upload_is_rejected_with_code_and_a_real_file_is_clean(client, admin_auth, project_id):
    _, h = admin_auth
    bad = await _upload(client, h, project_id, data=b"")
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["error"] == "document_rules_failed"
    assert _codes(bad) == {"documents.file_not_empty"}
    ok = await _upload(client, h, project_id)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_empty_revision_is_rejected(client, admin_auth, project_id):
    _, h = admin_auth
    doc = (await _upload(client, h, project_id)).json()
    bad = await client.post(
        f"/api/v1/documents/{doc['id']}/revisions/",
        files={"file": ("plan.pdf", b"", "application/pdf")},
        headers=h,
    )
    assert bad.status_code == 422 and _codes(bad) == {"documents.file_not_empty"}


@pytest.mark.asyncio
async def test_update_blocks_an_introduced_error_and_keeps_the_document(client, admin_auth, project_id):
    _, h = admin_auth
    doc = (await _upload(client, h, project_id)).json()
    await _set(doc["id"], cde_state="archived", is_current_revision=False)
    bad = await client.patch(f"/api/v1/documents/{doc['id']}", json={"is_current_revision": True}, headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"documents.archived_not_current"}
    assert (await client.get(f"/api/v1/documents/{doc['id']}", headers=h)).json()["is_current_revision"] is False


@pytest.mark.asyncio
async def test_legacy_archived_current_document_stays_editable(client, admin_auth, project_id):
    _, h = admin_auth
    doc = (await _upload(client, h, project_id)).json()
    await _set(doc["id"], cde_state="archived", is_current_revision=True)
    edit = await client.patch(f"/api/v1/documents/{doc['id']}", json={"description": "superseded by C"}, headers=h)
    assert edit.status_code == 200, edit.text


@pytest.mark.asyncio
async def test_publishing_an_unnumbered_drawing_is_allowed_with_a_warning(client, admin_auth, project_id):
    _, h = admin_auth
    doc = (await _upload(client, h, project_id)).json()
    await _set(doc["id"], cde_state="shared")
    pub = await client.patch(
        f"/api/v1/documents/{doc['id']}",
        json={"cde_state": "published", "approver_signature": "Lead appointed party"},
        headers=h,
    )
    assert pub.status_code == 200, pub.text
    assert isinstance(pub.json()["validation_warnings"], list)


@pytest.mark.asyncio
async def test_photo_location_is_gated(client, admin_auth, project_id):
    _, h = admin_auth
    url = f"/api/v1/documents/photos/upload/?project_id={project_id}"
    files = {"file": ("site.png", PNG, "image/png")}
    bad = await client.post(url, files=files, data={"gps_lat": "95", "gps_lon": "10"}, headers=h)
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["error"] == "document_rules_failed"
    assert _codes(bad) == {"documents.photo_location"}
    half = await client.post(url, files=files, data={"gps_lat": "10"}, headers=h)
    assert half.status_code == 422 and _codes(half) == {"documents.photo_location"}
    ok = await client.post(url, files=files, data={"gps_lat": "52.52", "gps_lon": "13.4"}, headers=h)
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_archiving_retires_the_current_flag_unless_the_caller_says_otherwise(client, admin_auth, project_id):
    _, h = admin_auth
    doc = (await _upload(client, h, project_id)).json()
    assert doc["is_current_revision"] is True
    await _set(doc["id"], cde_state="published")
    done = await client.patch(f"/api/v1/documents/{doc['id']}", json={"cde_state": "archived"}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["is_current_revision"] is False
