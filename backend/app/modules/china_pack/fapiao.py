# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""数电票 invoice data, prepared for import into the taxpayer's own channel.

The platform does not issue fully digitalised e-invoices: issuing needs the
taxpayer's access to the national platform or a certified channel. This module
prepares the face data of a construction-services invoice (STA Announcement
2024 No.11 Art.3, special-business tag 建筑服务) as JSON or XML. The 20-digit
number the platform assigns, and its PDF and OFD, are recorded back on the
invoice under ``metadata.einvoice.issued_number`` and checked by
``cn.fapiao_number``.

Field names are our own neutral English keys with the face label beside them;
a channel's import template maps them. Nothing here claims to be a channel's
schema.
"""

from __future__ import annotations

import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from xml.etree import ElementTree as ET

from app.core.line_tax import to_decimal
from app.modules.china_pack.config import CN_TAX

DOCUMENT_FORMAT = "cn_shudianpiao_json"
SCHEMA = "oe.cn_fapiao/1"
_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)


class FapiaoDataError(ValueError):
    """The invoice lacks what a construction 数电票 must carry."""


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _party(raw: dict[str, Any] | None) -> dict[str, str]:
    raw = raw or {}
    return {
        "name": str(raw.get("name") or ""),
        "tax_id": str(raw.get("vat_id") or raw.get("tax_id") or ""),
    }


def build_fapiao_data(
    *,
    invoice: dict[str, Any],
    lines: list[dict[str, Any]],
    seller: dict[str, Any] | None,
    buyer: dict[str, Any] | None,
    einvoice: dict[str, Any] | None,
) -> dict[str, Any]:
    """The face data of one construction-services 数电票.

    Args:
        invoice: ``invoice_number``, ``invoice_date``, ``currency_code``.
        lines: ``description``, ``quantity``, ``unit``, ``unit_rate``,
            ``amount`` (net), ``vat_rate`` (percent), optional ``tax_category``.
        seller: the seller party (``name``, ``vat_id``).
        buyer: the buyer party (``name``, ``vat_id``).
        einvoice: ``metadata.einvoice`` of the invoice: ``project_name``,
            ``site_address`` (``line1``, ``city``, ``subdivision``),
            ``cross_region``.

    Raises:
        FapiaoDataError: The site location or the project name is missing.
    """
    ei = einvoice or {}
    site = ei.get("site_address") if isinstance(ei.get("site_address"), dict) else {}
    location = " ".join(str(site.get(k) or "").strip() for k in ("subdivision", "city", "line1")).strip()
    project_name = str(ei.get("project_name") or "").strip()
    missing = [n for n, v in (("site_location", location), ("project_name", project_name)) if not v]
    if missing:
        raise FapiaoDataError(
            "A construction 数电票 must name the site location and the project; missing: " + ", ".join(missing)
        )
    items = []
    net_total = Decimal(0)
    tax_total = Decimal(0)
    for line in lines:
        net = to_decimal(line.get("amount"))
        rate = to_decimal(line.get("vat_rate"))
        tax = (net * rate / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
        net_total += net
        tax_total += tax
        items.append(
            {
                "item_name": str(line.get("description") or ""),
                "unit": str(line.get("unit") or ""),
                "quantity": str(to_decimal(line.get("quantity") or 1).normalize()),
                "unit_price": str(to_decimal(line.get("unit_rate")).normalize()),
                "amount": _money(net),
                "tax_rate_pct": str(rate.normalize()),
                "tax_amount": _money(tax),
            }
        )
    return {
        "schema": SCHEMA,
        "invoice_type": "数电票",
        "draft_reference": str(invoice.get("invoice_number") or ""),
        "issue_date": str(invoice.get("invoice_date") or "")[:10],
        "currency": str(invoice.get("currency_code") or "CNY"),
        "seller": _party(seller),
        "buyer": _party(buyer),
        "special_business": {
            "tag": CN_TAX["fapiao"]["special_business_tag"],
            "site_location": location,
            "project_name": project_name,
            "cross_region": bool(ei.get("cross_region")),
        },
        "items": items,
        "total_amount": _money(net_total),
        "total_tax": _money(tax_total),
        "total_with_tax": _money(net_total + tax_total),
        "issued_number": str(ei.get("issued_number") or ""),
        "unverified_fields": list(CN_TAX["fapiao"]["unverified_fields"]),
    }


def to_json(data: dict[str, Any]) -> str:
    """The invoice data as UTF-8 JSON, Chinese kept readable."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _xml_value(parent: ET.Element, key: str, value: Any) -> None:
    if isinstance(value, dict):
        node = ET.SubElement(parent, key)
        for k, v in value.items():
            _xml_value(node, k, v)
    elif isinstance(value, list):
        node = ET.SubElement(parent, key)
        child = "item" if key == "items" else "value"
        for v in value:
            _xml_value(node, child, v)
    else:
        ET.SubElement(parent, key).text = str(value).lower() if isinstance(value, bool) else str(value)


def to_xml(data: dict[str, Any]) -> str:
    """The same data as a plain XML document with one element per key."""
    root = ET.Element("fapiao", {"schema": SCHEMA})
    for key, value in data.items():
        if key != "schema":
            _xml_value(root, key, value)
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


async def load_fapiao_data(session: Any, invoice_id: uuid.UUID) -> dict[str, Any]:
    """Read a finance invoice and prepare its 数电票 data.

    Raises:
        LookupError: No such invoice.
        FapiaoDataError: The invoice cannot be a construction 数电票 yet.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.finance.einvoice_parties import einvoice_defaults_for_invoice  # noqa: PLC0415
    from app.modules.finance.models import Invoice, InvoiceLineItem  # noqa: PLC0415

    invoice = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise LookupError("invoice not found")
    rows = (
        (
            await session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
                .order_by(InvoiceLineItem.sort_order, InvoiceLineItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    defaults = await einvoice_defaults_for_invoice(
        session,
        contact_id=invoice.contact_id,
        project_id=invoice.project_id,
        invoice_direction=invoice.invoice_direction,
    )
    meta = invoice.metadata_ if isinstance(invoice.metadata_, dict) else {}
    ei = meta.get("einvoice") if isinstance(meta.get("einvoice"), dict) else {}
    return build_fapiao_data(
        invoice={
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "currency_code": invoice.currency_code,
        },
        lines=[
            {
                "description": r.description,
                "quantity": r.quantity,
                "unit": r.unit,
                "unit_rate": r.unit_rate,
                "amount": r.amount,
                "vat_rate": r.vat_rate,
            }
            for r in rows
        ],
        seller={**(defaults.get("seller") or {}), **(ei.get("seller") or {})},
        buyer={**(defaults.get("buyer") or {}), **(ei.get("buyer") or {})},
        einvoice=ei,
    )


async def build_from_invoice(
    session: Any,
    *,
    invoice_id: uuid.UUID,
    profile: Any,
    country_fields: dict[str, Any],
) -> tuple[str, str]:
    """The payload builder registered for ``cn_shudianpiao_json``."""
    from app.modules.einvoice_clearance.service import ClearanceError  # noqa: PLC0415

    del profile, country_fields
    try:
        data = await load_fapiao_data(session, invoice_id)
    except LookupError as exc:
        raise ClearanceError(f"Invoice {invoice_id} was not found, so there is nothing to prepare.") from exc
    except FapiaoDataError as exc:
        raise ClearanceError(str(exc)) from exc
    return to_json(data), "application/json"
