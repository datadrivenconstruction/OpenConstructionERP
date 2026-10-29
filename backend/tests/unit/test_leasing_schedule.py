# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing schedule arithmetic, country limits and rules (pure, no database)."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.leasing import country_rules
from app.modules.leasing.schedule import add_months, build_schedule, escalation_factor, term_months
from app.modules.leasing.validators import (
    CurrencyMatchesEntityRule,
    DepositNonNegativeRule,
    DepositWithinCapRule,
    EndAfterStartRule,
    NoOverlapRule,
    TenantIdentifierRule,
)


@pytest.mark.parametrize(
    ("anchor", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, date(2028, 2, 29)),
        (date(2026, 1, 31), 2, date(2026, 3, 31)),
        (date(2026, 4, 30), 1, date(2026, 5, 31)),
        (date(2026, 1, 30), 1, date(2026, 2, 28)),
        (date(2026, 1, 30), 2, date(2026, 3, 30)),
        (date(2026, 11, 15), 3, date(2027, 2, 15)),
    ],
)
def test_add_months_clamps_and_keeps_month_end(anchor, months, expected):
    assert add_months(anchor, months) == expected


def test_term_months():
    assert term_months(date(2026, 1, 1), date(2026, 12, 31)) == 12
    assert term_months(date(2026, 1, 31), date(2027, 1, 30)) == 12
    assert term_months(date(2026, 1, 1), date(2026, 1, 20)) == 0


def test_monthly_schedule_from_month_end_stays_on_month_end():
    lines = build_schedule(
        start=date(2026, 1, 31), end=date(2026, 7, 30), rent_amount=Decimal("1000.00"), frequency="monthly"
    )
    assert [x.period_start for x in lines[:4]] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]
    assert lines[0].period_end == date(2026, 2, 27)
    assert all(isinstance(x.amount, Decimal) for x in lines)
    assert sum(x.amount for x in lines) == Decimal("6000.00")


def test_fixed_escalation_compounds_yearly():
    lines = build_schedule(
        start=date(2026, 1, 1),
        end=date(2028, 12, 31),
        rent_amount=Decimal("1000.00"),
        frequency="quarterly",
        escalation_kind="fixed",
        escalation_rate=Decimal("3"),
    )
    assert len(lines) == 12
    assert [x.amount for x in lines[::4]] == [Decimal("1000.00"), Decimal("1030.00"), Decimal("1060.90")]
    assert [x.review_number for x in lines[::4]] == [0, 1, 2]


def test_index_escalation_uses_recorded_rates_only():
    rates = {1: Decimal("2.5")}
    assert escalation_factor(2, kind="index", rate=None, index_rates=rates) == Decimal("1.025")
    lines = build_schedule(
        start=date(2026, 1, 1),
        end=date(2027, 12, 31),
        rent_amount=Decimal("2000"),
        frequency="annual",
        escalation_kind="index",
        index_rates=rates,
    )
    assert [x.amount for x in lines] == [Decimal("2000.00"), Decimal("2050.00")]


def test_short_last_period_is_prorated_by_days_and_tax_rounded():
    lines = build_schedule(
        start=date(2026, 1, 1),
        end=date(2026, 2, 14),
        rent_amount=Decimal("2800.00"),
        frequency="monthly",
        tax_rate=Decimal("15"),
    )
    assert lines[-1].period_end == date(2026, 2, 14)
    assert lines[-1].amount == Decimal("1400.00")
    assert lines[-1].tax_amount == Decimal("210.00")
    assert lines[0].tax_amount == Decimal("420.00")


def test_schedule_is_deterministic():
    kw = {
        "start": date(2026, 3, 31),
        "end": date(2027, 3, 30),
        "rent_amount": Decimal("999.99"),
        "frequency": "monthly",
    }
    assert build_schedule(**kw) == build_schedule(**kw)


def test_unknown_frequency_refused():
    with pytest.raises(ValueError):
        build_schedule(start=date(2026, 1, 1), end=date(2026, 2, 1), rent_amount=Decimal("1"), frequency="weekly")


def _run(rule, data):
    return asyncio.run(rule.validate(ValidationContext(data=data)))


def _lease(**kw):
    base = {
        "id": "L1",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "rent_amount": "1000",
        "frequency": "monthly",
        "deposit": "3000",
        "currency": "EUR",
    }
    base.update(kw)
    return base


def test_end_after_start_rule():
    assert _run(EndAfterStartRule(), {"lease": _lease()})[0].passed
    assert not _run(EndAfterStartRule(), {"lease": _lease(end_date="2025-12-31")})[0].passed


def test_overlap_and_deposit_rules():
    assert not _run(NoOverlapRule(), {"lease": _lease(), "overlaps": ["A-1"]})[0].passed
    assert _run(NoOverlapRule(), {"lease": _lease(), "overlaps": []})[0].passed
    assert not _run(DepositNonNegativeRule(), {"lease": _lease(deposit="-1")})[0].passed


def test_no_country_data_means_no_cap_and_no_identifier_requirement():
    assert _run(DepositWithinCapRule(), {"lease": _lease(deposit="999999"), "country": "ZZ"}) == []
    assert _run(TenantIdentifierRule(), {"lease": _lease(), "country": "ZZ"}) == []


def test_country_cap_and_identifier_from_registered_rules(monkeypatch):
    monkeypatch.setattr(country_rules, "_EXTRA", {})
    country_rules.register_country_rules(
        "ZZ",
        {"deposit_cap_months": 2, "tenant_identifier_schemes": ["nid"], "source_url": "https://example.org/law"},
    )
    over = _run(DepositWithinCapRule(), {"lease": _lease(deposit="2000.01"), "country": "ZZ"})
    assert not over[0].passed
    assert over[0].details["limit"] == "2000.00"
    assert _run(DepositWithinCapRule(), {"lease": _lease(deposit="2000.00"), "country": "ZZ"})[0].passed
    assert not _run(TenantIdentifierRule(), {"lease": _lease(), "country": "ZZ", "tenant_identifier_schemes": []})[
        0
    ].passed
    assert _run(TenantIdentifierRule(), {"lease": _lease(), "country": "ZZ", "tenant_identifier_schemes": ["nid"]})[
        0
    ].passed


def test_country_rule_needs_a_source():
    with pytest.raises(ValueError):
        country_rules.register_country_rules("ZZ", {"deposit_cap_months": 2})


def test_currency_rule_only_with_an_entity():
    assert _run(CurrencyMatchesEntityRule(), {"lease": _lease()}) == []
    assert not _run(CurrencyMatchesEntityRule(), {"lease": _lease(), "entity_currency": "SAR"})[0].passed


def test_export_profiles_are_pluggable():
    from app.modules.leasing.service import export_profiles, register_export_profile

    register_export_profile("demo", lambda rows: (b"x", "text/plain", "txt"))
    assert {"csv", "json", "demo"} <= set(export_profiles())
