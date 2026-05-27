"""Shared encoding / number-parsing helpers for BOQ importers.

Centralises three concerns that the historical inline parsers each
re-implemented (and got slightly differently right) in ``router.py``:

* ``decode_text_bytes()`` — try a sequence of codecs (UTF-8 BOM,
  UTF-8, Latin-1, CP1252) and return the first that round-trips
  losslessly. BC3 files in particular ship in CP1252 / Latin-1 by
  convention, and DACH CSV exports from Excel default to Latin-1.
* ``safe_float()`` — locale-tolerant float parse. Understands
  European (``1.234,56``) and US (``1,234.56``) thousand/decimal
  conventions, trailing currency / unit suffixes (``"185.00 EUR"``),
  and Spanish negative signs (``-3,5``).
* ``parse_numeric_cell()`` — strict variant for Excel/CSV imports:
  empty cells parse to ``0.0`` with ``error=None``; non-empty cells
  that can't be coerced return ``(None, error_message)`` so the
  caller can surface a per-row diagnostic.

All helpers are pure / sync / no third-party deps.
"""

from __future__ import annotations

from typing import Any

# Encoding probe order matters: BOM-tagged UTF-8 first (Excel exports),
# then plain UTF-8, then the DACH/Spanish/LATAM legacy CP1252 (covers
# Latin-1 as a strict subset). Latin-1 is the last-resort fallback —
# it never raises (every byte is a valid code-point), so it must come
# last or it would shadow legitimate UTF-8.
DEFAULT_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


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
    """
    last_exc: UnicodeDecodeError | None = None
    for enc in encodings:
        try:
            return content.decode(enc), enc
        except UnicodeDecodeError as exc:
            last_exc = exc
            continue
    # If we got here every codec failed — re-raise the last exception
    # rather than synthesising a fresh one (preserves the offending
    # byte position for the debug log).
    if last_exc is not None:
        raise last_exc
    # Defensive: empty encodings tuple.
    raise UnicodeDecodeError("decode_text_bytes", content, 0, 0, "no encodings supplied")


def safe_float(value: Any, default: float = 0.0) -> float:
    """Parse ``value`` to ``float``, returning ``default`` on failure.

    Handles ``int``/``float`` directly, and for ``str`` understands:

    * European decimal-comma (``"1.234,56"`` → ``1234.56``).
    * US decimal-dot (``"1,234.56"`` → ``1234.56``).
    * Single decimal-comma (``"42,5"`` → ``42.5``) — covers de_DE,
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
        # bool is an int subclass — explicitly reject so True/False
        # is not silently accepted as 1/0 in a numeric column.
        return default
    if isinstance(value, (int, float)):
        f = float(value)
        # Reject NaN/Infinity for safety.
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    text = str(value).strip()
    if not text:
        return default

    # Strip optional sign prefix.
    sign = 1.0
    if text[0] in "+-":
        if text[0] == "-":
            sign = -1.0
        text = text[1:].strip()

    # Take only the leading numeric run plus separators — trailing
    # ``" EUR"`` / ``" m"`` is silently dropped.
    import re

    m = re.match(r"[0-9][0-9.,\s]*", text)
    if not m:
        return default
    numeric = m.group(0).strip()
    # Collapse whitespace thousands separators ("1 234,56" → "1234,56").
    for ws in (" ", "\t", " ", " "):
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


def parse_numeric_cell(value: Any) -> tuple[float | None, str | None]:
    """Strict numeric parse for spreadsheet imports.

    Empty cells parse to ``(0.0, None)`` — the column was simply blank.
    Non-empty cells that can't be coerced return ``(None, error_message)``
    so the caller can surface a per-row diagnostic instead of silently
    zero-filling.
    """
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
    if parsed != parsed:  # NaN — safe_float couldn't coerce it.
        return None, f"expected a number, got {text!r}"
    return parsed, None
