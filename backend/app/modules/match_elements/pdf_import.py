# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PDF BoQ ingest for the match-elements module.

Implements MAPPING_PROCESS.md §4.1.x - the "PDF" source. The estimator
uploads a tender PDF (a printed bill of quantities, a priced schedule,
a specification table) and we extract one matchable line item per table
row (preferred) or per text line (fallback). The extracted rows land in
the same shape :class:`PdfAdapter` and :class:`BoqAdapter` understand -
``{description, qty?, unit?, code?, category?}`` - so the downstream
group / match / apply pipeline does not branch on source type.

This module is the heavy lifting; the adapter itself is a thin reader
over ``MatchSession.metadata_["pdf_rows"]`` (mirrors the Excel split,
where parsing happens once at session-creation time rather than on the
match hot path).

PDF text extraction reuses the libraries already shipped with the
platform - ``pdfplumber`` first (best at table reconstruction), with
``pypdfium2`` (through :mod:`app.core.pdf_reader`) as the plain-text
fallback when pdfplumber cannot open the file. Both are existing
dependencies; no new dependency is introduced.

Public surface:

* :func:`parse_boq_pdf` - bytes -> list[dict] ready for SessionCreate.

Extraction strategy
--------------------
1. ``pdfplumber`` opens the document and, per page, attempts
   ``extract_tables()``. When a table is found we detect a header row
   using the same multi-language alias map the Excel importer uses, then
   read each data row into a ``{description, qty?, unit?, code?, ...}``
   dict. A header is not mandatory: a table whose first textual column
   reads like a description (and which has no recognised header) is
   treated as a positional ``[code?, description, qty?, unit?]`` layout.
2. When a page has no tables, we fall back to per-line text parsing:
   each non-blank line that carries enough signal (a description plus an
   optional trailing ``<qty> <unit>`` pair) becomes one row.
3. When ``pdfplumber`` cannot open the file at all, ``pypdfium2`` extracts
   plain text per page and we run the same per-line parser.

The parser is deliberately forgiving: a scanned PDF with no text layer
yields zero rows (the caller surfaces a clear "no extractable text"
message) rather than raising, and malformed cells are skipped instead
of aborting the whole import.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

# Reuse the Excel importer's column-detection + numeric-coercion logic so
# PDF and Excel BoQ ingest stay behaviourally identical (same alias
# table, same "12.345,67" handling). Keeping a single source of truth
# means a new header spelling added for Excel works for PDF too.
from app.modules.match_elements.excel_import import _match_column, _to_float_qty

logger = logging.getLogger(__name__)


# A trailing "<number> <unit>" pair on a free-text line - e.g.
# "Reinforced concrete wall C30/37 ... 125.50 m3". The unit is one of the
# canonical measurement tokens the BoQ adapter already maps onto a
# quantity dimension; anything else is left in the description. The
# number tolerates thousands separators and a decimal comma or point.
_QTY_UNIT_TAIL_RE = re.compile(
    r"(?P<qty>\d[\d.,\s]*\d|\d)\s*"
    r"(?P<unit>m2|m²|m3|m³|m|lm|rm|kg|t|pcs|pc|ea|stk|stck|nr|no|st|шт|м2|м²|м3|м³|м)\b\.?\s*$",
    re.IGNORECASE,
)

# A leading position code - "01.02.003", "1.1", "WALL-001", "04 20 00".
# Used by the positional (header-less) table layout and the text-line
# parser to peel a code off the front of a row.
_LEADING_CODE_RE = re.compile(r"^(?P<code>[0-9]+(?:[.\-][0-9A-Za-z]+){1,5}|[A-Z]{2,}[-_][0-9A-Za-z\-]+)\s+")

# Lines that are page furniture, not estimable items. Compared after
# lower-casing + stripping; kept short and conservative so we never drop
# a real description that merely starts with one of these words.
_NOISE_LINE_RE = re.compile(
    r"^(page\s+\d+|seite\s+\d+|страница\s+\d+|\d+\s*/\s*\d+|total|summe|итого|subtotal|"
    r"carried forward|brought forward|continued|fortsetzung)\b",
    re.IGNORECASE,
)

# Minimum number of alphabetic characters a description must carry to be
# treated as a real line item - filters out stray numeric rows, rulers,
# and table separators that survive extraction.
_MIN_DESCRIPTION_ALPHA = 3


def _clean_cell(value: Any) -> str:
    """Normalise a raw table cell to a trimmed single-line string."""
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    return re.sub(r"\s{2,}", " ", text)


