# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes for the standing e-invoice configuration.

Validated here rather than at the screen, because the screen is one caller. The
rules are the ones a receiver would apply to the finished document, moved to the
point where the user can still see the field they are typing in.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.modules.einvoice.bank import (
    InvalidBankDetail,
    iban_countries,
    normalise_payment_account,
    normalise_payment_provider,
)
from app.modules.einvoice.rules import DIRECT_DEBIT_CODES, PAYMENT_CARD_CODES, UNTDID_4461_CODES

__all__ = ["EInvoiceSettingsRead", "EInvoiceSettingsUpdate"]

_COUNTRY = re.compile(r"^[A-Z]{2}$")
# BT-31. Two letters for the country then the registration itself; the national
# formats differ too much to check further without a table per country, and a
# table that is wrong refuses a valid registration.
_VAT_ID = re.compile(r"^[A-Z]{2}[A-Z0-9 .\-]{2,18}$")
# ISO 6523 scheme identifier for BT-34, e.g. 0204 for the German Leitweg-ID.
_EAS_SCHEME = re.compile(r"^[0-9]{4}$")


class _StoredFields(BaseModel):
    """The fields the row holds, carrying the lengths of their columns and nothing else.

    Split out from the rules below so that reading can never be refused by a rule
    that governs writing. The lengths stay here because a column enforces them
    either way, so they describe the row rather than judge it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    seller_name: str = Field(default="", max_length=200)
    seller_vat_id: str = Field(default="", max_length=50, examples=["DE123456789"])
    seller_tax_number: str = Field(default="", max_length=50)
    seller_legal_id: str = Field(default="", max_length=50)
    seller_country_code: str = Field(default="", max_length=2, examples=["DE"])
    seller_line1: str = Field(default="", max_length=200)
    seller_postcode: str = Field(default="", max_length=20)
    seller_city: str = Field(default="", max_length=100)
    seller_email: str = Field(default="", max_length=200)
    seller_contact_name: str = Field(default="", max_length=200)
    seller_contact_phone: str = Field(default="", max_length=50, examples=["+49 30 123456"])
    seller_contact_email: str = Field(default="", max_length=200)
    seller_electronic_address: str = Field(default="", max_length=200)
    seller_electronic_address_scheme: str = Field(default="", max_length=20, examples=["0204"])

    payee_iban: str = Field(default="", max_length=34, examples=["DE02120300000000202051"])
    payee_bic: str = Field(default="", max_length=11, examples=["COBADEFFXXX"])
    payee_account_name: str = Field(default="", max_length=200)
    payment_means_code: str = Field(default="", max_length=4, examples=["30"])
    payment_terms: str = Field(default="", max_length=500)


class EInvoiceSettingsUpdate(_StoredFields):
    """What a user may set. Every field optional: a half-filled form is normal.

    These rules run on the way in, where the user is still looking at the field
    and can correct it. They deliberately do not run on the way out, because a
    row that somehow holds a bad value has to stay readable: this screen is the
    only place that value can be fixed, and a screen that refuses to open on
    exactly the data it exists to repair is the dead end again.
    """

    @field_validator("seller_country_code")
    @classmethod
    def _check_country(cls, v: str) -> str:
        """BR-9: the seller's country is what decides which national rules apply."""
        if not v:
            return ""
        code = v.strip().upper()
        if not _COUNTRY.match(code):
            raise ValueError(f"country must be a two-letter ISO 3166-1 code such as DE, got {v!r}")
        return code

    @field_validator("seller_vat_id")
    @classmethod
    def _check_vat_id(cls, v: str) -> str:
        if not v:
            return ""
        vat = v.strip().upper()
        if not _VAT_ID.match(vat):
            raise ValueError(
                f"a VAT identifier starts with the two-letter country code and its registration, got {v!r}"
            )
        return vat

    @field_validator("payee_iban")
    @classmethod
    def _check_iban(cls, v: str, info: ValidationInfo) -> str:
        """BT-84. The one field on this screen no later step can check.

        The seller's country decides what may be stored, so this reads it back
        out of ``info.data``. That works because ``seller_country_code`` is
        declared before this field on ``_StoredFields`` and pydantic validates
        in declaration order; a value the country validator has already refused
        is simply absent, and an absent country is the permissive case anyway.
        """
        try:
            return normalise_payment_account(v, country=info.data.get("seller_country_code", ""), allow_empty=True)
        except InvalidBankDetail as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("payee_bic")
    @classmethod
    def _check_bic(cls, v: str, info: ValidationInfo) -> str:
        try:
            return normalise_payment_provider(v, country=info.data.get("seller_country_code", ""), allow_empty=True)
        except InvalidBankDetail as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("payment_means_code")
    @classmethod
    def _check_means_code(cls, v: str) -> str:
        """BT-81, checked against the code list and against what we can write.

        Two separate refusals, because they fail for different reasons. A value
        outside UNTDID 4461 is not a payment means at all. A card or direct-debit
        code is a real one, but it obliges the document to carry BG-18 or BG-19,
        and this platform writes neither, so accepting it here would store a
        setting whose only effect is a rejected invoice (BR-DE-24-a, BR-DE-25-a).
        """
        if not v:
            return ""
        code = v.strip().upper()
        if code not in UNTDID_4461_CODES:
            raise ValueError(f"a payment means code is a UNTDID 4461 value such as 30 or 58, got {v!r}")
        if code in PAYMENT_CARD_CODES or code in DIRECT_DEBIT_CODES:
            raise ValueError(
                f"payment means {code} needs card or direct-debit details this platform cannot write yet; "
                "use a credit transfer code such as 30 or 58"
            )
        return code

    @field_validator("seller_electronic_address_scheme")
    @classmethod
    def _check_eas(cls, v: str) -> str:
        if not v:
            return ""
        scheme = v.strip()
        if not _EAS_SCHEME.match(scheme):
            raise ValueError(f"an electronic address scheme is a four-digit ISO 6523 code such as 0204, got {v!r}")
        return scheme


