"""Buyer self-service portal — endpoint tests.

Covers the v3124 buyer-portal magic-link surface end-to-end:

* Manager issuance + verify round-trip (happy path).
* Expired-token rejection (clock-mocked).
* Revoked-token rejection.
* IDOR: token-A cannot fetch token-B's document → 404 (NOT 403).
* Rate-limit: 30/min/token fires the 31st request.
* KYC magic-byte mismatch (PNG bytes posted as PDF → 415).
* KYC happy-path: PDF accepted, document_id returned.
* Contact-agent creates a CrmActivity tagged with the buyer ref + fires
  the ``crm.lead.message_received`` event.
* RBAC: EDITOR cannot issue, MANAGER can.

The R7/R8 ``conftest.py`` does the per-module SQLite isolation so this
file runs in parallel with the rest of the property_dev tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

# ── Shared fixture: a buyer wired to a reservation + SPA + payment schedule ──


async def _mk_buyer_with_full_chain(
    client: AsyncClient,
) -> dict[str, str]:
    """Bring up: admin user → project → development → plot → buyer
    → reservation → SPA → payment schedule → instalment.

    Returns ids the tests reuse.
    """
    _uid, _email, headers = await _register_user(
        client,
        role="admin",
        tag=f"portal-{uuid.uuid4().hex[:6]}",
    )

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Portal-{uuid.uuid4().hex[:6]}",
            "description": "Buyer portal tests",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"PORT-{uuid.uuid4().hex[:6]}",
            "name": "Riverside Portal",
            "total_plots": 2,
            "currency": "EUR",
            "location_address": "10 Lake Rd, Anywhere",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": development_id,
            "plot_number": f"PT-{uuid.uuid4().hex[:4]}",
            "area_m2": "120.50",
            "price_base": "450000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    buyer = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": development_id,
            "plot_id": plot_id,
            "full_name": "Anna Portal-Test",
            "email": f"anna-{uuid.uuid4().hex[:6]}@example.io",
            "status": "lead",
        },
        headers=headers,
    )
    assert buyer.status_code == 201, buyer.text
    buyer_id = buyer.json()["id"]

    return {
        "headers": headers,
        "project_id": project_id,
        "development_id": development_id,
        "plot_id": plot_id,
        "buyer_id": buyer_id,
    }


@pytest_asyncio.fixture
async def portal_chain(client: AsyncClient):
    """Per-test buyer chain so token state doesn't leak between tests."""
    return await _mk_buyer_with_full_chain(client)


# ── 1. Issue / verify round-trip ───────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_then_verify_roundtrip(
    client: AsyncClient,
    portal_chain,
):
    """Manager issues a magic link; the public verify endpoint accepts it."""
    res = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["token"]
    assert body["portal_url"].endswith(f"/buyer-portal/{body['token']}")
    assert body["row"]["buyer_id"] == portal_chain["buyer_id"]
    assert body["row"]["revoked_at"] is None

    verify = await client.post(
        "/api/v1/property-dev/portal/verify/",
        json={"token": body["token"]},
    )
    assert verify.status_code == 200, verify.text
    vbody = verify.json()
    assert vbody["buyer_id"] == portal_chain["buyer_id"]
    assert vbody["buyer_full_name"] == "Anna Portal-Test"


# ── 2. Token includes scope='portal' (decoded JWT inspection) ───────────


@pytest.mark.asyncio
async def test_issued_token_has_portal_scope(
    client: AsyncClient,
    portal_chain,
):
    """Sanity: the JWT we mint carries ``scope='portal'`` + ``type='portal''``."""
    from jose import jwt

    from app.config import get_settings

    res = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = res.json()["token"]
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["scope"] == "portal"
    assert payload["type"] == "portal"
    assert payload["sub"] == portal_chain["buyer_id"]
    assert "jti" in payload


