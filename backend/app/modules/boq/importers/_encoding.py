# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared encoding / number-parsing helpers for BOQ importers.

Centralises three concerns that the historical inline parsers each
re-implemented (and got slightly differently right) in ``router.py``:

* ``decode_text_bytes()`` - try a sequence of codecs (UTF-8 BOM,
  UTF-8, Latin-1, CP1252) and return the first that round-trips
  losslessly. BC3 files in particular ship in CP1252 / Latin-1 by
  convention, and DACH CSV exports from Excel default to Latin-1.
* ``safe_float()`` - locale-tolerant float parse. Understands
  European (``1.234,56``) and US (``1,234.56``) thousand/decimal
  conventions, trailing currency / unit suffixes (``"185.00 EUR"``),
  and Spanish negative signs (``-3,5``).
* ``parse_numeric_cell()`` - strict variant for Excel/CSV imports:
  empty cells parse to ``0.0`` with ``error=None``; non-empty cells
  that can't be coerced return ``(None, error_message)`` so the
  caller can surface a per-row diagnostic.
* ``dot_groups_thousands()`` - whether a typed number is written with dots
  between groups of three and no comma (``"12.500"``), which a market
  that writes a decimal comma means as twelve thousand five hundred.
* ``comma_groups_thousands()`` - the mirror image: ``"12,500"``, which a
  market that writes a decimal point means as twelve thousand five hundred.

All helpers are pure / sync / no third-party deps.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Encoding probe order matters: BOM-tagged UTF-8 first (Excel exports),
# then plain UTF-8, then the DACH/Spanish/LATAM legacy CP1252 (covers
# Latin-1 as a strict subset). Latin-1 is the last-resort fallback -
# it never raises (every byte is a valid code-point), so it must come
# last or it would shadow legitimate UTF-8.
DEFAULT_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

# The byte-order marks of the wide Unicode forms, longest first: the UTF-32 LE
# mark begins with the UTF-16 LE one. Excel saves "Unicode text" as UTF-16
# with a mark, and none of the probes above can read it: every second byte is
# a NUL, which cp1252 and latin-1 decode without an error into text nobody
# wrote.
_WIDE_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def wide_bom_codec(content: bytes) -> str | None:
    """``"utf-16"`` or ``"utf-32"`` when ``content`` opens with that form's byte-order mark."""
    for bom, codec in _WIDE_BOMS:
        if content.startswith(bom):
            return codec
    return None


def decode_text_bytes(
    content: bytes,
    encodings: tuple[str, ...] = DEFAULT_ENCODINGS,
) -> tuple[str, str]:
    """Decode ``content`` with the first codec that succeeds.

    Args:
        content: Raw file bytes.
        encodings: Ordered tuple of codec names to try.

    Returns:
        Tuple ``(text, encoding_used)``.

    Raises:
        UnicodeDecodeError: If none of the candidate encodings can
            decode the input (only possible if ``encodings`` excludes
            ``latin-1``, which is universal).

    A UTF-16 or UTF-32 byte-order mark is read before the probes: it names
    the form outright, and the codec named after it strips the mark.
    """
    wide = wide_bom_codec(content)
    if wide is not None:
        try:
            return content.decode(wide), wide
        except UnicodeDecodeError:
            pass
    last_exc: UnicodeDecodeError | None = None
    for enc in encodings:
        try:
            return content.decode(enc), enc
        except UnicodeDecodeError as exc:
            last_exc = exc
            continue
    # If we got here every codec failed - re-raise the last exception
    # rather than synthesising a fresh one (preserves the offending
    # byte position for the debug log).
    if last_exc is not None:
        raise last_exc
    # Defensive: empty encodings tuple.
    raise UnicodeDecodeError("decode_text_bytes", content, 0, 0, "no encodings supplied")


def _is_wide(char: str) -> bool:
    """Whether ``char`` is one of the full-width or squared forms :func:`fold_width` folds."""
    code = ord(char)
    return (
        0xFF01 <= code <= 0xFF5E  # full-width ASCII: digits, letters, ( ) . , : and the rest
        or 0xFFE0 <= code <= 0xFFE6  # full-width cent, pound, not, macron, broken bar, yen, won
        or code == 0x3000  # ideographic space
        or 0x3300 <= code <= 0x33FF  # CJK compatibility squares: ㎡ ㎥ ㎏ ㎜ ㏄
    )


