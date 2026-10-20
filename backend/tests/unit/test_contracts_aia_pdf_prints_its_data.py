"""First tests for the AIA payment application renderer.

This module renders a contract document that goes to an owner and an architect,
and until now it had no test of any kind anywhere in the tree. The defect these
cover is what that allowed to ship: a plain string table cell is drawn directly
rather than parsed as markup, so escaping its value puts the entity on the page.
A party named ``R&D Tower`` printed as ``R&amp;D Tower``, and because the
escaping ran with quote=True, ``O'Brien Construction`` printed as
``O&#x27;Brien Construction``. The apostrophe is the wide case: it needs no
unusual punctuation at all, only a name of a kind this document's market is
full of.

The last test here guards the other direction, because the two cell kinds in
this document want opposite treatment and the obvious repair to one of them
breaks the other.
"""

from __future__ import annotations

import io
from typing import Any

import pypdf
import pytest
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import mm

import app.modules.contracts.aia_pdf as aia_pdf
from app.core import pdf_reader
from app.core.paper_size import PAPER_SIZES

# The probe and the suite must agree about which copy of the package they are
# reading. Running a file by path puts the script's own directory on sys.path
# rather than the working directory, which is how an earlier measurement of this
# module was taken against the installed copy under .venv-run instead of the
# tree. pytest resolves the tree, but saying so out loud costs nothing.
assert "site-packages" not in aia_pdf.__file__, aia_pdf.__file__

AMPERSAND_PARTY = "R&D Tower <Ltda>"


def application(**overrides: Any) -> dict[str, Any]:
    """A payment application with every field the renderer reads."""
    app: dict[str, Any] = {
        "application_number": "APP-014",
        "claim_date": "2026-04-15",
        "period_end": "2026-04-30",
        "currency": "USD",
        "certification": {
            "architect_certified_by": "Ortega Architects",
            "architect_certified_at": "2026-05-01",
            "owner_certified_by": "Harbour Estates",
            "owner_certified_at": "2026-05-02",
            "certified_amount": "1000.00",
        },
        "summary": {
            "contract_sum_to_date": "1000.00",
            "total_completed_stored": "1000.00",
            "balance_to_finish": "0.00",
            "retainage": "0.00",
        },
        "lines": [
            {
                "item_number": "01",
                "description": "Substructure",
                "scheduled_value": "1000.00",
                "previous_value": "0.00",
                "this_period_value": "1000.00",
                "materials_stored": "0.00",
                "total_completed_stored": "1000.00",
                "percent_complete": "100",
                "balance_to_finish": "0.00",
                "retainage": "0.00",
            }
        ],
    }
    app.update(overrides)
    return app


def drawn_runs(data: bytes) -> list[str]:
    """Every non-empty text run the page actually draws."""
    runs: list[str] = []
    for page in pypdf.PdfReader(io.BytesIO(data)).pages:
        page.extract_text(visitor_text=lambda text, cm, tm, font, size: runs.append(text))
    return [run.strip() for run in runs if run.strip()]


@pytest.mark.parametrize(
    "value",
    [
        "R&D Tower <Ltda>",
        # The apostrophe is the case that decides how wide this defect was. The
        # old escaping ran with quote=True, so it also rewrote apostrophes and
        # double quotes, and a name shaped like this one is ordinary in the
        # market that uses AIA documents.
        "O'Brien Construction",
        'Smith "Bud" Contracting',
    ],
)
def test_a_string_cell_is_printed_rather_than_escaped(value: str) -> None:
    """The application number is a plain string cell, so it is never parsed."""
    runs = drawn_runs(aia_pdf.render_aia_application_pdf(application(application_number=value)))
    assert value in runs, f"the application number was not drawn as written: {runs[:12]}"
    assert not any(ENTITY in run for run in runs for ENTITY in ("&amp;", "&lt;", "&#x27;", "&quot;")), (
        f"an HTML entity reached the page: {runs[:12]}"
    )


def test_a_certifier_name_is_printed_rather_than_escaped() -> None:
    """The second population, and the reason the count on the page was two.

    Certifier names are string cells in a different table, so a fix applied to
    one table would leave this one printing entities.
    """
    cert = application()["certification"] | {"owner_certified_by": AMPERSAND_PARTY}
    runs = drawn_runs(aia_pdf.render_aia_application_pdf(application(certification=cert)))
    assert AMPERSAND_PARTY in runs, f"the certifier name was not drawn as written: {runs[:12]}"


