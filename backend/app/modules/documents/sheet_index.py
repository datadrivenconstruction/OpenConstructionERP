# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drawing-index / issue-register parsing and sheet reconciliation.

Turns a drawing index (a sheet-list table in a PDF, or a pasted list) into the
EXPECTED set of sheets and diffs it against the ACTUAL ``Sheet`` rows already
extracted for a project, producing a deterministic, explainable set-diff:
which sheets are missing, which are extra, and which are at a different
revision than the index expects.

The core (``normalize_sheet_number`` / ``parse_pasted_index`` / ``reconcile``)
is pure and depends only on the stdlib, so it is cheap to unit-test without a
database or a PDF. Only ``parse_index_tables`` reaches for ``pdfplumber`` (the
same library the sheet splitter already uses), imported lazily so the pure path
carries no heavy dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.modules.documents.sheet_fields import extract_inline_revision, sheet_chain_key

# A cell "looks like" a sheet number when it is short, carries at least one
# digit, and reads as an optional discipline prefix followed by digits and a
# little trailing detail (e.g. 'A-101', 'S100', 'E-2.01', 'M001/A'). Used to
# find the number column in a table whose header is unclear.
_SHEET_NUMBER_CELL = re.compile(r"^[A-Za-z]{0,4}[\s._\-]?\d[\w.\-/]*$")


# Header cell vocabulary for column identification.
_NUMBER_HEADERS = ("SHEET", "DWG", "DRAWING", "NO", "NUMBER", "REF")
_TITLE_HEADERS = ("TITLE", "NAME", "DESCRIPTION", "DESIGNATION")
_REVISION_HEADERS = ("REV", "REVISION", "ISSUE")


@dataclass(frozen=True)
class ExpectedSheet:
    """One expected sheet lifted from a drawing index / issue register."""

    sheet_number: str
    sheet_number_norm: str
    sheet_title: str | None = None
    revision: str | None = None


@dataclass
class ReconcileResult:
    """Outcome of diffing the expected index against the actual sheet set."""

    missing: list[str] = field(default_factory=list)  # in index, not in the set
    extra: list[str] = field(default_factory=list)  # in the set, not in the index
    matched: list[str] = field(default_factory=list)  # present on both sides
    rev_mismatch: list[dict[str, str]] = field(default_factory=list)  # matched, differing rev
    expected_count: int = 0
    actual_count: int = 0


def normalize_sheet_number(raw: str | None) -> str:
    """Normalize a sheet number to a comparison key.

    The revision stack's own key, :func:`sheet_chain_key`: case, separators
    and leading zeros are drafting style, so 'A-101', 'A 101', 'a.101' and
    'A-0101' all key to 'A101', and 'A-01' to 'A1' like 'A-1'. It used to keep
    leading zeros, so the register stacked A-01 and A-1 as one drawing while
    this check reported one of them missing. The same function must be applied
    to expected and actual numbers, or every sheet mis-matches.
    """
    return sheet_chain_key(raw)


def _extract_inline_revision(text: str | None) -> str | None:
    """Pull a revision token ('Rev C') out of a free-text cell/line.

    Read through the title block reader's own pattern, so a pasted register and
    a drawing page cannot disagree about what a revision label is. It used to be
    a copy of the old page pattern, which read "Pianta porta scorrevole" as
    revision "ole".
    """
    return extract_inline_revision(text)


def _looks_like_sheet_number(cell: str | None) -> bool:
    """True when a table cell reads like a sheet number (short, has a digit)."""
    s = (cell or "").strip()
    if not s or len(s) > 20:
        return False
    if not any(ch.isdigit() for ch in s):
        return False
    return bool(_SHEET_NUMBER_CELL.match(s))


