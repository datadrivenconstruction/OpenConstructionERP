# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Turkish e-invoice fields of one invoice: ``metadata.einvoice.tr``.

A namespaced block inside the e-invoice metadata rather than new columns: the
fields below mean something only on an e-Fatura / e-Arşiv Fatura, and an
invoice issued anywhere else never carries them.

It is the one part of ``metadata.einvoice`` that is validated when it is
written. The EN 16931 keys beside it stay as free as they were, because
existing invoices carry them in shapes nobody ever policed. A new block has no
such history, so a mistyped key is refused at the moment it is typed instead
of being stored and silently ignored by the export.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.einvoice.rules_tr import (
    EXEMPTION_REASON_CODES,
    SUPPORTED_INVOICE_TYPES,
    SUPPORTED_PROFILES,
    WITHHOLDING_CODES,
)
from app.modules.einvoice.tr_ids import is_valid_document_id
from app.modules.einvoice.ubl_tr import CUSTOMIZATION_IDS

__all__ = ["TR_BLOCK_KEY", "TrEInvoiceFields", "TrOriginalInvoice", "validate_tr_block"]

#: The key of the block under ``metadata.einvoice``.
TR_BLOCK_KEY = "tr"


def _iso_date(value: str, what: str) -> str:
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{what} must be a date written YYYY-MM-DD, got {value!r}") from exc
    return value


class TrOriginalInvoice(BaseModel):
    """The invoice a return (IADE) answers, as its issuer numbered and dated it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=64)
    issue_date: str = Field(min_length=10, max_length=10)

    @field_validator("issue_date")
    @classmethod
    def _check_issue_date(cls, value: str) -> str:
        return _iso_date(value, "original_invoice.issue_date")


class TrEInvoiceFields(BaseModel):
    """What an accountant fills in for an e-Fatura that the invoice itself does not say.

    Every field is optional here. A half-filled block is the normal state on
    the way to a complete one, and what is still missing is reported by the
    export's dry run, which names each gap and where to close it.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: The scenario (``cbc:ProfileID``). Never defaulted: which of the three
    #: applies depends on whether the buyer is a registered e-Fatura user,
    #: which only the integrator can look up.
    profile_id: str = ""
    #: ``cbc:InvoiceTypeCode``. Left empty it follows from the taxes: TEVKIFAT
    #: when VAT is withheld, SATIS otherwise.
    invoice_type: str = ""
    #: The sixteen character document number. Empty leaves it to the
    #: integrator, which is the usual arrangement.
    document_id: str = ""
    #: The three character series (birim kodu) the number starts with.
    series: str = ""
    issue_time: str = ""
    #: Units of Turkish lira per one unit of the invoice currency, on a
    #: foreign currency invoice.
    exchange_rate: str = ""
    exchange_rate_date: str = ""
    exemption_reason_code: str = ""
    exemption_reason: str = Field(default="", max_length=500)
    original_invoice: TrOriginalInvoice | None = None
    #: A return of an invoice issued from this platform: its id here, and the
    #: number and date are read from that invoice.
    original_invoice_id: str = ""
    #: Withholding code per invoice line id, for a document where only some
    #: lines are subject to withholding. An empty code means none on that line.
    line_withholding: dict[str, str] = Field(default_factory=dict)
    tax_total_convention: Literal["", "net_of_withholding", "computed"] = ""
    customization_id: str = ""
    #: Whether the payable amount is also written in words as a note.
    amount_in_words: bool = True
    notes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("profile_id", "invoice_type", "document_id", "series", "exemption_reason_code", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("profile_id")
    @classmethod
    def _check_profile(cls, value: str) -> str:
        if value and value not in SUPPORTED_PROFILES:
            raise ValueError(f"profile_id must be one of {', '.join(sorted(SUPPORTED_PROFILES))}, got {value!r}")
        return value

    @field_validator("invoice_type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if value and value not in SUPPORTED_INVOICE_TYPES:
            raise ValueError(f"invoice_type must be one of {', '.join(sorted(SUPPORTED_INVOICE_TYPES))}, got {value!r}")
        return value

    @field_validator("document_id")
    @classmethod
    def _check_document_id(cls, value: str) -> str:
        if value and not is_valid_document_id(value):
            raise ValueError(
                "document_id must be sixteen characters: a three character series, the four digit year "
                f"and a nine digit sequence, got {value!r}"
            )
        return value

    @field_validator("series")
    @classmethod
    def _check_series(cls, value: str) -> str:
        if value and not (len(value) == 3 and value.isascii() and value.isalnum()):
            raise ValueError(f"series must be three letters or digits, got {value!r}")
        return value

    @field_validator("issue_time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        if value:
            try:
                dt.time.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"issue_time must be a time written HH:MM:SS, got {value!r}") from exc
        return value

    @field_validator("exchange_rate", mode="before")
    @classmethod
    def _check_rate(cls, value: Any) -> Any:
        if value in (None, ""):
            return ""
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"exchange_rate must be a number, got {value!r}") from exc
        if not rate.is_finite() or rate <= 0:
            raise ValueError(f"exchange_rate must be greater than zero, got {value!r}")
        return format(rate, "f")

    @field_validator("exchange_rate_date")
    @classmethod
    def _check_rate_date(cls, value: str) -> str:
        return _iso_date(value, "exchange_rate_date") if value else value

    @field_validator("exemption_reason_code")
    @classmethod
    def _check_exemption(cls, value: str) -> str:
        if value and value not in EXEMPTION_REASON_CODES:
            raise ValueError(f"exemption_reason_code {value!r} is not in the published exemption code list")
        return value

    @field_validator("customization_id")
    @classmethod
    def _check_customization(cls, value: str) -> str:
        if value and value not in CUSTOMIZATION_IDS:
            raise ValueError(f"customization_id must be one of {', '.join(sorted(CUSTOMIZATION_IDS))}, got {value!r}")
        return value

    @field_validator("line_withholding")
    @classmethod
    def _check_line_withholding(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for line_id, code in value.items():
            text = str(code or "").strip()
            if text and text not in WITHHOLDING_CODES:
                raise ValueError(f"line_withholding names the code {text!r}, which is not in the published code list")
            cleaned[str(line_id).strip().lower()] = text
        return cleaned

    @model_validator(mode="after")
    def _series_starts_the_number(self) -> TrEInvoiceFields:
        if self.series and self.document_id and not self.document_id.startswith(self.series):
            raise ValueError(f"document_id {self.document_id!r} does not start with the series {self.series!r}")
        return self


def validate_tr_block(metadata: Any) -> None:
    """Refuse invoice metadata whose ``einvoice.tr`` block is malformed.

    Called where invoice metadata is written. Metadata without the block, and
    every other key of it, passes untouched.

    Raises:
        ValueError: the block is not an object, names a field that does not
            exist, or holds a value the format has no place for.
    """
    if not isinstance(metadata, dict):
        return
    einvoice = metadata.get("einvoice")
    if not isinstance(einvoice, dict) or TR_BLOCK_KEY not in einvoice:
        return
    block = einvoice[TR_BLOCK_KEY]
    if block is None:
        return
    if not isinstance(block, dict):
        raise ValueError("metadata.einvoice.tr must be an object")
    TrEInvoiceFields.model_validate(block)
