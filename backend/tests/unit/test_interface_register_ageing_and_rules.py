# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DB-free tests for the interface register's ageing view, lifecycle edge and rule set.

The ageing numbers come from the pure core, so every band edge is pinned here
from plain values. The ``interface_management`` rules are pure over the payload
the service builds, so each one is asserted to pass and to fail on a row built
to tell the two apart. The segregation-of-duties wiring in approval_routes is a
constant and a literal; both are checked to know the ``interface`` kind.
"""

from __future__ import annotations

import typing
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.interface_management.register import (
    AGEING_BUCKETS,
    OVERDUE_BUCKETS,
    UNKNOWN_AGE,
    InterfaceRow,
    age_days,
    build_report,
    days_overdue,
    open_ageing,
    overdue_ageing,
    transition_problem,
)
from app.modules.interface_management.schemas import InterfaceRegisterResponse
from app.modules.interface_management.validators import (
    ALL_RULES,
    AgreedHasAgreedDateRule,
    AgreedThroughRouteRule,
    ClosedWasAgreedRule,
    NeedByBeforeActivityFinishRule,
    RfiInProjectRule,
    ScheduleActivityInProjectRule,
)

AS_OF = date(2026, 10, 16)


def _row(status: str = "open", *, opened_days_ago: int | None = 0, need_by: date | None = None) -> InterfaceRow:
    opened = AS_OF - timedelta(days=opened_days_ago) if opened_days_ago is not None else None
    return InterfaceRow(id="x", reference="IF", status=status, opened_on=opened, need_by_date=need_by)


# -- Ageing ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "band"),
    [(0, "0_7"), (7, "0_7"), (8, "8_30"), (30, "8_30"), (31, "31_60"), (60, "31_60"), (61, "61_90"), (90, "61_90")]
    + [(91, "over_90"), (400, "over_90")],
)
def test_open_ageing_band_edges(days: int, band: str) -> None:
    counts = open_ageing([_row(opened_days_ago=days)], AS_OF)
    assert counts[band] == 1
    assert sum(counts.values()) == 1


def test_open_ageing_skips_settled_and_counts_unknown() -> None:
    rows = [
        _row("agreed", opened_days_ago=100),
        _row("closed", opened_days_ago=100),
        _row("disputed", opened_days_ago=3),
        _row("on_hold", opened_days_ago=None),
    ]
    counts = open_ageing(rows, AS_OF)
    assert list(counts) == [b[0] for b in AGEING_BUCKETS] + [UNKNOWN_AGE]
    assert counts["0_7"] == 1
    assert counts[UNKNOWN_AGE] == 1
    assert counts["over_90"] == 0  # settled interfaces are not ageing
    assert sum(counts.values()) == 2


@pytest.mark.parametrize(("late", "band"), [(1, "1_7"), (7, "1_7"), (8, "8_30"), (31, "31_60"), (61, "over_60")])
def test_overdue_ageing_band_edges(late: int, band: str) -> None:
    counts = overdue_ageing([_row(need_by=AS_OF - timedelta(days=late))], AS_OF)
    assert list(counts) == [b[0] for b in OVERDUE_BUCKETS]
    assert counts[band] == 1


def test_due_today_and_settled_are_not_overdue() -> None:
    assert days_overdue(_row(need_by=AS_OF), AS_OF) is None
    assert days_overdue(_row("agreed", need_by=AS_OF - timedelta(days=9)), AS_OF) is None
    assert days_overdue(_row("on_hold", need_by=AS_OF - timedelta(days=9)), AS_OF) is None
    assert days_overdue(_row(need_by=AS_OF - timedelta(days=9)), AS_OF) == 9


def test_age_never_negative_and_unknown_is_none() -> None:
    future = InterfaceRow(status="open", opened_on=AS_OF + timedelta(days=3))
    assert age_days(future, AS_OF) == 0
    assert age_days(_row(opened_days_ago=None), AS_OF) is None


def test_report_carries_ageing_and_serialises_average_as_string() -> None:
    rows = [
        _row(opened_days_ago=10, need_by=AS_OF - timedelta(days=5)),
        _row(opened_days_ago=40, need_by=AS_OF - timedelta(days=70)),
        _row("agreed", opened_days_ago=200),
        _row(opened_days_ago=1),
    ]
    report = build_report(rows, AS_OF)
    assert report.open_count == 3
    assert report.overdue_count == 2
    assert report.oldest_open_age_days == 40
    assert report.average_open_age_days == Decimal("17.00")
    assert report.max_days_overdue == 70
    assert report.overdue_ageing == {"1_7": 1, "8_30": 0, "31_60": 0, "over_60": 1}
    payload = report.to_dict()
    assert payload["overdue"][0]["days_overdue"] == 5
    assert payload["overdue"][0]["age_days"] == 10
    payload["project_id"] = "11111111-1111-1111-1111-111111111111"
    dumped = InterfaceRegisterResponse.model_validate(payload).model_dump(mode="json")
    assert dumped["average_open_age_days"] == "17.00"
    assert dumped["ageing"]["31_60"] == 1
    assert dumped["overdue"][1]["days_overdue"] == 70


def test_empty_register_ageing_is_undefined_not_zero() -> None:
    report = build_report([], AS_OF)
    assert report.average_open_age_days is None
    assert report.oldest_open_age_days is None
    assert report.max_days_overdue is None
    assert sum(report.ageing.values()) == 0


# -- Lifecycle edge ----------------------------------------------------------


@pytest.mark.parametrize("source", ["identified", "open", "in_progress", "disputed", "on_hold"])
def test_closed_only_from_agreed(source: str) -> None:
    assert transition_problem(source, "closed") is not None
    assert transition_problem("agreed", "closed") is None


def test_other_moves_stay_free() -> None:
    assert transition_problem("closed", "open") is None
    assert transition_problem("open", "agreed") is None
    assert transition_problem("open", "open") is None


# -- Rule set ----------------------------------------------------------------


async def _run(rule_cls: type, row: dict) -> list:
    return await rule_cls().validate(ValidationContext(data={"interfaces": [row]}))


async def test_schedule_activity_rule_fails_on_foreign_or_missing_activity() -> None:
    bad = await _run(ScheduleActivityInProjectRule, {"id": "1", "schedule_activity_id": "a", "activity_found": False})
    good = await _run(ScheduleActivityInProjectRule, {"id": "1", "schedule_activity_id": "a", "activity_found": True})
    none = await _run(ScheduleActivityInProjectRule, {"id": "1", "schedule_activity_id": None})
    assert [r.passed for r in bad] == [False]
    assert bad[0].severity == Severity.ERROR
    assert [r.passed for r in good] == [True]
    assert none == []


async def test_rfi_rule_fails_on_foreign_or_missing_rfi() -> None:
    assert [r.passed for r in await _run(RfiInProjectRule, {"rfi_id": "r", "rfi_found": False})] == [False]
    assert [r.passed for r in await _run(RfiInProjectRule, {"rfi_id": "r", "rfi_found": True})] == [True]


async def test_agreed_needs_agreed_date() -> None:
    assert [r.passed for r in await _run(AgreedHasAgreedDateRule, {"status": "agreed"})] == [False]
    ok = {"status": "closed", "agreed_date": "2026-10-01"}
    assert [r.passed for r in await _run(AgreedHasAgreedDateRule, ok)] == [True]
    assert await _run(AgreedHasAgreedDateRule, {"status": "open"}) == []


@pytest.mark.parametrize(("approval", "passed"), [("pending", False), ("rejected", False), ("approved", True)])
async def test_agreed_follows_route(approval: str, passed: bool) -> None:
    results = await _run(AgreedThroughRouteRule, {"status": "agreed", "approval_status": approval})
    assert [r.passed for r in results] == [passed]


async def test_agreed_without_any_route_is_out_of_scope() -> None:
    assert await _run(AgreedThroughRouteRule, {"status": "agreed", "approval_status": None}) == []
    assert await _run(AgreedThroughRouteRule, {"status": "agreed", "approval_status": "cancelled"}) == []


async def test_closed_was_agreed_first() -> None:
    never = await _run(ClosedWasAgreedRule, {"status": "closed", "closed_date": "2026-10-01"})
    backwards = await _run(
        ClosedWasAgreedRule, {"status": "closed", "agreed_date": "2026-10-05", "closed_date": "2026-10-01"}
    )
    fine = await _run(
        ClosedWasAgreedRule, {"status": "closed", "agreed_date": "2026-10-01", "closed_date": "2026-10-05"}
    )
    assert [r.passed for r in never + backwards + fine] == [False, False, True]


async def test_need_by_after_activity_finish_is_a_warning() -> None:
    late = {"activity_found": True, "need_by_date": "2026-11-02", "activity_end_date": "2026-11-01"}
    on_time = {"activity_found": True, "need_by_date": "2026-11-01", "activity_end_date": "2026-11-01T00:00:00"}
    results = await _run(NeedByBeforeActivityFinishRule, late)
    assert [r.passed for r in results] == [False]
    assert results[0].severity == Severity.WARNING
    assert [r.passed for r in await _run(NeedByBeforeActivityFinishRule, on_time)] == [True]


def test_rule_ids_are_unique_and_namespaced() -> None:
    ids = [cls.rule_id for cls in ALL_RULES]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("interface_management.") for i in ids)


# -- approval_routes wiring ---------------------------------------------------


def test_approval_routes_know_the_interface_kind_and_segregate_it() -> None:
    from app.modules.approval_routes.models import SELF_APPROVAL_FORBIDDEN_KINDS, TARGET_KINDS
    from app.modules.approval_routes.schemas import TargetKindLiteral

    assert "interface" in TARGET_KINDS
    assert "interface" in typing.get_args(TargetKindLiteral)
    assert set(TARGET_KINDS) >= SELF_APPROVAL_FORBIDDEN_KINDS
    assert "interface" in SELF_APPROVAL_FORBIDDEN_KINDS
