"""Wave 23 — Reporting currency parameterisation integration tests.

Verifies that the ``POST /reporting/generate/`` endpoint:

1. Resolves currency from the project's ``currency`` field and stamps it
   into ``data_snapshot["currency"]`` when no ``override_currency`` is
   provided.
2. Honours the caller-supplied ``override_currency`` ahead of the
   project default.
3. Falls back to ``"EUR"`` when the project has no currency set.

Also verifies the negative assertions required by the audit spec:
- A USD project's report must NOT contain the euro sign (``€``) when
  the data_snapshot is rendered.
- A DACH (EUR) project's report must NOT contain the dollar sign (``$``).

Scaffolding mirrors ``test_reporting_idor.py`` — per-module SQLite
registered BEFORE any ``app`` import to keep the production database
untouched.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation ────────────────────────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-reporting-currency-"))
_TMP_DB = _TMP_DIR / "reporting_currency.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.reporting import models as _reporting_models  # noqa: F401

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
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()


async def _register_and_login(
    client: AsyncClient,
    label: str,
) -> tuple[str, dict[str, str]]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@rep-ccy.io"
    password = f"RepCcy{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    await _activate_user(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def admin_headers(http_client):
    _email, headers = await _register_and_login(http_client, "admin-ccy")
    return headers


async def _create_project(
    client: AsyncClient,
    headers: dict,
    currency: str,
) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Currency-Test-{currency}-{uuid.uuid4().hex[:6]}",
            "description": "Wave 23 currency test project",
            "currency": currency,
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"project create failed: {resp.text}"
    return resp.json()["id"]


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_currency_stamped_from_project_usd(
    http_client,
    admin_headers,
):
    """A USD project's generated report must carry currency='USD' in data_snapshot."""
    project_id = await _create_project(http_client, admin_headers, "USD")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "USD Cost Report",
            "format": "pdf",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # data_snapshot must carry the stamped currency.
    snapshot = body.get("data_snapshot") or {}
    assert snapshot.get("currency") == "USD", f"Expected currency='USD' in data_snapshot, got: {snapshot!r}"


@pytest.mark.asyncio
async def test_report_currency_stamped_from_project_eur(
    http_client,
    admin_headers,
):
    """A EUR (DACH) project's report must carry currency='EUR'."""
    project_id = await _create_project(http_client, admin_headers, "EUR")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "EUR Cost Report",
            "format": "pdf",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    snapshot = resp.json().get("data_snapshot") or {}
    assert snapshot.get("currency") == "EUR", f"Expected currency='EUR' in data_snapshot, got: {snapshot!r}"


@pytest.mark.asyncio
async def test_override_currency_takes_precedence(
    http_client,
    admin_headers,
):
    """override_currency='GBP' must win over the project's default 'USD'."""
    project_id = await _create_project(http_client, admin_headers, "USD")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "GBP Override Report",
            "format": "pdf",
            "override_currency": "GBP",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    snapshot = resp.json().get("data_snapshot") or {}
    assert snapshot.get("currency") == "GBP", f"Expected override 'GBP' in data_snapshot, got: {snapshot!r}"


@pytest.mark.asyncio
async def test_usd_report_no_euro_symbol_in_snapshot(
    http_client,
    admin_headers,
):
    """USD project report: data_snapshot must not contain euro sign or 'EUR' as currency."""
    project_id = await _create_project(http_client, admin_headers, "USD")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "USD Cost Report — no euro",
            "format": "pdf",
            "data_snapshot": {"total": "123456.00"},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    snapshot = body.get("data_snapshot") or {}

    # The currency code must be USD, not EUR.
    assert snapshot.get("currency") == "USD", snapshot
    # The euro symbol must not appear in the JSON response text at all.
    assert "€" not in resp.text, f"Euro sign leaked into USD report response: {resp.text!r}"


@pytest.mark.asyncio
async def test_eur_report_no_dollar_symbol_in_snapshot(
    http_client,
    admin_headers,
):
    """EUR (DACH) project report: data_snapshot must not contain dollar sign or 'USD'."""
    project_id = await _create_project(http_client, admin_headers, "EUR")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "project_status",
            "title": "DACH EUR Report — no dollar",
            "format": "pdf",
            "data_snapshot": {"total": "500000.00"},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    snapshot = resp.json().get("data_snapshot") or {}

    assert snapshot.get("currency") == "EUR", snapshot
    assert "$" not in resp.text, f"Dollar sign leaked into EUR report response: {resp.text!r}"


@pytest.mark.asyncio
async def test_fallback_to_eur_when_project_currency_null(
    http_client,
    admin_headers,
):
    """When a project has no currency set, the report must default to 'EUR'."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    # Create project then NULL out its currency directly (simulates a legacy
    # project created before the currency column was mandatory).
    project_id = await _create_project(http_client, admin_headers, "EUR")
    async with async_session_factory() as s:
        await s.execute(
            update(Project).where(Project.id == uuid.UUID(project_id)).values(currency="")  # empty string = "not set"
        )
        await s.commit()

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "Fallback-to-EUR Report",
            "format": "pdf",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    snapshot = resp.json().get("data_snapshot") or {}
    assert snapshot.get("currency") == "EUR", f"Expected EUR fallback, got: {snapshot!r}"


@pytest.mark.asyncio
async def test_currency_persisted_on_generated_report_model(
    http_client,
    admin_headers,
):
    """The resolved currency must be persisted in GeneratedReport.currency column."""
    project_id = await _create_project(http_client, admin_headers, "JPY")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "JPY Report",
            "format": "pdf",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    report_id = resp.json()["id"]

    # Verify the DB row has the correct currency column value.
    from app.database import async_session_factory
    from app.modules.reporting.models import GeneratedReport

    async with async_session_factory() as s:
        row = await s.get(GeneratedReport, uuid.UUID(report_id))
        assert row is not None
        assert row.currency == "JPY", f"Expected GeneratedReport.currency='JPY', got {row.currency!r}"


@pytest.mark.asyncio
async def test_override_currency_normalised_to_uppercase(
    http_client,
    admin_headers,
):
    """override_currency supplied in lowercase must be normalised to uppercase."""
    project_id = await _create_project(http_client, admin_headers, "EUR")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "Lowercase currency override",
            "format": "pdf",
            "override_currency": "chf",  # lowercase
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    snapshot = resp.json().get("data_snapshot") or {}
    assert snapshot.get("currency") == "CHF", f"Expected uppercase 'CHF', got: {snapshot!r}"


@pytest.mark.asyncio
async def test_invalid_override_currency_rejected(
    http_client,
    admin_headers,
):
    """A non-ISO override (e.g. 4-letter code) must be rejected with 422."""
    project_id = await _create_project(http_client, admin_headers, "EUR")

    resp = await http_client.post(
        "/api/v1/reporting/generate/",
        json={
            "project_id": project_id,
            "report_type": "cost_report",
            "title": "Invalid currency override",
            "format": "pdf",
            "override_currency": "EURO",  # 4 chars — invalid
        },
        headers=admin_headers,
    )
    assert resp.status_code == 422, f"Expected 422 for invalid override_currency, got {resp.status_code}: {resp.text}"
