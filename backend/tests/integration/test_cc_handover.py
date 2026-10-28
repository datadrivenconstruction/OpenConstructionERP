"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 4 (handover) integration + IDOR/tenant-isolation tests.

Covers the handover / acceptance package end to end:

* Happy path: create a package, auto-assemble the acceptance-evidence manifest, and -
  with a clear completion gate - e-sign and issue the acceptance certificate (the
  signature digest is captured and the package reaches ``issued``).
* The completion gate (the headline cross-pillar behaviour): an unreleased blocking hold
  gate on the project blocks issue with 409; after a satisfying-party release the gate
  clears and the certificate issues.
* Open-NCR gate: an inspection recorded as failed raises an NCR, which blocks issue;
  the gate report surfaces the open-NCR count.
* Manager override: a manager can override a blocked gate (recorded as a documentation
  NCR) and then issue over the snag list.
* FSM guards: an issued package cannot be edited or re-issued, but can be revoked.
* Tenant isolation / IDOR: a second tenant cannot read another tenant's package, cannot
  create one in a project it cannot access, and cannot link another tenant's model
  element.
* RBAC: a viewer cannot create; an editor can create / assemble but cannot issue or
  override (both manager-only).

Harness mirrors ``test_cc_gating.py``: register/activate/login real users over HTTP, set
roles via a direct DB write, seed projects via the DB. Because the completion gate counts
open NCRs and unreleased holds across the whole project, gate-sensitive tests each create
their own fresh project so they never share gate state.
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
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, *, tenant: str) -> tuple[str, str, str]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@cc-handover-test.io"
    password = f"CcHov{uuid.uuid4().hex[:6]}9"
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


async def _new_project(owner_uid: str, *, name: str) -> str:
    """Create a fresh project owned by ``owner_uid`` and return its id as a string.

    Gate-sensitive tests use their own project so the project-wide NCR / hold counts
    never bleed across tests.
    """
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(Project(id=pid, name=name, owner_id=uuid.UUID(owner_uid), status="active", currency="EUR"))
        await s.commit()
    return str(pid)


@pytest_asyncio.fixture(scope="module")
async def cc_world(http_client):
    """Manager A owns P_A. Manager B owns P_B (IDOR counterpart). Editor E owns P_E for the
    editor RBAC checks. Viewer V is a plain viewer."""
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

    p_a = await _new_project(a_uid, name="A-CC-Handover")
    p_b = await _new_project(b_uid, name="B-CC-Handover")
    p_e = await _new_project(e_uid, name="E-CC-Handover")

    return {
        "a": {"uid": a_uid, "headers": a_headers},
        "b": {"uid": b_uid, "headers": b_headers},
        "e": {"uid": e_uid, "headers": e_headers},
        "v": {"uid": v_uid, "headers": v_headers},
        "p_a": p_a,
        "p_b": p_b,
        "p_e": p_e,
    }


async def _create_package(client, headers, project_id, **overrides):
    payload = {"project_id": project_id, "title": "Practical completion - Block A"}
    payload.update(overrides)
    return await client.post(f"{_CC}/handover", json=payload, headers=headers)


async def _create_hold_gate(client, headers, project_id, **overrides):
    payload = {"project_id": project_id, "title": "Outstanding hold", "point_type": "hold"}
    payload.update(overrides)
    return await client.post(f"{_CC}/gates", json=payload, headers=headers)


# ── Happy path: clear gate -> assemble -> issue ────────────────────────────────


@pytest.mark.asyncio
async def test_create_assemble_issue_happy_path(http_client, cc_world):
    a = cc_world["a"]
    project = await _new_project(a["uid"], name="HOV-happy")

    create = await _create_package(http_client, a["headers"], project, completion_regime="practical")
    assert create.status_code == 201, create.text
    pkg = create.json()
    assert pkg["package_number"].startswith("HOP-")
    assert pkg["status"] == "draft"
    assert pkg["gating_state"] == "blocked"  # not validated yet

    assemble = await http_client.post(f"{_CC}/handover/{pkg['id']}/assemble", headers=a["headers"])
    assert assemble.status_code == 200, assemble.text
    abody = assemble.json()
    # No NCRs and no holds in this fresh project -> the gate is clear and the package ready.
    assert abody["gating_state"] == "clear"
    assert abody["status"] == "ready"
    assert abody["open_ncr_count"] == 0
    assert abody["unreleased_hold_count"] == 0

    issue = await http_client.post(
        f"{_CC}/handover/{pkg['id']}/issue",
        json={"notes": "Practical completion granted."},
        headers=a["headers"],
    )
    assert issue.status_code == 200, issue.text
    ibody = issue.json()
    assert ibody["status"] == "issued"
    assert ibody["issued_by"] == a["uid"]
    assert ibody["certificate_no"]
    assert ibody["issue_signature_sha256"]
    assert len(ibody["issue_signature_sha256"]) == 64


# ── Completion gate: unreleased hold blocks issue (cross-pillar) ───────────────


