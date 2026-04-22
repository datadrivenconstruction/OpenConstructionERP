"""Contacts ORM models.

Tables:
    oe_contacts_contact — unified contacts directory
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Contact(Base):
    """A contact entry: client, subcontractor, supplier, consultant, or internal."""

    __tablename__ = "oe_contacts_contact"

    contact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_platform_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Name
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Company
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vat_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Location
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )

    # Contact info
    primary_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    primary_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Qualifications
    certifications: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    insurance: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    prequalification_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    qualified_until: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Financial
    payment_terms_days: Mapped[str | None] = mapped_column(String(10), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # i18n
    name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )

    # General
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Tenant scoping. In single-tenant installs this equals the creator's
    # user id — contacts are siloed per user. Introduced in v2.3.1 to
    # replace the ``created_by`` IDOR proxy: ``created_by`` remains as an
    # audit field (who inserted the row), ``tenant_id`` is the access
    # gate. Indexed so the list endpoint stays O(log n) at scale.
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        label = self.company_name or f"{self.first_name or ''} {self.last_name or ''}".strip()
        return f"<Contact {label} ({self.contact_type})>"
