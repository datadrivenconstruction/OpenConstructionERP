"""Unit tests for the UBL-TR 1.2.1 (e-Fatura / e-Arşiv Fatura) invoice writer.

Structural assertions with ElementTree, one byte-stable golden document, the
element order against sequences derived from the official XSD, and an optional
validation against that XSD when a copy of it is available locally.

Every company, person and tax number here is invented. The tax numbers were
generated with ``tr_ids`` from made-up stems (111222333, 987654321, ...), so
they carry correct check digits without being taken from anyone.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.core.payment_taxes import Figure, PaymentTaxResult
from app.modules.einvoice.cii import EInvoiceError
from app.modules.einvoice.rules import FATAL
from app.modules.einvoice.rules_tr import check_tr
from app.modules.einvoice.tr_words import amount_in_words
from app.modules.einvoice.ubl import CAC, CBC, INV
from app.modules.einvoice.ubl_tr import (
    EXT,
    UNSIGNED,
    TrAddress,
    TrAllowanceCharge,
    TrContact,
    TrDocumentRef,
    TrInvoice,
    TrLine,
    TrParty,
    TrPaymentMeans,
    TrPeriod,
    TrTaxGroup,
    TrTotals,
    build_ubl_tr_xml,
    tr_unit_code,
)

NS = {"inv": INV, "cac": CAC, "cbc": CBC, "ext": EXT}
TODAY = dt.date(2026, 10, 10)
GOLDEN = Path(__file__).parent / "data" / "einvoice_tr" / "tevkifat_ticarifatura.xml"

# Synthetic identifiers with valid check digits (see the module docstring).
SUPPLIER_VKN = "1112223339"
CUSTOMER_VKN = "9876543217"
PERSON_TCKN = "10000000146"

# A withholding code and percent pair that exists in GİB's code list: checked
# on 2026-10-10 against ``WithholdingTaxTypeWithPercent`` in
# ``UBL-TR_Codelist.xml`` (e-Fatura package, revision 2026-07-01), which holds
# the entry "60140". The fraction is test data, not a statement of the law.
WH_CODE = "601"
WH_FRACTION = (4, 10)
WH_NAME = "Yapım işleri ile bu işlerle birlikte ifa edilen mühendislik-mimarlık ve etüt-proje hizmetleri"


# ── synthetic figures ────────────────────────────────────────────────────────


def fig(kind: str, amount: Decimal | None, *, status: str = "value", **kw: object) -> Figure:
    """A hand-built figure. The real ones come from ``compute_payment_taxes``."""
    fields: dict = {
        "kind": kind,
        "status": status,
        "amount": amount,
        "base": None,
        "rate_pct": None,
        "numerator": None,
        "denominator": None,
        "code": "",
        "legal_reference": "",
        "effective_from": None,
        "review_status": "confirmed" if status == "value" else "",
        "overridden": False,
        "reason_key": "",
        "reason_params": {},
    }
    fields.update(kw)
    return Figure(**fields)


def not_applicable(kind: str) -> Figure:
    return fig(kind, None, status="not_applicable", reason_key="not_applicable")


def held(kind: str, reason: str = "not_chosen") -> Figure:
    return fig(kind, None, status="held", reason_key=reason)


def taxes(
    net: str,
    rate: str,
    *,
    withholding: tuple[str, int, int] | None = None,
    quantum: str = "0.01",
) -> PaymentTaxResult:
    """Figures for one group, rounded the way the shared calculation specifies.

    VAT is rounded half up once, the withheld part is a fraction of the rounded
    VAT rounded half up once, and the payable VAT is their difference.
    """
    q = Decimal(quantum)
    base = Decimal(net)
    pct = Decimal(rate)
    vat = (base * pct / 100).quantize(q, rounding=ROUND_HALF_UP)
    computed = fig("vat_computed", vat, base=base, rate_pct=pct)
    if withholding is None:
        return PaymentTaxResult(
            vat_computed=computed,
            vat_withheld=not_applicable("vat_withheld"),
            vat_payable=fig("vat_payable", vat, base=base, rate_pct=pct),
            income_withheld=not_applicable("income_withheld"),
            stamp_duty=not_applicable("stamp_duty"),
        )
    code, numerator, denominator = withholding
    withheld = (vat * numerator / denominator).quantize(q, rounding=ROUND_HALF_UP)
    return PaymentTaxResult(
        vat_computed=computed,
        vat_withheld=fig("vat_withheld", withheld, base=vat, numerator=numerator, denominator=denominator, code=code),
        vat_payable=fig("vat_payable", vat - withheld, base=base, rate_pct=pct),
        income_withheld=not_applicable("income_withheld"),
        stamp_duty=not_applicable("stamp_duty"),
    )


# ── synthetic invoices ───────────────────────────────────────────────────────


def supplier() -> TrParty:
    return TrParty(
        tax_number=SUPPLIER_VKN,
        name="Örnek Mekanik Tesisat Taahhüt A.Ş.",
        tax_office="Çankaya",
        address=TrAddress(
            street="Şehit Öğretmen Caddesi",
            building_number="12/A",
            district="Çankaya",
            city="Ankara",
            postal_zone="06690",
            country_code="TR",
        ),
        contact=TrContact(telephone="+90 312 000 00 00", email="info@datadrivenconstruction.io"),
        extra_ids=(("MERSISNO", "0111222333900017"),),
    )


def customer() -> TrParty:
    return TrParty(
        tax_number=CUSTOMER_VKN,
        name="Güneş Yapı İnşaat Sanayi ve Ticaret Ltd. Şti.",
        tax_office="Zincirlikuyu",
        address=TrAddress(
            street="Büyükdere Caddesi",
            building_number="100",
            district="Şişli",
            city="İstanbul",
            postal_zone="34394",
        ),
    )


def person() -> TrParty:
    return TrParty(
        tax_number=PERSON_TCKN,
        first_name="Ayşe Gül",
        family_name="Çağlayan",
        address=TrAddress(street="Iğdır Sokak", building_number="3", district="Üsküdar", city="İstanbul"),
    )


def satis_invoice() -> TrInvoice:
    """A plain sale in lira: two lines at 20% VAT, no withholding."""
    return TrInvoice(
        profile_id="TEMELFATURA",
        invoice_type="SATIS",
        document_id="OMT2026000000001",
        uuid="6f1c2d3e-4a5b-4c6d-8e7f-001122334455",
        issue_date=dt.date(2026, 9, 30),
        issue_time=dt.time(14, 5, 9),
        currency="TRY",
        supplier=supplier(),
        customer=customer(),
        notes=(amount_in_words(Decimal("51000.00"), "TRY"),),
        lines=(
            TrLine(
                line_id="1",
                name="Çelik boru DN100 montajı",
                quantity=Decimal("120"),
                unit="m",
                unit_price=Decimal("250.00"),
                line_amount=Decimal("30000.00"),
                tax_group="kdv20",
                vat_amount=Decimal("6000.00"),
                vat_payable=Decimal("6000.00"),
                seller_item_code="MT-0100",
            ),
            TrLine(
                line_id="2",
                name="Yangın pompa grubu",
                description="Elektrikli ve dizel pompalı, kumanda panosu dahil",
                quantity=Decimal("1"),
                unit="set",
                unit_price=Decimal("12500.00"),
                line_amount=Decimal("12500.00"),
                tax_group="kdv20",
                vat_amount=Decimal("2500.00"),
                vat_payable=Decimal("2500.00"),
            ),
        ),
        tax_groups=(
            TrTaxGroup(
                key="kdv20",
                vat_rate_pct=Decimal("20"),
                taxable_amount=Decimal("42500.00"),
                taxes=taxes("42500.00", "20"),
            ),
        ),
        totals=TrTotals(
            line_extension=Decimal("42500.00"),
            tax_exclusive=Decimal("42500.00"),
            tax_inclusive=Decimal("51000.00"),
            payable=Decimal("51000.00"),
        ),
        payment_means=(
            TrPaymentMeans(code="42", due_date=dt.date(2026, 10, 30), payee_iban="TR000000000000000000000000"),
        ),
        payment_terms_note="30 gün vadeli",
    )


def tevkifat_invoice() -> TrInvoice:
    """A progress payment invoice with VAT withheld by the customer on both lines."""
    group = TrTaxGroup(
        key="kdv20-601",
        vat_rate_pct=Decimal("20"),
        taxable_amount=Decimal("100000.00"),
        taxes=taxes("100000.00", "20", withholding=(WH_CODE, *WH_FRACTION)),
        withholding_code=WH_CODE,
        withholding_name=WH_NAME,
    )
    return TrInvoice(
        profile_id="TICARIFATURA",
        invoice_type="TEVKIFAT",
        document_id="OMT2026000000002",
        uuid="0a1b2c3d-4e5f-4a6b-9c7d-8e9f00112233",
        issue_date=dt.date(2026, 9, 30),
        issue_time=dt.time(10, 30, 0),
        currency="TRY",
        supplier=supplier(),
        customer=customer(),
        notes=(
            "Hakediş No: 3 - Mekanik tesisat yapım işi",
            amount_in_words(Decimal("112000.00"), "TRY"),
        ),
        contract_references=(TrDocumentRef(id="SZL-2026-014", issue_date=dt.date(2026, 3, 2)),),
        period=TrPeriod(start_date=dt.date(2026, 9, 1), end_date=dt.date(2026, 9, 30)),
        lines=(
            TrLine(
                line_id="1",
                name="Isıtma ve soğutma tesisatı imalatı",
                quantity=Decimal("1"),
                unit="lsum",
                unit_price=Decimal("60000.00"),
                line_amount=Decimal("60000.00"),
                tax_group="kdv20-601",
                vat_amount=Decimal("12000.00"),
                vat_withheld=Decimal("4800.00"),
                vat_payable=Decimal("7200.00"),
            ),
            TrLine(
                line_id="2",
                name="Yangın söndürme tesisatı imalatı",
                quantity=Decimal("1"),
                unit="lsum",
                unit_price=Decimal("40000.00"),
                line_amount=Decimal("40000.00"),
                tax_group="kdv20-601",
                vat_amount=Decimal("8000.00"),
                vat_withheld=Decimal("3200.00"),
                vat_payable=Decimal("4800.00"),
            ),
        ),
        tax_groups=(group,),
        totals=TrTotals(
            line_extension=Decimal("100000.00"),
            tax_exclusive=Decimal("100000.00"),
            tax_inclusive=Decimal("120000.00"),
            payable=Decimal("112000.00"),
        ),
    )


def eur_invoice() -> TrInvoice:
    """A sale in euro, which obliges the document to state the rate to lira."""
    return TrInvoice(
        profile_id="TICARIFATURA",
        invoice_type="SATIS",
        document_id="OMT2026000000003",
        uuid="11111111-2222-4333-8444-555555555555",
        issue_date=dt.date(2026, 9, 30),
        currency="EUR",
        exchange_rate=Decimal("48.1250"),
        exchange_rate_date=dt.date(2026, 9, 29),
        supplier=supplier(),
        customer=customer(),
        lines=(
            TrLine(
                line_id="1",
                name="Plakalı eşanjör",
                quantity=Decimal("2"),
                unit="adet",
                unit_price=Decimal("1850.50"),
                line_amount=Decimal("3701.00"),
                tax_group="kdv20",
            ),
        ),
        tax_groups=(
            TrTaxGroup(
                key="kdv20", vat_rate_pct=Decimal("20"), taxable_amount=Decimal("3701.00"), taxes=taxes("3701.00", "20")
            ),
        ),
        totals=TrTotals(
            line_extension=Decimal("3701.00"),
            tax_exclusive=Decimal("3701.00"),
            tax_inclusive=Decimal("4441.20"),
            payable=Decimal("4441.20"),
        ),
    )


def person_invoice() -> TrInvoice:
    """An e-Arşiv invoice to a natural person, identified by a TCKN."""
    base = satis_invoice()
    return replace(
        base,
        profile_id="EARSIVFATURA",
        document_id="OMA2026000000001",
        uuid="22222222-3333-4444-8555-666666666666",
        customer=person(),
    )


def two_rate_invoice() -> TrInvoice:
    """Three lines over two VAT rates, with a line discount on the first."""
    return TrInvoice(
        profile_id="TEMELFATURA",
        invoice_type="SATIS",
        document_id="OMT2026000000004",
        uuid="33333333-4444-4555-8666-777777777777",
        issue_date=dt.date(2026, 9, 30),
        currency="TRY",
        supplier=supplier(),
        customer=customer(),
        lines=(
            TrLine(
                line_id="1",
                name="Havalandırma kanalı",
                quantity=Decimal("40"),
                unit="m2",
                unit_price=Decimal("500.00"),
                line_amount=Decimal("19000.00"),
                tax_group="kdv20",
                vat_amount=Decimal("3800.00"),
                vat_payable=Decimal("3800.00"),
                allowances=(
                    TrAllowanceCharge(
                        amount=Decimal("1000.00"),
                        reason="İskonto",
                        multiplier_factor=Decimal("0.05"),
                        base_amount=Decimal("20000.00"),
                    ),
                ),
            ),
            TrLine(
                line_id="2",
                name="Devreye alma hizmeti",
                quantity=Decimal("16"),
                unit="hour",
                unit_price=Decimal("750.00"),
                line_amount=Decimal("12000.00"),
                tax_group="kdv20",
                vat_amount=Decimal("2400.00"),
                vat_payable=Decimal("2400.00"),
            ),
            TrLine(
                line_id="3",
                name="Teknik yayın",
                quantity=Decimal("3"),
                unit="pcs",
                unit_price=Decimal("333.33"),
                line_amount=Decimal("999.99"),
                tax_group="kdv10",
                vat_amount=Decimal("100.00"),
                vat_payable=Decimal("100.00"),
            ),
        ),
        tax_groups=(
            TrTaxGroup(
                key="kdv20",
                vat_rate_pct=Decimal("20"),
                taxable_amount=Decimal("31000.00"),
                taxes=taxes("31000.00", "20"),
            ),
            TrTaxGroup(
                key="kdv10", vat_rate_pct=Decimal("10"), taxable_amount=Decimal("999.99"), taxes=taxes("999.99", "10")
            ),
        ),
        totals=TrTotals(
            line_extension=Decimal("32999.99"),
            tax_exclusive=Decimal("31999.99"),
            tax_inclusive=Decimal("38299.99"),
            payable=Decimal("38299.99"),
            allowance_total=Decimal("1000.00"),
        ),
    )


def iade_invoice() -> TrInvoice:
    """A return of the second line of :func:`satis_invoice`, positive amounts under type IADE."""
    return TrInvoice(
        profile_id="TEMELFATURA",
        invoice_type="IADE",
        document_id="OMT2026000000005",
        uuid="44444444-5555-4666-8777-888888888888",
        issue_date=dt.date(2026, 10, 5),
        currency="TRY",
        supplier=supplier(),
        customer=customer(),
        billing_references=(
            TrDocumentRef(id="OMT2026000000001", issue_date=dt.date(2026, 9, 30), document_type_code="IADE"),
        ),
        lines=(
            TrLine(
                line_id="1",
                name="Yangın pompa grubu",
                quantity=Decimal("1"),
                unit="set",
                unit_price=Decimal("12500.00"),
                line_amount=Decimal("12500.00"),
                tax_group="kdv20",
            ),
        ),
        tax_groups=(
            TrTaxGroup(
                key="kdv20",
                vat_rate_pct=Decimal("20"),
                taxable_amount=Decimal("12500.00"),
                taxes=taxes("12500.00", "20"),
            ),
        ),
        totals=TrTotals(
            line_extension=Decimal("12500.00"),
            tax_exclusive=Decimal("12500.00"),
            tax_inclusive=Decimal("15000.00"),
            payable=Decimal("15000.00"),
        ),
    )


def istisna_invoice() -> TrInvoice:
    """A fully exempt supply. Code 350 is in GİB's exemption list for type ISTISNA."""
    return TrInvoice(
        profile_id="TEMELFATURA",
        invoice_type="ISTISNA",
        document_id="OMT2026000000006",
        uuid="55555555-6666-4777-8888-999999999999",
        issue_date=dt.date(2026, 9, 30),
        currency="TRY",
        supplier=supplier(),
        customer=customer(),
        lines=(
            TrLine(
                line_id="1",
                name="Mühendislik hizmeti",
                quantity=Decimal("5"),
                unit="day",
                unit_price=Decimal("8000.00"),
                line_amount=Decimal("40000.00"),
                tax_group="istisna",
            ),
        ),
        tax_groups=(
            TrTaxGroup(
                key="istisna",
                vat_rate_pct=Decimal("0"),
                taxable_amount=Decimal("40000.00"),
                taxes=taxes("40000.00", "0"),
                exemption_reason_code="350",
                exemption_reason="Diğerleri",
            ),
        ),
        totals=TrTotals(
            line_extension=Decimal("40000.00"),
            tax_exclusive=Decimal("40000.00"),
            tax_inclusive=Decimal("40000.00"),
            payable=Decimal("40000.00"),
        ),
    )


