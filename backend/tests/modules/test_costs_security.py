"""Round-7 security audit tests for the ``costs`` module.

Pins the four trip-wires established by the audit:

1. IDOR — ``GET /v1/costs/vector/v3-status/`` must not leak
   ``language_mismatch`` diagnostics for a project the caller does not
   own. Anonymous/cross-tenant callers still get the engine-status
   payload (the probe is public-by-design for the catalog-readiness
   banner) but the per-project diagnostic block collapses to the
   ``unknown`` sentinel — never the bound catalogue id, region, or
   language of an unrelated tenant.

2. Decimal money — every money/rate/factor field surfaces on the wire
   as a Decimal-coercible string, never as a JSON float. A 199.99 unit
   rate must round-trip unchanged.

3. Upload safety — ``POST /v1/costs/import/file/`` rejects payloads
   whose magic bytes don't match the declared extension. A ``.xlsx``
   that's really a PDF / PE / random binary returns 415, not 400 (and
   definitely not 200 with a parse warning).

4. RBAC — a viewer cannot PATCH a cost item; the existing
   ``RequirePermission("costs.update")`` gate is enforced and returns
   401/403, never 200.

Test isolation follows the pattern in
``backend/tests/integration/test_costs_idor.py``: the per-module temp
SQLite DB redirect MUST run before any ``from app...`` import.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-r7-"))
_TMP_DB = _TMP_DIR / "costs_r7.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
os.environ.setdefault("SEED_SHOWCASE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.costs import models as _costs_models  # noqa: F401
        from app.modules.projects import models as _projects_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _force_role_active(email: str, *, role: str = "admin") -> None:
    """Bypass admin-approve so login works in tests."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register_and_login(
    client: AsyncClient,
    *,
    tag: str,
    role: str = "admin",
) -> tuple[str, str, dict[str, str]]:
    """Register, force role/active, log in. Returns ``(uid, email, headers)``."""
    email = f"r7-{tag}-{uuid.uuid4().hex[:6]}@costs-sec.io"
    password = f"R7Costs{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"R7 {tag}"},
    )
    assert reg.status_code in (200, 201), reg.text
    uid = reg.json()["id"]

    await _force_role_active(email, role=role)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return uid, email, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def owner_auth(http_client):
    """Admin caller — owns the project the IDOR test guards."""
    uid, _email, headers = await _register_and_login(
        http_client,
        tag="owner",
        role="admin",
    )
    return uid, headers


@pytest_asyncio.fixture(scope="module")
async def attacker_auth(http_client):
    """Second admin caller — owns a different project, sees the first one
    via guessed UUID (the IDOR vector)."""
    uid, _email, headers = await _register_and_login(
        http_client,
        tag="attacker",
        role="admin",
    )
    return uid, headers


@pytest_asyncio.fixture(scope="module")
async def viewer_auth(http_client):
    """A non-privileged viewer (no ``costs.update`` permission)."""
    uid, _email, headers = await _register_and_login(
        http_client,
        tag="viewer",
        role="viewer",
    )
    return uid, headers


@pytest_asyncio.fixture(scope="module")
async def owner_project_id(http_client, owner_auth):
    """A real project owned by ``owner_auth``."""
    _uid, headers = owner_auth
    resp = await http_client.post(
        "/api/v1/projects/",
        json={"name": "R7 Costs Owner", "description": "fixture"},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def seeded_cost_item():
    """One cost item with a high-precision rate the response should
    preserve. Inserted directly via the ORM — the HTTP create path is
    exercised by ``test_costs_idor`` already."""
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    item_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            CostItem(
                id=item_id,
                code=f"R7-DEC-{uuid.uuid4().hex[:6]}",
                description="R7 audit — decimal money round-trip",
                unit="m3",
                rate="199.99",
                currency="EUR",
                source="custom",
                classification={},
                components=[],
                tags=[],
                region=None,
                is_active=True,
                metadata_={},
            )
        )
        await s.commit()
    return str(item_id)


# ── Test (a): IDOR ─ vector_v3_status must not leak language_mismatch ──────


