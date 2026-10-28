# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the methodology PDF exporter.

``app.modules.methodology.pdf_export.generate_methodology_pdf`` turns the
data dict produced by ``MethodologyService.build_export_data`` into a
client-facing PDF. It is a pure function (dict -> bytes, no DB, no I/O) so
it is exercised directly here without the embedded PostgreSQL engine.

These pin the contract that matters for a deliverable a customer prints:

1. a representative estimate renders to a well-formed PDF (``%PDF`` magic,
   ``%%EOF`` trailer, non-trivial size, two-pass page counting succeeds);
2. **injection safety (BUG-PDF01 / BUG-PDF02)** - a methodology name / step
   label / prepared-by string carrying ReportLab inline markup
   (``<font ...>``) or a malformed tag (``<img onerror=...>``) must neither
   crash ReportLab's paraparser nor render as markup. ``_safe_para``
   ``html.escape``s every dynamic value, so the build must SUCCEED and
   return valid bytes rather than raising;
3. a methodology with no quantities still exports a valid (zeroed) document;
4. the money / format helpers (locale separators, Decimal coercion, the
   currency-code suffix, the escaping primitive) behave as documented.
"""

from __future__ import annotations

from decimal import Decimal

from reportlab.lib.styles import getSampleStyleSheet

from app.modules.methodology.pdf_export import (
    _fmt,
    _fmt_currency,
    _safe_para,
    _to_decimal,
    generate_methodology_pdf,
)


def _sample_data(**overrides: object) -> dict:
    """A faithful stand-in for ``build_export_data``'s output dict."""
    data: dict = {
        "project_name": "Riverside Tower",
        "methodology_name": "Uzbekistan SMR (machinery in base)",
        "methodology_slug": "uz-smr",
        "currency": "EUR",
        "decimals": 2,
        "direct_total": "1000000.00",
        "markup_total": "235000.00",
        "grand_total": "1235000.00",
        "steps": [
            {
                "key": "overheads",
                "label": "Overheads",
                "category": "overhead",
                "kind": "percentage",
                "rate": "12.5",
                "base_amount": "1000000.00",
                "amount": "125000.00",
                "running_total": "1125000.00",
            },
            {
                "key": "profit",
                "label": "Profit",
                "category": "profit",
                "kind": "percentage",
                "rate": "5",
                "base_amount": "1125000.00",
                "amount": "56250.00",
                "running_total": "1181250.00",
            },
            {
                "key": "vat",
                "label": "VAT",
                "category": "tax",
                "kind": "percentage",
                "rate": "12",
                "base_amount": "1181250.00",
                "amount": "141750.00",
                "running_total": "1323000.00",
            },
        ],
        "bases": {"direct_cost": "1000000.00", "labour": "400000.00"},
        "composites": {"works_base": "1100000.00"},
        "prepared_by": "Cost Engineer",
    }
    data.update(overrides)
    return data


# ── 1. Happy path ──────────────────────────────────────────────────────────


def test_generates_well_formed_pdf() -> None:
    out = generate_methodology_pdf(_sample_data())
    assert isinstance(out, bytes)
    assert out.startswith(b"%PDF")  # PDF magic
    assert b"%%EOF" in out  # trailer present -> build completed
    assert len(out) > 1500  # a real multi-page document, not a stub


def test_currency_and_decimals_variants_render() -> None:
    # CHF apostrophe grouping, JPY zero-decimal, and a blank currency must all
    # render without error (the formatter is locale-aware + empty-safe).
    for currency, decimals in (("CHF", 2), ("JPY", 0), ("", 2)):
        out = generate_methodology_pdf(_sample_data(currency=currency, decimals=decimals))
        assert out.startswith(b"%PDF")


# ── 2. Injection safety (BUG-PDF01 / BUG-PDF02) ──────────────────────────────


def test_markup_in_dynamic_fields_does_not_crash_or_inject() -> None:
    """A name / label / prepared-by full of markup must not break the build.

    Un-escaped, ``<img src=x onerror=...>`` makes ReportLab's paraparser
    raise and ``<font color=...>`` renders as styled markup. ``_safe_para``
    escapes every dynamic value, so the document still builds and returns
    valid PDF bytes.
    """
    hostile = '<img src=x onerror=alert(1)><font color="white">hidden</font> & <b>x</b>'
    data = _sample_data(
        project_name=hostile,
        methodology_name=hostile,
        prepared_by=hostile,
    )
    data["steps"][0]["label"] = hostile
    data["steps"][0]["category"] = hostile
    data["bases"] = {hostile: "1.00"}

    out = generate_methodology_pdf(data)
    assert out.startswith(b"%PDF")
    assert b"%%EOF" in out


def test_safe_para_escapes_html_metacharacters() -> None:
    style = getSampleStyleSheet()["Normal"]
    para = _safe_para('<b>bold</b> & "quoted" <tag>', style)
    # ReportLab stores the source text on the flowable; it must be escaped so
    # the paraparser sees inert entities, not live markup.
    assert "&lt;b&gt;" in para.text
    assert "&amp;" in para.text
    assert "&quot;" in para.text
    assert "<b>" not in para.text


def test_safe_para_handles_none_and_non_str() -> None:
    style = getSampleStyleSheet()["Normal"]
    assert _safe_para(None, style).text == ""
    assert _safe_para(1234, style).text == "1234"


# ── 3. Zeroed / degenerate documents ─────────────────────────────────────────


def test_methodology_with_no_steps_still_exports() -> None:
    data = _sample_data(
        steps=[],
        bases={},
        composites={},
        markup_total="0",
        grand_total="1000000.00",
        prepared_by="",
    )
    out = generate_methodology_pdf(data)
    assert out.startswith(b"%PDF")


def test_missing_optional_keys_are_tolerated() -> None:
    # An almost-empty dict (the compute layer guarantees the totals, but be
    # defensive about everything else) must not raise.
    out = generate_methodology_pdf({"currency": "USD", "decimals": 2})
    assert out.startswith(b"%PDF")


# ── 4. Money / format helpers ────────────────────────────────────────────────


def test_fmt_locale_separators() -> None:
    assert _fmt("1234567.5", 2, "EUR") == "1.234.567,50"
    assert _fmt("1234567.5", 2, "CHF") == "1'234'567.50"
    assert _fmt("1234567.5", 2, "USD") == "1,234,567.50"
    assert _fmt("1234567.5", 2, "") == "1,234,567.50"


def test_fmt_zero_decimals() -> None:
    assert _fmt("1234.99", 0, "JPY") == "1,235"


def test_fmt_currency_appends_code_and_is_empty_safe() -> None:
    assert _fmt_currency("1000", "EUR", 2) == "1.000,00 EUR"
    # No currency -> no dangling space.
    assert _fmt_currency("1000", "", 2) == "1,000.00"


def test_to_decimal_coercion() -> None:
    assert _to_decimal("1234.56") == Decimal("1234.56")
    assert _to_decimal(Decimal("7")) == Decimal("7")
    assert _to_decimal(42) == Decimal("42")
    # Missing / unparseable / non-finite all collapse to 0 (never raise).
    assert _to_decimal(None) == Decimal(0)
    assert _to_decimal("") == Decimal(0)
    assert _to_decimal("not-a-number") == Decimal(0)
    assert _to_decimal("Infinity") == Decimal(0)
    assert _to_decimal("NaN") == Decimal(0)