SCENARIOS = {
    "satis": satis_invoice,
    "tevkifat": tevkifat_invoice,
    "eur": eur_invoice,
    "person": person_invoice,
    "two_rates": two_rate_invoice,
    "iade": iade_invoice,
    "istisna": istisna_invoice,
}


def render(inv: TrInvoice, **kw: object) -> ET.Element:
    return ET.fromstring(build_ubl_tr_xml(inv, today=TODAY, **kw))


def text(root: ET.Element, path: str) -> str | None:
    return root.findtext(path, namespaces=NS)


# ── every scenario is clean ──────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_has_no_fatal_violation_and_renders(name: str) -> None:
    inv = SCENARIOS[name]()
    fatal = [v for v in check_tr(inv, today=TODAY) if v.severity == FATAL]
    assert fatal == []
    root = render(inv)
    assert root.tag == f"{{{INV}}}Invoice"


# ── header ───────────────────────────────────────────────────────────────────


def test_header_constants_and_identifiers() -> None:
    root = render(satis_invoice())
    assert text(root, "cbc:UBLVersionID") == "2.1"
    assert text(root, "cbc:CustomizationID") == "TR1.2"
    assert text(root, "cbc:ProfileID") == "TEMELFATURA"
    assert text(root, "cbc:ID") == "OMT2026000000001"
    assert text(root, "cbc:CopyIndicator") == "false"
    assert text(root, "cbc:UUID") == "6f1c2d3e-4a5b-4c6d-8e7f-001122334455"
    assert text(root, "cbc:IssueDate") == "2026-09-30"
    assert text(root, "cbc:IssueTime") == "14:05:09"
    assert text(root, "cbc:InvoiceTypeCode") == "SATIS"
    assert text(root, "cbc:DocumentCurrencyCode") == "TRY"
    assert text(root, "cbc:LineCountNumeric") == "2"
    assert text(root, "cbc:Note") == "Yalnız ElliBirBin Türk Lirası"