class EInvoiceSettingsRead(_StoredFields):
    """What is stored, plus what the screen needs to explain itself.

    ``complete`` answers the question the user actually has, which is whether
    filling this in was enough. It is deliberately not a compliance verdict on
    any invoice: an invoice still has to name its buyer and its buyer reference,
    and only the panel on the invoice can say whether it did.
    """

    complete: bool = False
    missing: list[str] = Field(default_factory=list)
    #: The countries whose sellers are paid through an IBAN, sent so the screen
    #: can label the account field for the country the user is typing rather
    #: than for the language they read. It is served rather than held on the
    #: client because there must be one copy of this list, and the copy that
    #: decides what may be saved is the one in ``bank.py``. A client list would
    #: be a second, and the two would part company the day the registry moves.
    iban_countries: list[str] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: Any) -> EInvoiceSettingsRead:
        stored = {name: getattr(row, name, "") or "" for name in _StoredFields.model_fields}
        missing = [f for f in ("seller_name", "seller_country_code") if not stored.get(f)]
        # A seller must be identified for tax either way round (BR-CO-26).
        if not (stored.get("seller_vat_id") or stored.get("seller_tax_number") or stored.get("seller_legal_id")):
            missing.append("seller_vat_id")
        missing += _german_gaps(stored)
        return cls(**stored, complete=not missing, missing=missing, iban_countries=iban_countries())


#: Fields XRechnung needs that EN 16931 does not, reported on the settings screen
#: rather than only on a finished invoice. The configuration cannot know which
#: profile a future document will use, so this advises on the country it is
#: filed under, which is the one signal it does have.
_DE_REQUIRED_CONTACT_FIELDS = ("seller_contact_name", "seller_contact_phone", "seller_contact_email")


def _german_gaps(stored: dict[str, str]) -> list[str]:
    """The XRechnung-only gaps in a German seller's configuration.

    Advice, not a verdict: an invoice is judged by the rules engine against the
    profile it is actually exported as. This exists so the four fatal findings
    BR-DE-2/5/6/7 and BR-DE-16 would raise are visible on the one screen that
    can clear them, before anybody has tried to send anything.
    """
    if (stored.get("seller_country_code") or "").upper() != "DE":
        return []
    gaps = [
        f
        for f in _DE_REQUIRED_CONTACT_FIELDS
        if not stored.get(f) and not (f.endswith("email") and stored.get("seller_email"))
    ]
    # BR-DE-16 is stricter than BR-CO-26: a company registration number is not a
    # tax registration, so it does not answer this one.
    if not (stored.get("seller_vat_id") or stored.get("seller_tax_number")):
        gaps.append("seller_tax_number")
    return gaps
