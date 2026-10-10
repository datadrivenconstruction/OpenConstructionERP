# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The mapping from plain invoice data to a UBL-TR document, and its dispatch.

Every party, tax number, rate and fraction here is invented. The tax figures
are hand-built with the helpers of the writer's own tests; in production they
come from the shared payment tax calculation and this module never computes
one, which is what several tests below pin: the totals are sums of the group
figures it was handed.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.core.payment_taxes import PaymentTaxResult
from app.modules.einvoice import profiles as profiles_module
from app.modules.einvoice import service as einvoice_service
from app.modules.einvoice.cii import EInvoiceError
from app.modules.einvoice.profiles import (
    EN16931_SYNTAXES,
    PROFILES,
    Profile,
    default_profile_for_country,
    is_en16931_profile,
)
from app.modules.einvoice.rules import FATAL, WARNING
from app.modules.einvoice.service import (
    map_tr_einvoice,
    render_einvoice,
    render_einvoice_pdf,
    render_tr_einvoice,
    violations_for,
)
from app.modules.einvoice.tr_mapper import (
    TR_UUID_NAMESPACE,
    TrGroupTaxes,
    group_lines,
    normalise_tr_tax_number,
    tr_invoice_uuid,
)
from app.modules.einvoice.ubl import CAC, CBC, INV
from tests.unit.test_einvoice_ubl_tr import (
    CUSTOMER_VKN,
    PERSON_TCKN,
    SUPPLIER_VKN,
    WH_CODE,
    WH_FRACTION,
    WH_NAME,
    fig,
    held,
    not_applicable,
    taxes,
)

NS = {"inv": INV, "cac": CAC, "cbc": CBC}
TODAY = dt.date(2026, 10, 10)
INVOICE_ID = uuid.UUID("0b0f5a3e-2c1d-4e6f-8a9b-1c2d3e4f5a6b")

# Invented rates. Nothing below states what any country charges.
RATE_A = "18.5"
RATE_B = "7.25"


def seller(**over: object) -> dict:
    data = {
        "name": "Örnek Mekanik Tesisat Taahhüt A.Ş.",
        "tax_number": SUPPLIER_VKN,
        "tax_office": "Çankaya",
        "line1": "Şehit Öğretmen Caddesi",
        "building_number": "12/A",
        "district": "Çankaya",
        "city": "Ankara",
        "postcode": "06690",
        "country_code": "TR",
    }
    data.update(over)
    return data


def buyer(**over: object) -> dict:
    data = {
        "name": "Güneş Yapı İnşaat Sanayi ve Ticaret Ltd. Şti.",
        "vat_id": f"TR {CUSTOMER_VKN}",
        "tax_office": "Zincirlikuyu",
        "line1": "Büyükdere Caddesi",
        "building_number": "100",
        "district": "Şişli",
        "city": "İstanbul",
        "postcode": "34394",
        "country_code": "TR",
    }
    data.update(over)
    return data


def line(amount: str, *, rate: str | None = RATE_A, code: str = "", unit: str = "m", qty: str = "1") -> dict:
    return {
        "description": "Havalandırma kanalı montajı",
        "quantity": qty,
        "unit": unit,
        "unit_rate": str(Decimal(amount) / Decimal(qty)),
        "amount": amount,
        "vat_rate": rate,
        "withholding_code": code,
    }


def header(currency: str = "TRY") -> dict:
    return {
        "invoice_number": "INV-2026-0042",
        "invoice_date": "2026-10-09",
        "due_date": "2026-11-08",
        "currency_code": currency,
    }


def group(net: str, rate: str, *, withholding: bool = False) -> TrGroupTaxes:
    return TrGroupTaxes(
        vat_rate_pct=Decimal(rate),
        withholding_code=WH_CODE if withholding else "",
        taxes=taxes(net, rate, withholding=(WH_CODE, *WH_FRACTION) if withholding else None),
        withholding_name=WH_NAME if withholding else "",
    )


def mapped(**over: object):
    kwargs: dict = {
        "invoice_id": INVOICE_ID,
        "invoice": header(),
        "line_items": [line("1000.00")],
        "seller": seller(),
        "buyer": buyer(),
        "tr": {"profile_id": "TICARIFATURA"},
        "group_taxes": [group("1000.00", RATE_A)],
        "today": TODAY,
    }
    kwargs.update(over)
    return map_tr_einvoice(**kwargs), kwargs