def _looks_like_description(text: str) -> bool:
    """Return True when ``text`` carries enough alphabetic signal.

    A real BoQ description has letters; a stray "1,234.50" or a row of
    dashes does not. We also reject pure page-furniture lines.
    """
    if not text:
        return False
    if _NOISE_LINE_RE.match(text.strip()):
        return False
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha >= _MIN_DESCRIPTION_ALPHA


def _split_qty_unit_tail(text: str) -> tuple[str, float | None, str | None]:
    """Peel a trailing ``<qty> <unit>`` pair off a free-text line.

    Returns ``(remaining_description, qty, unit)``. When no recognised
    tail is present, ``qty`` and ``unit`` are ``None`` and the
    description is returned unchanged.
    """
    match = _QTY_UNIT_TAIL_RE.search(text)
    if not match:
        return text.strip(), None, None
    qty = _to_float_qty(match.group("qty"))
    unit = match.group("unit").strip().lower()
    description = text[: match.start()].strip(" .\t:-")
    # Guard: if stripping the tail leaves no real description, keep the
    # original line intact (the number was probably part of the text,
    # e.g. "Concrete C30/37").
    if not _looks_like_description(description):
        return text.strip(), None, None
    return description, qty, unit


def _peel_leading_code(text: str) -> tuple[str | None, str]:
    """Peel a leading position code off a line. Returns ``(code, rest)``."""
    match = _LEADING_CODE_RE.match(text)
    if not match:
        return None, text.strip()
    code = match.group("code")
    rest = text[match.end() :].strip()
    # Only treat it as a code when something descriptive follows - a bare
    # "01.02.003" with nothing after it is an ordinal label, not a line.
    if not _looks_like_description(rest):
        return None, text.strip()
    return code, rest


def _row_from_text_line(line: str) -> dict[str, Any] | None:
    """Parse a single free-text line into a BoQ row dict, or ``None``.

    Shape: ``{description, qty?, unit?, code?}``. Returns ``None`` for
    blank lines, page furniture, and lines without a usable description.
    """
    raw = _clean_cell(line)
    if not raw or not _looks_like_description(raw):
        return None
    code, rest = _peel_leading_code(raw)
    description, qty, unit = _split_qty_unit_tail(rest)
    if not _looks_like_description(description):
        return None
    row: dict[str, Any] = {"description": description}
    if qty is not None:
        row["qty"] = qty
    if unit:
        row["unit"] = unit
    if code:
        row["code"] = code
    return row


def _column_map_from_header(header: list[Any]) -> dict[int, str]:
    """Detect canonical columns in a table header row.

    Reuses the Excel importer's :func:`_match_column` alias table so PDF
    and Excel agree on header spellings across all supported locales.
    Returns ``{col_index: canonical_name}`` (empty when no header maps).
    """
    column_map: dict[int, str] = {}
    for idx, cell in enumerate(header):
        canon = _match_column(_clean_cell(cell))
        if canon:
            column_map[idx] = canon
    return column_map


def _rows_from_structured_table(
    table: list[list[Any]],
    column_map: dict[int, str],
) -> list[dict[str, Any]]:
    """Read data rows from a table whose header columns were detected."""
    out: list[dict[str, Any]] = []
    for raw_row in table[1:]:
        entry: dict[str, Any] = {}
        for idx, cell in enumerate(raw_row):
            key = column_map.get(idx)
            if key is None:
                continue
            value = _clean_cell(cell)
            if not value:
                continue
            if key == "qty":
                f = _to_float_qty(value)
                if f is not None:
                    entry["qty"] = f
            else:
                entry[key] = value
        description = entry.get("description")
        if isinstance(description, str) and _looks_like_description(description):
            out.append(entry)
    return out


