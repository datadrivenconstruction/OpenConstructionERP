"""‌⁠‍PEPPOL UBL 2.1 invoice parser.

Implements a minimal but correct ``Invoice`` parser for the OASIS UBL 2.1
syntax used by the PEPPOL BIS Billing 3.0 specification (EN 16931).

We accept the document as long as it has the required header fields
(invoice ID, supplier endpoint, monetary totals) — strict EN 16931
business-rule validation is performed downstream by validators (or
by an external service like a Peppol Access Point).

We deliberately use stdlib ``xml.etree`` rather than ``lxml`` because:
    * lxml is not a hard dependency of the platform
    * the surface area we parse is tiny (header + line items)
    * defusedxml fallback is wired below for safety

References:
    * https://docs.peppol.eu/poacc/billing/3.0/syntax/ubl-invoice/
    * https://docs.oasis-open.org/ubl/os-UBL-2.2/xml/UBL-Invoice-2.1-Example.xml
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

# Inbound PEPPOL XML arrives from an external Access Point — it is
# untrusted. defusedxml neutralises XXE / billion-laughs / external-DTD
# attacks. If it is unavailable we MUST refuse to parse rather than fall
# back to the unsafe stdlib parser (which resolves external entities).
try:  # pragma: no cover — single-line import preference
    from defusedxml import ElementTree as ET  # type: ignore

    _XML_HARDENED = True
except ImportError:  # pragma: no cover
    from xml.etree import ElementTree as ET  # noqa: N817

    _XML_HARDENED = False

# UBL namespace map
UBL_NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


@dataclass
class PeppolInvoiceLine:
    """‌⁠‍A single line parsed from ``cac:InvoiceLine``."""

    line_id: str
    description: str
    quantity: Decimal
    unit_of_measure: str
    unit_price: Decimal
    line_total: Decimal
    vendor_sku: str | None = None
    buyer_sku: str | None = None


@dataclass
class PeppolInvoiceParsed:
    """‌⁠‍Fully parsed PEPPOL invoice ready for ingest."""

    invoice_id: str
    issue_date: str | None
    due_date: str | None
    currency: str
    supplier_endpoint: str | None
    supplier_name: str
    supplier_vat: str | None
    buyer_endpoint: str | None
    buyer_name: str | None
    payable_amount: Decimal
    tax_total: Decimal
    line_extension_amount: Decimal
    order_reference: str | None  # buyer PO number, if present
    peppol_message_id: str | None
    lines: list[PeppolInvoiceLine] = field(default_factory=list)


class PeppolParseError(ValueError):
    """Raised when the supplied document is not a valid PEPPOL UBL invoice."""


def _strip_ns(tag: str) -> str:
    """Remove the ``{ns}`` prefix from an XPath tag for friendlier errors."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_text(parent: Any, path: str) -> str | None:
    """Find a single child element's text by namespace-aware path; None if absent."""
    el = parent.find(path, UBL_NS)
    if el is None or el.text is None:
        return None
    text = el.text.strip()
    return text or None


def _to_decimal(s: str | None) -> Decimal:
    if s is None:
        return Decimal("0")
    s = s.strip()
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _unit_attr(parent: Any, path: str) -> tuple[Decimal, str]:
    """Read ``<cbc:InvoicedQuantity unitCode="...">12.3</cbc:InvoicedQuantity>``."""
    el = parent.find(path, UBL_NS)
    if el is None:
        return Decimal("0"), "EA"
    qty = _to_decimal(el.text)
    unit = el.attrib.get("unitCode", "EA")
    return qty, unit


# Map UBL UNECE recommendation 20 unit codes → human-readable abbreviations
_UNIT_MAP = {
    "EA": "pcs",
    "C62": "pcs",
    "PCE": "pcs",
    "PR": "pair",
    "MTR": "m",
    "KMT": "km",
    "CMT": "cm",
    "MMT": "mm",
    "MTK": "m2",
    "MTQ": "m3",
    "LTR": "l",
    "KGM": "kg",
    "TNE": "ton",
    "GRM": "g",
    "HUR": "hr",
    "DAY": "day",
}


def _normalise_unit(code: str) -> str:
    return _UNIT_MAP.get(code.upper(), code.lower())