def test_a_paragraph_cell_still_escapes_what_it_is_given() -> None:
    """The property this document already had, which the fix must not spend.

    Line descriptions are Paragraph cells, and a Paragraph is parsed. Removing
    the escaping there as well, which is the obvious way to make the tests above
    pass everywhere, would let a description carrying markup style the document
    or silently lose its own text. The bold tag has to survive as four printed
    characters.
    """
    described = application(lines=[application()["lines"][0] | {"description": "Steel <b>frame</b> & cladding"}])
    runs = drawn_runs(aia_pdf.render_aia_application_pdf(described))
    assert "Steel <b>frame</b> & cladding" in runs, f"the description was parsed instead of printed: {runs[:12]}"


# ── The continuation sheet on the paper ────────────────────────────────────
#
# The continuation sheet's columns were fixed at 278mm on a landscape Letter
# sheet with 247mm inside its margins, so it was drawn to within a millimetre
# of both paper edges and a printer clipped the item numbers and the retainage.
# The margin and the frame padding are stated here rather than imported, so the
# test carries its own idea of where the printable area is.

SIDE_MARGIN = 14 * mm
FRAME_PADDING = 6.0

LARGE_LINE = "9999999.99"
LARGE_TOTAL = "99999999.99"


def _large_application(lines: int = 20) -> dict[str, Any]:
    """The largest figures the columns are sized for, in every money cell."""
    money_fields = (
        "scheduled_value",
        "previous_value",
        "this_period_value",
        "materials_stored",
        "total_completed_stored",
        "balance_to_finish",
        "retainage",
    )
    line = application()["lines"][0] | dict.fromkeys(money_fields, LARGE_LINE)
    summary = {
        "contract_sum_to_date": LARGE_TOTAL,
        "total_completed_stored": LARGE_TOTAL,
        "balance_to_finish": LARGE_TOTAL,
        "retainage": LARGE_LINE,
    }
    return application(lines=[line | {"item_number": f"{index:02d}"} for index in range(1, lines + 1)], summary=summary)


@pytest.mark.parametrize("sheet", ["LETTER", "A4"])
def test_the_continuation_sheet_columns_fit_the_frame(sheet: str) -> None:
    """The widths sum to no more than the frame on either landscape sheet, and
    the description still gets a readable share of it."""
    page_width = landscape(PAPER_SIZES[sheet])[0]
    frame = page_width - 2 * SIDE_MARGIN - 2 * FRAME_PADDING
    widths = aia_pdf._g703_column_widths(frame, "USD")
    assert len(widths) == 10
    assert sum(widths) <= frame + 0.01, f"{sheet}: the columns take {sum(widths) / mm:.1f}mm of {frame / mm:.1f}mm"
    assert widths[1] >= 50 * mm, f"{sheet}: the description column is down to {widths[1] / mm:.1f}mm"


def test_nothing_on_the_payment_application_is_drawn_past_the_margins() -> None:
    """The rendered pages, not the arithmetic: every rule and fill the tables
    draw lies inside the margins, on the face and on every continuation page."""
    with pdf_reader.open_pdf(aia_pdf.render_aia_application_pdf(_large_application())) as document:
        assert document.page_count > 1, "expected a continuation page to measure"
        for number, page in enumerate(document, start=1):
            rects = [drawing["rect"] for drawing in page.drawings()]
            assert rects, f"page {number} draws no table"
            left = min(rect.x0 for rect in rects)
            right = max(rect.x1 for rect in rects)
            assert left >= SIDE_MARGIN, f"page {number}: drawn from {left:.1f}pt, the margin is at {SIDE_MARGIN:.1f}pt"
            assert right <= page.rect.width - SIDE_MARGIN, (
                f"page {number}: drawn to {right:.1f}pt, the margin is at {page.rect.width - SIDE_MARGIN:.1f}pt"
            )


def test_the_largest_realistic_amounts_are_printed_on_one_line() -> None:
    """A figure too wide for its column is broken in two rather than refused,
    so a column narrowed to fit the frame prints an amount across two lines.

    Counted, not merely found: one broken column among seven still leaves the
    whole figure in the other six. Scaling the old widths down evenly broke
    exactly one, the materials stored column, and a presence check passed it.
    Ten schedule lines put the line figure in seventy money cells and add up to
    a contract level figure in each of the four totals the sheet foots, so both
    widths are measured on the columns that print them. The totals row used to
    take three of its figures off the face instead of adding its own columns
    up, which is why one line used to be enough to reach both widths here.
    The face prefixes its amounts with the currency, so none of them counts.
    """
    runs = drawn_runs(aia_pdf.render_aia_application_pdf(_large_application(lines=10)))
    figures = [run for run in runs if run[:1].isdigit() and "," in run]
    assert runs.count("9,999,999.99") == 70, f"a line figure was broken across lines: {figures}"
    assert runs.count("99,999,999.90") == 4, f"a total was broken across lines: {figures}"
