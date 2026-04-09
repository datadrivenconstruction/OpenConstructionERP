"""Contacts service — business logic for contact management.

Stateless service layer. Handles:
- Contact CRUD
- Search across name, company, email
- Soft-delete (deactivate)
- Email format validation and duplicate detection
"""

import logging
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import ContactCreate, ContactUpdate

logger = logging.getLogger(__name__)
_logger_audit = logging.getLogger(__name__ + ".audit")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _safe_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Best-effort audit log — never blocks the caller on failure."""
    try:
        from app.core.audit import audit_log

        await audit_log(
            session,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            details=details,
        )
    except Exception:
        _logger_audit.debug("Audit log write skipped for %s %s", action, entity_type)


def _validate_email_format(email: str | None) -> None:
    """Validate email format. Raises 400 if invalid."""
    if email is not None and not _EMAIL_RE.match(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid email format: {email}",
        )


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
        """Create a new contact.

        Validates email format and checks for duplicate emails among active contacts.
        """
        # Validate email format
        _validate_email_format(data.primary_email)

        # Check for duplicate email among active contacts
        normalised_email = data.primary_email.lower() if data.primary_email else None
        if normalised_email:
            existing = await self.repo.get_by_email(normalised_email)
            if existing is not None and existing.is_active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"A contact with email '{normalised_email}' already exists "
                        f"(id={existing.id})."
                    ),
                )

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
            primary_email=normalised_email,
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

        await _safe_audit(
            self.session,
            action="create",
            entity_type="contact",
            entity_id=str(contact.id),
            user_id=user_id,
            details={"company_name": label, "contact_type": data.contact_type},
        )

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
        """Update contact fields.

        Validates email format and checks for duplicate emails on update.
        """
        contact = await self.get_contact(contact_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Validate and normalise email if being updated
        if "primary_email" in fields and fields["primary_email"] is not None:
            _validate_email_format(fields["primary_email"])
            fields["primary_email"] = fields["primary_email"].lower()

            # Check for duplicate email (skip if it's the same contact)
            existing = await self.repo.get_by_email(fields["primary_email"])
            if existing is not None and existing.id != contact_id and existing.is_active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"A contact with email '{fields['primary_email']}' already exists "
                        f"(id={existing.id})."
                    ),
                )
        elif "primary_email" in fields:
            # Explicitly setting to None is OK (clearing the email)
            pass

        if not fields:
            return contact

        await self.repo.update(contact_id, **fields)
        updated = await self.repo.get(contact_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )

        await _safe_audit(
            self.session,
            action="update",
            entity_type="contact",
            entity_id=str(contact_id),
            details={"updated_fields": list(fields.keys())},
        )

        logger.info("Contact updated: %s (fields=%s)", contact_id, list(fields.keys()))
        return updated

    # ── Soft delete ───────────────────────────────────────────────────────

    async def deactivate_contact(self, contact_id: uuid.UUID) -> None:
        """Soft-delete a contact (set is_active=False)."""
        await self.get_contact(contact_id)  # Raises 404 if not found
        await self.repo.update(contact_id, is_active=False)
        await _safe_audit(
            self.session,
            action="delete",
            entity_type="contact",
            entity_id=str(contact_id),
            details={},
        )

        logger.info("Contact deactivated: %s", contact_id)

    # ── Count ─────────────────────────────────────────────────────────────

    async def count_contacts(self, contact_type: str | None = None) -> int:
        """Count contacts, optionally by type."""
        return await self.repo.count(contact_type=contact_type)

    # ── Stats ────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        """Return aggregate contact statistics."""
        return await self.repo.stats()

    # ── By Company ───────────────────────────────────────────────────────

    async def list_by_company(
        self,
        company_name: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Contact], int]:
        """List contacts grouped by company name."""
        return await self.repo.list_by_company(
            company_name,
            limit=limit,
            offset=offset,
        )
