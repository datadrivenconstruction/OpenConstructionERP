# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Review-authority module - integration tests.

Covers the API contract end to end:

    1.  Create a cycle -> status ``draft``.
    2.  Submit -> pinned version frozen, status ``submitted``, clock open.
    3.  Add a remark with a norm reference -> ``has_norm_ref``, cycle moves to
        ``remarks_issued``.
    4.  Add a remark with no norm reference -> ``no_norm_ref_contestable``.
    5.  Respond then decide a remark (open -> responded -> accepted).
    6.  Illegal remark decision from a wrong state -> 400.
    7.  Stale-remark detector: bumping the live document version surfaces every
        remark as stale.
    8.  Repeat radar: a new remark that repeats an accepted one is linked.
    9.  Dossier assembles cycle + remarks + an evidence header.
    10. Cross-project IDOR: user B cannot read A's cycle.
    11. ``/meta`` returns localized labels for the requested locale.

Scaffolding mirrors ``test_credentials_api.py`` - the engine is bound to the
conftest-provisioned PostgreSQL cluster before any test module imports.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.projects import models as _proj_models  # noqa: F401
        from app.modules.review_authority import models as _ra_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _promote_to_editor(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="editor"))
        await s.commit()

    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _register_login(client: AsyncClient, *, tenant: str) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@reviewauthority.io"
    password = f"Rev{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    user_id = reg.json()["id"]
    await _activate_user(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    return user_id, email, password, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_project(owner_user_id: str, name: str) -> str:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        p = Project(id=pid, name=name, description="", owner_id=uuid.UUID(owner_user_id))
        s.add(p)
        await s.commit()
    return str(pid)


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    # Tenant A owns the project under test and has to be able to create in it.
    # Registration cannot be relied on for that: self-registration only hands out
    # admin to the very first account on a fresh install, and every module in this
    # job shares one database, so exactly one of them wins that slot and the rest
    # get a viewer with no <module>.create permission. A was then refused 403 in
    # its own project and the cross-tenant probe below never ran. Promote it the
    # same way B is promoted. Editor, not admin, so A passes verify_project_access
    # on the ownership branch a real tenant would use rather than an admin bypass.
    a_uid, a_email, a_pw, _a_hdr = await _register_login(http_client, tenant="a")
    a_hdr = await _promote_to_editor(http_client, a_email, a_pw)
    b_uid, b_email, b_pw, _b_hdr = await _register_login(http_client, tenant="b")
    b_hdr = await _promote_to_editor(http_client, b_email, b_pw)
    a_project = await _create_project(a_uid, "A's project")
    b_project = await _create_project(b_uid, "B's project")
    return {
        "a": {"uid": a_uid, "headers": a_hdr, "project_id": a_project},
        "b": {"uid": b_uid, "headers": b_hdr, "project_id": b_project},
    }


async def _open_submitted_cycle(client: AsyncClient, tenant: dict) -> str:
    """Create a cycle at version A and submit it, returning the cycle id."""
    create = await client.post(
        "/api/v1/review_authority/cycles/",
        json={
            "project_id": tenant["project_id"],
            "authority_name": "State expertise board",
            "authority_kind": "state_expertise",
            "current_document_version": "A",
            "sla_days": 42,
        },
        headers=tenant["headers"],
    )
    assert create.status_code == 201, create.text
    cid = create.json()["id"]
    submit = await client.post(
        f"/api/v1/review_authority/cycles/{cid}/submit",
        json={},
        headers=tenant["headers"],
    )
    assert submit.status_code == 200, submit.text
    return cid


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_submit_freezes_version(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/review_authority/cycles/",
        json={
            "project_id": a["project_id"],
            "authority_name": "Building control body",
            "authority_kind": "building_control",
            "current_document_version": "Rev1",
        },
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    assert create.json()["status"] == "draft"
    assert create.json()["pinned_document_version"] is None
    cid = create.json()["id"]

    submit = await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/submit",
        json={},
        headers=a["headers"],
    )
    assert submit.status_code == 200, submit.text
    body = submit.json()
    assert body["status"] == "submitted"
    assert body["pinned_document_version"] == "Rev1"
    assert body["days_remaining"] is not None


@pytest.mark.asyncio
async def test_add_remarks_and_auto_classify(http_client, two_tenants):
    a = two_tenants["a"]
    cid = await _open_submitted_cycle(http_client, a)

    grounded = await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "Wall thickness below minimum", "norm_reference": "SP 20 cl.6"},
        headers=a["headers"],
    )
    assert grounded.status_code == 201, grounded.text
    assert grounded.json()["classification"] == "has_norm_ref"
    assert grounded.json()["ordinal"] == 1

    # Adding the first remark advances the cycle FSM.
    cycle = await http_client.get(f"/api/v1/review_authority/cycles/{cid}/", headers=a["headers"])
    assert cycle.json()["status"] == "remarks_issued"

    contestable = await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "Reviewer feels layout is awkward"},
        headers=a["headers"],
    )
    assert contestable.status_code == 201, contestable.text
    assert contestable.json()["classification"] == "no_norm_ref_contestable"
    assert contestable.json()["ordinal"] == 2


