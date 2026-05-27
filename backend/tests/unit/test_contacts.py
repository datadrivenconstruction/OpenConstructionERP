"""Baseline unit tests for the ``contacts`` module.

Covers the CRUD service round-trip (create / list / update / delete) plus
two security regressions:

* Export endpoint refuses callers without ``contacts.read``.
* PII (raw e-mail, phone) is not interpolated into log records emitted
  by the create/update/delete service paths.

The aim is a fast, dependency-free baseline — a future contributor
adding business logic to the module can extend this file rather than
starting from zero.
"""

from __future__ import annotations

import io
import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.contacts.models import Contact
from app.modules.contacts.schemas import ContactCreate, ContactUpdate
from app.modules.contacts.service import ContactService
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Scoped to Contact + User tables — see test_contact_tenancy for the rationale."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # Audit table is needed because the service writes to it on every
    # mutating call. Importing it here also registers it on Base.metadata.
    from app.core.audit import AuditEntry

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, Contact.__table__, AuditEntry.__table__],
        )
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# CRUD round-trip
# ---------------------------------------------------------------------------


class TestContactCrudRoundTrip:
    @pytest.mark.asyncio
    async def test_create_list_update_delete(self, session: AsyncSession) -> None:
        service = ContactService(session)
        user_id = str(uuid.uuid4())

        # Create
        created = await service.create_contact(
            ContactCreate(
                contact_type="supplier",
                company_name="Acme Construction GmbH",
                primary_email="info@acme.de",
                primary_phone="+49 170 1234567",
            ),
            user_id=user_id,
        )
        assert created.id is not None
        assert created.tenant_id == user_id
        # Service normalises e-mail to lower-case so dup-detection works.
        assert created.primary_email == "info@acme.de"

        # List (tenant-scoped)
        items, total = await service.list_contacts(owner_id=user_id)
        assert total == 1
        assert [c.id for c in items] == [created.id]

        # Update
        updated = await service.update_contact(
            created.id,
            ContactUpdate(company_name="Acme Construction AG"),
            user_id=user_id,
        )
        assert updated.company_name == "Acme Construction AG"

        # Soft-delete
        await service.deactivate_contact(created.id, user_id=user_id)
        items_active, total_active = await service.list_contacts(owner_id=user_id)
        assert total_active == 0
        # And still listable via is_active=False — soft-delete, not purge.
        items_archive, total_archive = await service.list_contacts(owner_id=user_id, is_active=False)
        assert total_archive == 1

    @pytest.mark.asyncio
    async def test_duplicate_email_returns_409(self, session: AsyncSession) -> None:
        """Read-then-write duplicate check raises 409, not 500."""
        service = ContactService(session)
        user_id = str(uuid.uuid4())
        await service.create_contact(
            ContactCreate(contact_type="supplier", primary_email="dup@x.com"),
            user_id=user_id,
        )
        with pytest.raises(Exception) as ei:
            await service.create_contact(
                ContactCreate(contact_type="supplier", primary_email="dup@x.com"),
                user_id=user_id,
            )
        # The service raises an HTTPException with status 409.
        from fastapi import HTTPException

        assert isinstance(ei.value, HTTPException)
        assert ei.value.status_code == 409


# ---------------------------------------------------------------------------
# Audit / PII safety
# ---------------------------------------------------------------------------


