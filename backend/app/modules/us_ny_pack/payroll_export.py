# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""New York State Department of Labor certified payroll XML.

Labor Law § 220 public work files certified payroll with the department
electronically; the department publishes the ``ProjectRollup`` schema this
writer follows, element by element. The project's registration code
(``prcNumber``) and each worker's address are typed by the person filing;
anything absent stays empty and is listed in ``missing``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree as ET

from app.modules.certified_payroll.certpay_math import week_days
from app.modules.certified_payroll.export_profiles import ExportProfile, ExportResult, split_name


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
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


def render_ny_payroll(header: dict[str, Any], lines: list[dict[str, Any]], extra: dict[str, str]) -> ExportResult:
    """Write one week as a NYSDOL ``ProjectRollup`` document."""
    missing: list[str] = []
    prc = str(extra.get("prc_number") or "").strip()
    if not prc or len(prc) > 10:
        missing.append("prc_number")
    root = ET.Element("ProjectRollup")
    _sub(root, "prcNumber", prc)
    ending = str(header.get("week_ending") or "")
    _sub(root, "weekEndingDate", f"{ending}T00:00:00.000Z" if ending else "")
    days = week_days(ending) if ending else []
    weeks = _sub(root, "employeeWorkWeeks")

    for line in lines:
        name = str(line.get("worker_name") or "")
        first, middle, last = split_name(name)
        title = str(line.get("classification_title") or "")
        ew = _sub(weeks, "employeeWorkWeek")
        emp = _sub(ew, "employee")
        _sub(emp, "firstName", first)
        if middle:
            _sub(emp, "middleName", middle)
        _sub(emp, "lastName", last)
        _sub(emp, "nysRegisteredApprentice", "true" if "apprentice" in title.lower() else "false")
        address = _sub(emp, "address")
        for tag in ("address1", "city", "state", "postalCode"):
            _sub(address, tag, "")
        _sub(address, "country", "United States")
        missing.append(f"{name}: address")
        _sub(ew, "deductionsGrossEarnings", _m(_d(line.get("gross_amount"))))
        _sub(ew, "netWages", _m(_d(line.get("net_amount"))))

        work_weeks = _sub(ew, "workWeeks")
        week = _sub(work_weeks, "workWeek")
        _sub(week, "workCategory", title)
        basic = _d(line.get("paid_basic_rate"))
        overtime = _d(line.get("overtime_base_rate") or basic) * _d(line.get("overtime_multiplier") or "1.5")
        _sub(week, "stHourlyRate", _m(basic))
        _sub(week, "otHourlyRate", _m(overtime))
        day_list = _sub(week, "days")
        by_day = line.get("hours_by_day") if isinstance(line.get("hours_by_day"), dict) else {}
        for day in days:
            entry = by_day.get(day) if isinstance(by_day.get(day), dict) else {}
            straight, extra_hours = _d(entry.get("straight")), _d(entry.get("overtime"))
            if straight == 0 and extra_hours == 0:
                continue
            node = _sub(day_list, "day")
            _sub(node, "day", day)
            _sub(node, "standardTimeHours", _m(straight))
            _sub(node, "overTimeHours", _m(extra_hours))

        deductions = _sub(ew, "deductions")
        for item in (line.get("deductions_detail") or [])[:10]:
            if isinstance(item, dict):
                node = _sub(deductions, "deduction")
                _sub(node, "type", str(item.get("label") or item.get("type") or "Other")[:50])
                _sub(node, "amount", _m(_d(item.get("amount"))))

        fringe = _d(line.get("paid_fringe_rate"))
        supplements = _sub(ew, "supplementalPayments")
        if fringe > 0:
            node = _sub(supplements, "supplementalPayment")
            _sub(node, "type", "Other Benefit (Type)")
            _sub(node, "workCategory", title)
            _sub(node, "explanation", "Supplements as paid")
            _sub(node, "standardHourlyRate", _m(fringe))
            _sub(node, "overtimeHourlyRate", _m(fringe))

    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    return ExportResult(content='<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n", missing=missing)


PAYROLL_EXPORT_PROFILES: tuple[ExportProfile, ...] = (
    ExportProfile(
        code="ny_dol_payroll_xml",
        label="New York DOL certified payroll (XML)",
        media_type="application/xml",
        extension="xml",
        render=render_ny_payroll,
        extra_fields=("prc_number",),
        backend_module="oe_us_ny_pack",
    ),
)

__all__ = ["PAYROLL_EXPORT_PROFILES", "render_ny_payroll"]
