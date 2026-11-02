# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Weighbridge​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ and plant delivery ticket import (CSV or Excel).

The file is read into headers and rows, a column mapping is suggested from the
header names, the person corrects it, and the mapped rows become ticket drafts.
Duplicates are flagged against the file itself and against existing tickets: the
same haulier and ticket number, or the same plate, time out and net weight.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

from app.modules.haul_tickets.logic import dec

MAX_ROWS = 5000

TARGET_FIELDS = (
    "ticket_number",
    "ticket_date",
    "time_out",
    "time_in",
    "haulier_name",
    "plate",
    "driver_name",
    "material_code",
    "material_name",
    "origin",
    "destination",
    "gross_t",
    "tare_t",
    "net_t",
    "volume_m3",
    "loads",
    "rate",
    "waste_code",
    "receiving_facility",
    "cost_code",
    "notes",
)

# Header synonyms, lower case; the screen lets the person override every guess.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ticket_number": ("ticket", "ticket no", "ticket number", "docket", "delivery note", "note no", "slip", "number"),
    "ticket_date": ("date", "day", "delivery date"),
    "time_out": ("time out", "out", "departure", "weighed out", "exit"),
    "time_in": ("time in", "in", "arrival", "weighed in", "entry"),
    "haulier_name": ("haulier", "hauler", "carrier", "transport company", "contractor", "customer"),
    "plate": ("plate", "registration", "reg", "vehicle", "truck", "licence plate", "license plate"),
    "driver_name": ("driver",),
    "material_code": ("material code", "product code", "article"),
    "material_name": ("material", "product", "description", "grade"),
    "origin": ("origin", "from", "source", "quarry", "plant"),
    "destination": ("destination", "to", "site", "delivery address"),
    "gross_t": ("gross", "gross weight", "gross t", "gross kg"),
    "tare_t": ("tare", "tare weight", "tare t", "tare kg"),
    "net_t": ("net", "net weight", "net t", "net kg", "weight", "tonnes", "tons"),
    "volume_m3": ("volume", "m3", "cubic metres", "cubic meters", "cbm"),
    "loads": ("loads", "load count"),
    "rate": ("rate", "price", "unit price"),
    "waste_code": ("waste code", "ewc", "waste"),
    "receiving_facility": ("facility", "landfill", "receiving facility", "disposal site"),
    "cost_code": ("cost code", "cost centre", "cost center", "wbs"),
    "notes": ("notes", "remarks", "comment"),
}


def read_table(payload: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
    """Headers and string cells of the first sheet (Excel) or the CSV, delimiter sniffed."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [["" if c is None else _cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        text = payload.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return [], []
    headers = [str(h).strip() for h in rows[0]]
    return headers, [[str(c).strip() for c in r] for r in rows[1 : MAX_ROWS + 1]]


def _cell(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def suggest_mapping(headers: list[str]) -> dict[str, int]:
    """Target field -> column index, from exact then partial synonym matches."""
    low = [h.lower().strip() for h in headers]
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for exact in (True, False):
        for target, words in _SYNONYMS.items():
            if target in mapping:
                continue
            for i, h in enumerate(low):
                if i in used or not h:
                    continue
                hit = h in words if exact else any(len(w) > 2 and w in h for w in words)
                if hit:
                    mapping[target] = i
                    used.add(i)
                    break
    return mapping


def parse_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_date(value: str) -> date | None:
    text = (value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def map_rows(
    headers: list[str], rows: list[list[str]], mapping: dict[str, int], *, weights_in_kg: bool = False
) -> list[dict[str, Any]]:
    """Mapped rows as ticket drafts; weights in kilograms are converted to tonnes."""
    out: list[dict[str, Any]] = []
    for row in rows:

        def cell(field: str, _row: list[str] = row) -> str:
            idx = mapping.get(field)
            return _row[idx] if idx is not None and 0 <= idx < len(_row) else ""

        draft: dict[str, Any] = {f: cell(f) for f in TARGET_FIELDS}
        for w in ("gross_t", "tare_t", "net_t"):
            v = dec(draft[w])
            if v is not None and weights_in_kg:
                v = v / 1000
            draft[w] = v
        draft["volume_m3"] = dec(draft["volume_m3"])
        draft["rate"] = dec(draft["rate"])
        loads = dec(draft["loads"])
        draft["loads"] = int(loads) if loads is not None else 1
        t_out = parse_datetime(draft["time_out"])
        draft["time_out"] = t_out
        draft["time_in"] = parse_datetime(draft["time_in"])
        draft["ticket_date"] = parse_date(draft["ticket_date"]) or (t_out.date() if t_out else None)
        out.append(draft)
    return out


def dedupe_key(d: dict[str, Any]) -> tuple[str, str]:
    return (str(d.get("haulier_name") or "").strip().lower(), str(d.get("ticket_number") or "").strip().upper())


def fingerprint(d: dict[str, Any]) -> tuple[str, str, str] | None:
    plate = str(d.get("plate") or "").replace(" ", "").upper()
    t_out = d.get("time_out")
    net = d.get("net_t")
    if not plate or t_out is None or net is None:
        return None
    stamp = t_out.strftime("%Y-%m-%dT%H:%M") if isinstance(t_out, datetime) else str(t_out)[:16]
    return (plate, stamp, str(dec(net).quantize(dec("0.01"))))  # type: ignore[union-attr]


def mark_duplicates(drafts: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set ``duplicate`` to ``in_file`` / ``existing`` / None on each draft."""
    known_keys = {dedupe_key(e) for e in existing if e.get("ticket_number")}
    known_prints = {fp for e in existing if (fp := fingerprint(e)) is not None}
    seen_keys: set[tuple[str, str]] = set()
    seen_prints: set[tuple[str, str, str]] = set()
    for d in drafts:
        key = dedupe_key(d) if d.get("ticket_number") else None
        fp = fingerprint(d)
        if (key and key in known_keys) or (fp and fp in known_prints):
            d["duplicate"] = "existing"
        elif (key and key in seen_keys) or (fp and fp in seen_prints):
            d["duplicate"] = "in_file"
        else:
            d["duplicate"] = None
        if key:
            seen_keys.add(key)
        if fp:
            seen_prints.add(fp)
    return drafts
