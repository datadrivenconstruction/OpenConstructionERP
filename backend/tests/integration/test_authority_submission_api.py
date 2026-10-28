# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Authority-submission factory - integration tests.

Covers the API contract end to end:

    1. Built-in profiles are seeded and readable; a single profile reads back.
    2. Create a submission (opens draft).
    3. Validate an incomplete payload -> errors, stays draft.
    4. Validate a complete payload -> passed, advances to validated.
    5. Generate deterministic XML; the same call twice is byte-identical.
    6. Render returns a human-readable view of the same payload.
    7. Submit a validated submission -> submitted, submitted_at set.
    8. Cannot submit a draft / unvalidated submission.
    9. Editing the payload resets a validated submission to draft.
   10. Cross-project IDOR: user B cannot read/list A's submissions.
   11. /meta returns localized labels.

Scaffolding mirrors ``test_credentials_api.py`` - the engine is bound to the
conftest-provisioned PostgreSQL cluster before any test module imports.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_BASE = "/api/v1/authority-submission"


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.authority_submission import models as _as_models  # noqa: F401
        from app.modules.projects import models as _proj_models  # noqa: F401

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


async def _promote_to_manager(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="manager"))
        await s.commit()

    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _register_login(client: AsyncClient, *, tenant: str) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@authsub.io"
    password = f"Auth{uuid.uuid4().hex[:6]}9"
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
    a_uid, a_email, a_pw, _a_hdr = await _register_login(http_client, tenant="a")
    a_hdr = await _promote_to_manager(http_client, a_email, a_pw)
    b_uid, b_email, b_pw, _b_hdr = await _register_login(http_client, tenant="b")
    b_hdr = await _promote_to_manager(http_client, b_email, b_pw)
    a_project = await _create_project(a_uid, "A's project")
    b_project = await _create_project(b_uid, "B's project")
    return {
        "a": {"uid": a_uid, "headers": a_hdr, "project_id": a_project},
        "b": {"uid": b_uid, "headers": b_hdr, "project_id": b_project},
    }


async def _gaeb_profile_id(client: AsyncClient, headers: dict[str, str]) -> str:
    r = await client.get(f"{_BASE}/profiles", params={"format_key": "gaeb_x83"}, headers=headers)
    assert r.status_code == 200, r.text
    profiles = r.json()
    assert profiles, "expected the built-in gaeb_x83 profile to be seeded"
    return profiles[0]["id"]


