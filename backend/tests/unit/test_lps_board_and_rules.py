# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Last Planner pure helpers and the ``last_planner`` validation rules​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import validation_engine
from app.modules.schedule_advanced import lps_rules
from app.modules.schedule_advanced.lps import monday, pareto_rows, week_ppc


def _c(status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status)


def test_week_ppc_counts_only_promised_work() -> None:
    n, done, ppc = week_ppc([_c("completed"), _c("completed"), _c("missed"), _c("planned")])
    assert (n, done, ppc) == (3, 2, Decimal("66.67"))


def test_week_ppc_is_none_when_nothing_was_committed() -> None:
    assert week_ppc([_c("planned")]) == (0, 0, None)


def test_pareto_sorts_and_accumulates() -> None:
    rows = pareto_rows({"material": 5, "info": 3, "weather": 2, "quality": 0})
    assert [r["category"] for r in rows] == ["material", "info", "weather"]
    assert rows[0]["percent"] == Decimal("50.0")
    assert rows[-1]["cumulative_percent"] == Decimal("100.0")


def test_monday() -> None:
    assert monday(date(2026, 10, 25)) == date(2026, 10, 19)


def _payload(**kw):
    base = {"as_of": "2026-10-26", "weeks": [], "commitments": [], "constraints": []}
    base.update(kw)
    return base


def test_check_commitment_constraints_open() -> None:
    p = _payload(
        commitments=[
            {"id": "a", "status": "committed", "open_constraints": 2},
            {"id": "b", "status": "committed", "open_constraints": 0},
            {"id": "c", "status": "completed", "open_constraints": 1},
        ]
    )
    assert [r["id"] for r in lps_rules.check_commitment_constraints_open(p)] == ["a"]


def test_check_week_ppc_recorded_flags_only_finished_weeks() -> None:
    p = _payload(
        weeks=[
            {"id": "old", "week_start_date": "2026-10-12", "status": "committed", "committed": 4, "ppc_percent": None},
            {"id": "ok", "week_start_date": "2026-10-05", "status": "closed", "committed": 4, "ppc_percent": "75"},
            {"id": "now", "week_start_date": "2026-10-26", "status": "committed", "committed": 4, "ppc_percent": None},
            {"id": "empty", "week_start_date": "2026-09-28", "status": "draft", "committed": 0, "ppc_percent": None},
        ]
    )
    assert [r["id"] for r in lps_rules.check_week_ppc_recorded(p)] == ["old"]


def test_check_constraint_overdue_and_owner() -> None:
    p = _payload(
        constraints=[
            {"id": "x", "status": "open", "target_clear_date": "2026-10-20", "owner_user_id": None},
            {"id": "y", "status": "cleared", "target_clear_date": "2026-10-01", "owner_user_id": None},
            {"id": "z", "status": "open", "target_clear_date": "2026-11-20", "owner_user_id": "u"},
        ]
    )
    assert [r["id"] for r in lps_rules.check_constraint_overdue(p)] == ["x"]
    assert [r["id"] for r in lps_rules.check_constraint_owner(p)] == ["x"]


def test_check_missed_commitment_reason() -> None:
    p = _payload(
        commitments=[
            {"id": "m", "status": "missed", "has_rnc": False},
            {"id": "n", "status": "missed", "has_rnc": True},
        ]
    )
    assert [r["id"] for r in lps_rules.check_missed_commitment_reason(p)] == ["m"]


@pytest.mark.asyncio
async def test_rule_set_runs_through_the_engine_and_words_findings() -> None:
    lps_rules.register_lps_rules()
    payload = _payload(
        commitments=[
            {
                "id": "a",
                "status": "committed",
                "open_constraints": 1,
                "worker_or_crew": "Rebar crew",
                "week_start_date": "2026-10-26",
            }
        ],
        constraints=[
            {
                "id": "x",
                "status": "open",
                "target_clear_date": "2026-10-20",
                "owner_user_id": "u",
                "description": "Permit",
            }
        ],
    )
    report = await validation_engine.validate(payload, rule_sets=[lps_rules.RULE_SET], metadata={"locale": "de"})
    failed = {r.rule_id: r for r in report.results if not r.passed}
    assert "last_planner.commitment_constraints_open" in failed
    assert failed["last_planner.commitment_constraints_open"].severity.value == "error"
    assert "Rebar crew" in failed["last_planner.commitment_constraints_open"].message
    assert "Hindernis" in failed["last_planner.constraint_overdue"].message
    assert report.has_errors