def test_unsigned_document_carries_both_signature_placeholders() -> None:
    root = render(satis_invoice())
    content = root.find("ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent", NS)
    assert content is not None
    # Exactly one child, from a namespace that is not the extension namespace.
    assert [child.tag for child in content] == [f"{{{UNSIGNED}}}SignaturePlaceholder"]
    assert root[0].tag == f"{{{EXT}}}UBLExtensions"

    signature = root.findall("cac:Signature", NS)
    assert len(signature) == 1
    sig_id = signature[0].find("cbc:ID", NS)
    assert sig_id is not None
    assert sig_id.get("schemeID") == "VKN_TCKN"
    assert sig_id.text == SUPPLIER_VKN
    signatory = signature[0].find("cac:SignatoryParty/cac:PartyIdentification/cbc:ID", NS)
    assert signatory is not None
    assert (signatory.get("schemeID"), signatory.text) == ("VKN", SUPPLIER_VKN)
    assert text(signature[0], "cac:SignatoryParty/cac:PostalAddress/cbc:CityName") == "Ankara"
    assert (
        text(signature[0], "cac:DigitalSignatureAttachment/cac:ExternalReference/cbc:URI")
        == "#Signature_OMT2026000000001"
    )


# ── parties ──────────────────────────────────────────────────────────────────


