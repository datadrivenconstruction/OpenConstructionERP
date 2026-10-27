# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payroll​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ period export writers: generic CSV / Excel, DATEV LODAS ASCII, neutral JSON.

Pure functions over plain row dicts (one per period line), so the same writer runs in
a unit test and behind the API. Money and hours stay Decimal strings until the writer
formats them for its target.

The LODAS writer follows the ASCII import interface layout: an ``[Allgemein]`` header,
one ``[Satzbeschreibung]`` record definition for standard movement data and the
``[Bewegungsdaten]`` rows. Wage type numbers (Lohnart) and the unit keys come from the
DE profile in ``country_data/payroll_rules.json``, so a payroll office maps its own
wage types without a code change. The file is cp1252 with CRLF line ends.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

DEFAULT_COLUMNS: tuple[str, ...] = (
    "employee_number",
    "employee",
    "project",
    "cost_code",
    "work_date",
    "pay_type",
    "hours",
    "rate",
    "multiplier",
    "amount",
    "currency",
)
ALLOWED_COLUMNS: frozenset[str] = frozenset(
    {*DEFAULT_COLUMNS, "employee_id", "project_id", "overtime_approved", "period_start", "period_end"}
)


def pick_columns(columns: Sequence[str] | None) -> list[str]:
    """Validated column list; unknown names raise ``ValueError``."""
    if not columns:
        return list(DEFAULT_COLUMNS)
    bad = [c for c in columns if c not in ALLOWED_COLUMNS]
    if bad:
        raise ValueError(f"Unknown export column(s): {', '.join(bad)}")
    return list(columns)


def to_csv(rows: Iterable[Mapping[str, Any]], columns: Sequence[str] | None = None, delimiter: str = ",") -> str:
    """Generic CSV with a header row and the chosen columns."""
    cols = pick_columns(columns)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(cols)
    for row in rows:
        writer.writerow(["" if row.get(c) is None else str(row.get(c)) for c in cols])
    return buf.getvalue()


def to_xlsx(rows: Iterable[Mapping[str, Any]], columns: Sequence[str] | None = None) -> bytes:
    """Excel workbook with one sheet; numbers are written as numbers."""
    from openpyxl import Workbook

    cols = pick_columns(columns)
    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll"
    ws.append(cols)
    numeric = {"hours", "rate", "multiplier", "amount"}
    for row in rows:
        ws.append([Decimal(str(row[c])) if c in numeric and row.get(c) not in (None, "") else row.get(c) for c in cols])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_json(period: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    """Neutral JSON for an HR system: the period header, totals and every line."""
    by_employee: dict[str, dict[str, Any]] = {}
    for row in rows:
        emp = by_employee.setdefault(
            str(row.get("employee_id") or row.get("employee")),
            {
                "employee_id": row.get("employee_id"),
                "employee_number": row.get("employee_number"),
                "employee": row.get("employee"),
                "lines": [],
            },
        )
        emp["lines"].append(
            {
                k: row.get(k)
                for k in ("work_date", "project_id", "cost_code", "pay_type", "hours", "rate", "multiplier", "amount")
            }
        )
    payload = {
        "schema": "openconstructionerp.payroll_period/1",
        "period": dict(period),
        "employees": list(by_employee.values()),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _de_number(value: Any) -> str:
    return f"{Decimal(str(value)):.2f}".replace(".", ",")


def to_lodas(
    rows: Iterable[Mapping[str, Any]],
    *,
    period_start: date,
    consultant_number: str,
    client_number: str,
    lodas: Mapping[str, Any],
) -> bytes:
    """DATEV LODAS ASCII import file of standard movement data.

    One movement per employee, wage type and cost centre: hours for hour types,
    an amount for the per diem. The accounting month is the period's start month.
    """
    lohnart = lodas.get("lohnart") or {}
    bs_hours = str(lodas.get("bs_nr_hours") or "1")
    bs_amount = str(lodas.get("bs_nr_amount") or "3")
    agg: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        pay_type = str(row.get("pay_type") or "")
        wage_type = str(lohnart.get(pay_type) or "")
        if not wage_type:
            raise ValueError(f"No LODAS wage type mapped for pay type '{pay_type}'")
        pnr = str(row.get("employee_number") or "").strip()
        if not pnr:
            raise ValueError(f"Employee '{row.get('employee')}' has no personnel number for LODAS")
        is_amount = pay_type == "per_diem"
        value = Decimal(str(row.get("amount" if is_amount else "hours") or "0"))
        agg[(pnr, wage_type, bs_amount if is_amount else bs_hours, str(row.get("cost_code") or ""))] += value
    month = period_start.replace(day=1).strftime("%d/%m/%Y")
    lines = [
        "[Allgemein]",
        "Ziel=LODAS",
        "Version_SST=1.0",
        f"BeraterNr={consultant_number}",
        f"MandantenNr={client_number}",
        "Datumsformat=TT/MM/JJJJ",
        "Feldtrennzeichen=;",
        "Zahlenkomma=,",
        "",
        "[Satzbeschreibung]",
        "1;u_lod_bwd_buchung_standard;abrechnung_zeitraum#bwd;pnr#bwd;la_eigene#bwd;bs_nr#bwd;"
        "bs_wert_butab#bwd;kostenstelle#bwd;",
        "",
        "[Bewegungsdaten]",
    ]
    for (pnr, wage_type, bs_nr, cost_centre), value in sorted(agg.items()):
        lines.append(f"1;{month};{pnr};{wage_type};{bs_nr};{_de_number(value)};{cost_centre};")
    return ("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace")