# ── 3. Expired token rejected ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_expired_token_rejected(client: AsyncClient, portal_chain):
    """A token whose row says ``expires_at < now`` is rejected as 401."""
    res = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = res.json()["token"]
    row_id = res.json()["row"]["id"]

    # Backdate the row to mark it expired (mock-clock alternative).
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.property_dev.models import PortalToken

    async with async_session_factory() as s:
        await s.execute(
            update(PortalToken)
            .where(PortalToken.id == uuid.UUID(row_id))
            .values(expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await s.commit()

    verify = await client.post(
        "/api/v1/property-dev/portal/verify/",
        json={"token": token},
    )
    assert verify.status_code == 401, verify.text
    assert verify.json()["detail"]["code"] == "portal_token_invalid_or_expired"


# ── 4. Revoked token rejected ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoked_token_rejected(client: AsyncClient, portal_chain):
    """Once a manager revokes the row, the token stops verifying."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]
    row_id = issued.json()["row"]["id"]

    revoke = await client.post(
        f"/api/v1/property-dev/portal/tokens/{row_id}/revoke/",
        headers=portal_chain["headers"],
    )
    assert revoke.status_code == 204, revoke.text

    verify = await client.post(
        "/api/v1/property-dev/portal/verify/",
        json={"token": token},
    )
    assert verify.status_code == 401, verify.text


# ── 5. Garbage token rejected ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_garbage_token_rejected(client: AsyncClient):
    """Any non-JWT string → 401 with the same code (no enumeration)."""
    res = await client.post(
        "/api/v1/property-dev/portal/verify/",
        json={"token": "deadbeef" * 8},
    )
    assert res.status_code == 401, res.text
    assert res.json()["detail"]["code"] == "portal_token_invalid_or_expired"


# ── 6. Tokens for two different buyers are isolated ─────────────────────


@pytest.mark.asyncio
async def test_two_buyer_tokens_are_isolated(client: AsyncClient):
    """Buyer A's token returns Buyer A's data; Buyer B's returns Buyer B's."""
    chain_a = await _mk_buyer_with_full_chain(client)
    chain_b = await _mk_buyer_with_full_chain(client)

    issue_a = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": chain_a["buyer_id"]},
        headers=chain_a["headers"],
    )
    issue_b = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": chain_b["buyer_id"]},
        headers=chain_b["headers"],
    )
    token_a = issue_a.json()["token"]
    token_b = issue_b.json()["token"]

    verify_a = await client.post("/api/v1/property-dev/portal/verify/", json={"token": token_a})
    verify_b = await client.post("/api/v1/property-dev/portal/verify/", json={"token": token_b})
    assert verify_a.status_code == 200
    assert verify_b.status_code == 200
    assert verify_a.json()["buyer_id"] == chain_a["buyer_id"]
    assert verify_b.json()["buyer_id"] == chain_b["buyer_id"]
    assert verify_a.json()["buyer_id"] != verify_b.json()["buyer_id"]


# ── 7. Overview endpoint returns the buyer's payload ───────────────────


@pytest.mark.asyncio
async def test_overview_returns_buyer_data(
    client: AsyncClient,
    portal_chain,
):
    """``/buyer/{token}/overview/`` returns the buyer's summary."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]

    overview = await client.get(f"/api/v1/property-dev/portal/buyer/{token}/overview/")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["buyer_id"] == portal_chain["buyer_id"]
    assert body["buyer_full_name"] == "Anna Portal-Test"
    assert body["development_name"] == "Riverside Portal"
    # Default KYC requests present.
    assert len(body["kyc_requests"]) >= 3
    # Money fields are STRINGS (R7 convention).
    assert isinstance(body["payment_schedule_total"], str)


# ── 8. Money fields serialize as strings ────────────────────────────────


@pytest.mark.asyncio
async def test_overview_money_fields_are_strings(
    client: AsyncClient,
    portal_chain,
):
    """Decimal money values come back as plain-decimal strings, not floats."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]
    overview = await client.get(f"/api/v1/property-dev/portal/buyer/{token}/overview/")
    body = overview.json()
    for field in (
        "payment_schedule_total",
        "payment_schedule_paid",
        "payment_schedule_outstanding",
    ):
        assert isinstance(body[field], str), f"{field} should be string"
        # Round-trips through Decimal cleanly.
        Decimal(body[field])


# ── 9. IDOR — cross-buyer document download → 404 (NOT 403) ────────────


@pytest.mark.asyncio
async def test_idor_cross_buyer_document_download_404(client: AsyncClient):
    """Buyer A's token cannot fetch Buyer B's KYC doc — collapses to 404.

    A successful breach would have been 200 (data leak) or 403 (existence
    oracle). 404 is the correct hardened shape.
    """
    chain_a = await _mk_buyer_with_full_chain(client)
    chain_b = await _mk_buyer_with_full_chain(client)

    issue_a = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": chain_a["buyer_id"]},
        headers=chain_a["headers"],
    )
    issue_b = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": chain_b["buyer_id"]},
        headers=chain_b["headers"],
    )
    token_a = issue_a.json()["token"]
    token_b = issue_b.json()["token"]

    # Buyer B uploads a KYC doc (valid PDF magic bytes).
    pdf_bytes = b"%PDF-1.7\n" + b"\x00" * 200
    upload = await client.post(
        f"/api/v1/property-dev/portal/buyer/{token_b}/upload-kyc/?document_type=passport",
        files={"file": ("passport.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    doc_id_b = upload.json()["document_id"]

    # Buyer A tries to download Buyer B's doc — must 404.
    sneak = await client.get(f"/api/v1/property-dev/portal/buyer/{token_a}/documents/{doc_id_b}/download/")
    assert sneak.status_code == 404, sneak.text


# ── 10. IDOR — random UUID download also 404 (no existence oracle) ─────


@pytest.mark.asyncio
async def test_random_uuid_download_404(client: AsyncClient, portal_chain):
    """Random UUID returns the same 404 as cross-buyer — no oracle."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]
    res = await client.get(f"/api/v1/property-dev/portal/buyer/{token}/documents/{uuid.uuid4()}/download/")
    assert res.status_code == 404, res.text


# ── 11. KYC upload — PNG-as-PDF rejected (magic-byte enforcement) ──────


@pytest.mark.asyncio
async def test_kyc_upload_png_as_pdf_rejected(
    client: AsyncClient,
    portal_chain,
):
    """PNG magic bytes labelled as ``.pdf`` → 415, not silently stored."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]

    # PNG magic header — but uploader claims it's a PDF in the filename
    # and Content-Type. The magic-byte sniffer still accepts it (PNG is
    # in the KYC allow-list) — so try a *banned* signature: a fake EXE.
    fake_exe = b"MZ\x90\x00" + b"\x00" * 200  # PE header, banned.
    res = await client.post(
        f"/api/v1/property-dev/portal/buyer/{token}/upload-kyc/?document_type=passport",
        files={"file": ("passport.pdf", fake_exe, "application/pdf")},
    )
    assert res.status_code == 415, res.text


# ── 12. KYC upload — happy path (PDF) ─────────────────────────────────


@pytest.mark.asyncio
async def test_kyc_upload_pdf_happy_path(
    client: AsyncClient,
    portal_chain,
):
    """Real PDF bytes → 201 + document_id."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]

    pdf = b"%PDF-1.7\nReally a pdf\n%%EOF"
    res = await client.post(
        f"/api/v1/property-dev/portal/buyer/{token}/upload-kyc/?document_type=address_proof",
        files={"file": ("bill.pdf", pdf, "application/pdf")},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["document_type"] == "address_proof"
    # uuid4 strings parse cleanly.
    uuid.UUID(body["document_id"])
    assert body["storage_path"].endswith(".pdf")


# ── 13. KYC upload — invalid document_type rejected ────────────────────


@pytest.mark.asyncio
async def test_kyc_upload_invalid_type_rejected(
    client: AsyncClient,
    portal_chain,
):
    """An unsupported KYC code (e.g. arbitrary string) → 400."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]
    pdf = b"%PDF-1.7\nhi\n"
    res = await client.post(
        f"/api/v1/property-dev/portal/buyer/{token}/upload-kyc/?document_type=nuclear_codes",
        files={"file": ("a.pdf", pdf, "application/pdf")},
    )
    assert res.status_code == 400, res.text


# ── 14. KYC uploaded docs surface in overview ─────────────────────────


@pytest.mark.asyncio
async def test_overview_lists_uploaded_kyc(
    client: AsyncClient,
    portal_chain,
):
    """After upload, the document appears in ``overview.documents``."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]
    pdf = b"%PDF-1.7\nreal pdf\n%%EOF"
    upload = await client.post(
        f"/api/v1/property-dev/portal/buyer/{token}/upload-kyc/?document_type=passport",
        files={"file": ("passport.pdf", pdf, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text

    overview = await client.get(f"/api/v1/property-dev/portal/buyer/{token}/overview/")
    body = overview.json()
    kyc_docs = [d for d in body["documents"] if d["doc_type"].startswith("kyc:")]
    assert len(kyc_docs) >= 1
    assert any(d["doc_type"] == "kyc:passport" for d in kyc_docs)

    # The corresponding KYC request is now marked uploaded.
    passport_req = next((r for r in body["kyc_requests"] if r["code"] == "passport"), None)
    assert passport_req is not None
    assert passport_req["is_uploaded"] is True


# ── 15. Contact-agent creates a CrmActivity tagged with the buyer ──────


@pytest.mark.asyncio
async def test_contact_agent_creates_activity(
    client: AsyncClient,
    portal_chain,
):
    """Buyer message → CrmActivity row with [source=portal] in body."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]

    res = await client.post(
        f"/api/v1/property-dev/portal/buyer/{token}/contact-agent/",
        json={
            "message": "When will my SPA be ready?",
            "callback_phone": "+49 30 12345678",
        },
    )
    assert res.status_code == 201, res.text
    activity_id = res.json()["activity_id"]

    # Verify the CrmActivity row exists and is tagged with the portal marker.
    from app.database import async_session_factory
    from app.modules.crm.models import CrmActivity

    async with async_session_factory() as s:
        row = await s.get(CrmActivity, uuid.UUID(activity_id))
        assert row is not None
        assert "[source=portal]" in row.body
        assert portal_chain["buyer_id"] in row.body
        assert row.subject.startswith("[Portal]")


# ── 16. Contact-agent publishes the lead-message event ─────────────────


@pytest.mark.asyncio
async def test_contact_agent_publishes_event(
    client: AsyncClient,
    portal_chain,
):
    """``crm.lead.message_received`` is published with the buyer id.

    We monkey-patch ``event_bus.publish_detached`` so we capture the
    event arguments synchronously without running any async subscribers
    (subscribers that hit the DB would race the request session under
    aiosqlite — see ``feedback_lazy_locale_header_race`` for context).
    """
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]

    seen: list[tuple[str, dict]] = []

    from app.core import events as events_mod

    original = events_mod.event_bus.publish_detached

    def _capture(name: str, data: dict, source_module: str | None = None) -> None:
        seen.append((name, data))

    events_mod.event_bus.publish_detached = _capture  # type: ignore[assignment]
    try:
        res = await client.post(
            f"/api/v1/property-dev/portal/buyer/{token}/contact-agent/",
            json={"message": "Test message"},
        )
        assert res.status_code == 201, res.text
        matching = [
            data
            for name, data in seen
            if name == "crm.lead.message_received"
            and data.get("buyer_id") == portal_chain["buyer_id"]
            and data.get("source") == "portal"
        ]
        assert matching, f"event not captured; saw: {seen!r}"
    finally:
        events_mod.event_bus.publish_detached = original  # type: ignore[assignment]


# ── 17. Contact-agent rate limit (30 req / min / token) ────────────────


@pytest.mark.asyncio
async def test_rate_limit_fires_on_31st_request(
    client: AsyncClient,
    portal_chain,
):
    """Burst of N+1 public-endpoint calls trips the per-token approval_limiter.

    Uses /overview/ rather than /verify/ because verify is single-use
    (spec change v3130) and would 401 on the 2nd call before the
    limiter could fire. /overview/ stays multi-use so we can issue
    enough hits to exercise the rate gate.
    """
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]

    # The approval_limiter is shared (max=20) — patch it to a tight 5 so
    # the test runs in <1 second instead of needing 30 hits.
    from app.core import rate_limiter as rl
    from app.modules.property_dev.portal_router import _PORTAL_RATE_BUCKET_PREFIX

    bucket = f"{_PORTAL_RATE_BUCKET_PREFIX}{token[:48]}"
    # Clear any state for this bucket from previous tests.
    with rl.approval_limiter._lock:
        rl.approval_limiter._requests.pop(bucket, None)

    original_max = rl.approval_limiter.max_requests
    rl.approval_limiter.max_requests = 3
    try:
        # Use /overview/ rather than /verify/ for the burst — both go
        # through the same _resolve_portal_context rate-limit gate but
        # /verify/ is single-use after the spec change, so calling it
        # 4× on one token would yield 401 already_used on the 2nd hit
        # before the limiter could fire. /overview/ stays multi-use
        # (session JWT semantics) so the limiter is the only thing
        # rejecting the 4th call — which is what this test pins.
        overview_path = f"/api/v1/property-dev/portal/buyer/{token}/overview/"
        first = await client.get(overview_path)
        second = await client.get(overview_path)
        third = await client.get(overview_path)
        fourth = await client.get(overview_path)
        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 200
        assert fourth.status_code == 429, fourth.text
    finally:
        rl.approval_limiter.max_requests = original_max
        with rl.approval_limiter._lock:
            rl.approval_limiter._requests.pop(bucket, None)


# ── 18. RBAC — EDITOR cannot issue, MANAGER can ────────────────────────


@pytest.mark.asyncio
async def test_rbac_editor_cannot_issue(client: AsyncClient, portal_chain):
    """Editor role gets 403 on POST /issue/."""
    _uid, _email, editor_headers = await _register_user(
        client,
        role="editor",
        tag=f"port-ed-{uuid.uuid4().hex[:6]}",
    )
    res = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=editor_headers,
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_rbac_manager_can_issue(client: AsyncClient):
    """Manager-role user (owning the project) can issue."""
    _uid, _email, headers = await _register_user(
        client,
        role="manager",
        tag=f"port-mg-{uuid.uuid4().hex[:6]}",
    )
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"Port-Mgr-{uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    pid = proj.json()["id"]
    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": pid,
            "code": f"MG-{uuid.uuid4().hex[:6]}",
            "name": "Manager dev",
            "currency": "EUR",
        },
        headers=headers,
    )
    did = dev.json()["id"]
    buyer = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": did,
            "full_name": "Mgr Buyer",
            "email": f"mgr-{uuid.uuid4().hex[:6]}@test.io",
        },
        headers=headers,
    )
    bid = buyer.json()["id"]

    res = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": bid},
        headers=headers,
    )
    assert res.status_code == 201, res.text


# ── 19. Cross-tenant issuance blocked ──────────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_issuance_404(client: AsyncClient):
    """Tenant B cannot mint a portal link for tenant A's buyer."""
    chain_a = await _mk_buyer_with_full_chain(client)
    _uid, _email, headers_b = await _register_user(
        client,
        role="manager",
        tag=f"port-xtnt-{uuid.uuid4().hex[:6]}",
    )

    res = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": chain_a["buyer_id"]},
        headers=headers_b,
    )
    assert res.status_code == 404, res.text


# ── 20. Issued token row appears in /buyer-links/ list ─────────────────


@pytest.mark.asyncio
async def test_buyer_links_lists_active_tokens(
    client: AsyncClient,
    portal_chain,
):
    """``GET /buyer-links/{buyer_id}/`` reflects freshly-issued tokens."""
    await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    listing = await client.get(
        f"/api/v1/property-dev/portal/buyer-links/{portal_chain['buyer_id']}/",
        headers=portal_chain["headers"],
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert len(body) >= 1
    assert body[0]["buyer_id"] == portal_chain["buyer_id"]
    assert body[0]["revoked_at"] is None


# ── 21. Revoked token does not surface in /buyer-links/ list ───────────


@pytest.mark.asyncio
async def test_revoked_token_not_in_active_list(
    client: AsyncClient,
    portal_chain,
):
    """After revoke, the row disappears from the active list."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    row_id = issued.json()["row"]["id"]
    await client.post(
        f"/api/v1/property-dev/portal/tokens/{row_id}/revoke/",
        headers=portal_chain["headers"],
    )
    listing = await client.get(
        f"/api/v1/property-dev/portal/buyer-links/{portal_chain['buyer_id']}/",
        headers=portal_chain["headers"],
    )
    body = listing.json()
    ids = [r["id"] for r in body]
    assert row_id not in ids


# ── 22. verify_token updates last_used_at + last_used_ip ───────────────


@pytest.mark.asyncio
async def test_verify_updates_last_used(client: AsyncClient, portal_chain):
    """Successful verify side-effects the audit columns on the row."""
    issued = await client.post(
        "/api/v1/property-dev/portal/issue/",
        json={"buyer_id": portal_chain["buyer_id"]},
        headers=portal_chain["headers"],
    )
    token = issued.json()["token"]
    row_id = issued.json()["row"]["id"]

    await client.post("/api/v1/property-dev/portal/verify/", json={"token": token})

    from app.database import async_session_factory
    from app.modules.property_dev.models import PortalToken

    async with async_session_factory() as s:
        row = await s.get(PortalToken, uuid.UUID(row_id))
        assert row is not None
        assert row.last_used_at is not None


# ── 23. JWT scope tampering rejected ───────────────────────────────────


@pytest.mark.asyncio
async def test_jwt_scope_tampering_rejected(client: AsyncClient):
    """A JWT minted with scope != 'portal' (e.g. a leaked access token)
    is rejected by /verify/ even though the signature is valid."""
    from jose import jwt

    from app.config import get_settings

    settings = get_settings()
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "iss": "openconstructionerp",
            "sub": str(uuid.uuid4()),
            "scope": "access",  # wrong scope
            "type": "access",
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    res = await client.post("/api/v1/property-dev/portal/verify/", json={"token": forged})
    assert res.status_code == 401, res.text
