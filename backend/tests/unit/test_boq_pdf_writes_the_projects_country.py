# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A BOQ PDF is written in its project's country: separators, date, labels, paper.

Each case pairs the right answer with the one the generator used to print:

* An Irish euro bill printed German separators, because the currency alone
  chose them. It now prints ``123,456.78 EUR``.
* A hryvnia bill printed American separators; it is now spaced, and its labels
  are Ukrainian when the project locale is.
* A Russian bill printed its labels in Latin transliteration ("SMETNYJ
  RASCHET"); they are Cyrillic now, through the bundled Unicode face.
* The summary report (the writer for bills over 500 positions) printed English
  whatever the locale and laid a Letter page out with A4 frames.
* A percentage on a zero-decimal currency's bill was rounded to whole units.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pypdf
import pytest
from reportlab.lib.pagesizes import A4, LETTER

from app.core.regional_format import NBSP, SWISS_APOSTROPHE, format_date
from app.modules.boq.pdf_export import (
    _PDF_LABELS,
    _build_boq_table,
    _build_cover_page,
    _build_styles,
    _fmt,
    _fmt_currency,
    _get_pdf_labels,
    _status_label,
    _tax_label,
    _zero_tax_fallback_label,
    generate_boq_pdf,
    generate_boq_pdf_simple,
)

DIRECT = Decimal("123456.78")
OVERHEAD = Decimal("12345.68")


def _markup(name: str, category: str, percentage: float, amount: Decimal) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        markup_type="percentage",
        category=category,
        percentage=percentage,
        fixed_amount=Decimal("0"),
        apply_to="cumulative",
        sort_order=0,
        is_active=True,
        amount=amount,
    )


def _boq(currency: str = "EUR", markups: list[Any] | None = None, status: str = "draft") -> Any:
    markups = markups if markups is not None else [_markup("Overhead", "overhead", 10.0, OVERHEAD)]
    net = DIRECT + sum((Decimal(str(m.amount)) for m in markups), Decimal("0"))
    position = SimpleNamespace(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        ordinal="01.001",
        description="Concrete wall",
        unit="m3",
        quantity=Decimal("100"),
        unit_rate=Decimal("1234.5678"),
        total=DIRECT,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Country BOQ",
        description="",
        status=status,
        currency=currency,
        sections=[
            SimpleNamespace(
                id=uuid.uuid4(), ordinal="01", description="Structure", positions=[position], subtotal=DIRECT
            )
        ],
        positions=[],
        direct_cost=DIRECT,
        markups=markups,
        net_total=net,
        grand_total=net,
    )


def _cell_text(cell: Any) -> str:
    return getattr(cell, "text", cell if isinstance(cell, str) else "")


def _texts(flowables: list[Any]) -> list[str]:
    """Every paragraph and table cell's text, one level of nesting deep."""
    out: list[str] = []
    for flowable in flowables:
        if hasattr(flowable, "text"):
            out.append(flowable.text)
        for row in getattr(flowable, "_cellvalues", []) or []:
            for cell in row:
                out.append(_cell_text(cell))
                for inner in getattr(cell, "_cellvalues", []) or []:
                    out.extend(_cell_text(c) for c in inner)
    return out


def _pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(data)).pages)


def _page_size(data: bytes) -> tuple[float, float]:
    box = pypdf.PdfReader(io.BytesIO(data)).pages[0].mediabox
    return float(box.width), float(box.height)


# ── Separators ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("currency", "country", "expected", "old"),
    [
        ("EUR", "IE", "123,456.78 EUR", "123.456,78 EUR"),
        ("EUR", "FR", f"123{NBSP}456,78 EUR", "123.456,78 EUR"),
        ("UAH", "UA", f"123{NBSP}456,78 UAH", "123,456.78 UAH"),
        ("UAH", "", f"123{NBSP}456,78 UAH", "123,456.78 UAH"),
        ("CHF", "CH", f"123{SWISS_APOSTROPHE}456.78 CHF", None),
        ("GBP", "GB", "123,456.78 GBP", None),
        ("EUR", "DE", "123.456,78 EUR", None),
    ],
)
def test_the_amount_is_written_the_way_the_country_writes_it(
    currency: str, country: str, expected: str, old: str | None
) -> None:
    written = _fmt_currency(DIRECT, currency, country=country)
    assert written == expected
    if old is not None:
        assert written != old


@pytest.mark.parametrize(
    ("currency", "expected"),
    [("EUR", "123.456,78"), ("USD", "123,456.78"), ("RUB", "123.456,78"), ("INR", "1,23,456.78")],
)
def test_without_a_country_the_old_currency_answer_stands(currency: str, expected: str) -> None:
    assert _fmt(DIRECT, 2, currency) == expected


def test_a_percentage_on_a_zero_decimal_bill_keeps_its_fraction() -> None:
    """``Overhead (11%)`` for a 10.5 per cent markup is a different contract."""
    jp = _markup("Overhead", "overhead", 10.5, Decimal("1050"))
    rows = _texts(_build_boq_table(_boq("JPY", [jp]), "JPY", _build_styles(), "metric", "JP"))
    assert any("Overhead (10.5%)" in t for t in rows), rows
    assert not any("Overhead (11%)" in t for t in rows)
    # The money itself stays whole yen.
    assert any("1,050 JPY" in t for t in rows)


def test_a_hungarian_tax_rate_is_written_with_a_decimal_comma_and_kept() -> None:
    afa = _markup("ÁFA", "tax", 27.0, Decimal("33333"))
    assert _tax_label(afa, "HUF", "HU") == "ÁFA (27,00%)"
    # Without a country the forint fell to the old currency table: 27.00 kept.
    assert _tax_label(afa, "HUF") == "ÁFA (27,00%)"


