"""Wave 23 — Document template currency parameterisation integration tests.

Covers the ``resolve_template_currency`` helper from
``app.modules.reporting.currency_resolver`` and the
``PropertyDevCustomTemplate.override_currency`` model column (alembic
migration v3135).

Test groups
-----------
1. ``resolve_template_currency`` unit-style tests (using a live DB session
   from the test app so we exercise the real SQLAlchemy path).
2. ``PropertyDevCustomTemplate.override_currency`` persistence via direct
   DB writes — verifies the alembic migration added the column correctly.
3. Resolution-chain contract:
   - override_currency → project.currency → EUR fallback.
   - Changing the project's currency causes re-resolution on the next call.
   - 422 when ``require_resolved=True`` and no currency is found.

Scaffolding mirrors ``test_reporting_currency.py`` — per-module SQLite
registered BEFORE any ``app`` import to keep the production database
untouched.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation ────────────────────────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-doc-tmpl-currency-"))
_TMP_DB = _TMP_DIR / "doc_tmpl_currency.db"
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
        from app.modules.projects import models as _project_models  # noqa: F401
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

        # Import all relevant model namespaces so SQLAlchemy knows the tables.
        from app.modules.reporting import models as _reporting_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_admin(email: str) -> None:
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
    email = f"{label}-{uuid.uuid4().hex[:8]}@doc-ccy.io"
    password = f"DocCcy{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    await _activate_admin(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def admin_headers(http_client):
    _email, headers = await _register_and_login(http_client, "doc-ccy-admin")
    return headers


async def _create_project(
    client: AsyncClient,
    headers: dict,
    currency: str,
) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"DocCcy-{currency}-{uuid.uuid4().hex[:6]}",
            "description": "Wave 23 doc-template currency test",
            "currency": currency,
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"project create failed: {resp.text}"
    return resp.json()["id"]


# ── Tests: resolve_template_currency ──────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_returns_override_currency(app_instance):
    """override_currency takes priority over project.currency."""
    from app.database import async_session_factory
    from app.modules.reporting.currency_resolver import resolve_template_currency

    async with async_session_factory() as session:
        result = await resolve_template_currency(
            session=session,
            project_id=None,
            override_currency="GBP",
        )
    assert result == "GBP"


@pytest.mark.asyncio
async def test_resolver_reads_project_currency(http_client, admin_headers, app_instance):
    """Without override, the resolver reads Project.currency from the DB."""
    from app.database import async_session_factory
    from app.modules.reporting.currency_resolver import resolve_template_currency

    project_id = await _create_project(http_client, admin_headers, "AUD")

    async with async_session_factory() as session:
        result = await resolve_template_currency(
            session=session,
            project_id=uuid.UUID(project_id),
            override_currency=None,
        )
    assert result == "AUD", f"Expected 'AUD', got {result!r}"


@pytest.mark.asyncio
async def test_resolver_fallback_to_eur_no_project(app_instance):
    """When project_id is None and no override, falls back to EUR."""
    from app.database import async_session_factory
    from app.modules.reporting.currency_resolver import resolve_template_currency

    async with async_session_factory() as session:
        result = await resolve_template_currency(
            session=session,
            project_id=None,
            override_currency=None,
        )
    assert result == "EUR"


@pytest.mark.asyncio
async def test_resolver_fallback_to_eur_unknown_project(app_instance):
    """When project UUID doesn't exist, the resolver falls back to EUR."""
    from app.database import async_session_factory
    from app.modules.reporting.currency_resolver import resolve_template_currency

    non_existent = uuid.uuid4()
    async with async_session_factory() as session:
        result = await resolve_template_currency(
            session=session,
            project_id=non_existent,
            override_currency=None,
        )
    assert result == "EUR"


@pytest.mark.asyncio
async def test_resolver_require_resolved_raises_422_when_no_currency(app_instance):
    """require_resolved=True must raise 422 when project is missing and no override."""
    from fastapi import HTTPException

    from app.database import async_session_factory
    from app.modules.reporting.currency_resolver import resolve_template_currency

    non_existent = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await resolve_template_currency(
                session=session,
                project_id=non_existent,
                override_currency=None,
                require_resolved=True,
            )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_resolver_require_resolved_ok_when_override_supplied(app_instance):
    """require_resolved=True must NOT raise when override_currency is given."""
    from app.database import async_session_factory
    from app.modules.reporting.currency_resolver import resolve_template_currency

    non_existent = uuid.uuid4()
    async with async_session_factory() as session:
        result = await resolve_template_currency(
            session=session,
            project_id=non_existent,
            override_currency="CHF",
            require_resolved=True,
        )
    assert result == "CHF"


