# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-unit tests for the shared BOQ importer encoding / number parsers.

``app.modules.boq.importers._encoding`` centralises three concerns the
historical inline importer parsers each re-implemented (and got slightly
differently right):

* ``safe_float`` - locale-tolerant float parse. EU decimal-comma
  (``1.234,56``), US decimal-dot (``1,234.56``), single decimal-comma
  (``42,5``), whitespace thousands (``1 234,56``), trailing currency / unit
  suffix (``150,00 EUR``), sign prefix; rejects bool / NaN / Inf.
* ``parse_numeric_cell`` - strict spreadsheet variant: a blank cell is a
  legitimate ``0.0`` (``error=None``) but a non-blank cell that cannot be
  coerced returns ``(None, message)`` so the import loop can surface a
  per-row diagnostic instead of silently zero-filling.
* ``decode_text_bytes`` - tries UTF-8 BOM -> UTF-8 -> CP1252 -> Latin-1 and
  returns the first codec that round-trips (BC3 ships CP1252/Latin-1 by
  convention, DACH Excel CSV defaults to Latin-1).

These helpers are imported here in isolation - the module pulls in NO
``app.database`` engine - so unlike the service-level helper suites this file
runs locally on Python 3.11 as well as in CI. The parsers are also a security
boundary (importers feed untrusted spreadsheet/XML cells straight into money
arithmetic), so the bool / NaN / Inf rejections below are regression locks,
not just happy-path coverage.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_encoding_parsers.py -v
"""

from __future__ import annotations

import math

import pytest

from app.modules.boq.importers._encoding import (
    DEFAULT_ENCODINGS,
    decode_text_bytes,
    parse_numeric_cell,
    safe_float,
)

# ── safe_float: native numeric inputs ────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (42, 42.0),
        (3.5, 3.5),
        (0, 0.0),
        (-7, -7.0),
        (-2.25, -2.25),
    ],
)
def test_safe_float_native_numbers(value: float, expected: float) -> None:
    assert safe_float(value) == pytest.approx(expected)


# ── safe_float: locale decimal/thousand conventions ──────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # European decimal-comma with dot thousands.
        ("1.234,56", 1234.56),
        # US decimal-dot with comma thousands.
        ("1,234.56", 1234.56),
        # Single decimal-comma (de_DE / es_ES / fr_FR / pt_PT).
        ("42,5", 42.5),
        ("1250,75", 1250.75),
        # Multi-comma -> US thousands, no decimals.
        ("1,234,567", 1234567.0),
        # Multi-dot -> DACH thousands, no decimals.
        ("1.234.567", 1234567.0),
        # Canonical single-dot decimal.
        ("185.00", 185.0),
        # Whitespace thousands separators (incl. NBSP / narrow NBSP).
        ("1 234,56", 1234.56),
        ("8 450,00", 8450.0),
        ("1 234,56", 1234.56),
        ("1 234,56", 1234.56),
        # Plain integer string.
        ("100", 100.0),
    ],
)
def test_safe_float_locale_conventions(text: str, expected: float) -> None:
    assert safe_float(text) == pytest.approx(expected)


# ── safe_float: sign prefix + trailing suffix ────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("-3,5", -3.5),
        ("+42", 42.0),
        ("- 3,5", -3.5),  # space after sign is stripped
        # Trailing currency / unit suffix is dropped.
        ("150,00 EUR", 150.0),
        ("3.0 m", 3.0),
        ("1.234,56 USD", 1234.56),
        ("12 pcs", 12.0),
    ],
)
def test_safe_float_sign_and_suffix(text: str, expected: float) -> None:
    assert safe_float(text) == pytest.approx(expected)


# ── safe_float: rejected / default-returning inputs ──────────────────────


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "N/A",
        "abc",
        "EUR",  # no leading digit
        "-",  # sign only
        True,  # bool is an int subclass - must NOT count as 1
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_safe_float_returns_default_for_uncoercible(value: object) -> None:
    sentinel = 9.9
    assert safe_float(value, default=sentinel) == pytest.approx(sentinel)
    # And the documented 0.0 default when none is supplied.
    assert safe_float(value) == pytest.approx(0.0)


def test_safe_float_bool_not_treated_as_int() -> None:
    """``True``/``False`` are ints in Python; a numeric column must not read
    them as 1/0 - that would silently turn a stray boolean cell into money."""
    assert safe_float(True, default=-1.0) == pytest.approx(-1.0)
    assert safe_float(False, default=-1.0) == pytest.approx(-1.0)


# ── parse_numeric_cell: strict spreadsheet semantics ─────────────────────


@pytest.mark.parametrize(
    "blank",
    [None, "", "   ", "\t"],
)
def test_parse_numeric_cell_blank_is_zero_no_error(blank: object) -> None:
    """A blank cell is a legitimate 0.0 with NO error (the column was empty)."""
    value, error = parse_numeric_cell(blank)
    assert value == pytest.approx(0.0)
    assert error is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("42,5", 42.5),
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("185.00 EUR", 185.0),
        ("-3,5", -3.5),
    ],
)
def test_parse_numeric_cell_parses_locale_numbers(text: str, expected: float) -> None:
    value, error = parse_numeric_cell(text)
    assert error is None
    assert value == pytest.approx(expected)


def test_parse_numeric_cell_native_numbers() -> None:
    assert parse_numeric_cell(42) == (42.0, None)
    assert parse_numeric_cell(3.5) == (3.5, None)


@pytest.mark.parametrize(
    "value",
    ["abc", "N/A", "1,2,3.4.5", "--5"],
)
def test_parse_numeric_cell_uncoercible_reports_error(value: str) -> None:
    """A non-blank cell that can't be coerced returns (None, message) - the
    import loop surfaces a per-row diagnostic instead of zero-filling."""
    parsed, error = parse_numeric_cell(value)
    assert parsed is None
    assert error is not None and value in error


def test_parse_numeric_cell_bool_is_an_error() -> None:
    parsed, error = parse_numeric_cell(True)
    assert parsed is None
    assert error is not None and "boolean" in error


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_parse_numeric_cell_non_finite_is_an_error(value: float) -> None:
    parsed, error = parse_numeric_cell(value)
    assert parsed is None
    assert error is not None


def test_parse_numeric_cell_distinguishes_blank_from_garbage() -> None:
    """The core contract: blank -> 0.0/None; garbage -> None/error. The two
    paths must never collapse (a blank quantity is valid, 'abc' is a defect)."""
    blank_value, blank_error = parse_numeric_cell("")
    garbage_value, garbage_error = parse_numeric_cell("abc")
    assert (blank_value, blank_error) == (0.0, None)
    assert garbage_value is None and garbage_error is not None


# ── decode_text_bytes: codec probe order ─────────────────────────────────


def test_decode_text_bytes_prefers_utf8_bom() -> None:
    text = "Wände café"
    decoded, enc = decode_text_bytes(text.encode("utf-8-sig"))
    assert decoded == text
    assert enc == "utf-8-sig"


def test_decode_text_bytes_plain_utf8() -> None:
    """Plain UTF-8 (no BOM) still decodes correctly. The ``utf-8-sig`` codec
    accepts BOM-less UTF-8 too, so as the first probe it claims the win - the
    important guarantee is the round-tripped TEXT, not which UTF-8 variant
    name is reported."""
    text = "Béton armé · Cyrillic щит"
    decoded, enc = decode_text_bytes(text.encode("utf-8"))
    assert decoded == text
    assert enc in ("utf-8-sig", "utf-8")


def test_decode_text_bytes_falls_back_to_cp1252() -> None:
    """DACH / LATAM CSV + BC3 files ship CP1252; bytes that are not valid
    UTF-8 must decode losslessly through the CP1252 fallback."""
    text = "Wände café Mörtel"
    raw = text.encode("cp1252")
    # Sanity: this byte sequence is genuinely not valid UTF-8 (so the probe
    # has to fall through past utf-8-sig and utf-8).
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    decoded, enc = decode_text_bytes(raw)
    assert decoded == text
    assert enc == "cp1252"


def test_decode_text_bytes_latin1_is_last_resort() -> None:
    """Latin-1 maps every byte, so it must come LAST in the probe order or it
    would shadow legitimate UTF-8. Confirm the default order ends with it."""
    assert DEFAULT_ENCODINGS[-1] == "latin-1"
    assert DEFAULT_ENCODINGS[0] == "utf-8-sig"


def test_decode_text_bytes_ascii_roundtrip() -> None:
    decoded, enc = decode_text_bytes(b"Pos,Description\n0010,Wall\n")
    assert decoded.startswith("Pos,Description")
    assert enc == "utf-8-sig"  # first codec that succeeds for plain ASCII


def test_decode_text_bytes_raises_when_no_codec_matches() -> None:
    """With a restricted, strict-only codec set that can't decode the bytes,
    the helper re-raises the underlying UnicodeDecodeError (it never returns
    mojibake silently)."""
    raw = "café".encode("cp1252")  # 0xe9 - invalid as UTF-8
    with pytest.raises(UnicodeDecodeError):
        decode_text_bytes(raw, encodings=("utf-8",))


def test_encoding_module_exposes_pure_helpers() -> None:
    """Guard: the parser module stays a self-contained, side-effect-free unit.

    It must NOT bind an ``app.database`` engine (the importer fast-paths and
    this very test file rely on importing it without a live PostgreSQL). Re-
    importing is cheap and idempotent; the module exposes the three documented
    helpers and nothing engine-shaped.
    """
    import importlib

    mod = importlib.import_module("app.modules.boq.importers._encoding")
    assert callable(mod.safe_float)
    assert callable(mod.parse_numeric_cell)
    assert callable(mod.decode_text_bytes)
    # No DB engine / session leaked into the parser namespace.
    assert not hasattr(mod, "engine")
    assert not hasattr(mod, "async_session_factory")


def test_safe_float_nan_helper_consistency() -> None:
    """``parse_numeric_cell`` is built on ``safe_float`` with a NaN sentinel;
    a math.isnan round-trip documents that contract stays intact."""
    assert math.isnan(safe_float("not-a-number", default=float("nan")))
    assert not math.isnan(safe_float("42,5", default=float("nan")))
