# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The server PDF is the BOQ editor's only PDF, so it carries what the browser one did.

The editor used to build its PDF in the browser for bills of up to 500 lines.
That copy took its tax from the first percentage tax markup only, so a second
tax line or a fixed one vanished from its totals, while the server PDF prints
every tax line from the authoritative rollup. The button now downloads the
server PDF, and these are the things the browser copy had that the server one
lacked, each with the case that tells right from wrong:

* A line priced in a foreign currency printed its own figure under a "Total
  (EUR)" heading, and the lines of its section stopped adding up to the
  subtotal printed under them. Lines are read in the base currency now.
* The resources a rate is built from could be printed under each line. They
  are per unit of the line in storage, so printed as stored they added up to
  the unit rate and not to the line. They are scaled to the line now.
* The cover counted sections and positions and had a place for whoever
  approves the estimate to sign.
* A bill of several sections opened with a table of contents that gave the
  page each section starts on, and ended with a page listing each section's
  subtotal above the totals.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pypdf
import pytest

from app.modules.boq.pdf_export import (
    _PDF_LABELS,
    _build_boq_table,
    _build_styles,
    _line_money,
    _resource_lines,
    generate_boq_pdf,
    generate_boq_pdf_simple,
    pdf_language,
)

FX = {"USD": "0.90"}


def _position(
    ordinal: str,
    quantity: str,
    unit_rate: str,
    total: str,
    *,
    unit: str = "m3",
    metadata: dict[str, Any] | None = None,
    description: str = "Line",
) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=Decimal(quantity),
        unit_rate=Decimal(unit_rate),
        total=Decimal(total),
        metadata=metadata or {},
    )


def _tax(name: str, percentage: float, amount: str) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        markup_type="percentage",
        category="tax",
        percentage=percentage,
        fixed_amount=Decimal("0"),
        apply_to="cumulative",
        sort_order=0,
        is_active=True,
        amount=Decimal(amount),
    )


def _bill(sections: list[Any], positions: list[Any] | None = None, markups: list[Any] | None = None) -> Any:
    direct = sum((Decimal(str(s.subtotal)) for s in sections), Decimal("0"))
    markups = markups or []
    net = direct + sum((m.amount for m in markups), Decimal("0"))
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Harbour BOQ",
        description="",
        status="draft",
        sections=sections,
        positions=positions or [],
        direct_cost=direct,
        markups=markups,
        net_total=net,
        grand_total=net,
    )


def _section(positions: list[Any], subtotal: str, ordinal: str = "01") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(), ordinal=ordinal, description="Structure", positions=positions, subtotal=Decimal(subtotal)
    )


def _rows(flowables: list[Any]) -> list[list[str]]:
    """Each row of the position table as the text of its six cells."""
    table = flowables[0]
    return [[getattr(cell, "text", cell if isinstance(cell, str) else "") for cell in row] for row in table._cellvalues]


def _row(rows: list[list[str]], ordinal: str) -> list[str]:
    return next(row for row in rows if row[0] == ordinal)


