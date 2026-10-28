"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 3 (as-built) integration + IDOR/tenant-isolation tests.

Covers the verified-record flow end to end:

* The legal-record flow: create an as-built, record a survey (tolerance computed against
  the criterion), verify it, and sign the legal-record attestation - confirming the
  record only reaches ``recorded`` once signed valid, and that the e-signature digest is
  captured.
* The NCR bridge: an as-built verified out of tolerance raises a workmanship NCR linked
  back via ``raised_ncr_id`` and ``metadata.asbuilt_id``.
* FSM guards: cannot verify before surveying, cannot sign before verifying, cannot edit a
  recorded record.
* Format-agnostic model linking: an as-built links to a model element through the same
  Universal Element Reference the inspection uses.
* Tenant isolation / IDOR: a second tenant cannot read another tenant's as-built, cannot
  create one in a project it cannot access, cannot link another tenant's model element,
  and cannot judge against another tenant's criterion.
* RBAC: a viewer cannot create; an editor can create/survey but cannot verify or sign
  (both manager-only).

Harness mirrors ``test_construction_control_materials.py``: register/activate/login real
users over HTTP, set roles via a direct DB write, seed projects/models via the DB. The
router is auto-mounted by the module loader at ``/api/v1/construction-control``.
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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@cc-asb-test.io"
    password = f"CcAsb{uuid.uuid4().hex[:6]}9"
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
    """Manager A owns P_A (three single-element BIM models IFC/Revit/DWG + a max-rule
    criterion). Manager B owns P_B (IDOR counterpart). Editor E owns P_E (its own
    criterion) so the editor RBAC checks run inside a project E can access - the only gate
    under test there is RBAC, never project access. Viewer V is a plain viewer.

    Access rule reminder: ``verify_project_access`` grants a non-admin access to a project
    they OWN (or are a team member of); RBAC (``RequirePermission``) is a separate
    dependency evaluated first. So a write a user's role forbids is a 403 regardless of
    project access, and a project a user cannot reach is a 404 regardless of role.
    """
    a_uid, a_email, a_pw = await _register(http_client, tenant="a")
    b_uid, b_email, b_pw = await _register(http_client, tenant="b")
    e_uid, e_email, e_pw = await _register(http_client, tenant="e")
    v_uid, v_email, v_pw = await _register(http_client, tenant="v")

    await _set_role(a_email, role="manager")
    await _set_role(b_email, role="manager")
    await _set_role(e_email, role="editor")
    await _set_role(v_email, role="viewer")

    a_headers = await _login(http_client, a_email, a_pw)
    b_headers = await _login(http_client, b_email, b_pw)
    e_headers = await _login(http_client, e_email, e_pw)
    v_headers = await _login(http_client, v_email, v_pw)

    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.projects.models import Project

    p_a = uuid.uuid4()
    p_b = uuid.uuid4()
    p_e = uuid.uuid4()

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
        s.add(Project(id=p_a, name="A-CC-Asb", owner_id=uuid.UUID(a_uid), status="active", currency="EUR"))
        s.add(Project(id=p_b, name="B-CC-Asb", owner_id=uuid.UUID(b_uid), status="active", currency="EUR"))
        s.add(Project(id=p_e, name="E-CC-Asb", owner_id=uuid.UUID(e_uid), status="active", currency="EUR"))
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
            "code": "AC-LEVEL-01",
            "title": "Slab flatness deviation",
            "standard_ref": "EN 13670",
            "category": "geometry",
            "characteristic": "level deviation",
            "acceptance_rule": "max",
            "unit": "mm",
            "tolerance_upper": "10",
        },
        headers=a_headers,
    )
    assert crit_resp.status_code == 201, crit_resp.text
    criterion_id = crit_resp.json()["id"]

    return {
        "a": {"uid": a_uid, "headers": a_headers},
        "b": {"uid": b_uid, "headers": b_headers},
        "e": {"uid": e_uid, "headers": e_headers},
        "v": {"uid": v_uid, "headers": v_headers},
        "p_a": str(p_a),
        "p_b": str(p_b),
        "p_e": str(p_e),
        "models": {
            k: {ik: str(iv) if isinstance(iv, uuid.UUID) else iv for ik, iv in v.items()} for k, v in models.items()
        },
        "criterion_id": criterion_id,
    }


async def _create_asbuilt(client, headers, project_id, **overrides):
    payload = {
        "project_id": project_id,
        "title": "As-built slab level survey",
        "discipline": "structural",
        "capture_method": "total_station",
        "accuracy_class": "survey",
        "coordinate_system": "EPSG:25832",
    }
    payload.update(overrides)
    return await client.post(f"{_CC}/asbuilt", json=payload, headers=headers)


