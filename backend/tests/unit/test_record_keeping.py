# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How long a country makes a business keep its records, and in which language.

Saudi Arabia is the first country in the table: VAT records six years from the
end of the tax period, capital asset records for the adjustment period plus
five years from acquisition, real estate records fifteen years in all cases,
and every record and invoice in Arabic, with Arabic the authoritative text.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app.core.record_keeping import (
    LANGUAGE_REQUIREMENTS,
    RETENTION_RULES,
    language_requirement,
    retain_until,
    retention_rule,
    validate_tables,
)


def test_the_shipped_tables_are_sound() -> None:
    assert validate_tables(RETENTION_RULES, LANGUAGE_REQUIREMENTS) == []


def test_saudi_retention_periods() -> None:
    general = retention_rule("SA", "general")
    real_estate = retention_rule("SA", "real_estate")
    capital = retention_rule("SA", "capital_assets")
    assert general is not None and general.years == 6 and general.starts_from == "end_of_tax_period"
    assert real_estate is not None and real_estate.years == 15
    assert capital is not None and capital.years == 5 and capital.plus_adjustment_period is True
    assert capital.starts_from == "acquisition"


def test_the_retention_date_is_counted_from_the_right_day() -> None:
    general = retention_rule("SA", "general")
    assert general is not None
    assert retain_until(general, date(2026, 3, 31)) == date(2032, 3, 31)
    real_estate = retention_rule("SA", "real_estate")
    assert real_estate is not None
    assert retain_until(real_estate, date(2024, 2, 29)) == date(2039, 2, 28)


def test_a_capital_asset_needs_its_adjustment_period_to_be_counted() -> None:
    capital = retention_rule("SA", "capital_assets")
    assert capital is not None
    assert retain_until(capital, date(2026, 1, 15)) is None
    assert retain_until(capital, date(2026, 1, 15), adjustment_period_years=6) == date(2037, 1, 15)


def test_an_unknown_country_or_class_answers_none() -> None:
    assert retention_rule("DE", "general") is None
    assert retention_rule("SA", "payroll") is None
    assert language_requirement("DE") is None


def test_saudi_records_and_invoices_are_in_arabic() -> None:
    rule = language_requirement("sa")
    assert rule is not None
    assert rule.required_language == "ar"
    assert rule.authoritative_language == "ar"
    assert rule.other_languages_allowed is True
    assert {"tax_invoice", "records"} <= set(rule.documents)


@pytest.mark.parametrize("field", ["legal_reference", "source_url"])
def test_a_rule_without_its_source_is_refused(field: str) -> None:
    broken = replace(RETENTION_RULES[0], **{field: ""})
    assert validate_tables((broken,), LANGUAGE_REQUIREMENTS) != []
