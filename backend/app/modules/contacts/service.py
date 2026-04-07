"""Contacts service — business logic for contact management.

Stateless service layer. Handles:
- Contact CRUD
- Search across name, company, email
- Soft-delete (deactivate)
"""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import ContactCreate, ContactUpdate

logger = logging.getLogger(__name__)


class ContactService:
    """Business logic for contact operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ContactRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_contact(
        self,
        data: ContactCreate,
        user_id: str | None = None,
    ) -> Contact:
        """Create a new contact."""
        contact = Contact(
            contact_type=data.contact_type,
            is_platform_user=data.is_platform_user,
            user_id=data.user_id,
            first_name=data.first_name,
            last_name=data.last_name,
            company_name=data.company_name,
            legal_name=data.legal_name,
            vat_number=data.vat_number,
            country_code=data.country_code,
            address=data.address,
            primary_email=data.primary_email.lower() if data.primary_email else None,
            primary_phone=data.primary_phone,
            website=data.website,
            certifications=data.certifications,
            insurance=data.insurance,
            prequalification_status=data.prequalification_status,
            qualified_until=data.qualified_until,
            payment_terms_days=data.payment_terms_days,
            currency_code=data.currency_code,
            name_translations=data.name_translations,
            notes=data.notes,
            created_by=user_id,
            metadata_=data.metadata,
        )
        contact = await self.repo.create(contact)
        label = data.company_name or f"{data.first_name or ''} {data.last_name or ''}".strip()
        logger.info("Contact created: %s (%s)", label, data.contact_type)
        return contact

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_contact(self, contact_id: uuid.UUID) -> Contact:
        """Get contact by ID. Raises 404 if not found."""
        contact = await self.repo.get(contact_id)
        if contact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )
        return contact

    async def get_by_email(self, email: str) -> Contact | None:
        """Get contact by primary email."""
        return await self.repo.get_by_email(email)

    async def list_contacts(
        self,
        *,
        contact_type: str | None = None,
        country_code: str | None = None,
        search: str | None = None,
        is_active: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Contact], int]:
        """List contacts with filters."""
        return await self.repo.list(
            contact_type=contact_type,
            country_code=country_code,
            search=search,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_contact(
        self,
        contact_id: uuid.UUID,
        data: ContactUpdate,
    ) -> Contact:
        """Update contact fields."""
        contact = await self.get_contact(contact_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Normalise email to lowercase
        if "primary_email" in fields and fields["primary_email"] is not None:
            fields["primary_email"] = fields["primary_email"].lower()

        if not fields:
            return contact

        await self.repo.update(contact_id, **fields)
        updated = await self.repo.get(contact_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )

        logger.info("Contact updated: %s (fields=%s)", contact_id, list(fields.keys()))
        return updated

    # ── Soft delete ───────────────────────────────────────────────────────

    async def deactivate_contact(self, contact_id: uuid.UUID) -> None:
        """Soft-delete a contact (set is_active=False)."""
        await self.get_contact(contact_id)  # Raises 404 if not found
        await self.repo.update(contact_id, is_active=False)
        logger.info("Contact deactivated: %s", contact_id)

    # ── Count ─────────────────────────────────────────────────────────────

    async def count_contacts(self, contact_type: str | None = None) -> int:
        """Count contacts, optionally by type."""
        return await self.repo.count(contact_type=contact_type)
