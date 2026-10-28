"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 2 integration + IDOR/tenant-isolation tests.

Covers the materials / digital-passport and test-result flows end to end:

* The conformity flow: create a material record (digital passport), review it, and
  confirm a ``fail`` raises a linked material NCR while a ``pass`` raises none and a
  ``conditional`` raises a low-severity observation NCR.
* Certificate validity: a material whose ``valid_until`` is past is surfaced as
  ``is_expired`` on the response.
* The test flow: record a test result and confirm a ``fail`` raises an NCR, typed
  ``material`` when the test is tied to a material lot and ``workmanship`` otherwise.
* Format-agnostic model linking: a material links to a model element through the same
  Universal Element Reference the inspection uses.
* Tenant isolation / IDOR: a second tenant cannot read another tenant's material or
  test, cannot create a material in a project it cannot access, cannot judge a material
  against another tenant's criterion, and cannot tie a test to another tenant's material.
* RBAC: a viewer cannot create materials or tests.

Harness mirrors ``test_construction_control.py``: register/activate/login real users
over HTTP, set roles via a direct DB write, seed projects/models via the DB. The router
is auto-mounted by the module loader at ``/api/v1/construction-control``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_CC = "/api/v1/construction-control"


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bim_hub import models as _bim_models  # noqa: F401
        from app.modules.construction_control import models as _cc_models  # noqa: F401
        from app.modules.ncr import models as _ncr_models  # noqa: F401
        from app.modules.projects import models as _project_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, *, role: str) -> None:
    """Force ``role`` and ``is_active=True`` on a user via a direct DB write."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, *, tenant: str) -> tuple[str, str, str]:
    """Register a user. Returns ``(uid, email, password)``."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@cc-mat-test.io"
    password = f"CcMat{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    return reg.json()["id"], email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"login failed for {email}: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def cc_world(http_client):
    """Two editor tenants (A, B) + one viewer (V); A owns project P_A with three single-
    element BIM models (IFC / Revit / DWG) and an acceptance criterion. B owns P_B."""
    a_uid, a_email, a_pw = await _register(http_client, tenant="a")
    b_uid, b_email, b_pw = await _register(http_client, tenant="b")
    v_uid, v_email, v_pw = await _register(http_client, tenant="v")

    await _set_role(a_email, role="editor")
    await _set_role(b_email, role="editor")
    await _set_role(v_email, role="viewer")

    a_headers = await _login(http_client, a_email, a_pw)
    b_headers = await _login(http_client, b_email, b_pw)
    v_headers = await _login(http_client, v_email, v_pw)

    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.projects.models import Project

    p_a = uuid.uuid4()
    p_b = uuid.uuid4()

    models = {
        "ifc": {
            "model_id": uuid.uuid4(),
            "element_id": uuid.uuid4(),
            "stable_id": "3kdF2hSdf9$RtY0bGq1aZ9",
            "type": "IfcWall",
        },
        "revit": {
            "model_id": uuid.uuid4(),
            "element_id": uuid.uuid4(),
            "stable_id": "a1b2c3d4-0000-1111-2222-333344445555-0007abcd",
            "type": "Wall",
        },
        "dwg": {"model_id": uuid.uuid4(), "element_id": uuid.uuid4(), "stable_id": "1A2F", "type": "LINE"},
    }

    async with async_session_factory() as s:
        s.add(Project(id=p_a, name="A-CC-Mat", owner_id=uuid.UUID(a_uid), status="active", currency="EUR"))
        s.add(Project(id=p_b, name="B-CC-Mat", owner_id=uuid.UUID(b_uid), status="active", currency="EUR"))
        await s.flush()
        for fmt, m in models.items():
            s.add(
                BIMModel(
                    id=m["model_id"],
                    project_id=p_a,
                    name=f"A-{fmt}-model",
                    model_format=fmt,
                    version="3",
                    status="ready",
                    metadata_={},
                )
            )
            await s.flush()
            s.add(
                BIMElement(
                    id=m["element_id"],
                    model_id=m["model_id"],
                    stable_id=m["stable_id"],
                    element_type=m["type"],
                    name=f"{fmt}-element-1",
                )
            )
        await s.commit()

    crit_resp = await http_client.post(
        f"{_CC}/criteria",
        json={
            "project_id": str(p_a),
            "code": "AC-STEEL-01",
            "title": "Structural steel yield strength",
            "standard_ref": "EN 10025-2",
            "category": "steel",
            "characteristic": "yield strength",
            "acceptance_rule": "min",
            "unit": "MPa",
            "tolerance_lower": "355",
        },
        headers=a_headers,
    )
    assert crit_resp.status_code == 201, crit_resp.text
    criterion_id = crit_resp.json()["id"]

    return {
        "a": {"uid": a_uid, "headers": a_headers},
        "b": {"uid": b_uid, "headers": b_headers},
        "v": {"uid": v_uid, "headers": v_headers},
        "p_a": str(p_a),
        "p_b": str(p_b),
        "models": {
            k: {ik: str(iv) if isinstance(iv, uuid.UUID) else iv for ik, iv in v.items()} for k, v in models.items()
        },
        "criterion_id": criterion_id,
    }


