"""ZATCA document tests: the UBL builder, the cryptographic stamp, the QR and the offline rule checks.

No database and no network. The distinguishing cases are the ones where a plausible
simplification gives a different, wrong answer: the invoice hash taken with the standard
library's C14N 2.0 instead of C14N 1.1, a signature taken over SignedInfo instead of the
hash, a retention subtracted from the VAT base, a negative line instead of a credit note.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import re
from decimal import Decimal
from xml.etree import ElementTree as stdlib_et  # noqa: N813

import pytest
from lxml import etree

from app.modules.einvoice_zatca import builder, c14n, checks, csr, hashing, qr, signing
from app.modules.einvoice_zatca.codes import (
    FIRST_PREVIOUS_HASH,
    NS_CAC,
    NS_CBC,
    NS_EXT,
    TYPE_CREDIT_NOTE,
    TYPE_INVOICE,
    TYPE_PREPAYMENT,
    Subtype,
)
from app.modules.einvoice_zatca.stamp import StampError, apply_stamp

NOW = dt.datetime(2026, 10, 19, 10, 0, 1)
CHECK_TIME = dt.datetime(2026, 10, 19, 11, 0, tzinfo=dt.UTC)
SELLER_VAT = "399999999900003"
BUYER_VAT = "399999999800003"
ADDRESS = builder.Address(
    street="Prince Sultan Street",
    building_number="1234",
    additional_number="5678",
    district="Al Olaya",
    city="Riyadh",
    postal_zone="12214",
)


def make_input(
    *,
    simplified: bool = False,
    type_code: str = TYPE_INVOICE,
    lines: tuple[builder.Line, ...] | None = None,
    **overrides,
) -> builder.ZatcaInvoiceInput:
    note = type_code in ("381", "383")
    values = {
        "number": "INV-1",
        "uuid": "8e6000cf-1a98-4174-b3e7-b5d5954bc10d",
        "issue_date": "2026-10-19",
        "issue_time": "10:00:00",
        "type_code": type_code,
        "subtype": Subtype(simplified=simplified),
        "currency": "SAR",
        "seller": builder.Party(
            name="Maximum Speed Tech Supply LTD",
            vat_number=SELLER_VAT,
            id_scheme="CRN",
            id_value="1010010000",
            address=ADDRESS,
        ),
        "buyer": None if simplified else builder.Party(name="Buyer Co", vat_number=BUYER_VAT, address=ADDRESS),
        "lines": lines or (builder.Line("Works", Decimal("2"), "PCE", Decimal("100")),),
        "icv": 1,
        "previous_hash": FIRST_PREVIOUS_HASH,
        "supply_date": "" if simplified else "2026-10-19",
        "billing_reference": "INV-0" if note else "",
        "reason": "Correction" if note else "",
    }
    values.update(overrides)
    return builder.ZatcaInvoiceInput(**values)


async def stamped(spec: builder.ZatcaInvoiceInput, signer: signing.Signer | None = None):
    root = builder.build_unsigned(spec)
    signer = signer or signing.make_test_signer()
    stamp = await apply_stamp(
        root, signer, signing_time=NOW, qr_fields=builder.qr_fields(spec), simplified=spec.subtype.simplified
    )
    return root, stamp, c14n.serialize(root), signer


def qr_text_of(text: str) -> str:
    tree = etree.fromstring(text.encode("utf-8"))
    ns = {"cac": NS_CAC, "cbc": NS_CBC}
    return tree.xpath(
        "//cac:AdditionalDocumentReference[cbc:ID='QR']//cbc:EmbeddedDocumentBinaryObject", namespaces=ns
    )[0].text


def codes_of(text: str, **kwargs) -> list[str]:
    return [i.code for i in checks.check_document(text, profile_vat=SELLER_VAT, now=CHECK_TIME, **kwargs)]


# ── The hash ────────────────────────────────────────────────────────────────


class TestInvoiceHash:
    async def test_the_hash_is_the_one_an_independent_canonicalizer_gives(self):
        # lxml canonicalizes the document with the three excluded parts removed. Nothing in
        # it is shared with c14n.py, so agreement is evidence about the bytes, not a tautology.
        _root, stamp, text, _ = await stamped(make_input())
        tree = etree.fromstring(text.encode("utf-8"))
        ns = {"ext": NS_EXT, "cac": NS_CAC, "cbc": NS_CBC}
        for node in tree.xpath("//ext:UBLExtensions | //cac:Signature", namespaces=ns):
            node.getparent().remove(node)
        for node in tree.xpath("//cac:AdditionalDocumentReference[cbc:ID='QR']", namespaces=ns):
            node.getparent().remove(node)
        expected = base64.b64encode(hashlib.sha256(etree.tostring(tree, method="c14n")).digest()).decode()
        assert stamp.invoice_hash == expected

    async def test_the_standard_library_c14n_gives_another_hash(self):
        # The distinguishing case for c14n.py: C14N 2.0 moves namespace declarations to first
        # use, so a "simplification" back to the standard library would hash differently.
        _root, stamp, text, _ = await stamped(make_input())
        tree = etree.fromstring(text.encode("utf-8"))
        ns = {"ext": NS_EXT, "cac": NS_CAC, "cbc": NS_CBC}
        for node in tree.xpath("//ext:UBLExtensions | //cac:Signature", namespaces=ns):
            node.getparent().remove(node)
        for node in tree.xpath("//cac:AdditionalDocumentReference[cbc:ID='QR']", namespaces=ns):
            node.getparent().remove(node)
        modern = stdlib_et.canonicalize(etree.tostring(tree).decode("utf-8"))
        assert base64.b64encode(hashlib.sha256(modern.encode("utf-8")).digest()).decode() != stamp.invoice_hash

    async def test_stamping_does_not_move_the_hash(self):
        spec = make_input()
        unsigned = builder.build_unsigned(spec)
        before = hashing.invoice_hash(unsigned)
        _root, stamp, _text, _ = await stamped(spec)
        assert stamp.invoice_hash == before

    async def test_a_stamped_document_is_refused_a_second_stamp(self):
        root, _stamp, _text, signer = await stamped(make_input())
        with pytest.raises(StampError):
            await apply_stamp(
                root, signer, signing_time=NOW, qr_fields=builder.qr_fields(make_input()), simplified=False
            )


# ── The signature and the QR ────────────────────────────────────────────────


class TestSignatureAndQr:
    async def test_the_signature_verifies_over_the_hash_and_not_over_signed_info(self):
        _root, stamp, text, signer = await stamped(make_input())
        tree = etree.fromstring(text.encode("utf-8"))
        ds = {"ds": "http://www.w3.org/2000/09/xmldsig#"}
        value = base64.b64decode(tree.xpath("//ds:SignatureValue", namespaces=ds)[0].text)
        digest = base64.b64decode(stamp.invoice_hash)
        public = signer.certificate.public_key_der
        assert signing.verify(public, value, digest)
        signed_info = etree.tostring(tree.xpath("//ds:SignedInfo", namespaces=ds)[0], method="c14n")
        assert not signing.verify(public, value, signed_info)

    async def test_a_standard_invoice_qr_has_tags_one_to_eight(self):
        _root, stamp, text, signer = await stamped(make_input())
        tags = qr.decode(qr_text_of(text))
        assert sorted(tags) == [1, 2, 3, 4, 5, 6, 7, 8]
        assert tags[2].decode() == SELLER_VAT
        assert tags[6].decode() == stamp.invoice_hash

    async def test_a_simplified_invoice_qr_carries_the_certificate_signature(self):
        _root, stamp, text, signer = await stamped(make_input(simplified=True))
        tags = qr.decode(qr_text_of(text))
        assert 9 in tags
        assert tags[9] == signer.certificate.certificate_signature

    def test_a_qr_over_the_limit_is_refused(self):
        fields = qr.QrFields(
            seller_name="x" * 200,
            vat_number=SELLER_VAT,
            timestamp="2026-10-19T10:00:00",
            total_with_vat="1.00",
            vat_total="0.15",
            invoice_hash="h" * 44,
            signature="s" * 200,
            public_key=b"k" * 120,
            certificate_signature=b"c" * 120,
        )
        with pytest.raises(qr.QrError):
            qr.encode(fields)

    async def test_qr_tag_four_is_the_amount_due_after_a_prepayment(self):
        # The SDK reads tag 4 from PayableAmount, not TaxInclusiveAmount.
        prepayment = builder.Prepayment(
            number="ADV-1", issue_date="2026-09-01", issue_time="09:00:00", taxable_amount=Decimal("100"), uuid="u-1"
        )
        spec = make_input(
            lines=(builder.Line("Works", Decimal("1"), "PCE", Decimal("1000")),), prepayments=(prepayment,)
        )
        fields = builder.qr_fields(spec)
        assert fields.total_with_vat == "1035.00"  # 1150 with VAT, less 100 + 15 prepaid


# ── Figures the construction guideline pins ─────────────────────────────────


class TestConstructionFigures:
    def test_vat_is_due_on_the_gross_and_retention_is_not_subtracted(self):
        # VAT Guideline for the Contracting Sector §5.2, Example 4: 5,000,000 invoiced, VAT 750,000.
        spec = builder.input_from_invoice(
            invoice={"invoice_number": "IPC-4", "invoice_date": "2026-10-19", "currency_code": "SAR"},
            lines=[
                {
                    "description": "Interim payment",
                    "quantity": 1,
                    "unit_rate": "5000000",
                    "amount": "5000000",
                    "vat_rate": 15,
                }
            ],
            vat_number=SELLER_VAT,
            settings={
                "seller": {
                    "name": "Contractor",
                    "address": {"street": "Main", "building_number": "1234", "city": "Riyadh", "postal_zone": "12214"},
                }
            },
            zatca_fields={"kind": "interim"},
            buyer={
                "name": "Owner",
                "vat_id": BUYER_VAT,
                "line1": "Road",
                "building_number": "4321",
                "city": "Riyadh",
                "postcode": "12345",
            },
            icv=1,
            previous_hash=FIRST_PREVIOUS_HASH,
            unit_code_for=lambda unit: "PCE",
            now=NOW,
        )
        totals = builder.compute(spec)
        assert totals.vat == Decimal("750000.00")
        assert totals.payable == Decimal("5750000.00")
        # The distinguishing figure: subtracting a 10% retention first would tax only 4,500,000.
        assert totals.vat != Decimal("675000.00")

    def test_liquidated_damages_are_a_credit_note_with_vat(self):
        # §5.4, Example 6: 440,000 + 66,000 VAT = 506,000.
        spec = make_input(
            type_code=TYPE_CREDIT_NOTE,
            lines=(builder.Line("Liquidated damages", Decimal("1"), "PCE", Decimal("440000")),),
        )
        totals = builder.compute(spec)
        assert (totals.vat, totals.payable) == (Decimal("66000.00"), Decimal("506000.00"))

    def test_a_prepayment_is_deducted_from_what_is_payable(self):
        prepayment = builder.Prepayment(
            number="ADV-1", issue_date="2026-09-01", issue_time="09:00:00", taxable_amount=Decimal("200"), uuid="u-1"
        )
        spec = make_input(
            lines=(builder.Line("Works", Decimal("1"), "PCE", Decimal("1000")),), prepayments=(prepayment,)
        )
        totals = builder.compute(spec)
        assert totals.vat == Decimal("150.00")  # the VAT of the whole supply, as in the SDK sample
        assert totals.prepaid == Decimal("230.00")
        assert totals.payable == Decimal("920.00")

    def test_a_negative_line_is_refused_and_pointed_at_the_credit_note(self):
        spec = make_input(lines=(builder.Line("Reduction", Decimal("1"), "PCE", Decimal("-50")),))
        with pytest.raises(builder.ZatcaBuildError, match="credit note"):
            builder.build_unsigned(spec)

    def test_a_credit_note_needs_the_invoice_it_corrects(self):
        spec = make_input(type_code=TYPE_CREDIT_NOTE, billing_reference="")
        with pytest.raises(builder.ZatcaBuildError, match="BR-KSA-56"):
            builder.build_unsigned(spec)

    def test_a_zero_rated_line_needs_a_reason_code(self):
        line = builder.Line(
            "Export works", Decimal("1"), "PCE", Decimal("100"), vat_category="Z", vat_rate=Decimal("0")
        )
        with pytest.raises(builder.ZatcaBuildError, match="BR-KSA-CL-04"):
            builder.build_unsigned(make_input(lines=(line,)))

    def test_a_simplified_export_is_refused(self):
        spec = make_input(simplified=True)
        spec = builder.ZatcaInvoiceInput(**{**spec.__dict__, "subtype": Subtype(simplified=True, export=True)})
        with pytest.raises(builder.ZatcaBuildError, match="BR-KSA-31"):
            builder.build_unsigned(spec)

    def test_an_advance_is_type_386_and_builds(self):
        root = builder.build_unsigned(make_input(type_code=TYPE_PREPAYMENT))
        assert 'name="0100000">386<' in c14n.serialize(root)


# ── The offline checks ──────────────────────────────────────────────────────


class TestChecks:
    @pytest.mark.parametrize("simplified", [False, True])
    async def test_a_document_we_build_has_no_findings(self, simplified):
        _root, _stamp, text, _ = await stamped(make_input(simplified=simplified))
        assert codes_of(text) == []

    async def test_tampering_with_an_amount_breaks_the_stamp(self):
        _root, _stamp, text, _ = await stamped(make_input())
        tampered = text.replace(
            '<cbc:InvoicedQuantity unitCode="PCE">2.00<', '<cbc:InvoicedQuantity unitCode="PCE">3.00<'
        )
        assert tampered != text
        found = checks.check_document(tampered, profile_vat=SELLER_VAT, now=CHECK_TIME)
        assert any(i.group == checks.GROUP_STAMP and i.severity == checks.SEVERITY_ERROR for i in found)

    async def test_a_negative_amount_and_a_third_decimal_are_reported_on_the_amount_path(self):
        # These reach the amount reader that reports BR-KSA-F-04 and BR-DEC.
        _root, _stamp, text, _ = await stamped(make_input())
        negative = re.sub(r"(<cbc:LineExtensionAmount currencyID=\"SAR\">)200\.00", r"\g<1>-200.00", text, count=1)
        assert "BR-KSA-F-04" in codes_of(negative)
        long = re.sub(r"(<cbc:LineExtensionAmount currencyID=\"SAR\">)200\.00", r"\g<1>200.001", text, count=1)
        assert "BR-DEC" in codes_of(long)

    async def test_text_that_is_not_a_number_is_reported_not_raised(self):
        _root, _stamp, text, _ = await stamped(make_input())
        broken = re.sub(r"(<cbc:LineExtensionAmount currencyID=\"SAR\">)200\.00", r"\g<1>two hundred", text, count=1)
        assert "BR-KSA-F-04" in codes_of(broken)

    async def test_an_unknown_vat_category_is_reported(self):
        _root, _stamp, text, _ = await stamped(make_input())
        broken = text.replace("<cbc:ID>S</cbc:ID>", "<cbc:ID>Q</cbc:ID>")
        assert "BR-KSA-18" in codes_of(broken)

    async def test_a_zero_rated_category_without_a_reason_is_reported(self):
        _root, _stamp, text, _ = await stamped(make_input())
        broken = text.replace("<cbc:ID>S</cbc:ID>", "<cbc:ID>E</cbc:ID>")
        found = codes_of(broken)
        assert "BR-KSA-11" in found or "BR-KSA-CL-04" in found

    async def test_a_seller_vat_number_that_does_not_end_in_three_is_reported(self):
        _root, _stamp, text, _ = await stamped(make_input())
        broken = text.replace(SELLER_VAT, "399999999900004")
        assert any(c.startswith("BR-KSA") for c in codes_of(broken))

    def test_text_that_is_not_xml_is_one_readable_finding(self):
        found = checks.check_document("this is not xml", profile_vat=SELLER_VAT, now=CHECK_TIME)
        assert [(i.code, i.group) for i in found] == [("XML", checks.GROUP_READABLE)]

    def test_the_identity_of_a_document_is_its_uuid_and_subtype(self):
        text = c14n.serialize(builder.build_unsigned(make_input(simplified=True)))
        assert checks.read_identity(text) == ("8e6000cf-1a98-4174-b3e7-b5d5954bc10d", "0200000")
        assert checks.issue_moment(text) == dt.datetime(2026, 10, 19, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=3)))

    def test_construction_rules_refuse_what_the_guideline_says_has_no_invoice(self):
        found = checks.construction_issues({"kind": "retention_release"}, type_code=TYPE_INVOICE)
        assert [i.code for i in found] == ["SA-CONSTRUCTION-NO-INVOICE"]
        assert "§5.2" in found[0].message
        found = checks.construction_issues({"kind": "damages_compensation"}, type_code=TYPE_CREDIT_NOTE)
        assert [i.code for i in found] == ["SA-CONSTRUCTION-NO-INVOICE"]

    def test_liquidated_damages_must_be_a_credit_note(self):
        found = checks.construction_issues({"kind": "liquidated_damages"}, type_code=TYPE_INVOICE)
        assert [i.code for i in found] == ["SA-CONSTRUCTION-TYPE"]
        assert checks.construction_issues({"kind": "liquidated_damages"}, type_code=TYPE_CREDIT_NOTE) == []

    def test_an_unknown_construction_kind_is_an_error(self):
        found = checks.construction_issues({"kind": "bonus"}, type_code=TYPE_INVOICE)
        assert [i.code for i in found] == ["SA-CONSTRUCTION-KIND"]
        assert found[0].severity == checks.SEVERITY_ERROR

    def test_a_government_claim_without_a_payment_order_date_only_warns(self):
        fields = {"government": {"contract": "C-1", "role": "main"}}
        found = checks.construction_issues(fields, type_code=TYPE_INVOICE)
        assert [(i.code, i.severity) for i in found] == [("SA-GOV-TAX-POINT", checks.SEVERITY_WARNING)]
        sub = {"government": {"contract": "C-1", "role": "subcontractor"}}
        assert checks.construction_issues(sub, type_code=TYPE_INVOICE) == []


# ── Signers and the CSR ─────────────────────────────────────────────────────


class TestSigners:
    def test_a_test_signer_is_refused_on_a_live_registration(self):
        with pytest.raises(signing.SigningError, match="live"):
            signing.resolve_signer(signing.SIGNER_TEST, sandbox=False)

    def test_a_stored_key_needs_a_certificate_and_a_key(self):
        with pytest.raises(signing.SigningError, match="CSID"):
            signing.resolve_signer(signing.SIGNER_STORED_KEY, sandbox=True)
        with pytest.raises(signing.SigningError, match="key"):
            signing.resolve_signer(signing.SIGNER_STORED_KEY, sandbox=True, certificate="x")

    async def test_a_key_that_is_not_on_secp256k1_is_refused(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        other = ec.generate_private_key(ec.SECP256R1())
        donor = signing.make_test_signer()
        with pytest.raises(signing.SigningError, match="secp256k1"):
            signing.KeySigner(other, donor.certificate.certificate, kind="stored_key")

    async def test_an_external_signer_signs_through_the_service(self):
        import httpx

        donor = signing.make_test_signer()

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.read()
            assert b"ECDSA-SHA256" in body
            return httpx.Response(200, json={"signature": base64.b64encode(b"sig").decode()})

        async def resolves(url: str) -> str:
            return url

        external = signing.ExternalHttpSigner(
            "https://signer.example/sign",
            donor.certificate.certificate,
            transport=httpx.MockTransport(handler),
            url_guard=resolves,
        )
        assert await external.sign(b"x" * 32) == b"sig"

    async def test_an_external_signer_at_a_metadata_address_is_refused(self):
        donor = signing.make_test_signer()
        external = signing.ExternalHttpSigner("https://169.254.169.254/sign", donor.certificate.certificate)
        with pytest.raises(signing.SigningError, match="refused"):
            await external.sign(b"x" * 32)

    def test_an_external_signer_must_be_https(self):
        donor = signing.make_test_signer()
        with pytest.raises(signing.SigningError, match="https"):
            signing.ExternalHttpSigner("http://signer.example/sign", donor.certificate.certificate)


class TestCsr:
    FIELDS = csr.CsrFields(
        common_name="EGS1-886431145",
        serial_number="1-OCE|2-1|3-ed22f1d8-e6a2-1118-9b58-d9a8f11e445f",
        vat_number=SELLER_VAT,
        organization_unit="Riyadh Branch",
        organization_name="Maximum Speed Tech Supply LTD",
        location="Riyadh 12214",
        industry="Construction",
    )

    def test_the_csr_carries_the_template_extension_and_the_subject(self):
        key = signing.generate_key()
        pem = csr.build_csr(self.FIELDS, key, environment="developer_portal")
        request = csr.read_csr(pem)
        assert request.is_signature_valid
        oids = {ext.oid.dotted_string for ext in request.extensions}
        assert csr.TEMPLATE_OID.dotted_string in oids
        assert SELLER_VAT in pem or base64.b64decode(csr.csr_for_api(pem))  # the API form decodes

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"vat_number": "123"}, "15 digits"),
            ({"organization_name": "Acme_Co"}, "must not contain"),
            ({"serial_number": "abc"}, "serial number"),
            ({"invoice_type": "12"}, "invoice type"),
            ({"location": ""}, "location is required"),
        ],
    )
    def test_fields_zatca_would_refuse_are_refused_here(self, change, message):
        fields = csr.CsrFields(**{**self.FIELDS.__dict__, **change})
        with pytest.raises(csr.CsrError, match=message):
            csr.build_csr(fields, signing.generate_key(), environment="developer_portal")

    def test_an_unknown_environment_is_refused(self):
        with pytest.raises(csr.CsrError, match="environment"):
            csr.build_csr(self.FIELDS, signing.generate_key(), environment="moon")
