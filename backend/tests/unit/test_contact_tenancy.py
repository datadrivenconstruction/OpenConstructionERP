"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for Contact.tenant_id (v2.3.1).

Covers:
    - Service sets ``tenant_id`` on insert alongside ``created_by``.
    - Repository list/stats/list_by_company scope by ``tenant_id``.
    - Legacy rows (tenant_id NULL, created_by set) still match via the
      backwards-compat fallback so pre-v2.3.1 data stays reachable to
      its original author after the migration.
    - Cross-tenant rows are NOT returned when the caller passes an
      ``owner_id`` filter — the core IDOR guarantee.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository, _tenant_scope
from app.modules.contacts.schemas import ContactCreate
from app.modules.contacts.service import ContactService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Session bound to the shared PostgreSQL unit database.

    The session runs inside an outer transaction that is rolled back on
    teardown, so each test starts against an empty schema (the full
    ``oe_test_unit`` schema is materialised once per session, including
    ``oe_users_user`` for ``Contact.user_id``). The session's own
    ``commit()`` becomes a savepoint release, so committed data is visible
    within the test but undone afterward.
    """
    async with transactional_session() as s:
        yield s


async def _insert_raw(
    session: AsyncSession,
    *,
    company_name: str,
    tenant_id: str | None,
    created_by: str | None,
) -> Contact:
    """Insert a contact bypassing the service (simulates migrated + legacy rows)."""
    contact = Contact(
        contact_type="supplier",
        company_name=company_name,
        tenant_id=tenant_id,
        created_by=created_by,
    )
    session.add(contact)
    await session.flush()
    await session.refresh(contact)
    return contact


# ---------------------------------------------------------------------------
# Service -- create
# ---------------------------------------------------------------------------


class TestServiceSetsTenantOnCreate:
    @pytest.mark.asyncio
    async def test_tenant_id_is_populated(self, session):
        service = ContactService(session)
        user_id = str(uuid.uuid4())
        contact = await service.create_contact(
            ContactCreate(contact_type="supplier", company_name="Acme"),
            user_id=user_id,
        )
        assert contact.tenant_id == user_id
        # Audit field populated alongside the access gate.
        assert contact.created_by == user_id

    @pytest.mark.asyncio
    async def test_anonymous_creation_leaves_tenant_null(self, session):
        service = ContactService(session)
        contact = await service.create_contact(
            ContactCreate(contact_type="supplier", company_name="Anonymous Ltd"),
            user_id=None,
        )
        assert contact.tenant_id is None
        assert contact.created_by is None


# ---------------------------------------------------------------------------
# Repository list -- tenant scoping
# ---------------------------------------------------------------------------


class TestRepositoryListTenantScoping:
    @pytest.mark.asyncio
    async def test_returns_only_own_tenant(self, session):
        alice = str(uuid.uuid4())
        bob = str(uuid.uuid4())
        await _insert_raw(session, company_name="Alice Co", tenant_id=alice, created_by=alice)
        await _insert_raw(session, company_name="Bob Co", tenant_id=bob, created_by=bob)

        repo = ContactRepository(session)
        items, total = await repo.list(owner_id=alice)
        assert total == 1
        assert [c.company_name for c in items] == ["Alice Co"]

    @pytest.mark.asyncio
    async def test_legacy_row_with_created_by_is_reachable(self, session):
        """Pre-v2.3.1 rows have tenant_id=NULL but created_by set."""
        alice = str(uuid.uuid4())
        await _insert_raw(
            session,
            company_name="Legacy Co",
            tenant_id=None,
            created_by=alice,
        )

        repo = ContactRepository(session)
        items, total = await repo.list(owner_id=alice)
        assert total == 1
        assert items[0].company_name == "Legacy Co"

    @pytest.mark.asyncio
    async def test_other_tenants_legacy_rows_are_not_reachable(self, session):
        """Cross-tenant legacy row must stay invisible to unrelated callers."""
        alice = str(uuid.uuid4())
        bob = str(uuid.uuid4())
        await _insert_raw(
            session,
            company_name="Bob Legacy",
            tenant_id=None,
            created_by=bob,
        )

        repo = ContactRepository(session)
        items, total = await repo.list(owner_id=alice)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_admin_unscoped_query_returns_all(self, session):
        """``owner_id=None`` is the admin bypass — every tenant visible."""
        alice = str(uuid.uuid4())
        bob = str(uuid.uuid4())
        await _insert_raw(session, company_name="Alice Co", tenant_id=alice, created_by=alice)
        await _insert_raw(session, company_name="Bob Co", tenant_id=bob, created_by=bob)

        repo = ContactRepository(session)
        items, total = await repo.list(owner_id=None)
        assert total == 2
        assert sorted(c.company_name for c in items) == ["Alice Co", "Bob Co"]

    @pytest.mark.asyncio
    async def test_null_owner_row_stays_admin_only(self, session):
        """Rows with neither tenant_id nor created_by must only leak via admin bypass."""
        alice = str(uuid.uuid4())
        await _insert_raw(
            session,
            company_name="Orphaned Co",
            tenant_id=None,
            created_by=None,
        )

        repo = ContactRepository(session)
        items, total = await repo.list(owner_id=alice)
        assert total == 0

        items_all, total_all = await repo.list(owner_id=None)
        assert total_all == 1
        assert items_all[0].company_name == "Orphaned Co"


# ---------------------------------------------------------------------------
# Repository stats + list_by_company
# ---------------------------------------------------------------------------


class TestStatsTenantScoping:
    @pytest.mark.asyncio
    async def test_stats_scoped_to_tenant(self, session):
        alice = str(uuid.uuid4())
        bob = str(uuid.uuid4())
        await _insert_raw(session, company_name="Alice Co", tenant_id=alice, created_by=alice)
        await _insert_raw(session, company_name="Bob Co 1", tenant_id=bob, created_by=bob)
        await _insert_raw(session, company_name="Bob Co 2", tenant_id=bob, created_by=bob)

        repo = ContactRepository(session)
        alice_stats = await repo.stats(owner_id=alice)
        bob_stats = await repo.stats(owner_id=bob)
        assert alice_stats["total"] == 1
        assert bob_stats["total"] == 2

    @pytest.mark.asyncio
    async def test_list_by_company_scoped_to_tenant(self, session):
        alice = str(uuid.uuid4())
        bob = str(uuid.uuid4())
        await _insert_raw(
            session,
            company_name="Shared Corp",
            tenant_id=alice,
            created_by=alice,
        )
        await _insert_raw(
            session,
            company_name="Shared Corp",
            tenant_id=bob,
            created_by=bob,
        )

        repo = ContactRepository(session)
        items, total = await repo.list_by_company("Shared Corp", owner_id=alice)
        assert total == 1
        assert items[0].tenant_id == alice


# ---------------------------------------------------------------------------
# _tenant_scope predicate smoke test
# ---------------------------------------------------------------------------


class TestTenantScopePredicate:
    """Ensures the predicate compiles and contains the OR clause."""

    def test_returns_or_clause(self):
        pred = _tenant_scope("abc")
        compiled = str(pred.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_id" in compiled
        assert "created_by" in compiled
        assert " OR " in compiled.upper()
