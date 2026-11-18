# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The neutral engines on their own, and every shipped table against them.

The engines carry no country: a table from any pack must parse, every rule must
name its source, and every binding must point at a check the engine knows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.jurisdiction_rules import all_jurisdictions, clear_cache, get_jurisdiction
from app.modules.contracts.retention_cap import RetentionTableError, check_retention, parse_table
from app.modules.deadlines.notice_calendar import (
    CalendarInput,
    NoticeRuleError,
    add_months,
    compute_calendar,
    nth_day_of_mth_month,
    parse_rules,
)
from app.modules.statutory import repository
from app.modules.statutory.tax_engine import TaxProfileError, validate_profile
from app.modules.statutory.validators import CHECKS


@pytest.fixture(autouse=True)
def _fresh_registry() -> None:
    clear_cache()


def test_month_arithmetic_clamps_to_the_month_end() -> None:
    assert add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert add_months(date(2026, 12, 15), 8) == date(2027, 8, 15)
    assert nth_day_of_mth_month(2026, 5, 3, 15) == date(2026, 8, 15)
    assert nth_day_of_mth_month(2026, 11, 3, 31) == date(2027, 2, 28)


def test_a_rule_without_a_source_is_refused() -> None:
    with pytest.raises(NoticeRuleError):
        parse_rules([{"code": "x", "rule_type": "days_after_event", "event": "a", "days": 5}])
    with pytest.raises(NoticeRuleError):
        parse_rules([{"code": "x", "rule_type": "weekly", "event": "a", "source": "s"}])


def test_status_follows_today() -> None:
    rules = parse_rules([{"code": "n", "rule_type": "days_after_event", "event": "start", "days": 10, "source": "s"}])
    due = compute_calendar(rules, CalendarInput(events={"start": date(2026, 1, 1)}, today=date(2026, 1, 11)))
    assert due[0].status == "due_today"
    late = compute_calendar(rules, CalendarInput(events={"start": date(2026, 1, 1)}, today=date(2026, 1, 20)))
    assert late[0].status == "overdue"


def test_retention_lowest_cap_and_highest_floor_govern() -> None:
    rows = parse_table(
        [
            {"code": "a", "kind": "cap", "pct": "10", "source": "s"},
            {"code": "b", "kind": "cap", "pct": "5", "source": "s"},
            {"code": "c", "kind": "floor", "pct": "2", "source": "s"},
            {"code": "d", "kind": "floor", "pct": "3", "source": "s"},
        ]
    )
    out = check_retention(
        rows, sector=None, contract_value=None, payment_amount=Decimal("1000"), retention_pct=Decimal("4")
    )
    assert out.cap.code == "b" and out.floor.code == "d"
    assert not out.over_cap and not out.below_floor
    with pytest.raises(RetentionTableError):
        parse_table([{"code": "x", "kind": "cap", "pct": "5"}])


def test_a_tax_profile_with_an_unknown_treatment_is_refused() -> None:
    with pytest.raises(TaxProfileError):
        validate_profile({"contract_forms": {"f": {"source": "s", "treatment": {"material": "free"}}}})


def test_four_states_are_registered() -> None:
    assert {"US-CA", "US-TX", "US-NY", "US-FL"} <= set(all_jurisdictions())
    assert get_jurisdiction("us-ny")["name"] == "New York"
    assert get_jurisdiction("DE-BY") is None


@pytest.mark.parametrize("code", ["US-CA", "US-TX", "US-NY", "US-FL"])
def test_every_shipped_table_parses_and_binds_known_checks(code: str) -> None:
    table = get_jurisdiction(code)
    assert table is not None
    rules = parse_rules(table["notice_calendar"])
    assert rules, "a state with no deadlines has nothing to show"
    known = {r.code for r in rules}
    for rule in rules:
        if rule.event.startswith("rule:"):
            assert rule.event[5:] in known
    parse_table(table["retention"])
    validate_profile(table["tax"])
    for binding in table["validation_rules"]:
        assert binding["check"] in CHECKS, binding["id"]
        assert binding["message"]
    ids = [b["id"] for b in table["validation_rules"]]
    assert len(ids) == len(set(ids))
    summary = repository.summary(table)
    assert summary["code"] == code
    assert summary["tax"]["contract_forms"]
