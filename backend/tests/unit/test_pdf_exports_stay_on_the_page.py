# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An export that does not fit the paper must still be entirely on the paper.

Two generators built their tables without ``colWidths``, so reportlab sized the
columns to their content and the table simply grew. It did not refuse and it did
not shrink: ``doc.build`` returned a path and a byte count, and the columns that
did not fit were drawn past the edge of the sheet. Nothing was raised and nothing
was logged.

**These assertions are about coordinates on the page, deliberately.** The obvious
check, that a text extractor can still find every column, passed for the whole
life of this defect while the data sat off the paper, because extraction reads
the file and a reader reads the page. An export that loses its right hand columns
looks finished, which is what makes it worse than the visible kind of overflow:
nobody is prompted to check. A test that concluded "all columns present,
therefore fine" would be repeating the original mistake in assertion form.

The opposite mistake is available too, and one test here exists only to catch it.
Making a table fit by dividing the frame between its columns puts every column on
the page and can still leave a page nobody can read, at which point these
coordinate assertions would pass on a broken export. So the wide case also asserts
a floor under the column width and that a word survives whole.
"""

from __future__ import annotations

import io
import os
import re

import pypdf
import pytest
from reportlab.lib.units import cm, inch

from app.core.paper_size import PAPER_SIZES
from app.modules.bi_dashboards.report_builder import build_pdf_report
from app.modules.file_transmittals.service import _build_cover_pdf
from app.modules.property_dev.service import _render_regulator_pdf

# The margins each generator passes to SimpleDocTemplate. Named here because the
# frame is what a reader sees, and asserting against the sheet alone would accept
# text printed into the margin.
DASHBOARD_MARGIN = 1 * cm
REGULATOR_MARGIN = 2 * cm
TRANSMITTAL_MARGIN = 0.75 * inch

# Below this a column holds about seven characters at the size these tables draw
# at. The number is stated here rather than imported so that the test carries its
# own expectation: importing the implementation's constant would make any future
# change to it silently agree with itself.
LEGIBLE_COLUMN = 48.0

LONG_VALUE = "Rectification of defective works identified during the pre-handover inspection walk"

# The regulator sheet is portrait with wider margins, so its frame is 482pt wide
# against the dashboard's 785pt, but its table is only two columns. A value has to
# be long rather than numerous to push it off: measured through this generator, 83
# characters of prose drew to 335pt and fitted, and this sentence drew to 795pt and
# did not. A disclosure finding written as a sentence is the ordinary case here,
# not a stress input.
LONG_FINDING = (
    "Rectification of defective works identified during the pre-handover inspection walk, "
    "tracked to completion and re-inspected before the completion certificate was issued"
)

_NUM = rb"(-?[\d.]+)"
_TOKEN = re.compile(
    rb"(?:"
    + _NUM
    + rb"\s+"
    + _NUM
    + rb"\s+"
    + _NUM
    + rb"\s+"
    + _NUM
    + rb"\s+"
    + _NUM
    + rb"\s+"
    + _NUM
    + rb"\s+(cm|Tm))"
    rb"|(?:" + _NUM + rb"\s+" + _NUM + rb"\s+([ml])\s)"
    rb"|(?:(?<![A-Za-z])(q|Q)(?![A-Za-z]))"
)


def _page_geometry(pdf_bytes: bytes) -> tuple[list[float], list[float], float]:
    """Ink positions and text origins in page coordinates, plus the sheet width.

    reportlab draws a table inside a saved graphics state that it has translated
    to the frame origin, so the coordinates in the content stream are relative to
    that corner and start at zero. Comparing them directly against the sheet is an
    error of one left margin in the permissive direction, which is how an earlier
    version of this file under-reported by 28pt how far off the paper the defect
    actually put the data. So the ``cm`` translations are followed, along with the
    ``q`` and ``Q`` that bracket them, and what comes back is where the ink is on
    the page.
    """
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    page = reader.pages[0]
    data = page["/Contents"].get_data()
    translation = 0.0
    saved: list[float] = []
    ink: list[float] = []
    origins: list[float] = []
    for match in _TOKEN.finditer(data):
        if match.group(7):
            a, b, c, d, x = (float(match.group(i)) for i in range(1, 6))
            if match.group(7) == b"Tm":
                origins.append(translation + x)
                continue
            assert (a, b, c, d) == (1.0, 0.0, 0.0, 1.0), (
                f"the page applies a transform this test cannot follow ({a} {b} {c} {d}), so the "
                "coordinates it reports would be wrong rather than merely imprecise"
            )
            translation += x
        elif match.group(10):
            ink.append(translation + float(match.group(8)))
        elif match.group(11) == b"q":
            saved.append(translation)
        elif match.group(11) == b"Q":
            translation = saved.pop() if saved else 0.0
    assert origins, "no text runs found on the page, so this test is measuring nothing"
    assert ink, "no table geometry found, so the rightmost ink cannot be located"
    return ink, origins, float(page.mediabox.width)


def _column_edges(pdf_bytes: bytes) -> list[float]:
    """The x positions the table's grid was drawn at, which are its column edges."""
    ink, _origins, _width = _page_geometry(pdf_bytes)
    return sorted({round(x, 2) for x in ink})