def _rows_from_positional_table(table: list[list[Any]]) -> list[dict[str, Any]]:
    """Read a header-less table by positional heuristics.

    Strategy: the widest textual column is the description. A column that
    parses fully numeric is the quantity; a short alpha column to its
    right is the unit; a leading code-shaped column is the code. This is
    a best-effort fallback for tables that pdfplumber reconstructs
    without a recognisable header row.
    """
    if not table:
        return []
    # Find the column index whose cells carry the most alphabetic text on
    # average - that is the description column.
    n_cols = max((len(r) for r in table), default=0)
    if n_cols == 0:
        return []
    alpha_score = [0] * n_cols
    for row in table:
        for idx in range(n_cols):
            cell = _clean_cell(row[idx]) if idx < len(row) else ""
            alpha_score[idx] += sum(1 for ch in cell if ch.isalpha())
    desc_col = max(range(n_cols), key=lambda i: alpha_score[i])

    out: list[dict[str, Any]] = []
    for row in table:
        cells = [_clean_cell(c) for c in row]
        description = cells[desc_col] if desc_col < len(cells) else ""
        if not _looks_like_description(description):
            continue
        entry: dict[str, Any] = {"description": description}
        # Quantity: first fully-numeric cell that is not the description.
        for idx, cell in enumerate(cells):
            if idx == desc_col or not cell:
                continue
            f = _to_float_qty(cell)
            if f is not None and not any(ch.isalpha() for ch in cell):
                entry["qty"] = f
                # Unit often sits in the next non-empty short alpha cell.
                for unit_cell in cells[idx + 1 :]:
                    if unit_cell and len(unit_cell) <= 6 and any(c.isalpha() for c in unit_cell):
                        entry["unit"] = unit_cell.lower()
                        break
                break
        # Code: a leading code-shaped cell before the description.
        if desc_col > 0:
            code, _rest = _peel_leading_code(cells[0] + " x")
            if code:
                entry["code"] = code
        out.append(entry)
    return out


def _rows_from_tables(tables: list[list[list[Any]]]) -> list[dict[str, Any]]:
    """Extract rows from all tables on one page."""
    out: list[dict[str, Any]] = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        column_map = _column_map_from_header(table[0])
        if "description" in column_map.values():
            out.extend(_rows_from_structured_table(table, column_map))
        else:
            out.extend(_rows_from_positional_table(table))
    return out


def _rows_from_text(text: str) -> list[dict[str, Any]]:
    """Parse plain page text into rows, one per usable line."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        row = _row_from_text_line(line)
        if row is not None:
            out.append(row)
    return out


def _extract_with_pdfplumber(content: bytes) -> list[dict[str, Any]]:
    """Primary extractor - tables first, per-page text fallback."""
    import pdfplumber

    rows: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            page_rows = _rows_from_tables(tables)
            if page_rows:
                rows.extend(page_rows)
                continue
            # No usable table on this page - fall back to text lines.
            text = page.extract_text() or ""
            rows.extend(_rows_from_text(text))
    return rows


def _extract_with_pdfium(content: bytes) -> list[dict[str, Any]]:
    """Fallback extractor - plain text per page via pypdfium2."""
    from app.core import pdf_reader

    rows: list[dict[str, Any]] = []
    with pdf_reader.open_pdf(content) as doc:
        for page in doc:
            rows.extend(_rows_from_text(page.text() or ""))
    return rows


def parse_boq_pdf(content: bytes) -> list[dict[str, Any]]:
    """Parse a PDF upload into a list of BoQ row dicts.

    Tries ``pdfplumber`` (tables + text), then ``pypdfium2`` (text only)
    when pdfplumber cannot open the file. Returns rows ready to feed
    into :class:`SessionCreate.pdf_rows` and from there to
    :class:`PdfAdapter`.

    Rules (mirror :func:`match_elements.excel_import.parse_boq_xlsx`):

    * Rows without a usable ``description`` are skipped.
    * ``qty`` is parsed numerically; a trailing ``<qty> <unit>`` pair on
      a text line is split off into ``qty`` / ``unit``.
    * Other recognised columns (``code``, ``category``, ``unit``) pass
      through as trimmed strings.

    Args:
        content: The PDF file bytes as uploaded.

    Returns:
        ``[{description, qty?, unit?, code?, category?}, ...]`` - possibly
        empty when the PDF carries no extractable text (scanned image).

    Raises:
        ValueError: When the bytes cannot be parsed by either backend.
    """
    if not content:
        raise ValueError("Uploaded file is empty.")

    try:
        rows = _extract_with_pdfplumber(content)
    except Exception:
        logger.warning(
            "match_elements.parse_boq_pdf: pdfplumber failed (size=%dB) - falling back to pypdfium2",
            len(content),
            exc_info=True,
        )
        try:
            rows = _extract_with_pdfium(content)
        except Exception as exc:
            logger.exception(
                "match_elements.parse_boq_pdf: both pdfplumber and pypdfium2 failed (size=%dB)",
                len(content),
            )
            raise ValueError(
                f"Could not read the uploaded file as a PDF: {exc}",
            ) from exc

    return rows


__all__ = ["parse_boq_pdf"]