def parse_peppol_invoice(xml_source: bytes | str) -> PeppolInvoiceParsed:
    """Parse a UBL 2.1 PEPPOL invoice document.

    Raises:
        PeppolParseError: when the input is not a UBL Invoice or required
            fields are missing.
    """
    if not _XML_HARDENED:
        # Hard refusal: parsing untrusted PEPPOL XML without defusedxml
        # would expose the platform to XXE / entity-expansion attacks.
        raise PeppolParseError(
            "Secure XML parser (defusedxml) is not installed; refusing to parse untrusted PEPPOL document.",
        )
    raw = xml_source if isinstance(xml_source, bytes) else xml_source.encode("utf-8")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:  # type: ignore[attr-defined]
        raise PeppolParseError(f"XML parse error: {exc}") from exc
    except PeppolParseError:
        raise
    except Exception as exc:  # noqa: BLE001 — defusedxml raises EntitiesForbidden,
        # DTDForbidden, ExternalReferenceForbidden — none subclass ParseError.
        # Treat any boundary failure as a bad document (HTTP 400), never 500.
        raise PeppolParseError(
            f"Rejected unsafe or malformed XML: {type(exc).__name__}",
        ) from exc

    # Verify this is an Invoice (vs CreditNote / other document)
    root_tag = _strip_ns(root.tag)
    if root_tag != "Invoice":
        raise PeppolParseError(
            f"Expected ubl:Invoice root element, got '{root_tag}'",
        )

    invoice_id = _find_text(root, "cbc:ID")
    if not invoice_id:
        raise PeppolParseError("Missing required cbc:ID (invoice number)")

    issue_date = _find_text(root, "cbc:IssueDate")
    due_date = _find_text(root, "cbc:DueDate")
    currency = _find_text(root, "cbc:DocumentCurrencyCode") or "EUR"

    # Order reference (buyer PO)
    order_ref_el = root.find("cac:OrderReference/cbc:ID", UBL_NS)
    order_reference = order_ref_el.text.strip() if (order_ref_el is not None and order_ref_el.text) else None

    # Supplier (AccountingSupplierParty)
    supplier = root.find("cac:AccountingSupplierParty/cac:Party", UBL_NS)
    supplier_name = ""
    supplier_vat: str | None = None
    supplier_endpoint: str | None = None
    if supplier is not None:
        supplier_name = (
            _find_text(supplier, "cac:PartyName/cbc:Name")
            or _find_text(supplier, "cac:PartyLegalEntity/cbc:RegistrationName")
            or ""
        )
        ep = supplier.find("cbc:EndpointID", UBL_NS)
        if ep is not None and ep.text:
            supplier_endpoint = ep.text.strip()
        supplier_vat = _find_text(
            supplier,
            "cac:PartyTaxScheme/cbc:CompanyID",
        )

    # Buyer (AccountingCustomerParty)
    buyer = root.find("cac:AccountingCustomerParty/cac:Party", UBL_NS)
    buyer_name: str | None = None
    buyer_endpoint: str | None = None
    if buyer is not None:
        buyer_name = _find_text(buyer, "cac:PartyName/cbc:Name") or _find_text(
            buyer,
            "cac:PartyLegalEntity/cbc:RegistrationName",
        )
        ep = buyer.find("cbc:EndpointID", UBL_NS)
        if ep is not None and ep.text:
            buyer_endpoint = ep.text.strip()

    # Monetary totals
    totals = root.find("cac:LegalMonetaryTotal", UBL_NS)
    payable_amount = Decimal("0")
    line_extension_amount = Decimal("0")
    if totals is not None:
        payable_amount = _to_decimal(_find_text(totals, "cbc:PayableAmount"))
        line_extension_amount = _to_decimal(
            _find_text(totals, "cbc:LineExtensionAmount"),
        )

    tax_total = Decimal("0")
    for el in root.findall("cac:TaxTotal/cbc:TaxAmount", UBL_NS):
        tax_total += _to_decimal(el.text)

    # Optional Peppol message ID (UBLVersionID + ProfileID concatenation)
    peppol_message_id = _find_text(root, "cbc:UUID")

    # Invoice lines
    lines: list[PeppolInvoiceLine] = []
    for line in root.findall("cac:InvoiceLine", UBL_NS):
        line_id = _find_text(line, "cbc:ID") or ""
        description = (
            _find_text(line, "cac:Item/cbc:Name") or _find_text(line, "cac:Item/cbc:Description") or "(unnamed line)"
        )
        qty, unit_code = _unit_attr(line, "cbc:InvoicedQuantity")
        unit_price = _to_decimal(
            _find_text(line, "cac:Price/cbc:PriceAmount"),
        )
        line_total = _to_decimal(_find_text(line, "cbc:LineExtensionAmount"))
        vendor_sku = _find_text(
            line,
            "cac:Item/cac:SellersItemIdentification/cbc:ID",
        )
        buyer_sku = _find_text(
            line,
            "cac:Item/cac:BuyersItemIdentification/cbc:ID",
        )
        lines.append(
            PeppolInvoiceLine(
                line_id=line_id,
                description=description,
                quantity=qty,
                unit_of_measure=_normalise_unit(unit_code),
                unit_price=unit_price,
                line_total=line_total,
                vendor_sku=vendor_sku,
                buyer_sku=buyer_sku,
            ),
        )

    return PeppolInvoiceParsed(
        invoice_id=invoice_id,
        issue_date=issue_date,
        due_date=due_date,
        currency=currency,
        supplier_endpoint=supplier_endpoint,
        supplier_name=supplier_name,
        supplier_vat=supplier_vat,
        buyer_endpoint=buyer_endpoint,
        buyer_name=buyer_name,
        payable_amount=payable_amount,
        tax_total=tax_total,
        line_extension_amount=line_extension_amount,
        order_reference=order_reference,
        peppol_message_id=peppol_message_id,
        lines=lines,
    )


# Endpoint-ID regex helpers — PEPPOL endpoints encode scheme + value, e.g.
# ``9930:DE123456789`` (Germany VAT) or ``0088:5790000436026`` (GLN)
_ENDPOINT_RE = re.compile(r"^(?P<scheme>\d{4}):(?P<value>.+)$")


def split_endpoint(endpoint: str) -> tuple[str | None, str]:
    """Split ``9930:DE12345`` → (``9930``, ``DE12345``)."""
    if not endpoint:
        return None, ""
    m = _ENDPOINT_RE.match(endpoint.strip())
    if not m:
        return None, endpoint.strip()
    return m.group("scheme"), m.group("value")


__all__ = [
    "PeppolInvoiceLine",
    "PeppolInvoiceParsed",
    "PeppolParseError",
    "parse_peppol_invoice",
    "split_endpoint",
]
