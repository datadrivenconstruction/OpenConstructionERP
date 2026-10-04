# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAEB X89 (Rechnung): the invoice of a progress claim, and the check of a received one.

Pure tests over the line mapping, the builder, the parser and the checker.
No app, no database.

The money cases are built so a wrong implementation fails them:

* the second claim on a contract bills its own period only. Its cumulative
  column is twice its period column, so writing cumulative instead of period
  would double the invoice and the totals assertion would see it;
* one line was claimed at a value that is not quantity times rate. Its
  amount must stay the claimed value, so re-multiplying would break the
  equality with the claim's gross;
* VAT follows the existing GAEB export: ``TotalNet`` excludes tax,
  ``VATAmount`` is computed once on the net and ``TotalGross`` is net plus
  VAT to the cent. A rate whose per-line VAT would round differently from
  the VAT on the sum is used, so summing rounded line VAT would be off by a
  cent;
* in the check, the per-line differences add up to the total difference.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_x89_invoice.py -v
"""

from __future__ import annotations

import copy
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.modules.boq.gaeb_x89 import (
    InvoiceInput,
    InvoiceLine,
    InvoiceParty,
    build_x89_xml,
    check_x89,
    invoice_figures,
    invoice_lines_from_claim,
    missing_invoice_fields,
    parse_x89,
)
from app.modules.boq.importers import ImporterParseError
from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

NS = "{http://www.gaeb.de/GAEB_DA_XML/DA89/3.3}"
D = Decimal

CONTRACTOR = InvoiceParty(
    name="Rohbau Nord GmbH", street="Hafenweg 4", postcode="20457", city="Hamburg", tax_no="22/815/04711"
)
CLIENT = InvoiceParty(name="Stadt Musterstadt", street="Rathausplatz 1", postcode="12345", city="Musterstadt")


# ── A contract with three schedule lines and two claims on it ────────────

SOV = {
    "L1": SimpleNamespace(
        id="L1",
        code="1",
        description="Concrete",
        unit="m3",
        unit_rate="185.50",
        total_value="18550",
        order_index=1,
        metadata_={"boq_position_id": "P1"},
    ),
    "L2": SimpleNamespace(
        id="L2",
        code="2",
        description="Rebar",
        unit="t",
        unit_rate="1340",
        total_value="13400",
        order_index=2,
        metadata_={"boq_position_id": "P2"},
    ),
    "L3": SimpleNamespace(
        id="L3",
        code="3",
        description="Site setup",
        unit="lsum",
        unit_rate="4000",
        total_value="4000",
        order_index=3,
        metadata_={},
    ),
}
POSITIONS = {
    "P1": SimpleNamespace(
        id="P1",
        boq_id="B1",
        ordinal="01.0010",
        description="Beton C30/37",
        unit="m3",
        quantity="100",
        unit_rate="185.50",
        metadata_={},
    ),
    "P2": SimpleNamespace(
        id="P2",
        boq_id="B1",
        ordinal="01.0020",
        description="Betonstahl",
        unit="t",
        quantity="10",
        unit_rate="1340",
        metadata_={},
    ),
}


def _position_for(line: SimpleNamespace) -> str | None:
    return (line.metadata_ or {}).get("boq_position_id")


def _claim_line(line_id: str, qty: str, value: str, pct: str = "0", cumulative: str = "0") -> SimpleNamespace:
    return SimpleNamespace(
        contract_line_id=line_id,
        period_completed_qty=qty,
        period_completed_value=value,
        period_completed_pct=pct,
        cumulative_completed_value=cumulative,
    )


# Claim 1: 40 m3 and 3 t. Claim 2: another 40 m3 and 3 t, and a quarter of the
# site setup billed by value. Claim 2's cumulative is claim 1 plus claim 2.
CLAIM_1 = [
    _claim_line("L1", "40", "7420.00", cumulative="7420.00"),
    _claim_line("L2", "3", "4020.00", cumulative="4020.00"),
]
CLAIM_2 = [
    _claim_line("L1", "40", "7420.00", cumulative="14840.00"),
    # Claimed at an agreed value that is not 3 x 1340 = 4020.
    _claim_line("L2", "3", "3999.99", cumulative="8019.99"),
    _claim_line("L3", "0", "1000.00", pct="25", cumulative="1000.00"),
    # Nothing this period: not billed, not written.
    _claim_line("L1", "0", "0"),
]


def _invoice(lines: list[InvoiceLine], *, vat: str = "19", retention: str = "0", no: str = "AR-2") -> InvoiceInput:
    return InvoiceInput(
        invoice_no=no,
        invoice_date=date(2026, 10, 1),
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        currency="EUR",
        project_name="Kita Nord",
        boq_name="LV Rohbau",
        lines=lines,
        vat_rate=D(vat),
        retention=D(retention),
        creator=CONTRACTOR,
        recipient=CLIENT,
        sequential_no=2,
    )


def _items(xml: str) -> list[ET.Element]:
    return ET.fromstring(xml).findall(f".//{NS}Item")


def _totals(xml: str) -> dict[str, Decimal]:
    totals = ET.fromstring(xml).find(f"{NS}Invoice/{NS}BoQ/{NS}BoQInfo/{NS}Totals")
    assert totals is not None
    return {_tag(child): D(child.text or "0") for child in totals}


def _tag(el: ET.Element) -> str:
    return el.tag.split("}", 1)[1]


# ── Claim lines to invoice lines ────────────────────────────────────────


def test_each_claim_bills_its_own_period_not_the_running_total() -> None:
    first, _ = invoice_lines_from_claim(CLAIM_1, SOV, POSITIONS, position_for_line=_position_for)
    second, boqs = invoice_lines_from_claim(CLAIM_2, SOV, POSITIONS, position_for_line=_position_for)

    assert [ln.amount for ln in first] == [D("7420.00"), D("4020.00")]
    assert [ln.amount for ln in second] == [D("7420.00"), D("3999.99"), D("1000.00")]
    # Two invoices together bill exactly the cumulative of the second claim.
    cumulative = sum((D(cl.cumulative_completed_value) for cl in CLAIM_2), D("0"))
    assert sum((ln.amount for ln in first + second), D("0")) == cumulative
    assert boqs == {"B1": 2}


def test_linked_lines_take_the_bill_oz_and_unlinked_keep_their_code() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_2, SOV, POSITIONS, position_for_line=_position_for)
    assert [(ln.oz, ln.unit) for ln in lines] == [("01.0010", "m3"), ("01.0020", "t"), ("3", "psch")]
    assert lines[0].description == "Beton C30/37"


def test_a_line_billed_by_value_is_a_share_of_a_lump_sum() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_2, SOV, POSITIONS, position_for_line=_position_for)
    setup = lines[2]
    assert (setup.bill_qty, setup.unit_price, setup.amount) == (D("0.25"), D("4000"), D("1000.00"))


def test_a_link_to_a_position_outside_the_project_does_not_lend_its_oz() -> None:
    lines, boqs = invoice_lines_from_claim(CLAIM_1, SOV, {}, position_for_line=_position_for)
    assert [ln.oz for ln in lines] == ["1", "2"]
    assert boqs == {}


# ── The X89 document ────────────────────────────────────────────────────


def test_item_totals_equal_the_claim_gross_and_vat_matches_the_x84_export() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_2, SOV, POSITIONS, position_for_line=_position_for)
    claim_gross = sum((D(cl.period_completed_value) for cl in CLAIM_2), D("0"))
    exported = build_x89_xml(_invoice(lines, vat="19"))

    amounts = [D(item.findtext(f"{NS}IT") or "0") for item in _items(exported.xml)]
    assert sum(amounts, D("0")) == claim_gross == D("12419.99")

    totals = _totals(exported.xml)
    assert totals["Total"] == claim_gross
    # Like the X84 export, TotalNet is the figure without tax.
    assert totals["TotalNet"] == claim_gross
    assert totals["VAT"] == D("19.00")
    assert totals["VATAmount"] == D("2359.80")  # 12419.99 x 19 % = 2359.7981
    assert totals["TotalGross"] == totals["TotalNet"] + totals["VATAmount"] == D("14779.79")
    invoice_gross = ET.fromstring(exported.xml).findtext(f"{NS}Invoice/{NS}TotalGross")
    assert D(invoice_gross or "0") == totals["TotalGross"]


def test_vat_is_taken_once_on_the_net_not_summed_per_line() -> None:
    # Three lines of 0.03 at 19 %: per line 0.0057 rounds to 0.01, so summed
    # line VAT would be 0.03; on the 0.09 net it is 0.0171, which rounds to 0.02.
    lines = [InvoiceLine(f"01.00{i}0", "x", "St", D("1"), D("0.03"), D("0.03")) for i in range(1, 4)]
    figures = invoice_figures(lines, vat_rate=D("19"), retention=D("0"))
    assert figures.net == D("0.09")
    assert figures.vat_amount == D("0.02")
    assert figures.gross == D("0.11")


def test_amount_is_the_claimed_value_even_when_it_is_not_qty_times_price() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_2, SOV, POSITIONS, position_for_line=_position_for)
    exported = build_x89_xml(_invoice(lines))
    rebar = next(i for i in _items(exported.xml) if i.findtext(f"{NS}UP") == "1340.000")
    assert rebar.findtext(f"{NS}BillQty") == "3.000"
    assert rebar.findtext(f"{NS}IT") == "3999.99"


def test_retention_is_a_counter_claim_and_the_outstanding_amount_is_what_is_due() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_1, SOV, POSITIONS, position_for_line=_position_for)
    exported = build_x89_xml(_invoice(lines, retention="572.00"))
    shares = {s.findtext(f"{NS}InvoiceShareType"): s for s in ET.fromstring(exported.xml).iter(f"{NS}InvoiceShare")}
    assert D(shares["basic amount"].findtext(f"{NS}Total") or "0") == D("11440.00")
    assert D(shares["VAT"].findtext(f"{NS}Total") or "0") == D("2173.60")
    deposit = shares["security deposit"]
    assert D(deposit.findtext(f"{NS}Total") or "0") == D("572.00")
    assert deposit.findtext(f"{NS}CounterClaim") == "Yes"
    assert D(shares["outstanding amount"].findtext(f"{NS}Total") or "0") == D("13041.60")
    assert exported.figures.payable == D("13041.60")
    # Retention is held from payment, not from the invoice: the gross stays.
    assert exported.figures.gross == D("13613.60")


def test_no_retention_writes_no_deposit_share() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_1, SOV, POSITIONS, position_for_line=_position_for)
    exported = build_x89_xml(_invoice(lines))
    types = [s.findtext(f"{NS}InvoiceShareType") for s in ET.fromstring(exported.xml).iter(f"{NS}InvoiceShare")]
    assert types == ["basic amount", "VAT"]


def test_category_totals_add_up_to_the_bill_total() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_2, SOV, POSITIONS, position_for_line=_position_for)
    exported = build_x89_xml(_invoice(lines))
    root = ET.fromstring(exported.xml)
    body = root.find(f"{NS}Invoice/{NS}BoQ/{NS}BoQBody")
    assert body is not None
    category_totals = [D(c.findtext(f"{NS}Totals/{NS}Total") or "0") for c in body.findall(f"{NS}BoQCtgy")]
    assert sum(category_totals, D("0")) == _totals(exported.xml)["Total"]


def test_an_oz_gaeb_cannot_spell_is_remapped_and_said_so() -> None:
    lines = [
        InvoiceLine("01.0010", "Beton", "m3", D("1"), D("10"), D("10")),
        InvoiceLine("A/7", "Nachtrag", "psch", D("1"), D("5"), D("5")),
    ]
    exported = build_x89_xml(_invoice(lines))
    assert exported.remapped == [{"ordinal": "A/7", "written_as": "ZZ.Z001", "reason": "ordinal_not_representable"}]
    texts = ["".join(i.itertext()) for i in _items(exported.xml)]
    assert any("A/7" in t for t in texts)
    assert _totals(exported.xml)["Total"] == D("15.00")


def test_missing_mandatory_fields_are_named_and_the_export_refuses() -> None:
    data = _invoice([InvoiceLine("1", "x", "St", D("1"), D("1"), D("1"))], no=" ")
    data.creator = InvoiceParty(name="Rohbau Nord GmbH")
    data.period_end = None
    missing = missing_invoice_fields(data)
    assert {"invoice_no", "period_end", "creator.street", "creator.postcode", "creator.city", "creator.tax_no"} <= set(
        missing
    )
    assert not any(m.startswith("recipient.") for m in missing)
    with pytest.raises(ValueError, match="creator.street"):
        build_x89_xml(data)


def test_a_vat_id_satisfies_the_tax_number() -> None:
    data = _invoice([InvoiceLine("1", "x", "St", D("1"), D("1"), D("1"))])
    data.creator = InvoiceParty(name="A", street="B", postcode="1", city="C", vat_id="DE123456789")
    assert missing_invoice_fields(data) == []


# ── Checking a received invoice ─────────────────────────────────────────

_RECEIVED = b"""<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA89/3.3">
  <GAEBInfo><Version>3.3</Version><VersDate>2021-05</VersDate><Date>2026-10-01</Date></GAEBInfo>
  <PrjInfo><NamePrj>Kita Nord</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Invoice>
    <DP>89</DP>
    <BoQ ID="B">
      <BoQInfo>
        <Name>LV</Name><LblBoQ>LV</LblBoQ><OutlCompl>OutTxt</OutlCompl>
        <BoQBkdn><Type>BoQLevel</Type><Length>2</Length><Num>Yes</Num></BoQBkdn>
        <BoQBkdn><Type>Item</Type><Length>4</Length><Num>Yes</Num></BoQBkdn>
        <Totals><Total>10620.00</Total><VAT>19.00</VAT><TotalNet>10620.00</TotalNet><VATAmount>2017.80</VATAmount><TotalGross>12637.80</TotalGross></Totals>
      </BoQInfo>
      <BoQBody>
        <BoQCtgy ID="C1" RNoPart="01">
          <LblTx><p><span>Rohbau</span></p></LblTx>
          <BoQBody><Itemlist>
            <Item ID="I1" RNoPart="0010"><BillQty>40.000</BillQty><QU>m3</QU><UP>185.500</UP><IT>7420.00</IT>
              <Description><OutlineText><OutlTxt><TextOutlTxt><p><span>Beton</span></p></TextOutlTxt></OutlTxt></OutlineText></Description></Item>
            <Item ID="I2" RNoPart="0020"><BillQty>2.000</BillQty><QU>t</QU><UP>1400.000</UP><IT>2800.00</IT>
              <Description><OutlineText><OutlTxt><TextOutlTxt><p><span>Stahl</span></p></TextOutlTxt></OutlTxt></OutlineText></Description></Item>
            <Item ID="I3" RNoPart="0090"><BillQty>1.000</BillQty><QU>psch</QU><UP>350.000</UP><IT>400.00</IT>
              <Description><OutlineText><OutlTxt><TextOutlTxt><p><span>Zulage</span></p></TextOutlTxt></OutlTxt></OutlineText></Description></Item>
          </Itemlist></BoQBody>
          <Totals><Total>10620.00</Total></Totals>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
    <InvoiceHeader><InvoiceNo>R-17</InvoiceNo><InvoiceDate>2026-10-01</InvoiceDate><InvoiceType>deduction</InvoiceType>
      <ServiceProvisionStartDate>2026-09-01</ServiceProvisionStartDate><ServiceProvisionEndDate>2026-09-30</ServiceProvisionEndDate></InvoiceHeader>
    <InvoiceCreator><Address><Name1>A</Name1><Street>B</Street><PCode>1</PCode><City>C</City></Address><TaxNo>1</TaxNo></InvoiceCreator>
    <InvoiceRecipient><Address><Name1>D</Name1><Street>E</Street><PCode>2</PCode><City>F</City></Address></InvoiceRecipient>
    <InvoiceShare><InvoiceShareType>basic amount</InvoiceShareType><Description>netto</Description><Total>10620.00</Total></InvoiceShare>
    <TotalGross>12637.80</TotalGross>
  </Invoice>
