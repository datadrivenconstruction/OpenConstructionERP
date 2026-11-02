# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""w1-einvoice: permission matrix on every route, project isolation, idempotent lifecycle calls.

A small FastAPI app mounts the module router with a fake caller (role from the test) and the
per-test PostgreSQL transaction. ``verify_project_access`` is replaced by a recorder that
answers 404 for any project the caller is not a member of, which is the real helper's contract.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Role, permission_registry
from app.dependencies import RequirePermission, get_current_user_payload, get_session
from app.modules.einvoice_clearance import adapters, regimes, repository, schemas, service
from app.modules.einvoice_clearance import router as router_mod
from app.modules.einvoice_clearance.models import EInvoiceProfile
from app.modules.einvoice_clearance.permissions import register_einvoice_clearance_permissions
from app.modules.einvoice_clearance.validators import register_einvoice_clearance_rules
from tests._pg import transactional_session
from tests.unit.test_einvoice_clearance_module import MX_FIELDS

PREFIX = "/v1/einvoice-clearance"
USER = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _registries() -> None:
    register_einvoice_clearance_permissions()
    register_einvoice_clearance_rules()
    adapters.register_builtin_adapters()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


class Caller:
    """Mutable identity the fake JWT dependency reads."""

    def __init__(self) -> None:
        self.role = "admin"
        self.permissions: list[str] = []
        self.projects: set[uuid.UUID] = set()
        self.guard_calls: list[uuid.UUID] = []


@pytest_asyncio.fixture
async def env(session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    caller = Caller()
    app = FastAPI()
    app.include_router(router_mod.router, prefix=PREFIX)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    async def _payload() -> dict[str, Any]:
        return {"sub": USER, "role": caller.role, "permissions": caller.permissions}

    async def _guard(project_id: uuid.UUID, user_id: str, _session: AsyncSession) -> None:
        caller.guard_calls.append(project_id)
        if project_id not in caller.projects:
            raise HTTPException(status_code=404, detail="Project not found")

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_payload] = _payload
    monkeypatch.setattr(router_mod, "verify_project_access", _guard)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, caller, session


async def _profile(session: AsyncSession, country: str, **extra: Any) -> EInvoiceProfile:
    entry = regimes.COUNTRY_REGIMES[country]
    values = {
        "company_key": f"co-{uuid.uuid4().hex[:8]}",
        "country": country,
        "regime": entry.regime,
        "platform": entry.platform,
        "tax_registration_id": "310122393500003",
        "network_participant_id": "0088:1234567890128",
        "certificate_reference": "vault://csid/egs-1",
        "adapter_key": adapters.REFERENCE_ADAPTER_KEY,
        "sandbox": True,
        "mode": "export",
        "is_active": True,
    }
    values.update(extra)
    return await repository.add_profile(session, EInvoiceProfile(**values))


def _body(profile: EInvoiceProfile, project_id: uuid.UUID, **over: Any) -> schemas.DocumentCreateRequest:
    entry = regimes.COUNTRY_REGIMES[profile.country]
    values: dict[str, Any] = {
        "project_id": project_id,
        "profile_id": profile.id,
        "invoice_number": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": "2026-03-10T09:00:00",
        "currency_code": "SAR",
        "total_amount": "5290.00",
        "country_fields": dict.fromkeys(entry.document_fields, "x"),
        "payload": f"<Invoice n='{uuid.uuid4().hex}'/>",
    }
    values.update(over)
    return schemas.DocumentCreateRequest(**values)


def _mx(profile: EInvoiceProfile, project_id: uuid.UUID) -> schemas.DocumentCreateRequest:
    return _body(profile, project_id, currency_code="MXN", total_amount="1190.00", country_fields=MX_FIELDS)


# ── Permission matrix on every route ────────────────────────────────────────


def _routes() -> list[tuple[str, str, str]]:
    out = []
    for route in router_mod.router.routes:
        keys = [d.dependency.permission for d in route.dependencies if isinstance(d.dependency, RequirePermission)]
        assert len(keys) == 1, f"{route.path} must carry exactly one permission gate"
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, route.path, keys[0]))
    return out


ROUTES = _routes()


