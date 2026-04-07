"""Contacts data access layer.

All database queries for contacts live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact


class ContactRepository:
    """Data access for Contact model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, contact_id: uuid.UUID) -> Contact | None:
        """Get contact by ID."""
        return await self.session.get(Contact, contact_id)

    async def get_by_email(self, email: str) -> Contact | None:
        """Get contact by primary email."""
        stmt = select(Contact).where(Contact.primary_email == email.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        contact_type: str | None = None,
        country_code: str | None = None,
        search: str | None = None,
        is_active: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Contact], int]:
        """List contacts with filters and pagination.

        Returns (contacts, total_count).
        """
        base = select(Contact).where(Contact.is_active == is_active)

        if contact_type is not None:
            base = base.where(Contact.contact_type == contact_type)
        if country_code is not None:
            base = base.where(Contact.country_code == country_code)
        if search is not None:
            term = f"%{search}%"
            base = base.where(
                or_(
                    Contact.first_name.ilike(term),
                    Contact.last_name.ilike(term),
                    Contact.company_name.ilike(term),
                    Contact.primary_email.ilike(term),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Contact.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        contacts = list(result.scalars().all())

        return contacts, total

    async def create(self, contact: Contact) -> Contact:
        """Insert a new contact."""
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def update(self, contact_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a contact."""
        stmt = update(Contact).where(Contact.id == contact_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def count(self, contact_type: str | None = None) -> int:
        """Count contacts, optionally filtered by type."""
        base = select(func.count()).select_from(Contact)
        if contact_type is not None:
            base = select(func.count()).select_from(
                select(Contact).where(Contact.contact_type == contact_type).subquery()
            )
        return (await self.session.execute(base)).scalar_one()
