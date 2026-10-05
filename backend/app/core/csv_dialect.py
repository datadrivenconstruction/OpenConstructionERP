# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pick the delimiter a CSV upload was written with.

The rule first lived in the BOQ importer (``boq/importers/excel.py``) and is
copied here so other tabular importers, the schedule spreadsheet import first,
read a CSV the same way without importing the BOQ package. The BOQ importer
still carries its own private copy; the two should be folded together when that
file is next touched.

Pure and stdlib-only.
"""

from __future__ import annotations

import csv
import re

#: Delimiters tried, in tie-break order. Semicolon first: it is what Excel
#: writes in every locale that uses the decimal comma.
CSV_DELIMITERS: tuple[str, ...] = (";", "\t", ",", "|")

# The first line Excel writes, and reads, to name a CSV's separator outright:
# "sep=;". It is the file saying what it is, so it beats any count.
_SEP_DIRECTIVE = re.compile(r"\A\ufeff?[ \t]*sep=(.)[ \t]*(\r\n|\r|\n|\Z)", re.IGNORECASE)


def sep_directive(text: str) -> tuple[str | None, str]:
    """The separator a leading ``sep=`` line names, and the text with that line blanked.

    The line is blanked rather than cut so every row keeps the line number the
    user sees in the file.
    """
    match = _SEP_DIRECTIVE.match(text)
    if match is None:
        return None, text
    return match.group(1), match.group(2) + text[match.end() :]


def sniff_delimiter(text: str) -> str:
    """The delimiter that splits the most lines into the same number of fields.

    ``csv.Sniffer`` reads the whole sample, title lines included, and a
    semicolon file whose numbers carry decimal commas gives it two plausible
    answers. Counting fields line by line with the csv reader itself (so a
    quoted "125,5" stays one field) and taking the delimiter whose most common
    field count is shared by the most lines picks the one the table is laid
    out in, whatever sits above it. A tie goes to the earlier delimiter in
    :data:`CSV_DELIMITERS`. A leading ``sep=`` line, see :func:`sep_directive`,
    is taken at its word.
    """
    named, text = sep_directive(text)
    if named is not None:
        return named
    lines = [line for line in text[:16384].splitlines()[:60] if line.strip()]
    best, best_score = ",", 0
    for delimiter in CSV_DELIMITERS:
        counts: dict[int, int] = {}
        for fields in csv.reader(lines, delimiter=delimiter):
            if len(fields) > 1:
                counts[len(fields)] = counts.get(len(fields), 0) + 1
        score = max(counts.values(), default=0)
        if score > best_score:
            best, best_score = delimiter, score
    return best


__all__ = ["CSV_DELIMITERS", "sep_directive", "sniff_delimiter"]