def fold_width(text: str) -> str:
    """``text`` with its full-width and squared characters folded to their plain forms.

    Chinese, Japanese and Korean input methods type digits, brackets,
    separators and units full width ("１２．５", "（元）", "㎡"), and a
    workbook mixes them with the ASCII forms. Only those blocks are folded:
    the full-width ASCII forms, the full-width currency signs, the
    ideographic space and the CJK unit squares. Everything else is kept as
    typed, so "m²", "№" and "½" stay what they are, which a whole-string
    NFKC would not leave them.
    """
    if not any(_is_wide(char) for char in text):
        return text
    return "".join(unicodedata.normalize("NFKC", char) if _is_wide(char) else char for char in text)


# A currency written in front of the amount: a sign ("$", "₹", "¥"), a
# dollar with its country ("US$", "C$", "R$"), the rupiah's "Rp", or an ISO
# code ("AED ", "CHF "). Only in front of a number; a trailing "EUR" or "Ft"
# is dropped by the numeric-run match already. Without this a rate typed as
# "$1,234.56" was not a number at all, and "R$ 1.234,56" imported nothing.
_CURRENCY_PREFIX = re.compile(
    r"^(?:[A-Z]{3}(?=[\s\d])|(?:US|NZ|HK|A|C|S|R|MX|CA|AU)?\$|Rp\.?|[€£¥￥₹₽₺₩₴₦฿₫₪₱])\s*(?=[\d+-])"
)

# Group separators that are never a decimal point: the Swiss apostrophe in
# both spellings, the space and its no-break and narrow no-break variants.
_GROUP_ONLY = ("'", "\u2019", " ", "\t", "\u00a0", "\u202f")


def strip_currency(text: str) -> str:
    """``text`` without a currency written in front of its number."""
    return _CURRENCY_PREFIX.sub("", text.strip(), count=1)


