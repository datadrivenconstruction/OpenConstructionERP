# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""California electronic certified payroll (eCPR, schema version 2.0).

Labor Code § 1776 requires certified payroll on public works to be filed with
the Department of Industrial Relations, and the department accepts it as XML in
its eCPR schema. Element order follows the department's blank template.

What the week does not hold stays empty and is listed in ``missing``: the
contractor's 10-digit public works registration number, the DIR project id, and
each worker's address and tax id. The platform does not store tax ids.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree as ET

from app.modules.certified_payroll.certpay_math import week_days
from app.modules.certified_payroll.export_profiles import ExportProfile, ExportResult, split_name

NS = "https://www.dir.ca.gov/Public-Works/CPR/eCPR-v2.xsd"
ET.register_namespace("CPR", NS)

#: Deduction ``type`` (or a word in its label) to the eCPR deduction element.
_DEDUCTION_ELEMENT = {"social": "FICA", "tax": "fedTax", "pension": "other", "other": "other"}
_LABEL_HINTS = (("sdi", "SDI"), ("state", "stateTax"), ("dues", "dues"), ("saving", "savings"), ("admin", "fundAdmin"))
_DEDUCTION_ORDER = ("fedTax", "FICA", "stateTax", "SDI", "fundAdmin", "savings", "dues", "other")


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, _q(tag), attrs)
    if text is not None:
        el.text = text
    return el


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _m(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _deduction_element(item: dict[str, Any]) -> str:
    label = str(item.get("label") or "").lower()
    for hint, element in _LABEL_HINTS:
        if hint in label:
            return element
    return _DEDUCTION_ELEMENT.get(str(item.get("type") or "other"), "other")


def render_ecpr(header: dict[str, Any], lines: list[dict[str, Any]], extra: dict[str, str]) -> ExportResult:
    """Write one week as an eCPR v2 document."""
    missing: list[str] = []
    registration = str(extra.get("contractor_registration") or "").strip()
    project_id = str(extra.get("project_id") or "").strip()
    awarding_body = str(extra.get("awarding_body") or "").strip()
    if not (registration.isdigit() and len(registration) == 10):
        missing.append("contractor_registration")
    if not project_id.isdigit():
        missing.append("project_id")
    if not awarding_body:
        missing.append("awarding_body")

    root = ET.Element(_q("eCPR"))
    _sub(root, "version", "2.0")
    contractor = _sub(root, "contractorInfo")
    _sub(contractor, "contractorName", str(header.get("contractor_name") or ""))
    _sub(contractor, "contractorPWCR", registration)
    project = _sub(root, "projectInfo")
    _sub(project, "awardingBody", awarding_body)
    _sub(project, "projectID", project_id)
    payroll = _sub(root, "payrollInfo")
    worked = [line for line in lines if _d(line.get("straight_hours")) + _d(line.get("overtime_hours")) > 0]
    _sub(payroll, "statementOfNP", "false" if worked else "true")
    ending = str(header.get("week_ending") or "")
    _sub(payroll, "forWeekEnding", ending)
    days = week_days(ending) if ending else []
    employees = _sub(payroll, "employees")

    for line in worked:
        name = str(line.get("worker_name") or "")
        first, middle, last = split_name(name)
        emp = _sub(employees, "employee")
        _sub(emp, "firstName", first)
        _sub(emp, "lastName", last)
        _sub(emp, "middleName", middle)
        address = _sub(emp, "address")
        for tag in ("street", "city", "state", "zip"):
            _sub(address, tag, "")
        _sub(emp, "ssn", "")
        missing.extend([f"{name}: address", f"{name}: ssn or itin"])
        _sub(emp, "notes", "")

        classes = _sub(emp, "classifications")
        title = str(line.get("classification_title") or "")
        cls = _sub(classes, "classification", name=title)
        _sub(cls, "craft", title)
        apprentice = "apprentice" in title.lower()
        _sub(cls, "employeeLevel", "apprentice" if apprentice else "journeyman")
        _sub(cls, "apprenticeLevel", "")
        if apprentice:
            missing.append(f"{name}: apprentice level")
        per_day = _sub(cls, "hrsWorkedEachDay")
        by_day = line.get("hours_by_day") if isinstance(line.get("hours_by_day"), dict) else {}
        for index, day in enumerate(days, start=1):
            entry = by_day.get(day) if isinstance(by_day.get(day), dict) else {}
            node = _sub(per_day, "day", id=str(index))
            _sub(node, "date", day)
            _sub(node, "straightTime", _m(_d(entry.get("straight"))))
            _sub(node, "overtime", _m(_d(entry.get("overtime"))))
            _sub(node, "doubletime", "0.00")

        fringe_rate = _d(line.get("paid_fringe_rate"))
        to_plan = str(line.get("fringe_election") or header.get("fringe_election") or "") == "plan"
        paid = _sub(cls, "fringePaid")
        _sub(paid, "paidToEmployee", "false" if to_plan else "true")
        _sub(paid, "paidToBenefitPlan", "true" if to_plan else "false")
        fringe = _sub(cls, "fringe")
        for tag in ("healthWelfare", "vacationHoliday", "pension", "training"):
            _sub(fringe, tag, "0.00")
        _sub(fringe, "other", _m(fringe_rate))

        totals = _sub(cls, "totHrs")
        _sub(totals, "totHrsStraightTime", _m(_d(line.get("straight_hours"))))
        _sub(totals, "totHrsOvertime", _m(_d(line.get("overtime_hours"))))
        _sub(totals, "totHrsDoubletime", "0.00")
        basic = _d(line.get("paid_basic_rate"))
        overtime = _d(line.get("overtime_base_rate") or basic) * _d(line.get("overtime_multiplier") or "1.5")
        rates = _sub(cls, "hrlyPayRate")
        _sub(rates, "hrlyPayRateStraightTime", _m(basic))
        _sub(rates, "hrlyPayRateOvertime", _m(overtime))
        _sub(rates, "hrlyPayRateDoubletime", "0.00")
        _sub(rates, "totalHrlyPayRateStraightTime", _m(basic + fringe_rate))
        _sub(rates, "totalHrlyPayRateOvertime", _m(overtime + fringe_rate))
        _sub(rates, "totalHrlyPayRateDoubletime", "0.00")

        payments = _sub(emp, "payments")
        _sub(payments, "travelSubs", "0.00")
        buckets = dict.fromkeys(_DEDUCTION_ORDER, Decimal("0"))
        for item in line.get("deductions_detail") or []:
            if isinstance(item, dict):
                buckets[_deduction_element(item)] += _d(item.get("amount"))
        deductions = _sub(emp, "deductions")
        for tag in _DEDUCTION_ORDER:
            _sub(deductions, tag, _m(buckets[tag]))
        _sub(deductions, "totalDeductions", _m(_d(line.get("total_deductions"))))
        earnings = _sub(emp, "earnings")
        gross = _m(_d(line.get("gross_amount")))
        _sub(earnings, "grossThisProject", gross)
        # The week only knows this project; the filer corrects it when the worker had other work.
        _sub(earnings, "grossAllWork", gross)
        _sub(earnings, "netWagePaidWeek", _m(_d(line.get("net_amount"))))
        _sub(earnings, "checkNum", "")

    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    return ExportResult(
        content='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body + "\n", missing=missing
    )


PAYROLL_EXPORT_PROFILES: tuple[ExportProfile, ...] = (
    ExportProfile(
        code="ca_dir_ecpr_v2",
        label="California DIR eCPR (XML)",
        media_type="application/xml",
        extension="xml",
        render=render_ecpr,
        extra_fields=("contractor_registration", "awarding_body", "project_id"),
        backend_module="oe_us_ca_pack",
    ),
)

__all__ = ["PAYROLL_EXPORT_PROFILES", "render_ecpr"]
