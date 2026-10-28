# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠User-facing output reads from the platform catalogue in every interface language.

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
from app.modules.property_dev.intl import explain_figure, localize_status, localize_term
from app.modules.reporting import intl as rep


def test_every_explainer_offers_every_interface_language() -> None:
    assert set(rep.SUPPORTED_LOCALES) == set(SUPPORTED_LOCALES)


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_language_has_number_and_date_conventions(locale: str) -> None:
    style = number_style_for_language(locale)
    assert style.decimal != style.group
    pattern = date_format_for_language(locale)
    assert {"YYYY", "MM", "DD"} <= {tok for tok in ("YYYY", "MM", "DD") if tok in pattern}


def test_money_follows_the_language_not_just_en_and_de() -> None:
    assert format_money("1234.5", "EUR", "en") == "\u20ac 1,234.50"
    assert format_money("1234.5", "EUR", "de") == "1.234,50 \u20ac"
    assert format_money("1234.5", "EUR", "fr") == "1\u00a0234,50 \u20ac"
    assert format_money("1234.5", "EUR", "xx") == "\u20ac 1,234.50"


def test_catalogue_table_covers_every_language_and_falls_back_to_english() -> None:
    table = catalogue_table("property_dev.term", ("gross_development_value", "residual_land_value"))
    assert set(table) == set(SUPPORTED_LOCALES)
    assert table["de"]["gross_development_value"] == "Bruttoentwicklungswert"
    assert table["en"]["residual_land_value"]
    by_key = catalogue_table("property_dev.term", ("gross_development_value",), by_key=True)
    assert set(by_key["gross_development_value"]) == set(SUPPORTED_LOCALES)
    assert lookup("property_dev.term.no_such_key", "de") is None


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
    prefixes = ("property_dev.term.",)
    for locale in ("de", "ru"):
        bundle = get_all_translations(locale)
        for key in en:
            if key.startswith(prefixes):
                assert key in bundle, f"{locale} lacks {key}"
    assert t("ai.advisor.not_configured", "de").startswith("KI nicht")
