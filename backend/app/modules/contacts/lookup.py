# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resolve a contact picked in another module as the person responsible.

The schedule's activity assignee and the task assignee both store a contact
id chosen from the contacts list. Both have to accept exactly the contacts
that list shows the caller, or a module becomes a way to name, and read the
name of, a contact of another tenant. The scope is the list's own
(:func:`app.modules.contacts.repository._tenant_scope`: ``tenant_id``, falling
back to ``created_by``), with admins seeing every contact.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact


def contact_display_name(contact: Contact) -> str:
    """The person's name, else the company, else the email."""
    person = " ".join(p for p in (contact.first_name, contact.last_name) if p)
    return person or contact.company_name or contact.primary_email or ""


async def _is_admin(session: AsyncSession, actor_id: str) -> bool:
    """Read the role from the users table; a token can outlive a demotion."""
    from app.modules.users.models import User

    try:
        uid = uuid.UUID(str(actor_id))
    except (ValueError, TypeError):
        return False
    return await session.scalar(select(User.role).where(User.id == uid)) == "admin"


async def assignable_contact(session: AsyncSession, contact_id: uuid.UUID, actor_id: str | None) -> Contact:
    """Return the contact if the caller may assign it, else raise.

    Args:
        session: Database session.
        contact_id: The contact being assigned.
        actor_id: The caller; None skips the tenant scope (internal callers).

    Raises:
        HTTPException 404 when the contact does not exist or belongs to
        another tenant (the same answer, so ids cannot be probed); 422 when it
        has been deactivated.
    """
    contact = await session.get(Contact, contact_id)
    if contact is not None and actor_id is not None and not await _is_admin(session, actor_id):
        owner = str(actor_id)
        if str(contact.tenant_id or "") != owner and str(contact.created_by or "") != owner:
            contact = None
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee contact not found")
    if not contact.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Assignee contact is deactivated",
        )
    return contact