def test_legal_entity_party_is_identified_by_vkn_with_name_and_tax_office() -> None:
    root = render(satis_invoice())
    party = root.find("cac:AccountingSupplierParty/cac:Party", NS)
    assert party is not None
    ids = [(el.get("schemeID"), el.text) for el in party.findall("cac:PartyIdentification/cbc:ID", NS)]
    assert ids == [("VKN", SUPPLIER_VKN), ("MERSISNO", "0111222333900017")]
    assert text(party, "cac:PartyName/cbc:Name") == "Örnek Mekanik Tesisat Taahhüt A.Ş."
    assert text(party, "cac:PartyTaxScheme/cac:TaxScheme/cbc:Name") == "Çankaya"
    address = party.find("cac:PostalAddress", NS)
    assert address is not None
    assert text(address, "cbc:StreetName") == "Şehit Öğretmen Caddesi"
    assert text(address, "cbc:BuildingNumber") == "12/A"
    assert text(address, "cbc:CitySubdivisionName") == "Çankaya"
    assert text(address, "cbc:CityName") == "Ankara"
    assert text(address, "cbc:PostalZone") == "06690"
    assert text(address, "cac:Country/cbc:IdentificationCode") == "TR"
    assert text(address, "cac:Country/cbc:Name") == "Türkiye"
    assert text(party, "cac:Contact/cbc:ElectronicMail") == "info@datadrivenconstruction.io"
    assert party.find("cac:Person", NS) is None


def test_natural_person_is_identified_by_tckn_with_person_block() -> None:
    root = render(person_invoice())
    assert text(root, "cbc:ProfileID") == "EARSIVFATURA"
    party = root.find("cac:AccountingCustomerParty/cac:Party", NS)
    assert party is not None
    ident = party.find("cac:PartyIdentification/cbc:ID", NS)
    assert ident is not None
    assert (ident.get("schemeID"), ident.text) == ("TCKN", PERSON_TCKN)
    assert party.find("cac:PartyName", NS) is None
    assert text(party, "cac:Person/cbc:FirstName") == "Ayşe Gül"
    assert text(party, "cac:Person/cbc:FamilyName") == "Çağlayan"
    assert party.find("cac:PartyTaxScheme", NS) is None


# ── taxes ────────────────────────────────────────────────────────────────────


def test_satis_tax_block_and_totals() -> None:
    root = render(satis_invoice())
    assert text(root, "cac:TaxTotal/cbc:TaxAmount") == "8500.00"
    sub = root.find("cac:TaxTotal/cac:TaxSubtotal", NS)
    assert sub is not None
    assert text(sub, "cbc:TaxableAmount") == "42500.00"
    assert text(sub, "cbc:TaxAmount") == "8500.00"
    assert text(sub, "cbc:CalculationSequenceNumeric") == "1"
    assert text(sub, "cbc:Percent") == "20"
    assert text(sub, "cac:TaxCategory/cac:TaxScheme/cbc:Name") == "KDV"
    assert text(sub, "cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode") == "0015"
    assert root.find("cac:WithholdingTaxTotal", NS) is None
    lmt = root.find("cac:LegalMonetaryTotal", NS)
    assert lmt is not None
    assert text(lmt, "cbc:LineExtensionAmount") == "42500.00"
    assert text(lmt, "cbc:TaxExclusiveAmount") == "42500.00"
    assert text(lmt, "cbc:TaxInclusiveAmount") == "51000.00"
    assert text(lmt, "cbc:PayableAmount") == "51000.00"
    assert lmt.find("cbc:AllowanceTotalAmount", NS) is None


def test_every_amount_carries_the_document_currency() -> None:
    for build in (satis_invoice, tevkifat_invoice, eur_invoice, two_rate_invoice):
        inv = build()
        root = render(inv)
        amounts = [el for el in root.iter() if el.tag.endswith("Amount")]
        assert amounts
        assert {el.get("currencyID") for el in amounts} == {inv.currency}