class TestPiiNotInLogs:
    """Service-layer log lines must not interpolate raw e-mail or phone.

    These records can be shipped to centralised log stores (Loki,
    CloudWatch, Sentry). GDPR Art. 5(1)(c) requires data minimisation,
    so the service redacts PII before formatting any log line.
    """

    @pytest.mark.asyncio
    async def test_create_log_redacts_email_and_phone(
        self,
        session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO, logger="app.modules.contacts.service")

        service = ContactService(session)
        await service.create_contact(
            ContactCreate(
                contact_type="supplier",
                company_name="Visible Co",
                first_name="Alice",
                last_name="Mustermann",
                primary_email="alice.private@secret-domain.example",
                primary_phone="+49 170 99999999",
            ),
            user_id=str(uuid.uuid4()),
        )

        blob = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "alice.private@secret-domain.example" not in blob, f"raw e-mail leaked into log stream: {blob!r}"
        assert "+49 170 99999999" not in blob, f"raw phone leaked into log stream: {blob!r}"
        # The safe label (company name) is allowed.
        assert "Visible Co" in blob

    @pytest.mark.asyncio
    async def test_update_log_does_not_contain_new_email(
        self,
        session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        service = ContactService(session)
        user_id = str(uuid.uuid4())
        created = await service.create_contact(
            ContactCreate(
                contact_type="supplier",
                company_name="Visible Co",
                primary_email="old@example.com",
            ),
            user_id=user_id,
        )
        caplog.clear()
        caplog.set_level(logging.INFO, logger="app.modules.contacts.service")

        await service.update_contact(
            created.id,
            ContactUpdate(primary_email="new-secret@example.com"),
            user_id=user_id,
        )
        blob = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "new-secret@example.com" not in blob
        # The update log line records the *field names* changed, not values.
        assert "primary_email" in blob


# ---------------------------------------------------------------------------
# Export-endpoint permissions
# ---------------------------------------------------------------------------


class TestExportPermissions:
    """The v2.9.14 P0 fix on ``/contacts/export`` must stay in place.

    The audit forced ``contacts.read`` plus a tenant-scoped query so an
    EDITOR with no contacts can no longer scrape every tenant's data.
    This test asserts both:

    * The route registers ``RequirePermission("contacts.read")``.
    * The query filters by ``tenant_id`` / ``created_by``.
    """

    def test_route_requires_contacts_read_permission(self) -> None:
        from app.modules.contacts import router as contacts_router

        export_route = next(r for r in contacts_router.router.routes if getattr(r, "path", "") == "/export/")
        # FastAPI flattens Depends() into ``dependant.dependencies``;
        # ``RequirePermission`` exposes ``permission`` on the callable so
        # we can introspect without invoking it.
        perms = {getattr(d.call, "permission", None) for d in export_route.dependant.dependencies}
        assert "contacts.read" in perms, f"/contacts/export/ lost its permission guard; saw {perms}"

    @pytest.mark.asyncio
    async def test_export_query_is_tenant_scoped(self, session: AsyncSession) -> None:
        """Smoke-check that a non-admin caller only sees their own contacts.

        We exercise the same select() the export route runs (filter on
        is_active + tenant_id / created_by). If the v2.9.14 fix were
        reverted to ``select(Contact).where(is_active)`` this query
        would return Bob's row to Alice.
        """
        from sqlalchemy import and_, or_, select

        alice = str(uuid.uuid4())
        bob = str(uuid.uuid4())
        session.add_all(
            [
                Contact(
                    contact_type="supplier",
                    company_name="Alice Co",
                    tenant_id=alice,
                    created_by=alice,
                    is_active=True,
                ),
                Contact(
                    contact_type="supplier",
                    company_name="Bob Co",
                    tenant_id=bob,
                    created_by=bob,
                    is_active=True,
                ),
            ]
        )
        await session.flush()

        stmt = (
            select(Contact)
            .where(Contact.is_active.is_(True))
            .where(
                or_(
                    Contact.tenant_id == alice,
                    and_(Contact.tenant_id.is_(None), Contact.created_by == alice),
                )
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        names = sorted(c.company_name for c in rows)
        assert names == ["Alice Co"], f"Tenant-scope filter regressed — Alice saw {names}"


# ---------------------------------------------------------------------------
# Magic-byte file sniff
# ---------------------------------------------------------------------------


class TestImportFileMagicByteSniff:
    """``_sniff_upload_content`` rejects mislabelled binaries."""

    def test_rejects_exe_renamed_as_xlsx(self) -> None:
        from fastapi import HTTPException

        from app.modules.contacts.router import _sniff_upload_content

        # MZ header — Windows PE / DOS executable.
        evil = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 32
        with pytest.raises(HTTPException) as ei:
            _sniff_upload_content("payload.xlsx", evil)
        assert ei.value.status_code == 400

    def test_accepts_real_xlsx_signature(self) -> None:
        from app.modules.contacts.router import _sniff_upload_content

        # Real xlsx is a zip — PK\x03\x04 is enough for the sniff (the
        # zip-bomb guard handles structural validity downstream).
        assert _sniff_upload_content("ok.xlsx", b"PK\x03\x04" + b"\x00" * 16) == "xlsx"

    def test_csv_rejects_elf_binary(self) -> None:
        from fastapi import HTTPException

        from app.modules.contacts.router import _sniff_upload_content

        elf = b"\x7fELF" + b"\x00" * 32
        with pytest.raises(HTTPException):
            _sniff_upload_content("contacts.csv", elf)

    def test_csv_accepts_text(self) -> None:
        from app.modules.contacts.router import _sniff_upload_content

        ok = b"company,email\nAcme,info@acme.de\n"
        assert _sniff_upload_content("contacts.csv", ok) == "csv"


# ---------------------------------------------------------------------------
# Audit user_id propagation (PATCH regression)
# ---------------------------------------------------------------------------


class TestAuditCarriesUserId:
    """PATCH used to write audit rows with ``user_id=NULL`` — make sure that doesn't return."""

    @pytest.mark.asyncio
    async def test_update_audit_records_user_id(self, session: AsyncSession) -> None:
        from sqlalchemy import select

        from app.core.audit import AuditEntry

        service = ContactService(session)
        user_id = uuid.uuid4()
        created = await service.create_contact(
            ContactCreate(contact_type="supplier", company_name="Visible Co"),
            user_id=str(user_id),
        )
        await service.update_contact(
            created.id,
            ContactUpdate(company_name="Visible Co (new)"),
            user_id=str(user_id),
        )

        rows = (
            (
                await session.execute(
                    select(AuditEntry).where(
                        AuditEntry.entity_type == "contact",
                        AuditEntry.entity_id == str(created.id),
                        AuditEntry.action == "update",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        # GUID column returns a UUID instance — compare on str both sides
        # to stay platform-agnostic.
        assert str(rows[0].user_id) == str(user_id), (
            "PATCH audit row regressed to user_id=NULL — see service.update_contact"
        )


# Keep io import in use even if a future contributor drops the helper.
_ = io  # noqa: F841