def parse_pasted_index(text: str) -> list[ExpectedSheet]:
    """Parse a pasted sheet list into the expected set.

    Accepts CSV / TSV / semicolon rows (``number, title, rev``) and bare
    newline-delimited numbers. The first token per row is the sheet number; a
    third column, when present, is the revision, otherwise a trailing revision
    token is detected in the row via the ``Rev X`` pattern. Rows whose first
    token carries no digit (headers such as "Sheet, Title, Rev", or a register
    title line) are skipped. Duplicates collapse on the normalized number,
    last row wins.
    """
    if not text:
        return []
    # Ordered map keeps a stable output order while letting a later duplicate
    # overwrite an earlier one (last wins).
    by_norm: dict[str, ExpectedSheet] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "\t" in line:
            cells = [c.strip() for c in line.split("\t")]
        elif "," in line:
            cells = [c.strip() for c in line.split(",")]
        elif ";" in line:
            cells = [c.strip() for c in line.split(";")]
        else:
            # Bare row: the first whitespace token is the number, the remainder
            # (if any) is the free-text title.
            parts = line.split(None, 1)
            cells = [parts[0]] + ([parts[1]] if len(parts) > 1 else [])
        number = cells[0].strip() if cells else ""
        # A real sheet number always carries a digit; this drops header rows and
        # register-title lines without a hand-maintained keyword list.
        if not number or not any(ch.isdigit() for ch in number):
            continue
        norm = normalize_sheet_number(number)
        if not norm:
            continue
        title = cells[1].strip() if len(cells) > 1 and cells[1].strip() else None
        revision: str | None = None
        if len(cells) > 2 and cells[2].strip():
            revision = cells[2].strip()
        else:
            revision = _extract_inline_revision(line)
        by_norm[norm] = ExpectedSheet(
            sheet_number=number,
            sheet_number_norm=norm,
            sheet_title=title,
            revision=revision,
        )
    return list(by_norm.values())


def _cell_text(cell: object) -> str:
    """Coerce a pdfplumber table cell (``str | None``) to trimmed text."""
    if cell is None:
        return ""
    return str(cell).replace("\n", " ").strip()


def _identify_columns(rows: list[list[str]]) -> tuple[int | None, int | None, int | None]:
    """Locate the number / title / revision columns in a lifted table.

    Header match wins: a first row whose cells name SHEET / DWG / NO, TITLE and
    REV pins the columns directly. Failing that, the number column is the one
    with the highest ratio of sheet-number-looking cells, the title column is
    the widest free-text column, and the revision column is left unset.
    """
    if not rows:
        return None, None, None
    header = [c.upper() for c in rows[0]]
    num_col = title_col = rev_col = None

    def _header_hit(cell: str, needles: tuple[str, ...]) -> bool:
        return any(n in cell for n in needles)

    for idx, cell in enumerate(header):
        if rev_col is None and _header_hit(cell, _REVISION_HEADERS):
            rev_col = idx
        elif title_col is None and _header_hit(cell, _TITLE_HEADERS):
            title_col = idx
        elif num_col is None and _header_hit(cell, _NUMBER_HEADERS):
            num_col = idx

    if num_col is None:
        # No usable header: pick the column with the most sheet-number cells.
        col_count = len(rows[0])
        best_idx, best_ratio = None, 0.0
        for col in range(col_count):
            cells = [row[col] for row in rows if col < len(row)]
            if not cells:
                continue
            ratio = sum(1 for c in cells if _looks_like_sheet_number(c)) / len(cells)
            if ratio > best_ratio:
                best_idx, best_ratio = col, ratio
        # Require a real signal so a table without any sheet numbers yields none.
        if best_ratio >= 0.3:
            num_col = best_idx

    if num_col is not None and title_col is None:
        # Widest free-text column that is not the number/rev column.
        col_count = max(len(r) for r in rows)
        best_idx, best_len = None, 0
        for col in range(col_count):
            if col in (num_col, rev_col):
                continue
            avg = _avg_len([row[col] for row in rows if col < len(row)])
            if avg > best_len:
                best_idx, best_len = col, avg
        if best_len >= 4:
            title_col = best_idx

    return num_col, title_col, rev_col


def _avg_len(cells: list[str]) -> int:
    non_empty = [c for c in cells if c]
    if not non_empty:
        return 0
    return sum(len(c) for c in non_empty) // len(non_empty)