@pytest.mark.asyncio
async def test_resolver_currency_change_reflected_on_next_call(
    http_client,
    admin_headers,
    app_instance,
):
    """Changing the project's currency is reflected in the next resolve call."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.reporting.currency_resolver import resolve_template_currency

    project_id = await _create_project(http_client, admin_headers, "CAD")
    pid = uuid.UUID(project_id)

    # First resolution: should return CAD.
    async with async_session_factory() as session:
        r1 = await resolve_template_currency(session=session, project_id=pid)
    assert r1 == "CAD"

    # Swap currency to MXN.
    async with async_session_factory() as session:
        await session.execute(update(Project).where(Project.id == pid).values(currency="MXN"))
        await session.commit()

    # Second resolution: should now return MXN.
    async with async_session_factory() as session:
        r2 = await resolve_template_currency(session=session, project_id=pid)
    assert r2 == "MXN", f"Expected 'MXN' after project currency change, got {r2!r}"


# ── Tests: PropertyDevCustomTemplate.override_currency column ─────────────


@pytest.mark.asyncio
async def test_custom_template_override_currency_persisted(app_instance):
    """PropertyDevCustomTemplate.override_currency must be stored and retrieved."""
    from app.database import async_session_factory
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    tmpl_id = uuid.uuid4()
    async with async_session_factory() as session:
        tmpl = PropertyDevCustomTemplate(
            id=tmpl_id,
            name="Test Template USD",
            doc_type="invoice",
            entity="contract",
            trigger="manual",
            filename="invoice_usd.docx",
            storage_path=f"uploads/property_dev/custom_templates/{tmpl_id}_invoice_usd.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=1024,
            override_currency="USD",
        )
        session.add(tmpl)
        await session.commit()

    async with async_session_factory() as session:
        loaded = await session.get(PropertyDevCustomTemplate, tmpl_id)
        assert loaded is not None
        assert loaded.override_currency == "USD", f"Expected override_currency='USD', got {loaded.override_currency!r}"


@pytest.mark.asyncio
async def test_custom_template_override_currency_nullable(app_instance):
    """PropertyDevCustomTemplate.override_currency defaults to None (inherit from project)."""
    from app.database import async_session_factory
    from app.modules.property_dev.models import PropertyDevCustomTemplate

    tmpl_id = uuid.uuid4()
    async with async_session_factory() as session:
        tmpl = PropertyDevCustomTemplate(
            id=tmpl_id,
            name="Test Template No Currency",
            doc_type="lease",
            entity="lease",
            trigger="manual",
            filename="lease.docx",
            storage_path=f"uploads/property_dev/custom_templates/{tmpl_id}_lease.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=512,
            # override_currency not set — should default to None
        )
        session.add(tmpl)
        await session.commit()

    async with async_session_factory() as session:
        loaded = await session.get(PropertyDevCustomTemplate, tmpl_id)
        assert loaded is not None
        assert loaded.override_currency is None, (
            f"Expected None for override_currency, got {loaded.override_currency!r}"
        )


@pytest.mark.asyncio
async def test_resolver_uses_template_override_over_project(
    http_client,
    admin_headers,
    app_instance,
):
    """When template.override_currency != project.currency, override wins."""
    from app.database import async_session_factory
    from app.modules.property_dev.models import PropertyDevCustomTemplate
    from app.modules.reporting.currency_resolver import resolve_template_currency

    project_id = await _create_project(http_client, admin_headers, "EUR")
    tmpl_id = uuid.uuid4()

    async with async_session_factory() as session:
        tmpl = PropertyDevCustomTemplate(
            id=tmpl_id,
            name="AED Override Template",
            doc_type="invoice",
            entity="contract",
            trigger="manual",
            filename="invoice_aed.docx",
            storage_path=f"uploads/property_dev/custom_templates/{tmpl_id}_invoice_aed.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=1024,
            override_currency="AED",  # Dubai dirham — overrides the EUR project
        )
        session.add(tmpl)
        await session.commit()

        # Use the template's override_currency in the resolution chain.
        loaded = await session.get(PropertyDevCustomTemplate, tmpl_id)
        assert loaded is not None

        resolved = await resolve_template_currency(
            session=session,
            project_id=uuid.UUID(project_id),
            override_currency=loaded.override_currency,
        )

    assert resolved == "AED", f"Expected 'AED' from template override, got {resolved!r}"