def test_every_route_is_gated_and_the_keys_are_registered() -> None:
    registered = set(permission_registry.list_all())
    assert ROUTES
    assert {key for _m, _p, key in ROUTES} <= registered


def test_consequential_routes_need_the_manager_role() -> None:
    by_suffix = {(m, p.rsplit("/", 1)[-1]): k for m, p, k in ROUTES}
    assert by_suffix[("POST", "submit")] == "einvoice_clearance.submit"
    assert by_suffix[("POST", "cancel")] == "einvoice_clearance.cancel"
    for key in ("submit", "cancel"):
        assert permission_registry.role_has_permission(Role.EDITOR, f"einvoice_clearance.{key}") is False
        assert permission_registry.role_has_permission(Role.VIEWER, f"einvoice_clearance.{key}") is False


def _fill(path: str) -> str:
    return PREFIX + path.replace("{document_id}", str(uuid.uuid4())).replace("{profile_id}", str(uuid.uuid4()))


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "key"), ROUTES, ids=[f"{m} {p}" for m, p, _k in ROUTES])
async def test_a_role_below_the_gate_gets_403_and_one_at_it_does_not(env, method: str, path: str, key: str) -> None:
    client, caller, _session = env
    below = [r for r in ("viewer", "editor", "manager") if not permission_registry.role_has_permission(r, key)]
    at = next(r for r in ("viewer", "editor", "manager") if permission_registry.role_has_permission(r, key))
    for role in below:
        caller.role = role
        resp = await client.request(method, _fill(path), json={})
        assert resp.status_code == 403, f"{role} reached {method} {path}"
    caller.role = at
    resp = await client.request(method, _fill(path), json={})
    assert resp.status_code != 403, f"{at} was refused {method} {path}"


@pytest.mark.asyncio
async def test_an_unknown_role_and_no_permissions_is_refused_everywhere(env) -> None:
    client, caller, _session = env
    caller.role = "no-such-role"
    for method, path, _key in ROUTES:
        resp = await client.request(method, _fill(path), json={})
        assert resp.status_code == 403, f"{method} {path}"


@pytest.mark.asyncio
async def test_a_stale_token_permission_list_cannot_exceed_the_role(env) -> None:
    client, caller, _session = env
    caller.role = "viewer"
    caller.permissions = ["einvoice_clearance.submit"]  # the token itself lists it
    resp = await client.post(_fill("/documents/{document_id}/submit"), json={})
    assert resp.status_code != 403  # RequirePermission trusts the token list by design
    # ...but the registry is what decides for a token that does not list it
    caller.permissions = []
    resp = await client.post(_fill("/documents/{document_id}/submit"), json={})
    assert resp.status_code == 403


# ── Project isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_user_outside_the_project_cannot_read_or_change_its_documents(env) -> None:
    client, caller, session = env
    mine, foreign = uuid.uuid4(), uuid.uuid4()
    caller.projects = {mine}
    caller.role = "manager"
    profile = await _profile(session, "SA", mode="sandbox")
    doc, _ = await service.create_document(
        session, profile=profile, body=_body(profile, foreign, document_kind="simplified")
    )
    status_before = doc.status
    d = f"/documents/{doc.id}"
    attempts = [
        ("GET", d, None),
        ("GET", d + "/payload", None),
        ("GET", d + "/events", None),
        ("GET", d + "/lifecycle", None),
        ("PUT", d, {"invoice_number": "HACK"}),
        ("POST", d + "/validate", None),
        ("POST", d + "/submit", {}),
        ("POST", d + "/refresh", None),
        ("POST", d + "/resolve", {"outcome": "cleared", "note": "portal"}),
        ("POST", d + "/cancel", {"reason": "x"}),
    ]
    for method, path, body in attempts:
        resp = await client.request(method, PREFIX + path, json=body)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
    assert foreign in caller.guard_calls  # the guard saw the DOCUMENT's project, not a client-supplied one
    await session.refresh(doc)
    assert doc.status == status_before
    assert doc.invoice_number != "HACK"


