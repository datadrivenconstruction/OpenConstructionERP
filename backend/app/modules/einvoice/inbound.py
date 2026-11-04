# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parse a received UBL 2.1 or UN/CEFACT CII e-invoice into header fields.

The receive side of the EN 16931 engine. The result feeds the supplier invoice
inbox as a draft a person reviews and confirms; nothing is posted from here.
Parsing goes through defusedxml because the file comes from outside.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from defusedxml import ElementTree as DET  # noqa: N814

SYNTAX_UBL = "ubl"
SYNTAX_CII = "cii"

_UBL_ROOTS = {
    "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice",
    "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote",
}
_CII_ROOT = "{urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100}CrossIndustryInvoice"
_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}


class InboundParseError(ValueError):
    """The file is not a UBL or CII invoice this parser understands."""


@dataclass
class InboundInvoice:
    syntax: str
    invoice_number: str = ""
    invoice_date: str = ""
    currency_code: str = ""
    supplier_name: str = ""
    supplier_tax_id: str = ""
    supplier_endpoint: str = ""
    buyer_name: str = ""
    buyer_endpoint: str = ""
    amount_net: Decimal = Decimal("0")
    amount_tax: Decimal = Decimal("0")
    amount_gross: Decimal = Decimal("0")
    is_credit_note: bool = False
    order_reference: str = ""
    lines: list[dict[str, str]] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)

    def capture_fields(self) -> dict[str, Any]:
        """Field names of the supplier invoice inbox."""
        return {
            "supplier_name": self.supplier_name,
            "supplier_tax_id": self.supplier_tax_id,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "currency_code": self.currency_code,
            "amount_net": self.amount_net,
            "amount_tax": self.amount_tax,
            "amount_gross": self.amount_gross,
        }