def _dashboard_pdf(rows: list[dict[str, object]], name: str = "Width check") -> bytes:
    path, _size = build_pdf_report(report_name=name, rows=rows)
    try:
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        if os.path.exists(path):
            os.remove(path)


def _assert_inside_the_frame(pdf_bytes: bytes, margin: float, label: str) -> float:
    """Nothing is drawn past the frame. Returns the margin of safety in points."""
    ink, origins, sheet_width = _page_geometry(pdf_bytes)
    right_edge = sheet_width - margin
    drawn, origin = max(ink), max(origins)
    assert drawn <= right_edge + 0.5, (
        f"{label}: the table is drawn out to {drawn:.0f}pt, past the right edge of the frame at "
        f"{right_edge:.0f}pt on a {sheet_width:.0f}pt sheet. That is {drawn - sheet_width:.0f}pt beyond "
        f"the paper itself, so those columns are not on the page at all"
    )
    assert origin < right_edge, (
        f"{label}: a text run starts at {origin:.0f}pt, at or past the frame edge {right_edge:.0f}pt"
    )
    return right_edge - drawn


@pytest.mark.parametrize("columns", [7, 8, 12])
def test_a_wide_dashboard_export_draws_nothing_past_the_frame(columns: int) -> None:
    """Seven columns of ordinary text was enough to run off the sheet.

    A dashboard export is arbitrary query output, so the column count is whatever
    somebody selected, and seven is not a lot. The number is seven rather than six
    because it was measured through this generator at the eight point it actually
    draws at; measuring a bare table at reportlab's default ten point puts the
    boundary a column earlier and is measuring a different table.
    """
    rows = [{f"Column {i}": "Rectification of defective works" for i in range(columns)}]
    _assert_inside_the_frame(_dashboard_pdf(rows), DASHBOARD_MARGIN, f"{columns} column export")


@pytest.mark.parametrize("columns", [2, 5])
def test_a_narrow_export_fits_today_and_has_to_keep_fitting(columns: int) -> None:
    """The control, and it is not decoration.

    These already fitted, so they pass before the fix as well as after. They are
    here because the obvious way to stop a table exceeding its frame is to make
    every table exactly the width of the frame, which would silently stretch the
    narrow exports that are the common case. reportlab does precisely that of its
    own accord once cells become flowables, so this is a live failure mode rather
    than a hypothetical one: a fix that wrapped the cells and left the widths to
    reportlab would pass every other test in this file.
    """
    rows = [{f"Column {i}": "Rectification of defective works" for i in range(columns)}]
    slack = _assert_inside_the_frame(_dashboard_pdf(rows), DASHBOARD_MARGIN, f"{columns} column export")
    assert slack > 40, f"a {columns} column export now fills the frame to within {slack:.0f}pt, so it was stretched"


