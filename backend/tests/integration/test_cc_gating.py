"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pillar 5 (gating) integration + IDOR/tenant-isolation tests.

Covers the hold/witness/surveillance/review gating engine end to end:

* Hold blocks, then releases: a hold gate attached to an activity makes ``can-proceed``
  report blocked; after a satisfying-party release it reports clear, and the release
  captures an e-signature.
* Surveillance never blocks: a surveillance gate on the same activity does not block.
* Party-role defence in depth: a qc cannot release an ahj gate (403), even though the
  caller is a manager (RBAC alone would allow it).
* Witness waive: a witness gate may be waived; a hold gate may not (409).
* Linked-inspection guard: a gate naming an inspection that has not passed cannot be
  released yet.
* Tenant isolation / IDOR: a second tenant cannot read another tenant's gate, cannot
  create one in a project it cannot access, and cannot cross-link another tenant's
  inspection or criterion.
* RBAC: a viewer cannot create; an editor can create but cannot release.

Harness mirrors ``test_construction_control_materials.py``.
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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@cc-gate-test.io"
    password = f"CcGate{uuid.uuid4().hex[:6]}9"
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
    """Manager A owns P_A (+ a criterion). Manager B owns P_B (IDOR counterpart). Editor E
    owns P_E for the editor RBAC checks. Viewer V is a plain viewer."""
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
    from app.modules.projects.models import Project

    p_a = uuid.uuid4()
    p_b = uuid.uuid4()
    p_e = uuid.uuid4()

    async with async_session_factory() as s:
        s.add(Project(id=p_a, name="A-CC-Gate", owner_id=uuid.UUID(a_uid), status="active", currency="EUR"))
        s.add(Project(id=p_b, name="B-CC-Gate", owner_id=uuid.UUID(b_uid), status="active", currency="EUR"))
        s.add(Project(id=p_e, name="E-CC-Gate", owner_id=uuid.UUID(e_uid), status="active", currency="EUR"))
        await s.commit()

    crit_resp = await http_client.post(
        f"{_CC}/criteria",
        json={"project_id": str(p_a), "code": "AC-GATE-01", "title": "Reinforcement before pour"},
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
        "criterion_id": criterion_id,
    }


def _activity_id() -> str:
    """A fresh soft activity id so tests do not share gating state on one entity."""
    return f"act-{uuid.uuid4().hex[:12]}"


async def _create_gate(client, headers, project_id, **overrides):
    payload = {"project_id": project_id, "title": "Hold before concrete pour", "point_type": "hold"}
    payload.update(overrides)
    return await client.post(f"{_CC}/gates", json=payload, headers=headers)


async def _can_proceed(client, headers, project_id, kind, attached_id):
    return await client.get(
        f"{_CC}/gates/can-proceed",
        params={"project_id": project_id, "kind": kind, "id": attached_id},
        headers=headers,
    )


# ── Hold blocks then releases ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hold_blocks_then_qa_release_clears(http_client, cc_world):
    a = cc_world["a"]
    activity = _activity_id()
    create = await _create_gate(
        http_client,
        a["headers"],
        cc_world["p_a"],
        attached_kind="activity",
        attached_id=activity,
        required_party_role="qa",
    )
    assert create.status_code == 201, create.text
    gate = create.json()
    assert gate["gate_number"].startswith("GATE-")
    assert gate["status"] == "pending"
    assert gate["blocks_progress"] is True

    before = await _can_proceed(http_client, a["headers"], cc_world["p_a"], "activity", activity)
    assert before.status_code == 200, before.text
    bbody = before.json()
    assert bbody["can_proceed"] is False
    assert gate["gate_number"] in bbody["blocking_gate_numbers"]

    release = await http_client.post(
        f"{_CC}/gates/{gate['id']}/release",
        json={"party_role": "qa", "justification": "Reinforcement inspected and accepted."},
        headers=a["headers"],
    )
    assert release.status_code == 200, release.text
    rbody = release.json()
    assert rbody["status"] == "released"
    assert rbody["released_party_role"] == "qa"
    assert rbody["released_by"] == a["uid"]
    assert rbody["release_signature_sha256"]
    assert len(rbody["release_signature_sha256"]) == 64

    after = await _can_proceed(http_client, a["headers"], cc_world["p_a"], "activity", activity)
    assert after.json()["can_proceed"] is True


@pytest.mark.asyncio
async def test_surveillance_gate_does_not_block(http_client, cc_world):
    a = cc_world["a"]
    activity = _activity_id()
    create = await _create_gate(
        http_client,
        a["headers"],
        cc_world["p_a"],
        title="Surveillance walk",
        point_type="surveillance",
        attached_kind="activity",
        attached_id=activity,
    )
    assert create.status_code == 201, create.text
    # A surveillance point defaults to non-blocking.
    assert create.json()["blocks_progress"] is False
    proceed = await _can_proceed(http_client, a["headers"], cc_world["p_a"], "activity", activity)
    assert proceed.json()["can_proceed"] is True


@pytest.mark.asyncio
async def test_higher_authority_may_release_lower_gate(http_client, cc_world):
    """An ahj party may release a gate that only requires qa (rank covers down)."""
    a = cc_world["a"]
    activity = _activity_id()
    gate = (
        await _create_gate(
            http_client,
            a["headers"],
            cc_world["p_a"],
            attached_kind="activity",
            attached_id=activity,
            required_party_role="qa",
        )
    ).json()
    release = await http_client.post(
        f"{_CC}/gates/{gate['id']}/release",
        json={"party_role": "ahj", "justification": "Authority sign-off."},
        headers=a["headers"],
    )
    assert release.status_code == 200, release.text
    assert release.json()["status"] == "released"