async def _create_material(client, headers, project_id, **overrides):
    payload = {
        "project_id": project_id,
        "name": "Reinforcing steel B500B",
        "material_type": "reinforcing steel",
        "spec_grade": "B500B",
        "manufacturer": "Mill One",
        "supplier": "Steel Supply Co",
        "cert_type": "3.1",
        "cert_number": "MTC-2026-0001",
        "batch_number": "B-77",
        "heat_number": "H-1234",
        "quantity": "12.5",
        "unit": "t",
    }
    payload.update(overrides)
    resp = await client.post(f"{_CC}/materials", json=payload, headers=headers)
    return resp


# ── Material conformity flow: review -> NCR ──────────────────────────────────


@pytest.mark.asyncio
async def test_material_review_pass_accepts_without_ncr(http_client, cc_world):
    a = cc_world["a"]
    create = await _create_material(http_client, a["headers"], cc_world["p_a"], criterion_id=cc_world["criterion_id"])
    assert create.status_code == 201, create.text
    body = create.json()
    material_id = body["id"]
    assert body["record_number"].startswith("MAT-")
    assert body["status"] == "draft"
    assert body["is_expired"] is False

    review = await http_client.post(
        f"{_CC}/materials/{material_id}/review",
        json={"decision": "pass", "notes": "MTC verified, conforms to EN 10025-2."},
        headers=a["headers"],
    )
    assert review.status_code == 200, review.text
    rbody = review.json()
    assert rbody["status"] == "accepted"
    assert rbody["raised_ncr_id"] is None


@pytest.mark.asyncio
async def test_material_review_fail_raises_material_ncr(http_client, cc_world):
    a = cc_world["a"]
    create = await _create_material(http_client, a["headers"], cc_world["p_a"], criterion_id=cc_world["criterion_id"])
    assert create.status_code == 201, create.text
    material_id = create.json()["id"]

    review = await http_client.post(
        f"{_CC}/materials/{material_id}/review",
        json={"decision": "fail", "notes": "Mill certificate shows 320 MPa, below 355 minimum."},
        headers=a["headers"],
    )
    assert review.status_code == 200, review.text
    rbody = review.json()
    assert rbody["status"] == "rejected"
    ncr_id = rbody["raised_ncr_id"]
    assert ncr_id, "a rejected material must raise an NCR"

    ncr_resp = await http_client.get(f"/api/v1/ncr/{ncr_id}", headers=a["headers"])
    assert ncr_resp.status_code == 200, ncr_resp.text
    ncr = ncr_resp.json()
    assert ncr["ncr_type"] == "material"
    assert ncr["severity"] == "major"
    assert ncr["project_id"] == cc_world["p_a"]


@pytest.mark.asyncio
async def test_material_review_conditional_raises_observation_ncr(http_client, cc_world):
    a = cc_world["a"]
    create = await _create_material(http_client, a["headers"], cc_world["p_a"])
    assert create.status_code == 201, create.text
    material_id = create.json()["id"]

    review = await http_client.post(
        f"{_CC}/materials/{material_id}/review",
        json={"decision": "conditional", "notes": "Accept this lot pending the 28-day retest."},
        headers=a["headers"],
    )
    assert review.status_code == 200, review.text
    rbody = review.json()
    # A conditional acceptance still accepts the material, but opens a tracked observation.
    assert rbody["status"] == "accepted"
    ncr_id = rbody["raised_ncr_id"]
    assert ncr_id

    ncr = (await http_client.get(f"/api/v1/ncr/{ncr_id}", headers=a["headers"])).json()
    assert ncr["ncr_type"] == "material"
    assert ncr["severity"] == "observation"