def test_a_wide_export_is_readable_and_not_merely_on_the_page() -> None:
    """The other way to pass the tests above while shipping a useless page.

    Dividing the frame among the columns satisfies every coordinate assertion here
    and can still produce columns four characters wide with the words broken across
    lines. That failure is quieter than the one being fixed, so it gets its own
    assertions: a floor under the narrowest column, and a word that has to survive
    whole in the extracted text.
    """
    rows = [{f"Column {i}": "Rectification of defective works" for i in range(12)}]
    pdf_bytes = _dashboard_pdf(rows)
    edges = _column_edges(pdf_bytes)
    widths = [b - a for a, b in zip(edges, edges[1:], strict=False)]
    narrowest = min(widths)
    assert narrowest >= LEGIBLE_COLUMN, (
        f"twelve columns were fitted by squeezing one to {narrowest:.0f}pt, under the "
        f"{LEGIBLE_COLUMN:.0f}pt that holds about seven characters. The export is on the page "
        "and cannot be read"
    )
    text = pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()
    assert "Rectification" in text, "the column is too narrow to hold one word, so the word was broken across lines"


def test_a_long_value_does_not_push_the_dashboard_table_off_the_sheet() -> None:
    """The other shape of the same defect: few columns, one very long value."""
    rows = [{"Metric": "Finding", "Value": LONG_VALUE * 3}]
    _assert_inside_the_frame(_dashboard_pdf(rows), DASHBOARD_MARGIN, "long value export")


def test_a_short_label_beside_a_long_value_keeps_its_own_width() -> None:
    """Fitting takes the width from the column that has width to give.

    Scaling every column by the same factor would fit the table and narrow the
    label column for no reason, wrapping "Metric" onto two lines to buy points a
    column of prose was going to need anyway. The label column here is far below an
    equal share, so it should come through at its natural width.
    """
    rows = [{"Metric": "Finding", "Value": LONG_VALUE * 3}]
    edges = _column_edges(_dashboard_pdf(rows))
    assert len(edges) >= 3, f"expected two columns and three edges, found {len(edges)}"
    label_width = edges[1] - edges[0]
    assert label_width < 80, f"the label column is {label_width:.0f}pt, wider than the text it holds"
    assert label_width > 30, (
        f"the label column was squeezed to {label_width:.0f}pt to make room for the value beside it, "
        "which is what proportional scaling does and what the fitting is meant to avoid"
    )


def test_the_regulator_disclosure_stays_on_the_page() -> None:
    """The same missing colWidths, on a document that goes to a regulator."""
    pdf_bytes = _render_regulator_pdf(
        regulator="Financial Conduct Authority",
        development_name="Northgate Quarter",
        development_code="NGQ-001",
        quarter="2026-Q2",
        summary={f"Metric {i}": LONG_FINDING for i in range(6)},
    )
    _assert_inside_the_frame(pdf_bytes, REGULATOR_MARGIN, "regulator disclosure")


def test_markup_in_a_dashboard_cell_is_printed_and_not_interpreted() -> None:
    """A guard on the fix rather than on the defect.

    Making cells wrap means making them flowables, and a ``Paragraph`` parses its
    text as markup where a bare string was literal. Dashboard cells carry whatever
    a query returned, so an ampersand or an angle bracket has to survive as itself.
    Here extraction is the right instrument: the question is which characters were
    drawn, not where they landed.
    """
    literal = "R&D <b>not bold</b> 5 < 6"
    reader = pypdf.PdfReader(io.BytesIO(_dashboard_pdf([{"Note": literal}])))
    text = reader.pages[0].extract_text()
    assert "<b>" in text, "the angle brackets were swallowed, so the cell was parsed as markup"
    assert "R&D" in text, "the ampersand did not survive"
    assert "5 < 6" in text, "the bare less-than did not survive"