def fatal(found) -> list[str]:
    return [v.rule_id for v in found if v.severity == FATAL]


# ── the document ─────────────────────────────────────────────────────────────


def test_a_lira_sale_maps_to_a_document_with_no_fatal_finding() -> None:
    (mapping, found), kwargs = mapped()
    assert fatal(found) == []
    inv = mapping.invoice
    assert inv is not None
    assert inv.invoice_type == "SATIS"
    assert mapping.inferred == {"invoice_type": "SATIS"}
    assert inv.customer.tax_number == CUSTOMER_VKN
    assert inv.customer.address.country_name == "Türkiye"
    vat = taxes("1000.00", RATE_A).vat_computed.amount
    assert inv.totals.line_extension == Decimal("1000.00")
    assert inv.totals.tax_inclusive == Decimal("1000.00") + vat
    assert inv.totals.payable == inv.totals.tax_inclusive

    filename, media_type, xml, remaining = render_tr_einvoice(**kwargs)
    assert media_type == "application/xml"
    assert filename.endswith("_ubl_tr.xml")
    root = ET.fromstring(xml)
    assert root.findtext("cbc:ProfileID", namespaces=NS) == "TICARIFATURA"
    assert root.findtext("cbc:UUID", namespaces=NS) == tr_invoice_uuid(INVOICE_ID)
    assert all(v.severity != FATAL for v in remaining)


def test_the_document_number_is_never_taken_from_the_invoice_number() -> None:
    (mapping, found), _ = mapped()
    assert mapping.invoice.document_id == ""
    # Left for the integrator to assign: reported, and not as a blocker.
    assert [v.severity for v in found if v.rule_id == "TR-ID-01"] == [WARNING]

    (numbered, found), _ = mapped(tr={"profile_id": "TICARIFATURA", "document_id": "ABC2026000000042"})
    assert numbered.invoice.document_id == "ABC2026000000042"
    assert "TR-ID-01" not in [v.rule_id for v in found]


def test_the_uuid_is_stable_per_invoice_and_differs_between_invoices() -> None:
    assert tr_invoice_uuid(INVOICE_ID) == tr_invoice_uuid(str(INVOICE_ID))
    assert tr_invoice_uuid(INVOICE_ID) == str(uuid.uuid5(TR_UUID_NAMESPACE, str(INVOICE_ID)))
    assert tr_invoice_uuid(INVOICE_ID) != tr_invoice_uuid(uuid.uuid4())


def test_a_missing_scenario_is_asked_for_and_never_defaulted() -> None:
    (mapping, found), _ = mapped(tr={})
    assert mapping.invoice.profile_id == ""
    assert "TR-PROFILE-01" in fatal(found)


def test_withholding_makes_it_a_tevkifat_and_the_payable_is_net_of_it() -> None:
    (mapping, found), _ = mapped(
        line_items=[line("600.00", code=WH_CODE), line("400.00", code=WH_CODE)],
        group_taxes=[group("1000.00", RATE_A, withholding=True)],
    )
    assert fatal(found) == []
    inv = mapping.invoice
    figures = taxes("1000.00", RATE_A, withholding=(WH_CODE, *WH_FRACTION))
    assert inv.invoice_type == "TEVKIFAT"
    assert mapping.inferred["invoice_type"] == "TEVKIFAT"
    assert inv.totals.tax_inclusive == Decimal("1000.00") + figures.vat_computed.amount
    assert inv.totals.payable == inv.totals.tax_inclusive - figures.vat_withheld.amount
    # The line shares add up to the group figures they were split from.
    assert sum(item.vat_amount for item in inv.lines) == figures.vat_computed.amount
    assert sum(item.vat_withheld for item in inv.lines) == figures.vat_withheld.amount
    assert sum(item.vat_payable for item in inv.lines) == figures.vat_payable.amount
    assert inv.tax_groups[0].withholding_name == WH_NAME


def test_a_stated_invoice_type_is_kept_and_not_reported_as_inferred() -> None:
    (mapping, _found), _ = mapped(tr={"profile_id": "TEMELFATURA", "invoice_type": "satis"})
    assert mapping.invoice.invoice_type == "SATIS"
    assert mapping.inferred == {}