def test_the_irish_table_prints_its_totals_irish_style() -> None:
    vat = _markup("VAT", "tax", 13.5, Decimal("18333.33"))
    texts = _texts(_build_boq_table(_boq("EUR", [vat]), "EUR", _build_styles(), "metric", "IE"))
    assert any("123,456.78" in t for t in texts)
    assert any("VAT (13.50%)" in t for t in texts)
    assert not any("123.456,78" in t for t in texts)


# ── Labels ───────────────────────────────────────────────────────────────────


def test_every_locale_carries_every_english_key_or_inherits_it() -> None:
    english = set(_PDF_LABELS["en"])
    for locale in _PDF_LABELS:
        assert set(_get_pdf_labels(locale)) == english, locale


@pytest.mark.parametrize("locale", ["ru", "uk"])
def test_cyrillic_locales_are_written_in_cyrillic(locale: str) -> None:
    labels = _get_pdf_labels(locale)
    for key in ("cost_estimate", "net_total", "gross_total", "description", "markups"):
        assert any("Ѐ" <= ch <= "ӿ" for ch in labels[key]), (locale, key, labels[key])
    assert "SMETNYJ" not in labels["cost_estimate"]


def test_ukrainian_is_not_russian() -> None:
    uk, ru = _get_pdf_labels("uk"), _get_pdf_labels("ru")
    assert uk["cost_estimate"] == "КОШТОРИСНИЙ РОЗРАХУНОК"
    assert uk["net_total"] == "Разом без ПДВ:"
    assert uk["cost_estimate"] != ru["cost_estimate"]


def test_accents_are_back() -> None:
    assert _get_pdf_labels("de")["cost_estimate"] == "KOSTENSCHÄTZUNG"
    assert _get_pdf_labels("fr")["cost_estimate"] == "ESTIMATION DES COÛTS"
    assert _get_pdf_labels("pt")["cost_estimate"] == "ORÇAMENTO"
    assert _get_pdf_labels("tr")["cost_estimate"] == "MALİYET TAHMİNİ"


def test_the_markups_row_is_translated_and_english_is_unchanged() -> None:
    assert _get_pdf_labels("en")["markups"] == "Markups (excl. tax):"
    rows = _texts(_build_cover_page(_boq(), "P", "EUR", "", _build_styles(), "DE", labels=_get_pdf_labels("de")))
    assert "Zuschläge (ohne MwSt.):" in rows
    assert "Markups (excl. tax):" not in rows


@pytest.mark.parametrize(
    ("status", "locale", "expected"),
    [
        ("draft", "en", "Draft"),
        ("final", "en", "Final"),
        ("final", "de", "Freigegeben"),
        ("draft", "uk", "Чернетка"),
        (None, "en", "Draft"),
        ("something_else", "en", "Something_else"),
    ],
)
def test_the_status_is_translated(status: str | None, locale: str, expected: str) -> None:
    assert _status_label(status, _get_pdf_labels(locale)) == expected


@pytest.mark.parametrize(("country", "word"), [("UA", "PDV"), ("HU", "ÁFA"), ("CH", "MWST"), ("IE", "VAT")])
def test_an_untaxed_bill_names_the_countrys_tax(country: str, word: str) -> None:
    assert _zero_tax_fallback_label(country) == f"{word} 0%:"


# ── Dates ────────────────────────────────────────────────────────────────────


def test_the_cover_date_is_in_the_countrys_order() -> None:
    today = datetime.now(tz=UTC)
    rows = _texts(_build_cover_page(_boq(), "P", "EUR", "", _build_styles(), "IE"))
    assert format_date(today, "IE") in rows
    if today.day != today.month:
        # The German order the cover used for everyone is not the Irish one.
        assert today.strftime("%d.%m.%Y") not in rows


# ── End to end ───────────────────────────────────────────────────────────────


def test_a_ukrainian_bill_renders_in_ukrainian_with_spaced_hryvnias() -> None:
    data = generate_boq_pdf(_boq("UAH"), project_name="Київ", currency="UAH", country_code="UA", locale="uk")
    text = _pdf_text(data)
    assert "КОШТОРИСНИЙ РОЗРАХУНОК" in text
    compact = "".join(text.split())
    assert "123456,78UAH" in compact
    assert "123,456.78" not in text


def test_the_summary_report_is_translated() -> None:
    data = generate_boq_pdf_simple(_boq("UAH"), project_name="P", currency="UAH", country_code="UA", locale="uk")
    text = _pdf_text(data)
    assert "Зведений звіт" in text
    assert "Зведення витрат" in text
    assert "Summary Report" not in text
    assert "Cost Summary" not in text


def test_the_summary_report_in_english_reads_as_before() -> None:
    data = generate_boq_pdf_simple(_boq("USD"), project_name="P", currency="USD")
    text = _pdf_text(data)
    assert "Summary Report" in text
    assert "positions (full detail omitted for performance)" in text
    assert "Cost Summary" in text


@pytest.mark.parametrize("writer", [generate_boq_pdf, generate_boq_pdf_simple])
def test_letter_paper_is_letter_paper(writer: Any) -> None:
    data = writer(_boq("USD"), project_name="P", currency="USD", country_code="US", page_format="LETTER")
    assert _page_size(data) == pytest.approx(LETTER, abs=0.5)
    data = writer(_boq("EUR"), project_name="P", currency="EUR", country_code="DE")
    assert _page_size(data) == pytest.approx(A4, abs=0.5)
