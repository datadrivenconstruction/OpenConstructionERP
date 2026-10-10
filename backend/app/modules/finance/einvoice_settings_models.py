# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The standing e-invoice configuration for this instance.

Tables:
    oe_finance_einvoice_settings - seller identity and bank account, one row

Seller identity, the tax registration behind it and the account a buyer pays
into are properties of the company running the instance. They are identical on
every invoice it issues, so holding them on each invoice means retyping a legal
identity per document and getting it wrong somewhere.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# The single row's key. There is no organisation table in the platform, and
# seller identity is not per user and not per project, so one row it is. The
# column exists rather than being implied so that a future per-organisation
# split fills it in instead of reshaping the table.
DEFAULT_SCOPE = "default"

# Party fields, named exactly as ``_coerce_party`` reads them so the column name
# and the business term stay one thing. Anything added here reaches the document
# through ``as_defaults`` with no second edit, and the parity test enforces it.
_SELLER_FIELDS = (
    "name",
    "vat_id",
    "tax_number",
    "legal_id",
    "tax_office",
    "country_code",
    "line1",
    "postcode",
    "city",
    "contact_name",
    "contact_phone",
    "contact_email",
    "electronic_address",
    "electronic_address_scheme",
)

#: ``seller_email`` predates the contact group and always held the address a
#: person reads, which is BT-43. It is not in ``_SELLER_FIELDS`` because the
#: party field it feeds is now named ``contact_email``, and it is not dropped
#: because instances have real addresses stored in it. The newer column wins
#: where both are set.
_LEGACY_CONTACT_EMAIL_COLUMN = "seller_email"

# Settlement fields, named as ``build_einvoice`` reads them out of
# ``metadata.einvoice`` for the same reason: the column, the business term and
# the key on the invoice are one name, so no mapping table can fall behind.
_PAYMENT_FIELDS = (
    "payee_iban",
    "payee_bic",
    "payee_account_name",
    "payment_means_code",
    "payment_terms",
)


class EInvoiceSettings(Base):
    """Seller identity and payment details every e-invoice from this instance carries.

    Every column is nullable and defaults to empty. A half-filled configuration
    is the normal state on the way to a complete one, and refusing to store it
    would mean the screen could not be left until the user had found their
    company registration number.
    """

    __tablename__ = "oe_finance_einvoice_settings"
    __table_args__ = (UniqueConstraint("scope", name="uq_oe_finance_einvoice_settings_scope"),)

    scope: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=DEFAULT_SCOPE,
        server_default=DEFAULT_SCOPE,
        index=True,
    )

    # Seller trade party (BG-4).
    seller_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    seller_vat_id: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    seller_tax_number: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    seller_legal_id: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    # The tax office the seller is registered with. A first-class part of a
    # party's tax identity where an invoice names it beside the tax number
    # (the Turkish vergi dairesi, written as PartyTaxScheme/TaxScheme/Name).
    # The EN 16931 party has no such term and ignores it.
    seller_tax_office: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    seller_country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="", server_default="")
    seller_line1: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    seller_postcode: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    seller_city: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    seller_email: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    # BG-6 SELLER CONTACT. XRechnung makes the group and all three of its fields
    # mandatory (BR-DE-2, BR-DE-5, BR-DE-6, BR-DE-7), and none of them is invoice
    # data: they name the person a buyer rings about this company's invoices.
    seller_contact_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    seller_contact_phone: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    seller_contact_email: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    # BT-34, the address a network delivers to, and the scheme that reads it.
    seller_electronic_address: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    seller_electronic_address_scheme: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", server_default=""
    )

    # Settlement (BG-16 payment instructions, BT-20 payment terms).
    payee_iban: Mapped[str] = mapped_column(String(34), nullable=False, default="", server_default="")
    payee_bic: Mapped[str] = mapped_column(String(11), nullable=False, default="", server_default="")
    payee_account_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    payment_means_code: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    payment_terms: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")

    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def as_defaults(self) -> dict[str, Any]:
        """Render the configuration in the shape ``build_einvoice`` merges.

        The keys are the ones an invoice would carry under
        ``metadata.einvoice``, so a value configured here and a value typed onto
        an invoice are the same field and the merge can prefer one over the
        other. Empty strings are dropped rather than sent as blanks, because an
        unset field must leave the invoice's own value alone.
        """
        seller = {f: getattr(self, f"seller_{f}") for f in _SELLER_FIELDS if getattr(self, f"seller_{f}")}
        legacy_email = getattr(self, _LEGACY_CONTACT_EMAIL_COLUMN, "")
        if legacy_email and not seller.get("contact_email"):
            seller["contact_email"] = legacy_email
        result: dict[str, Any] = {"seller": seller} if seller else {}
        result.update({f: getattr(self, f) for f in _PAYMENT_FIELDS if getattr(self, f)})
        return result

    def __repr__(self) -> str:
        return f"<EInvoiceSettings {self.scope} seller={self.seller_name!r}>"