def parse_index_tables(pdf_path: str, page: int | None = None) -> list[ExpectedSheet]:
    """Lift the drawing-index table(s) from a PDF into the expected set.

    Best-effort table extraction with ``pdfplumber.extract_tables()`` (the same
    library the sheet splitter uses). ``page`` is 1-based; ``None`` scans every
    page. Rows without a sheet-number cell are skipped, and duplicates collapse
    on the normalized number (last wins). Returns an empty list when no table or
    no number column can be found, in which case the caller falls back to paste
    mode. Never raises on a malformed table.
    """
    import pdfplumber

    by_norm: dict[str, ExpectedSheet] = {}
    with pdfplumber.open(pdf_path) as pdf:
        if page is not None:
            if page < 1 or page > len(pdf.pages):
                return []
            pages = [pdf.pages[page - 1]]
        else:
            pages = list(pdf.pages)

        for pg in pages:
            for table in pg.extract_tables() or []:
                rows = [[_cell_text(c) for c in row] for row in table if row]
                # Drop fully-blank rows so they do not skew column detection.
                rows = [r for r in rows if any(c for c in r)]
                if len(rows) < 2:
                    continue
                num_col, title_col, rev_col = _identify_columns(rows)
                if num_col is None:
                    continue
                for row in rows:
                    if num_col >= len(row):
                        continue
                    number = row[num_col].strip()
                    if not _looks_like_sheet_number(number):
                        continue  # header / spanning / blank row
                    norm = normalize_sheet_number(number)
                    if not norm:
                        continue
                    title = (
                        row[title_col].strip()
                        if title_col is not None and title_col < len(row) and row[title_col].strip()
                        else None
                    )
                    revision = (
                        row[rev_col].strip()
                        if rev_col is not None and rev_col < len(row) and row[rev_col].strip()
                        else None
                    )
                    by_norm[norm] = ExpectedSheet(
                        sheet_number=number,
                        sheet_number_norm=norm,
                        sheet_title=title,
                        revision=revision,
                    )
    return list(by_norm.values())


def reconcile(expected: list[ExpectedSheet], actual: list[dict]) -> ReconcileResult:
    """Pure set-diff of the expected index against the actual sheet rows.

    Both sides are keyed on ``normalize_sheet_number``. An actual row with a
    blank/None number is dropped from the actual set (it cannot be reconciled by
    number). A revision mismatch is only reported for a matched number where
    both revisions are present and differ after upper/trim. Display strings (not
    the normalized keys) are returned for every user-facing list.
    """
    expected_by_norm: dict[str, ExpectedSheet] = {}
    for e in expected:
        # Recomputed from the number whenever there is one: a key stored by an
        # earlier normaliser (a saved report's "A01") must not keep apart what
        # the current one joins.
        norm = normalize_sheet_number(e.sheet_number) or e.sheet_number_norm
        if norm:
            expected_by_norm[norm] = e

    actual_by_norm: dict[str, dict] = {}
    for a in actual:
        norm = normalize_sheet_number(a.get("sheet_number"))
        if norm:
            actual_by_norm[norm] = a

    expected_norms = set(expected_by_norm)
    actual_norms = set(actual_by_norm)
    matched_norms = expected_norms & actual_norms

    missing = sorted(expected_by_norm[n].sheet_number for n in (expected_norms - actual_norms))
    extra = sorted(str(actual_by_norm[n].get("sheet_number") or "") for n in (actual_norms - expected_norms))
    matched = sorted(expected_by_norm[n].sheet_number for n in matched_norms)

    rev_mismatch: list[dict[str, str]] = []
    for n in sorted(matched_norms):
        e = expected_by_norm[n]
        a = actual_by_norm[n]
        expected_rev = (e.revision or "").strip()
        actual_rev = str(a.get("revision") or "").strip()
        if expected_rev and actual_rev and expected_rev.upper() != actual_rev.upper():
            rev_mismatch.append(
                {
                    "sheet_number": e.sheet_number,
                    "expected_rev": expected_rev,
                    "actual_rev": actual_rev,
                }
            )

    return ReconcileResult(
        missing=missing,
        extra=extra,
        matched=matched,
        rev_mismatch=rev_mismatch,
        expected_count=len(expected_by_norm),
        actual_count=len(actual_by_norm),
    )
