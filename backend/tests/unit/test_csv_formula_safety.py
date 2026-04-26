"""Unit tests for :mod:`app.core.csv_safety` — CSV formula-injection defence.

These tests pin down the contract of :func:`neutralise_formula` so that
future refactors cannot silently weaken the BUG-CSV-INJECTION fix:

* every dangerous prefix (``= + - @ \\t \\r``) gets an apostrophe added
* benign content round-trips byte-for-byte
* non-string types (``None``, ``int``, ``float``, ``Decimal``) pass through
* only the *first* character is inspected — a ``=`` later in the string is
  fine because Excel will not treat the whole cell as a formula
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.csv_safety import neutralise_formula


# ── Padding the dangerous-prefix characters ────────────────────────────


def test_neutralise_formula_pads_equals() -> None:
    assert neutralise_formula("=SUM(A1:B1)") == "'=SUM(A1:B1)"


def test_neutralise_formula_pads_plus() -> None:
    assert neutralise_formula("+1+1") == "'+1+1"


def test_neutralise_formula_pads_minus() -> None:
    # Negative-looking text that is actually a formula payload.
    assert neutralise_formula("-2+3") == "'-2+3"


def test_neutralise_formula_pads_at() -> None:
    # Old-style Lotus 1-2-3 syntax that Excel still honours.
    assert neutralise_formula("@SUM(A1:A5)") == "'@SUM(A1:A5)"


def test_neutralise_formula_pads_tab() -> None:
    assert neutralise_formula("\t=cmd|'/c calc'!A0") == "'\t=cmd|'/c calc'!A0"


def test_neutralise_formula_pads_carriage_return() -> None:
    assert neutralise_formula("\r=HYPERLINK(\"http://evil\")") == "'\r=HYPERLINK(\"http://evil\")"


def test_neutralise_formula_pads_real_world_rce_payload() -> None:
    # Canonical CVE-style payload from the OWASP CSV-injection cheat sheet.
    payload = "=cmd|'/c calc'!A0"
    assert neutralise_formula(payload) == "'" + payload


# ── Benign content passes through unchanged ────────────────────────────


def test_neutralise_formula_passes_through_safe() -> None:
    assert neutralise_formula("Concrete C30/37") == "Concrete C30/37"


def test_neutralise_formula_passes_through_unicode() -> None:
    assert neutralise_formula("Stahlbeton — Wand") == "Stahlbeton — Wand"


def test_neutralise_formula_passes_through_numbers_in_string() -> None:
    # Leading digit is safe.
    assert neutralise_formula("330 — Außenwände") == "330 — Außenwände"


# ── Edge cases: empty / None / numeric types ───────────────────────────


def test_neutralise_formula_handles_empty_string() -> None:
    assert neutralise_formula("") == ""


def test_neutralise_formula_handles_none() -> None:
    assert neutralise_formula(None) is None


def test_neutralise_formula_handles_int() -> None:
    assert neutralise_formula(42) == 42


def test_neutralise_formula_handles_negative_int() -> None:
    # ``int`` is not a string — it must pass through, otherwise legitimate
    # negative quantities would be corrupted.
    assert neutralise_formula(-5) == -5


def test_neutralise_formula_handles_float() -> None:
    assert neutralise_formula(3.14) == 3.14


def test_neutralise_formula_handles_decimal() -> None:
    d = Decimal("123.456")
    assert neutralise_formula(d) is d


def test_neutralise_formula_handles_bool() -> None:
    # ``bool`` is an int subclass — also not a string.
    assert neutralise_formula(True) is True


# ── Only the leading character matters ─────────────────────────────────


def test_neutralise_formula_only_first_char() -> None:
    """A dangerous character mid-string is harmless — Excel only evaluates
    cells whose *first* character starts a formula."""
    assert neutralise_formula("=in middle=") == "'=in middle="


def test_neutralise_formula_dangerous_char_after_text_is_safe() -> None:
    assert neutralise_formula("price = 100") == "price = 100"


def test_neutralise_formula_dangerous_char_after_space_is_safe() -> None:
    # Leading space — not in our dangerous list — passes through.
    assert neutralise_formula(" =SUM(A1)") == " =SUM(A1)"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_neutralise_formula_all_dangerous_prefixes_parametrised(prefix: str) -> None:
    payload = f"{prefix}injected"
    out = neutralise_formula(payload)
    assert isinstance(out, str)
    assert out.startswith("'")
    assert out == "'" + payload
