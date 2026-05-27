"""Unit tests for the Contacts ↔ PropDev module bridge.

Covers the v3117 bridge:

* :func:`app.modules.contacts.bridge.ensure_contact_for_lead` and
  :func:`ensure_contact_for_buyer` — find-or-create + module-tag
  application.
* :func:`mirror_lead_fields_to_contact` and
  :func:`mirror_buyer_fields_to_contact` — write-back of canonical
  fields when the module entity is edited.
* :func:`list_module_rows_for_contact` — reverse lookup.
* Cross-tenant guard: a lead created by user A must not link to a
  contact created by user B even when the emails match.

The tests run against an in-memory SQLite engine, exercising the real
ORM so the JSON columns and FK linkages exercise their actual storage
paths.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.contacts import bridge
from app.modules.contacts.models import Contact
from app.modules.projects.models import Project
from app.modules.property_dev.models import (
    Buyer,
    Development,
    HouseType,
    HouseTypeVariant,
    Lead,
    Plot,
)
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Spin up a fresh in-memory database with the tables the bridge needs."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # Pull in only the tables the bridge touches. The full
        # PropDev set is listed here because Lead / Buyer FK to
        # ``oe_property_dev_development`` / ``oe_property_dev_plot``
        # transitively (development_id is nullable so the FK is the
        # constraint that matters).
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                Project.__table__,
                Contact.__table__,
                Development.__table__,
                HouseType.__table__,
                HouseTypeVariant.__table__,
                Plot.__table__,
                Lead.__table__,
                Buyer.__table__,
            ],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────


def _make_lead(
    *,
    email: str = "alice@example.com",
    full_name: str = "Alice Müller",
    phone: str | None = "+49 30 1234567",
) -> Lead:
    return Lead(
        development_id=None,
        tenant_id=None,
        source="web_form",
        lead_score=Decimal("0"),
        status="new",
        full_name=full_name,
        email=email,
        phone=phone,
        language="en",
        currency="",
        metadata_={},
    )


def _make_buyer(
    *,
    development_id: uuid.UUID,
    email: str = "alice@example.com",
    full_name: str = "Alice Müller",
) -> Buyer:
    return Buyer(
        development_id=development_id,
        full_name=full_name,
        email=email,
        phone="+49 30 1234567",
        language="en",
        status="lead",
        contract_value=Decimal("0"),
        currency="",
        metadata_={},
    )


async def _make_development(session: AsyncSession) -> Development:
    # Development.project_id is NOT NULL with FK to projects — we
    # need a parent Project row to satisfy the constraint. Project
    # itself FKs to oe_users_user via ``owner_id``, so we plant a
    # disposable user first. This is the minimal chain to get a valid
    # Development row in an in-memory test database.
    user = User(
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Test Owner",
        role="admin",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"P-{uuid.uuid4().hex[:6]}", status="active", owner_id=user.id)
    session.add(project)
    await session.flush()
    dev = Development(
        project_id=project.id,
        code=f"D-{uuid.uuid4().hex[:6]}",
        name="Test Dev",
        dev_type="residential",
    )
    session.add(dev)
    await session.flush()
    return dev


# ── Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_lead_autocreates_contact_with_lead_tag(
    session: AsyncSession,
) -> None:
    """A fresh Lead with no matching Contact yields a brand-new Contact row tagged property_dev_lead."""
    lead = _make_lead(email="newperson@example.com")
    session.add(lead)
    await session.flush()

    contact = await bridge.ensure_contact_for_lead(session, lead, tenant_id="user-1")

    assert contact.id is not None
    assert lead.contact_id == contact.id
    assert contact.primary_email == "newperson@example.com"
    assert contact.first_name == "Alice"
    assert contact.last_name == "Müller"
    assert bridge.PROPERTY_DEV_LEAD_TAG in (contact.module_tags or [])
    assert contact.tenant_id == "user-1"


@pytest.mark.asyncio
async def test_create_buyer_with_existing_contact_email_links_not_duplicates(
    session: AsyncSession,
) -> None:
    """When a Contact already exists for the buyer's email we link, not duplicate."""
    # Existing contact owned by user-1.
    existing = Contact(
        contact_type="customer",
        first_name="Existing",
        last_name="Person",
        primary_email="shared@example.com",
        primary_phone="+1 555 0000",
        tenant_id="user-1",
        created_by="user-1",
    )
    session.add(existing)
    await session.flush()
    existing_id = existing.id

    dev = await _make_development(session)
    buyer = _make_buyer(development_id=dev.id, email="shared@example.com")
    session.add(buyer)
    await session.flush()

    contact = await bridge.ensure_contact_for_buyer(session, buyer, tenant_id="user-1")

    assert contact.id == existing_id  # same row, not a new one
    assert buyer.contact_id == existing_id
    assert bridge.PROPERTY_DEV_BUYER_TAG in (contact.module_tags or [])


