"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control (Pillar 1) integration + IDOR/tenant-isolation tests.

Covers the universal QA/QC core end to end:

* The acceptance flow: create an acceptance criterion, create an ``acceptance``
  inspection linked to a model element, record a FAIL, and confirm a linked NCR is
  raised automatically and the inspection points back at it.
* Format-agnostic model linking: the same inspection links resolve against an IFC,
  a Revit and a DWG model through the normalised ``(model_id, stable_id)`` identity,
  with IFC GlobalId never required.
* Tenant isolation / IDOR: a second tenant cannot read another tenant's inspection,
  cannot create an inspection in a project it cannot access, and cannot link an
  inspection in its own project to another tenant's model.
* RBAC: a viewer cannot create criteria or inspections.

Structure mirrors ``test_bim_hub_idor.py``: register/activate/login real users over
HTTP, set roles via a direct DB write, seed projects/models via the DB. The router is
auto-mounted by the module loader at ``/api/v1/construction-control``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@cc-test.io"
    password = f"CcTest{uuid.uuid4().hex[:6]}9"
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
    """Two editor tenants (A, B) + one viewer (V), each with a project for A and B.

    A owns project P_A and three single-element BIM models (IFC / Revit / DWG) under it,
    plus an acceptance criterion. B owns P_B (so B can legitimately create inspections
    in its own project for the IDOR tests). V is a viewer for the RBAC negative.
    """
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

    # One model per format, each with a single element. stable_id mimics each
    # format's native stable id (IFC GlobalId / Revit UniqueId / DWG handle).
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
        s.add(Project(id=p_a, name="A-CC-Project", owner_id=uuid.UUID(a_uid), status="active", currency="EUR"))
        s.add(Project(id=p_b, name="B-CC-Project", owner_id=uuid.UUID(b_uid), status="active", currency="EUR"))
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

    # Acceptance criterion under P_A, created over HTTP by A (proves editor can write).
    crit_resp = await http_client.post(
        "/api/v1/construction-control/criteria",
        json={
            "project_id": str(p_a),
            "code": "AC-CONC-01",
            "title": "Concrete cube compressive strength",
            "standard_ref": "EN 1992-1-1",
            "category": "concrete",
            "characteristic": "28-day cube compressive strength",
            "acceptance_rule": "min",
            "unit": "MPa",
            "tolerance_lower": "30",
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


# ── Acceptance flow: fail -> NCR ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acceptance_fail_raises_linked_ncr(http_client, cc_world):
    a = cc_world["a"]
    ifc = cc_world["models"]["ifc"]

    # Create an acceptance inspection linked to the IFC element by its strong id.
    create = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={
            "project_id": cc_world["p_a"],
            "inspection_type": "acceptance",
            "party_role": "qa",
            "title": "Acceptance of wall W-12",
            "criterion_id": cc_world["criterion_id"],
            "element": {"bim_element_id": ifc["element_id"]},
        },
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    body = create.json()
    inspection_id = body["id"]
    assert body["inspection_number"].startswith("INS-")
    assert body["status"] == "draft"
    # UER resolved + display fields backfilled from the IFC model/element.
    assert len(body["elements"]) == 1
    el = body["elements"][0]
    assert el["source_format"] == "ifc"
    assert el["bim_element_id"] == ifc["element_id"]
    assert el["element_name"] == "ifc-element-1"
    assert el["model_version"] == "3"
    # IFC stable_id is a 22-char GlobalId, so the BCF crosswalk is auto-populated.
    assert el["ifc_global_id"] == ifc["stable_id"]

    # Record a FAIL -> an NCR must be raised and linked.
    result = await http_client.post(
        f"/api/v1/construction-control/inspections/{inspection_id}/record-result",
        json={"result": "fail", "measured_value": "21", "notes": "Below 30 MPa minimum."},
        headers=a["headers"],
    )
    assert result.status_code == 200, result.text
    rbody = result.json()
    assert rbody["status"] == "failed"
    assert rbody["result"] == "fail"
    ncr_id = rbody["raised_ncr_id"]
    assert ncr_id, "a failed acceptance inspection must raise an NCR"

    # The NCR exists, is in this project, and links back to the inspection.
    ncr_resp = await http_client.get(f"/api/v1/ncr/{ncr_id}", headers=a["headers"])
    assert ncr_resp.status_code == 200, ncr_resp.text
    ncr = ncr_resp.json()
    assert ncr["linked_inspection_id"] == inspection_id
    assert ncr["severity"] == "major"
    assert ncr["ncr_type"] == "workmanship"
    assert ncr["project_id"] == cc_world["p_a"]


@pytest.mark.asyncio
async def test_pass_records_no_ncr(http_client, cc_world):
    a = cc_world["a"]
    create = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={
            "project_id": cc_world["p_a"],
            "inspection_type": "ir",
            "title": "Final inspection, room 101",
        },
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    inspection_id = create.json()["id"]

    result = await http_client.post(
        f"/api/v1/construction-control/inspections/{inspection_id}/record-result",
        json={"result": "pass"},
        headers=a["headers"],
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "passed"
    assert body["result"] == "pass"
    assert body["raised_ncr_id"] is None


# ── Format-agnostic linking (IFC / Revit / DWG) ──────────────────────────────


@pytest.mark.parametrize("fmt", ["ifc", "revit", "dwg"])
@pytest.mark.asyncio
async def test_element_link_resolves_for_every_format(http_client, cc_world, fmt):
    """The same inspection links resolve against IFC, Revit and DWG models."""
    a = cc_world["a"]
    model = cc_world["models"][fmt]

    create = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={
            "project_id": cc_world["p_a"],
            "inspection_type": "wir",
            "title": f"Witness inspection ({fmt})",
            # Link by the normalised identity, NOT by IFC GlobalId.
            "element": {"model_id": model["model_id"], "stable_id": model["stable_id"]},
        },
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    elements = create.json()["elements"]
    assert len(elements) == 1
    el = elements[0]
    assert el["source_format"] == fmt
    # The element was ingested, so the strong id is resolved from (model, stable_id).
    assert el["bim_element_id"] == model["element_id"]
    assert el["element_name"] == f"{fmt}-element-1"


# ── Tenant isolation / IDOR ──────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_read_other_tenant_inspection(http_client, cc_world):
    a, b = cc_world["a"], cc_world["b"]
    # A creates an inspection in its project.
    create = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={"project_id": cc_world["p_a"], "inspection_type": "ir", "title": "A private inspection"},
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    inspection_id = create.json()["id"]

    # B (editor, holds cc.inspection.read via role) must not be able to read it.
    resp = await http_client.get(f"/api/v1/construction-control/inspections/{inspection_id}", headers=b["headers"])
    assert resp.status_code == 404, f"LEAK: B read A's inspection (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_create_in_foreign_project(http_client, cc_world):
    b = cc_world["b"]
    resp = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={"project_id": cc_world["p_a"], "inspection_type": "ir", "title": "B intrudes into A's project"},
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B created an inspection in A's project (status {resp.status_code})"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_link_foreign_model(http_client, cc_world):
    """B may create in its own project, but cannot link to A's model (cross-tenant UER)."""
    b = cc_world["b"]
    ifc = cc_world["models"]["ifc"]
    resp = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={
            "project_id": cc_world["p_b"],
            "inspection_type": "ir",
            "title": "B links A's model",
            "element": {"bim_element_id": ifc["element_id"]},
        },
        headers=b["headers"],
    )
    assert resp.status_code == 404, (
        f"LEAK: B linked an inspection to A's model (status {resp.status_code}): {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_use_foreign_criterion(http_client, cc_world):
    """B cannot attach A's acceptance criterion to an inspection in B's own project."""
    b = cc_world["b"]
    resp = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={
            "project_id": cc_world["p_b"],
            "inspection_type": "acceptance",
            "title": "B borrows A's criterion",
            "criterion_id": cc_world["criterion_id"],
        },
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B used A's criterion (status {resp.status_code}): {resp.text!r}"


# ── RBAC ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_create_criterion(http_client, cc_world):
    v = cc_world["v"]
    resp = await http_client.post(
        "/api/v1/construction-control/criteria",
        json={"project_id": cc_world["p_a"], "code": "X", "title": "viewer attempt"},
        headers=v["headers"],
    )
    assert resp.status_code in (401, 403), f"viewer must not create criteria (status {resp.status_code})"


@pytest.mark.asyncio
async def test_viewer_cannot_create_inspection(http_client, cc_world):
    v = cc_world["v"]
    resp = await http_client.post(
        "/api/v1/construction-control/inspections",
        json={"project_id": cc_world["p_a"], "inspection_type": "ir", "title": "viewer attempt"},
        headers=v["headers"],
    )
    assert resp.status_code in (401, 403), f"viewer must not create inspections (status {resp.status_code})"