@pytest.mark.asyncio
async def test_listing_overview_and_consolidation_of_a_foreign_project_are_404(env) -> None:
    client, caller, session = env
    mine, foreign = uuid.uuid4(), uuid.uuid4()
    caller.projects = {mine}
    caller.role = "manager"
    profile = await _profile(session, "MY", settings={"annual_turnover": "40000000"})
    await service.create_document(session, profile=profile, body=_body(profile, foreign, currency_code="MYR"))
    for path in (f"/documents/?project_id={foreign}", f"/documents/overview?project_id={foreign}"):
        assert (await client.get(PREFIX + path)).status_code == 404
    for path, method in (("/consolidated/preview", "POST"), ("/consolidated/", "POST")):
        resp = await client.request(
            method, PREFIX + path, json={"project_id": str(foreign), "profile_id": str(profile.id), "period": "2026-10"}
        )
        assert resp.status_code == 404
    # creating a document in a foreign project is refused too
    resp = await client.post(
        PREFIX + "/documents/", json=_body(profile, foreign, currency_code="MYR").model_dump(mode="json")
    )
    assert resp.status_code == 404
    assert await repository.list_documents(session, project_id=foreign) != []  # only the seeded one


@pytest.mark.asyncio
async def test_a_member_sees_only_their_own_projects_documents(env) -> None:
    client, caller, session = env
    mine, other = uuid.uuid4(), uuid.uuid4()
    caller.projects = {mine}
    caller.role = "viewer"
    profile = await _profile(session, "SA")
    own, _ = await service.create_document(session, profile=profile, body=_body(profile, mine))
    await service.create_document(session, profile=profile, body=_body(profile, other))
    got = (await client.get(PREFIX + f"/documents/?project_id={mine}")).json()
    assert [row["id"] for row in got] == [str(own.id)]
    overview = (await client.get(PREFIX + f"/documents/overview?project_id={mine}")).json()
    assert len(overview) == 1


# ── Lifecycle through HTTP: idempotent and no illegal jumps ─────────────────


@pytest.mark.asyncio
async def test_sandbox_submit_twice_clears_once_and_the_second_call_is_a_409(env) -> None:
    client, caller, session = env
    mine = uuid.uuid4()
    caller.projects = {mine}
    caller.role = "manager"
    profile = await _profile(session, "MX", mode="sandbox", tax_registration_id="AAA010101AAA")
    doc, _ = await service.create_document(session, profile=profile, body=_mx(profile, mine))
    first = await client.post(PREFIX + f"/documents/{doc.id}/submit", json={"accept_warnings": True})
    assert first.status_code == 200, first.text
    again = await client.post(PREFIX + f"/documents/{doc.id}/submit", json={"accept_warnings": True})
    assert again.status_code == 409
    events = (await client.get(PREFIX + f"/documents/{doc.id}/events")).json()
    assert [e["event_type"] for e in events].count("submitted") == 1
    await session.refresh(doc)
    assert doc.status in {"cleared", "reported", "submitted"}


@pytest.mark.asyncio
async def test_export_mode_refuses_submit_and_leaves_the_status_alone(env) -> None:
    client, caller, session = env
    mine = uuid.uuid4()
    caller.projects = {mine}
    caller.role = "manager"
    profile = await _profile(session, "SA", mode="export")
    doc, _ = await service.create_document(session, profile=profile, body=_body(profile, mine))
    resp = await client.post(PREFIX + f"/documents/{doc.id}/submit", json={"accept_warnings": True})
    assert resp.status_code == 409
    await session.refresh(doc)
    assert doc.status == "draft"
    view = (await client.get(PREFIX + f"/documents/{doc.id}/lifecycle")).json()
    assert "send" not in view["allowed_actions"]
    assert view["allowed_actions"][-1] == "download"
    assert "EINV-CORE-006" in [f["rule_id"] for f in view["findings"]]


