"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠HTTP tests: punch photo evidence + BCF, defect photos, handover dossier, condition plan.

Drives the full app so routing, permission gates, project-access checks and
serialisation are exercised together.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import update as sa_update

from app.database import async_session_factory
from app.main import create_app
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _user(client, role: str) -> dict:
    unique = uuid.uuid4().hex[:8]
    email = f"field-{role}-{unique}@smoke.io"
    password = f"FieldTest{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": f"Field {role}"}
    )
    assert reg.status_code == 201, reg.text
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = resp.json().get("access_token", "")
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin(client):
    return await _user(client, "admin")


async def _project(client, headers) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Field Evidence Project", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (90, 90, 90)).save(buf, format="JPEG")
    return buf.getvalue()


async def test_punch_photo_upload_records_device_evidence_and_bcf_round_trips(client, admin):
    project_id = await _project(client, admin)
    item = await client.post(
        "/api/v1/punchlist/items/", json={"project_id": project_id, "title": "Chipped door frame"}, headers=admin
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]

    up = await client.post(
        f"/api/v1/punchlist/items/{item_id}/photos/",
        files={"file": ("door.jpg", _jpeg(), "image/jpeg")},
        data={
            "capture_lat": "48.137",
            "capture_lon": "11.575",
            "capture_accuracy_m": "7.5",
            "captured_at": "2026-10-25T09:30:00Z",
            "capture_heading_deg": "210",
        },
        headers=admin,
    )
    assert up.status_code == 200, up.text
    body = up.json()
    evidence = body["photo_evidence"][0]
    assert evidence["location"] == {"lat": 48.137, "lon": 11.575, "accuracy_m": 7.5, "source": "device"}
    assert evidence["orientation"]["heading_deg"] == 210.0
    assert evidence["grade"] == "full"
    assert body["geo_lat"] == 48.137

    export = await client.get(f"/api/v1/punchlist/export/bcf/?project_id={project_id}", headers=admin)
    assert export.status_code == 200, export.text
    assert export.headers["x-topic-count"] == "1"
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        assert any(n.startswith(f"{item_id}/") for n in zf.namelist())

    imported = await client.post(
        f"/api/v1/punchlist/import/bcf/?project_id={project_id}",
        files={"file": ("p.bcfzip", export.content, "application/octet-stream")},
        headers=admin,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["updated"] == 1 and imported.json()["photos_added"] == 0

    check = await client.get(f"/api/v1/punchlist/validate/?project_id={project_id}", headers=admin)
    assert check.status_code == 200 and check.json()["status"] == "passed"


async def test_punch_bcf_export_hides_other_projects(client, admin):
    project_id = await _project(client, admin)
    stranger = await _user(client, "editor")
    resp = await client.get(f"/api/v1/punchlist/export/bcf/?project_id={project_id}", headers=stranger)
    assert resp.status_code in (403, 404)


async def test_defect_photo_goes_through_the_gallery_with_evidence(client, admin):
    project_id = await _project(client, admin)
    warranty = await client.post(
        f"/api/v1/defects-liability/projects/{project_id}/warranties",
        json={"reference": "W-1", "title": "Roof membrane"},
        headers=admin,
    )
    assert warranty.status_code == 201, warranty.text
    defect = await client.post(
        f"/api/v1/defects-liability/projects/{project_id}/warranties/{warranty.json()['id']}/defects",
        json={"reference": "D-1", "description": "Blistering"},
        headers=admin,
    )
    assert defect.status_code == 201, defect.text
    defect_id = defect.json()["id"]
    up = await client.post(
        f"/api/v1/defects-liability/projects/{project_id}/defects/{defect_id}/photos",
        files={"file": ("d.jpg", _jpeg(), "image/jpeg")},
        data={"capture_lat": "53.55", "capture_lon": "9.99", "capture_accuracy_m": "12"},
        headers=admin,
    )
    assert up.status_code == 200, up.text
    photo = up.json()["photos"][0]
    assert photo["photo_id"] and photo["evidence"]["sha256"]
    assert up.json()["geo_lat"] == 53.55
    gallery = await client.get(f"/api/v1/documents/photos/?project_id={project_id}", headers=admin)
    assert gallery.status_code == 200
    check = await client.get(f"/api/v1/defects-liability/projects/{project_id}/defects-evidence-check", headers=admin)
    assert check.status_code == 200 and check.json()["status"] == "passed"
    removed = await client.delete(
        f"/api/v1/defects-liability/projects/{project_id}/defects/{defect_id}/photos/0", headers=admin
    )
    assert removed.status_code == 200 and removed.json()["photos"] == []


async def test_dossier_check_config_and_signoff_gate(client, admin):
    project_id = await _project(client, admin)
    pkg = await client.post(
        f"/api/v1/closeout/projects/{project_id}/package", json={"project_type": "commercial"}, headers=admin
    )
    assert pkg.status_code == 201, pkg.text
    package_id = pkg.json()["id"]

    cfg = await client.get(f"/api/v1/closeout/packages/{package_id}/dossier/config", headers=admin)
    assert cfg.status_code == 200 and "acceptance" in cfg.json()["required_categories"]
    put = await client.put(
        f"/api/v1/closeout/packages/{package_id}/dossier/config", json={"require_punch_photos": False}, headers=admin
    )
    assert put.status_code == 200 and put.json()["require_punch_photos"] is False

    check = await client.get(
        f"/api/v1/closeout/packages/{package_id}/dossier/check?scope_kind=area&scope_value=Level%201", headers=admin
    )
    assert check.status_code == 200, check.text
    assert check.json()["check_status"] == "errors"
    assert check.json()["scope"] == {"kind": "area", "value": "Level 1"}

    blocked = await client.post(f"/api/v1/closeout/packages/{package_id}/dossier", json={}, headers=admin)
    assert blocked.status_code == 409

    editor = await _user(client, "editor")
    gated = await client.post(
        f"/api/v1/closeout/packages/{package_id}/dossier", json={"allow_incomplete": True}, headers=editor
    )
    assert gated.status_code in (403, 404)

    targets = await client.get(f"/api/v1/closeout/projects/{project_id}/dossier-targets", headers=admin)
    assert targets.status_code == 200 and targets.json()["items"] == []

    listed = await client.get(f"/api/v1/closeout/packages/{package_id}/dossiers", headers=admin)
    assert listed.status_code == 200 and listed.json()["items"] == []


async def test_condition_rating_plan_and_export(client, admin):
    project_id = await _project(client, admin)
    scales = await client.get(f"/api/v1/condition/scales?project_id={project_id}", headers=admin)
    assert scales.status_code == 200 and scales.json()["items"][0]["key"] == "default_6"

    suggestion = await client.post(
        "/api/v1/condition/suggest-rating", json={"severity": 4, "extent_pct": 80, "intensity": 4}, headers=admin
    )
    assert suggestion.status_code == 200 and suggestion.json()["rating"] == 6

    created = await client.post(
        "/api/v1/condition/assessments",
        json={
            "project_id": project_id,
            "element_name": "Facade render",
            "rating": 5,
            "severity": 3,
            "extent_pct": 50,
            "quantity": "300",
            "unit": "m2",
            "unit_cost": "45.50",
            "currency": "EUR",
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    assert created.json()["unit_cost"] == "45.5"

    derived = await client.post(
        f"/api/v1/condition/plan/derive?project_id={project_id}", json={"base_year": 2027}, headers=admin
    )
    assert derived.status_code == 200 and derived.json()["created"] == 1
    action_id = derived.json()["actions"][0]["id"]

    editor = await _user(client, "editor")
    refused = await client.patch(f"/api/v1/condition/actions/{action_id}", json={"status": "approved"}, headers=editor)
    assert refused.status_code in (403, 404)
    approved = await client.patch(f"/api/v1/condition/actions/{action_id}", json={"status": "approved"}, headers=admin)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    plan = await client.get(
        f"/api/v1/condition/plan?project_id={project_id}&start_year=2027&horizon_years=5&inflation_rate=0.02",
        headers=admin,
    )
    assert plan.status_code == 200, plan.text
    totals = plan.json()["totals"]
    assert totals["cost"] == "6825.00"
    assert totals["cost_inflated"] == "6961.50"

    csv_resp = await client.get(f"/api/v1/condition/plan/export?project_id={project_id}&start_year=2027", headers=admin)
    assert csv_resp.status_code == 200 and "Facade render" in csv_resp.text

    rules = await client.get(f"/api/v1/condition/validate?project_id={project_id}", headers=admin)
    assert rules.status_code == 200 and rules.json()["status"] == "passed"

    stranger_view = await client.get(f"/api/v1/condition/assessments?project_id={project_id}", headers=editor)
    assert stranger_view.status_code in (403, 404)