def safe_float(value: Any, default: float = 0.0) -> float:
    """Parse ``value`` to ``float``, returning ``default`` on failure.

    Handles ``int``/``float`` directly, and for ``str`` understands:

    * European decimal-comma (``"1.234,56"`` → ``1234.56``).
    * US decimal-dot (``"1,234.56"`` → ``1234.56``).
    * Single decimal-comma (``"42,5"`` → ``42.5``) - covers de_DE,
      es_ES, fr_FR, pt_PT.
    * Trailing whitespace + currency / unit suffix
      (``"150,00 EUR"`` / ``"3.0 m"`` → ``150.0`` / ``3.0``).
    * Plus/minus sign prefix.

    Returns ``default`` for ``None``, empty string, or any input that
    can't be coerced.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        # bool is an int subclass - explicitly reject so True/False
        # is not silently accepted as 1/0 in a numeric column.
        return default
    if isinstance(value, (int, float)):
        f = float(value)
        # Reject NaN/Infinity for safety.
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    text = fold_width(str(value)).strip()
    if not text:
        return default

    # Strip optional sign prefix, on either side of a leading currency.
    sign = 1.0
    text = strip_currency(text)
    if text and text[0] in "+-":
        if text[0] == "-":
            sign = -1.0
        text = strip_currency(text[1:].strip())

    # Take only the leading numeric run plus separators - trailing
    # ``" EUR"`` / ``" m"`` is silently dropped.
    m = re.match(r"[0-9][0-9.,\s'\u2019\u00a0\u202f]*", text)
    if not m:
        return default
    numeric = m.group(0).strip()
    # Collapse group-only separators ("1 234,56" -> "1234,56", "1'250.50" ->
    # "1250.50").
    for ws in _GROUP_ONLY:
        numeric = numeric.replace(ws, "")
    if not numeric:
        return default

    has_dot = "." in numeric
    has_comma = "," in numeric

    if has_dot and has_comma:
        # Both present → last-occurring separator is the decimal point.
        if numeric.rfind(",") > numeric.rfind("."):
            numeric = numeric.replace(".", "").replace(",", ".")
        else:
            numeric = numeric.replace(",", "")
    elif has_comma:
        # Single comma → decimal (EU). Multi-comma → US thousands.
        if numeric.count(",") > 1:
            numeric = numeric.replace(",", "")
        else:
            numeric = numeric.replace(",", ".")
    elif has_dot:
        # Multi-dot → DACH thousands; single dot is canonical decimal.
        if numeric.count(".") > 1:
            numeric = numeric.replace(".", "")

    try:
        return sign * float(numeric)
    except (ValueError, TypeError):
        return default


# One to three digits, then one or more groups of a dot and exactly three
# digits, and nothing numeric after: "12.500", "1.250.000", "12.500 Ft".
_DOT_GROUPS = re.compile(r"[+-]?\d{1,3}(?:\.\d{3})+(?![\d.,])")


def dot_groups_thousands(value: Any) -> bool:
    """Whether a typed cell writes its number with dots between groups of three.

    ``"12.500"`` is twelve and a half to :func:`safe_float`, which reads a
    lone dot as the decimal point, and twelve thousand five hundred to anyone
    who writes a decimal comma: Hungarian prices are written ``12.500 Ft`` as
    often as ``12 500 Ft``. Only text answers: a cell Excel holds as a number
    carries no separators to misread. A comma anywhere in the number means the
    writer used one as the decimal point, and :func:`safe_float` already reads
    that shape correctly.
    """
    if not isinstance(value, str):
        return False
    text = strip_currency(fold_width(value)).replace("\u00a0", "").replace("\u202f", "")
    match = _DOT_GROUPS.match(text)
    return match is not None and "," not in text[: match.end() + 1]


# One to three digits, then one or more groups of a comma and exactly three
# digits, and no dot: "12,500", "1,250,000", "¥12,500".
_COMMA_GROUPS = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?![\d.,])")


def comma_groups_thousands(value: Any) -> bool:
    """Whether a typed cell writes its number with commas between groups of three.

    The mirror of :func:`dot_groups_thousands`. :func:`safe_float` reads one
    comma as the decimal point, which is right in Berlin and wrong in Sydney,
    Beijing or Mumbai, where ``"12,500"`` is twelve thousand five hundred and
    was imported as twelve and a half. More than one comma already reads as
    grouping, so only the single-group shape changes meaning.
    """
    if not isinstance(value, str):
        return False
    text = strip_currency(fold_width(value)).replace(" ", "").replace("\u00a0", "")
    match = _COMMA_GROUPS.match(text)
    return match is not None and "." not in text[: match.end() + 1]


def parse_numeric_cell(
    value: Any, *, dot_thousands: bool = False, comma_thousands: bool = False
) -> tuple[float | None, str | None]:
    """Strict numeric parse for spreadsheet imports.

    Empty cells parse to ``(0.0, None)`` - the column was simply blank.
    Non-empty cells that can't be coerced return ``(None, error_message)``
    so the caller can surface a per-row diagnostic instead of silently
    zero-filling.

    Args:
        value: The cell.
        dot_thousands: Read ``"12.500"`` as 12500, see
            :func:`dot_groups_thousands`. For a file whose header says it was
            written in a decimal-comma market; the caller reports each cell it
            read this way.
        comma_thousands: Read ``"12,500"`` as 12500, see
            :func:`comma_groups_thousands`. For a file written in a
            decimal-point market; reported the same way.

    Full-width digits and separators ("１２．５") read as their ASCII twins,
    see :func:`fold_width`.
    """
    if isinstance(value, str):
        value = fold_width(value)
    if dot_thousands and dot_groups_thousands(value):
        value = value.strip().replace(".", "")
    elif comma_thousands and comma_groups_thousands(value):
        value = value.strip().replace(",", "")
    if value is None:
        return 0.0, None
    if isinstance(value, bool):
        return None, f"expected a number, got boolean {value!r}"
    if isinstance(value, (int, float)):
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            return None, f"expected a finite number, got {value!r}"
        return f, None
    text = str(value).strip()
    if not text:
        return 0.0, None
    # Sentinel for unparseable: safe_float returns NaN-equivalent only
    # if we explicitly ask for it. Easier to re-parse with a NaN-default.
    parsed = safe_float(text, default=float("nan"))
    if parsed != parsed:  # NaN - safe_float couldn't coerce it.
        return None, f"expected a number, got {text!r}"
    return parsed, None