# ── Happy path: survey -> verify -> sign -> recorded ─────────────────────────


@pytest.mark.asyncio
async def test_asbuilt_within_tolerance_records_after_signing(http_client, cc_world):
    a = cc_world["a"]
    create = await _create_asbuilt(http_client, a["headers"], cc_world["p_a"], criterion_id=cc_world["criterion_id"])
    assert create.status_code == 201, create.text
    body = create.json()
    record_id = body["id"]
    assert body["record_number"].startswith("ASB-")
    assert body["status"] == "draft"
    assert body["valid_for_legal_record"] is False

    survey = await http_client.post(
        f"{_CC}/asbuilt/{record_id}/record-survey",
        json={"measured_value": "6", "survey_date": "2026-06-01"},
        headers=a["headers"],
    )
    assert survey.status_code == 200, survey.text
    sbody = survey.json()
    assert sbody["status"] == "surveyed"
    assert sbody["tolerance_result"] == "within"

    verify = await http_client.post(f"{_CC}/asbuilt/{record_id}/verify", json={}, headers=a["headers"])
    assert verify.status_code == 200, verify.text
    vbody = verify.json()
    assert vbody["status"] == "verified"
    assert vbody["raised_ncr_id"] is None

    sign = await http_client.post(
        f"{_CC}/asbuilt/{record_id}/sign-validity",
        json={"valid": True, "notes": "Attested as the legal as-built."},
        headers=a["headers"],
    )
    assert sign.status_code == 200, sign.text
    fbody = sign.json()
    assert fbody["status"] == "recorded"
    assert fbody["valid_for_legal_record"] is True
    assert fbody["validity_signed_by"] == a["uid"]
    assert fbody["validity_signed_at"]
    assert fbody["validity_signature_sha256"]
    assert len(fbody["validity_signature_sha256"]) == 64


@pytest.mark.asyncio
async def test_asbuilt_out_of_tolerance_raises_workmanship_ncr(http_client, cc_world):
    a = cc_world["a"]
    record_id = (
        await _create_asbuilt(http_client, a["headers"], cc_world["p_a"], criterion_id=cc_world["criterion_id"])
    ).json()["id"]
    # 18 mm deviation against a 10 mm max criterion -> out of tolerance.
    await http_client.post(
        f"{_CC}/asbuilt/{record_id}/record-survey",
        json={"measured_value": "18"},
        headers=a["headers"],
    )
    verify = await http_client.post(f"{_CC}/asbuilt/{record_id}/verify", json={}, headers=a["headers"])
    assert verify.status_code == 200, verify.text
    vbody = verify.json()
    assert vbody["tolerance_result"] == "out_of_tolerance"
    ncr_id = vbody["raised_ncr_id"]
    assert ncr_id, "an out-of-tolerance as-built must raise an NCR"

    ncr = (await http_client.get(f"/api/v1/ncr/{ncr_id}", headers=a["headers"])).json()
    assert ncr["ncr_type"] == "workmanship"
    assert ncr["severity"] == "major"
    assert ncr["project_id"] == cc_world["p_a"]
    assert ncr["metadata"]["asbuilt_id"] == record_id


