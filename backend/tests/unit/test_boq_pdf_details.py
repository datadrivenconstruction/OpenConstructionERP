"""The estimate PDF prints the client, the site and the payment terms the project holds.

Worked example: a project with client "Acme Build Ltd", project number "P-7",
site "Plot 4, Dock Road" and the terms "30 days net" prints all four on the
cover (client, number, site) and the terms under the totals. A project that
set nothing prints exactly the document it printed before. Hiding "qty_unit"
and "rate" leaves Pos | Description | Total, and the totals captions stay
readable.
"""

from __future__ import annotations

from reportlab.platypus import Paragraph

from app.modules.boq.pdf_details import METADATA_KEY, PdfDetails, drop_columns, merged_metadata, read_details
from app.modules.boq.pdf_export import _PageMark
from tests.unit.test_boq_pdf_writes_the_projects_country import _boq, _pdf_text, generate_boq_pdf


def _details() -> PdfDetails:
    return PdfDetails(
        client_name="Acme Build Ltd",
        client_address="1 High St\nSpringfield",
        project_number="P-7",
        site_address="Plot 4, Dock Road",
        payment_terms="30 days net\n10% on signing",
    )


def test_details_are_printed_on_the_cover_and_terms_close_the_document() -> None:
    text = _pdf_text(generate_boq_pdf(_boq(), "Dock", "EUR", details=_details()))
    for expected in ("Acme Build Ltd", "1 High St, Springfield", "P-7", "Plot 4, Dock Road"):
        assert expected in text
    assert "Payment terms" in text
    assert text.rindex("30 days net") > text.rindex("Gross Total")


def test_a_project_without_details_prints_the_same_document_as_before() -> None:
    plain = _pdf_text(generate_boq_pdf(_boq(), "Dock", "EUR"))
    empty = _pdf_text(generate_boq_pdf(_boq(), "Dock", "EUR", details=PdfDetails()))
    assert plain == empty
    assert "Payment terms" not in plain


def test_hidden_columns_leave_the_headers_out() -> None:
    both = PdfDetails(hidden_columns=["qty_unit", "rate"])
    text = _pdf_text(generate_boq_pdf(_boq(), "Dock", "EUR", details=both))
    shown = _pdf_text(generate_boq_pdf(_boq(), "Dock", "EUR"))
    assert "Rate (EUR)" in shown
    assert "Rate (EUR)" not in text
    assert "Total (EUR)" in text


def test_sanitising_cleans_text_and_drops_unknown_columns() -> None:
    d = PdfDetails.model_validate(
        {
            "client_name": "  Acme\x00  Ltd \n",
            "client_address": "a\r\nb\x07",
            "payment_terms": "x" * 3000,
            "hidden_columns": ["rate", "rate", "total", 5],
        }
    )
    assert d.client_name == "Acme Ltd"
    assert d.client_address == "a\nb"
    assert len(d.payment_terms) == 2000
    assert d.hidden_columns == ["rate"]


def test_malformed_stored_value_reads_as_defaults_and_other_keys_survive() -> None:
    assert read_details({METADATA_KEY: "oops"}) == PdfDetails()
    assert read_details(None) == PdfDetails()
    merged = merged_metadata({"keep": 1}, _details())
    assert merged["keep"] == 1
    assert read_details(merged).client_name == "Acme Build Ltd"


def test_drop_columns_moves_total_captions_and_page_marks() -> None:
    marks: dict[str, int] = {}
    mark = _PageMark("s0", marks)
    caption = Paragraph("Net total")
    rows = [
        ["Pos", "Desc", "Unit", "Qty", "Rate", "Total"],
        [Paragraph("01"), Paragraph("Structure"), mark, "", "", ""],
        ["", "", caption, "", "", Paragraph("10")],
    ]
    widths = drop_columns(rows, [10.0, 50.0, 5.0, 5.0, 10.0, 20.0], ["qty_unit", "rate"])
    assert widths == [10.0, 70.0, 20.0]
    assert rows[0] == ["Pos", "Desc", "Total"]
    assert mark in rows[1]
    assert rows[2][1] is caption