@pytest.mark.asyncio
async def test_lead_then_buyer_for_same_email_gets_both_tags(
    session: AsyncSession,
) -> None:
    """A contact that is first a Lead and later a Buyer carries BOTH tags."""
    # Step 1: lead created → contact gets property_dev_lead.
    lead = _make_lead(email="convert@example.com")
    session.add(lead)
    await session.flush()
    contact_lead = await bridge.ensure_contact_for_lead(session, lead, tenant_id="u-1")
    contact_id = contact_lead.id
    assert bridge.PROPERTY_DEV_LEAD_TAG in (contact_lead.module_tags or [])
    assert bridge.PROPERTY_DEV_BUYER_TAG not in (contact_lead.module_tags or [])

    # Step 2: buyer created for the same email → same contact, both tags.
    dev = await _make_development(session)
    buyer = _make_buyer(development_id=dev.id, email="convert@example.com")
    session.add(buyer)
    await session.flush()
    contact_buyer = await bridge.ensure_contact_for_buyer(session, buyer, tenant_id="u-1")

    assert contact_buyer.id == contact_id
    tags = set(contact_buyer.module_tags or [])
    assert bridge.PROPERTY_DEV_LEAD_TAG in tags
    assert bridge.PROPERTY_DEV_BUYER_TAG in tags


@pytest.mark.asyncio
async def test_update_lead_email_mirrors_to_contact(session: AsyncSession) -> None:
    """Editing the Lead's email writes back to the linked Contact."""
    lead = _make_lead(email="before@example.com")
    session.add(lead)
    await session.flush()
    contact = await bridge.ensure_contact_for_lead(session, lead, tenant_id="u-1")
    assert contact.primary_email == "before@example.com"

    # Simulate the service update: caller changes the lead's email.
    lead.email = "after@example.com"
    await session.flush()
    mirrored = await bridge.mirror_lead_fields_to_contact(session, lead)

    assert mirrored is not None
    assert mirrored.id == contact.id
    assert mirrored.primary_email == "after@example.com"


@pytest.mark.asyncio
async def test_cross_tenant_contacts_not_reused(session: AsyncSession) -> None:
    """A lead created by user-1 must not silently link to user-2's contact (IDOR guard)."""
    # User-2's contact.
    foreign = Contact(
        contact_type="customer",
        first_name="Other",
        last_name="Tenant",
        primary_email="shared@example.com",
        tenant_id="user-2",
        created_by="user-2",
    )
    session.add(foreign)
    await session.flush()

    # User-1 creates a Lead with the same email.
    lead = _make_lead(email="shared@example.com")
    session.add(lead)
    await session.flush()
    contact = await bridge.ensure_contact_for_lead(session, lead, tenant_id="user-1")

    # The bridge must NOT pick the foreign contact — it must create a
    # fresh row in user-1's tenant.
    assert contact.id != foreign.id
    assert contact.tenant_id == "user-1"
    assert lead.contact_id == contact.id


@pytest.mark.asyncio
async def test_list_module_rows_for_contact(session: AsyncSession) -> None:
    """Reverse lookup returns Lead + Buyer payloads for the contact."""
    lead = _make_lead(email="multi@example.com")
    session.add(lead)
    await session.flush()
    contact = await bridge.ensure_contact_for_lead(session, lead, tenant_id="u-1")

    dev = await _make_development(session)
    buyer = _make_buyer(development_id=dev.id, email="multi@example.com")
    session.add(buyer)
    await session.flush()
    await bridge.ensure_contact_for_buyer(session, buyer, tenant_id="u-1")

    rows = await bridge.list_module_rows_for_contact(session, contact.id)
    assert len(rows["property_dev_leads"]) == 1
    assert rows["property_dev_leads"][0]["id"] == str(lead.id)
    assert len(rows["property_dev_buyers"]) == 1
    assert rows["property_dev_buyers"][0]["id"] == str(buyer.id)


@pytest.mark.asyncio
async def test_lead_without_email_creates_contact_anyway(
    session: AsyncSession,
) -> None:
    """Email-less leads still produce a contact (matched only by future updates).

    Inbound walk-in leads may arrive with only a name + phone — the
    bridge accepts that and creates a contact with a NULL email. The
    next lead with the same name will NOT match (we only dedupe on
    email) which is the correct behaviour for low-quality identifiers.
    """
    lead = _make_lead(email="", full_name="Phone-only Walkin")
    session.add(lead)
    await session.flush()
    contact = await bridge.ensure_contact_for_lead(session, lead, tenant_id="u-1")

    assert contact.id is not None
    assert contact.primary_email is None
    assert contact.first_name == "Phone-only"
    assert contact.last_name == "Walkin"
    assert bridge.PROPERTY_DEV_LEAD_TAG in (contact.module_tags or [])