# ── Party-role defence in depth ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_qc_cannot_release_ahj_gate(http_client, cc_world):
    """The headline rule: a contractor QC cannot release an authority gate, even as a
    manager (RBAC alone would allow the call)."""
    a = cc_world["a"]
    activity = _activity_id()
    gate = (
        await _create_gate(
            http_client,
            a["headers"],
            cc_world["p_a"],
            title="Authority hold",
            attached_kind="activity",
            attached_id=activity,
            required_party_role="ahj",
        )
    ).json()
    resp = await http_client.post(
        f"{_CC}/gates/{gate['id']}/release",
        json={"party_role": "qc", "justification": "trying to self-release"},
        headers=a["headers"],
    )
    assert resp.status_code == 403, f"a qc must not release an ahj gate (status {resp.status_code}): {resp.text}"
    # The gate is still pending and still blocks.
    proceed = await _can_proceed(http_client, a["headers"], cc_world["p_a"], "activity", activity)
    assert proceed.json()["can_proceed"] is False


# ── Waive semantics ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_witness_gate_can_be_waived(http_client, cc_world):
    a = cc_world["a"]
    gate = (
        await _create_gate(http_client, a["headers"], cc_world["p_a"], title="Witness pour", point_type="witness")
    ).json()
    resp = await http_client.post(
        f"{_CC}/gates/{gate['id']}/waive",
        json={"reason": "Client waived attendance for this pour."},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "waived"


@pytest.mark.asyncio
async def test_hold_gate_cannot_be_waived(http_client, cc_world):
    a = cc_world["a"]
    gate = (await _create_gate(http_client, a["headers"], cc_world["p_a"])).json()
    resp = await http_client.post(
        f"{_CC}/gates/{gate['id']}/waive", json={"reason": "skip the hold"}, headers=a["headers"]
    )
    assert resp.status_code == 409, f"a hold gate must not be waivable (status {resp.status_code}): {resp.text}"


# ── Linked-inspection guard ────────────────────────────────────────────────---


@pytest.mark.asyncio
async def test_gate_with_unpassed_inspection_cannot_release(http_client, cc_world):
    a = cc_world["a"]
    # An inspection that has NOT passed (created, left as draft).
    insp = await http_client.post(
        f"{_CC}/inspections",
        json={"project_id": cc_world["p_a"], "inspection_type": "wir", "title": "Pre-pour WIR"},
        headers=a["headers"],
    )
    assert insp.status_code == 201, insp.text
    inspection_id = insp.json()["id"]

    gate = (
        await _create_gate(
            http_client,
            a["headers"],
            cc_world["p_a"],
            inspection_id=inspection_id,
            required_party_role="qa",
        )
    ).json()
    resp = await http_client.post(
        f"{_CC}/gates/{gate['id']}/release",
        json={"party_role": "qa", "justification": "early release attempt"},
        headers=a["headers"],
    )
    assert resp.status_code == 400, f"a gate on an unpassed inspection must not release: {resp.text}"


# ── Tenant isolation / IDOR ──────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_read_other_tenant_gate(http_client, cc_world):
    a, b = cc_world["a"], cc_world["b"]
    gate_id = (await _create_gate(http_client, a["headers"], cc_world["p_a"])).json()["id"]
    resp = await http_client.get(f"{_CC}/gates/{gate_id}", headers=b["headers"])
    assert resp.status_code == 404, f"LEAK: B read A's gate (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_create_gate_in_foreign_project(http_client, cc_world):
    b = cc_world["b"]
    resp = await _create_gate(http_client, b["headers"], cc_world["p_a"])
    assert resp.status_code == 404, f"LEAK: B created a gate in A's project (status {resp.status_code})"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_use_foreign_criterion(http_client, cc_world):
    """B cannot attach A's criterion to a gate in B's own project."""
    b = cc_world["b"]
    resp = await _create_gate(http_client, b["headers"], cc_world["p_b"], criterion_id=cc_world["criterion_id"])
    assert resp.status_code == 404, f"LEAK: B used A's criterion (status {resp.status_code}): {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_idor_cannot_link_foreign_inspection(http_client, cc_world):
    """B cannot tie a gate in B's project to A's inspection."""
    a, b = cc_world["a"], cc_world["b"]
    insp = await http_client.post(
        f"{_CC}/inspections",
        json={"project_id": cc_world["p_a"], "inspection_type": "ir", "title": "A private inspection"},
        headers=a["headers"],
    )
    inspection_id = insp.json()["id"]
    resp = await _create_gate(http_client, b["headers"], cc_world["p_b"], inspection_id=inspection_id)
    assert resp.status_code == 404, f"LEAK: B linked A's inspection (status {resp.status_code}): {resp.text!r}"


# ── RBAC ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_create_gate(http_client, cc_world):
    v = cc_world["v"]
    resp = await _create_gate(http_client, v["headers"], cc_world["p_a"])
    assert resp.status_code in (401, 403), f"viewer must not create gates (status {resp.status_code})"


@pytest.mark.asyncio
async def test_editor_can_create_but_not_release(http_client, cc_world):
    """An editor creates a gate in its own project but cannot release it (manager-only)."""
    e = cc_world["e"]
    create = await _create_gate(http_client, e["headers"], cc_world["p_e"])
    assert create.status_code == 201, create.text
    gate_id = create.json()["id"]
    resp = await http_client.post(
        f"{_CC}/gates/{gate_id}/release",
        json={"party_role": "qa", "justification": "editor attempt"},
        headers=e["headers"],
    )
    assert resp.status_code in (401, 403), f"editor must not release gates (status {resp.status_code}): {resp.text}"