@pytest.mark.asyncio
async def test_unreleased_hold_blocks_issue_then_release_clears(http_client, cc_world):
    """The headline cross-pillar behaviour: an unreleased blocking hold gate on the
    project blocks the acceptance certificate; releasing it lets the certificate issue."""
    a = cc_world["a"]
    project = await _new_project(a["uid"], name="HOV-hold-gate")

    pkg = (await _create_package(http_client, a["headers"], project)).json()

    # A hold gate attached to this very handover package (also a project-wide blocker).
    gate = (
        await _create_hold_gate(
            http_client,
            a["headers"],
            project,
            attached_kind="handover_package",
            attached_id=pkg["id"],
            required_party_role="qa",
        )
    ).json()
    assert gate["blocks_progress"] is True

    # Assemble: the gate is blocked by the unreleased hold.
    assemble = await http_client.post(f"{_CC}/handover/{pkg['id']}/assemble", headers=a["headers"])
    assert assemble.status_code == 200, assemble.text
    assert assemble.json()["gating_state"] == "blocked"
    assert assemble.json()["unreleased_hold_count"] >= 1
    # The package's own gate report surfaces the blocking gate number.
    gates = await http_client.get(f"{_CC}/handover/{pkg['id']}/gates", headers=a["headers"])
    assert gates.status_code == 200, gates.text
    gbody = gates.json()
    assert gbody["can_issue"] is False
    assert gate["gate_number"] in gbody["blocking_gate_numbers"]

    # Issue is refused while the gate is blocked.
    blocked = await http_client.post(f"{_CC}/handover/{pkg['id']}/issue", json={}, headers=a["headers"])
    assert blocked.status_code == 409, f"issue must be blocked by the hold gate: {blocked.text}"

    # Release the hold as qa.
    release = await http_client.post(
        f"{_CC}/gates/{gate['id']}/release",
        json={"party_role": "qa", "justification": "Outstanding item resolved and inspected."},
        headers=a["headers"],
    )
    assert release.status_code == 200, release.text

    # The gate clears and the certificate now issues.
    gates_after = await http_client.get(f"{_CC}/handover/{pkg['id']}/gates", headers=a["headers"])
    assert gates_after.json()["can_issue"] is True
    issue = await http_client.post(f"{_CC}/handover/{pkg['id']}/issue", json={}, headers=a["headers"])
    assert issue.status_code == 200, f"issue should succeed after release: {issue.text}"
    assert issue.json()["status"] == "issued"


# ── Completion gate: open NCR blocks issue ─────────────────────────────────────


@pytest.mark.asyncio
async def test_open_ncr_blocks_issue(http_client, cc_world):
    a = cc_world["a"]
    project = await _new_project(a["uid"], name="HOV-open-ncr")

    # A failed inspection raises an NCR on the project (Pillar 1 fail -> NCR bridge).
    insp = await http_client.post(
        f"{_CC}/inspections",
        json={"project_id": project, "inspection_type": "ir", "title": "Final inspection"},
        headers=a["headers"],
    )
    assert insp.status_code == 201, insp.text
    rec = await http_client.post(
        f"{_CC}/inspections/{insp.json()['id']}/record-result",
        json={"result": "fail", "notes": "Defect found."},
        headers=a["headers"],
    )
    assert rec.status_code == 200, rec.text
    assert rec.json()["raised_ncr_id"]

    pkg = (await _create_package(http_client, a["headers"], project)).json()
    gates = await http_client.get(f"{_CC}/handover/{pkg['id']}/gates", headers=a["headers"])
    gbody = gates.json()
    assert gbody["open_ncr_count"] >= 1
    assert gbody["gating_state"] == "blocked"
    assert gbody["can_issue"] is False

    blocked = await http_client.post(f"{_CC}/handover/{pkg['id']}/issue", json={}, headers=a["headers"])
    assert blocked.status_code == 409, f"an open NCR must block issue: {blocked.text}"


# ── Manager override of a blocked gate ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_override_then_issue(http_client, cc_world):
    a = cc_world["a"]
    project = await _new_project(a["uid"], name="HOV-override")

    # A blocking hold to make the gate blocked.
    pkg = (await _create_package(http_client, a["headers"], project)).json()
    await _create_hold_gate(http_client, a["headers"], project, attached_kind="handover_package", attached_id=pkg["id"])

    # Override the blocked gate (manager); this records a documentation NCR.
    override = await http_client.post(
        f"{_CC}/handover/{pkg['id']}/override-gate",
        json={"reason": "FIDIC taking-over with an agreed snag list."},
        headers=a["headers"],
    )
    assert override.status_code == 200, override.text
    obody = override.json()
    assert obody["gating_state"] == "overridden"
    assert obody["gating_override_by"] == a["uid"]

    # Issue now succeeds over the snag list.
    issue = await http_client.post(f"{_CC}/handover/{pkg['id']}/issue", json={}, headers=a["headers"])
    assert issue.status_code == 200, f"issue should succeed after override: {issue.text}"
    assert issue.json()["status"] == "issued"


