# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egypt's VAT and its construction line price at the rate of the document's own date.

Read against the shipped seed file, never a fixture. The day that tells the
answers apart is 2025-07-18, when Law No. 157 of 2025 moved construction and
contracting works from a 5 percent schedule tax without input credit to the
standard 14 percent with it. Each window is checked on its last day and on the
first day of the next one, because a window that leaks one way prices
yesterday's certificate at tomorrow's rate.

Sources, read 2026-10-19: PwC Worldwide Tax Summaries - Egypt, other taxes;
EY Tax News 2025-1554 and 2025-2316; Andersen Egypt, "Subcontractors in Egypt".
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.tax import get_vat_rate
from app.modules.boq.markup_templates import (
    CONSTRUCTION_TIER_COUNTRIES,
    CONSTRUCTION_TIER_TAX_CODE,
    seeded_tax_line_names,
)
from app.modules.boq.service import _construction_tier_rate
from app.modules.i18n_foundation.seed import load_tax_seed_rows, tax_configuration_from_seed_row
from app.modules.i18n_foundation.tax_rules import resolve, row_from_mapping


def _rows():
    return [row_from_mapping(row) for row in load_tax_seed_rows()]


def _egypt():
    return [row for row in load_tax_seed_rows() if row["country_code"] == "EG"]


def _standard(on_date: str) -> str | None:
    outcome = resolve(_rows(), "EG", None, on_date)
    return outcome.combined_rate_pct if outcome.resolved else None


def _construction(on_date: str) -> str | None:
    return _construction_tier_rate(_rows(), "EG", "VAT_CONSTR", on_date, uuid.uuid4())


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        ("2016-09-07", None),
        ("2016-09-08", "13"),
        ("2017-06-30", "13"),
        ("2017-07-01", "14"),
        ("2025-07-17", "14"),
        ("2025-07-18", "14"),
        ("2026-10-19", "14"),
    ],
)
def test_the_standard_rate_on_each_side_of_its_change(on_date: str, expected: str | None) -> None:
    assert _standard(on_date) == expected


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        # The schedule tax on contracting works, which a bill of this date charged.
        ("2024-12-31", "5"),
        ("2025-07-17", "5"),
        # Law No. 157 of 2025: construction is charged the standard rate.
        ("2025-07-18", "14"),
        ("2026-10-19", "14"),
    ],
)
def test_a_construction_bill_is_charged_the_regime_of_its_date(on_date: str, expected: str) -> None:
    assert _construction(on_date) == expected


def test_the_change_is_the_one_date_where_standard_and_construction_part() -> None:
    """Before the change the two answers differ, after it they agree; a single row cannot say both."""
    assert (_standard("2025-07-17"), _construction("2025-07-17")) == ("14", "5")
    assert (_standard("2025-07-18"), _construction("2025-07-18")) == ("14", "14")


def test_egypt_is_a_construction_tier_country_reading_its_own_row() -> None:
    assert CONSTRUCTION_TIER_TAX_CODE["EG"] == "VAT_CONSTR"
    assert "157 of 2025" in CONSTRUCTION_TIER_COUNTRIES["EG"]


def test_an_egyptian_bill_gets_a_vat_line() -> None:
    """A DEFAULT-stack country with a seed row gets one tax line appended, named by the row."""
    assert seeded_tax_line_names()["EG"] == "VAT"


def test_the_core_table_agrees_with_the_seed_today() -> None:
    assert get_vat_rate("EG") == Decimal("0.14")
    assert get_vat_rate("EG", "zero") == Decimal("0.00")


def test_every_egyptian_row_says_where_it_was_read() -> None:
    rows = _egypt()
    assert len(rows) == 4
    for row in rows:
        source = row["metadata"]["source"]
        assert source["source_url"].startswith("https://")
        assert source["legal_reference"].strip()
        assert source["read_date"] == "2026-10-19"
        assert row["metadata"]["review"]["status"] in {"confirmed", "needs_expert_review"}
        assert set(row["tax_name_translations"]) == {"en", "ar"}


def test_the_schedule_tax_start_is_marked_for_expert_review_and_still_prices() -> None:
    """Flagged for review, not for confirmation: a pending confirmation would make the row resolve to nothing."""
    schedule = next(row for row in _egypt() if row["tax_code"] == "VAT_CONSTR" and row["rate_pct"] == "5.0")
    assert schedule["metadata"]["review"]["status"] == "needs_expert_review"
    assert "local_confirmation" not in schedule["metadata"]
    assert schedule["metadata"]["vat_treatment"] == {"input_credit": False}


def test_the_seed_metadata_reaches_the_stored_row() -> None:
    schedule = next(row for row in _egypt() if row["tax_code"] == "VAT_CONSTR" and row["rate_pct"] == "5.0")
    stored = tax_configuration_from_seed_row(schedule)
    assert stored.metadata_["source"]["source_url"].startswith("https://")
    # A row without the key still stores an empty dict, as before.
    german = next(row for row in load_tax_seed_rows() if row["country_code"] == "DE")
    assert tax_configuration_from_seed_row(german).metadata_ == {}
