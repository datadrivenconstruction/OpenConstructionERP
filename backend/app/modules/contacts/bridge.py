"""Contacts ↔ Modules bridge — single-source-of-truth person directory.

The Contact table is the canonical store for person data
(``first_name`` / ``last_name`` / ``primary_email`` / ``primary_phone`` /
``address``). Module-specific entities (PropDev ``Lead`` / ``Buyer``,
``Broker``, ``Vendor``, ``Subcontractor`` …) hold only the fields that
are meaningful in their own domain (lead_score, contract_value,
buyer_status, broker_commission_pct, …) plus a nullable ``contact_id``
FK back to the canonical row.

Tagging
-------
A single contact may participate in multiple modules at once — a
person can be a ``property_dev_lead`` who converted to a
``property_dev_buyer`` and later signed up as a ``broker``. We keep a
JSON list ``Contact.module_tags`` and append (idempotently) on every
sync.

The values are opaque short identifiers. We document the canonical set
in :data:`KNOWN_MODULE_TAGS` so callers can use a constant rather than a
string literal, but third-party modules adding their own tag value just
work — there is no registry check.

Workflow
--------

1. **Lead/Buyer create flow** (``service.create_lead`` etc.)::

       contact = await bridge.ensure_contact_for_lead(session, lead, user_id)
       lead.contact_id = contact.id

   The bridge:

   * Looks up an existing contact by ``primary_email`` (case-insensitive)
     when the lead carries one. Matches the email-uniqueness rule the
     Contacts module already enforces.
   * Falls back to creating a fresh contact row with ``contact_type =
     'lead'`` (or ``'customer'`` for buyers) using the Lead's
     ``full_name`` + ``phone`` + ``email``.
   * Appends the module tag (``'property_dev_lead'`` /
     ``'property_dev_buyer'``) to the contact's ``module_tags`` if not
     already present.
   * Returns the (possibly fresh) :class:`Contact`.

2. **Lead/Buyer update flow** (``service.update_lead`` etc.) — when the
   user edits canonical fields on the Lead/Buyer form, the bridge
   mirrors them back to the linked Contact so the directory stays
   authoritative.

3. **Contact ↔ Lead/Buyer conversion** (``router.convert_to_lead`` /
   ``router.convert_to_buyer``) — explicit user action from the
   Contacts UI: "Convert this contact to a PropDev Lead". The bridge
   creates the Lead/Buyer row and links it.

Tenancy
-------
The bridge respects the caller's tenant scope on both sides. A Lead
created by user X only matches a Contact whose ``tenant_id`` == X (or
``created_by`` == X for legacy rows). If the email collides across
tenants the bridge **creates a fresh contact** in the caller's tenant
rather than leaking the existence of someone else's row.

Importing
---------
Modules import from this file via::

    from app.modules.contacts import bridge

The functions are stateless — they take an ``AsyncSession`` plus the
input row and return a Contact / nothing. No globals, no singletons.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact

if TYPE_CHECKING:
    from app.modules.property_dev.models import Buyer, Lead

logger = logging.getLogger(__name__)


# ── Canonical module-tag identifiers ────────────────────────────────

PROPERTY_DEV_LEAD_TAG = "property_dev_lead"
PROPERTY_DEV_BUYER_TAG = "property_dev_buyer"
BROKER_TAG = "broker"
VENDOR_TAG = "vendor"
SUBCONTRACTOR_TAG = "subcontractor"

KNOWN_MODULE_TAGS: tuple[str, ...] = (
    PROPERTY_DEV_LEAD_TAG,
    PROPERTY_DEV_BUYER_TAG,
    BROKER_TAG,
    VENDOR_TAG,
    SUBCONTRACTOR_TAG,
)


# ── Helpers ────────────────────────────────────────────────────────


def _split_full_name(full_name: str | None) -> tuple[str | None, str | None]:
    """Split ``full_name`` into ``(first_name, last_name)``.

    The split is best-effort — single-token names go into ``first_name``;
    multi-token names put everything before the last whitespace into
    ``first_name`` and the rest into ``last_name``. Handles unicode
    correctly (we only split on whitespace, not on ASCII space).
    """
    if not full_name:
        return None, None
    parts = full_name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return " ".join(parts[:-1]), parts[-1]


def _join_name(first: str | None, last: str | None) -> str:
    """Inverse of :func:`_split_full_name` — used when mirroring back."""
    return " ".join(p for p in (first or "", last or "") if p).strip()


def _add_tag(contact: Contact, tag: str) -> bool:
    """Idempotently append ``tag`` to ``contact.module_tags``.

    Returns True if the tag was actually added (i.e. the column needs
    a write). SQLAlchemy can't track in-place mutations of a JSON list
    so we reassign the attribute when we add — that ensures the dirty
    flag fires and the row is UPDATEd on the next flush.
    """
    existing = list(contact.module_tags or [])
    if tag in existing:
        return False
    existing.append(tag)
    contact.module_tags = existing
    return True


async def _find_contact_by_email(
    session: AsyncSession,
    email: str,
    *,
    tenant_id: str | None,
) -> Contact | None:
    """Look up an active contact by primary email within ``tenant_id``.

    Tenant scoping mirrors ``ContactRepository._tenant_scope`` — matches
    by ``Contact.tenant_id`` OR by ``Contact.created_by`` (the v2.3.1
    fallback for legacy rows). If ``tenant_id`` is None we are running
    in an admin / system context and search globally.
    """
    if not email:
        return None
    normalised = email.lower()
    stmt = select(Contact).where(Contact.primary_email == normalised).where(Contact.is_active.is_(True))
    if tenant_id is not None:
        owner = str(tenant_id)
        stmt = stmt.where(or_(Contact.tenant_id == owner, Contact.created_by == owner))
    stmt = stmt.order_by(Contact.created_at.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ── Public API ─────────────────────────────────────────────────────


async def ensure_contact_for_person(
    session: AsyncSession,
    *,
    full_name: str | None,
    email: str | None,
    phone: str | None,
    contact_type: str,
    module_tag: str,
    tenant_id: str | None,
    custom_properties: dict[str, Any] | None = None,
) -> Contact:
    """Return a Contact for the given person, creating one if necessary.

    Search order:
        1. By ``email`` (case-insensitive) scoped to ``tenant_id``.
        2. Otherwise create a fresh row.

    Either way the function:

    * Appends ``module_tag`` to ``Contact.module_tags`` (idempotent).
    * Merges ``custom_properties`` into ``Contact.custom_properties``
      under the module-namespaced bucket inferred from ``module_tag``.
    * Returns the contact with its FK ``id`` populated (a
      ``session.flush()`` is issued for fresh rows so the caller can
      assign ``lead.contact_id = contact.id`` immediately).

    The caller is responsible for the actual commit — this function
    never commits.
    """
    normalised_email = (email or "").strip().lower() or None
    contact = await _find_contact_by_email(session, normalised_email, tenant_id=tenant_id) if normalised_email else None

    if contact is None:
        first, last = _split_full_name(full_name)
        contact = Contact(
            contact_type=contact_type,
            first_name=first,
            last_name=last,
            primary_email=normalised_email,
            primary_phone=(phone or None),
            module_tags=[module_tag],
            custom_properties=({module_tag.split("_", 1)[0]: custom_properties} if custom_properties else {}),
            tenant_id=tenant_id,
            created_by=tenant_id,
        )
        session.add(contact)
        # Flush so ``contact.id`` is populated for the immediate FK
        # assignment the caller will perform.
        await session.flush()
        logger.info("Contact bridge: created contact %s for %s tag", contact.id, module_tag)
        return contact

    # Existing contact — append the tag idempotently and update phone/
    # name when the contact's slot is empty (don't clobber a richer
    # canonical row with a sparse Lead/Buyer form). The Contact stays
    # the source of truth for fields it already owns.
    changed = _add_tag(contact, module_tag)

    if not contact.first_name and not contact.last_name and full_name:
        first, last = _split_full_name(full_name)
        contact.first_name = first
        contact.last_name = last
        changed = True
    if phone and not contact.primary_phone:
        contact.primary_phone = phone
        changed = True
    if custom_properties:
        bucket = module_tag.split("_", 1)[0]
        merged = dict(contact.custom_properties or {})
        existing_bucket = dict(merged.get(bucket) or {})
        existing_bucket.update(custom_properties)
        merged[bucket] = existing_bucket
        contact.custom_properties = merged
        changed = True

    if changed:
        await session.flush()
        logger.info(
            "Contact bridge: linked existing contact %s with tag %s",
            contact.id,
            module_tag,
        )
    return contact


async def ensure_contact_for_lead(
    session: AsyncSession,
    lead: Lead,
    *,
    tenant_id: str | None,
) -> Contact:
    """Find-or-create the contact for a Lead and link it.

    Side-effect: sets ``lead.contact_id`` to the resolved contact's id.
    The caller commits.
    """
    contact = await ensure_contact_for_person(
        session,
        full_name=lead.full_name,
        email=lead.email,
        phone=lead.phone,
        contact_type="lead",
        module_tag=PROPERTY_DEV_LEAD_TAG,
        tenant_id=tenant_id,
        custom_properties=None,
    )
    lead.contact_id = contact.id
    return contact


async def ensure_contact_for_buyer(
    session: AsyncSession,
    buyer: Buyer,
    *,
    tenant_id: str | None,
) -> Contact:
    """Find-or-create the contact for a Buyer and link it.

    Side-effect: sets ``buyer.contact_id`` to the resolved contact's id.
    The caller commits.
    """
    contact = await ensure_contact_for_person(
        session,
        full_name=buyer.full_name,
        email=buyer.email,
        phone=buyer.phone,
        contact_type="customer",
        module_tag=PROPERTY_DEV_BUYER_TAG,
        tenant_id=tenant_id,
        custom_properties=None,
    )
    buyer.contact_id = contact.id
    return contact


async def mirror_lead_fields_to_contact(
    session: AsyncSession,
    lead: Lead,
) -> Contact | None:
    """Mirror Lead canonical fields (name/email/phone) back to the Contact.

    Called from ``PropertyDevService.update_lead`` after the Lead row is
    persisted. The Contact remains the canonical store, but we keep it
    in sync with the latest Lead form input — otherwise the user edits
    the Lead's name on the PropDev tab and the Contacts module still
    shows the old one.

    Returns the Contact (or None if no link exists).
    """
    if lead.contact_id is None:
        return None
    contact = await session.get(Contact, lead.contact_id)
    if contact is None:
        return None

    changed = False
    if lead.email:
        normalised = lead.email.strip().lower() or None
        if normalised and contact.primary_email != normalised:
            contact.primary_email = normalised
            changed = True
    if lead.phone is not None and contact.primary_phone != lead.phone:
        contact.primary_phone = lead.phone or None
        changed = True
    if lead.full_name:
        first, last = _split_full_name(lead.full_name)
        current_full = _join_name(contact.first_name, contact.last_name)
        if current_full != lead.full_name.strip():
            contact.first_name = first
            contact.last_name = last
            changed = True
    if changed:
        await session.flush()
    return contact


async def mirror_buyer_fields_to_contact(
    session: AsyncSession,
    buyer: Buyer,
) -> Contact | None:
    """Mirror Buyer canonical fields (name/email/phone) back to the Contact."""
    if buyer.contact_id is None:
        return None
    contact = await session.get(Contact, buyer.contact_id)
    if contact is None:
        return None

    changed = False
    if buyer.email:
        normalised = buyer.email.strip().lower() or None
        if normalised and contact.primary_email != normalised:
            contact.primary_email = normalised
            changed = True
    if buyer.phone is not None and contact.primary_phone != buyer.phone:
        contact.primary_phone = buyer.phone or None
        changed = True
    if buyer.full_name:
        first, last = _split_full_name(buyer.full_name)
        current_full = _join_name(contact.first_name, contact.last_name)
        if current_full != buyer.full_name.strip():
            contact.first_name = first
            contact.last_name = last
            changed = True
    if changed:
        await session.flush()
    return contact


# ── Reverse lookups (Contact → module rows) ─────────────────────────


async def list_module_rows_for_contact(
    session: AsyncSession,
    contact_id: uuid.UUID,
) -> dict[str, list[dict[str, Any]]]:
    """Return a summary of every module row linked to ``contact_id``.

    The shape is::

        {
          "property_dev_leads":  [{"id": ..., "status": ..., "score": ...}, ...],
          "property_dev_buyers": [{"id": ..., "status": ..., "contract_value": ...}, ...],
        }

    Used by the contact-detail drawer to render the "Linked records"
    section. Future modules (broker, vendor, subcontractor) extend this
    dict — keep the keys stable so the frontend can switch on them.

    Cross-module imports live inside the function so the contacts
    module stays importable without property_dev loaded.
    """
    # Local import: contacts is a more foundational module than
    # property_dev — keep the dependency arrow pointing the right way.
    from app.modules.property_dev.models import Buyer as PdBuyer
    from app.modules.property_dev.models import Lead as PdLead

    leads_stmt = select(PdLead).where(PdLead.contact_id == contact_id)
    buyers_stmt = select(PdBuyer).where(PdBuyer.contact_id == contact_id)

    leads = (await session.execute(leads_stmt)).scalars().all()
    buyers = (await session.execute(buyers_stmt)).scalars().all()

    return {
        "property_dev_leads": [
            {
                "id": str(lead.id),
                "development_id": (str(lead.development_id) if lead.development_id else None),
                "source": lead.source,
                "status": lead.status,
                "lead_score": float(lead.lead_score or 0),
                "full_name": lead.full_name,
                "email": lead.email,
                "created_at": (lead.created_at.isoformat() if lead.created_at else None),
            }
            for lead in leads
        ],
        "property_dev_buyers": [
            {
                "id": str(b.id),
                "development_id": (str(b.development_id) if b.development_id else None),
                "plot_id": str(b.plot_id) if b.plot_id else None,
                "status": b.status,
                "contract_value": float(b.contract_value or 0),
                "currency": b.currency,
                "full_name": b.full_name,
                "email": b.email,
                "created_at": (b.created_at.isoformat() if b.created_at else None),
            }
            for b in buyers
        ],
    }
