"""Handover dossier: check, assemble, deliver, resend (real PostgreSQL session)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from app.core.photo_evidence import DeviceCapture, build_evidence_record
from app.core.storage import module_uploads_dir
from app.modules.closeout.dossier_service import DossierService
from app.modules.closeout.models import CloseoutDossier
from app.modules.closeout.service import CloseoutService
from app.modules.closeout.validators import register_closeout_validation_rules
from app.modules.commissioning.models import CxSystem
from app.modules.documents.models import Document
from app.modules.punchlist.models import PunchItem
from app.modules.signing.models import SigningSession

pytestmark = pytest.mark.asyncio

PROJECT_SCOPE = {"kind": "project", "value": None}


@pytest.fixture(autouse=True)
def _rules():
    register_closeout_validation_rules()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 10, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def _punch(session, project_id, *, status: str, area: str | None = None, photo: bool = True) -> PunchItem:
    item = PunchItem(
        project_id=project_id,
        title=f"Snag {status} {area or ''}".strip(),
        description="",
        priority="medium",
        status=status,
        photos=[],
        metadata_={"area": area} if area else {},
        reopen_history=[],
    )
    session.add(item)
    await session.flush()
    if photo:
        name = f"{item.id}.png"
        folder = module_uploads_dir("punchlist", "photos")
        folder.mkdir(parents=True, exist_ok=True)
        data = _png()
        (folder / name).write_bytes(data)
        path = f"punchlist/photos/{name}"
        record = build_evidence_record(data, path=path, device=DeviceCapture(lat=50.1, lon=8.6, accuracy_m=4.0))
        item.photos = [path]
        item.metadata_ = {**item.metadata_, "photo_evidence": {path: record}}
        await session.flush()
    return item


async def _complete_package(session, project_id):
    closeout = CloseoutService(session)
    package = await closeout.create_package(project_id, "commercial")
    slots = await closeout.repo.list_slots(package.id)
    doc = Document(project_id=project_id, name="acceptance.pdf", category="contract", file_path="", uploaded_by="")
    session.add(doc)
    await session.flush()
    for slot in slots:
        if slot.source_kind == "generated":
            continue
        if slot.category == "acceptance":
            await closeout.bind_slot(slot, document_id=doc.id, external_url=None, mark_verified=True, verified_by="m")
        else:
            await closeout.bind_slot(
                slot,
                document_id=None,
                external_url=f"https://cde.example/{slot.slot_key}",
                mark_verified=True,
                verified_by="m",
            )
    session.add(
        SigningSession(
            project_id=project_id,
            document_ref=f"document:{doc.id}",
            document_content_hash="ab" * 32,
            status="fully_signed",
            signatory_map=[],
            metadata_={},
        )
    )
    session.add(CxSystem(project_id=project_id, name="AHU-1", system_type="hvac", status="commissioned", metadata_={}))
    await session.flush()
    return await closeout.get_package_or_404(package.id), doc


async def test_fresh_package_fails_on_acceptance_and_open_work(session, project_id):
    closeout = CloseoutService(session)
    package = await closeout.create_package(project_id, "commercial")
    await _punch(session, project_id, status="open")
    state, failed, ctx = await DossierService(session).run_checks(package, PROJECT_SCOPE, "en")
    assert state == "errors"
    ids = {f["rule_id"] for f in failed}
    assert {"closeout.dossier_acceptance_signed", "closeout.dossier_punch_resolved"} <= ids
    assert ctx["punch"]["total"] == 1


async def test_request_is_refused_on_errors_unless_incomplete_is_allowed(session, project_id):
    package = await CloseoutService(session).create_package(project_id, "commercial")
    service = DossierService(session)
    with pytest.raises(HTTPException) as exc:
        await service.request(package, scope=PROJECT_SCOPE, deliveries=[], allow_incomplete=False, requested_by=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["results"]
    dossier = await service.request(
        package, scope=PROJECT_SCOPE, deliveries=[], allow_incomplete=True, requested_by=None
    )
    assert dossier.status == "queued" and dossier.check_status == "errors"


async def test_complete_package_passes_and_builds_an_indexed_archive(session, project_id):
    package, _doc = await _complete_package(session, project_id)
    await _punch(session, project_id, status="verified")
    service = DossierService(session)
    state, failed, ctx = await service.run_checks(package, PROJECT_SCOPE, "en")
    assert state == "passed", failed
    assert ctx["acceptance"]["signed"] is True

    user = str(uuid.uuid4())
    dossier = await service.request(
        package, scope=PROJECT_SCOPE, deliveries=[], allow_incomplete=False, requested_by=user
    )
    await service.build(dossier)
    assert dossier.status == "built" and dossier.document_id is not None
    assert dossier.sha256 and dossier.size_bytes
    with zipfile.ZipFile(dossier.file_path) as zf:
        names = set(zf.namelist())
        assert {"index.pdf", "manifest.json", "index.json", "README.md", "punch/register.json"} <= names
        assert "generated/commissioning_certificates.pdf" in names
        assert any(n.startswith("punch/") and n.endswith(".png") for n in names)
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["kind"] == "construction_handover_dossier"
        assert manifest["checks"]["status"] == "passed"
        register = json.loads(zf.read("punch/register.json"))
        assert register[0]["photos"][0]["evidence"]["location"]["accuracy_m"] == 4.0
        index = json.loads(zf.read("index.json"))
        assert any(e["path"] == "index.pdf" for e in index)
    filed = await session.get(Document, dossier.document_id)
    assert filed is not None and "handover_dossier" in filed.tags


async def test_area_scope_takes_only_that_areas_punch_items(session, project_id):
    package, _doc = await _complete_package(session, project_id)
    await _punch(session, project_id, status="verified", area="Level 2 / Room 2.1")
    await _punch(session, project_id, status="open", area="Level 3")
    service = DossierService(session)
    state, failed, ctx = await service.run_checks(package, {"kind": "area", "value": "Level 2"}, "en")
    assert ctx["punch"]["total"] == 1 and state == "passed", failed
    state, _failed, _ctx = await service.run_checks(package, {"kind": "area", "value": "Level 3"}, "en")
    assert state == "errors"


async def test_download_webhook_delivery_and_resend_are_logged(session, project_id, monkeypatch):
    package, _doc = await _complete_package(session, project_id)
    service = DossierService(session)
    user = str(uuid.uuid4())
    dossier = await service.request(
        package, scope=PROJECT_SCOPE, deliveries=[], allow_incomplete=False, requested_by=user
    )
    await service.build(dossier)

    download = await service.deliver(dossier, {"channel": "download"}, delivered_by=user)
    assert download.status == "sent"

    from app.modules.integrations.models import WebhookEndpoint
    from app.modules.integrations.service import WebhookService

    hook = WebhookEndpoint(
        user_id=uuid.UUID(user), project_id=project_id, name="Owner FM", url="https://fm.example/hook", events=[]
    )
    session.add(hook)
    await session.flush()
    sent_payloads: list[dict] = []

    async def fake_deliver(self, webhook, event_type, payload):
        sent_payloads.append(payload)
        return SimpleNamespace(status_code=202, response_body="queued")

    monkeypatch.setattr(WebhookService, "deliver_to", fake_deliver)
    entry = {"channel": "webhook", "target_id": str(hook.id), "message": "Handover for block A"}
    await service.validate_target(project_id, entry, user)
    delivery = await service.deliver(dossier, entry, delivered_by=user)
    assert delivery.status == "sent" and delivery.status_code == 202
    assert delivery.share_url and "/share/" in delivery.share_url
    assert sent_payloads[0]["sha256"] == dossier.sha256
    assert sent_payloads[0]["download_url"] == delivery.share_url
    assert dossier.status == "delivered"

    resent = await service.resend(delivery, delivered_by=user)
    assert resent.resend_of == delivery.id and resent.status == "sent"
    assert resent.share_url != delivery.share_url
    log = await service.list_deliveries([dossier.id])
    assert len(log) == 3


async def test_failed_delivery_is_logged_not_raised(session, project_id, monkeypatch):
    package, _doc = await _complete_package(session, project_id)
    service = DossierService(session)
    user = str(uuid.uuid4())
    dossier = await service.request(
        package, scope=PROJECT_SCOPE, deliveries=[], allow_incomplete=False, requested_by=user
    )
    await service.build(dossier)

    async def refuse(*_args, **_kwargs):
        return False

    monkeypatch.setattr("app.modules.integrations.email_service.send_email", refuse)
    delivery = await service.deliver(dossier, {"channel": "email", "recipient": "owner@example.com"}, delivered_by=user)
    assert delivery.status == "failed" and delivery.detail
    assert dossier.status == "built"


async def test_targets_must_belong_to_the_project(session, project_id):
    service = DossierService(session)
    with pytest.raises(HTTPException) as exc:
        await service.validate_target(project_id, {"channel": "webhook", "target_id": str(uuid.uuid4())}, None)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as bad_mail:
        await service.validate_target(project_id, {"channel": "email", "recipient": "nobody"}, None)
    assert bad_mail.value.status_code == 422


async def test_unbuilt_dossier_cannot_be_delivered(session, project_id):
    package = await CloseoutService(session).create_package(project_id, "commercial")
    dossier = CloseoutDossier(package_id=package.id, project_id=project_id, status="queued", scope=PROJECT_SCOPE)
    session.add(dossier)
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await DossierService(session).deliver(dossier, {"channel": "download"}, delivered_by=None)
    assert exc.value.status_code == 409


async def test_config_round_trip(session, project_id):
    package = await CloseoutService(session).create_package(project_id, "commercial")
    service = DossierService(session)
    cfg = await service.set_config(package, {"required_categories": ["as_built"], "require_punch_photos": False})
    assert cfg["required_categories"] == ["as_built"]
    assert service.get_config(package)["require_punch_photos"] is False
    assert service.get_config(package)["require_punch_resolved"] is True
