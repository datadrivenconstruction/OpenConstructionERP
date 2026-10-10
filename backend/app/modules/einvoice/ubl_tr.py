# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""UBL-TR 1.2.1 invoice writer: the e-Fatura and e-Arşiv Fatura document of Türkiye.

UBL-TR is the Revenue Administration's (GİB) customisation of OASIS UBL 2.1.
It shares the UBL namespaces with the Peppol writer in ``ubl`` and almost
nothing else: its own header constants, its own party identification, its own
tax codes, a mandatory signature block, and totals that mean something
different once VAT is withheld. So it has its own model, :class:`TrInvoice`,
and its own rules in ``rules_tr``. It never passes through the EN 16931 rules:
BR-CO-14, BR-CO-15 and BR-CO-16 would refuse a correct withholding invoice.

What this module produces is an UNSIGNED document. Signing it with the
taxpayer's financial seal and submitting it to GİB is the work of the
customer's licensed integrator. The two mandatory signature containers are
therefore written as placeholders (see :func:`build_ubl_tr_xml`).

Everything structural below was read from the official packages published at
https://ebelge.gib.gov.tr/efaturamevzuat.html on 2026-10-10: the element order
from ``UBL-Invoice-2.1.xsd`` and ``UBL-CommonAggregateComponents-2.1.xsd`` of
the UBL-TR 1.2.1 package, the header constants from ``UBL-TR_Common_Schematron.xml``
(revision 2026-07-01), the tax block from the three official withholding
samples (``TEVKIFAT.xml``, ``YTB_Tevkıfat_Efatura.xml``, ``YTB_Tevkıfat_EArşiv.xml``).

The writer performs no tax arithmetic. Every VAT figure it prints is a
:class:`~app.core.payment_taxes.Figure` computed by the shared payment tax
calculation, and the only thing done to those figures here is to add the
groups of one document together. A figure that is ``held`` has no amount, and
a document with one is not generated.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from xml.etree import ElementTree as ET  # noqa: N817 - trusted, we build not parse

from app.core.currency_registry import minor_units
from app.core.payment_taxes import Figure, PaymentTaxResult
from app.modules.einvoice.cii import EInvoiceError
from app.modules.einvoice.tr_ids import classify_tax_number
from app.modules.einvoice.ubl import CAC, CBC, INV, _amt, _tostring

EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
# Namespace of the element that stands where the integrator will put the
# XAdES ``ds:Signature``. ``ext:ExtensionContent`` must hold exactly one element
# from a namespace other than the extension namespace (the wildcard in
# ``UBL-ExtensionContentDataType-2.1.xsd`` is ``##other``, min 1, max 1, lax).
UNSIGNED = "urn:datadrivenconstruction:ubl-tr:unsigned"

ET.register_namespace("ext", EXT)
ET.register_namespace("oce", UNSIGNED)

_PREFIXES = {"cac": CAC, "cbc": CBC, "ext": EXT}


def _sub(parent: ET.Element, prefix: str, local: str, text: str | None = None) -> ET.Element:
    # The helper of the same name in ``ubl`` knows the two component
    # namespaces only; this document also has the extension namespace.
    el = ET.SubElement(parent, f"{{{_PREFIXES[prefix]}}}{local}")
    if text is not None:
        el.text = text
    return el


# ── header constants ─────────────────────────────────────────────────────────
#
# ``UBLVersionIDCheck``, ``CustomizationIDCheck`` and ``CopyIndicatorCheck`` of
# the Schematron. Both "TR1.2" and "TR1.2.1" are accepted for the
# customisation; every official sample, the 2025 ones included, writes "TR1.2".
UBL_VERSION_ID = "2.1"
CUSTOMIZATION_ID = "TR1.2"
CUSTOMIZATION_IDS = frozenset({"TR1.2", "TR1.2.1"})
COPY_INDICATOR = "false"

# Tax type code and scheme name of VAT, as the official samples carry them.
KDV_TAX_TYPE_CODE = "0015"
KDV_TAX_NAME = "KDV"

#: How the header ``TaxTotal/TaxAmount`` reads on a withholding invoice.
#:
#: ``net_of_withholding`` is what all three official withholding samples do:
#: the header amount is the VAT the seller still collects (3600 computed less
#: 3240 withheld is written as 360), while the ``TaxSubtotal`` beneath it keeps
#: the full computed VAT. ``computed`` writes the full computed VAT in the
#: header as well, which is how some integrators want it and how the general
#: sentence of the guide ("the total amount of the taxes computed") reads when
#: taken on its own. The guide never discusses the withholding case, so the
#: samples decide the default. On an invoice with no withholding the two are
#: the same number.
TaxTotalConvention = Literal["net_of_withholding", "computed"]

