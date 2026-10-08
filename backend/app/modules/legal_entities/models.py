# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legal entity and branch ORM models.

Tables:
    oe_legal_entities_entity - one company in the group: the registered name,
        the country whose law it answers to, and the currency its books are
        kept in.
    oe_legal_entities_branch - an establishment of one entity, which may sit
        in another country (a foreign branch) but books in its entity.

A construction group trades through several companies, each with its own
country, functional currency, document numbering and taxes. This is the
structure those later pieces hang off. It is part of the core product on
purpose: numbering, tax and stock all read the owning entity, and a module that
had to work both with and without entities would be written twice.

The rows are install-wide, like the company profile, and written by admins.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class LegalEntity(Base):
    """A company of the group, with the country and currency its books follow."""

    __tablename__ = "oe_legal_entities_entity"
    __table_args__ = (UniqueConstraint("code", name="uq_oe_legal_entities_entity_code"),)

    #: Short code the group uses for the company, e.g. ``DE01``. Unique.
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Registered name as it appears on the company's documents.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: ISO 3166-1 alpha-2 of the country the company is registered in.
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    #: ISO 3166-2 where a state or province registers companies, else NULL.
    subdivision_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    #: ISO 4217 code of the currency the company keeps its books in.
    functional_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: Commercial register number, as written by the registry.
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: VAT, GST or other tax identifier, as written by the tax authority.
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: The entity a document falls back to when nothing names one. At most one.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    branches: Mapped[list[Branch]] = relationship(
        back_populates="legal_entity",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Branch.code",
    )

    def __repr__(self) -> str:
        return f"<LegalEntity {self.code} {self.country_code} {self.functional_currency}>"


class Branch(Base):
    """An establishment of one legal entity: a regional office, a site office, a foreign branch."""

    __tablename__ = "oe_legal_entities_branch"
    __table_args__ = (
        UniqueConstraint("legal_entity_id", "code", name="uq_oe_legal_entities_branch_entity_code"),
        Index("ix_oe_legal_entities_branch_entity", "legal_entity_id"),
    )

    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_legal_entities_entity.id", ondelete="CASCADE"), nullable=False
    )
    #: Short code, unique within the entity.
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: ISO 3166-1 alpha-2 where the branch is. May differ from its entity's.
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    subdivision_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    legal_entity: Mapped[LegalEntity] = relationship(back_populates="branches", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<Branch {self.code} of {self.legal_entity_id}>"
