# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Keep user text in a workbook text, not a formula.

openpyxl types a cell from the value it is given, so a note a user typed as
``=SUM(A1:A5)``, or a smiley written ``=) done``, is stored as a formula. Two
things follow, and both are wrong for an export of what people wrote:

* the workbook no longer says what the user said. Excel evaluates the cell on
  open, so a note reads as a number, or as ``#NAME?``;
* anything that rewrites references, the company letterhead among them, has to
  parse it. A note that is not a formula, ``=) done``, cannot be parsed.

The cells are typed text instead. Unlike
:func:`app.core.csv_safety.neutralise_formula`, which guards a CSV a
spreadsheet will parse on open, nothing is added to the text: a cell stored as
text is not evaluated whatever it starts with, so it comes back out exactly as
it was typed, ``+49 30 1234567`` included.

Exporters call this on a finished sheet, before the letterhead. None of our
exporters writes a formula of its own; one that starts to must call this
before it writes them, not after.
"""

from __future__ import annotations

from typing import Any

__all__ = ["store_strings_as_text"]


def store_strings_as_text(ws: Any) -> int:
    """Type every string cell on ``ws`` as text.

    Args:
        ws: The worksheet, after the exporter has written its rows. A
            write-only sheet holds no cells to retype and is left alone.

    Returns:
        How many cells were retyped, for tests and logging.
    """
    cells = getattr(ws, "_cells", None)
    if not isinstance(cells, dict):
        return 0
    retyped = 0
    for cell in cells.values():
        if getattr(cell, "data_type", None) == "f" and isinstance(cell.value, str):
            cell.data_type = "s"
            retyped += 1
    return retyped