@pytest.mark.asyncio
async def test_respond_then_decide_remark(http_client, two_tenants):
    a = two_tenants["a"]
    cid = await _open_submitted_cycle(http_client, a)
    remark = await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "Fire rating not shown", "norm_reference": "Part B"},
        headers=a["headers"],
    )
    rid = remark.json()["id"]

    responded = await http_client.post(
        f"/api/v1/review_authority/remarks/{rid}/respond",
        json={"response_text": "Fire rating added to drawing legend"},
        headers=a["headers"],
    )
    assert responded.status_code == 200, responded.text
    assert responded.json()["status"] == "responded"
    assert responded.json()["responded_at"] is not None

    decided = await http_client.post(
        f"/api/v1/review_authority/remarks/{rid}/decide",
        json={"decision": "accepted", "note": "Reviewer satisfied"},
        headers=a["headers"],
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_illegal_decision_is_rejected(http_client, two_tenants):
    a = two_tenants["a"]
    cid = await _open_submitted_cycle(http_client, a)
    remark = await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "Some open remark"},
        headers=a["headers"],
    )
    rid = remark.json()["id"]
    # Cannot decide (accept) a remark that has not been responded to.
    bad = await http_client.post(
        f"/api/v1/review_authority/remarks/{rid}/decide",
        json={"decision": "accepted"},
        headers=a["headers"],
    )
    assert bad.status_code == 400, bad.text


@pytest.mark.asyncio
async def test_stale_remarks_after_version_bump(http_client, two_tenants):
    a = two_tenants["a"]
    cid = await _open_submitted_cycle(http_client, a)  # pinned = current = "A"
    await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "Detail unclear", "norm_reference": "X"},
        headers=a["headers"],
    )

    # No stale remarks while pinned == current.
    before = await http_client.get(
        f"/api/v1/review_authority/cycles/{cid}/stale-remarks",
        headers=a["headers"],
    )
    assert before.status_code == 200, before.text
    assert before.json() == []

    # Bump the live document version; the pinned version stays "A".
    bump = await http_client.patch(
        f"/api/v1/review_authority/cycles/{cid}/",
        json={"current_document_version": "B"},
        headers=a["headers"],
    )
    assert bump.status_code == 200, bump.text

    after = await http_client.get(
        f"/api/v1/review_authority/cycles/{cid}/stale-remarks",
        headers=a["headers"],
    )
    assert after.status_code == 200, after.text
    assert len(after.json()) == 1
    assert after.json()[0]["is_stale"] is True


@pytest.mark.asyncio
async def test_repeat_radar_links_accepted_repeat(http_client, two_tenants):
    a = two_tenants["a"]
    cid = await _open_submitted_cycle(http_client, a)

    first = await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "Stair core fire rating not specified on drawing", "norm_reference": "Part B"},
        headers=a["headers"],
    )
    first_id = first.json()["id"]
    # Move it to accepted so the radar considers it prior art.
    await http_client.post(
        f"/api/v1/review_authority/remarks/{first_id}/respond",
        json={"response_text": "added"},
        headers=a["headers"],
    )
    await http_client.post(
        f"/api/v1/review_authority/remarks/{first_id}/decide",
        json={"decision": "accepted"},
        headers=a["headers"],
    )

    repeat = await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "Stair core fire rating not specified on drawing set"},
        headers=a["headers"],
    )
    assert repeat.status_code == 201, repeat.text
    assert repeat.json()["repeat_of_id"] == first_id

    radar = await http_client.get(
        f"/api/v1/review_authority/cycles/{cid}/repeat-radar",
        headers=a["headers"],
    )
    assert radar.status_code == 200, radar.text
    assert any(row["repeat_of_id"] == first_id for row in radar.json())


@pytest.mark.asyncio
async def test_dossier_has_evidence_and_remarks(http_client, two_tenants):
    a = two_tenants["a"]
    cid = await _open_submitted_cycle(http_client, a)
    await http_client.post(
        f"/api/v1/review_authority/cycles/{cid}/remarks",
        json={"text": "A remark", "norm_reference": "N"},
        headers=a["headers"],
    )
    dossier = await http_client.get(
        f"/api/v1/review_authority/cycles/{cid}/dossier",
        headers=a["headers"],
    )
    assert dossier.status_code == 200, dossier.text
    body = dossier.json()
    assert "evidence" in body
    assert body["cycle"]["pinned_document_version"] == "A"
    assert body["summary"]["total_remarks"] == 1


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_idor_blocked(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    cid = await _open_submitted_cycle(http_client, a)

    got = await http_client.get(f"/api/v1/review_authority/cycles/{cid}/", headers=b["headers"])
    assert got.status_code in (403, 404), got.text

    listed = await http_client.get(
        "/api/v1/review_authority/cycles/",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert listed.status_code in (403, 404), listed.text


@pytest.mark.asyncio
async def test_meta_localized_labels(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get(
        "/api/v1/review_authority/meta",
        params={"locale": "ru"},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {row["code"]: row["label"] for row in body["authority_kinds"]}
    assert kinds["state_expertise"] == "Государственная экспертиза"
    classes = {row["code"]: row["label"] for row in body["remark_classifications"]}
    assert "no_norm_ref_contestable" in classes
