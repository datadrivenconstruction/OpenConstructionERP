"""Payroll hours export: the DOMAIN worked examples, correction rows and the payexp.* rules."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.modules.field_time.payroll_export import (
    Column,
    ExportProfile,
    HourLine,
    check_run,
    current_hours,
    plan_rows,
    render,
)

D = Decimal

DE = ExportProfile(
    name="Payroll DE",
    columns=(
        Column("Personalnummer", "worker_ref"),
        Column("Datum", "date"),
        Column("Projekt", "project_code"),
        Column("Kostenstelle", "cost_code"),
        Column("Lohnart", "pay_code"),
        Column("Stunden", "hours"),
    ),
    delimiter=";",
    decimal=",",
    date_format="DD.MM.YYYY",
    include_header=False,
    pay_codes={"regular": "1000", "overtime": "1200"},
)
US = ExportProfile(
    name="Payroll US",
    columns=(
        Column("Employee ID", "worker_ref"),
        Column("Week ending", "date"),
        Column("Job", "project_code"),
        Column("Cost code", "cost_code"),
        Column("Pay code", "pay_code"),
        Column("Hours", "hours"),
    ),
    delimiter=",",
    decimal=".",
    date_format="MM/DD/YYYY",
    grouping="week",
    week_start=0,
    include_header=False,
    pay_codes={"regular": "REG"},
)


def line(
    day: date,
    hours: str,
    *,
    rid: str = "r1",
    name: str = "Jonas Weber",
    ref: str = "1047",
    project: str = "P-2026-014",
    cost: str = "300.20",
    hour_type: str = "regular",
    sign: int = 1,
    daywork: bool = False,
) -> HourLine:
    return HourLine(
        resource_id=rid,
        worker_name=name,
        payroll_ref=ref,
        resource_code=f"W-{rid}",
        work_date=day,
        project_id=project,
        project_code=project,
        cost_code=cost,
        hour_type=hour_type,
        hours=D(hours),
        sign=sign,
        is_daywork=daywork,
    )


def lines_of(text: bytes) -> list[str]:
    return text.decode("utf-8").split("\r\n")[:-1]


def test_example_1_day_rows_with_decimal_comma() -> None:
    day = date(2026, 11, 9)
    lines = [line(day, "8.00"), line(day, "1.50", hour_type="overtime")]
    rows = plan_rows(lines, {}, date(2026, 11, 9), date(2026, 11, 15), DE)
    assert lines_of(render(rows, DE)) == [
        "1047;09.11.2026;P-2026-014;300.20;1000;8,00",
        "1047;09.11.2026;P-2026-014;300.20;1200;1,50",
    ]
    assert not any(r.correction for r in rows)


def test_example_2_week_rows_keep_regular_and_do_not_move_overtime() -> None:
    kw = {"rid": "r2", "name": "Maria Lopez", "ref": "E-2207", "project": "TX-118"}
    lines = [
        line(date(2026, 11, 9), "6.0", cost="03-3000", **kw),
        line(date(2026, 11, 9), "4.0", cost="03-1100", **kw),
        *[line(date(2026, 11, 10 + i), "8.5", cost="03-3000", **kw) for i in range(4)],
    ]
    rows = plan_rows(lines, {}, date(2026, 11, 9), date(2026, 11, 15), US)
    assert lines_of(render(rows, US)) == [
        "E-2207,11/15/2026,TX-118,03-1100,REG,4.00",
        "E-2207,11/15/2026,TX-118,03-3000,REG,40.00",
    ]
    assert sum(r.hours for r in rows) == D("44.00")


def test_example_3_reversed_and_reapproved_sheet_yields_a_correction_in_the_next_run() -> None:
    day = date(2026, 11, 10)
    kw = {"rid": "r3", "name": "Ali Kaya", "ref": "2210"}
    first = [line(day, "8.00", **kw)]
    r1 = plan_rows(first, {}, date(2026, 11, 9), date(2026, 11, 15), DE)
    exported = defaultdict(lambda: D("0"))
    for row in r1:
        exported[row.key] += row.hours
    assert lines_of(render(r1, DE)) == ["2210;10.11.2026;P-2026-014;300.20;1000;8,00"]

    after = [
        line(day, "8.00", **kw),  # original, now status reversed
        line(day, "8.00", sign=-1, **kw),  # the reversing timesheet
        line(day, "7.50", **kw),  # re-approved at 7.5 h
    ]
    r2 = plan_rows(after, dict(exported), date(2026, 11, 16), date(2026, 11, 22), DE)
    assert lines_of(render(r2, DE)) == ["2210;10.11.2026;P-2026-014;300.20;1000;-0,50"]
    assert [r.correction for r in r2] == [True]
    # Exporting the same state again adds nothing: the earlier file stays as it was.
    for row in r2:
        exported[row.key] += row.hours
    assert plan_rows(after, dict(exported), date(2026, 11, 16), date(2026, 11, 22), DE) == []


def test_overlapping_period_only_adds_corrections() -> None:
    day = date(2026, 11, 9)
    lines = [line(day, "8.00")]
    exported = {rowkey: D("8.00") for rowkey in current_hours(lines, DE)}
    assert plan_rows(lines, exported, date(2026, 11, 9), date(2026, 11, 15), DE) == []


def test_daywork_can_be_left_out_by_the_profile() -> None:
    day = date(2026, 11, 9)
    lines = [line(day, "8.00"), line(day, "2.00", cost="999", daywork=True)]
    no_daywork = ExportProfile(**{**DE.__dict__, "include_daywork": False})
    assert len(plan_rows(lines, {}, day, day, no_daywork)) == 1
    assert len(plan_rows(lines, {}, day, day, DE)) == 2


def test_header_constant_column_and_correction_flag() -> None:
    profile = ExportProfile(
        columns=(Column("Company", constant="ACME"), Column("Hours", "hours"), Column("Corr", "correction")),
        delimiter=",",
        decimal=".",
        pay_codes={"regular": "1"},
    )
    day = date(2026, 11, 9)
    rows = plan_rows([line(day, "8.00")], {}, day, day, profile)
    assert lines_of(render(rows, profile)) == ["Company,Hours,Corr", "ACME,8.00,"]


def _ids(issues: list[dict]) -> set[str]:
    return {i["rule_id"] for i in issues}


def test_rules_error_and_warning_kinds() -> None:
    day = date(2026, 11, 9)
    lines = [
        line(day, "8.00", ref="", rid="r9", name="No Ref"),
        line(day, "20.00", hour_type="night", cost=""),
        line(day, "6.00", project="P-2"),
    ]
    profile = ExportProfile(**{**DE.__dict__, "day_threshold": D("12")})
    found = check_run(lines, profile, unapproved_refs=["FT-000007"], overlapping_runs=["R12"])
    assert _ids(found) == {
        "payexp.worker_without_ref",
        "payexp.day_over_24h",
        "payexp.hour_type_unmapped",
        "payexp.cost_code_missing",
        "payexp.not_approved",
        "payexp.period_overlap",
    }
    severities = {i["rule_id"]: i["severity"] for i in found}
    assert severities["payexp.not_approved"] == "info"
    assert severities["payexp.worker_without_ref"] == "error"


def test_threshold_warning_is_off_without_a_value_and_code_fallback_clears_the_ref_error() -> None:
    day = date(2026, 11, 9)
    lines = [line(day, "13.00", ref="")]
    assert _ids(check_run(lines, DE)) == {"payexp.worker_without_ref"}
    fallback = ExportProfile(**{**DE.__dict__, "fallback_to_code": True, "day_threshold": D("12")})
    assert _ids(check_run(lines, fallback)) == {"payexp.day_over_threshold"}


def test_negative_total_after_a_reversal_without_its_replacement() -> None:
    day = date(2026, 11, 9)
    lines = [line(day, "8.00", sign=-1)]
    assert "payexp.negative_total" in _ids(check_run(lines, DE))


def test_registered_rules_report_through_the_engine() -> None:
    import asyncio

    from app.core.validation.engine import ValidationContext
    from app.modules.field_time.validators import PAYEXP_RULES

    day = date(2026, 11, 9)
    payload = {"lines": [line(day, "8.00", ref="")], "profile": DE, "unapproved": [], "overlaps": []}
    context = ValidationContext(data=payload, metadata={})
    results = [r for rule in PAYEXP_RULES for r in asyncio.run(rule().validate(context))]
    failed = {r.rule_id for r in results if not r.passed}
    assert failed == {"payexp.worker_without_ref"}
    assert {rule.rule_id for rule in PAYEXP_RULES} == {
        "payexp.worker_without_ref",
        "payexp.day_over_24h",
        "payexp.day_over_threshold",
        "payexp.hour_type_unmapped",
        "payexp.cost_code_missing",
        "payexp.not_approved",
        "payexp.period_overlap",
        "payexp.negative_total",
    }