def _t(node: Any, path: str) -> str:
    found = node.find(path, _NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def _d(text: str) -> Decimal:
    """Decimal of an amount; unreadable text becomes NaN so ``_check`` flags it, NaN/Infinity is rejected."""
    if not text:
        return Decimal("0")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return Decimal("NaN")
    if not value.is_finite():
        raise InboundParseError(f"amount {text!r} is not a finite number")
    return value


def _cii_date(text: str) -> str:
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 and text.isdigit() else text


def _parse_ubl(root: Any) -> InboundInvoice:
    out = InboundInvoice(syntax=SYNTAX_UBL, is_credit_note=root.tag.endswith("CreditNote"))
    out.invoice_number = _t(root, "cbc:ID")
    out.invoice_date = _t(root, "cbc:IssueDate")
    out.currency_code = _t(root, "cbc:DocumentCurrencyCode")
    seller = "cac:AccountingSupplierParty/cac:Party"
    buyer = "cac:AccountingCustomerParty/cac:Party"
    out.supplier_name = _t(root, f"{seller}/cac:PartyLegalEntity/cbc:RegistrationName") or _t(
        root, f"{seller}/cac:PartyName/cbc:Name"
    )
    out.supplier_tax_id = _t(root, f"{seller}/cac:PartyTaxScheme/cbc:CompanyID")
    out.supplier_endpoint = _endpoint(root.find(f"{seller}/cbc:EndpointID", _NS))
    out.buyer_name = _t(root, f"{buyer}/cac:PartyLegalEntity/cbc:RegistrationName") or _t(
        root, f"{buyer}/cac:PartyName/cbc:Name"
    )
    out.buyer_endpoint = _endpoint(root.find(f"{buyer}/cbc:EndpointID", _NS))
    out.amount_net = _d(_t(root, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"))
    out.amount_gross = _d(_t(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"))
    out.amount_tax = _d(_t(root, "cac:TaxTotal/cbc:TaxAmount"))
    out.order_reference = _t(root, "cac:OrderReference/cbc:ID")
    for node in [*root.findall("cac:InvoiceLine", _NS), *root.findall("cac:CreditNoteLine", _NS)]:
        out.lines.append(
            _line(
                _t(node, "cac:Item/cbc:Name") or _t(node, "cac:Item/cbc:Description"),
                _t(node, "cbc:InvoicedQuantity") or _t(node, "cbc:CreditedQuantity"),
                _t(node, "cac:Price/cbc:PriceAmount"),
                _t(node, "cbc:LineExtensionAmount"),
            )
        )
    return out


def _line(description: str, quantity: str, unit_rate: str, amount: str) -> dict[str, str]:
    """One invoice line as the inbox stores it; an unreadable figure becomes ``0``, a negative one is kept."""

    def num(text: str, default: str) -> str:
        value = _d(text) if text else Decimal(default)
        return format(value, "f") if value.is_finite() else default

    return {
        "description": description[:500],
        "quantity": num(quantity, "1"),
        "unit_rate": num(unit_rate, "0"),
        "amount": num(amount, "0"),
    }


def _endpoint(node: Any) -> str:
    if node is None or not (node.text or "").strip():
        return ""
    scheme = node.get("schemeID") or ""
    return f"{scheme}:{node.text.strip()}" if scheme else node.text.strip()


def _parse_cii(root: Any) -> InboundInvoice:
    out = InboundInvoice(syntax=SYNTAX_CII)
    out.invoice_number = _t(root, "rsm:ExchangedDocument/ram:ID")
    out.is_credit_note = _t(root, "rsm:ExchangedDocument/ram:TypeCode") == "381"
    out.invoice_date = _cii_date(_t(root, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString"))
    trade = "rsm:SupplyChainTradeTransaction"
    agreement = f"{trade}/ram:ApplicableHeaderTradeAgreement"
    settlement = f"{trade}/ram:ApplicableHeaderTradeSettlement"
    out.supplier_name = _t(root, f"{agreement}/ram:SellerTradeParty/ram:Name")
    out.supplier_tax_id = _t(root, f"{agreement}/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID")
    out.supplier_endpoint = _endpoint(
        root.find(f"{agreement}/ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID", _NS)
    )
    out.buyer_name = _t(root, f"{agreement}/ram:BuyerTradeParty/ram:Name")
    out.buyer_endpoint = _endpoint(
        root.find(f"{agreement}/ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID", _NS)
    )
    out.currency_code = _t(root, f"{settlement}/ram:InvoiceCurrencyCode")
    summation = f"{settlement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"
    out.amount_net = _d(_t(root, f"{summation}/ram:TaxBasisTotalAmount"))
    out.amount_tax = _d(_t(root, f"{summation}/ram:TaxTotalAmount"))
    out.amount_gross = _d(_t(root, f"{summation}/ram:GrandTotalAmount"))
    out.order_reference = _t(root, f"{agreement}/ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID")
    for node in root.findall(f"{trade}/ram:IncludedSupplyChainTradeLineItem", _NS):
        out.lines.append(
            _line(
                _t(node, "ram:SpecifiedTradeProduct/ram:Name"),
                _t(node, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"),
                _t(node, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"),
                _t(
                    node,
                    "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
                ),
            )
        )
    return out


def _check(inv: InboundInvoice) -> None:
    unreadable = False
    for name, code in (("invoice_number", "BR-02"), ("invoice_date", "BR-03"), ("currency_code", "BR-05")):
        if not getattr(inv, name):
            inv.findings.append({"severity": "error", "code": code, "field": name, "message": f"{name} missing"})
    if not inv.supplier_name:
        inv.findings.append(
            {"severity": "error", "code": "BR-06", "field": "supplier_name", "message": "seller name missing"}
        )
    for name in ("amount_net", "amount_tax", "amount_gross"):
        if getattr(inv, name).is_nan():
            inv.findings.append(
                {"severity": "error", "code": "PARSE-AMOUNT", "field": name, "message": f"{name} is not a number"}
            )
            setattr(inv, name, Decimal("0"))
            unreadable = True
    for idx, line in enumerate(inv.lines, start=1):
        if Decimal(line["amount"]) < 0:
            inv.findings.append(
                {
                    "severity": "warning",
                    "code": "LINE-NEGATIVE",
                    "field": f"lines[{idx}].amount",
                    "message": f"line {idx} is a negative amount ({line['amount']}): discount or credit, review it",
                }
            )
    if not unreadable and inv.amount_gross and inv.amount_net + inv.amount_tax != inv.amount_gross:
        inv.findings.append(
            {
                "severity": "error",
                "code": "BR-CO-15",
                "field": "amount_gross",
                "message": f"net {inv.amount_net} + tax {inv.amount_tax} != gross {inv.amount_gross}",
            }
        )


def parse_inbound(data: bytes) -> InboundInvoice:
    """Parse UBL or CII bytes. Raises :class:`InboundParseError` for anything else."""
    try:
        root = DET.fromstring(data)
    except Exception as exc:  # noqa: BLE001 - defusedxml raises several types
        raise InboundParseError(f"not well-formed XML: {exc}") from exc
    if root.tag in _UBL_ROOTS:
        inv = _parse_ubl(root)
    elif root.tag == _CII_ROOT:
        inv = _parse_cii(root)
    else:
        raise InboundParseError(f"unsupported root element {root.tag}")
    _check(inv)
    return inv


__all__ = ["SYNTAX_CII", "SYNTAX_UBL", "InboundInvoice", "InboundParseError", "parse_inbound"]