def test_markup_in_a_regulator_value_is_printed_and_not_interpreted() -> None:
    """The same guard on the other generator, which escaped its prose but not its rows.

    ``_render_regulator_pdf`` already escaped every value it interpolated into
    paragraph markup, and did not escape the table rows, because those were bare
    cells and needed no escaping. Turning them into Paragraphs is what puts them in
    front of a markup parser for the first time.
    """
    pdf_bytes = _render_regulator_pdf(
        regulator="Financial Conduct Authority",
        development_name="Northgate and Co",
        development_code="NGQ-001",
        quarter="2026-Q2",
        summary={"Contractor": "Smith & Sons <Northern>"},
    )
    text = pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()
    assert "Smith & Sons <Northern>" in text, "the table value was parsed as markup instead of printed"


# ── More columns than a sheet can hold ─────────────────────────────────
#
# A dashboard KPI's breakdown is capped at 200 groups and ``run_report``
# gives every group its own column, so a KPI grouped by a free-text field
# reaches this generator with 204 columns. Dividing the frame between them
# leaves 3.8pt each, less than the 12pt of cell padding, and reportlab
# refuses a negative content width: ``ValueError: flowable given negative
# availWidth=-8.2``. That escapes ``run_report``, which lands the run as
# ``status="failed"`` and returns a 500, so the reader gets no document at
# all. Between the two there is a band where the columns are narrow enough
# that the header row grows taller than the frame and reportlab raises
# ``LayoutError`` instead. Measured through this generator: 30 columns
# built, 40 raised LayoutError, 80 raised ValueError.


def _wide_rows(columns: int) -> list[dict[str, object]]:
    """One row of ``columns`` columns, headed and filled like a real export."""
    return [
        {
            f"breakdown__Rectification of defective works to bay {i:03d}": f"Precast beam type {i:03d}"
            for i in range(columns)
        },
    ]


@pytest.mark.parametrize("columns", [40, 80, 204])
def test_a_report_wider_than_the_sheet_still_produces_a_document(columns: int) -> None:
    """The three regimes above, all of which raised out of ``build_pdf_report``.

    Asserting that a document comes back is the whole point: the previous
    behaviour was not an ugly page, it was no page.
    """
    pdf_bytes = _dashboard_pdf(_wide_rows(columns), name=f"{columns} column export")
    assert pdf_bytes.startswith(b"%PDF"), "no PDF was produced"
    _assert_inside_the_frame(pdf_bytes, DASHBOARD_MARGIN, f"{columns} column export")


def test_the_columns_a_wide_report_does_print_are_legible() -> None:
    """Surviving the build is not the bar; 204 slivers would also survive it.

    The failure this replaces was loud, and the quiet way to "fix" it is to
    keep drawing every column at whatever width is left. So the columns
    that are kept have to clear the same floor a twelve column export
    clears.
    """
    pdf_bytes = _dashboard_pdf(_wide_rows(204), name="204 column export")
    edges = _column_edges(pdf_bytes)
    widths = [b - a for a, b in zip(edges, edges[1:], strict=False)]
    narrowest = min(widths)
    assert narrowest >= LEGIBLE_COLUMN, (
        f"204 columns were fitted by squeezing one to {narrowest:.0f}pt, under the "
        f"{LEGIBLE_COLUMN:.0f}pt that holds about seven characters"
    )


def test_a_report_that_drops_columns_says_so_on_the_page() -> None:
    """Dropping data silently is a worse defect than the one being fixed.

    A reader has to be able to tell a complete document from a truncated
    one without counting columns against a query they cannot see, and has
    to be told where the rest of the data is.
    """
    pdf_bytes = _dashboard_pdf(_wide_rows(204), name="204 column export")
    text = " ".join(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text().split())
    match = re.search(r"Showing (\d+) of (\d+) columns", text)
    assert match, f"a truncated export printed no note saying so. Page text: {text[:400]}"
    shown, total = int(match.group(1)), int(match.group(2))
    assert total == 204, f"the note reports {total} columns where the export had 204"
    assert 0 < shown < total
    assert f"other {total - shown}" in text, "the note does not say how many columns are missing"
    assert "CSV" in text and "XLSX" in text, "the note does not say which export carries every column"

    edges = _column_edges(pdf_bytes)
    assert len(edges) - 1 == shown, f"the note claims {shown} columns and the table was drawn with {len(edges) - 1}"