def _money(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _pdf_text(data: bytes) -> list[str]:
    return [page.extract_text() for page in pypdf.PdfReader(io.BytesIO(data)).pages]


# -- A foreign-currency line -----------------------------------------------------


def _mixed_bill() -> Any:
    euro = _position("01.001", "10", "50", "500")
    dollar = _position("01.002", "10", "100", "1000", metadata={"currency": "USD"})
    # 500 EUR + 1000 USD at 0.90 = 1400 EUR, which is what the rollup makes.
    return _bill([_section([euro, dollar], "1400")])


def test_a_dollar_line_on_a_euro_bill_prints_in_euro() -> None:
    rows = _rows(
        _build_boq_table(_mixed_bill(), "EUR", _build_styles(), country_code="IE", base_currency="EUR", fx_rates=FX)
    )

    dollar = _row(rows, "01.002")
    assert dollar[5] == "900.00", "the line total is not in the base currency"
    assert dollar[4] == "90.00", "the rate is not restated in the base currency"
    assert _money(dollar[3]) * _money(dollar[4]) == _money(dollar[5])
    # The euro line is untouched.
    assert _row(rows, "01.001")[4:] == ["50.00", "500.00"]


def test_the_lines_of_a_section_add_up_to_its_subtotal() -> None:
    # The distinguishing case: printed raw, the lines make 1500 under a
    # subtotal of 1400.
    rows = _rows(
        _build_boq_table(_mixed_bill(), "EUR", _build_styles(), country_code="IE", base_currency="EUR", fx_rates=FX)
    )

    lines = sum(_money(_row(rows, o)[5]) for o in ("01.001", "01.002"))
    subtotal = next(row[5] for row in rows if row[2].startswith("Subtotal"))
    assert lines == _money(subtotal) == Decimal("1400")
    assert not any("1,000.00" in cell for row in rows for cell in row)


def test_ungrouped_lines_are_summed_in_the_base_currency_too() -> None:
    dollar = _position("02", "10", "100", "1000", metadata={"currency": "USD"})
    bill = _bill([], positions=[dollar])
    bill.direct_cost = Decimal("900")

    rows = _rows(_build_boq_table(bill, "EUR", _build_styles(), country_code="IE", base_currency="EUR", fx_rates=FX))
    subtotal = next(row[5] for row in rows if row[2].startswith("Subtotal"))
    assert subtotal == "900.00"

    summary = "\n".join(
        _pdf_text(
            generate_boq_pdf_simple(
                bill, "Harbour", currency="EUR", country_code="IE", base_currency="EUR", fx_rates=FX
            )
        )
    )
    assert "900.00 EUR" in summary
    assert "1,000.00 EUR" not in summary


@pytest.mark.parametrize("fx", [{}, {"USD": "0"}, {"USD": "-1"}, {"USD": "bad"}])
def test_a_rate_with_no_usable_fx_entry_is_excluded_from_base_money(fx: dict[str, str]) -> None:
    # Unconverted dollars must never appear under the EUR column headings.
    dollar = _position("01.002", "10", "100", "1000", metadata={"currency": "USD"})
    assert _line_money(dollar, "EUR", fx) == (Decimal("0"), Decimal("0"))
    assert (dollar.total, dollar.unit_rate) == (Decimal("1000"), Decimal("100"))


def test_a_single_currency_line_prints_exactly_as_stored() -> None:
    line = _position("01", "3", "33.3333", "100.00")
    assert _line_money(line, "EUR", FX) == (Decimal("100.00"), Decimal("33.3333"))
    assert _line_money(line, "", None) == (Decimal("100.00"), Decimal("33.3333"))


# -- Resources ---------------------------------------------------------------------


def _resourced() -> Any:
    return _position(
        "01.003",
        "10",
        "110",
        # Stored unconverted, the way update_position builds it: 10 x (60 + 50).
        "1100",
        metadata={
            "resources": [
                {"name": "Labour", "type": "labor", "unit": "h", "quantity": 2, "unit_rate": 30, "currency": "EUR"},
                {"name": "Steel", "type": "material", "unit": "kg", "quantity": 5, "unit_rate": 10, "currency": "USD"},
            ]
        },
    )


def test_resources_are_scaled_to_the_line_and_add_up_to_it() -> None:
    lines = _resource_lines(_resourced(), "EUR", FX)

    assert [(r.name, r.unit, r.quantity, r.unit_rate, r.total) for r in lines] == [
        ("Labour", "h", Decimal("20"), Decimal("30"), Decimal("600")),
        ("Steel", "kg", Decimal("50"), Decimal("9.00"), Decimal("450.00")),
    ]
    total, rate = _line_money(_resourced(), "EUR", FX)
    # Per unit the resources make 105; printed per unit they summed to the
    # rate, not to the 1050 line.
    assert sum(r.total for r in lines) == total == Decimal("1050")
    assert rate == Decimal("105")


def test_resources_print_under_their_line_only_when_asked() -> None:
    bill = _bill([_section([_resourced()], "1050")])
    styles = _build_styles()

    plain = _rows(_build_boq_table(bill, "EUR", styles, country_code="IE", base_currency="EUR", fx_rates=FX))
    assert not any("Labour" in cell for row in plain for cell in row)

    rows = _rows(
        _build_boq_table(
            bill, "EUR", styles, country_code="IE", base_currency="EUR", fx_rates=FX, include_resources=True
        )
    )
    at = next(i for i, row in enumerate(rows) if row[0] == "01.003")
    assert rows[at][5] == "1,050.00"
    labour, steel = rows[at + 1], rows[at + 2]
    assert labour[1:] == ["Labour", "h", "20.00", "30.00", "600.00"]
    assert steel[1:] == ["Steel", "kg", "50.00", "9.00", "450.00"]
    assert _money(labour[5]) + _money(steel[5]) == _money(rows[at][5])


def _dollar_assembly_line() -> Any:
    """A USD assembly applied to a euro project that had no USD rate yet.

    ``assemblies/service.py`` stores the assembly's currency on the position and
    builds the resources without a currency of their own: they inherit the
    line's. 10 m3 at 100 USD, built from 2 units of 50 per m3.
    """
    return _position(
        "01.004",
        "10",
        "100",
        "1000",
        metadata={
            "currency": "USD",
            "resources": [{"name": "Crew", "type": "labor", "unit": "h", "quantity": 2, "unit_rate": 50}],
        },
    )


def test_resources_of_a_foreign_line_are_converted_by_the_lines_currency() -> None:
    # The rate was added in Project Settings afterwards. The rollup converts the
    # line by its own currency, so the rows under it have to come along: read
    # resource by resource they carry no currency and printed 1,000.00 under a
    # 900.00 line.
    line = _dollar_assembly_line()
    total, rate = _line_money(line, "EUR", FX)
    assert (total, rate) == (Decimal("900.00"), Decimal("90.00"))

    (crew,) = _resource_lines(line, "EUR", FX)
    assert (crew.quantity, crew.unit_rate, crew.total) == (Decimal("20"), Decimal("45.00"), Decimal("900.00"))
    assert crew.total == total

    rows = _rows(
        _build_boq_table(
            _bill([_section([line], "900")]),
            "EUR",
            _build_styles(),
            country_code="IE",
            base_currency="EUR",
            fx_rates=FX,
            include_resources=True,
        )
    )
    at = next(i for i, row in enumerate(rows) if row[0] == "01.004")
    assert rows[at][4:] == ["90.00", "900.00"]
    assert rows[at + 1][1:] == ["Crew", "h", "20.00", "45.00", "900.00"]
    assert not any("1,000.00" in cell for row in rows for cell in row)


def test_a_foreign_line_with_no_rate_excludes_its_resource_money_from_base_columns() -> None:
    # The build-up follows the same missing-FX policy as the parent line.
    line = _dollar_assembly_line()
    assert _line_money(line, "EUR", {}) == (Decimal("0"), Decimal("0"))
    (crew,) = _resource_lines(line, "EUR", {})
    assert (crew.quantity, crew.unit_rate, crew.total) == (Decimal("20"), Decimal("0"), Decimal("0"))
    rows = _rows(
        _build_boq_table(
            _bill([_section([line], "0")]),
            "EUR",
            _build_styles(),
            country_code="IE",
            base_currency="EUR",
            fx_rates={},
            include_resources=True,
        )
    )
    at = next(i for i, row in enumerate(rows) if row[0] == "01.004")
    assert rows[at][4:] == ["0.00", "0.00"]
    assert rows[at + 1][1:] == ["Crew", "h", "20.00", "0.00", "0.00"]


def test_a_resource_naming_a_foreign_currency_is_converted_on_its_own() -> None:
    # Once one resource names a foreign currency the rollup converts resource by
    # resource and ignores the line's currency; a resource with no currency is
    # then read as base. The rows follow the same branch, so they still add up.
    line = _position(
        "01.005",
        "10",
        "110",
        "1100",
        metadata={
            "currency": "USD",
            "resources": [
                {"name": "Crew", "unit": "h", "quantity": 2, "unit_rate": 30},
                {"name": "Steel", "unit": "kg", "quantity": 5, "unit_rate": 10, "currency": "USD"},
            ],
        },
    )
    crew, steel = _resource_lines(line, "EUR", FX)
    assert (crew.unit_rate, steel.unit_rate) == (Decimal("30"), Decimal("9.00"))
    total, _rate = _line_money(line, "EUR", FX)
    assert crew.total + steel.total == total == Decimal("1050.00")


def test_resource_rows_follow_the_measurement_system() -> None:
    line = _position(
        "01",
        "2",
        "40",
        "80",
        unit="m",
        metadata={"resources": [{"name": "Kerb", "unit": "m", "quantity": 1, "unit_rate": 40}]},
    )
    rows = _rows(
        _build_boq_table(
            _bill([_section([line], "80")]),
            "USD",
            _build_styles(),
            measurement_system="imperial",
            country_code="US",
            include_resources=True,
        )
    )
    kerb = next(row for row in rows if row[1] == "Kerb")
    assert kerb[2] == "ft"
    assert _money(kerb[3]) * _money(kerb[4]) == pytest.approx(Decimal("80"), abs=Decimal("0.05"))
    assert kerb[5] == "80.00"


def _crewed(ordinal: str, crews: int) -> Any:
    resources: list[Any] = [
        {"name": f"Crew {n}", "unit": "h", "quantity": 1, "unit_rate": 10} for n in range(1, crews + 1)
    ]
    # Not a resource record: skipped when printed, so not counted either.
    resources.append("junk")
    return _position(ordinal, "1", str(10 * crews), str(10 * crews), metadata={"resources": resources})


def test_the_row_budget_counts_the_resource_rows_the_pdf_would_print(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.boq import pdf_export

    # 2 positions + 3 resources = 5 rows, one of them ungrouped.
    bill = _bill([_section([_crewed("01.001", 2)], "20")], positions=[_crewed("02", 1)])
    assert pdf_export.count_boq_resource_rows(bill) == 3

    monkeypatch.setattr(pdf_export, "PDF_ROW_BUDGET", 5)
    assert pdf_export.resource_rows_fit(bill)
    monkeypatch.setattr(pdf_export, "PDF_ROW_BUDGET", 4)
    # Two positions are far inside any position threshold; the rows are not.
    assert not pdf_export.resource_rows_fit(bill)


def test_a_bill_past_the_row_budget_prints_its_lines_without_the_build_up(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.boq import pdf_export

    bill = _bill([_section([_crewed("01.001", 3), _crewed("01.002", 3)], "60")])
    monkeypatch.setattr(pdf_export, "PDF_ROW_BUDGET", 7)  # 2 positions + 6 resources = 8 rows

    text = " ".join(
        " ".join(_pdf_text(generate_boq_pdf(bill, "Harbour", currency="EUR", include_resources=True))).split()
    )
    assert _PDF_LABELS["en"]["resources_omitted"] in text
    assert "Crew 1" not in text
    # Every line is still printed: this is not the summary report.
    assert "01.001" in text and "01.002" in text
    assert _PDF_LABELS["en"]["summary_report"] not in text

    monkeypatch.setattr(pdf_export, "PDF_ROW_BUDGET", 8)
    text = " ".join(
        " ".join(_pdf_text(generate_boq_pdf(bill, "Harbour", currency="EUR", include_resources=True))).split()
    )
    assert "Crew 1" in text
    assert _PDF_LABELS["en"]["resources_omitted"] not in text


def test_a_bill_that_did_not_ask_for_the_build_up_is_not_told_it_was_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.boq import pdf_export

    bill = _bill([_section([_crewed("01.001", 3)], "30")])
    monkeypatch.setattr(pdf_export, "PDF_ROW_BUDGET", 1)
    text = " ".join(" ".join(_pdf_text(generate_boq_pdf(bill, "Harbour", currency="EUR"))).split())
    assert _PDF_LABELS["en"]["resources_omitted"] not in text


def test_malformed_resources_are_skipped_rather_than_failing_the_export() -> None:
    line = _position("01", "2", "40", "80", metadata={"resources": ["junk", None, {"name": "Ok", "quantity": "x"}]})
    assert [r.name for r in _resource_lines(line, "EUR", FX)] == ["Ok"]
    assert _resource_lines(_position("02", "1", "1", "1", metadata={"resources": "nope"}), "EUR", FX) == []


# -- Table of contents and cost summary --------------------------------------------

SECTION_NAMES = ("Earthworks", "Concrete", "Roofing")


def _long_bill() -> Any:
    """Three sections of 40 lines each, so every section starts on a page of its own.

    Each position's description is the same neutral word, so a section's name
    is printed only by its own header row and by the table of contents.
    """
    sections = []
    for number, name in enumerate(SECTION_NAMES, start=1):
        lines = [_position(f"{number:02d}.{i:03d}", "1", "100", "100", description="Item") for i in range(1, 41)]
        section = _section(lines, "4000", ordinal=f"{number:02d}")
        section.description = name
        sections.append(section)
    return _bill(sections)


def _toc_numbers(toc_page: str) -> dict[str, int]:
    """The page number the table of contents prints against each entry."""
    import re

    numbers: dict[str, int] = {}
    for name in (*SECTION_NAMES, "Cost Summary"):
        match = re.search(rf"{name}\s+(\d+)", toc_page)
        assert match, f"{name} has no page number in the table of contents:\n{toc_page}"
        numbers[name] = int(match.group(1))
    return numbers


def test_a_bill_of_several_sections_opens_with_a_table_of_contents_that_points_right() -> None:
    pages = _pdf_text(generate_boq_pdf(_long_bill(), "Harbour", currency="EUR"))

    assert "Table of Contents" in pages[1]
    numbers = _toc_numbers(pages[1])
    starts = [numbers[name] for name in SECTION_NAMES]
    # The distinguishing shape: the sections start on three different pages,
    # all after the contents, so a number off by one page, or the same number
    # for all, cannot pass.
    assert starts == sorted(set(starts)), starts
    assert starts[0] > 2

    for name, number in numbers.items():
        page = pages[number - 1]
        assert name in page, f"{name} is not on page {number}, where the contents point"
        assert f"Page {number} of {len(pages)}" in page, "the number is not the one the footer prints"
        # And it is where the section starts, not a later page it also appears on.
        earlier = [i + 1 for i, text in enumerate(pages[2 : number - 1], start=2) if name in text]
        assert not earlier, f"{name} already appears on page(s) {earlier}"
    assert numbers["Cost Summary"] == len(pages)


def test_a_bill_of_one_section_has_no_table_of_contents() -> None:
    pages = _pdf_text(generate_boq_pdf(_three_taxes(), "Harbour", currency="EUR"))
    assert not any("Table of Contents" in page for page in pages)
    assert "Pos." in pages[1]


def test_the_table_of_contents_is_in_the_project_language() -> None:
    pages = _pdf_text(generate_boq_pdf(_long_bill(), "Hafen", currency="EUR", locale="de"))
    assert "Inhaltsverzeichnis" in pages[1]
    assert "Kostenübersicht" in pages[-1]


def _summary_bill() -> Any:
    """Two sections plus a dollar line outside any section, on a euro project."""
    first = _section([_position("01.001", "10", "50", "500")], "500", ordinal="01")
    second = _section([_position("02.001", "2", "300", "600")], "600", ordinal="02")
    second.description = "Finishes"
    dollar = _position("99", "10", "100", "1000", metadata={"currency": "USD"})
    bill = _bill([first, second], positions=[dollar], markups=[_tax("VAT", 23.0, "460.00")])
    # 500 + 600 + 1000 USD at 0.90, as the rollup makes it.
    bill.direct_cost = Decimal("2000")
    bill.net_total = bill.grand_total = Decimal("2460")
    return bill


def test_the_cost_summary_page_lists_each_section_and_adds_up_to_the_direct_cost() -> None:
    from app.modules.boq.pdf_export import _section_summary_table

    bill = _summary_bill()
    table = _section_summary_table(
        bill, "EUR", _build_styles(), _PDF_LABELS["en"], 170, country_code="IE", base_currency="EUR", fx_rates=FX
    )
    rows = [[getattr(cell, "text", "") for cell in row] for row in table._cellvalues[1:]]
    assert [(row[1], row[3]) for row in rows] == [
        ("Structure", "500.00 EUR"),
        ("Finishes", "600.00 EUR"),
        ("Other Positions", "900.00 EUR"),
    ]
    # The distinguishing case: summed raw, the dollar row makes 2,100.
    assert sum(_money(row[3].removesuffix(" EUR")) for row in rows) == bill.direct_cost

    pages = _pdf_text(
        generate_boq_pdf(bill, "Harbour", currency="EUR", country_code="IE", base_currency="EUR", fx_rates=FX)
    )
    summary = " ".join(pages[-1].split())
    assert "Cost Summary" in summary
    for expected in ("Finishes", "600.00 EUR", "Other Positions", "900.00 EUR", "2,000.00 EUR", "2,460.00 EUR"):
        assert expected in summary, f"{expected} is missing from the cost summary page"
    assert "1,000.00 EUR" not in summary


# -- The cover -----------------------------------------------------------------------


def _three_taxes() -> Any:
    return _bill(
        [_section([_position("01.001", "10", "50", "500"), _position("01.002", "1", "500", "500")], "1000")],
        markups=[_tax("PIS", 1.65, "16.50"), _tax("COFINS", 7.6, "76.00"), _tax("ISS", 5.0, "50.00")],
    )


def test_the_cover_counts_the_bill_and_has_a_place_to_sign() -> None:
    pages = _pdf_text(generate_boq_pdf(_three_taxes(), "Harbour", currency="EUR", prepared_by="Maria Keller"))
    cover = " ".join(pages[0].split())

    assert "Sections / Positions: 1 / 2" in cover
    assert "Prepared by:" in cover
    assert "Maria Keller" in cover
    assert "Approved by:" in cover
    assert cover.count("Name / Signature / Date") == 2


def _letterhead(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full company profile with a logo, through the branding layer's readers."""
    import base64

    from PIL import Image as PILImage

    from app.core import pdf_branding
    from app.core.company_profile import DEFAULT_COMPANY_PROFILE

    out = io.BytesIO()
    PILImage.new("RGB", (400, 140), (20, 60, 140)).save(out, format="PNG")
    profile = {
        **DEFAULT_COMPANY_PROFILE,
        "legal_name": "Acme & Sons Construction GmbH",
        "address": "Hauptstrasse 1\n10115 Berlin\nGermany",
        "registration_line": "HRB 12345 · VAT DE123456789",
        "phone": "+49 30 1234567",
        "email": "office@acme.example",
        "website": "acme.example",
        "document_logo_data_url": "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii"),
    }
    monkeypatch.setattr(pdf_branding, "_read_company_profile", lambda *_a, **_kw: dict(profile))
    monkeypatch.setattr(pdf_branding, "_read_branding", lambda *_a, **_kw: {})
    monkeypatch.setattr(pdf_branding, "_read_appearance", lambda *_a, **_kw: {})


@pytest.mark.parametrize("letterhead", [False, True], ids=["plain", "letterhead"])
@pytest.mark.parametrize("locale", ["en", "de"])
def test_the_cover_stays_one_page_with_three_tax_lines(
    monkeypatch: pytest.MonkeyPatch, letterhead: bool, locale: str
) -> None:
    if letterhead:
        _letterhead(monkeypatch)
    pages = _pdf_text(
        generate_boq_pdf(_three_taxes(), "Harbour", currency="EUR", prepared_by="Maria Keller", locale=locale)
    )
    if letterhead:
        assert "Acme & Sons" in pages[0]
    labels = _PDF_LABELS[locale]
    assert labels["approved_by"] in pages[0]
    assert pages[0].count(labels["signature_hint"]) == 2, "the sign-off block ran onto a second page"
    assert labels["signature_hint"] not in pages[1]
    # The position table, headed by its "Pos." column, starts on page two.
    assert labels["pos"] in pages[1]
    assert labels["description"] not in pages[0]


def test_the_cover_labels_are_in_the_project_language() -> None:
    cover = " ".join(_pdf_text(generate_boq_pdf(_three_taxes(), "Hafen", currency="EUR", locale="de"))[0].split())

    assert "Freigegeben von:" in cover
    assert "Abschnitte / Positionen: 1 / 2" in cover
    assert "Name / Unterschrift / Datum" in cover


def test_every_translated_table_names_the_sign_off_and_the_counts() -> None:
    # Chinese prints English labels on purpose (see the note on _PDF_LABELS).
    for locale, table in _PDF_LABELS.items():
        if locale in {"en", "zh"}:
            continue
        for key in ("approved_by", "signature_hint", "contents", "table_of_contents", "resources_omitted"):
            assert table.get(key), f"{locale} has no {key}"
            assert table[key] != _PDF_LABELS["en"][key], f"{locale} {key} is still English"


def test_the_declared_language_is_the_one_the_labels_are_printed_in() -> None:
    assert pdf_language("de-DE") == "de"
    assert pdf_language("uk") == "uk"
    assert pdf_language("zh-CN") == "en"
    assert pdf_language("ja") == "en"
    assert pdf_language("") == "en"