def test_a_euro_invoice_carries_its_exchange_rate_and_defaults_the_rate_date() -> None:
    (mapping, found), kwargs = mapped(
        invoice=header("EUR"),
        tr={"profile_id": "TICARIFATURA", "exchange_rate": "41.2345"},
    )
    assert fatal(found) == []
    assert mapping.invoice.exchange_rate == Decimal("41.2345")
    assert mapping.invoice.exchange_rate_date == dt.date(2026, 10, 9)
    root = ET.fromstring(render_tr_einvoice(**kwargs)[2])
    rate = root.find("cac:PricingExchangeRate", NS)
    assert rate is not None
    assert rate.findtext("cbc:SourceCurrencyCode", namespaces=NS) == "EUR"
    assert rate.findtext("cbc:TargetCurrencyCode", namespaces=NS) == "TRY"


def test_a_natural_person_is_named_by_first_and_family_name() -> None:
    person = buyer(vat_id=PERSON_TCKN, name="", first_name="Ayşe Gül", family_name="Çağlayan", tax_office="")
    (mapping, found), kwargs = mapped(buyer=person, tr={"profile_id": "EARSIVFATURA"})
    assert fatal(found) == []
    assert mapping.invoice.customer.first_name == "Ayşe Gül"
    root = ET.fromstring(render_tr_einvoice(**kwargs)[2])
    party = root.find("cac:AccountingCustomerParty/cac:Party", NS)
    assert party.findtext("cac:Person/cbc:FamilyName", namespaces=NS) == "Çağlayan"
    assert party.find("cac:PartyIdentification/cbc:ID", NS).get("schemeID") == "TCKN"


def test_two_vat_rates_give_two_groups_whose_lines_and_totals_add_up() -> None:
    lines = [line("333.33", rate=RATE_A), line("100.10", rate=RATE_B), line("666.67", rate=RATE_A)]
    groups = group_lines(lines, "TRY")
    assert [(g.key, g.taxable_amount, g.line_indexes) for g in groups] == [
        (RATE_A, Decimal("1000.00"), (0, 2)),
        (RATE_B, Decimal("100.10"), (1,)),
    ]
    supplied = [group(str(g.taxable_amount), str(g.vat_rate_pct)) for g in groups]
    (mapping, found), kwargs = mapped(line_items=lines, group_taxes=supplied)
    assert fatal(found) == []
    inv = mapping.invoice

    vat_by_group = [item.taxes.vat_computed.amount for item in supplied]
    # The document VAT is the sum of the group figures, each rounded on its own.
    assert inv.totals.tax_inclusive - inv.totals.tax_exclusive == sum(vat_by_group)
    assert inv.totals.line_extension == sum(item.line_amount for item in inv.lines) == Decimal("1100.10")
    for found_group, vat in zip(groups, vat_by_group, strict=True):
        assert sum(inv.lines[index].vat_amount for index in found_group.line_indexes) == vat
    assert sum(item.vat_amount for item in inv.lines) == sum(vat_by_group)

    root = ET.fromstring(render_tr_einvoice(**kwargs)[2])
    header_total = root.find("cac:TaxTotal", NS)
    assert len(header_total.findall("cac:TaxSubtotal", NS)) == 2


def test_rounding_per_group_can_differ_from_rounding_the_document_once() -> None:
    """The stated consequence of one TaxSubtotal per rate, shown on one rate split in two.

    Two groups of 0.05 at an invented 10% each round 0.005 up to 0.01, so the
    document carries 0.02 where a single rounding of 0.10 gives 0.01. Separate
    withholding codes are what split one rate into two groups in practice.
    """
    one = taxes("0.05", "10").vat_computed.amount
    whole = taxes("0.10", "10").vat_computed.amount
    assert (one + one, whole) == (Decimal("0.02"), Decimal("0.01"))


def test_a_return_points_at_the_invoice_it_answers() -> None:
    original = {"document_id": "ABC2026000000007", "issue_date": "2026-09-01"}
    (mapping, found), kwargs = mapped(
        tr={"profile_id": "TEMELFATURA", "invoice_type": "IADE", "original_invoice": original}
    )
    assert fatal(found) == []
    reference = mapping.invoice.billing_references[0]
    assert (reference.id, reference.issue_date, reference.document_type_code) == (
        "ABC2026000000007",
        dt.date(2026, 9, 1),
        "IADE",
    )
    root = ET.fromstring(render_tr_einvoice(**kwargs)[2])
    assert root.findtext("cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID", namespaces=NS) == (
        "ABC2026000000007"
    )