# ── unit codes ───────────────────────────────────────────────────────────────
#
# Platform unit labels to the UN/ECE Recommendation 20 codes GİB accepts. Every
# code on the right was checked on 2026-10-10 against ``UnitCodeList`` in
# ``UBL-TR_Codelist.xml`` (revision 2026-07-01). There is deliberately no
# default: a unit this table does not know is a validation error (TR-UNIT-01),
# never a silent "piece".
TR_UNIT_CODES: dict[str, str] = {
    "pcs": "C62",
    "pc": "C62",
    "pce": "C62",
    "each": "C62",
    "ea": "C62",
    "adet": "C62",
    "ad": "C62",
    "pair": "PR",
    "çift": "PR",
    "set": "SET",
    "takım": "SET",
    "m": "MTR",
    "lm": "MTR",
    "rm": "MTR",
    "mt": "MTR",
    "metre": "MTR",
    "km": "KMT",
    "cm": "CMT",
    "mm": "MMT",
    "m2": "MTK",
    "m²": "MTK",
    "sqm": "MTK",
    "m3": "MTQ",
    "m³": "MTQ",
    "cbm": "MTQ",
    "l": "LTR",
    "lt": "LTR",
    "kg": "KGM",
    "g": "GRM",
    "t": "TNE",
    "ton": "TNE",
    "tonne": "TNE",
    "ton_us": "STN",
    "lb": "LBR",
    "lbs": "LBR",
    "h": "HUR",
    "hr": "HUR",
    "hour": "HUR",
    "saat": "HUR",
    "day": "DAY",
    "d": "DAY",
    "gün": "DAY",
    "week": "WEE",
    "hafta": "WEE",
    "month": "MON",
    "ay": "MON",
    "year": "ANN",
    "yıl": "ANN",
    "kwh": "KWH",
    "kw": "KWT",
    "lsum": "LS",
    "ls": "LS",
    "psch": "LS",
    "götürü": "LS",
    "%": "P1",
}


def tr_unit_code(unit: str | None) -> str | None:
    """Map a platform unit label to its UBL-TR unit code, or ``None`` when unknown.

    Only surrounding space and ASCII letter case are ignored. ``str.lower`` is
    not used on purpose: it turns a Turkish capital "İ" into two characters.
    """
    text = (unit or "").strip()
    if not text:
        return None
    folded = "".join(chr(ord(ch) + 32) if "A" <= ch <= "Z" else ch for ch in text)
    return TR_UNIT_CODES.get(folded)


# ── model ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrAddress:
    """A postal address in the fields the UBL-TR schema names.

    ``district`` (ilçe, ``CitySubdivisionName``), ``city`` (il, ``CityName``)
    and ``country_name`` are mandatory in the schema; the rest is optional.
    """

    district: str
    city: str
    country_name: str = "Türkiye"
    street: str = ""
    building_number: str = ""
    building_name: str = ""
    room: str = ""
    postal_zone: str = ""
    region: str = ""
    country_code: str = ""


@dataclass(frozen=True)
class TrContact:
    """How to reach a party (``cac:Contact``)."""

    name: str = ""
    telephone: str = ""
    telefax: str = ""
    email: str = ""


@dataclass(frozen=True)
class TrParty:
    """The supplier or the customer.

    ``tax_number`` is a VKN (ten digits, a legal entity: ``name`` is then
    required) or a TCKN (eleven digits, a natural person: ``first_name`` and
    ``family_name`` are then required). Which one it is follows from its
    length and is never stated separately.

    Attributes:
        tax_number: VKN or TCKN, digits only.
        address: postal address.
        name: registered name (``PartyName/Name``).
        first_name: given name of a natural person.
        family_name: family name of a natural person.
        tax_office: vergi dairesi, written as ``PartyTaxScheme/TaxScheme/Name``.
        contact: optional contact details.
        website: optional ``WebsiteURI``.
        extra_ids: further identifiers as ``(schemeID, value)`` pairs, e.g.
            ``("MERSISNO", ...)`` or ``("TICARETSICILNO", ...)``.
    """

    tax_number: str
    address: TrAddress
    name: str = ""
    first_name: str = ""
    family_name: str = ""
    tax_office: str = ""
    contact: TrContact | None = None
    website: str = ""
    extra_ids: tuple[tuple[str, str], ...] = ()

    @property
    def id_scheme(self) -> str | None:
        """``"VKN"``, ``"TCKN"`` or ``None`` when the number is neither shape."""
        return classify_tax_number(self.tax_number)


@dataclass(frozen=True)
class TrDocumentRef:
    """A reference to another document. The schema makes the date mandatory.

    ``document_type_code`` is ``"IADE"`` on the billing reference of a return
    invoice, where ``id`` is the sixteen character ID of the invoice returned.
    """

    id: str
    issue_date: dt.date
    document_type_code: str = ""
    document_type: str = ""