@pytest.mark.asyncio
async def test_override_refused_when_gate_clear(http_client, cc_world):
    a = cc_world["a"]
    project = await _new_project(a["uid"], name="HOV-override-clear")
    pkg = (await _create_package(http_client, a["headers"], project)).json()
    # No blockers -> overriding a clear gate is a 409 (nothing to override).
    resp = await http_client.post(
        f"{_CC}/handover/{pkg['id']}/override-gate",
        json={"reason": "unnecessary"},
        headers=a["headers"],
    )
    assert resp.status_code == 409, f"overriding a clear gate must be refused: {resp.text}"


# ── FSM guards ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issued_package_cannot_be_edited_or_reissued_but_can_revoke(http_client, cc_world):
    a = cc_world["a"]
    project = await _new_project(a["uid"], name="HOV-fsm")
    pkg = (await _create_package(http_client, a["headers"], project)).json()
    await http_client.post(f"{_CC}/handover/{pkg['id']}/assemble", headers=a["headers"])
    issue = await http_client.post(f"{_CC}/handover/{pkg['id']}/issue", json={}, headers=a["headers"])
    assert issue.status_code == 200, issue.text

    # An issued package is immutable.
    patch = await http_client.patch(f"{_CC}/handover/{pkg['id']}", json={"title": "renamed"}, headers=a["headers"])
    assert patch.status_code == 400, f"an issued package must not be editable: {patch.text}"

    # It cannot be issued again.
    again = await http_client.post(f"{_CC}/handover/{pkg['id']}/issue", json={}, headers=a["headers"])
    assert again.status_code == 400, f"an issued package must not re-issue: {again.text}"

    # But it can be revoked.
    revoke = await http_client.post(f"{_CC}/handover/{pkg['id']}/revoke", headers=a["headers"])
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "revoked"


# ── Tenant isolation / IDOR ──────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_read_other_tenant_package(http_client, cc_world):
    a, b = cc_world["a"], cc_world["b"]
    pkg_id = (await _create_package(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    resp = await http_client.get(f"{_CC}/handover/{pkg_id}", headers=b["headers"])
    assert resp.status_code == 404, f"LEAK: B read A's handover package (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_create_package_in_foreign_project(http_client, cc_world):
    b = cc_world["b"]
    resp = await _create_package(http_client, b["headers"], cc_world["p_a"])
    assert resp.status_code == 404, f"LEAK: B created a package in A's project (status {resp.status_code})"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_issue_other_tenant_package(http_client, cc_world):
    """B cannot drive A's package through its lifecycle (issue is project-access gated)."""
    a, b = cc_world["a"], cc_world["b"]
    pkg_id = (await _create_package(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    resp = await http_client.post(f"{_CC}/handover/{pkg_id}/issue", json={}, headers=b["headers"])
    assert resp.status_code == 404, f"LEAK: B issued A's package (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_link_foreign_model_element(http_client, cc_world):
    """B cannot attach a model element from A's project to a package in B's own project."""
    a, b = cc_world["a"], cc_world["b"]
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel

    model_id = uuid.uuid4()
    element_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(BIMModel(id=model_id, project_id=uuid.UUID(cc_world["p_a"]), name="A model", model_format="ifc"))
        await s.flush()
        s.add(
            BIMElement(
                id=element_id,
                model_id=model_id,
                stable_id="3kdF2hSdf9$RtY0bGq1aZ9",
                name="A wall",
                element_type="IfcWall",
            )
        )
        await s.commit()

    resp = await _create_package(
        http_client,
        b["headers"],
        cc_world["p_b"],
        element={"bim_element_id": str(element_id)},
    )
    assert resp.status_code == 404, f"LEAK: B linked A's element (status {resp.status_code}): {resp.text!r}"


# ── RBAC ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_create_package(http_client, cc_world):
    v = cc_world["v"]
    resp = await _create_package(http_client, v["headers"], cc_world["p_a"])
    assert resp.status_code in (401, 403), f"viewer must not create packages (status {resp.status_code})"


@pytest.mark.asyncio
async def test_editor_can_create_and_assemble_but_not_issue_or_override(http_client, cc_world):
    """An editor creates and assembles a package in its own project but cannot issue the
    certificate or override the gate (both manager-only)."""
    e = cc_world["e"]
    project = await _new_project(e["uid"], name="HOV-editor")
    # Editor must be able to access this project: it owns it (owner_id == e.uid).
    create = await _create_package(http_client, e["headers"], project)
    assert create.status_code == 201, create.text
    pkg_id = create.json()["id"]

    assemble = await http_client.post(f"{_CC}/handover/{pkg_id}/assemble", headers=e["headers"])
    assert assemble.status_code == 200, f"editor should be able to assemble: {assemble.text}"

    issue = await http_client.post(f"{_CC}/handover/{pkg_id}/issue", json={}, headers=e["headers"])
    assert issue.status_code in (401, 403), f"editor must not issue (status {issue.status_code}): {issue.text}"

    override = await http_client.post(
        f"{_CC}/handover/{pkg_id}/override-gate", json={"reason": "x"}, headers=e["headers"]
    )
    assert override.status_code in (401, 403), f"editor must not override (status {override.status_code})"
