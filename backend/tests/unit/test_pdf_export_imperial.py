"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Imperial-unit reconciliation in the priced BOQ PDF (GitHub #285).

When ``measurement_system="imperial"`` the printed quantity column is
converted (m -> ft, m2 -> sq ft ...). Before this fix the per-unit RATE
column was still printed raw (money per ONE metric unit), so a converted
line no longer reconciled: a 2.31 m line shown as 7.58 ft beside a raw
"50" rate reads as 7.58 * 50 = 379 while the (invariant) line total stays
115.50.

The fix restates the rate reciprocally against the displayed unit
(50 / m -> 15.24 / ft) via :func:`app.core.unit_conversion.display_rate`,
so ``qty_shown * rate_shown`` reconciles back to the line total. Money
totals / subtotals are never converted or recomputed.

These tests build the BOQ table flowables directly and read the rendered
``Paragraph`` cells, mirroring the fixture style of
``test_pdf_export_safety.py`` (a duck-typed ``SimpleNamespace`` BOQ - the
generator only does attribute access, never Pydantic validation).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.unit_conversion import convert, display_rate
from app.modules.boq.pdf_export import _build_boq_table, _build_styles, generate_boq_pdf

# A metric line that does NOT divide evenly, so a raw-rate bug would be
# numerically obvious: 2.31 m at 50 / m == 115.50 (the invariant total).
_METRIC_QTY = Decimal("2.31")
_UNIT = "m"
_RATE = Decimal("50")
_TOTAL = Decimal("115.50")


def _make_boq(
    *,
    quantity: Decimal = _METRIC_QTY,
    unit: str = _UNIT,
    unit_rate: Decimal = _RATE,
    total: Decimal = _TOTAL,
    ungrouped: bool = False,
) -> Any:
    """Build a minimal duck-typed ``boq_data`` with a single priced line.

    ``ungrouped=True`` puts the line under "Other Positions" (the second row
    writer) instead of inside a section, so both code paths can be exercised.
    """
    pos = SimpleNamespace(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        ordinal="01.001",
        description="Concrete wall",
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total=total,
    )
    sections = []
    positions = []
    if ungrouped:
        positions = [pos]
    else:
        sections = [
            SimpleNamespace(
                id=uuid.uuid4(),
                ordinal="01",
                description="Section one",
                positions=[pos],
                subtotal=total,
            )
        ]
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Imperial test BOQ",
        status="draft",
        currency="USD",
        sections=sections,
        positions=positions,
        direct_cost=total,
        markups=[],
        net_total=total,
        grand_total=total,
    )


def _cell_text(cell: Any) -> str:
    """Render a table cell to plain text (``Paragraph`` -> ``.text``)."""
    return getattr(cell, "text", cell if isinstance(cell, str) else "")


def _item_row(boq: Any, *, measurement_system: str) -> list[Any]:
    """Return the rendered item row (Pos | Desc | Unit | Qty | Rate | Total).

    Walks the flowables produced by :func:`_build_boq_table` for the single
    ``Table`` it emits and finds the one data row whose ordinal is the line's
    ``01.001`` (header / section / subtotal / total rows are skipped).
    """
    styles = _build_styles()
    flowables = _build_boq_table(boq, "USD", styles, measurement_system)
    table = next(f for f in flowables if hasattr(f, "_cellvalues"))
    for row in table._cellvalues:
        if _cell_text(row[0]) == "01.001":
            return row
    raise AssertionError("item row not found in rendered BOQ table")


def _parse_amount(text: str) -> Decimal:
    """Parse a locale-formatted USD number ("1,234.56") back to Decimal."""
    return Decimal(text.replace(",", ""))


def test_metric_rate_is_unchanged_and_reconciles():
    """In metric the rate prints raw and qty * rate == line total."""
    boq = _make_boq()
    row = _item_row(boq, measurement_system="metric")

    qty = _parse_amount(_cell_text(row[3]))
    rate = _parse_amount(_cell_text(row[4]))

    assert rate == _RATE
    assert qty == _METRIC_QTY
    # The metric line reconciles to the invariant total.
    assert qty * rate == _TOTAL


def test_imperial_rate_is_restated_reciprocally():
    """In imperial the printed rate equals display_rate(rate, unit, imperial)."""
    boq = _make_boq()
    row = _item_row(boq, measurement_system="imperial")

    rate = _parse_amount(_cell_text(row[4]))
    expected = display_rate(_RATE, _UNIT, "imperial")

    # Rendered cell is 2-dp formatted; compare at 2-dp.
    assert rate == expected.quantize(Decimal("0.01"))
    # And it is genuinely different from the raw metric rate (50 / m).
    assert rate != _RATE


def test_imperial_unit_label_is_converted():
    """The unit column relabels to the imperial unit (m -> ft)."""
    boq = _make_boq()
    row = _item_row(boq, measurement_system="imperial")

    expected_unit = convert(_METRIC_QTY, _UNIT, "imperial").display_unit
    assert _cell_text(row[2]) == expected_unit
    assert _cell_text(row[2]) == "ft"


def test_imperial_line_reconciles_qty_times_rate_to_total():
    """The whole point of #285: qty_shown * rate_shown == invariant line total.

    Reconciliation holds within rounding of the 2-dp printed figures (the
    canonical, un-rounded math is exact because display_rate divides by the
    same factor convert multiplies by).
    """
    boq = _make_boq()
    row = _item_row(boq, measurement_system="imperial")

    qty = _parse_amount(_cell_text(row[3]))
    rate = _parse_amount(_cell_text(row[4]))
    total = _parse_amount(_cell_text(row[5]))

    # Total is the invariant money figure - never converted.
    assert total == _TOTAL
    # Printed qty * printed rate lands on the total within 2-dp rounding.
    assert abs(qty * rate - total) <= Decimal("0.05")


def test_imperial_total_is_invariant_money():
    """The Total cell is byte-identical between metric and imperial renders."""
    boq_metric = _make_boq()
    boq_imperial = _make_boq()

    metric_total = _cell_text(_item_row(boq_metric, measurement_system="metric")[5])
    imperial_total = _cell_text(_item_row(boq_imperial, measurement_system="imperial")[5])

    assert metric_total == imperial_total


def test_ungrouped_other_positions_rate_also_restated():
    """The second row writer ("Other Positions") restates the rate too."""
    boq = _make_boq(ungrouped=True)
    row = _item_row(boq, measurement_system="imperial")

    rate = _parse_amount(_cell_text(row[4]))
    expected = display_rate(_RATE, _UNIT, "imperial").quantize(Decimal("0.01"))
    assert rate == expected
    assert rate != _RATE


def test_unmapped_unit_rate_passes_through_in_imperial():
    """A countable / lump unit (no imperial mapping) keeps its raw rate.

    "pcs" has no imperial factor, so both the quantity and the rate pass
    through unchanged and the line reconciles exactly as in metric.
    """
    boq = _make_boq(unit="pcs", quantity=Decimal("4"), unit_rate=Decimal("25"), total=Decimal("100"))
    row = _item_row(boq, measurement_system="imperial")

    qty = _parse_amount(_cell_text(row[3]))
    rate = _parse_amount(_cell_text(row[4]))

    assert qty == Decimal("4")
    assert rate == Decimal("25")
    assert qty * rate == Decimal("100")


def test_full_pdf_renders_in_imperial_without_crashing():
    """End-to-end: the full generator path is exercised in imperial mode."""
    boq = _make_boq()
    pdf = generate_boq_pdf(
        boq,
        project_name="Imperial Project",
        currency="USD",
        measurement_system="imperial",
    )
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2_000