@dataclass(frozen=True)
class TrPeriod:
    """The period the invoice covers (``cac:InvoicePeriod``)."""

    start_date: dt.date | None = None
    end_date: dt.date | None = None
    description: str = ""


@dataclass(frozen=True)
class TrAllowanceCharge:
    """A discount (``is_charge`` false) or a surcharge, on the document or on a line.

    ``multiplier_factor`` is written as given. The guide's example writes the
    rate as a fraction (0.1 for ten percent); the official samples are not
    consistent with each other on this, some write 0.05 and some write 5.
    """

    amount: Decimal
    is_charge: bool = False
    reason: str = ""
    multiplier_factor: Decimal | None = None
    base_amount: Decimal | None = None


@dataclass(frozen=True)
class TrTaxGroup:
    """The taxes of all lines that share one VAT rate and one withholding code.

    This is the unit the shared payment tax calculation works in, and ``taxes``
    is its result, untouched. ``vat_rate_pct`` and ``withholding_code`` are the
    inputs that calculation was given; the rules check that they agree with
    what the figures themselves report.

    Attributes:
        key: what a :class:`TrLine` names to say it belongs here.
        vat_rate_pct: the VAT rate in percent.
        taxable_amount: the net amount VAT was computed on.
        taxes: the computed figures.
        withholding_code: the three digit withholding code, empty when no VAT
            is withheld on this group.
        withholding_name: the description of the withholding category, written
            as ``TaxScheme/Name`` of the withholding subtotal.
        exemption_reason_code: ``TaxExemptionReasonCode``, required with its
            text when the VAT of the group is zero.
        exemption_reason: ``TaxExemptionReason``.
    """

    key: str
    vat_rate_pct: Decimal
    taxable_amount: Decimal
    taxes: PaymentTaxResult
    withholding_code: str = ""
    withholding_name: str = ""
    exemption_reason_code: str = ""
    exemption_reason: str = ""


@dataclass(frozen=True)
class TrLine:
    """One invoice line.

    The three VAT amounts are this line's share of its group's figures, as the
    shared calculation's ``allocate`` distributed them. They are optional as a
    set: a line without them is written without a line level tax block, which
    the schema allows. ``vat_withheld`` stays ``None`` on a line whose group
    has no withholding.
    """

    line_id: str
    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    line_amount: Decimal
    tax_group: str
    vat_amount: Decimal | None = None
    vat_withheld: Decimal | None = None
    vat_payable: Decimal | None = None
    description: str = ""
    note: str = ""
    seller_item_code: str = ""
    allowances: tuple[TrAllowanceCharge, ...] = ()


@dataclass(frozen=True)
class TrPaymentMeans:
    """How the invoice is to be paid (``cac:PaymentMeans``). ``code`` is UN/EDIFACT 4461."""

    code: str
    due_date: dt.date | None = None
    channel_code: str = ""
    instruction_note: str = ""
    payee_iban: str = ""
    payee_currency: str = ""
    payment_note: str = ""


@dataclass(frozen=True)
class TrTotals:
    """``cac:LegalMonetaryTotal``, stated by whoever assembled the invoice.

    The rules verify these against the lines and the tax figures; the writer
    prints them as given.

    Attributes:
        line_extension: sum of the line amounts.
        tax_exclusive: the taxable total after document allowances and charges.
        tax_inclusive: ``tax_exclusive`` plus the full computed VAT, also on a
            withholding invoice.
        payable: ``tax_inclusive`` less the VAT withheld by the customer.
        allowance_total: total of the allowances, when any.
        charge_total: total of the charges, when any.
        payable_rounding: rounding applied to reach ``payable``, when any.
    """

    line_extension: Decimal
    tax_exclusive: Decimal
    tax_inclusive: Decimal
    payable: Decimal
    allowance_total: Decimal | None = None
    charge_total: Decimal | None = None
    payable_rounding: Decimal | None = None


