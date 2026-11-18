# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Certified payroll export profiles: the core CSV and the California and New York XML."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from app.modules.certified_payroll.export_profiles import available_profiles, get_profile, split_name

_HEADER: dict[str, Any] = {
    "week_ending": "2026-08-16",
    "payroll_number": "7",
    "contractor_name": "Northgate Mechanical",
    "project_name": "Valley Unified Classroom Building",
    "fringe_election": "cash",
}

_LINE: dict[str, Any] = {
    "worker_name": "Rosa Alvarez",
    "classification_title": "Electrician",
    "hours_by_day": {
        "2026-08-10": {"straight": "8", "overtime": "0"},
        "2026-08-11": {"straight": "8", "overtime": "2"},
    },
    "straight_hours": "16",
    "overtime_hours": "2",
    "paid_basic_rate": "40",
    "paid_fringe_rate": "10",
    "overtime_base_rate": "40",
    "overtime_multiplier": "1.5",
    "gross_amount": "940.00",
    "total_deductions": "140.00",
    "net_amount": "800.00",
    "deductions_detail": [
        {"label": "Social security", "type": "social", "amount": "60.00"},
        {"label": "Income tax", "type": "tax", "amount": "50.00"},
        {"label": "Union dues", "type": "other", "amount": "30.00"},
    ],
}

_CPR = "{https://www.dir.ca.gov/Public-Works/CPR/eCPR-v2.xsd}"


def test_profiles_follow_the_jurisdiction_list() -> None:
    codes = [p.code for p in available_profiles(["ca_dir_ecpr_v2", "us_wh347_csv"])]
    assert codes == ["ca_dir_ecpr_v2", "us_wh347_csv"]
    assert get_profile("nope") is None


def test_split_name() -> None:
    assert split_name("Rosa Maria Alvarez") == ("Rosa", "Maria", "Alvarez")
    assert split_name("Rosa") == ("Rosa", "", "")


def test_california_ecpr_week() -> None:
    profile = get_profile("ca_dir_ecpr_v2")
    assert profile is not None
    result = profile.render(
        _HEADER, [_LINE], {"contractor_registration": "1000012345", "awarding_body": "Valley USD", "project_id": "512"}
    )
    root = ET.fromstring(result.content.split("\n", 1)[1])
    assert root.find(f"{_CPR}payrollInfo/{_CPR}statementOfNP").text == "false"
    assert root.find(f"{_CPR}payrollInfo/{_CPR}forWeekEnding").text == "2026-08-16"
    emp = root.find(f"{_CPR}payrollInfo/{_CPR}employees/{_CPR}employee")
    assert emp.find(f"{_CPR}lastName").text == "Alvarez"
    days = emp.findall(f".//{_CPR}hrsWorkedEachDay/{_CPR}day")
    assert [d.get("id") for d in days] == ["1", "2", "3", "4", "5", "6", "7"]
    assert days[0].find(f"{_CPR}date").text == "2026-08-10"
    assert days[1].find(f"{_CPR}overtime").text == "2.00"
    rates = emp.find(f".//{_CPR}hrlyPayRate")
    assert rates.find(f"{_CPR}hrlyPayRateOvertime").text == "60.00"
    assert rates.find(f"{_CPR}totalHrlyPayRateStraightTime").text == "50.00"
    deductions = emp.find(f"{_CPR}deductions")
    assert deductions.find(f"{_CPR}FICA").text == "60.00"
    assert deductions.find(f"{_CPR}fedTax").text == "50.00"
    assert deductions.find(f"{_CPR}dues").text == "30.00"
    assert result.missing == ["Rosa Alvarez: address", "Rosa Alvarez: ssn or itin"]


def test_california_ecpr_names_missing_registration_and_non_performance() -> None:
    result = get_profile("ca_dir_ecpr_v2").render(_HEADER, [], {})
    assert {"contractor_registration", "project_id", "awarding_body"} <= set(result.missing)
    assert "<CPR:statementOfNP>true</CPR:statementOfNP>" in result.content


def test_new_york_dol_week() -> None:
    result = get_profile("ny_dol_payroll_xml").render(_HEADER, [_LINE], {"prc_number": "1092381092"})
    root = ET.fromstring(result.content.split("\n", 1)[1])
    assert root.tag == "ProjectRollup"
    assert root.find("weekEndingDate").text == "2026-08-16T00:00:00.000Z"
    week = root.find("employeeWorkWeeks/employeeWorkWeek")
    assert week.find("deductionsGrossEarnings").text == "940.00"
    days = week.findall("workWeeks/workWeek/days/day")
    assert [d.find("day").text for d in days] == ["2026-08-10", "2026-08-11"]
    assert week.find("workWeeks/workWeek/otHourlyRate").text == "60.00"
    assert week.find("supplementalPayments/supplementalPayment/type").text == "Other Benefit (Type)"
    assert result.missing == ["Rosa Alvarez: address"]


def test_core_csv_profile_is_the_weekly_form() -> None:
    result = get_profile("us_wh347_csv").render(_HEADER, [_LINE], {})
    assert "Rosa Alvarez" in result.content
    assert result.missing == []
