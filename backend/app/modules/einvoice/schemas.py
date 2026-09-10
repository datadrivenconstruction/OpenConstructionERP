# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the e-invoice standalone API.

These schemas type the request/response shapes of the standalone validation
and generation endpoints in ``router.py``. They are intentionally thin wrappers
around the dicts that :func:`app.modules.einvoice.service.build_einvoice`
already accepts, so a caller that already builds finance invoice dicts can
post the same shape here without translation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Request schemas ──────────────────────────────────────────────────────────


class PartySchema(BaseModel):
    """Seller or buyer trade party (EN 16931 BG-4 / BG-7)."""

    name: str = ""
    country_code: str = ""
    vat_id: str | None = None
    tax_number: str | None = None
    legal_id: str | None = None
    line1: str | None = None
    postcode: str | None = None
    city: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    electronic_address: str | None = None
    electronic_address_scheme: str | None = None

    model_config = {"extra": "forbid"}


class LineItemSchema(BaseModel):
    """One invoice line for validation or generation."""

    line_id: str | None = None
    description: str = "-"
    quantity: str | float = "1"
    unit: str | None = None
    unit_rate: str | float = "0"
    amount: str | float = "0"
    vat_rate: str | float | None = None
    vat_category: str | None = None

    model_config = {"extra": "forbid"}


class InvoiceDataSchema(BaseModel):
    """The invoice header, matching the dict shape ``build_einvoice`` expects."""

    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str | None = None
    currency_code: str = ""
    amount_subtotal: str | float = "0"
    tax_amount: str | float = "0"
    retention_amount: str | float = "0"
    amount_total: str | float = "0"
    notes: str | None = None
    invoice_direction: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ValidateRequest(BaseModel):
    """Request body for the standalone validation endpoint."""

    invoice: InvoiceDataSchema
    line_items: list[LineItemSchema]
    profile: str = "xrechnung"
    seller: PartySchema | None = None
    buyer: PartySchema | None = None

    model_config = {"extra": "forbid"}


class GenerateRequest(BaseModel):
    """Request body for the standalone XML/PDF generation endpoint."""

    invoice: InvoiceDataSchema
    line_items: list[LineItemSchema]
    profile: str = "xrechnung"
    seller: PartySchema | None = None
    buyer: PartySchema | None = None
    embed: bool = False
    locale: str = "en"

    model_config = {"extra": "forbid"}


# ── Response schemas ─────────────────────────────────────────────────────────


class ViolationResponse(BaseModel):
    """One rule finding, as the standalone validation endpoint returns it."""

    rule_id: str
    severity: str
    message: str
    term: str | None = None
    params: dict[str, str] = Field(default_factory=dict)


class ValidateResponse(BaseModel):
    """Response from the standalone validation endpoint."""

    format: str
    valid: bool
    problems: list[str]
    violations: list[ViolationResponse]


class ProfileResponse(BaseModel):
    """One e-invoice profile in the registry listing."""

    key: str
    name: str
    syntax: str
    region: str
    label: str