@dataclass(frozen=True)
class TrInvoice:
    """A UBL-TR invoice, ready to validate and render.

    Attributes:
        profile_id: the scenario, ``TEMELFATURA``, ``TICARIFATURA`` or
            ``EARSIVFATURA``.
        invoice_type: ``SATIS``, ``TEVKIFAT``, ``IADE`` or ``ISTISNA``.
        document_id: the sixteen character document ID. May be empty when the
            integrator assigns it; the document then carries an empty ``cbc:ID``.
        uuid: the ETTN.
        issue_date: date of issue.
        currency: ISO 4217 document currency.
        supplier: the seller.
        customer: the buyer.
        lines: at least one line.
        tax_groups: one per (VAT rate, withholding code) pair in use.
        totals: the monetary totals.
        issue_time: time of issue.
        exchange_rate: document currency to TRY, required when the currency
            is not TRY.
        exchange_rate_date: the date of that rate.
        notes: free text notes, in order. The amount in words goes here.
        order_reference: the customer's order.
        billing_references: the invoices a return invoice returns.
        despatch_references: delivery notes.
        contract_references: contracts.
        period: the period covered.
        allowance_charges: document level discounts and surcharges.
        payment_means: how to pay.
        payment_terms_note: free text payment terms.
        payment_due_date: due date written in the payment terms.
        customization_id: ``TR1.2`` unless the integrator asks for ``TR1.2.1``.
        tax_total_convention: see :data:`TaxTotalConvention`.
    """

    profile_id: str
    invoice_type: str
    document_id: str
    uuid: str
    issue_date: dt.date
    currency: str
    supplier: TrParty
    customer: TrParty
    lines: Sequence[TrLine]
    tax_groups: Sequence[TrTaxGroup]
    totals: TrTotals
    issue_time: dt.time | None = None
    exchange_rate: Decimal | None = None
    exchange_rate_date: dt.date | None = None
    notes: tuple[str, ...] = ()
    order_reference: TrDocumentRef | None = None
    billing_references: tuple[TrDocumentRef, ...] = ()
    despatch_references: tuple[TrDocumentRef, ...] = ()
    contract_references: tuple[TrDocumentRef, ...] = ()
    period: TrPeriod | None = None
    allowance_charges: tuple[TrAllowanceCharge, ...] = ()
    payment_means: tuple[TrPaymentMeans, ...] = ()
    payment_terms_note: str = ""
    payment_due_date: dt.date | None = None
    customization_id: str = CUSTOMIZATION_ID
    tax_total_convention: TaxTotalConvention = "net_of_withholding"


# ── reading the figures ──────────────────────────────────────────────────────


def figure_amount(figure: Figure) -> Decimal | None:
    """The amount of a figure that has one, ``None`` otherwise."""
    return figure.amount if figure.status == "value" else None


def has_withholding(group: TrTaxGroup) -> bool:
    """True when VAT is withheld on this group (its withheld figure is a value)."""
    return group.taxes.vat_withheld.status == "value"


def withholding_percent(group: TrTaxGroup) -> Decimal | None:
    """The withheld share of the VAT in percent, e.g. 40 for four tenths.

    Read from the fraction on the withheld figure, falling back to its
    ``rate_pct``. ``None`` when the figure states neither.
    """
    figure = group.taxes.vat_withheld
    if figure.numerator is not None and figure.denominator:
        return Decimal(figure.numerator) * 100 / Decimal(figure.denominator)
    return figure.rate_pct


def _sum_figures(groups: Sequence[TrTaxGroup], kind: str) -> Decimal | None:
    total = Decimal("0")
    for group in groups:
        figure: Figure = getattr(group.taxes, kind)
        if figure.status == "held":
            return None
        if figure.status == "value" and figure.amount is not None:
            total += figure.amount
    return total


def document_vat_computed(inv: TrInvoice) -> Decimal | None:
    """The computed VAT of all groups together, ``None`` when any is held."""
    return _sum_figures(inv.tax_groups, "vat_computed")


def document_vat_withheld(inv: TrInvoice) -> Decimal | None:
    """The withheld VAT of all groups together, ``None`` when any is held."""
    return _sum_figures(inv.tax_groups, "vat_withheld")


def document_vat_payable(inv: TrInvoice) -> Decimal | None:
    """The VAT the seller still collects, all groups together, ``None`` when any is held."""
    return _sum_figures(inv.tax_groups, "vat_payable")


def header_tax_amount(inv: TrInvoice) -> Decimal | None:
    """What ``TaxTotal/TaxAmount`` of the document carries under the chosen convention."""
    if inv.tax_total_convention == "computed":
        return document_vat_computed(inv)
    return document_vat_payable(inv)


# ── formatting ───────────────────────────────────────────────────────────────