def test_a_return_without_its_original_date_is_blocked() -> None:
    (_mapping, found), _ = mapped(
        tr={
            "profile_id": "TEMELFATURA",
            "invoice_type": "IADE",
            "original_invoice": {"document_id": "ABC2026000000007"},
        }
    )
    assert "OCE-TR-12" in fatal(found)


def test_a_missing_tax_office_is_a_warning_and_the_file_is_still_written() -> None:
    (_mapping, found), kwargs = mapped(buyer=buyer(tax_office=""))
    office = [v for v in found if v.rule_id == "TR-PARTY-05"]
    assert [v.severity for v in office] == [WARNING]
    assert fatal(found) == []
    _filename, _media, xml, remaining = render_tr_einvoice(**kwargs)
    assert xml.startswith(b"<?xml")
    assert "TR-PARTY-05" in [v.rule_id for v in remaining]


def test_a_unit_with_no_code_is_a_finding_that_names_the_line() -> None:
    (_mapping, found), kwargs = mapped(line_items=[line("400.00"), line("600.00", unit="gizmo")])
    unit = [v for v in found if v.rule_id == "TR-UNIT-01"]
    assert len(unit) == 1
    assert unit[0].severity == FATAL
    assert "gizmo" in unit[0].message
    assert "2" in unit[0].params.values() or "line 2" in unit[0].message.lower()
    with pytest.raises(EInvoiceError, match="TR-UNIT-01"):
        render_tr_einvoice(**kwargs)


def test_held_vat_blocks_the_file_and_says_why() -> None:
    waiting = PaymentTaxResult(
        vat_computed=fig("vat_computed", Decimal("185.00"), base=Decimal("1000.00"), rate_pct=Decimal(RATE_A)),
        vat_withheld=held("vat_withheld"),
        vat_payable=held("vat_payable"),
        income_withheld=not_applicable("income_withheld"),
        stamp_duty=not_applicable("stamp_duty"),
    )
    (mapping, found), kwargs = mapped(group_taxes=[TrGroupTaxes(Decimal(RATE_A), "", waiting)])
    assert "TR-HELD-01" in fatal(found)
    # Nothing is printed as a number while the figure behind it is held.
    assert all(item.vat_payable is None and item.vat_amount is None for item in mapping.invoice.lines)
    with pytest.raises(EInvoiceError, match="TR-HELD-01"):
        render_tr_einvoice(**kwargs)


def test_a_group_nobody_supplied_taxes_for_is_held_not_zero() -> None:
    (_mapping, found), _ = mapped(group_taxes=[])
    assert "TR-HELD-01" in fatal(found)


def test_a_line_without_a_vat_rate_is_named() -> None:
    (_mapping, found), _ = mapped(line_items=[line("1000.00", rate=None)], group_taxes=[])
    missing = [v for v in found if v.rule_id == "OCE-TR-11"]
    assert len(missing) == 1
    assert missing[0].params["lines"] == "1"


def test_an_unreadable_invoice_date_stops_the_mapping_with_one_finding() -> None:
    (mapping, found), _ = mapped(invoice={**header(), "invoice_date": "soon"})
    assert mapping.invoice is None
    assert [v.rule_id for v in found] == ["OCE-TR-10"]


def test_findings_the_caller_established_are_reported_first() -> None:
    from app.modules.einvoice.rules import RuleViolation

    mine = RuleViolation("OCE-TR-22", FATAL, "taxes are a draft", "TaxTotal", {})
    (_mapping, found), kwargs = mapped(extra_findings=[mine])
    assert found[0] is mine
    with pytest.raises(EInvoiceError, match="OCE-TR-22"):
        render_tr_einvoice(**kwargs)


def test_a_tax_number_loses_only_its_decoration() -> None:
    assert normalise_tr_tax_number(" tr 987 654 3217 ") == "9876543217"
    assert normalise_tr_tax_number("DE123456789") == "DE123456789"
    assert normalise_tr_tax_number(None) == ""