def test_a_report_whose_columns_already_fitted_keeps_every_one_of_them() -> None:
    """The control, and the reason the ceiling is not a fixed column count.

    Twenty short columns fit the frame at their own widths with room to
    spare. A ceiling computed as "frame width over the legible minimum"
    would throw four of them away to fix a defect they do not have, which
    is why the ceiling is the widest prefix that still fits legibly rather
    than a number.
    """
    rows = [{f"c{i}": f"{i}" for i in range(20)}]
    pdf_bytes = _dashboard_pdf(rows, name="20 narrow column export")
    text = " ".join(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text().split())
    assert "Showing" not in text, f"a report that fitted was truncated anyway: {text[:300]}"
    edges = _column_edges(pdf_bytes)
    assert len(edges) - 1 == 20, f"20 columns fitted at their own widths and {len(edges) - 1} were drawn"


# ── A generator that stopped being one page size ──────────────────────────


def _transmittal_cover(pagesize: tuple[float, float]) -> bytes:
    """A sent transmittal's cover sheet, laid out on ``pagesize``."""
    import uuid
    from datetime import UTC, datetime

    from app.modules.file_transmittals.models import (
        FileTransmittal,
        FileTransmittalItem,
        FileTransmittalRecipient,
    )

    transmittal = FileTransmittal(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        number="TR-2026-0041",
        subject="Issue for construction - ground floor",
        reason_code="for_construction",
        sent_at=datetime(2026, 3, 14, 9, 30, tzinfo=UTC),
        status="sent",
        notes=LONG_VALUE,
    )
    transmittal.items = [
        FileTransmittalItem(
            file_kind="drawing",
            file_id="file-1",
            file_version_snapshot="C",
            canonical_name_snapshot=("ARC-BLD-A-DR-2401-Ground floor general arrangement and setting out-Rev-C.pdf"),
            sort_order=0,
        )
    ]
    transmittal.recipients = [
        FileTransmittalRecipient(email="site.manager@example.com", display_name="Site Manager", role="contractor")
    ]
    pdf = _build_cover_pdf(transmittal, pagesize)
    assert pdf is not None, "the cover sheet fell back to text, so there is nothing to measure"
    return pdf


@pytest.mark.parametrize("size", ["A4", "LETTER", "LEGAL", "A3"])
def test_a_transmittal_cover_fits_whichever_sheet_it_was_given(size: str) -> None:
    """This generator was fixed at US Letter and its tables were drawn in inches.

    That was self-consistent while there was only ever one sheet: the widest of
    the three tables is 6.9in against the 7.0in content box Letter leaves at
    0.75in margins. It stops being self-consistent the moment the sheet follows
    the reader, because A4's content box is 6.768in - so those same literals
    draw 9.6pt past the right margin, and reportlab draws a table that does not
    fit rather than refusing it. The widths are scaled to the frame now, and
    this is the assertion that says so on the page rather than in the source.
    """
    _assert_inside_the_frame(_transmittal_cover(PAPER_SIZES[size]), TRANSMITTAL_MARGIN, f"transmittal cover on {size}")


def test_a_transmittal_cover_is_not_stretched_to_whatever_sheet_it_was_given() -> None:
    """The opposite mistake, which the scaling could have introduced.

    Dividing the frame between the columns puts every column on the page and
    would pass the test above on every sheet, while quietly widening a cover
    that already fitted. The design leaves 0.1in of its 7.0in unused, so a
    cover that fills its frame to the edge has been stretched rather than
    scaled, and the slack has to survive in proportion on the wider sheets too.
    """
    for size in ("A4", "LETTER", "A3"):
        pdf_bytes = _transmittal_cover(PAPER_SIZES[size])
        _ink, _origins, sheet_width = _page_geometry(pdf_bytes)
        slack = _assert_inside_the_frame(pdf_bytes, TRANSMITTAL_MARGIN, f"transmittal cover on {size}")
        frame = sheet_width - 2 * TRANSMITTAL_MARGIN
        assert slack > frame * 0.005, (
            f"the cover on {size} fills its frame to within {slack:.1f}pt, so it was stretched"
        )
