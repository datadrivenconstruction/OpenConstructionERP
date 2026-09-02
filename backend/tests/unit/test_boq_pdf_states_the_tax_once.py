"""The exported bill states its tax once, and states every levy it carries.

WHAT WAS WRONG. ``get_boq_structured`` prices a bill as
``net_total = direct_cost + sum(every active markup)`` and sets ``grand_total``
to exactly that. The markup calculator has no notion of a tax category, so a
VAT line is one markup among the others and its money is already inside both
figures. All three PDF writers read ``net_total`` as though it were net OF tax
and added ``net_total * rate / 100`` on top, so a German bill priced at nineteen
per cent printed a Gross Total nineteen per cent above the total the application
itself would quote, with the VAT money stated twice on the same page: once in
its own markup row and once again in the VAT row underneath.

The frontend had already settled this. ``BOQEditorPage`` builds its footer from
markups filtered by ``category !== 'tax'`` and only then adds VAT, and
``MarkupPanel`` carries a comment saying its own sum is the gross figure and not
a net one. The PDF took that formula and fed it the server's differently defined
variable, which is the failure this repository keeps paying for: one word, two
meanings, no gate between them.

A SECOND, NARROWER DEFECT sat in the same loops. Each stopped at the first tax
line it found. Brazil's stack carries two, PIS + COFINS and ISS, so the second
was dropped from the tax section while its money stayed inside the total.

WHY THESE ASSERTIONS. Each one fails in both directions on purpose.

- Overstating (the original defect) fails the "gross equals the priced total"
  assertions.
- Deleting the tax section instead of fixing it fails the assertions that name
  the tax rows and their amounts.
- Declaring the pre-tax subtotal equal to the gross, which would also make the
  column add up, fails ``subtotal < gross`` on any taxed bill.
- Dropping tax out of the total altogether fails ``gross == grand_total``.

The untaxed bill is the control. Its MONEY is unchanged by this work, since the
old arithmetic added nothing when it found no tax line, so a fix that simply
stopped printing tax could not pass by making every bill untaxed. Its labels did
change, deliberately: "Net Total" alone was the word the application uses for a
tax-INCLUSIVE figure and the frontend uses for a tax-exclusive one, which is how
the two came to disagree in the first place, so the document now says which one
it means.

MEASURED RED, on the code before this fix, with the helper import and the two
arithmetic tests stripped so the file could still be collected there: all four
rendering assertions fail. The end-to-end one names the money, printing
155.771,00 EUR where the application quotes 130.900,00 EUR, and the table one
finds the VAT amount on two rows rather than one.
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
    _build_boq_table,
    _build_cover_page,
    _build_styles,
    _tax_split,
    generate_boq_pdf_simple,
)

DIRECT = Decimal("100000.00")
OVERHEAD = Decimal("10000.00")  # 10 per cent of direct cost
# Cumulative on 110000.00, which is how the regional templates stack them.
DE_VAT = Decimal("20900.00")  # 19 per cent
BR_PIS = Decimal("4015.00")  # 3.65 per cent
BR_ISS = Decimal("3424.95")  # 3 per cent of 114015.00


def _markup(name: str, category: str, percentage: float, amount: Decimal) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        markup_type="percentage",
        category=category,
        percentage=percentage,
        fixed_amount=Decimal("0"),
        apply_to="cumulative",
        sort_order=0,
        is_active=True,
        amount=amount,
    )


def _fixed_markup(name: str, category: str, amount: Decimal) -> Any:
    """A markup charged as a sum, which carries no percentage at all."""
    m = _markup(name, category, 0.0, amount)
    m.markup_type = "fixed"
    m.fixed_amount = amount
    return m


def _boq(markups: list[Any]) -> Any:
    """A bill priced the way the service prices it: tax inside ``net_total``."""
    net = DIRECT + sum((Decimal(str(m.amount)) for m in markups), Decimal("0"))
    position = SimpleNamespace(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        ordinal="01.001",
        description="Concrete wall",
        unit="m3",
        quantity=Decimal("100"),
        unit_rate=Decimal("1000"),
        total=DIRECT,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Tax test BOQ",
        description="",
        status="draft",
        currency="EUR",
        sections=[
            SimpleNamespace(
                id=uuid.uuid4(),
                ordinal="01",
                description="Structure",
                positions=[position],
                subtotal=DIRECT,
            )
        ],
        positions=[],
        direct_cost=DIRECT,
        markups=markups,
        net_total=net,
        # The service sets this to net_total unchanged. It is the figure the
        # application quotes, and the document may not disagree with it.
        grand_total=net,
    )


UNTAXED = [_markup("Overhead", "overhead", 10.0, OVERHEAD)]
GERMAN = [*UNTAXED, _markup("VAT", "tax", 19.0, DE_VAT)]
BRAZIL = [
    *UNTAXED,
    _markup("PIS + COFINS", "tax", 3.65, BR_PIS),
    _markup("ISS", "tax", 3.0, BR_ISS),
]
# A tax charged as a sum rather than a rate. The old code read the rate off the
# line and a fixed line carries none, so it found nought per cent, printed no
# tax row and left the money inside the total with nothing naming it.
STAMP_DUTY = Decimal("750.00")
FIXED_TAX = [*UNTAXED, _fixed_markup("Stamp duty", "tax", STAMP_DUTY)]


def _cell_text(cell: Any) -> str:
    return getattr(cell, "text", cell if isinstance(cell, str) else "")


def _rows(flowables: list[Any]) -> list[tuple[str, ...]]:
    """Every rendered table row across the flowables, as plain text tuples."""
    out: list[tuple[str, ...]] = []
    for flowable in flowables:
        for row in getattr(flowable, "_cellvalues", []) or []:
            out.append(tuple(_cell_text(c) for c in row))
        # The cover page wraps its tables one level deep.
        for row in getattr(flowable, "_cellvalues", []) or []:
            for cell in row:
                for inner in getattr(cell, "_cellvalues", []) or []:
                    out.append(tuple(_cell_text(c) for c in inner))
    return out


def _labelled(rows: list[tuple[str, ...]], needle: str) -> list[tuple[str, ...]]:
    return [r for r in rows if any(needle in _cell_text(c) for c in r)]


def _money(rows: list[tuple[str, ...]], needle: str) -> Decimal:
    """The amount printed on the one row whose label contains *needle*.

    The document is priced in EUR, which the writer formats German style
    (``110.000,00 EUR``), so the dot is the thousands separator and the comma is
    the decimal point. Reading it with an Anglo parser turns a hundred and ten
    thousand into a hundred and ten, which is a silently wrong assertion rather
    than a failing one.
    """
    matches = _labelled(rows, needle)
    assert len(matches) == 1, f"expected one row containing {needle!r}, got {len(matches)}: {matches}"
    cells = [c for c in matches[0] if c and c != ""]
    raw = cells[-1].replace("<b>", "").replace("</b>", "").replace("EUR", "").strip()
    return Decimal(raw.replace(".", "").replace(",", "."))


# ── The arithmetic itself ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("markups", "expected_tax", "expected_lines"),
    [
        (UNTAXED, Decimal("0"), 0),
        (GERMAN, DE_VAT, 1),
        (BRAZIL, BR_PIS + BR_ISS, 2),
        (FIXED_TAX, STAMP_DUTY, 1),
    ],
)
def test_tax_split_takes_the_tax_out_of_the_total_it_is_already_in(
    markups: list[Any], expected_tax: Decimal, expected_lines: int
) -> None:
    boq = _boq(markups)
    tax_lines, tax_amount, subtotal, gross = _tax_split(boq)

    assert len(tax_lines) == expected_lines
    assert tax_amount == expected_tax
    # Subtracted, never added: the gross is the priced total, unchanged.
    assert gross == Decimal(str(boq.grand_total))
    assert subtotal + tax_amount == gross
    if expected_lines:
        # Guards the "declare the subtotal equal to the gross" non-fix, which
        # would also make the column add up.
        assert subtotal < gross


def test_a_german_bill_is_not_charged_its_vat_twice() -> None:
    """The original defect, stated as money rather than as structure."""
    boq = _boq(GERMAN)
    _, _, _, gross = _tax_split(boq)

    # What the old arithmetic printed: the priced total with the VAT added a
    # second time on top of the VAT already inside it.
    overstated = Decimal(str(boq.net_total)) * Decimal("1.19")
    assert overstated - gross == Decimal("24871.00")
    assert gross == DIRECT + OVERHEAD + DE_VAT


# ── The three writers ────────────────────────────────────────────────────────


def test_cover_page_summary_states_each_tax_line_once() -> None:
    rows = _rows(_build_cover_page(_boq(BRAZIL), "Project", "EUR", "Estimator", _build_styles()))

    assert _money(rows, "Direct Cost:") == DIRECT
    assert _money(rows, "Markups (excl. tax):") == OVERHEAD
    assert _money(rows, "Net Total (excl. tax):") == DIRECT + OVERHEAD
    # Both levies, each with its own rate. The second used to be dropped.
    assert _money(rows, "PIS + COFINS") == BR_PIS
    assert _money(rows, "ISS") == BR_ISS
    assert _money(rows, "Gross Total:") == DIRECT + OVERHEAD + BR_PIS + BR_ISS


def test_boq_table_prints_the_tax_below_the_subtotal_and_not_among_the_markups() -> None:
    boq = _boq(GERMAN)
    rows = _rows(_build_boq_table(boq, "EUR", _build_styles(), "metric"))

    # Exactly one row carries the VAT money, and it is the tax row.
    assert _money(rows, "VAT") == DE_VAT
    assert _money(rows, "Net Total (excl. tax)") == DIRECT + OVERHEAD
    assert _money(rows, "Gross Total") == Decimal(str(boq.grand_total))


def test_the_simple_pdf_agrees_with_the_price_the_application_quotes() -> None:
    """End to end, through the writer that renders large bills."""
    boq = _boq(GERMAN)
    data = generate_boq_pdf_simple(boq, project_name="Project", currency="EUR", prepared_by="Estimator")
    text = "".join("".join(page.extract_text().split()) for page in pypdf.PdfReader(io.BytesIO(data)).pages)

    # German formatting: 130.900,00
    assert "130.900,00" in text  # the priced total, printed as the Gross Total
    assert "155.771,00" not in text  # what the double count used to print
    assert "20.900,00" in text  # the VAT, stated once


def test_an_untaxed_bill_reads_exactly_as_before() -> None:
    """The control. A fix that stops printing tax cannot pass here."""
    boq = _boq(UNTAXED)
    rows = _rows(_build_cover_page(boq, "Project", "EUR", "Estimator", _build_styles()))

    assert _money(rows, "Net Total (excl. tax):") == Decimal(str(boq.net_total))
    assert _money(rows, "Gross Total:") == Decimal(str(boq.grand_total))
    # The zero row keeps the summary's shape, so an untaxed bill is visibly
    # untaxed rather than silently missing a line.
    assert _money(rows, "VAT 0%") == Decimal("0")


def test_a_tax_charged_as_a_sum_is_named_and_not_swallowed() -> None:
    """A fixed-amount tax line keeps its money and gets a row of its own.

    The rate-reading code could not see one at all: it took ``percentage`` off
    the line, found nought, and printed a nought per cent VAT row while the duty
    sat unnamed inside the total. Nothing on the page said the money was tax.
    """
    boq = _boq(FIXED_TAX)
    rows = _rows(_build_cover_page(boq, "Project", "EUR", "Estimator", _build_styles()))

    # Named by the line's own name, with no invented rate after it.
    assert _money(rows, "Stamp duty") == STAMP_DUTY
    assert not _labelled(rows, "Stamp duty (")
    assert _money(rows, "Net Total (excl. tax):") == DIRECT + OVERHEAD
    assert _money(rows, "Gross Total:") == Decimal(str(boq.grand_total))