@pytest.mark.asyncio
async def test_asbuilt_no_criterion_is_not_assessed(http_client, cc_world):
    a = cc_world["a"]
    record_id = (await _create_asbuilt(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    survey = await http_client.post(
        f"{_CC}/asbuilt/{record_id}/record-survey", json={"measured_value": "5"}, headers=a["headers"]
    )
    assert survey.json()["tolerance_result"] == "not_assessed"
    # An unassessed record verifies without raising an NCR.
    verify = await http_client.post(f"{_CC}/asbuilt/{record_id}/verify", json={}, headers=a["headers"])
    assert verify.json()["raised_ncr_id"] is None


# ── FSM guards ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_verify_before_survey(http_client, cc_world):
    a = cc_world["a"]
    record_id = (await _create_asbuilt(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    resp = await http_client.post(f"{_CC}/asbuilt/{record_id}/verify", json={}, headers=a["headers"])
    assert resp.status_code == 400, f"a draft as-built must not verify: {resp.text}"


@pytest.mark.asyncio
async def test_cannot_sign_before_verify(http_client, cc_world):
    a = cc_world["a"]
    record_id = (await _create_asbuilt(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    await http_client.post(
        f"{_CC}/asbuilt/{record_id}/record-survey", json={"measured_value": "5"}, headers=a["headers"]
    )
    # Surveyed but not verified: signing is rejected.
    resp = await http_client.post(
        f"{_CC}/asbuilt/{record_id}/sign-validity", json={"valid": True}, headers=a["headers"]
    )
    assert resp.status_code == 400, f"an unverified as-built must not be signed: {resp.text}"


@pytest.mark.asyncio
async def test_cannot_edit_recorded_asbuilt(http_client, cc_world):
    a = cc_world["a"]
    record_id = (await _create_asbuilt(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    await http_client.post(
        f"{_CC}/asbuilt/{record_id}/record-survey", json={"measured_value": "5"}, headers=a["headers"]
    )
    await http_client.post(f"{_CC}/asbuilt/{record_id}/verify", json={}, headers=a["headers"])
    await http_client.post(f"{_CC}/asbuilt/{record_id}/sign-validity", json={"valid": True}, headers=a["headers"])
    resp = await http_client.patch(f"{_CC}/asbuilt/{record_id}", json={"title": "tampered"}, headers=a["headers"])
    assert resp.status_code == 400, f"a recorded as-built must be immutable: {resp.text}"


# ── Model linking (UER) ─────────────────────────────────────────────────────--


@pytest.mark.asyncio
async def test_asbuilt_links_model_element(http_client, cc_world):
    a = cc_world["a"]
    ifc = cc_world["models"]["ifc"]
    create = await _create_asbuilt(
        http_client, a["headers"], cc_world["p_a"], element={"bim_element_id": ifc["element_id"]}
    )
    assert create.status_code == 201, create.text
    elements = create.json()["elements"]
    assert len(elements) == 1
    el = elements[0]
    assert el["source_format"] == "ifc"
    assert el["bim_element_id"] == ifc["element_id"]
    assert el["element_name"] == "ifc-element-1"


# ── Tenant isolation / IDOR ──────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_read_other_tenant_asbuilt(http_client, cc_world):
    a, b = cc_world["a"], cc_world["b"]
    record_id = (await _create_asbuilt(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    resp = await http_client.get(f"{_CC}/asbuilt/{record_id}", headers=b["headers"])
    assert resp.status_code == 404, f"LEAK: B read A's as-built (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_create_asbuilt_in_foreign_project(http_client, cc_world):
    b = cc_world["b"]
    resp = await _create_asbuilt(http_client, b["headers"], cc_world["p_a"])
    assert resp.status_code == 404, f"LEAK: B created an as-built in A's project (status {resp.status_code})"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_use_foreign_criterion(http_client, cc_world):
    """B cannot judge an as-built in its own project against A's acceptance criterion."""
    b = cc_world["b"]
    resp = await _create_asbuilt(http_client, b["headers"], cc_world["p_b"], criterion_id=cc_world["criterion_id"])
    assert resp.status_code == 404, f"LEAK: B used A's criterion (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_link_foreign_model_element(http_client, cc_world):
    """B cannot link A's model element into an as-built in B's own project."""
    b = cc_world["b"]
    ifc = cc_world["models"]["ifc"]
    resp = await _create_asbuilt(
        http_client, b["headers"], cc_world["p_b"], element={"bim_element_id": ifc["element_id"]}
    )
    assert resp.status_code == 404, f"LEAK: B linked A's element (status {resp.status_code}): {resp.text!r}"


# ── RBAC ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_create_asbuilt(http_client, cc_world):
    v = cc_world["v"]
    resp = await _create_asbuilt(http_client, v["headers"], cc_world["p_a"])
    assert resp.status_code in (401, 403), f"viewer must not create as-builts (status {resp.status_code})"


@pytest.mark.asyncio
async def test_editor_can_create_and_survey_but_not_verify_or_sign(http_client, cc_world):
    """An editor creates and surveys in its own project, but verify and sign are
    manager-only. Runs inside P_E (the editor owns it) so RBAC, not project access, is the
    only gate; the 401/403 therefore proves the permission boundary rather than ownership.
    """
    e = cc_world["e"]
    p_e = cc_world["p_e"]
    create = await _create_asbuilt(http_client, e["headers"], p_e)
    assert create.status_code == 201, create.text
    record_id = create.json()["id"]

    survey = await http_client.post(
        f"{_CC}/asbuilt/{record_id}/record-survey", json={"measured_value": "5"}, headers=e["headers"]
    )
    assert survey.status_code == 200, survey.text

    verify = await http_client.post(f"{_CC}/asbuilt/{record_id}/verify", json={}, headers=e["headers"])
    assert verify.status_code in (401, 403), f"editor must not verify (status {verify.status_code}): {verify.text}"

    sign = await http_client.post(
        f"{_CC}/asbuilt/{record_id}/sign-validity", json={"valid": True}, headers=e["headers"]
    )
    assert sign.status_code in (401, 403), f"editor must not sign (status {sign.status_code}): {sign.text}"
