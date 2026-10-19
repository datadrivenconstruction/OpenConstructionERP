# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ZATCA rules a document can be checked against before it leaves.

Each check names the rule it mirrors (BR-KSA-*, BR-CO-*, as numbered in the
schematron of the SDK 238-R3.3.8 and the XML Implementation Standard v1.2) and
the place in the document, so a finding reads "BR-KSA-37: the seller building
number 123 must have four digits" and not "address invalid". Only rules that can
be decided offline are here; ZATCA runs the full set again on submission.

Elements are matched by namespace URI and local name, not by prefix: a document
another generator wrote with other prefixes is the same document.

Groups: ``readable``, ``header``, ``parties``, ``lines`` (lines and totals),
``stamp`` (hash, signature, QR), ``construction`` (the contracting guideline,
read from the document's ZATCA fields), ``advisory`` (warnings).
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import re
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.modules.einvoice_zatca import c14n, data, hashing, qr, signing
from app.modules.einvoice_zatca.codes import (
    BUYER_ID_SCHEMES,
    CATEGORY_STANDARD,
    CITIZEN_ONLY_REASONS,
    EXEMPTION_REASONS,
    EXTENSION_URI,
    GOVERNMENT_LEGAL_FORM,
    NOTE_TYPES,
    NS_CAC,
    NS_CBC,
    NS_DS,
    NS_EXT,
    NS_INVOICE,
    NS_SAC,
    NS_SBC,
    NS_SIG,
    NS_XADES,
    PAYMENT_MEANS,
    PROFILE_ID,
    SAUDI_ARABIA,
    SELLER_ID_SCHEMES,
    SIGNATURE_ID,
    SIGNATURE_INFORMATION_ID,
    SIGNATURE_METHOD,
    TAX_CURRENCY,
    TYPE_CREDIT_NOTE,
    TYPE_INVOICE,
    TYPE_PREPAYMENT,
    VAT_CATEGORIES,
    parse_subtype,
)

GROUP_READABLE = "readable"
GROUP_HEADER = "header"
GROUP_PARTIES = "parties"
GROUP_LINES = "lines"
GROUP_STAMP = "stamp"
GROUP_CONSTRUCTION = "construction"
GROUP_ADVISORY = "advisory"

CENT = Decimal("0.01")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^\d{2}:\d{2}:\d{2}$")


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

# The rules the 238 schematron flags as warnings: ZATCA accepts the document
# with them, so they must not hold a submission back. Codes starting with
# ``SA-`` are ours and are warnings too; the stamp and QR checks are errors.
WARNING_RULES: frozenset[str] = frozenset(
    {
        "BR-KSA-08",
        "BR-KSA-09",
        "BR-KSA-10",
        "BR-KSA-16",
        "BR-KSA-27",
        "BR-KSA-29",
        "BR-KSA-37",
        "BR-KSA-42",
        "BR-KSA-51",
        "BR-KSA-56",
        "BR-KSA-60",
        "BR-KSA-61",
        "BR-KSA-63",
        "BR-KSA-66",
        "BR-KSA-67",
        "BR-KSA-80",
        "BR-KSA-81",
        "BR-KSA-83",
        "BR-KSA-91",
        "BR-KSA-92",
        "BR-KSA-CL-04",
        "BR-KSA-EN16931-08",
        "BR-KSA-EN16931-09",
        "BR-KSA-EN16931-11",
        "BR-KSA-F-01",
    }
)


# Our own codes that block: the contracting guideline is read as law here.
OWN_ERRORS: frozenset[str] = frozenset(
    {"SA-CONSTRUCTION-KIND", "SA-CONSTRUCTION-NO-INVOICE", "SA-CONSTRUCTION-TYPE", "SA-CONSTRUCTION-LD-VAT"}
)


def severity_of(code: str) -> str:
    """Whether a finding blocks the document (error) or only warns."""
    if code in OWN_ERRORS:
        return SEVERITY_ERROR
    if code in WARNING_RULES or code.startswith("SA-"):
        return SEVERITY_WARNING
    return SEVERITY_ERROR


@dataclass(frozen=True)
class ZatcaIssue:
    code: str
    group: str
    message: str
    path: str = ""

    @property
    def severity(self) -> str:
        return severity_of(self.code)


# ── Reading ──────────────────────────────────────────────────────────────────


class _Doc:
    """The parsed document with every element's expanded name resolved once."""

    def __init__(self, root: c14n.Element) -> None:
        self.root = root
        self.names: dict[int, tuple[str, str]] = {}
        self._index(root, {})

    def _index(self, element: c14n.Element, parent_scope: dict[str, str]) -> None:
        scope = {**parent_scope, **element.ns}
        self.names[id(element)] = c14n.expanded(element.tag, scope)
        for child in element.elements():
            self._index(child, scope)

    def name(self, element: c14n.Element) -> tuple[str, str]:
        return self.names[id(element)]

    def children(self, element: c14n.Element | None, ns: str, local: str) -> list[c14n.Element]:
        if element is None:
            return []
        return [c for c in element.elements() if self.names[id(c)] == (ns, local)]

    def child(self, element: c14n.Element | None, *path: tuple[str, str]) -> c14n.Element | None:
        node = element
        for ns, local in path:
            found = self.children(node, ns, local)
            if not found:
                return None
            node = found[0]
        return node

    def text(self, element: c14n.Element | None, *path: tuple[str, str]) -> str:
        node = self.child(element, *path)
        return node.text().strip() if node is not None else ""


def _cbc(local: str) -> tuple[str, str]:
    return (NS_CBC, local)


def _cac(local: str) -> tuple[str, str]:
    return (NS_CAC, local)


def _amount(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimals(value: str) -> int:
    return len(value.split(".", 1)[1]) if "." in value else 0


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def is_vat_number(value: str) -> bool:
    return len(value) == 15 and value.isdigit() and value[0] == "3" and value[-1] == "3"


# ── The checks ───────────────────────────────────────────────────────────────


class _Checker:
    def __init__(self, doc: _Doc, *, profile_vat: str, now: dt.datetime) -> None:
        self.doc = doc
        self.root = doc.root
        self.profile_vat = profile_vat
        self.now = now
        self.issues: list[ZatcaIssue] = []
        self.type_code = doc.text(self.root, _cbc("InvoiceTypeCode"))
        type_node = doc.child(self.root, _cbc("InvoiceTypeCode"))
        self.subtype = parse_subtype(type_node.attr("name") if type_node is not None else "")
        self.simplified = bool(self.subtype and self.subtype.simplified)
        self.currency = doc.text(self.root, _cbc("DocumentCurrencyCode"))

    def add(self, code: str, group: str, message: str, path: str = "") -> None:
        self.issues.append(ZatcaIssue(code=code, group=group, message=message, path=path))

    # Header ──────────────────────────────────────────────────────────────────

    def header(self) -> None:
        d, r = self.doc, self.root
        g = GROUP_HEADER
        if d.text(r, _cbc("ProfileID")) != PROFILE_ID:
            self.add("BR-KSA-EN16931-01", g, f"ProfileID must be {PROFILE_ID}.", "cbc:ProfileID")
        if not d.text(r, _cbc("ID")):
            self.add("BR-02", g, "The invoice number (BT-1) is missing.", "cbc:ID")
        raw_uuid = d.text(r, _cbc("UUID"))
        try:
            uuid.UUID(raw_uuid)
        except ValueError:
            self.add("BR-KSA-03", g, f"The invoice UUID (KSA-1) {raw_uuid!r} is not a UUID.", "cbc:UUID")
        issue_date = d.text(r, _cbc("IssueDate"))
        if not _DATE.match(issue_date):
            self.add("BR-KSA-F-01", g, f"The issue date {issue_date!r} must be YYYY-MM-DD.", "cbc:IssueDate")
        elif issue_date > self.now.date().isoformat():
            self.add("BR-KSA-04", g, f"The issue date {issue_date} is in the future.", "cbc:IssueDate")
        if not _TIME.match(d.text(r, _cbc("IssueTime"))):
            self.add("BR-KSA-70", g, "The issue time (KSA-25) must be hh:mm:ss.", "cbc:IssueTime")
        if self.type_code not in ("388", "381", "383", "386"):
            self.add(
                "BR-KSA-05",
                g,
                f"The document type {self.type_code!r} must be 388, 381, 383 or 386.",
                "cbc:InvoiceTypeCode",
            )
        if self.subtype is None:
            self.add(
                "BR-KSA-06",
                g,
                "The transaction code (KSA-2) must be 01 or 02 followed by five 0/1 flags.",
                "cbc:InvoiceTypeCode/@name",
            )
        else:
            for problem in self.subtype.problems():
                self.add("BR-KSA-31", g, f"The transaction code (KSA-2): {problem}.", "cbc:InvoiceTypeCode/@name")
        if d.text(r, _cbc("TaxCurrencyCode")) != TAX_CURRENCY:
            self.add("BR-KSA-68", g, "The tax currency code (BT-6) must be SAR.", "cbc:TaxCurrencyCode")
        refs = {d.text(a, _cbc("ID")): a for a in d.children(r, NS_CAC, "AdditionalDocumentReference")}
        icv = d.text(refs.get("ICV"), _cbc("UUID"))
        if not icv.isdigit():
            self.add(
                "BR-KSA-33",
                g,
                "The invoice counter (KSA-16) must be present and digits only.",
                "AdditionalDocumentReference[ICV]",
            )
        pih = d.text(refs.get("PIH"), _cac("Attachment"), _cbc("EmbeddedDocumentBinaryObject"))
        try:
            pih_ok = len(base64.b64decode(pih, validate=True)) in (32, 64)
        except (binascii.Error, ValueError):
            pih_ok = False
        if not pih_ok:
            self.add(
                "BR-KSA-61",
                g,
                "The previous invoice hash (KSA-13) must be a base64 SHA-256.",
                "AdditionalDocumentReference[PIH]",
            )
        if self.type_code in NOTE_TYPES:
            if not d.text(r, _cac("BillingReference"), _cac("InvoiceDocumentReference"), _cbc("ID")):
                self.add(
                    "BR-KSA-56",
                    g,
                    "A credit or debit note must name the invoice it corrects (BT-25).",
                    "cac:BillingReference",
                )
            reasons = [d.text(m, _cbc("InstructionNote")) for m in d.children(r, NS_CAC, "PaymentMeans")]
            if not any(reasons):
                self.add(
                    "BR-KSA-17",
                    g,
                    "A credit or debit note must give the reason it is issued (KSA-10).",
                    "cac:PaymentMeans/cbc:InstructionNote",
                )
        means = [d.text(m, _cbc("PaymentMeansCode")) for m in d.children(r, NS_CAC, "PaymentMeans")]
        for code in means:
            if code and code not in PAYMENT_MEANS:
                self.add("BR-KSA-16", g, f"The payment means code {code} is not in the ZATCA list.", "cac:PaymentMeans")
        delivery = d.child(r, _cac("Delivery"))
        supply = d.text(delivery, _cbc("ActualDeliveryDate"))
        supply_end = d.text(delivery, _cbc("LatestDeliveryDate"))
        if self.type_code == TYPE_INVOICE and not self.simplified and not supply:
            self.add("BR-KSA-15", g, "A standard tax invoice must state the supply date (KSA-5).", "cac:Delivery")
        if supply_end and (not supply or supply_end < supply):
            self.add(
                "BR-KSA-35",
                g,
                "The supply end date (KSA-24) needs a supply date and must not precede it.",
                "cac:Delivery",
            )
        legal_form = d.text(
            d.child(r, _cac("AccountingCustomerParty"), _cac("Party"), _cac("PartyLegalEntity")),
            _cbc("CompanyLegalForm"),
        )
        if legal_form == GOVERNMENT_LEGAL_FORM and not self.simplified and not d.text(r, _cbc("TaxPointDate")):
            self.add(
                "BR-KSA-92",
                g,
                "A government buyer (legal form GOV) needs the tax point date (BT-7): the payment order date.",
                "cbc:TaxPointDate",
            )

    # Parties ─────────────────────────────────────────────────────────────────

    def _address(self, party: c14n.Element | None, who: str, *, required: bool) -> None:
        d = self.doc
        g = GROUP_PARTIES
        address = d.child(party, _cac("PostalAddress"))
        country = d.text(address, _cac("Country"), _cbc("IdentificationCode"))
        if not required or country != SAUDI_ARABIA:
            if required and not country:
                code = "BR-KSA-09" if who == "seller" else "BR-KSA-10"
                self.add(code, g, f"The {who} address needs a country code.", f"{who}/PostalAddress")
            return
        missing = [
            label
            for label, local in (
                ("street", "StreetName"),
                ("building number", "BuildingNumber"),
                ("postal code", "PostalZone"),
                ("city", "CityName"),
                ("district", "CitySubdivisionName"),
            )
            if not d.text(address, _cbc(local))
        ]
        if missing:
            code = "BR-KSA-09" if who == "seller" else "BR-KSA-63"
            self.add(code, g, f"The {who} address is missing: {', '.join(missing)}.", f"{who}/PostalAddress")
        building = d.text(address, _cbc("BuildingNumber"))
        if building and not (len(building) == 4 and building.isdigit()):
            self.add(
                "BR-KSA-37", g, f"The {who} building number {building} must have four digits.", f"{who}/BuildingNumber"
            )
        postal = d.text(address, _cbc("PostalZone"))
        if postal and not (len(postal) == 5 and postal.isdigit()):
            code = "BR-KSA-66" if who == "seller" else "BR-KSA-67"
            self.add(code, g, f"The {who} postal code {postal} must have five digits.", f"{who}/PostalZone")

    def parties(self) -> None:
        d, r = self.doc, self.root
        g = GROUP_PARTIES
        seller = d.child(r, _cac("AccountingSupplierParty"), _cac("Party"))
        if seller is None:
            self.add("BR-06", g, "The document has no seller.", "cac:AccountingSupplierParty")
            return
        if not d.text(seller, _cac("PartyLegalEntity"), _cbc("RegistrationName")):
            self.add("BR-06", g, "The seller name (BT-27) is missing.", "seller/RegistrationName")
        vat = d.text(seller, _cac("PartyTaxScheme"), _cbc("CompanyID"))
        if not vat:
            self.add("BR-KSA-39", g, "The seller VAT number (BT-31) is missing.", "seller/CompanyID")
        elif not is_vat_number(vat):
            self.add(
                "BR-KSA-40",
                g,
                f"The seller VAT number {vat!r} must be 15 digits starting and ending with 3.",
                "seller/CompanyID",
            )
        elif self.profile_vat and vat != self.profile_vat:
            self.add(
                "SA-SELLER-VAT",
                g,
                f"The seller VAT number {vat} is not the registration's {self.profile_vat}.",
                "seller/CompanyID",
            )
        ids = d.children(seller, NS_CAC, "PartyIdentification")
        schemes = [d.child(i, _cbc("ID")) for i in ids]
        valid = [s for s in schemes if s is not None and s.attr("schemeID") in SELLER_ID_SCHEMES and s.text().strip()]
        if len(valid) != 1:
            self.add(
                "BR-KSA-08",
                g,
                "The seller needs exactly one other identifier with a scheme of " + ", ".join(SELLER_ID_SCHEMES) + ".",
                "seller/PartyIdentification",
            )
        self._address(seller, "seller", required=True)

        buyer = d.child(r, _cac("AccountingCustomerParty"), _cac("Party"))
        export = bool(self.subtype and self.subtype.export)
        buyer_vat = d.text(buyer, _cac("PartyTaxScheme"), _cbc("CompanyID"))
        if export and buyer_vat:
            self.add(
                "SA-EXPORT-BUYER-VAT",
                g,
                "An export invoice should not carry a Saudi buyer VAT number.",
                "buyer/CompanyID",
            )
        if buyer_vat and not export and not is_vat_number(buyer_vat):
            self.add(
                "BR-KSA-44",
                g,
                f"The buyer VAT number {buyer_vat} must be 15 digits starting and ending with 3.",
                "buyer/CompanyID",
            )
        if self.simplified:
            return
        if buyer is None:
            self.add("BR-KSA-42", g, "A standard tax invoice needs the buyer.", "cac:AccountingCustomerParty")
            return
        if not d.text(buyer, _cac("PartyLegalEntity"), _cbc("RegistrationName")):
            self.add("BR-KSA-42", g, "The buyer name (BT-44) is missing.", "buyer/RegistrationName")
        buyer_ids = [d.child(i, _cbc("ID")) for i in d.children(buyer, NS_CAC, "PartyIdentification")]
        has_id = any(i is not None and i.text().strip() and i.attr("schemeID") in BUYER_ID_SCHEMES for i in buyer_ids)
        if not buyer_vat and not has_id:
            self.add(
                "BR-KSA-81",
                g,
                "A buyer without a VAT number needs another identifier (CRN, NAT, 700 and so on).",
                "buyer/PartyIdentification",
            )
        self._address(buyer, "buyer", required=True)

    # Lines and totals ────────────────────────────────────────────────────────

    def _category(self, node: c14n.Element | None, where: str, *, subtotal: bool) -> tuple[str, Decimal | None]:
        d = self.doc
        g = GROUP_LINES
        category = d.text(node, _cbc("ID"))
        rate = _amount(d.text(node, _cbc("Percent")))
        if category not in VAT_CATEGORIES:
            self.add("BR-KSA-18", g, f"{where}: VAT category {category!r} must be S, Z, E or O.", where)
            return category, rate
        if category != CATEGORY_STANDARD and rate not in (None, Decimal("0")):
            self.add("BR-KSA-11", g, f"{where}: category {category} must carry a 0% rate.", where)
        if subtotal and category != CATEGORY_STANDARD:
            code = d.text(node, _cbc("TaxExemptionReasonCode"))
            reason = EXEMPTION_REASONS.get(code)
            if reason is None or reason.category != category:
                self.add(
                    "BR-KSA-CL-04", g, f"{where}: category {category} needs a VATEX-SA code of that category.", where
                )
            else:
                text = d.text(node, _cbc("TaxExemptionReason"))
                # The official samples write the English text and then "| <Arabic>".
                if reason.text and _squash(reason.text).lower() not in _squash(text).lower():
                    self.add("BR-KSA-83", g, f"{where}: the reason text for {code} must read {reason.text!r}.", where)
                if not reason.text and not text:
                    self.add("BR-KSA-83", g, f"{where}: {code} needs a reason text.", where)
                if code in CITIZEN_ONLY_REASONS:
                    buyer = d.child(self.root, _cac("AccountingCustomerParty"), _cac("Party"))
                    nat = [
                        i
                        for i in d.children(buyer, NS_CAC, "PartyIdentification")
                        if (d.child(i, _cbc("ID")) or c14n.Element("x")).attr("schemeID") == "NAT"
                    ]
                    if not nat:
                        self.add("BR-KSA-49", g, f"{code} needs the buyer's national ID (scheme NAT).", where)
        return category, rate

    def _check_amount_text(self, node: c14n.Element | None, where: str) -> Decimal | None:
        if node is None:
            return None
        text = node.text().strip()
        value = _amount(text)
        if value is None:
            self.add("BR-KSA-F-04", GROUP_LINES, f"{where} {text!r} is not a number.", where)
            return None
        if value < 0:
            self.add("BR-KSA-F-04", GROUP_LINES, f"{where} is negative; ZATCA accepts positive amounts only.", where)
        if _decimals(text) > 2:
            self.add("BR-DEC", GROUP_LINES, f"{where} has more than two decimals.", where)
        return value

    def lines(self) -> None:
        d, r = self.doc, self.root
        g = GROUP_LINES
        nets: list[Decimal] = []
        prepaid_parts = Decimal("0")
        for index, line in enumerate(d.children(r, NS_CAC, "InvoiceLine"), start=1):
            where = f"line {index}"
            net = self._check_amount_text(d.child(line, _cbc("LineExtensionAmount")), f"{where} net amount")
            quantity = _amount(d.text(line, _cbc("InvoicedQuantity")))
            price = _amount(d.text(line, _cac("Price"), _cbc("PriceAmount")))
            base = _amount(d.text(line, _cac("Price"), _cbc("BaseQuantity"))) or Decimal("1")
            if quantity is not None and quantity < 0:
                self.add("BR-KSA-F-04", g, f"{where}: the quantity is negative; issue a credit note instead.", where)
            if (
                net is not None
                and quantity is not None
                and price is not None
                and _money(quantity * price / base) != net
            ):
                self.add(
                    "BR-KSA-EN16931-11",
                    g,
                    f"{where}: net amount {net} is not quantity {quantity} x price {price}.",
                    where,
                )
            classified = d.child(line, _cac("Item"), _cac("ClassifiedTaxCategory"))
            if not d.text(classified, _cbc("ID")):
                self.add("BR-CO-04", g, f"{where}: the item has no VAT category (BT-151).", where)
                rate = None
            else:
                _category, rate = self._category(classified, where, subtotal=False)
            prepayment = d.text(line, _cac("DocumentReference"), _cbc("DocumentTypeCode")) == TYPE_PREPAYMENT
            tax = d.child(line, _cac("TaxTotal"))
            vat = _amount(d.text(tax, _cbc("TaxAmount")))
            total = _amount(d.text(tax, _cbc("RoundingAmount")))
            if prepayment:
                for sub in d.children(tax, NS_CAC, "TaxSubtotal"):
                    taxable = _amount(d.text(sub, _cbc("TaxableAmount"))) or Decimal("0")
                    sub_vat = _amount(d.text(sub, _cbc("TaxAmount"))) or Decimal("0")
                    prepaid_parts += taxable + sub_vat
                    self._category(d.child(sub, _cac("TaxCategory")), f"{where} prepayment", subtotal=True)
                continue
            if net is not None:
                nets.append(net)
            if not self.simplified and (vat is None or total is None):
                self.add(
                    "BR-KSA-52",
                    g,
                    f"{where}: a standard document needs the line VAT (KSA-11) and the line total (KSA-12).",
                    where,
                )
            if net is not None and vat is not None and rate is not None and _money(net * rate / 100) != vat:
                # A warning: ZATCA's own rounding sample carries a line VAT one
                # halala off, and the document-level breakdown is what counts.
                self.add("SA-LINE-VAT", g, f"{where}: line VAT {vat} is not {rate}% of {net}.", where)
            if net is not None and vat is not None and total is not None and net + vat != total:
                self.add("BR-KSA-51", g, f"{where}: line total {total} is not net {net} + VAT {vat}.", where)

        totals = d.child(r, _cac("LegalMonetaryTotal"))
        line_extension = self._check_amount_text(d.child(totals, _cbc("LineExtensionAmount")), "Sum of line amounts")
        exclusive = self._check_amount_text(d.child(totals, _cbc("TaxExclusiveAmount")), "Total without VAT")
        inclusive = self._check_amount_text(d.child(totals, _cbc("TaxInclusiveAmount")), "Total with VAT")
        prepaid = self._check_amount_text(d.child(totals, _cbc("PrepaidAmount")), "Prepaid amount") or Decimal("0")
        payable = self._check_amount_text(d.child(totals, _cbc("PayableAmount")), "Amount due")
        rounding = _amount(d.text(totals, _cbc("PayableRoundingAmount"))) or Decimal("0")
        allowances = _amount(d.text(totals, _cbc("AllowanceTotalAmount"))) or Decimal("0")
        charges = _amount(d.text(totals, _cbc("ChargeTotalAmount"))) or Decimal("0")
        if line_extension is not None and sum(nets, Decimal("0")) != line_extension:
            self.add(
                "BR-CO-10",
                g,
                f"The sum of line amounts {line_extension} is not the sum of the lines {sum(nets, Decimal('0'))}.",
                "LegalMonetaryTotal",
            )
        if exclusive is not None and line_extension is not None and line_extension - allowances + charges != exclusive:
            self.add(
                "BR-CO-13", g, "The total without VAT is not lines minus allowances plus charges.", "LegalMonetaryTotal"
            )

        tax_totals = d.children(r, NS_CAC, "TaxTotal")
        with_breakdown = [t for t in tax_totals if d.children(t, NS_CAC, "TaxSubtotal")]
        without = [t for t in tax_totals if not d.children(t, NS_CAC, "TaxSubtotal")]
        if len(with_breakdown) != 1 or len(without) != 1:
            self.add(
                "BR-KSA-EN16931-08",
                g,
                "The document needs two VAT totals: one with the breakdown, one in SAR without it.",
                "cac:TaxTotal",
            )
        sar = [
            t
            for t in without
            if (d.child(t, _cbc("TaxAmount")) or c14n.Element("x")).attr("currencyID") == TAX_CURRENCY
        ]
        if without and not sar:
            self.add("BR-KSA-68", g, "The VAT total without breakdown must be in SAR.", "cac:TaxTotal")
        vat_total = None
        if with_breakdown:
            node = with_breakdown[0]
            vat_total = self._check_amount_text(d.child(node, _cbc("TaxAmount")), "VAT total")
            category_sum = Decimal("0")
            for index, sub in enumerate(d.children(node, NS_CAC, "TaxSubtotal"), start=1):
                where = f"VAT breakdown {index}"
                taxable = self._check_amount_text(d.child(sub, _cbc("TaxableAmount")), f"{where} taxable amount")
                amount = self._check_amount_text(d.child(sub, _cbc("TaxAmount")), f"{where} VAT")
                _category, rate = self._category(d.child(sub, _cac("TaxCategory")), where, subtotal=True)
                if (
                    taxable is not None
                    and amount is not None
                    and rate is not None
                    and _money(taxable * rate / 100) != amount
                ):
                    self.add("BR-CO-17", g, f"{where}: VAT {amount} is not {rate}% of {taxable}.", where)
                category_sum += amount or Decimal("0")
            if vat_total is not None and category_sum != vat_total:
                self.add(
                    "BR-CO-14",
                    g,
                    f"The VAT total {vat_total} is not the sum of the breakdown {category_sum}.",
                    "cac:TaxTotal",
                )
            if self.currency == TAX_CURRENCY and sar and vat_total is not None:
                sar_amount = _amount(d.text(sar[0], _cbc("TaxAmount")))
                if sar_amount != vat_total:
                    self.add("BR-KSA-EN16931-09", g, "In a SAR document both VAT totals must agree.", "cac:TaxTotal")
        if (
            inclusive is not None
            and exclusive is not None
            and vat_total is not None
            and exclusive + vat_total != inclusive
        ):
            self.add(
                "BR-CO-15", g, f"The total with VAT {inclusive} is not {exclusive} + {vat_total}.", "LegalMonetaryTotal"
            )
        if payable is not None and inclusive is not None and inclusive - prepaid + rounding != payable:
            self.add(
                "BR-CO-16",
                g,
                f"The amount due {payable} is not {inclusive} - {prepaid} + {rounding}.",
                "LegalMonetaryTotal",
            )
        if prepaid_parts and prepaid != prepaid_parts:
            self.add(
                "BR-KSA-80",
                g,
                f"The prepaid amount {prepaid} is not the prepayments' taxable + VAT {prepaid_parts}.",
                "LegalMonetaryTotal",
            )

    # Stamp ───────────────────────────────────────────────────────────────────

    def stamp(self, text: str) -> None:
        d, r = self.doc, self.root
        g = GROUP_STAMP
        refs = {d.text(a, _cbc("ID")): a for a in d.children(r, NS_CAC, "AdditionalDocumentReference")}
        qr_text = d.text(refs.get("QR"), _cac("Attachment"), _cbc("EmbeddedDocumentBinaryObject"))
        extensions = d.child(r, (NS_EXT, "UBLExtensions"))
        pointer = d.child(r, _cac("Signature"))
        if self.simplified:
            if extensions is None or pointer is None:
                self.add(
                    "BR-KSA-60",
                    g,
                    "A simplified document must carry the cryptographic stamp (KSA-15).",
                    "ext:UBLExtensions",
                )
            if not qr_text:
                self.add(
                    "BR-KSA-27",
                    g,
                    "A simplified document must carry the QR code (KSA-14).",
                    "AdditionalDocumentReference[QR]",
                )
        if pointer is not None:
            if (
                d.text(pointer, _cbc("ID")) != SIGNATURE_ID
                or d.text(pointer, _cbc("SignatureMethod")) != SIGNATURE_METHOD
            ):
                self.add("BR-KSA-30", g, "cac:Signature must carry the ZATCA signature ID and method.", "cac:Signature")
        if extensions is None:
            return
        extension = d.child(extensions, (NS_EXT, "UBLExtension"))
        information = d.child(
            extension, (NS_EXT, "ExtensionContent"), (NS_SIG, "UBLDocumentSignatures"), (NS_SAC, "SignatureInformation")
        )
        if d.text(extension, (NS_EXT, "ExtensionURI")) != EXTENSION_URI or information is None:
            self.add("BR-KSA-28", g, "The signature extension is not the ZATCA XAdES extension.", "ext:UBLExtensions")
            return
        if (
            d.text(information, _cbc("ID")) != SIGNATURE_INFORMATION_ID
            or d.text(information, (NS_SBC, "ReferencedSignatureID")) != SIGNATURE_ID
        ):
            self.add(
                "BR-KSA-29",
                g,
                "The signature information IDs are not the ones ZATCA requires.",
                "sac:SignatureInformation",
            )
        signature = d.child(information, (NS_DS, "Signature"))
        info = d.child(signature, (NS_DS, "SignedInfo"))
        references = d.children(info, NS_DS, "Reference")
        invoice_ref = next((x for x in references if x.attr("Id") == "invoiceSignedData"), None)
        props_ref = next((x for x in references if x.attr("URI") == "#xadesSignedProperties"), None)
        expected_hash = hashing.invoice_hash(r)
        if d.text(invoice_ref, (NS_DS, "DigestValue")) != expected_hash:
            self.add(
                "STAMP-HASH",
                g,
                "The signed invoice hash does not match the document; it was changed after signing.",
                "ds:Reference[invoiceSignedData]",
            )
        written = hashing.written_signed_properties(text)
        if not written or d.text(props_ref, (NS_DS, "DigestValue")) != hashing.signed_properties_digest(written):
            self.add(
                "STAMP-PROPERTIES",
                g,
                "The signed properties digest does not match the signed properties.",
                "ds:Reference[xadesSignedProperties]",
            )
        certificate_text = d.text(signature, (NS_DS, "KeyInfo"), (NS_DS, "X509Data"), (NS_DS, "X509Certificate"))
        try:
            certificate = signing.certificate_info(certificate_text)
        except (ValueError, TypeError):
            self.add("STAMP-CERTIFICATE", g, "The stamp's certificate cannot be read.", "ds:X509Certificate")
            return
        cert_node = d.child(
            signature,
            (NS_DS, "Object"),
            (NS_XADES, "QualifyingProperties"),
            (NS_XADES, "SignedProperties"),
            (NS_XADES, "SignedSignatureProperties"),
            (NS_XADES, "SigningCertificate"),
            (NS_XADES, "Cert"),
        )
        if d.text(cert_node, (NS_XADES, "CertDigest"), (NS_DS, "DigestValue")) != hashing.certificate_digest(
            certificate_text
        ):
            self.add(
                "STAMP-CERT-DIGEST", g, "The certificate digest does not match the certificate.", "xades:CertDigest"
            )
        signature_value = d.text(signature, (NS_DS, "SignatureValue"))
        try:
            signature_bytes = base64.b64decode(signature_value, validate=True)
        except (binascii.Error, ValueError):
            signature_bytes = b""
        if not signing.verify(certificate.public_key_der, signature_bytes, base64.b64decode(expected_hash)):
            self.add(
                "STAMP-SIGNATURE",
                g,
                "The signature does not verify against the stamp's certificate.",
                "ds:SignatureValue",
            )
        if qr_text:
            self._qr(qr_text, expected_hash, signature_value, certificate)

    def _qr(self, text: str, invoice_hash: str, signature_value: str, certificate: signing.CertificateInfo) -> None:
        d, r = self.doc, self.root
        g = GROUP_STAMP
        if len(text) > qr.MAX_LENGTH:
            self.add("QR-LENGTH", g, f"The QR is {len(text)} characters; ZATCA allows {qr.MAX_LENGTH}.", "QR")
        try:
            tags = qr.decode(text)
        except qr.QrError as exc:
            self.add("QR-FORMAT", g, f"The QR cannot be read: {exc}", "QR")
            return
        seller = d.child(r, _cac("AccountingSupplierParty"), _cac("Party"))
        totals = d.child(r, _cac("LegalMonetaryTotal"))
        expected: dict[int, bytes] = {
            qr.TAG_SELLER_NAME: d.text(seller, _cac("PartyLegalEntity"), _cbc("RegistrationName")).encode("utf-8"),
            qr.TAG_VAT_NUMBER: d.text(seller, _cac("PartyTaxScheme"), _cbc("CompanyID")).encode("utf-8"),
            qr.TAG_TIMESTAMP: f"{d.text(r, _cbc('IssueDate'))}T{d.text(r, _cbc('IssueTime'))}".encode(),
            # The SDK writes the amount due here, and the VAT total of the
            # first cac:TaxTotal into tag 5 (SigningServiceImpl.populateQRCode).
            qr.TAG_TOTAL_WITH_VAT: d.text(totals, _cbc("PayableAmount")).encode(),
            qr.TAG_VAT_TOTAL: d.text(d.child(r, _cac("TaxTotal")), _cbc("TaxAmount")).encode(),
            qr.TAG_INVOICE_HASH: invoice_hash.encode(),
            qr.TAG_SIGNATURE: signature_value.encode(),
            qr.TAG_PUBLIC_KEY: certificate.public_key_der,
        }
        if self.simplified:
            expected[qr.TAG_CERTIFICATE_SIGNATURE] = certificate.certificate_signature
        names = {
            1: "seller name",
            2: "VAT number",
            3: "timestamp",
            4: "amount due",
            5: "VAT total",
            6: "invoice hash",
            7: "signature",
            8: "public key",
            9: "certificate signature",
        }
        for tag, value in expected.items():
            if tags.get(tag) != value:
                self.add("QR-TAG", g, f"QR tag {tag} ({names[tag]}) does not match the document.", f"QR tag {tag}")

    # Advisory ────────────────────────────────────────────────────────────────

    def advisory(self) -> None:
        d, r = self.doc, self.root
        issue_date = d.text(r, _cbc("IssueDate"))
        supply = d.text(r, _cac("Delivery"), _cbc("ActualDeliveryDate")) or issue_date
        try:
            day = dt.date.fromisoformat(supply[:10])
        except ValueError:
            return
        standard = data.standard_rate_on(day)
        for sub in d.children(self._breakdown(), NS_CAC, "TaxSubtotal"):
            category = d.text(sub, _cac("TaxCategory"), _cbc("ID"))
            rate = _amount(d.text(sub, _cac("TaxCategory"), _cbc("Percent")))
            if category == CATEGORY_STANDARD and standard is not None and rate is not None and rate != standard:
                self.add(
                    "SA-VAT-RATE",
                    GROUP_ADVISORY,
                    f"The standard rate on {day} was {standard}%, the document charges {rate}%. Only a transitional "
                    "contract rule would allow that; check it before sending.",
                    "TaxSubtotal",
                )

    def _breakdown(self) -> c14n.Element | None:
        for total in self.doc.children(self.root, NS_CAC, "TaxTotal"):
            if self.doc.children(total, NS_CAC, "TaxSubtotal"):
                return total
        return None


def parse(text: str) -> c14n.Element:
    """The document element, or :class:`c14n.XmlError`."""
    return c14n.parse(text.encode("utf-8") if isinstance(text, str) else text)


def read_identity(text: str) -> tuple[str, str]:
    """The document's UUID and its KSA-2 subtype code, or :class:`c14n.XmlError`.

    The adapter decides between clearance and reporting from the subtype, and
    keys the answer to the document by its UUID, so both are read from the
    document itself rather than from anything the caller says about it.
    """
    root = parse(text)
    doc = _Doc(root)
    if doc.name(root) != (NS_INVOICE, "Invoice"):
        raise c14n.XmlError("The document is not a UBL 2.1 Invoice.")
    code = doc.child(root, _cbc("InvoiceTypeCode"))
    subtype = ""
    if code is not None:
        subtype = next((value for name, value in code.attrs if name == "name"), "")
    return doc.text(root, _cbc("UUID")), subtype


def issue_moment(text: str) -> dt.datetime | None:
    """When the document says it was issued, in Riyadh time (+03:00), or ``None``.

    The samples write the time without an offset and ZATCA reads it as local
    time, which in the Kingdom is a fixed +03:00 all year.
    """
    try:
        root = parse(text)
        doc = _Doc(root)
        day = doc.text(root, _cbc("IssueDate"))
        clock = doc.text(root, _cbc("IssueTime"))
        zone = dt.timezone(dt.timedelta(hours=3))
        return dt.datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=zone)
    except (c14n.XmlError, ValueError):
        return None


def check_document(
    text: str,
    *,
    profile_vat: str = "",
    now: dt.datetime | None = None,
    zatca_fields: dict[str, Any] | None = None,
) -> list[ZatcaIssue]:
    """Every finding about one ZATCA document."""
    now = now or dt.datetime.now(dt.UTC)
    try:
        root = parse(text)
        doc = _Doc(root)
    except c14n.XmlError as exc:
        return [ZatcaIssue("XML", GROUP_READABLE, str(exc))]
    if doc.name(root) != (NS_INVOICE, "Invoice"):
        return [
            ZatcaIssue("XML", GROUP_READABLE, "The document is not a UBL 2.1 Invoice; ZATCA notes are Invoices too.")
        ]
    checker = _Checker(doc, profile_vat=profile_vat, now=now)
    checker.header()
    checker.parties()
    checker.lines()
    checker.stamp(text)
    checker.advisory()
    checker.issues.extend(construction_issues(zatca_fields or {}, type_code=checker.type_code, doc=doc))
    return checker.issues


def construction_issues(fields: dict[str, Any], *, type_code: str, doc: _Doc | None = None) -> list[ZatcaIssue]:
    """The contracting-sector rules, on what the document says it is (P4)."""
    g = GROUP_CONSTRUCTION
    issues: list[ZatcaIssue] = []
    kind = str(fields.get("kind") or "").strip().lower()
    rule = data.CONSTRUCTION_RULES.get(kind)
    if kind and rule is None:
        issues.append(
            ZatcaIssue(
                "SA-CONSTRUCTION-KIND",
                g,
                f"Unknown construction kind {kind!r}; use one of {', '.join(data.CONSTRUCTION_KINDS)}.",
            )
        )
    elif rule is not None and not rule.needs_expert_review:
        if not rule.document_types:
            issues.append(
                ZatcaIssue(
                    "SA-CONSTRUCTION-NO-INVOICE",
                    g,
                    f"No tax document is issued for {kind.replace('_', ' ')}: {rule.treatment} "
                    f"(contracting guideline {rule.section}).",
                )
            )
        elif type_code and type_code not in rule.document_types:
            issues.append(
                ZatcaIssue(
                    "SA-CONSTRUCTION-TYPE",
                    g,
                    f"{kind.replace('_', ' ').capitalize()} is issued as {' or '.join(rule.document_types)}, not "
                    f"{type_code}: {rule.treatment} (contracting guideline {rule.section}).",
                )
            )
        if kind == data.KIND_LIQUIDATED_DAMAGES and doc is not None and type_code == TYPE_CREDIT_NOTE:
            categories = {
                doc.text(sub, _cac("TaxCategory"), _cbc("ID"))
                for total in doc.children(doc.root, NS_CAC, "TaxTotal")
                for sub in doc.children(total, NS_CAC, "TaxSubtotal")
            }
            if categories and categories != {CATEGORY_STANDARD}:
                issues.append(
                    ZatcaIssue(
                        "SA-CONSTRUCTION-LD-VAT",
                        g,
                        "A credit note for liquidated damages reduces a standard-rated supply, so it carries VAT at "
                        "the standard rate (contracting guideline §5.4, Example 6).",
                    )
                )
    government = fields.get("government") if isinstance(fields.get("government"), dict) else {}
    if government.get("contract") and str(government.get("role") or "").lower() != "subcontractor":
        if not str(government.get("payment_order_date") or "").strip():
            issues.append(
                ZatcaIssue(
                    "SA-GOV-TAX-POINT",
                    GROUP_ADVISORY,
                    "On a government contract the tax point is the payment order date, or receipt if earlier "
                    "(VAT IR Art. 20(5); contracting guideline §4.2). Record the payment order date; the document "
                    "then states it as the tax point date (BR-KSA-92).",
                )
            )
    return issues


__all__ = [
    "GROUP_ADVISORY",
    "GROUP_CONSTRUCTION",
    "GROUP_HEADER",
    "GROUP_LINES",
    "GROUP_PARTIES",
    "GROUP_READABLE",
    "GROUP_STAMP",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "WARNING_RULES",
    "ZatcaIssue",
    "check_document",
    "construction_issues",
    "is_vat_number",
    "issue_moment",
    "parse",
    "read_identity",
    "severity_of",
]
