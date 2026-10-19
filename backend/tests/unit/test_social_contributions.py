# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory social insurance contributions, resolved by country, cohort and date.

Saudi Arabia is the first country in the table and the reason it has a cohort
axis: since the Social Insurance Law came into force on 2024-07-03, a Saudi
employee who never contributed before pays annuities on a schedule that rises
every July until 2028, while one already insured stays on the legacy 9
percent. Same country, same day, two answers, so the cohort is an input and
never a guess.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.core.social_contributions import (
    CONTRIBUTION_ROWS,
    contributory_wage,
    rows_in_force,
    total_rate,
    validate_rows,
)

_TODAY = date(2026, 10, 19)


def test_the_shipped_table_is_sound() -> None:
    assert validate_rows(CONTRIBUTION_ROWS) == []


def test_a_legacy_saudi_employee_pays_the_long_standing_rates() -> None:
    assert total_rate("SA", "national_legacy", "employee", _TODAY) == Decimal("9.75")
    assert total_rate("SA", "national_legacy", "employer", _TODAY) == Decimal("11.75")


def test_a_new_entrant_follows_the_july_schedule() -> None:
    def annuities(on: date, payer: str) -> Decimal:
        rows = [row for row in rows_in_force("SA", "national_new_entrant", on) if row.scheme == "annuities"]
        assert len(rows) == 2, rows
        return next(row.rate_pct for row in rows if row.payer == payer)

    assert annuities(date(2025, 6, 30), "employee") == Decimal("9")
    assert annuities(date(2025, 7, 1), "employee") == Decimal("9.5")
    assert annuities(date(2026, 6, 30), "employer") == Decimal("9.5")
    assert annuities(date(2026, 8, 1), "employer") == Decimal("10")
    assert annuities(date(2028, 7, 1), "employee") == Decimal("11")
    # Same day, other cohort: the legacy rate does not move.
    legacy = [r for r in rows_in_force("SA", "national_legacy", date(2028, 7, 1)) if r.scheme == "annuities"]
    assert {r.rate_pct for r in legacy} == {Decimal("9")}


def test_the_stepped_rows_are_flagged_for_review() -> None:
    stepped = [r for r in CONTRIBUTION_ROWS if r.cohort == "national_new_entrant" and r.rate_pct > Decimal("9")]
    assert stepped
    assert all(r.needs_expert_review for r in stepped)


def test_a_non_saudi_employee_costs_the_employer_hazards_only() -> None:
    assert total_rate("SA", "non_national", "employer", _TODAY) == Decimal("2")
    assert total_rate("SA", "non_national", "employee", _TODAY) == Decimal("0")


def test_an_unknown_cohort_or_country_or_date_answers_none() -> None:
    assert total_rate("SA", "volunteer", "employee", _TODAY) is None
    assert total_rate("DE", "national_legacy", "employee", _TODAY) is None
    assert total_rate("SA", "national_legacy", "employee", date(2024, 7, 2)) is None


def test_the_contributory_wage_is_capped() -> None:
    assert contributory_wage("SA", Decimal("60000"), _TODAY) == Decimal("45000")
    assert contributory_wage("SA", Decimal("12000"), _TODAY) == Decimal("12000")
    assert contributory_wage("DE", Decimal("60000"), _TODAY) is None


def test_overlapping_rows_are_refused() -> None:
    row = next(r for r in CONTRIBUTION_ROWS if r.cohort == "national_legacy" and r.scheme == "annuities")
    clash = replace(row, rate_pct=Decimal("10"))
    problems = validate_rows((*CONTRIBUTION_ROWS, clash))
    assert any("overlap" in problem for problem in problems), problems


@pytest.mark.parametrize("field", ["legal_reference", "source_url"])
def test_a_row_without_its_source_is_refused(field: str) -> None:
    row = replace(CONTRIBUTION_ROWS[0], **{field: ""})
    assert validate_rows((row,)) != []