def test_tevkifat_document_level_semantics_follow_the_official_samples() -> None:
    """Header VAT is net of withholding, the subtotal is the full VAT, the total with tax is gross.

    The same shape as the official samples: 3600 computed, 3240 withheld, 360
    in the header, 23600 with tax and 20360 to pay. Here 20000, 8000, 12000,
    120000 and 112000.
    """
    root = render(tevkifat_invoice())
    assert text(root, "cbc:InvoiceTypeCode") == "TEVKIFAT"
    assert text(root, "cac:TaxTotal/cbc:TaxAmount") == "12000.00"
    assert text(root, "cac:TaxTotal/cac:TaxSubtotal/cbc:TaxableAmount") == "100000.00"
    assert text(root, "cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount") == "20000.00"

    wht = root.findall("cac:WithholdingTaxTotal", NS)
    assert len(wht) == 1
    assert text(wht[0], "cbc:TaxAmount") == "8000.00"
    sub = wht[0].find("cac:TaxSubtotal", NS)
    assert sub is not None
    assert text(sub, "cbc:TaxableAmount") == "20000.00"
    assert text(sub, "cbc:TaxAmount") == "8000.00"
    # "40", never "40.00": GİB looks the code and this text up as "60140".
    assert text(sub, "cbc:Percent") == "40"
    assert sub.find("cbc:CalculationSequenceNumeric", NS) is None
    assert text(sub, "cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode") == "601"
    assert text(sub, "cac:TaxCategory/cac:TaxScheme/cbc:Name") == WH_NAME

    lmt = root.find("cac:LegalMonetaryTotal", NS)
    assert lmt is not None
    assert text(lmt, "cbc:TaxExclusiveAmount") == "100000.00"
    assert text(lmt, "cbc:TaxInclusiveAmount") == "120000.00"
    assert text(lmt, "cbc:PayableAmount") == "112000.00"


def test_tevkifat_line_level_carries_its_share_of_each_figure() -> None:
    root = render(tevkifat_invoice())
    lines = root.findall("cac:InvoiceLine", NS)
    assert [text(ln, "cac:TaxTotal/cbc:TaxAmount") for ln in lines] == ["7200.00", "4800.00"]
    assert [text(ln, "cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount") for ln in lines] == ["12000.00", "8000.00"]
    assert [text(ln, "cac:TaxTotal/cac:TaxSubtotal/cbc:TaxableAmount") for ln in lines] == ["60000.00", "40000.00"]
    assert [text(ln, "cac:WithholdingTaxTotal/cbc:TaxAmount") for ln in lines] == ["4800.00", "3200.00"]
    assert [text(ln, "cac:WithholdingTaxTotal/cac:TaxSubtotal/cbc:TaxableAmount") for ln in lines] == [
        "12000.00",
        "8000.00",
    ]
    assert [text(ln, "cac:WithholdingTaxTotal/cac:TaxSubtotal/cbc:Percent") for ln in lines] == ["40", "40"]


def test_computed_convention_writes_the_full_vat_in_the_header_and_nothing_else_moves() -> None:
    net = render(tevkifat_invoice())
    full = render(replace(tevkifat_invoice(), tax_total_convention="computed"))
    assert text(full, "cac:TaxTotal/cbc:TaxAmount") == "20000.00"
    lines = full.findall("cac:InvoiceLine", NS)
    assert [text(ln, "cac:TaxTotal/cbc:TaxAmount") for ln in lines] == ["12000.00", "8000.00"]
    for path in (
        "cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount",
        "cac:WithholdingTaxTotal/cbc:TaxAmount",
        "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount",
        "cac:LegalMonetaryTotal/cbc:PayableAmount",
    ):
        assert text(full, path) == text(net, path)


def test_two_vat_rates_give_two_subtotals_and_a_summed_header() -> None:
    root = render(two_rate_invoice())
    assert text(root, "cac:TaxTotal/cbc:TaxAmount") == "6300.00"
    subs = root.findall("cac:TaxTotal/cac:TaxSubtotal", NS)
    assert [text(s, "cbc:Percent") for s in subs] == ["20", "10"]
    assert [text(s, "cbc:TaxableAmount") for s in subs] == ["31000.00", "999.99"]
    assert [text(s, "cbc:TaxAmount") for s in subs] == ["6200.00", "100.00"]
    assert [text(s, "cbc:CalculationSequenceNumeric") for s in subs] == ["1", "2"]
    lmt = root.find("cac:LegalMonetaryTotal", NS)
    assert lmt is not None
    assert text(lmt, "cbc:LineExtensionAmount") == "32999.99"
    assert text(lmt, "cbc:TaxExclusiveAmount") == "31999.99"
    assert text(lmt, "cbc:AllowanceTotalAmount") == "1000.00"
    assert text(lmt, "cbc:TaxInclusiveAmount") == "38299.99"
    allowance = root.find("cac:InvoiceLine/cac:AllowanceCharge", NS)
    assert allowance is not None
    assert text(allowance, "cbc:ChargeIndicator") == "false"
    assert text(allowance, "cbc:MultiplierFactorNumeric") == "0.05"
    assert text(allowance, "cbc:Amount") == "1000.00"
    assert text(allowance, "cbc:BaseAmount") == "20000.00"


def test_istisna_states_zero_vat_with_its_reason() -> None:
    root = render(istisna_invoice())
    assert text(root, "cac:TaxTotal/cbc:TaxAmount") == "0.00"
    category = root.find("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory", NS)
    assert category is not None
    assert text(category, "cbc:TaxExemptionReasonCode") == "350"
    assert text(category, "cbc:TaxExemptionReason") == "Diğerleri"
    assert text(root, "cac:TaxTotal/cac:TaxSubtotal/cbc:Percent") == "0"


# ── currency, references, lines ──────────────────────────────────────────────


def test_foreign_currency_invoice_states_the_rate_to_lira() -> None:
    root = render(eur_invoice())
    rate = root.find("cac:PricingExchangeRate", NS)
    assert rate is not None
    assert text(rate, "cbc:SourceCurrencyCode") == "EUR"
    assert text(rate, "cbc:TargetCurrencyCode") == "TRY"
    assert text(rate, "cbc:CalculationRate") == "48.125"
    assert text(rate, "cbc:Date") == "2026-09-29"
    assert text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount") == "4441.20"
    assert render(satis_invoice()).find("cac:PricingExchangeRate", NS) is None


