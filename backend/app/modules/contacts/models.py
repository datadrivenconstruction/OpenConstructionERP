# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contacts ORM models.

Tables:
    oe_contacts_contact - unified contacts directory
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

    # ── Module bridge ──────────────────────────────────────────────
    # ``module_tags`` records which modules this contact participates
    # in. Multi-valued (a single contact may be a ``property_dev_lead``
    # AND a ``property_dev_buyer`` AND a ``broker`` simultaneously) so
    # we store it as a JSON list of opaque short identifiers. The
    # canonical set is maintained in ``app.modules.contacts.bridge``;
    # third-party modules add their own tag values without a registry
    # update.
    module_tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # ``custom_properties`` is a dict keyed by module name where each
    # module stores optional extension fields that don't justify a real
    # column on the Contact table. Example payload::
    #
    #   {
    #     "property_dev": {"preferred_contact_method": "email"},
    #     "crm":         {"acquisition_campaign": "spring2026"},
    #   }
    #
    # Modules MUST namespace their bucket under their own module name
    # to avoid key collisions.
    custom_properties: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Tenant scoping. In single-tenant installs this equals the creator's
    # user id - contacts are siloed per user. Introduced in v2.3.1 to
    # replace the ``created_by`` IDOR proxy: ``created_by`` remains as an
    # audit field (who inserted the row), ``tenant_id`` is the access
    # gate. Indexed so the list endpoint stays O(log n) at scale.
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Indexed for the same reason ``tenant_id`` is, and it has to be: the
    # scope clause is ``tenant_id = ? OR created_by = ?`` for rows written
    # before the v2.3.1 backfill, and PostgreSQL can only combine the two
    # branches into a BitmapOr when BOTH are indexed. With one side missing
    # the planner dropped to a sequential scan for the whole clause.
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
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