@pytest.mark.asyncio
async def test_idor_vector_v3_status_unrelated_project(
    http_client,
    attacker_auth,
    owner_project_id,
):
    """Attacker queries ``/vector/v3-status/?project_id=<owner's>`` —
    response MUST NOT contain the owner's bound catalogue / language.

    Returning 404 would also be acceptable (and is the canonical IDOR
    response across the platform), but the engine-status portion of the
    payload is public-by-design (it gates the catalogue-readiness banner
    on /match-elements). The acceptable contract is: engine status flows
    through, the per-project diagnostic block collapses to the
    ``unknown`` sentinel — i.e. no leakage of bound_catalogue /
    bound_language / project_region.
    """
    _uid, headers = attacker_auth
    resp = await http_client.get(
        f"/api/v1/costs/vector/v3-status/?project_id={owner_project_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    mismatch = body.get("language_mismatch")
    assert mismatch is not None, "language_mismatch block is missing — endpoint contract changed"
    # IDOR: bound_catalogue / bound_language / project_region MUST be
    # empty or sentinel; the attacker has no right to see them.
    assert mismatch.get("status") in {"unknown", None}, (
        f"LEAK: attacker saw status={mismatch.get('status')!r} for unrelated project {owner_project_id}: {mismatch!r}"
    )
    assert not mismatch.get("bound_catalogue"), (
        f"LEAK: bound_catalogue={mismatch.get('bound_catalogue')!r} surfaced for an unrelated project"
    )
    assert not mismatch.get("bound_language"), (
        f"LEAK: bound_language={mismatch.get('bound_language')!r} surfaced for an unrelated project"
    )
    assert not mismatch.get("project_region"), (
        f"LEAK: project_region={mismatch.get('project_region')!r} surfaced for an unrelated project"
    )


@pytest.mark.asyncio
async def test_idor_vector_v3_status_unknown_uuid_does_not_404(
    http_client,
    attacker_auth,
):
    """A guessed-but-nonexistent UUID must also return 200 with sentinel
    diagnostics — confirms we treat 'project missing' and 'access denied'
    identically (no information leak on which UUIDs exist)."""
    _uid, headers = attacker_auth
    bogus = uuid.uuid4()
    resp = await http_client.get(
        f"/api/v1/costs/vector/v3-status/?project_id={bogus}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    mismatch = resp.json().get("language_mismatch", {})
    assert not mismatch.get("project_region"), "leaked project_region for a non-existent project UUID"


# ── Test (b): Decimal money round-trip ─────────────────────────────────────


@pytest.mark.asyncio
async def test_money_is_decimal_string_in_response(
    http_client,
    owner_auth,
    seeded_cost_item,
):
    """``199.99`` must come back as the string ``"199.99"`` — proves
    Pydantic v2 PlainSerializer keeps the value out of JSON's float
    bridge. A raw float round-trip would surface as ``199.99`` or
    ``199.98999999999998`` depending on the runtime."""
    _uid, headers = owner_auth
    resp = await http_client.get(
        f"/api/v1/costs/{seeded_cost_item}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rate = body["rate"]
    assert isinstance(rate, str), f"rate must be a JSON string (Decimal-safe), got {type(rate).__name__}={rate!r}"
    # Exact equality — no float drift.
    assert Decimal(rate) == Decimal("199.99"), f"rate round-trip drifted: input=199.99 output={rate!r}"


@pytest.mark.asyncio
async def test_create_accepts_high_precision_decimal_string(
    http_client,
    owner_auth,
):
    """The create endpoint must accept a Decimal-string body and
    persist it without truncation."""
    _uid, headers = owner_auth
    code = f"R7-CREATE-{uuid.uuid4().hex[:6]}"
    resp = await http_client.post(
        "/api/v1/costs/",
        json={
            "code": code,
            "description": "R7 audit — Decimal create",
            "unit": "m2",
            # Sub-cent precision a float would silently round.
            "rate": "1234.5678",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert isinstance(body["rate"], str), body
    assert Decimal(body["rate"]) == Decimal("1234.5678")


@pytest.mark.asyncio
async def test_regional_adjust_returns_decimal_strings(
    http_client,
    owner_auth,
):
    """``GET /regional-adjust/`` should emit ``base_rate`` /
    ``factor_applied`` / ``adjusted_rate`` as strings — the math is
    Decimal × Decimal end-to-end."""
    _uid, headers = owner_auth
    resp = await http_client.get(
        "/api/v1/costs/regional-adjust/",
        params={
            "region": "TEST_UNKNOWN_REGION",
            "category": "concrete",
            "base_rate": "100.00",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("base_rate", "factor_applied", "adjusted_rate"):
        val = body[key]
        assert isinstance(val, str), f"{key} must be a Decimal string, got {type(val).__name__}={val!r}"
    # No index row exists → factor is 1.0 baseline, adjusted == base.
    assert Decimal(body["adjusted_rate"]) == Decimal(body["base_rate"])
    assert Decimal(body["factor_applied"]) == Decimal("1")


# ── Test (c): Magic-byte upload validation ─────────────────────────────────


@pytest.mark.asyncio
async def test_upload_rejects_wrong_magic_bytes_xlsx(
    http_client,
    owner_auth,
):
    """An ``.xlsx`` whose content is actually a PDF must 415 — not 400,
    not 200 with a swallowed parse error."""
    _uid, headers = owner_auth
    pdf_bytes = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nfake pdf body"
    resp = await http_client.post(
        "/api/v1/costs/import/file/",
        files={
            "file": (
                "evil.xlsx",
                pdf_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
        headers=headers,
    )
    assert resp.status_code == 415, f"expected 415 Unsupported Media Type, got {resp.status_code}: {resp.text!r}"


@pytest.mark.asyncio
async def test_upload_rejects_binary_renamed_to_csv(
    http_client,
    owner_auth,
):
    """A binary (NUL bytes) renamed to ``.csv`` must 415."""
    _uid, headers = owner_auth
    # An ELF-ish blob — definitely not a CSV.
    binary = b"\x7fELF\x00\x00\x00\x00\x01\x02\x03\x04random bytes"
    resp = await http_client.post(
        "/api/v1/costs/import/file/",
        files={
            "file": ("malware.csv", binary, "text/csv"),
        },
        headers=headers,
    )
    assert resp.status_code == 415, f"expected 415, got {resp.status_code}: {resp.text!r}"


@pytest.mark.asyncio
async def test_upload_rejects_oversize_payload(
    http_client,
    owner_auth,
):
    """A payload above the 25 MB cap must 413 — protects the parser
    from being handed an arbitrary-size blob to chew on."""
    _uid, headers = owner_auth
    # 26 MB of zero-padded "data" — past the cap; the magic-byte gate
    # runs after the size gate so this proves the size check fires
    # first.
    payload = b"a,b,c\n" + (b"x" * (26 * 1024 * 1024))
    resp = await http_client.post(
        "/api/v1/costs/import/file/",
        files={"file": ("huge.csv", payload, "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 413, (
        f"expected 413 Request Entity Too Large, got {resp.status_code}: {resp.text[:300]!r}"
    )


@pytest.mark.asyncio
async def test_upload_accepts_valid_csv(http_client, owner_auth):
    """Sanity: a real CSV still flows through — guarantees the gate
    isn't accidentally rejecting legitimate uploads."""
    _uid, headers = owner_auth
    csv_bytes = b"code,description,unit,rate,currency\nR7-CSV-1,R7 csv test row,m2,12.34,EUR\n"
    resp = await http_client.post(
        "/api/v1/costs/import/file/",
        files={"file": ("good.csv", csv_bytes, "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("imported", 0) >= 1, body


# ── Test (d): RBAC ─ viewer cannot PATCH ───────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_denied_patch_rbac(
    http_client,
    viewer_auth,
    seeded_cost_item,
):
    """A viewer (lowest role) must NOT be able to PATCH a cost item.
    The RBAC gate uses ``RequirePermission('costs.update')`` which maps
    to Role.EDITOR — viewer is below that threshold."""
    _uid, headers = viewer_auth
    resp = await http_client.patch(
        f"/api/v1/costs/{seeded_cost_item}",
        json={"description": "viewer-injected"},
        headers=headers,
    )
    assert resp.status_code in (401, 403), (
        f"LEAK: viewer was able to PATCH cost item (status {resp.status_code}): {resp.text!r}"
    )

    # Confirm the row is unchanged.
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        row = await s.get(CostItem, uuid.UUID(seeded_cost_item))
        assert row is not None
        assert row.description != "viewer-injected", "PATCH actually mutated the row despite RBAC denial"