def test_the_internal_note_of_an_invoice_is_not_printed() -> None:
    (mapping, _found), _ = mapped(
        invoice={**header(), "notes": "Auto-created from certified progress claim PC-7"},
        tr={"profile_id": "TICARIFATURA", "notes": ["Sözleşme no 2026/14"]},
    )
    assert mapping.invoice.notes[-1] == "Sözleşme no 2026/14"
    assert not any("Auto-created" in note for note in mapping.invoice.notes)


# ── registration and dispatch ────────────────────────────────────────────────


def test_ubl_tr_is_registered_outside_the_en16931_syntaxes() -> None:
    profile = PROFILES["ubl_tr"]
    assert profile.syntax not in EN16931_SYNTAXES
    assert not is_en16931_profile("ubl_tr")
    assert is_en16931_profile("xrechnung")
    assert default_profile_for_country("tr") == "ubl_tr"
    assert default_profile_for_country("DE") is None
    assert default_profile_for_country(None) is None


@pytest.mark.parametrize("call", [render_einvoice, render_einvoice_pdf, violations_for])
def test_the_en16931_engine_refuses_ubl_tr_by_name(call) -> None:
    with pytest.raises(EInvoiceError, match="UBL-TR"):
        call(invoice=header(), line_items=[line("1000.00")], profile="ubl_tr")


def test_a_syntax_nobody_wrote_a_writer_for_raises_instead_of_falling_through(monkeypatch) -> None:
    """The final branch is explicit: a new syntax is never handed to the CII writer."""
    monkeypatch.setitem(profiles_module.PROFILES, "future", Profile("future", "edifact", "x"))
    with pytest.raises(EInvoiceError, match="edifact"):
        render_einvoice(invoice=header(), line_items=[line("1000.00")], profile="future")
    with pytest.raises(EInvoiceError, match="edifact"):
        einvoice_service._write_en16931(object(), Profile("future", "edifact", "x"), strict=True)


def test_an_unregistered_profile_is_still_a_finding_of_the_dry_run() -> None:
    """Unchanged behaviour: only a registered non-EN 16931 profile is refused."""
    found = violations_for(invoice=header(), line_items=[line("1000.00")], profile="nonsense")
    assert found


# ── the official schema, when a copy is at hand ──────────────────────────────


def _schema():  # noqa: ANN202 - lxml is optional
    directory = os.environ.get("OE_UBLTR_XSD_DIR", "").strip()
    if not directory:
        pytest.skip("OE_UBLTR_XSD_DIR is not set")
    etree = pytest.importorskip("lxml.etree")
    path = Path(directory) / "maindoc" / "UBL-Invoice-2.1.xsd"
    if not path.is_file():
        pytest.skip(f"{path} does not exist")
    return etree, etree.XMLSchema(etree.parse(str(path)))


def _scenarios() -> dict[str, dict]:
    return {
        "sale": {},
        "withholding": {
            "line_items": [line("600.00", code=WH_CODE), line("400.00", code=WH_CODE)],
            "group_taxes": [group("1000.00", RATE_A, withholding=True)],
        },
        "euro": {"invoice": header("EUR"), "tr": {"profile_id": "TICARIFATURA", "exchange_rate": "41.2345"}},
        "person": {
            "buyer": buyer(vat_id=PERSON_TCKN, name="", first_name="Ayşe Gül", family_name="Çağlayan", tax_office=""),
            "tr": {"profile_id": "EARSIVFATURA"},
        },
        "two_rates": {
            "line_items": [line("1000.00", rate=RATE_A), line("100.10", rate=RATE_B)],
            "group_taxes": [group("1000.00", RATE_A), group("100.10", RATE_B)],
        },
        "return": {
            "tr": {
                "profile_id": "TEMELFATURA",
                "invoice_type": "IADE",
                "original_invoice": {"document_id": "ABC2026000000007", "issue_date": "2026-09-01"},
            }
        },
    }


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_the_mapped_document_validates_against_the_official_xsd(name: str) -> None:
    etree, schema = _schema()
    (_mapping, _found), kwargs = mapped(**_scenarios()[name])
    document = etree.fromstring(render_tr_einvoice(**kwargs)[2])
    assert schema.validate(document), schema.error_log