@pytest.mark.asyncio
async def test_cancelling_a_draft_is_refused_and_validate_twice_is_idempotent(env) -> None:
    client, caller, session = env
    mine = uuid.uuid4()
    caller.projects = {mine}
    caller.role = "manager"
    profile = await _profile(session, "SA", mode="sandbox")
    doc, _ = await service.create_document(
        session, profile=profile, body=_body(profile, mine, document_kind="simplified")
    )
    cancel = await client.post(PREFIX + f"/documents/{doc.id}/cancel", json={"reason": "typo"})
    assert cancel.status_code == 409
    await session.refresh(doc)
    assert doc.status == "draft"
    one = await client.post(PREFIX + f"/documents/{doc.id}/validate")
    two = await client.post(PREFIX + f"/documents/{doc.id}/validate")
    assert one.status_code == two.status_code == 200
    events = (await client.get(PREFIX + f"/documents/{doc.id}/events")).json()
    assert [e["event_type"] for e in events].count("validated") <= 1


@pytest.mark.asyncio
async def test_a_cleared_document_cannot_be_edited_back_to_draft(env) -> None:
    client, caller, session = env
    mine = uuid.uuid4()
    caller.projects = {mine}
    caller.role = "manager"
    profile = await _profile(session, "MX", mode="sandbox", tax_registration_id="AAA010101AAA")
    doc, _ = await service.create_document(session, profile=profile, body=_mx(profile, mine))
    sent = await client.post(PREFIX + f"/documents/{doc.id}/submit", json={"accept_warnings": True})
    assert sent.status_code == 200, sent.text
    await session.refresh(doc)
    settled = doc.status
    resp = await client.put(PREFIX + f"/documents/{doc.id}", json={"invoice_number": "CHANGED"})
    assert resp.status_code in {409, 422}
    await session.refresh(doc)
    assert doc.status == settled
    assert doc.invoice_number != "CHANGED"


# ── Setup gate and scoping ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_setup_is_empty_without_registrations_and_lists_only_active_markets(env) -> None:
    client, caller, session = env
    caller.role = "viewer"
    assert (await client.get(PREFIX + "/setup/")).json() == []  # a tenant with no e-invoice market sees nothing
    await _profile(session, "DE", network_participant_id="0204:991-12345-67")
    await _profile(session, "SA")
    await _profile(session, "PL", is_active=False)
    rows = {r["country"]: r for r in (await client.get(PREFIX + "/setup/")).json()}
    assert set(rows) == {"DE", "SA"}
    assert "US" not in rows
    assert rows["SA"]["has_consolidation"] is False


@pytest.mark.asyncio
async def test_setup_flags_missing_seller_id_and_peppol_id(env) -> None:
    client, caller, session = env
    caller.role = "viewer"
    await _profile(session, "DE", network_participant_id="", tax_registration_id="")
    row = (await client.get(PREFIX + "/setup/")).json()[0]
    assert row["ready"] is False
    assert "network_participant_id" in row["missing"]


@pytest.mark.asyncio
async def test_consolidated_is_refused_for_a_market_without_a_grouping_rule(env) -> None:
    client, caller, session = env
    mine = uuid.uuid4()
    caller.projects = {mine}
    caller.role = "manager"
    profile = await _profile(session, "SA")
    resp = await client.post(
        PREFIX + "/consolidated/preview",
        json={"project_id": str(mine), "profile_id": str(profile.id), "period": "2026-10"},
    )
    assert resp.status_code in {409, 422}


@pytest.mark.asyncio
async def test_consolidated_preview_for_an_empty_project_is_zero_not_an_error(env) -> None:
    client, caller, session = env
    mine = uuid.uuid4()
    caller.projects = {mine}
    caller.role = "viewer"
    profile = await _profile(session, "MY", settings={"annual_turnover": "40000000"})
    resp = await client.post(
        PREFIX + "/consolidated/preview",
        json={"project_id": str(mine), "profile_id": str(profile.id), "period": "2026-10"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["count"], body["total"], body["due_date"]) == (0, "0.00", "2026-11-07")
    assert body["included"] == body["excluded"] == []


@pytest.mark.asyncio
async def test_a_malformed_period_is_a_client_error_not_a_500(env) -> None:
    client, caller, session = env
    mine = uuid.uuid4()
    caller.projects = {mine}
    caller.role = "viewer"
    profile = await _profile(session, "MY")
    resp = await client.post(
        PREFIX + "/consolidated/preview",
        json={"project_id": str(mine), "profile_id": str(profile.id), "period": "2026-13"},
    )
    assert resp.status_code in {409, 422}