</GAEB>
"""


def _is_section(pos: SimpleNamespace) -> bool:
    return pos.unit == "section"


def test_check_reports_every_difference_and_they_add_up_to_the_total() -> None:
    positions = [
        *POSITIONS.values(),
        SimpleNamespace(
            id="S", ordinal="01", unit="section", quantity="0", unit_rate="0", description="Rohbau", metadata_={}
        ),
    ]
    before = copy.deepcopy([vars(p) for p in positions])
    report = check_x89(parse_x89(_RECEIVED), positions, is_section=_is_section)

    by_oz = {ln["oz"]: ln for ln in report["lines"]}
    assert by_oz["01.0010"]["issues"] == []
    assert by_oz["01.0010"]["difference"] == "0.00"
    assert by_oz["01.0020"]["issues"] == ["unit_price_differs"]
    assert by_oz["01.0020"]["expected_amount"] == "2680.00"
    assert by_oz["01.0020"]["difference"] == "120.00"
    assert set(by_oz["01.0090"]["issues"]) == {"amount_not_qty_times_price", "unknown_oz"}
    assert by_oz["01.0090"]["difference"] == "400.00"

    assert report["invoiced_total"] == "10620.00"
    assert report["expected_total"] == "10100.00"
    assert report["total_difference"] == "520.00"
    assert sum((D(ln["difference"]) for ln in report["lines"]), D("0")) == D(report["total_difference"])
    assert report["issue_counts"] == {"unit_price_differs": 1, "amount_not_qty_times_price": 1, "unknown_oz": 1}
    assert all(row["matches"] for row in report["totals_check"])
    assert report["header"]["InvoiceNo"] == "R-17"
    assert report["positions_not_invoiced"] == 0
    # A check writes nothing.
    assert [vars(p) for p in positions] == before


def test_check_flags_a_stated_total_that_does_not_add_up() -> None:
    tampered = _RECEIVED.replace(b"<VATAmount>2017.80</VATAmount>", b"<VATAmount>2117.80</VATAmount>")
    report = check_x89(parse_x89(tampered), list(POSITIONS.values()), is_section=_is_section)
    by_key = {row["key"]: row for row in report["totals_check"]}
    assert by_key["vat_amount"]["matches"] is False
    assert by_key["vat_amount"]["computed"] == "2017.80"


def test_a_quantity_split_over_one_oz_twice_is_held_against_the_bill_as_one() -> None:
    """40 m3 and 70 m3 under the same OZ are each below the 100 m3 of the bill, together above it."""
    split = _RECEIVED.replace(
        b'<Item ID="I3" RNoPart="0090"><BillQty>1.000</BillQty><QU>psch</QU><UP>350.000</UP><IT>400.00</IT>',
        b'<Item ID="I3" RNoPart="0010"><BillQty>70.000</BillQty><QU>m3</QU><UP>185.500</UP><IT>12985.00</IT>',
    )
    assert split != _RECEIVED
    report = check_x89(parse_x89(split), list(POSITIONS.values()), is_section=_is_section)

    concrete = [ln for ln in report["lines"] if ln["oz"] == "01.0010"]
    assert len(concrete) == 2
    for line in concrete:
        assert "duplicate_oz_in_file" in line["issues"]
        assert "quantity_above_boq" in line["issues"]
    # The bill's other position is under its quantity and stays clean of both.
    steel = next(ln for ln in report["lines"] if ln["oz"] == "01.0020")
    assert "quantity_above_boq" not in steel["issues"]
    assert "duplicate_oz_in_file" not in steel["issues"]
    assert report["issue_counts"]["quantity_above_boq"] == 2
    # The money still reconciles line by line.
    assert sum((D(ln["difference"]) for ln in report["lines"]), D("0")) == D(report["total_difference"])


def test_a_single_item_under_the_bill_quantity_is_not_flagged() -> None:
    report = check_x89(parse_x89(_RECEIVED), list(POSITIONS.values()), is_section=_is_section)
    assert all("quantity_above_boq" not in ln["issues"] for ln in report["lines"])
    assert all("duplicate_oz_in_file" not in ln["issues"] for ln in report["lines"])


def test_an_item_without_a_billed_quantity_is_named() -> None:
    no_qty = _RECEIVED.replace(b"<BillQty>40.000</BillQty>", b"")
    report = check_x89(parse_x89(no_qty), list(POSITIONS.values()), is_section=_is_section)
    concrete = next(ln for ln in report["lines"] if ln["oz"] == "01.0010")
    assert "missing_quantity" in concrete["issues"]
    # Without a quantity nothing is expected, so the whole amount is the difference.
    assert concrete["difference"] == "7420.00"


def test_our_own_export_checks_clean_against_the_bill() -> None:
    lines, _ = invoice_lines_from_claim(CLAIM_1, SOV, POSITIONS, position_for_line=_position_for)
    exported = build_x89_xml(_invoice(lines))
    report = check_x89(parse_x89(exported.xml.encode("utf-8")), list(POSITIONS.values()), is_section=_is_section)
    assert report["issue_counts"] == {}
    assert report["total_difference"] == "0.00"
    assert all(row["matches"] for row in report["totals_check"])


# ── Refusals ─────────────────────────────────────────────────────────────

_BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA89/3.3"><Invoice><DP>&lol3;</DP></Invoice></GAEB>
"""


