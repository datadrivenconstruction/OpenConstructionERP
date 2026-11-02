# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""JSON writer for the ``gst_einvoice_irn`` document format (IRP schema 1.1).

Maps the shared EN 16931 :class:`EInvoice` plus the national fields the regime
row asks for (GSTIN, HSN, state codes) onto the IRP request body. Intra-state
supplies split tax into CGST and SGST; inter-state ones carry IGST. Values are
rounded to two decimals as the schema expects.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.einvoice.cii import EInvoice

IRP_SCHEMA_VERSION = "1.1"
_CENT = Decimal("0.01")
_DEC_MARK = "@@dec:"


def _m(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENT, ROUND_HALF_UP)


def _num(value: Decimal) -> Decimal:
    return Decimal(value).normalize() + 0


def _ddmmyyyy(iso: str) -> str:
    year, month, day = iso[:10].split("-")
    return f"{day}/{month}/{year}"


def _party(name: str, gstin: str, fields: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "Gstin": gstin,
        "LglNm": name,
        "Addr1": str(fields.get(f"{prefix}_address") or ""),
        "Loc": str(fields.get(f"{prefix}_location") or ""),
        "Pin": int(fields.get(f"{prefix}_pin") or 0) or None,
        "Stcd": str(fields.get(f"{prefix}_state_code") or ""),
    }


def build_irp_document(inv: EInvoice, country_fields: dict[str, Any]) -> dict[str, Any]:
    """Return the IRP request body as a dict."""
    fields = dict(country_fields or {})
    seller_state = str(fields.get("seller_state_code") or "")
    pos = str(fields.get("place_of_supply") or fields.get("buyer_state_code") or "")
    inter_state = not seller_state or not pos or seller_state != pos
    hsn = str(fields.get("hsn_code") or "")
    items: list[dict[str, Any]] = []
    igst_total = cgst_total = Decimal("0")
    for index, line in enumerate(inv.lines, start=1):
        tax = (line.line_net_amount * line.vat_rate / Decimal(100)).quantize(_CENT, ROUND_HALF_UP)
        igst = tax if inter_state else Decimal("0")
        half = (tax / 2).quantize(_CENT, ROUND_HALF_UP) if not inter_state else Decimal("0")
        igst_total += igst
        cgst_total += half
        items.append(
            {
                "SlNo": str(index),
                "PrdDesc": line.name,
                "IsServc": "Y" if str(fields.get("is_service", "Y")).upper().startswith("Y") else "N",
                "HsnCd": hsn,
                "Qty": _num(line.quantity),
                "Unit": (line.unit or "OTH")[:8],
                "UnitPrice": _m(line.net_unit_price),
                "TotAmt": _m(line.line_net_amount),
                "AssAmt": _m(line.line_net_amount),
                "GstRt": _num(line.vat_rate),
                "IgstAmt": _m(igst),
                "CgstAmt": _m(half),
                "SgstAmt": _m(half),
                "TotItemVal": _m(line.line_net_amount + igst + half + half),
            }
        )
    assessable = sum((line.line_net_amount for line in inv.lines), Decimal("0"))
    total = assessable + igst_total + 2 * cgst_total
    buyer = _party(inv.buyer.name, str(fields.get("gstin_buyer") or ""), fields, "buyer")
    buyer["Pos"] = pos
    return {
        "Version": IRP_SCHEMA_VERSION,
        "TranDtls": {"TaxSch": "GST", "SupTyp": str(fields.get("supply_type") or "B2B")},
        "DocDtls": {
            "Typ": "CRN" if inv.type_code == "381" else "INV",
            "No": inv.invoice_number[:16],
            "Dt": _ddmmyyyy(inv.issue_date),
        },
        "SellerDtls": _party(inv.seller.name, str(fields.get("gstin_issuer") or ""), fields, "seller"),
        "BuyerDtls": buyer,
        "ItemList": items,
        "ValDtls": {
            "AssVal": _m(assessable),
            "IgstVal": _m(igst_total),
            "CgstVal": _m(cgst_total),
            "SgstVal": _m(cgst_total),
            "TotInvVal": _m(total),
        },
    }


def render_irp_json(inv: EInvoice, country_fields: dict[str, Any]) -> str:
    """Serialise with every amount as its exact decimal text, never through binary float."""
    text = json.dumps(
        build_irp_document(inv, country_fields),
        ensure_ascii=False,
        separators=(",", ":"),
        default=lambda v: f"{_DEC_MARK}{format(v, 'f')}" if isinstance(v, Decimal) else str(v),
    )
    return re.sub(rf'"{_DEC_MARK}(-?[0-9.]+)"', lambda m: m.group(1), text)


__all__ = ["IRP_SCHEMA_VERSION", "build_irp_document", "render_irp_json"]