def test_return_invoice_is_an_invoice_root_naming_the_original() -> None:
    root = render(iade_invoice())
    assert root.tag == f"{{{INV}}}Invoice"
    assert text(root, "cbc:InvoiceTypeCode") == "IADE"
    ref = root.find("cac:BillingReference/cac:InvoiceDocumentReference", NS)
    assert ref is not None
    assert text(ref, "cbc:ID") == "OMT2026000000001"
    assert text(ref, "cbc:IssueDate") == "2026-09-30"
    assert text(ref, "cbc:DocumentTypeCode") == "IADE"
    # Nothing on a return is negative.
    assert not [el.text for el in root.iter() if el.tag.endswith("Amount") and (el.text or "").startswith("-")]


def test_contract_period_and_payment_blocks() -> None:
    root = render(tevkifat_invoice())
    assert text(root, "cac:ContractDocumentReference/cbc:ID") == "SZL-2026-014"
    assert text(root, "cac:ContractDocumentReference/cbc:IssueDate") == "2026-03-02"
    assert text(root, "cac:InvoicePeriod/cbc:StartDate") == "2026-09-01"
    assert text(root, "cac:InvoicePeriod/cbc:EndDate") == "2026-09-30"
    satis = render(satis_invoice())
    assert text(satis, "cac:PaymentMeans/cbc:PaymentMeansCode") == "42"
    assert text(satis, "cac:PaymentMeans/cbc:PaymentDueDate") == "2026-10-30"
    assert text(satis, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID") == "TR000000000000000000000000"
    assert text(satis, "cac:PaymentTerms/cbc:Note") == "30 gün vadeli"


def test_line_content_and_unit_codes() -> None:
    root = render(satis_invoice())
    first, second = root.findall("cac:InvoiceLine", NS)
    qty = first.find("cbc:InvoicedQuantity", NS)
    assert qty is not None
    assert (qty.text, qty.get("unitCode")) == ("120", "MTR")
    assert text(first, "cbc:LineExtensionAmount") == "30000.00"
    assert text(first, "cac:Item/cbc:Name") == "Çelik boru DN100 montajı"
    assert text(first, "cac:Item/cac:SellersItemIdentification/cbc:ID") == "MT-0100"
    assert text(first, "cac:Price/cbc:PriceAmount") == "250"
    assert text(second, "cac:Item/cbc:Description") == "Elektrikli ve dizel pompalı, kumanda panosu dahil"
    second_qty = second.find("cbc:InvoicedQuantity", NS)
    assert second_qty is not None
    assert second_qty.get("unitCode") == "SET"


# The platform units a construction invoice uses and the code each must get.
# Each code was checked on 2026-10-10 against ``UnitCodeList`` in
# ``UBL-TR_Codelist.xml`` (e-Fatura package, revision 2026-07-01).
@pytest.mark.parametrize(
    ("unit", "code"),
    [
        ("m", "MTR"),
        ("m2", "MTK"),
        ("m²", "MTK"),
        ("m3", "MTQ"),
        ("m³", "MTQ"),
        ("kg", "KGM"),
        ("t", "TNE"),
        ("adet", "C62"),
        ("pcs", "C62"),
        ("PCS", "C62"),
        ("set", "SET"),
        ("hour", "HUR"),
        ("saat", "HUR"),
        ("day", "DAY"),
        ("gün", "DAY"),
        ("lsum", "LS"),
        (" l ", "LTR"),
    ],
)
def test_platform_units_map_to_accepted_codes(unit: str, code: str) -> None:
    assert tr_unit_code(unit) == code


@pytest.mark.parametrize("unit", ["", None, "furlong", "İ", "box of twelve"])
def test_unknown_unit_is_never_silently_a_piece(unit: str | None) -> None:
    assert tr_unit_code(unit) is None


# ── strictness ───────────────────────────────────────────────────────────────


def test_strict_refuses_an_invalid_invoice_and_names_every_fatal_rule() -> None:
    line = replace(satis_invoice().lines[0], unit="furlong")
    inv = replace(satis_invoice(), uuid="not-a-uuid", lines=(line, satis_invoice().lines[1]))
    with pytest.raises(EInvoiceError) as err:
        build_ubl_tr_xml(inv, today=TODAY)
    assert "TR-ID-02" in str(err.value)
    assert "TR-UNIT-01" in str(err.value)


def test_non_strict_writes_a_preview_of_an_invalid_invoice() -> None:
    line = replace(satis_invoice().lines[0], unit="furlong")
    inv = replace(satis_invoice(), uuid="not-a-uuid", lines=(line, satis_invoice().lines[1]))
    root = render(inv, strict=False)
    assert text(root, "cbc:UUID") == "not-a-uuid"
    qty = root.find("cac:InvoiceLine/cbc:InvoicedQuantity", NS)
    assert qty is not None
    assert qty.get("unitCode") == "furlong"


def test_held_figure_blocks_generation_and_leaves_a_hole_in_the_preview() -> None:
    base = tevkifat_invoice()
    group = base.tax_groups[0]
    held_taxes = replace(group.taxes, vat_withheld=held("vat_withheld"), vat_payable=held("vat_payable"))
    inv = replace(base, tax_groups=(replace(group, taxes=held_taxes),))
    with pytest.raises(EInvoiceError, match="TR-HELD-01"):
        build_ubl_tr_xml(inv, today=TODAY)
    root = render(inv, strict=False)
    # No amount is invented for a figure nobody decided.
    assert root.find("cac:TaxTotal/cbc:TaxAmount", NS) is None
    assert text(root, "cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount") == "20000.00"


def test_missing_document_id_is_left_for_the_integrator() -> None:
    inv = replace(satis_invoice(), document_id="")
    root = render(inv)
    assert root.find("cbc:ID", NS) is not None
    assert (text(root, "cbc:ID") or "") == ""
    assert text(root, "cac:Signature/cac:DigitalSignatureAttachment/cac:ExternalReference/cbc:URI") == "#Signature"


# ── encoding and determinism ─────────────────────────────────────────────────


def test_output_is_utf8_with_declaration_no_bom_and_turkish_characters_intact() -> None:
    xml = build_ubl_tr_xml(tevkifat_invoice(), today=TODAY)
    assert xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<Invoice ')
    assert not xml.startswith(b"\xef\xbb\xbf")
    decoded = xml.decode("utf-8")
    for expected in ("Örnek Mekanik Tesisat Taahhüt A.Ş.", "Şişli", "İstanbul", "Hakediş No: 3", "Isıtma ve soğutma"):
        assert expected in decoded
    # Written as characters, not as numeric references.
    assert "&#" not in decoded


def test_output_is_deterministic_with_stable_namespace_prefixes() -> None:
    first = build_ubl_tr_xml(tevkifat_invoice(), today=TODAY)
    assert first == build_ubl_tr_xml(tevkifat_invoice(), today=TODAY)
    head = first.split(b"\n", 2)[1].decode("utf-8")
    assert f'xmlns="{INV}"' in head
    assert f'xmlns:cac="{CAC}"' in head
    assert f'xmlns:cbc="{CBC}"' in head
    assert f'xmlns:ext="{EXT}"' in head
    assert "ns0" not in first.decode("utf-8")


def test_golden_document() -> None:
    """The withholding invoice, compared after canonical (C14N 2.0) serialisation.

    Canonical form on both sides, so that a checkout which rewrites line
    endings cannot fail the comparison while any change to an element, an
    attribute, a value or their order does.
    """
    produced = build_ubl_tr_xml(tevkifat_invoice(), today=TODAY)
    expected = GOLDEN.read_bytes()
    assert ET.canonicalize(produced.decode("utf-8")) == ET.canonicalize(expected.decode("utf-8"))


# ── element order ────────────────────────────────────────────────────────────

# Child element order per parent, derived on 2026-10-10 from the ``xsd:sequence``
# of each type in ``UBL-Invoice-2.1.xsd`` and
# ``UBL-CommonAggregateComponents-2.1.xsd`` of the UBL-TR 1.2.1 package. UBL is
# order sensitive: a receiver validating against the XSD rejects a document
# whose children are out of sequence. The lists are complete sequences, so an
# element the writer starts emitting later is already placed.
_DOCUMENT_REFERENCE = (
    "ID IssueDate DocumentTypeCode DocumentType DocumentDescription Attachment ValidityPeriod IssuerParty"
)
_PARTY = (
    "WebsiteURI EndpointID IndustryClassificationCode PartyIdentification PartyName PostalAddress "
    "PhysicalLocation PartyTaxScheme PartyLegalEntity Contact Person AgentParty"
)
_TAX_TOTAL = "TaxAmount TaxSubtotal"
XSD_SEQUENCES: dict[str, str] = {
    "Invoice": (
        "UBLExtensions UBLVersionID CustomizationID ProfileID ID CopyIndicator UUID IssueDate IssueTime "
        "InvoiceTypeCode Note DocumentCurrencyCode TaxCurrencyCode PricingCurrencyCode PaymentCurrencyCode "
        "PaymentAlternativeCurrencyCode AccountingCost LineCountNumeric InvoicePeriod OrderReference "
        "BillingReference DespatchDocumentReference ReceiptDocumentReference OriginatorDocumentReference "
        "ContractDocumentReference AdditionalDocumentReference Signature AccountingSupplierParty "
        "AccountingCustomerParty BuyerCustomerParty SellerSupplierParty TaxRepresentativeParty Delivery "
        "PaymentMeans PaymentTerms AllowanceCharge TaxExchangeRate PricingExchangeRate PaymentExchangeRate "
        "PaymentAlternativeExchangeRate TaxTotal WithholdingTaxTotal LegalMonetaryTotal InvoiceLine"
    ),
    "UBLExtensions": "UBLExtension",
    "UBLExtension": "ExtensionContent",
    "ExtensionContent": "SignaturePlaceholder",
    "Signature": "ID SignatoryParty DigitalSignatureAttachment",
    "SignatoryParty": _PARTY,
    "DigitalSignatureAttachment": "EmbeddedDocumentBinaryObject ExternalReference",
    "ExternalReference": "URI",
    "AccountingSupplierParty": "Party DespatchContact",
    "AccountingCustomerParty": "Party DeliveryContact",
    "Party": _PARTY,
    "PartyIdentification": "ID",
    "PartyName": "Name",
    "PostalAddress": (
        "ID Postbox Room StreetName BlockName BuildingName BuildingNumber CitySubdivisionName CityName "
        "PostalZone Region District Country"
    ),
    "Country": "IdentificationCode Name",
    "PartyTaxScheme": "RegistrationName CompanyID TaxScheme",
    "TaxScheme": "ID Name TaxTypeCode",
    "Contact": "ID Name Telephone Telefax ElectronicMail Note OtherCommunication",
    "Person": "FirstName FamilyName Title MiddleName NameSuffix NationalityID FinancialAccount IdentityDocumentReference",
    "InvoicePeriod": "StartDate StartTime EndDate EndTime DurationMeasure Description",
    "OrderReference": "ID SalesOrderID IssueDate OrderTypeCode DocumentReference",
    "BillingReference": (
        "InvoiceDocumentReference SelfBilledInvoiceDocumentReference CreditNoteDocumentReference "
        "SelfBilledCreditNoteDocumentReference DebitNoteDocumentReference ReminderDocumentReference "
        "AdditionalDocumentReference BillingReferenceLine"
    ),
    "InvoiceDocumentReference": _DOCUMENT_REFERENCE,
    "DespatchDocumentReference": _DOCUMENT_REFERENCE,
    "ContractDocumentReference": _DOCUMENT_REFERENCE,
    "PaymentMeans": (
        "PaymentMeansCode PaymentDueDate PaymentChannelCode InstructionNote PayerFinancialAccount PayeeFinancialAccount"
    ),
    "PayeeFinancialAccount": "ID CurrencyCode PaymentNote FinancialInstitutionBranch",
    "PaymentTerms": "Note PenaltySurchargePercent Amount PenaltyAmount PaymentDueDate SettlementPeriod",
    "AllowanceCharge": (
        "ChargeIndicator AllowanceChargeReason MultiplierFactorNumeric SequenceNumeric Amount BaseAmount PerUnitAmount"
    ),
    "PricingExchangeRate": "SourceCurrencyCode TargetCurrencyCode CalculationRate Date",
    "TaxTotal": _TAX_TOTAL,
    "WithholdingTaxTotal": _TAX_TOTAL,
    "TaxSubtotal": (
        "TaxableAmount TaxAmount CalculationSequenceNumeric TransactionCurrencyTaxAmount Percent "
        "BaseUnitMeasure PerUnitAmount TaxCategory"
    ),
    "TaxCategory": "Name TaxExemptionReasonCode TaxExemptionReason TaxScheme",
    "LegalMonetaryTotal": (
        "LineExtensionAmount TaxExclusiveAmount TaxInclusiveAmount AllowanceTotalAmount ChargeTotalAmount "
        "PayableRoundingAmount PayableAmount"
    ),
    "InvoiceLine": (
        "ID Note InvoicedQuantity LineExtensionAmount OrderLineReference DespatchLineReference "
        "ReceiptLineReference Delivery AllowanceCharge TaxTotal WithholdingTaxTotal Item Price SubInvoiceLine"
    ),
    "Item": (
        "Description Name Keyword BrandName ModelName BuyersItemIdentification SellersItemIdentification "
        "ManufacturersItemIdentification AdditionalItemIdentification OriginCountry CommodityClassification "
        "ItemInstance"
    ),
    "SellersItemIdentification": "ID",
    "Price": "PriceAmount",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _full_invoice() -> TrInvoice:
    """One invoice that exercises every element the writer can emit."""
    base = tevkifat_invoice()
    return replace(
        base,
        order_reference=TrDocumentRef(id="SP-778", issue_date=dt.date(2026, 2, 1)),
        despatch_references=(TrDocumentRef(id="IRS2026000000009", issue_date=dt.date(2026, 9, 28)),),
        payment_means=(
            TrPaymentMeans(
                code="42",
                due_date=dt.date(2026, 10, 30),
                channel_code="TT",
                instruction_note="Havale",
                payee_iban="TR000000000000000000000000",
                payee_currency="TRY",
                payment_note="Hakediş 3",
            ),
        ),
        payment_terms_note="30 gün",
        payment_due_date=dt.date(2026, 10, 30),
        exchange_rate=Decimal("1"),
        exchange_rate_date=dt.date(2026, 9, 30),
        period=TrPeriod(start_date=dt.date(2026, 9, 1), end_date=dt.date(2026, 9, 30), description="Eylül 2026"),
        supplier=replace(supplier(), website="https://datadrivenconstruction.io"),
        customer=replace(
            person(), contact=TrContact(name="Ayşe Gül Çağlayan", telephone="1", telefax="2", email="a@b.c")
        ),
        lines=(
            replace(
                base.lines[0],
                note="Not",
                description="Açıklama",
                seller_item_code="K-1",
                allowances=(
                    TrAllowanceCharge(
                        amount=Decimal("0.00"),
                        reason="İskonto",
                        multiplier_factor=Decimal("0"),
                        base_amount=Decimal("60000.00"),
                    ),
                ),
            ),
            base.lines[1],
        ),
        allowance_charges=(TrAllowanceCharge(amount=Decimal("0.00")),),
        totals=replace(
            base.totals, allowance_total=Decimal("0.00"), charge_total=Decimal("0.00"), payable_rounding=Decimal("0.00")
        ),
    )


@pytest.mark.parametrize("name", [*sorted(SCENARIOS), "full"])
def test_children_follow_the_xsd_sequence(name: str) -> None:
    inv = _full_invoice() if name == "full" else SCENARIOS[name]()
    root = render(inv, strict=False)
    checked = 0
    for parent in root.iter():
        children = [_local(child.tag) for child in parent]
        if not children:
            continue
        sequence = XSD_SEQUENCES[_local(parent.tag)].split()
        positions = [sequence.index(child) for child in children]
        assert positions == sorted(positions), f"{_local(parent.tag)}: {children}"
        checked += 1
    assert checked > 20


def test_full_invoice_is_valid_and_emits_every_optional_block() -> None:
    inv = _full_invoice()
    assert [v for v in check_tr(inv, today=TODAY) if v.severity == FATAL] == []
    root = render(inv)
    emitted = {_local(el.tag) for el in root.iter()}
    for expected in (
        "InvoicePeriod",
        "OrderReference",
        "DespatchDocumentReference",
        "ContractDocumentReference",
        "PaymentMeans",
        "PaymentTerms",
        "AllowanceCharge",
        "PricingExchangeRate",
        "WithholdingTaxTotal",
        "PayableRoundingAmount",
        "Person",
        "Contact",
        "WebsiteURI",
        "SellersItemIdentification",
    ):
        assert expected in emitted


# ── optional: the official XSD ───────────────────────────────────────────────


def _xsd_schema():  # noqa: ANN202 - lxml is optional, so its types are not imported
    """Load ``UBL-Invoice-2.1.xsd`` from ``OE_UBLTR_XSD_DIR``, or skip.

    The schema is GİB's and is not redistributed with this repository. Point
    the variable at the ``xsdrt`` directory of the UBL-TR 1.2.1 package (the
    one holding ``maindoc`` and ``common``) to run these tests.
    """
    directory = os.environ.get("OE_UBLTR_XSD_DIR", "").strip()
    if not directory:
        pytest.skip("OE_UBLTR_XSD_DIR is not set")
    etree = pytest.importorskip("lxml.etree")
    path = Path(directory) / "maindoc" / "UBL-Invoice-2.1.xsd"
    if not path.is_file():
        pytest.skip(f"{path} does not exist")
    return etree, etree.XMLSchema(etree.parse(str(path)))


@pytest.mark.parametrize("name", [*sorted(SCENARIOS), "full"])
def test_document_validates_against_the_official_xsd(name: str) -> None:
    etree, schema = _xsd_schema()
    inv = _full_invoice() if name == "full" else SCENARIOS[name]()
    document = etree.fromstring(build_ubl_tr_xml(inv, today=TODAY))
    assert schema.validate(document), schema.error_log


def test_xsd_rejects_an_out_of_order_document() -> None:
    """The control: the schema loaded above really does police element order."""
    etree, schema = _xsd_schema()
    document = etree.fromstring(build_ubl_tr_xml(satis_invoice(), today=TODAY))
    document.append(document[1])
    assert not schema.validate(document)
