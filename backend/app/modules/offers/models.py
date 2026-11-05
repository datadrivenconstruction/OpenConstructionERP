"""Customer offer ORM models.

Tables:
    oe_offers_offer - an issued document: number, revision, frozen lines, totals, texts and the draft
        instalments. One row per revision; revisions of one offer share ``group_id`` and ``number``.
    oe_offers_text_block - the text library: company scope, with a project override.
    oe_offers_settings - one row of company defaults: number pattern, validity, payment days, templates.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

OFFER_STATUSES = ("draft", "sent", "accepted", "declined", "expired", "superseded")


class Offer(Base):
    """One revision of a customer offer.

    A draft is re-priced from the BOQ on every save. From ``sent`` on the row is frozen: number,
    revision, prices and texts never change, and a BOQ edit makes the next revision instead.
    ``boq_id`` is a bare indexed GUID so deleting an estimate never cascades away what a customer
    holds. The customer and site addresses are snapshots for the same reason.
    """

    __tablename__ = "oe_offers_offer"
    __table_args__ = (
        UniqueConstraint("number", "revision", name="uq_offers_offer_number_revision"),
        Index("ix_offers_offer_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    revision: Mapped[str] = mapped_column(String(4), nullable=False, default="A", server_default="A")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")

    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    customer_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="business", server_default="business"
    )
    customer: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    site_address: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    site_same_as_billing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    pack_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default="en")
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="Offer", server_default="Offer")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    tax_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="standard", server_default="standard")
    tax_rate: Mapped[str] = mapped_column(String(12), nullable=False, default="0", server_default="0")
    tax_label: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")

    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    validity_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    contact_person: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    licence_number: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")

    markup_presentation: Mapped[str] = mapped_column(
        String(10), nullable=False, default="spread", server_default="spread"
    )
    options: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    lines: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    totals: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    estimate_net: Mapped[str] = mapped_column(String(40), nullable=False, default="0", server_default="0")
    texts: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    instalments: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    schedule: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    retention_percent: Mapped[str] = mapped_column(String(12), nullable=False, default="0", server_default="0")
    advance_security: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    boq_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_options: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<Offer {self.number} {self.revision} {self.status}>"


class OfferTextBlock(Base):
    """A reusable text of one kind in one language, company-wide or for a single project."""

    __tablename__ = "oe_offers_text_block"
    __table_args__ = (Index("ix_offers_text_scope_kind", "scope", "project_id", "kind"),)

    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="company", server_default="company")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default="en")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    pack_key: Mapped[str | None] = mapped_column(String(20), nullable=True)

    def __repr__(self) -> str:
        return f"<OfferTextBlock {self.scope}/{self.kind}/{self.language}>"


class OfferSettings(Base):
    """Company defaults for offers. One row, key ``default``."""

    __tablename__ = "oe_offers_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_offers_settings_key"),)

    key: Mapped[str] = mapped_column(String(20), nullable=False, default="default", server_default="default")
    number_pattern: Mapped[str] = mapped_column(
        String(60), nullable=False, default="OF-{YYYY}-{seq:3}", server_default="OF-{YYYY}-{seq:3}"
    )
    validity_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    markup_presentation: Mapped[str] = mapped_column(
        String(10), nullable=False, default="spread", server_default="spread"
    )
    schedule_templates: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    default_schedule: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    texts_seeded_for: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
