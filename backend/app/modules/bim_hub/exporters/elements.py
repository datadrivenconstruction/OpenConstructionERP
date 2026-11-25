"""Model data export: one row per element as CSV, JSON or XLSX.

A pure projection of ``BIMElement`` rows: fixed identity columns first, then one
``prop:<name>`` column per property key and one ``qty:<name>`` column per quantity
key found in the selection. No SQL here; the service loads the elements.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import Any

from app.core.csv_safety import neutralise_formula

ELEMENT_EXPORT_FORMATS = ("csv", "json", "xlsx")
_FIXED = ("element_id", "category", "name", "level", "discipline")
_MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bool):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _columns(elements: list[Any]) -> tuple[list[str], list[str]]:
    props: dict[str, None] = {}
    qtys: dict[str, None] = {}
    for el in elements:
        props.update(dict.fromkeys((el.properties or {}).keys()))
        qtys.update(dict.fromkeys((el.quantities or {}).keys()))
    return sorted(props), sorted(qtys)


def _rows(elements: list[Any]) -> tuple[list[str], list[list[Any]]]:
    props, qtys = _columns(elements)
    header = [*_FIXED, *(f"prop:{p}" for p in props), *(f"qty:{q}" for q in qtys)]
    rows = []
    for el in elements:
        p, q = el.properties or {}, el.quantities or {}
        rows.append(
            [
                el.stable_id,
                el.element_type,
                el.name,
                el.storey,
                el.discipline,
                *(_scalar(p.get(k)) for k in props),
                *(_scalar(q.get(k)) for k in qtys),
            ]
        )
    return header, rows


def build_elements_export(elements: Iterable[Any], fmt: str) -> tuple[bytes, str]:
    """Return ``(file_bytes, media_type)``; ``ValueError`` for an unknown format."""
    if fmt not in ELEMENT_EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt}")
    els = sorted(elements, key=lambda e: (str(e.element_type or ""), str(e.stable_id or "")))
    if fmt == "json":
        payload = {
            "count": len(els),
            "elements": [
                {
                    "element_id": e.stable_id,
                    "category": e.element_type,
                    "name": e.name,
                    "level": e.storey,
                    "discipline": e.discipline,
                    "properties": e.properties or {},
                    "quantities": e.quantities or {},
                }
                for e in els
            ],
        }
        return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), _MEDIA[fmt]

    header, rows = _rows(els)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else neutralise_formula(v) for v in r])
        return buf.getvalue().encode("utf-8-sig"), _MEDIA[fmt]

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Elements"
    ws.append(header)
    for r in rows:
        ws.append([neutralise_formula(v) for v in r])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), _MEDIA[fmt]