@pytest.mark.asyncio
async def test_material_review_is_single_shot(http_client, cc_world):
    """Once a decision is recorded the material is locked; a second review is rejected."""
    a = cc_world["a"]
    material_id = (await _create_material(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    first = await http_client.post(
        f"{_CC}/materials/{material_id}/review", json={"decision": "pass"}, headers=a["headers"]
    )
    assert first.status_code == 200, first.text
    second = await http_client.post(
        f"{_CC}/materials/{material_id}/review", json={"decision": "fail"}, headers=a["headers"]
    )
    assert second.status_code == 400, f"a locked material must not be re-reviewed: {second.text}"


@pytest.mark.asyncio
async def test_material_expiry_flag(http_client, cc_world):
    a = cc_world["a"]
    expired = await _create_material(http_client, a["headers"], cc_world["p_a"], valid_until="2000-01-01")
    assert expired.status_code == 201, expired.text
    assert expired.json()["is_expired"] is True

    valid = await _create_material(http_client, a["headers"], cc_world["p_a"], valid_until="2999-12-31")
    assert valid.status_code == 201, valid.text
    assert valid.json()["is_expired"] is False


@pytest.mark.asyncio
async def test_material_links_model_element(http_client, cc_world):
    a = cc_world["a"]
    ifc = cc_world["models"]["ifc"]
    create = await _create_material(
        http_client,
        a["headers"],
        cc_world["p_a"],
        element={"bim_element_id": ifc["element_id"]},
    )
    assert create.status_code == 201, create.text
    elements = create.json()["elements"]
    assert len(elements) == 1
    el = elements[0]
    assert el["source_format"] == "ifc"
    assert el["bim_element_id"] == ifc["element_id"]
    assert el["element_name"] == "ifc-element-1"


# ── Test-result flow: record -> NCR ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_result_pass_records_no_ncr(http_client, cc_world):
    a = cc_world["a"]
    create = await http_client.post(
        f"{_CC}/test-results",
        json={
            "project_id": cc_world["p_a"],
            "title": "Cube compressive strength, 28 days",
            "test_method": "EN 12390-3",
            "criterion_id": cc_world["criterion_id"],
            "sample_id": "C-101",
            "specimen_age_days": 28,
        },
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["result_number"].startswith("TST-")
    result_id = body["id"]

    record = await http_client.post(
        f"{_CC}/test-results/{result_id}/record-result",
        json={"result": "pass", "measured_value": "41"},
        headers=a["headers"],
    )
    assert record.status_code == 200, record.text
    rbody = record.json()
    assert rbody["status"] == "recorded"
    assert rbody["result"] == "pass"
    assert rbody["raised_ncr_id"] is None


@pytest.mark.asyncio
async def test_test_result_fail_raises_workmanship_ncr(http_client, cc_world):
    a = cc_world["a"]
    result_id = (
        await http_client.post(
            f"{_CC}/test-results",
            json={
                "project_id": cc_world["p_a"],
                "title": "Weld macro-etch",
                "test_method": "ISO 17639",
                "lab_name": "Acme Test Lab",
                "lab_accreditation": "UKAS 0001",
                "is_accredited": True,
            },
            headers=a["headers"],
        )
    ).json()["id"]

    record = await http_client.post(
        f"{_CC}/test-results/{result_id}/record-result",
        json={"result": "fail", "notes": "Lack of fusion in root pass."},
        headers=a["headers"],
    )
    assert record.status_code == 200, record.text
    rbody = record.json()
    assert rbody["status"] == "recorded"
    assert rbody["result"] == "fail"
    ncr_id = rbody["raised_ncr_id"]
    assert ncr_id, "a failed test must raise an NCR"

    ncr = (await http_client.get(f"/api/v1/ncr/{ncr_id}", headers=a["headers"])).json()
    # No material lot attached -> the non-conformance is workmanship, not material.
    assert ncr["ncr_type"] == "workmanship"
    assert ncr["severity"] == "major"
    assert ncr["project_id"] == cc_world["p_a"]


@pytest.mark.asyncio
async def test_test_tied_to_material_raises_material_ncr(http_client, cc_world):
    a = cc_world["a"]
    material_id = (await _create_material(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    result_id = (
        await http_client.post(
            f"{_CC}/test-results",
            json={
                "project_id": cc_world["p_a"],
                "title": "Tensile test on rebar lot",
                "test_method": "ISO 6892-1",
                "material_record_id": material_id,
            },
            headers=a["headers"],
        )
    ).json()["id"]

    record = await http_client.post(
        f"{_CC}/test-results/{result_id}/record-result",
        json={"result": "fail", "measured_value": "320"},
        headers=a["headers"],
    )
    assert record.status_code == 200, record.text
    ncr_id = record.json()["raised_ncr_id"]
    assert ncr_id
    ncr = (await http_client.get(f"/api/v1/ncr/{ncr_id}", headers=a["headers"])).json()
    # A test bound to a material lot is a material non-conformance.
    assert ncr["ncr_type"] == "material"


@pytest.mark.asyncio
async def test_test_result_record_is_single_shot(http_client, cc_world):
    a = cc_world["a"]
    result_id = (
        await http_client.post(
            f"{_CC}/test-results",
            json={"project_id": cc_world["p_a"], "title": "Slump test"},
            headers=a["headers"],
        )
    ).json()["id"]
    first = await http_client.post(
        f"{_CC}/test-results/{result_id}/record-result", json={"result": "pass"}, headers=a["headers"]
    )
    assert first.status_code == 200, first.text
    second = await http_client.post(
        f"{_CC}/test-results/{result_id}/record-result", json={"result": "fail"}, headers=a["headers"]
    )
    assert second.status_code == 400, f"a recorded test must not be re-recorded: {second.text}"


# ── Tenant isolation / IDOR ──────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_read_other_tenant_material(http_client, cc_world):
    a, b = cc_world["a"], cc_world["b"]
    material_id = (await _create_material(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    resp = await http_client.get(f"{_CC}/materials/{material_id}", headers=b["headers"])
    assert resp.status_code == 404, f"LEAK: B read A's material (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_create_material_in_foreign_project(http_client, cc_world):
    b = cc_world["b"]
    resp = await _create_material(http_client, b["headers"], cc_world["p_a"])
    assert resp.status_code == 404, f"LEAK: B created a material in A's project (status {resp.status_code})"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_use_foreign_criterion(http_client, cc_world):
    """B cannot judge a material in its own project against A's acceptance criterion."""
    b = cc_world["b"]
    resp = await _create_material(http_client, b["headers"], cc_world["p_b"], criterion_id=cc_world["criterion_id"])
    assert resp.status_code == 404, f"LEAK: B used A's criterion (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_tie_test_to_foreign_material(http_client, cc_world):
    """B may create a test in its own project, but cannot bind it to A's material lot."""
    a, b = cc_world["a"], cc_world["b"]
    material_id = (await _create_material(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    resp = await http_client.post(
        f"{_CC}/test-results",
        json={
            "project_id": cc_world["p_b"],
            "title": "B binds A's material",
            "material_record_id": material_id,
        },
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B tied a test to A's material (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_read_other_tenant_test(http_client, cc_world):
    a, b = cc_world["a"], cc_world["b"]
    result_id = (
        await http_client.post(
            f"{_CC}/test-results",
            json={"project_id": cc_world["p_a"], "title": "A private test"},
            headers=a["headers"],
        )
    ).json()["id"]
    resp = await http_client.get(f"{_CC}/test-results/{result_id}", headers=b["headers"])
    assert resp.status_code == 404, f"LEAK: B read A's test (status {resp.status_code}): {resp.text!r}"


# ── RBAC ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_create_material(http_client, cc_world):
    v = cc_world["v"]
    resp = await _create_material(http_client, v["headers"], cc_world["p_a"])
    assert resp.status_code in (401, 403), f"viewer must not create materials (status {resp.status_code})"


@pytest.mark.asyncio
async def test_viewer_cannot_create_test(http_client, cc_world):
    v = cc_world["v"]
    resp = await http_client.post(
        f"{_CC}/test-results",
        json={"project_id": cc_world["p_a"], "title": "viewer attempt"},
        headers=v["headers"],
    )
    assert resp.status_code in (401, 403), f"viewer must not create tests (status {resp.status_code})"
