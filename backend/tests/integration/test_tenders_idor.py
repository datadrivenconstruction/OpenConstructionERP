# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tenders API: the moved route groups, their old adapters, and tenant isolation.

The main contract tender and RFQ handlers answer under the canonical tenders
API (``/api/v1/bid-management/tenders/main-contract/`` and ``.../rfq/``) and
still under their old prefixes, which now carry Deprecation, Sunset and a
successor Link. A path id may be the canonical package id or the old one.

Tenant B is an editor with every role permission it needs, just not tenant A's
project: every read and write on A's tenders, by old or canonical id and under
old or canonical path, must answer 403 or 404 and leak nothing.

Runs against the PostgreSQL cluster provisioned by ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

TENDERS = "/api/v1/bid-management/tenders"
MAIN = f"{TENDERS}/main-contract"
RFQ = f"{TENDERS}/rfq"
SECRET = "Confidential drywall package"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bid_management import models as _bm  # noqa: F401
        from app.modules.rfq_bidding import models as _rfq  # noqa: F401
        from app.modules.tendering import models as _tm  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _user(client: AsyncClient, tenant: str, role: str) -> dict[str, str]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@tenders-idor.io"
    password = f"TendersIdor{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text
    await _set_role(email, role)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _resolve(client: AsyncClient, headers: dict[str, str], table: str, source_id: str) -> str:
    resp = await client.get(
        f"{TENDERS}/resolve/", params={"source_table": table, "source_id": source_id}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["package_id"]


@pytest_asyncio.fixture(scope="module")
async def tenders(http_client):
    """A owns a project with a main contract tender and an RFQ, both created on canonical paths."""
    a = await _user(http_client, "a", "admin")
    b = await _user(http_client, "b", "editor")
    proj = await http_client.post(
        "/api/v1/projects/", json={"name": f"Tenders-A {uuid.uuid4().hex[:6]}", "currency": "EUR"}, headers=a
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    pkg = await http_client.post(
        f"{MAIN}/packages/", json={"project_id": project_id, "name": SECRET, "description": "A only"}, headers=a
    )
    assert pkg.status_code == 201, pkg.text
    assert "Deprecation" not in pkg.headers
    rfq = await http_client.post(
        f"{RFQ}/", json={"project_id": project_id, "title": "Confidential ready-mix", "currency_code": "EUR"}, headers=a
    )
    assert rfq.status_code == 201, rfq.text
    package_id, rfq_id = pkg.json()["id"], rfq.json()["id"]
    return {
        "a": a,
        "b": b,
        "project_id": project_id,
        "package_id": package_id,
        "package_canonical": await _resolve(http_client, a, "oe_tendering_package", package_id),
        "rfq_id": rfq_id,
        "rfq_canonical": await _resolve(http_client, a, "oe_rfq_rfq", rfq_id),
    }


# ── Moved route groups ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_owner_reads_a_package_under_the_canonical_path_by_either_id(http_client, tenders):
    a = tenders["a"]
    for pid in (tenders["package_id"], tenders["package_canonical"]):
        resp = await http_client.get(f"{MAIN}/packages/{pid}", headers=a)
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == tenders["package_id"]
        assert "Deprecation" not in resp.headers and "Sunset" not in resp.headers


@pytest.mark.asyncio
async def test_the_owner_reads_and_edits_an_rfq_under_the_canonical_path(http_client, tenders):
    a = tenders["a"]
    resp = await http_client.get(f"{RFQ}/{tenders['rfq_canonical']}", headers=a)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == tenders["rfq_id"]
    listed = await http_client.get(f"{RFQ}/", params={"project_id": tenders["project_id"]}, headers=a)
    assert listed.status_code == 200, listed.text
    patched = await http_client.patch(f"{RFQ}/{tenders['rfq_id']}", json={"title": "Ready-mix C30/37"}, headers=a)
    assert patched.status_code == 200, patched.text
    card = await http_client.get(f"{TENDERS}/{tenders['rfq_canonical']}", headers=a)
    assert card.status_code == 200, card.text
    assert card.json()["package"]["title"] == "Ready-mix C30/37"  # the write reached the one model


@pytest.mark.asyncio
async def test_the_old_paths_still_answer_and_name_their_successor(http_client, tenders):
    a = tenders["a"]
    old = await http_client.get(f"/api/v1/tendering/packages/{tenders['package_id']}", headers=a)
    assert old.status_code == 200, old.text
    assert old.headers["Deprecation"].startswith("@")
    assert old.headers["Sunset"]
    assert old.headers["Link"] == f'<{MAIN}/packages/{tenders["package_id"]}>; rel="successor-version"'
    old_rfq = await http_client.get(f"/api/v1/rfq-bidding/{tenders['rfq_id']}", headers=a)
    assert old_rfq.status_code == 200, old_rfq.text
    assert old_rfq.headers["Link"] == f'<{RFQ}/{tenders["rfq_id"]}>; rel="successor-version"'


@pytest.mark.asyncio
async def test_the_tenders_list_shows_both_copies(http_client, tenders):
    resp = await http_client.get(f"{TENDERS}/", params={"project_id": tenders["project_id"]}, headers=tenders["a"])
    assert resp.status_code == 200, resp.text
    sources = {row["source"]: row["id"] for row in resp.json()}
    assert sources == {"tendering": tenders["package_canonical"], "rfq_bidding": tenders["rfq_canonical"]}


@pytest.mark.asyncio
async def test_the_bidder_portal_keeps_its_old_address_only(http_client, tenders):
    resp = await http_client.get(f"{MAIN}/bid-portal/not-a-token/")
    assert resp.status_code in (404, 405, 422)
    assert "Deprecation" not in resp.headers


@pytest.mark.asyncio
async def test_validation_runs_on_a_copied_tender(http_client, tenders):
    resp = await http_client.get(f"{TENDERS}/{tenders['package_canonical']}/validation", headers=tenders["a"])
    assert resp.status_code == 200, resp.text
    ids = {r["rule_id"] for r in resp.json()["results"]}
    assert any(i.startswith("tender.") for i in ids), ids


# ── Authentication ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_canonical_routes_refuse_anonymous_callers(http_client, tenders):
    for path in (
        f"{TENDERS}/?project_id={tenders['project_id']}",
        f"{TENDERS}/{tenders['package_canonical']}",
        f"{MAIN}/packages/{tenders['package_canonical']}",
        f"{RFQ}/{tenders['rfq_canonical']}",
    ):
        resp = await http_client.get(path)
        assert resp.status_code in (401, 403), f"{path}: {resp.status_code}"


# ── Cross-tenant ───────────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_read_tenant_a_tenders(http_client, tenders):
    b = tenders["b"]
    paths = [
        f"{TENDERS}/?project_id={tenders['project_id']}",
        f"{TENDERS}/{tenders['package_canonical']}",
        f"{TENDERS}/{tenders['rfq_canonical']}",
        f"{TENDERS}/{tenders['package_canonical']}/validation",
        f"{TENDERS}/resolve/?source_table=oe_tendering_package&source_id={tenders['package_id']}",
        f"{TENDERS}/export/?project_id={tenders['project_id']}&source=tendering",
        f"{MAIN}/packages/?project_id={tenders['project_id']}",
        f"{RFQ}/?project_id={tenders['project_id']}",
    ]
    for pid in (tenders["package_id"], tenders["package_canonical"]):
        paths += [f"{MAIN}/packages/{pid}", f"{MAIN}/packages/{pid}/bids/", f"{MAIN}/packages/{pid}/clarifications/"]
        paths.append(f"/api/v1/tendering/packages/{pid}")
    for rid in (tenders["rfq_id"], tenders["rfq_canonical"]):
        paths += [f"{RFQ}/{rid}", f"/api/v1/rfq-bidding/{rid}"]
    for path in paths:
        resp = await http_client.get(path, headers=b)
        listing = path.endswith(f"project_id={tenders['project_id']}")
        if resp.status_code == 200 and listing:
            body = resp.json()
            rows = body.get("items", body) if isinstance(body, dict) else body
            assert not rows, f"LEAK: B listed A's tenders at {path}"
            continue
        assert resp.status_code in (403, 404), f"LEAK: B read {path}: {resp.status_code} {resp.text[:200]!r}"
        assert SECRET not in resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_change_tenant_a_tenders(http_client, tenders):
    b = tenders["b"]
    for pid in (tenders["package_id"], tenders["package_canonical"]):
        resp = await http_client.patch(f"{MAIN}/packages/{pid}", json={"name": "Hijacked"}, headers=b)
        assert resp.status_code in (403, 404), f"LEAK: B patched package {pid}: {resp.status_code}"
        resp = await http_client.post(
            f"{MAIN}/packages/{pid}/bids/", json={"company_name": "Intruder", "total_amount": "1"}, headers=b
        )
        assert resp.status_code in (403, 404, 422), f"LEAK: B added a bid to {pid}: {resp.status_code}"
        assert resp.status_code != 201
    for rid in (tenders["rfq_id"], tenders["rfq_canonical"]):
        resp = await http_client.patch(f"{RFQ}/{rid}", json={"title": "Hijacked"}, headers=b)
        assert resp.status_code in (403, 404), f"LEAK: B patched RFQ {rid}: {resp.status_code}"
    resp = await http_client.post(
        f"{MAIN}/packages/", json={"project_id": tenders["project_id"], "name": "Planted"}, headers=b
    )
    assert resp.status_code in (403, 404), f"LEAK: B created a package in A's project: {resp.status_code}"

    card = await http_client.get(f"{TENDERS}/{tenders['package_canonical']}", headers=tenders["a"])
    assert card.status_code == 200
    assert card.json()["package"]["title"] == SECRET
    assert not [s for s in card.json()["submissions"] if "Intruder" in str(s)]
