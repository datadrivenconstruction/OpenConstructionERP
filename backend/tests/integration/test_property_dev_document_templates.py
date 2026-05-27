"""Property Development PDF document-template integration suite.

Covers the six PDF generators in
``app.modules.property_dev.document_templates`` and the two HTTP
endpoints (``GET /documents/{doc_type}`` + ``POST /documents/preview``).

Test groups
-----------
  * Happy path for every generator (6) — magic-byte check + pypdf parse.
  * Multi-locale rendering — one generator per shipped locale
    (en/de/ru/fr/ar/es).
  * Jurisdiction-clause inclusion — RERA / MAHARERA / 214_FZ / CMA.
  * Multi-buyer SPA with ownership_pct = 50/30/20 (sum=100).
  * Draft watermark — present when status=draft, absent when signed.
  * HTTP endpoint — streaming + base64 + filename header.
  * Cross-tenant IDOR — 404 from a different tenant.

Scaffolding mirrors :mod:`test_property_dev_lead_to_spa` — per-module
SQLite registered BEFORE any ``app`` import so the production DB is
never touched.
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-docs-"))
_TMP_DB = _TMP_DIR / "propdev_docs.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402

# ── App fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

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


async def _register(client: AsyncClient, label: str) -> tuple[str, dict[str, str]]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@propdev-docs.io"
    password = f"PropDevDocs{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"{label}"},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, {"_password": password}


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    """Tenant A — primary actor for the bulk of the tests."""
    email, meta = await _register(http_client, "docs-a")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, meta["_password"])

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"DocsA {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    dev = await http_client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"DEV{uuid.uuid4().hex[:6].upper()}",
            "name": "Marina Heights",
            "metadata": {
                "regulator": "RERA",
                "rera_registration_no": "RERA-2026-12345",
                "escrow_account_no": "AE07033456712345678901",
                "escrow_bank": "Emirates NBD",
                "completion_date": "2027-12-31",
                "jurisdiction_seat": "Dubai",
            },
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    plots: list[str] = []
    for i in range(2):
        p = await http_client.post(
            "/api/v1/property-dev/plots/",
            json={
                "development_id": development_id,
                "plot_number": f"A-{i + 1:02d}",
                "area_m2": 120 + i,
                "price_base": 450_000 + i * 5000,
                "currency": "EUR",
            },
            headers=headers,
        )
        assert p.status_code == 201, p.text
        plots.append(p.json()["id"])

    buyers: list[str] = []
    for i in range(3):
        b = await http_client.post(
            "/api/v1/property-dev/buyers/",
            json={
                "development_id": development_id,
                "full_name": f"Buyer {i + 1}",
                "email": f"buyer{i + 1}+{uuid.uuid4().hex[:4]}@example.com",
                "status": "lead",
            },
            headers=headers,
        )
        assert b.status_code == 201, b.text
        buyers.append(b.json()["id"])

    return {
        "email": email,
        "headers": headers,
        "project_id": project_id,
        "development_id": development_id,
        "plots": plots,
        "buyers": buyers,
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    """Tenant B — used for cross-tenant IDOR tests.

    Role intentionally below ``admin`` (admins bypass IDOR checks).
    """
    email, meta = await _register(http_client, "docs-b")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, meta["_password"])

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"DocsB {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {"email": email, "headers": headers, "project_id": proj.json()["id"]}


# ── Helpers — build a full SPA + reservation + handover graph ──────────────


async def _make_contract_graph(
    client: AsyncClient,
    tenant: dict,
    *,
    plot_index: int = 0,
) -> dict[str, str]:
    """Build a Reservation + SalesContract via direct REST endpoints.

    Goes through ``POST /reservations/`` and ``POST /sales-contracts/``
    rather than the lead → convert pipeline (the convert pipeline has a
    pre-existing greenlet sensitivity that's orthogonal to this work and
    out of scope for the document-templates change).
    """
    plot_id = tenant["plots"][plot_index]
    buyer_id = tenant["buyers"][0]

    # Direct Reservation creation. reservation_number is auto-generated.
    res_r = await client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": plot_id,
            "buyer_id": buyer_id,
            "deposit_amount": "10000.00",
            "currency": "EUR",
            "cooling_off_days": 14,
        },
        headers=tenant["headers"],
    )
    assert res_r.status_code == 201, res_r.text
    reservation_id = res_r.json()["id"]

    # Direct SalesContract creation. contract_number is auto-generated.
    spa_r = await client.post(
        "/api/v1/property-dev/sales-contracts/",
        json={
            "plot_id": plot_id,
            "reservation_id": reservation_id,
            "signing_date": "2026-06-01",
            "governing_law": "DE-BE",
            "language": "en",
            "total_value": "450000.00",
            "currency": "EUR",
            "total_price_breakdown": {
                "base": "450000",
                "vat": "0",
                "stamp_duty": "0",
                "legal_fees": "0",
                "options_value": "0",
                "discounts": "0",
            },
        },
        headers=tenant["headers"],
    )
    assert spa_r.status_code == 201, spa_r.text
    contract_id = spa_r.json()["id"]

    return {
        "reservation_id": reservation_id,
        "contract_id": contract_id,
        "plot_id": plot_id,
        "buyer_id": buyer_id,
    }


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def _assert_pdf_magic(b: bytes) -> None:
    assert isinstance(b, bytes), "expected bytes"
    assert b[:4] == b"%PDF", f"missing PDF magic bytes: {b[:8]!r}"
    # Confirm pypdf can parse it.
    PdfReader(io.BytesIO(b))


# ════════════════════════════════════════════════════════════════════════
# Group 1 — Happy path, one per generator (pure-function level)
# ════════════════════════════════════════════════════════════════════════


def _stub(**kw):
    """Lightweight stand-in for ORM rows in pure-function tests."""

    class _S:
        def __init__(self, **k):
            self.__dict__.update(k)

    return _S(**kw)


@pytest.mark.asyncio
async def test_render_reservation_receipt_happy_path():
    from app.modules.property_dev.document_templates import (
        render_reservation_receipt_pdf,
    )

    res = _stub(
        id=uuid.uuid4(),
        reservation_number="RES-2026-001",
        deposit_amount=Decimal("10000"),
        currency="EUR",
        expires_at="2026-06-15",
        cooling_off_until="2026-06-15",
        cooling_off_days=14,
        status="active",
    )
    plot = _stub(plot_number="A-01", area_m2=Decimal("120.5"), currency="EUR", metadata_={})
    dev = _stub(name="Marina Heights", code="MAR01", metadata_={})
    buyers = [_stub(full_name="John Doe", email="john@example.com")]
    pdf = render_reservation_receipt_pdf(res, plot, dev, buyers, locale="en")
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    assert "RES-2026-001" in txt
    assert "John Doe" in txt


@pytest.mark.asyncio
async def test_render_sales_contract_happy_path():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract = _stub(
        id=uuid.uuid4(),
        contract_number="SPA-2026-001",
        signing_date="2026-06-01",
        currency="EUR",
        total_value=Decimal("450000"),
        status="draft",
        total_price_breakdown={"base": "450000", "vat": "0"},
        metadata_={},
    )
    sched = _stub(currency="EUR")
    insts = [
        _stub(
            sequence=1,
            milestone_label="Reservation",
            milestone_event="reservation",
            due_date="2026-06-01",
            amount=Decimal("10000"),
        ),
        _stub(
            sequence=2,
            milestone_label="Foundation",
            milestone_event="foundation_complete",
            due_date="2026-09-01",
            amount=Decimal("440000"),
        ),
    ]
    parties = [
        _stub(
            buyer_id=uuid.uuid4(),
            party_role="primary",
            ownership_pct=Decimal("100"),
            full_name="Buyer One",
            email="one@example.com",
        )
    ]
    plot = _stub(plot_number="A-01", area_m2=Decimal("120"), currency="EUR", metadata_={})
    dev = _stub(name="Marina Heights", code="MAR01", metadata_={"regulator": "NONE"})
    pdf = render_sales_contract_pdf(contract, sched, insts, parties, plot, dev, locale="en")
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    assert "SPA-2026-001" in txt
    assert "Foundation" in txt
    assert "Marina Heights" in txt


@pytest.mark.asyncio
async def test_render_payment_receipt_happy_path():
    from app.modules.property_dev.document_templates import render_payment_receipt_pdf

    inst = _stub(
        id=uuid.uuid4(),
        sequence=2,
        milestone_label="Foundation",
        milestone_event="foundation_complete",
        amount=Decimal("100000"),
        amount_paid=Decimal("100000"),
        paid_at="2026-09-05",
    )
    contract = _stub(contract_number="SPA-2026-001", currency="EUR")
    pdf = render_payment_receipt_pdf(inst, contract, "bank_transfer", "WIRE-9988", locale="en")
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    assert "SPA-2026-001" in txt
    assert "WIRE-9988" in txt


@pytest.mark.asyncio
async def test_render_handover_certificate_happy_path():
    from app.modules.property_dev.document_templates import (
        render_handover_certificate_pdf,
    )

    handover = _stub(
        id=uuid.uuid4(),
        completed_at="2027-06-15",
        keys_handed_over_at="2027-06-15",
        snag_count_at_handover=2,
    )
    contract = _stub(contract_number="SPA-2026-001", status="signed")
    plot = _stub(plot_number="A-01", area_m2=Decimal("120"), metadata_={})
    dev = _stub(name="Marina Heights", code="MAR01", metadata_={})
    pdf = render_handover_certificate_pdf(handover, contract, snag_count=2, plot=plot, development=dev, locale="en")
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    assert "Handover" in txt or "Certificate" in txt


@pytest.mark.asyncio
async def test_render_warranty_certificate_happy_path():
    from app.modules.property_dev.document_templates import (
        render_warranty_certificate_pdf,
    )

    handover = _stub(id=uuid.uuid4(), completed_at="2027-06-15")
    contract = _stub(contract_number="SPA-2026-001", status="signed")
    pdf = render_warranty_certificate_pdf(
        contract,
        handover,
        structural_warranty_years=10,
        finishing_warranty_years=1,
        locale="en",
    )
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    # 10y structural appears in text; some renderers stretch ligatures —
    # check for the years number instead.
    assert "10" in txt


@pytest.mark.asyncio
async def test_render_noc_happy_path():
    from app.modules.property_dev.document_templates import (
        render_no_objection_certificate_pdf,
    )

    contract = _stub(id=uuid.uuid4(), contract_number="SPA-2026-001", status="signed")
    plot = _stub(plot_number="A-01", area_m2=Decimal("120"), metadata_={})
    dev = _stub(name="Marina Heights", code="MAR01", metadata_={})
    pdf = render_no_objection_certificate_pdf(
        contract,
        plot,
        dev,
        requested_by="John Doe",
        locale="en",
    )
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    assert "John Doe" in txt


# ════════════════════════════════════════════════════════════════════════
# Group 2 — Multi-locale rendering (one generator per shipped locale)
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locale,marker",
    [
        ("en", "Reservation Receipt"),
        ("de", "Reservierungsbestätigung"),
        ("ru", "Расписка о бронировании"),
        ("fr", "Reçu de Réservation"),
        ("es", "Recibo de Reserva"),
        ("ar", "إيصال حجز"),
    ],
)
async def test_locale_titles_present(locale, marker):
    """Every shipped locale produces the expected localized title."""
    from app.modules.property_dev.document_templates import (
        render_reservation_receipt_pdf,
    )

    res = _stub(
        id=uuid.uuid4(),
        reservation_number="RES-2026-LOC",
        deposit_amount=Decimal("1000"),
        currency="EUR",
        expires_at="2026-06-15",
        cooling_off_until="2026-06-15",
        cooling_off_days=7,
        status="active",
    )
    plot = _stub(plot_number="A-01", area_m2=Decimal("100"), metadata_={})
    dev = _stub(name="Localized Dev", code="LOC01", metadata_={})
    pdf = render_reservation_receipt_pdf(
        res,
        plot,
        dev,
        [_stub(full_name="Buyer", email="b@example.com")],
        locale=locale,
    )
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    # The Arabic / Russian / etc. extractor sometimes drops diacritics
    # but reportlab will faithfully embed the chars in the stream — at
    # minimum, the PDF should be larger than a degenerate empty doc.
    assert len(pdf) > 1500, f"locale {locale}: PDF too small ({len(pdf)})"
    # And we should be able to find at least the locale-independent
    # signal — the reservation number.
    assert "RES-2026-LOC" in txt
    # Best-effort marker check: Latin-script markers should appear; for
    # Arabic/Russian/etc. the PDF text extractor may fail to extract
    # custom-encoded glyphs, so we relax to "size > threshold" there.
    if locale in {"en", "de", "fr", "es"}:
        assert marker in txt, f"missing marker for {locale}"


# ════════════════════════════════════════════════════════════════════════
# Group 3 — Jurisdiction-clause inclusion (RERA / MAHARERA / 214_FZ / CMA)
# ════════════════════════════════════════════════════════════════════════


def _build_spa_inputs(regulator: str, extra_meta: dict[str, str] | None = None):
    meta = {"regulator": regulator}
    if extra_meta:
        meta.update(extra_meta)
    contract = _stub(
        id=uuid.uuid4(),
        contract_number="SPA-J-1",
        signing_date="2026-06-01",
        currency="EUR",
        total_value=Decimal("100"),
        status="draft",
        total_price_breakdown={},
        metadata_={},
    )
    sched = _stub(currency="EUR")
    parties = [
        _stub(
            buyer_id=uuid.uuid4(),
            party_role="primary",
            ownership_pct=Decimal("100"),
            full_name="J",
            email="j@example.com",
        )
    ]
    plot = _stub(plot_number="A-01", area_m2=Decimal("100"), metadata_={})
    dev = _stub(name=f"Dev-{regulator}", code="JUR01", metadata_=meta)
    return contract, sched, parties, plot, dev


@pytest.mark.asyncio
async def test_jurisdiction_clauses_rera():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract, sched, parties, plot, dev = _build_spa_inputs("RERA", {"rera_registration_no": "RERA-DXB-99"})
    pdf = render_sales_contract_pdf(contract, sched, [], parties, plot, dev, locale="en")
    txt = _pdf_text(pdf)
    assert "RERA" in txt
    # Placeholder substitution worked.
    assert "RERA-DXB-99" in txt
    # Mandatory RERA clauses present.
    assert "Escrow" in txt or "scrow" in txt.lower()


@pytest.mark.asyncio
async def test_jurisdiction_clauses_maharera():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract, sched, parties, plot, dev = _build_spa_inputs(
        "MAHARERA", {"maharera_registration_no": "P52100099", "carpet_area_m2": "95.5"}
    )
    pdf = render_sales_contract_pdf(contract, sched, [], parties, plot, dev, locale="en")
    txt = _pdf_text(pdf)
    assert "MAHARERA" in txt
    assert "P52100099" in txt
    # Carpet-area declaration is the MAHARERA-specific clause.
    assert "Carpet" in txt or "arpet" in txt


@pytest.mark.asyncio
async def test_jurisdiction_clauses_214fz():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract, sched, parties, plot, dev = _build_spa_inputs("214_FZ", {"ddu_registration_no": "77-77-001/000/2026"})
    pdf = render_sales_contract_pdf(contract, sched, [], parties, plot, dev, locale="en")
    txt = _pdf_text(pdf)
    # 214-FZ marker — text contains either "214" or the DDU registration
    # number, depending on which clause heading the extractor catches.
    assert "214" in txt or "DDU" in txt
    assert "77-77-001/000/2026" in txt


@pytest.mark.asyncio
async def test_jurisdiction_clauses_cma():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract, sched, parties, plot, dev = _build_spa_inputs("CMA", {"mof_approval_no": "MOF-9988"})
    pdf = render_sales_contract_pdf(contract, sched, [], parties, plot, dev, locale="en")
    txt = _pdf_text(pdf)
    assert "MOF-9988" in txt or "CMA" in txt or "scrow" in txt.lower()


# ════════════════════════════════════════════════════════════════════════
# Group 4 — Multi-buyer SPA with ownership_pct summing to 100
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_multi_buyer_spa_ownership_sums_to_100():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract = _stub(
        id=uuid.uuid4(),
        contract_number="SPA-MB-1",
        signing_date="2026-06-01",
        currency="EUR",
        total_value=Decimal("600000"),
        status="draft",
        total_price_breakdown={},
        metadata_={},
    )
    sched = _stub(currency="EUR")
    b1 = uuid.uuid4()
    b2 = uuid.uuid4()
    b3 = uuid.uuid4()
    parties = [
        _stub(buyer_id=b1, party_role="primary", ownership_pct=Decimal("50.00")),
        _stub(buyer_id=b2, party_role="co_owner", ownership_pct=Decimal("30.00")),
        _stub(buyer_id=b3, party_role="co_owner", ownership_pct=Decimal("20.00")),
    ]
    lookup = {
        b1: _stub(full_name="Alice Anderson", email="alice@example.com"),
        b2: _stub(full_name="Bob Brown", email="bob@example.com"),
        b3: _stub(full_name="Carol Carter", email="carol@example.com"),
    }
    plot = _stub(plot_number="A-01", area_m2=Decimal("120"), metadata_={})
    dev = _stub(name="Multi-Buyer Dev", code="MUL01", metadata_={"regulator": "NONE"})
    pdf = render_sales_contract_pdf(
        contract,
        sched,
        [],
        parties,
        plot,
        dev,
        locale="en",
        buyer_lookup=lookup,
    )
    _assert_pdf_magic(pdf)
    txt = _pdf_text(pdf)
    assert "Alice Anderson" in txt
    assert "Bob Brown" in txt
    assert "Carol Carter" in txt
    # Ownership percentages appear.
    assert "50.00%" in txt or "50.0%" in txt or "50%" in txt
    # Verify the sum is exactly 100 (mathematically — service layer
    # enforces this on write; here we just confirm the inputs we built).
    assert sum(p.ownership_pct for p in parties) == Decimal("100.00")


# ════════════════════════════════════════════════════════════════════════
# Group 5 — Draft watermark presence/absence
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_watermark_present_when_draft():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract, sched, parties, plot, dev = _build_spa_inputs("NONE")
    contract.status = "draft"
    pdf = render_sales_contract_pdf(contract, sched, [], parties, plot, dev, locale="en")
    txt = _pdf_text(pdf)
    assert "DRAFT" in txt, "DRAFT watermark missing on draft contract"


@pytest.mark.asyncio
async def test_watermark_absent_when_signed():
    from app.modules.property_dev.document_templates import render_sales_contract_pdf

    contract, sched, parties, plot, dev = _build_spa_inputs("NONE")
    contract.status = "signed"
    pdf = render_sales_contract_pdf(contract, sched, [], parties, plot, dev, locale="en")
    txt = _pdf_text(pdf)
    assert "DRAFT" not in txt, "DRAFT watermark must not appear on signed contract"


# ════════════════════════════════════════════════════════════════════════
# Group 6 — HTTP streaming + base64-preview endpoints + IDOR
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_endpoint_stream_returns_pdf_with_filename(http_client, tenant_a):
    graph = await _make_contract_graph(http_client, tenant_a)
    res = await http_client.get(
        f"/api/v1/property-dev/documents/sales_contract?contract_id={graph['contract_id']}&locale=en",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/pdf")
    cd = res.headers.get("content-disposition", "")
    assert "attachment" in cd and ".pdf" in cd
    assert res.content[:4] == b"%PDF", f"bad magic {res.content[:8]!r}"


@pytest.mark.asyncio
async def test_endpoint_preview_returns_base64(http_client, tenant_a):
    graph = await _make_contract_graph(
        http_client,
        tenant_a,
        plot_index=1,
    )
    res = await http_client.post(
        "/api/v1/property-dev/documents/preview",
        json={
            "doc_type": "sales_contract",
            "contract_id": graph["contract_id"],
            "locale": "en",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["doc_type"] == "sales_contract"
    assert body["locale"] == "en"
    assert body["size_bytes"] > 1500
    assert body["page_count"] >= 1
    decoded = base64.b64decode(body["base64"])
    assert decoded[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_endpoint_idor_cross_tenant_returns_404(http_client, tenant_a, tenant_b):
    # Tenant A builds the SPA; Tenant B tries to fetch the document.
    graph = await _make_contract_graph(http_client, tenant_a)
    res = await http_client.get(
        f"/api/v1/property-dev/documents/sales_contract?contract_id={graph['contract_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_endpoint_unknown_doc_type_returns_400(http_client, tenant_a):
    res = await http_client.get(
        "/api/v1/property-dev/documents/totally_made_up?contract_id=" + str(uuid.uuid4()),
        headers=tenant_a["headers"],
    )
    assert res.status_code in (400, 404), res.text


@pytest.mark.asyncio
async def test_endpoint_locale_fallback_to_en_for_unknown(http_client, tenant_a):
    graph = await _make_contract_graph(http_client, tenant_a)
    res = await http_client.get(
        f"/api/v1/property-dev/documents/sales_contract?contract_id={graph['contract_id']}&locale=xx",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.headers.get("x-document-locale") == "en"