def _money(value: Decimal, currency: str) -> str:
    """Format an amount with the subunit digits of its currency, two at most.

    The Schematron ``decimalCheck`` allows no more than two decimals. A
    currency with three is refused by TR-CUR-02 before anything is written.
    """
    places = min(minor_units(currency), 2)
    return str(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _plain(value: Decimal, max_places: int) -> str:
    """Format a number without exponent and without trailing zeros."""
    quantum = Decimal(1).scaleb(-max_places)
    text = f"{value.quantize(quantum, rounding=ROUND_HALF_UP):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _percent(value: Decimal) -> str:
    # "40", never "40.00": the Schematron joins the withholding code and this
    # text and looks the pair up in a list ("60140").
    return _plain(value, 4)


def _opt_amt(parent: ET.Element, local: str, value: Decimal | None, currency: str) -> None:
    """Write an amount element when there is an amount. A preview has holes; a document never does."""
    if value is not None:
        _amt(parent, local, _money(value, currency), currency)


def _text(parent: ET.Element, prefix: str, local: str, value: str | None) -> None:
    if value:
        _sub(parent, prefix, local, value)


# ── element builders, each in the order of its XSD sequence ──────────────────


def _address(parent: ET.Element, address: TrAddress) -> None:
    # AddressType: Room, StreetName, BuildingName, BuildingNumber,
    # CitySubdivisionName, CityName, PostalZone, Region, Country.
    node = _sub(parent, "cac", "PostalAddress")
    _text(node, "cbc", "Room", address.room)
    _text(node, "cbc", "StreetName", address.street)
    _text(node, "cbc", "BuildingName", address.building_name)
    _text(node, "cbc", "BuildingNumber", address.building_number)
    _sub(node, "cbc", "CitySubdivisionName", address.district)
    _sub(node, "cbc", "CityName", address.city)
    _text(node, "cbc", "PostalZone", address.postal_zone)
    _text(node, "cbc", "Region", address.region)
    country = _sub(node, "cac", "Country")
    _text(country, "cbc", "IdentificationCode", address.country_code)
    _sub(country, "cbc", "Name", address.country_name)


def _party_identification(parent: ET.Element, scheme: str, value: str) -> None:
    node = _sub(parent, "cac", "PartyIdentification")
    _sub(node, "cbc", "ID", value).set("schemeID", scheme)


def _party(parent: ET.Element, wrapper: str, party: TrParty) -> None:
    # PartyType: WebsiteURI, PartyIdentification, PartyName, PostalAddress,
    # PartyTaxScheme, Contact, Person.
    node = _sub(_sub(parent, "cac", wrapper), "cac", "Party")
    _text(node, "cbc", "WebsiteURI", party.website)
    # An unclassifiable number is still written, under the scheme its length
    # is nearest to, so that a preview shows what was entered. TR-PARTY-01
    # refuses the document.
    _party_identification(node, party.id_scheme or "VKN", party.tax_number)
    for scheme, value in party.extra_ids:
        _party_identification(node, scheme, value)
    if party.name:
        _sub(_sub(node, "cac", "PartyName"), "cbc", "Name", party.name)
    _address(node, party.address)
    if party.tax_office:
        scheme_node = _sub(_sub(node, "cac", "PartyTaxScheme"), "cac", "TaxScheme")
        _sub(scheme_node, "cbc", "Name", party.tax_office)
    contact = party.contact
    if contact and (contact.name or contact.telephone or contact.telefax or contact.email):
        contact_node = _sub(node, "cac", "Contact")
        _text(contact_node, "cbc", "Name", contact.name)
        _text(contact_node, "cbc", "Telephone", contact.telephone)
        _text(contact_node, "cbc", "Telefax", contact.telefax)
        _text(contact_node, "cbc", "ElectronicMail", contact.email)
    if party.first_name or party.family_name:
        person = _sub(node, "cac", "Person")
        _sub(person, "cbc", "FirstName", party.first_name)
        _sub(person, "cbc", "FamilyName", party.family_name)


def _signature(root: ET.Element, inv: TrInvoice) -> None:
    """Write the mandatory ``cac:Signature`` block for an unsigned document.

    The schema demands at least one. Following the official samples it names
    the supplier as signatory, with the supplier's address, and points at the
    ``ds:Signature`` the integrator will add: the URI is ``#Signature_`` plus
    the document ID, the form the 2025 samples use.
    """
    supplier = inv.supplier
    node = _sub(root, "cac", "Signature")
    _sub(node, "cbc", "ID", supplier.tax_number).set("schemeID", "VKN_TCKN")
    signatory = _sub(node, "cac", "SignatoryParty")
    _party_identification(signatory, supplier.id_scheme or "VKN", supplier.tax_number)
    _address(signatory, supplier.address)
    attachment = _sub(node, "cac", "DigitalSignatureAttachment")
    reference = _sub(attachment, "cac", "ExternalReference")
    uri = f"#Signature_{inv.document_id}" if inv.document_id else "#Signature"
    _sub(reference, "cbc", "URI", uri)


def _document_reference(parent: ET.Element, local: str, ref: TrDocumentRef) -> ET.Element:
    # DocumentReferenceType: ID, IssueDate, DocumentTypeCode, DocumentType.
    node = _sub(parent, "cac", local)
    _sub(node, "cbc", "ID", ref.id)
    _sub(node, "cbc", "IssueDate", ref.issue_date.isoformat())
    _text(node, "cbc", "DocumentTypeCode", ref.document_type_code)
    _text(node, "cbc", "DocumentType", ref.document_type)
    return node


def _allowance_charge(parent: ET.Element, item: TrAllowanceCharge, currency: str) -> None:
    # AllowanceChargeType: ChargeIndicator, AllowanceChargeReason,
    # MultiplierFactorNumeric, Amount, BaseAmount.
    node = _sub(parent, "cac", "AllowanceCharge")
    _sub(node, "cbc", "ChargeIndicator", "true" if item.is_charge else "false")
    _text(node, "cbc", "AllowanceChargeReason", item.reason)
    if item.multiplier_factor is not None:
        _sub(node, "cbc", "MultiplierFactorNumeric", _plain(item.multiplier_factor, 6))
    _amt(node, "Amount", _money(item.amount, currency), currency)
    _opt_amt(node, "BaseAmount", item.base_amount, currency)


def _payment_means(parent: ET.Element, means: TrPaymentMeans) -> None:
    # PaymentMeansType: PaymentMeansCode, PaymentDueDate, PaymentChannelCode,
    # InstructionNote, PayeeFinancialAccount{ID, CurrencyCode, PaymentNote}.
    node = _sub(parent, "cac", "PaymentMeans")
    _sub(node, "cbc", "PaymentMeansCode", means.code)
    if means.due_date:
        _sub(node, "cbc", "PaymentDueDate", means.due_date.isoformat())
    _text(node, "cbc", "PaymentChannelCode", means.channel_code)
    _text(node, "cbc", "InstructionNote", means.instruction_note)
    if means.payee_iban:
        account = _sub(node, "cac", "PayeeFinancialAccount")
        _sub(account, "cbc", "ID", means.payee_iban)
        _text(account, "cbc", "CurrencyCode", means.payee_currency)
        _text(account, "cbc", "PaymentNote", means.payment_note)


def _vat_subtotal(
    parent: ET.Element,
    *,
    taxable: Decimal | None,
    tax: Decimal | None,
    sequence: int,
    group: TrTaxGroup,
    currency: str,
) -> None:
    # TaxSubtotalType: TaxableAmount, TaxAmount, CalculationSequenceNumeric,
    # Percent, TaxCategory{TaxExemptionReasonCode, TaxExemptionReason,
    # TaxScheme{Name, TaxTypeCode}}.
    node = _sub(parent, "cac", "TaxSubtotal")
    _opt_amt(node, "TaxableAmount", taxable, currency)
    _opt_amt(node, "TaxAmount", tax, currency)
    _sub(node, "cbc", "CalculationSequenceNumeric", str(sequence))
    _sub(node, "cbc", "Percent", _percent(group.vat_rate_pct))
    category = _sub(node, "cac", "TaxCategory")
    _text(category, "cbc", "TaxExemptionReasonCode", group.exemption_reason_code)
    _text(category, "cbc", "TaxExemptionReason", group.exemption_reason)
    scheme = _sub(category, "cac", "TaxScheme")
    _sub(scheme, "cbc", "Name", KDV_TAX_NAME)
    _sub(scheme, "cbc", "TaxTypeCode", KDV_TAX_TYPE_CODE)


def _withholding_subtotal(
    parent: ET.Element,
    *,
    taxable: Decimal | None,
    tax: Decimal | None,
    group: TrTaxGroup,
    currency: str,
) -> None:
    # The base of a withholding is the computed VAT, and the percent is the
    # withheld fraction of it. No CalculationSequenceNumeric: the samples
    # carry none here.
    node = _sub(parent, "cac", "TaxSubtotal")
    _opt_amt(node, "TaxableAmount", taxable, currency)
    _opt_amt(node, "TaxAmount", tax, currency)
    percent = withholding_percent(group)
    if percent is not None:
        _sub(node, "cbc", "Percent", _percent(percent))
    scheme = _sub(_sub(node, "cac", "TaxCategory"), "cac", "TaxScheme")
    _text(scheme, "cbc", "Name", group.withholding_name)
    _sub(scheme, "cbc", "TaxTypeCode", group.withholding_code)


def _line(root: ET.Element, line: TrLine, groups: dict[str, TrTaxGroup], inv: TrInvoice) -> None:
    # InvoiceLineType: ID, Note, InvoicedQuantity, LineExtensionAmount,
    # AllowanceCharge, TaxTotal, WithholdingTaxTotal, Item, Price.
    currency = inv.currency
    node = _sub(root, "cac", "InvoiceLine")
    _sub(node, "cbc", "ID", line.line_id)
    _text(node, "cbc", "Note", line.note)
    quantity = _sub(node, "cbc", "InvoicedQuantity", _plain(line.quantity, 8))
    # An unknown unit is written as entered so a preview shows it; TR-UNIT-01
    # refuses the document.
    quantity.set("unitCode", tr_unit_code(line.unit) or line.unit)
    _amt(node, "LineExtensionAmount", _money(line.line_amount, currency), currency)
    for item in line.allowances:
        _allowance_charge(node, item, currency)

    group = groups.get(line.tax_group)
    if group is not None and line.vat_amount is not None:
        tax_total = _sub(node, "cac", "TaxTotal")
        header = line.vat_amount if inv.tax_total_convention == "computed" else line.vat_payable
        _opt_amt(tax_total, "TaxAmount", header, currency)
        _vat_subtotal(
            tax_total,
            taxable=line.line_amount,
            tax=line.vat_amount,
            sequence=1,
            group=group,
            currency=currency,
        )
        if has_withholding(group) and line.vat_withheld is not None:
            withholding = _sub(node, "cac", "WithholdingTaxTotal")
            _amt(withholding, "TaxAmount", _money(line.vat_withheld, currency), currency)
            _withholding_subtotal(
                withholding,
                taxable=line.vat_amount,
                tax=line.vat_withheld,
                group=group,
                currency=currency,
            )

    # ItemType: Description precedes Name.
    item_node = _sub(node, "cac", "Item")
    _text(item_node, "cbc", "Description", line.description)
    _sub(item_node, "cbc", "Name", line.name)
    if line.seller_item_code:
        _sub(_sub(item_node, "cac", "SellersItemIdentification"), "cbc", "ID", line.seller_item_code)
    price = _sub(node, "cac", "Price")
    _amt(price, "PriceAmount", _plain(line.unit_price, 8), currency)


def build_ubl_tr_xml(inv: TrInvoice, *, strict: bool = True, today: dt.date | None = None) -> bytes:
    """Render a :class:`TrInvoice` as unsigned UBL-TR 1.2.1 XML bytes.

    The output is UTF-8 with an XML declaration and no byte order mark, and is
    deterministic: the same invoice always yields the same bytes.

    Two containers exist only to be filled by the integrator who signs the
    document. ``ext:UBLExtensions`` is mandatory in the schema and must hold
    one element from a foreign namespace, so it holds an empty
    ``SignaturePlaceholder`` in this platform's own namespace where the
    ``ds:Signature`` will go (GİB's samples put a schema editor's dummy element
    there, which is not something to imitate). ``cac:Signature`` is mandatory
    too and names the supplier as the signatory.

    Args:
        inv: the invoice.
        strict: refuse to render when :func:`~app.modules.einvoice.rules_tr.check_tr`
            reports a fatal violation. With ``strict=False`` the document is
            written as far as the data goes, for a preview: an amount that is
            not known is left out, an unknown unit is written as entered.
        today: the day the issue date is judged against under ``strict``,
            see :func:`~app.modules.einvoice.rules_tr.check_tr`.

    Returns:
        The XML document.

    Raises:
        EInvoiceError: under ``strict`` when a fatal rule is violated. The
            message lists every violation.
    """
    if strict:
        from app.modules.einvoice.rules import FATAL
        from app.modules.einvoice.rules_tr import check_tr

        fatal = [violation for violation in check_tr(inv, today=today) if violation.severity == FATAL]
        if fatal:
            raise EInvoiceError("; ".join(str(violation) for violation in fatal))

    currency = inv.currency
    root = ET.Element(f"{{{INV}}}Invoice")

    # InvoiceType sequence, in order. Elements this writer never emits are
    # left out of the list: TaxCurrencyCode, PricingCurrencyCode,
    # PaymentCurrencyCode, AccountingCost, ReceiptDocumentReference,
    # OriginatorDocumentReference, AdditionalDocumentReference, the further
    # parties, Delivery and the other exchange rates.
    extensions = _sub(root, "ext", "UBLExtensions")
    content = _sub(_sub(extensions, "ext", "UBLExtension"), "ext", "ExtensionContent")
    ET.SubElement(content, f"{{{UNSIGNED}}}SignaturePlaceholder")

    _sub(root, "cbc", "UBLVersionID", UBL_VERSION_ID)
    _sub(root, "cbc", "CustomizationID", inv.customization_id)
    _sub(root, "cbc", "ProfileID", inv.profile_id)
    _sub(root, "cbc", "ID", inv.document_id)
    _sub(root, "cbc", "CopyIndicator", COPY_INDICATOR)
    _sub(root, "cbc", "UUID", inv.uuid)
    _sub(root, "cbc", "IssueDate", inv.issue_date.isoformat())
    if inv.issue_time is not None:
        _sub(root, "cbc", "IssueTime", inv.issue_time.replace(microsecond=0, tzinfo=None).isoformat())
    _sub(root, "cbc", "InvoiceTypeCode", inv.invoice_type)
    for note in inv.notes:
        _text(root, "cbc", "Note", note)
    _sub(root, "cbc", "DocumentCurrencyCode", currency)
    _sub(root, "cbc", "LineCountNumeric", str(len(inv.lines)))

    period = inv.period
    if period and (period.start_date or period.end_date or period.description):
        period_node = _sub(root, "cac", "InvoicePeriod")
        if period.start_date:
            _sub(period_node, "cbc", "StartDate", period.start_date.isoformat())
        if period.end_date:
            _sub(period_node, "cbc", "EndDate", period.end_date.isoformat())
        _text(period_node, "cbc", "Description", period.description)
    if inv.order_reference:
        order = _sub(root, "cac", "OrderReference")
        _sub(order, "cbc", "ID", inv.order_reference.id)
        _sub(order, "cbc", "IssueDate", inv.order_reference.issue_date.isoformat())
    for ref in inv.billing_references:
        _document_reference(_sub(root, "cac", "BillingReference"), "InvoiceDocumentReference", ref)
    for ref in inv.despatch_references:
        _document_reference(root, "DespatchDocumentReference", ref)
    for ref in inv.contract_references:
        _document_reference(root, "ContractDocumentReference", ref)

    _signature(root, inv)
    _party(root, "AccountingSupplierParty", inv.supplier)
    _party(root, "AccountingCustomerParty", inv.customer)

    for means in inv.payment_means:
        _payment_means(root, means)
    if inv.payment_terms_note or inv.payment_due_date:
        terms = _sub(root, "cac", "PaymentTerms")
        _text(terms, "cbc", "Note", inv.payment_terms_note)
        if inv.payment_due_date:
            _sub(terms, "cbc", "PaymentDueDate", inv.payment_due_date.isoformat())
    for item in inv.allowance_charges:
        _allowance_charge(root, item, currency)
    if inv.exchange_rate is not None:
        # ExchangeRateType: SourceCurrencyCode, TargetCurrencyCode,
        # CalculationRate, Date.
        rate = _sub(root, "cac", "PricingExchangeRate")
        _sub(rate, "cbc", "SourceCurrencyCode", currency)
        _sub(rate, "cbc", "TargetCurrencyCode", "TRY")
        _sub(rate, "cbc", "CalculationRate", _plain(inv.exchange_rate, 6))
        if inv.exchange_rate_date:
            _sub(rate, "cbc", "Date", inv.exchange_rate_date.isoformat())

    tax_total = _sub(root, "cac", "TaxTotal")
    _opt_amt(tax_total, "TaxAmount", header_tax_amount(inv), currency)
    for sequence, group in enumerate(inv.tax_groups, start=1):
        _vat_subtotal(
            tax_total,
            taxable=group.taxable_amount,
            tax=figure_amount(group.taxes.vat_computed),
            sequence=sequence,
            group=group,
            currency=currency,
        )

    withheld_groups = [group for group in inv.tax_groups if has_withholding(group)]
    if withheld_groups:
        withholding = _sub(root, "cac", "WithholdingTaxTotal")
        _opt_amt(withholding, "TaxAmount", document_vat_withheld(inv), currency)
        for group in withheld_groups:
            _withholding_subtotal(
                withholding,
                taxable=figure_amount(group.taxes.vat_computed),
                tax=figure_amount(group.taxes.vat_withheld),
                group=group,
                currency=currency,
            )

    # MonetaryTotalType: LineExtensionAmount, TaxExclusiveAmount,
    # TaxInclusiveAmount, AllowanceTotalAmount, ChargeTotalAmount,
    # PayableRoundingAmount, PayableAmount.
    totals = inv.totals
    monetary = _sub(root, "cac", "LegalMonetaryTotal")
    _amt(monetary, "LineExtensionAmount", _money(totals.line_extension, currency), currency)
    _amt(monetary, "TaxExclusiveAmount", _money(totals.tax_exclusive, currency), currency)
    _amt(monetary, "TaxInclusiveAmount", _money(totals.tax_inclusive, currency), currency)
    _opt_amt(monetary, "AllowanceTotalAmount", totals.allowance_total, currency)
    _opt_amt(monetary, "ChargeTotalAmount", totals.charge_total, currency)
    _opt_amt(monetary, "PayableRoundingAmount", totals.payable_rounding, currency)
    _amt(monetary, "PayableAmount", _money(totals.payable, currency), currency)

    groups = {group.key: group for group in inv.tax_groups}
    for line in inv.lines:
        _line(root, line, groups, inv)

    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + _tostring(root, INV) + b"\n"
