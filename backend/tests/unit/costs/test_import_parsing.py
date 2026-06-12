"""Unit tests for cost-import parsing helpers (audit fixes M1/m2 + zip guard).

Covers:
  1. ``_safe_float`` locale handling: a SINGLE comma is ALWAYS the decimal
     separator ("0,500" -> 0.5, "12,345" -> 12.345) while multi-group
     thousands ("1,234,567") and mixed comma+dot ("1,234.56", "1.234,56")
     keep working. The pre-fix behavior inflated European 3-decimal rates
     1000x by treating "12,345" as an English thousands group.
  2. ``_safe_float`` scientific notation: "1E+05" parses to 100000 instead
     of being mangled by the separator stripping; non-finite direct parses
     ("inf", "nan") still fall to the default.
  3. ``_validate_cost_upload`` zip-bomb gate: OOXML uploads whose declared
     UNCOMPRESSED payload or entry count exceeds the cap are rejected
     before openpyxl inflates anything; legacy OLE .xls (not a zip) passes
     through to the signature gate untouched.
"""

from __future__ import annotations

import io
import math
import zipfile

import pytest
from fastapi import HTTPException

import app.modules.costs.router as costs_router
from app.modules.costs.router import _safe_float, _validate_cost_upload

# ── _safe_float: comma handling (M1) ───────────────────────────────────────


def test_single_comma_three_decimals_is_decimal_separator() -> None:
    """European 3-decimal rates must NOT be inflated 1000x."""
    assert _safe_float("0,500") == 0.5
    assert _safe_float("12,345") == 12.345


def test_single_comma_two_decimals_is_decimal_separator() -> None:
    assert _safe_float("8 450,00") == 8450.0
    assert _safe_float("1250,75") == 1250.75


def test_multi_group_commas_are_thousands_separators() -> None:
    assert _safe_float("1,234,567") == 1234567.0


def test_comma_thousands_with_dot_decimal() -> None:
    assert _safe_float("1,234.56") == 1234.56


def test_dot_thousands_with_comma_decimal() -> None:
    assert _safe_float("1.234,56") == 1234.56


def test_currency_symbols_stripped_before_comma_logic() -> None:
    assert _safe_float("€ 0,500") == 0.5
    assert _safe_float("$1,234,567") == 1234567.0


def test_plain_numbers_and_passthrough() -> None:
    assert _safe_float("42") == 42.0
    assert _safe_float(3.5) == 3.5
    assert _safe_float(7) == 7.0


def test_unparseable_returns_default() -> None:
    assert _safe_float("N/A", default=0.0) == 0.0
    assert _safe_float("", default=1.5) == 1.5
    assert _safe_float(None, default=2.5) == 2.5
    assert math.isnan(_safe_float("N/A", default=math.nan))


# ── _safe_float: scientific notation (m2) ──────────────────────────────────


def test_scientific_notation_parses_directly() -> None:
    assert _safe_float("1E+05") == 100000.0
    assert _safe_float("1e3") == 1000.0
    assert _safe_float("-2.5e-2") == -0.025


def test_non_finite_direct_parse_falls_to_default() -> None:
    """'inf' / 'nan' are not rates - they must not leak through."""
    assert _safe_float("inf", default=0.0) == 0.0
    assert _safe_float("nan", default=0.0) == 0.0
    assert _safe_float("-inf", default=0.0) == 0.0


# ── _validate_cost_upload: zip-bomb gate ───────────────────────────────────


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def test_small_valid_zip_passes() -> None:
    content = _make_zip({"xl/workbook.xml": b"<workbook/>"})
    assert _validate_cost_upload(content, "catalog.xlsx") is False


def test_zip_uncompressed_size_over_cap_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Lower the cap so the test does not have to build a real 500 MB blob;
    # the gate reads the DECLARED file_size from the central directory.
    monkeypatch.setattr(costs_router, "_MAX_COST_ZIP_UNCOMPRESSED_BYTES", 1024)
    content = _make_zip({"xl/sheet1.xml": b"\x00" * 4096})
    with pytest.raises(HTTPException) as exc_info:
        _validate_cost_upload(content, "bomb.xlsx")
    assert exc_info.value.status_code == 413


def test_zip_entry_count_over_cap_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(costs_router, "_MAX_COST_ZIP_ENTRIES", 3)
    content = _make_zip({f"part{i}.xml": b"x" for i in range(4)})
    with pytest.raises(HTTPException) as exc_info:
        _validate_cost_upload(content, "bomb.xlsx")
    assert exc_info.value.status_code == 422


def test_ole_xls_is_not_a_zip_and_passes_signature_gate() -> None:
    """Legacy OLE .xls must reach the signature gate, not crash on BadZipFile."""
    ole_magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
    content = ole_magic + b"\x00" * 512
    assert _validate_cost_upload(content, "legacy.xls") is False