def _complete_payload() -> dict:
    return {
        "project_name": "Bridge 7",
        "currency": "EUR",
        "positions": [
            {"ordinal": "01.01", "description": "Concrete", "unit": "m3", "quantity": 12.5, "unit_rate": 120},
        ],
        "total": 1500,
    }


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profiles_seeded_and_readable(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get(f"{_BASE}/profiles", headers=a["headers"])
    assert r.status_code == 200, r.text
    profiles = r.json()
    keys = {p["format_key"] for p in profiles}
    assert {"generic_xml", "gaeb_x83", "cobie"} <= keys
    # Built-ins were jurisdiction-neutral to a one when this was written, and
    # are not any more: a German Bauantrag profile now ships as a built-in and
    # names its jurisdiction so the frontend can filter by country. So the
    # invariant is per profile rather than blanket - the formats that are
    # neutral by definition stay neutral, and a built-in that does name a
    # jurisdiction names a country code rather than free text.
    builtins = {p["format_key"]: p for p in profiles if p["is_builtin"]}
    for neutral in ("generic_xml", "gaeb_x83", "cobie", "doc_package_xml"):
        assert builtins[neutral]["jurisdiction"] is None, f"{neutral} is a jurisdiction-neutral format"
    tagged = {k: p["jurisdiction"] for k, p in builtins.items() if p["jurisdiction"] is not None}
    assert all(len(v) == 2 and v.isupper() for v in tagged.values()), tagged

    one = await http_client.get(f"{_BASE}/profiles/{profiles[0]['id']}/", headers=a["headers"])
    assert one.status_code == 200, one.text
    assert one.json()["field_spec"]


@pytest.mark.asyncio
async def test_create_and_validate_lifecycle(http_client, two_tenants):
    a = two_tenants["a"]
    profile_id = await _gaeb_profile_id(http_client, a["headers"])

    # Create with an incomplete payload -> draft.
    created = await http_client.post(
        f"{_BASE}/submissions/",
        json={
            "project_id": a["project_id"],
            "profile_id": profile_id,
            "title": "Tender 7",
            "payload": {"project_name": "Bridge 7"},  # missing currency + positions
        },
        headers=a["headers"],
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["status"] == "draft"

    # Validate incomplete -> errors, stays draft.
    bad = await http_client.post(f"{_BASE}/submissions/{sid}/validate", headers=a["headers"])
    assert bad.status_code == 200, bad.text
    assert bad.json()["status"] == "errors"
    assert "currency" in bad.json()["missing_required"]

    got = await http_client.get(f"{_BASE}/submissions/{sid}/", headers=a["headers"])
    assert got.json()["status"] == "draft"

    # Fill it in, validate -> passed, advances to validated.
    patched = await http_client.patch(
        f"{_BASE}/submissions/{sid}/",
        json={"payload": _complete_payload()},
        headers=a["headers"],
    )
    assert patched.status_code == 200, patched.text
    good = await http_client.post(f"{_BASE}/submissions/{sid}/validate", headers=a["headers"])
    assert good.status_code == 200, good.text
    assert good.json()["status"] == "passed"
    got2 = await http_client.get(f"{_BASE}/submissions/{sid}/", headers=a["headers"])
    assert got2.json()["status"] == "validated"


@pytest.mark.asyncio
async def test_generate_xml_deterministic_and_render(http_client, two_tenants):
    a = two_tenants["a"]
    profile_id = await _gaeb_profile_id(http_client, a["headers"])
    created = await http_client.post(
        f"{_BASE}/submissions/",
        json={
            "project_id": a["project_id"],
            "profile_id": profile_id,
            "title": "Tender XML",
            "payload": _complete_payload(),
        },
        headers=a["headers"],
    )
    sid = created.json()["id"]

    x1 = await http_client.post(f"{_BASE}/submissions/{sid}/generate-xml", headers=a["headers"])
    assert x1.status_code == 200, x1.text
    xml = x1.json()["xml"]
    assert "<TenderExchange" in xml
    assert "<ProjectName>Bridge 7</ProjectName>" in xml

    x2 = await http_client.post(f"{_BASE}/submissions/{sid}/generate-xml", headers=a["headers"])
    assert x2.json()["xml"] == xml  # deterministic

    rendered = await http_client.get(f"{_BASE}/submissions/{sid}/render", headers=a["headers"])
    assert rendered.status_code == 200, rendered.text
    assert rendered.json()["title"] == "Tender XML"
    assert "Bridge 7" in rendered.json()["text"]


@pytest.mark.asyncio
async def test_submit_requires_clean_validation(http_client, two_tenants):
    a = two_tenants["a"]
    profile_id = await _gaeb_profile_id(http_client, a["headers"])
    created = await http_client.post(
        f"{_BASE}/submissions/",
        json={
            "project_id": a["project_id"],
            "profile_id": profile_id,
            "title": "To submit",
            "payload": _complete_payload(),
        },
        headers=a["headers"],
    )
    sid = created.json()["id"]

    # Cannot submit before validating.
    early = await http_client.post(f"{_BASE}/submissions/{sid}/submit", headers=a["headers"])
    assert early.status_code == 400, early.text

    # Validate then submit.
    await http_client.post(f"{_BASE}/submissions/{sid}/validate", headers=a["headers"])
    submitted = await http_client.post(f"{_BASE}/submissions/{sid}/submit", headers=a["headers"])
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["submitted_at"] is not None


@pytest.mark.asyncio
async def test_editing_payload_resets_to_draft(http_client, two_tenants):
    a = two_tenants["a"]
    profile_id = await _gaeb_profile_id(http_client, a["headers"])
    created = await http_client.post(
        f"{_BASE}/submissions/",
        json={
            "project_id": a["project_id"],
            "profile_id": profile_id,
            "title": "Editable",
            "payload": _complete_payload(),
        },
        headers=a["headers"],
    )
    sid = created.json()["id"]
    await http_client.post(f"{_BASE}/submissions/{sid}/validate", headers=a["headers"])
    await http_client.post(f"{_BASE}/submissions/{sid}/generate-xml", headers=a["headers"])

    new_payload = _complete_payload()
    new_payload["project_name"] = "Bridge 8"
    patched = await http_client.patch(
        f"{_BASE}/submissions/{sid}/",
        json={"payload": new_payload},
        headers=a["headers"],
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["status"] == "draft"
    assert body["generated_xml"] is None
    assert body["validation_report"] is None


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_idor_blocked(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    profile_id = await _gaeb_profile_id(http_client, a["headers"])
    created = await http_client.post(
        f"{_BASE}/submissions/",
        json={
            "project_id": a["project_id"],
            "profile_id": profile_id,
            "title": "Private",
            "payload": _complete_payload(),
        },
        headers=a["headers"],
    )
    sid = created.json()["id"]

    got = await http_client.get(f"{_BASE}/submissions/{sid}/", headers=b["headers"])
    assert got.status_code in (403, 404), got.text

    listed = await http_client.get(
        f"{_BASE}/submissions/",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert listed.status_code in (403, 404), listed.text


@pytest.mark.asyncio
async def test_meta_localized_labels(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get(f"{_BASE}/meta", params={"locale": "ru"}, headers=a["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    statuses = {row["code"]: row["label"] for row in body["statuses"]}
    assert statuses["submitted"] == "Подан"
    formats = {row["code"]: row["label"] for row in body["format_keys"]}
    assert "gaeb_x83" in formats