def test_entity_expansion_is_refused() -> None:
    with pytest.raises(ImporterParseError, match="security parser"):
        parse_x89(_BILLION_LAUGHS)


def test_a_measurement_is_not_read_as_an_invoice() -> None:
    x31 = b"""<?xml version="1.0"?><GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA31/3.3">
    <QtyDeterm><DP>31</DP><BoQ ID="b"><BoQBody/></BoQ></QtyDeterm></GAEB>"""
    with pytest.raises(ImporterParseError, match="X31"):
        parse_x89(x31)


async def test_the_bill_importer_refuses_an_invoice_instead_of_adding_its_lines() -> None:
    assert GAEBXMLImporter.detect(_RECEIVED[:4096], "rechnung.x89") is True
    with pytest.raises(ImporterParseError, match="X89"):
        await GAEBXMLImporter.parse(_RECEIVED)


# ── The schema GAEB publishes (opt-in) ──────────────────────────────────


def test_published_x89_schema_accepts_the_export() -> None:
    """Validated against GAEB's own X89 schema when a local copy is provided.

    Set ``GAEB_XSD_DIR`` to a directory holding
    ``GAEB_DA_XML_89_3.3_2021-05.xsd`` and its ``GAEB_DA_XML_Lib_3.3_2021-05.xsd``.
    The schema is not redistributed with this repository.
    """
    etree = pytest.importorskip("lxml.etree")
    directory = os.environ.get("GAEB_XSD_DIR", "")
    xsd = Path(directory) / "GAEB_DA_XML_89_3.3_2021-05.xsd"
    if not directory or not xsd.exists():
        pytest.skip("GAEB_XSD_DIR does not hold the published X89 schema")
    parser = etree.XMLParser(load_dtd=False, no_network=True)
    schema = etree.XMLSchema(etree.parse(str(xsd), parser))
    lines, _ = invoice_lines_from_claim(CLAIM_2, SOV, POSITIONS, position_for_line=_position_for)
    lines.append(InvoiceLine("A/7", "Nachtrag", "psch", D("1"), None, D("5")))
    # Every optional party field the claim route fills in production: country
    # and VAT ID on both addresses, a tax number for the recipient too.
    full = _invoice(lines, retention="100")
    full.creator = InvoiceParty(
        name="Rohbau Nord GmbH",
        street="Hafenweg 4",
        postcode="20457",
        city="Hamburg",
        country="DE",
        tax_no="22/815/04711",
        vat_id="DE123456789",
    )
    full.recipient = InvoiceParty(
        name="Stadt Musterstadt",
        street="Rathausplatz 1",
        postcode="12345",
        city="Musterstadt",
        country="DE",
        tax_no="11/222/33333",
        vat_id="DE111222333",
    )
    exported = build_x89_xml(full)
    root = ET.fromstring(exported.xml)
    assert root.findtext(f"{NS}Invoice/{NS}InvoiceCreator/{NS}Address/{NS}VATID") == "DE123456789"
    assert root.findtext(f"{NS}Invoice/{NS}InvoiceRecipient/{NS}TaxNo") == "11/222/33333"
    assert schema.validate(etree.fromstring(exported.xml.encode("utf-8"))), [str(e) for e in schema.error_log][:5]
    assert schema.validate(etree.fromstring(_RECEIVED)), [str(e) for e in schema.error_log][:5]
