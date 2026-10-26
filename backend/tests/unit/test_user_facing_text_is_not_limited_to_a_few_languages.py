# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""User-facing output reads from the platform catalogue in every interface language.

These places used to hold their own en/de/ru (or en/de) tables, so a reader in
any other language got English. They now resolve through ``app.core.i18n``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.i18n import SUPPORTED_LOCALES, catalogue_table, get_all_translations, lookup, t
from app.core.money import format_money
from app.core.regional_format import date_format_for_language, number_style_for_language
from app.core.validation.dsl.nl_builder import parse_nl_to_dsl
from app.modules.einvoice import pdf_translations as inv
from app.modules.property_dev.intl import explain_figure, localize_status, localize_term
from app.modules.reporting import intl as rep
from app.modules.reporting import report_translations as rt


def test_every_document_catalogue_offers_every_interface_language() -> None:
    assert set(rt.SUPPORTED_REPORT_LOCALES) == set(SUPPORTED_LOCALES)
    assert set(inv.SUPPORTED_PDF_LOCALES) == set(SUPPORTED_LOCALES)
    assert set(rep.SUPPORTED_LOCALES) == set(SUPPORTED_LOCALES)


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_language_has_number_and_date_conventions(locale: str) -> None:
    style = number_style_for_language(locale)
    assert style.decimal != style.group
    pattern = date_format_for_language(locale)
    assert {"YYYY", "MM", "DD"} <= {tok for tok in ("YYYY", "MM", "DD") if tok in pattern}


@pytest.mark.parametrize(
    ("locale", "money", "number", "day"),
    [
        ("en", "1,240,000.50", "1.5", "2026-04-15"),
        ("de", "1.240.000,50", "1,5", "15.04.2026"),
        ("hu", "1\u00a0240\u00a0000,50", "1,5", "2026.04.15."),
        ("ja", "1,240,000.50", "1.5", "2026/04/15"),
        ("hi", "12,40,000.50", "1.5", "15/04/2026"),
    ],
)
def test_the_invoice_page_formats_for_the_reader_language(locale: str, money: str, number: str, day: str) -> None:
    assert inv.fmt_money(Decimal("1240000.5"), "EUR", locale) == money
    assert inv.fmt_number(Decimal("1.5"), locale) == number
    assert inv.fmt_date("2026-04-15", locale) == day


@pytest.mark.parametrize("locale", ["fr", "ja", "el", "uk", "ar", "vi"])
def test_the_invoice_labels_come_from_the_catalogue(locale: str) -> None:
    # A language still waiting for its translation reads English per key, never a raw key.
    assert inv.tr(locale, "amount_due")
    assert not inv.tr(locale, "amount_due").startswith("einvoice.")


def test_money_follows_the_language_not_just_en_and_de() -> None:
    assert format_money("1234.5", "EUR", "en") == "\u20ac 1,234.50"
    assert format_money("1234.5", "EUR", "de") == "1.234,50 \u20ac"
    assert format_money("1234.5", "EUR", "fr") == "1\u00a0234,50 \u20ac"
    assert format_money("1234.5", "EUR", "xx") == "\u20ac 1,234.50"


def test_catalogue_table_covers_every_language_and_falls_back_to_english() -> None:
    table = catalogue_table("reporting.field", ("budget", "actual"))
    assert set(table) == set(SUPPORTED_LOCALES)
    assert table["de"]["budget"] == "Budget"
    assert table["sw" if "sw" in table else "en"]["actual"] == "Actual"
    by_key = catalogue_table("reporting.field", ("budget",), by_key=True)
    assert set(by_key["budget"]) == set(SUPPORTED_LOCALES)
    assert lookup("reporting.field.no_such_key", "de") is None


def test_explainers_follow_the_language() -> None:
    assert rep.explain_report_total(Decimal("5"), line_count=2, locale="de").startswith("Berichtssumme:")
    assert rep.explain_top_n([1, 2], 3, locale="ru").startswith("\u0422\u043e\u043f 3")
    assert localize_term("profit_on_cost", "de") == "Gewinn auf Kosten"
    assert (
        localize_status("viable", "ru")
        == "\u0416\u0438\u0437\u043d\u0435\u0441\u043f\u043e\u0441\u043e\u0431\u043d\u044b\u0439"
    )
    assert explain_figure("profit_on_cost", "de").startswith("Entwicklergewinn")


def test_rule_builder_errors_and_hints_are_localized() -> None:
    import asyncio

    en = asyncio.run(parse_nl_to_dsl("", lang="en"))
    de = asyncio.run(parse_nl_to_dsl("", lang="de"))
    assert en.errors == ["Input is empty."]
    assert de.errors == ["Die Eingabe ist leer."]
    miss = asyncio.run(parse_nl_to_dsl("xyz qqq", lang="de"))
    assert miss.suggestions[0].startswith("Versuchen Sie:")


def test_migrated_label_tables_are_complete_in_en_de_ru() -> None:
    en = get_all_translations("en")
    prefixes = ("reporting.doc.", "reporting.section.", "reporting.field.", "einvoice.pdf.", "property_dev.term.")
    for locale in ("de", "ru"):
        bundle = get_all_translations(locale)
        for key in en:
            if key.startswith(prefixes):
                assert key in bundle, f"{locale} lacks {key}"
    assert t("ai.advisor.not_configured", "de").startswith("KI nicht")
