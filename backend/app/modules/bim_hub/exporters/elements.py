"""Model data export: one row per element as CSV, JSON or XLSX.

A pure projection of ``BIMElement`` rows: fixed identity columns first, then one
``prop:<name>`` column per property key and one ``qty:<name>`` column per quantity
key found in the selection. No SQL here: the service pages the elements in and the writers
stream them out (CSV, JSON); XLSX is built in memory for a capped selection.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import IO, Any

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


def columns(elements: Iterable[Any], props: dict[str, None] | None = None, qtys: dict[str, None] | None = None):
    """Property and quantity keys of ``elements``, merged into ``props``/``qtys`` (pass them again for each page)."""
    props = {} if props is None else props
    qtys = {} if qtys is None else qtys
    for el in elements:
        props.update(dict.fromkeys((el.properties or {}).keys()))
        qtys.update(dict.fromkeys((el.quantities or {}).keys()))
    return props, qtys


def header(props: Iterable[str], qtys: Iterable[str]) -> list[str]:
    return [*_FIXED, *(f"prop:{p}" for p in sorted(props)), *(f"qty:{q}" for q in sorted(qtys))]


def _row(el: Any, props: list[str], qtys: list[str]) -> list[Any]:
    p, q = el.properties or {}, el.quantities or {}
    return [
        el.stable_id,
        el.element_type,
        el.name,
        el.storey,
        el.discipline,
        *(_scalar(p.get(k)) for k in props),
        *(_scalar(q.get(k)) for k in qtys),
    ]


def safe_cell(value: Any) -> Any:
    """A cell a spreadsheet cannot run: a leading = + - @ tab or CR gets an apostrophe."""
    return neutralise_formula(_scalar(value))


class CsvWriter:
    """Writes the header once, then pages of elements, to a text stream."""

    def __init__(self, out: IO[str], props: Iterable[str], qtys: Iterable[str]) -> None:
        self.props, self.qtys = sorted(props), sorted(qtys)
        self.w = csv.writer(out)
        self.w.writerow([safe_cell(h) for h in header(self.props, self.qtys)])

    def write(self, elements: Iterable[Any]) -> None:
        for el in elements:
            self.w.writerow(["" if v is None else neutralise_formula(v) for v in _row(el, self.props, self.qtys)])


def _json_element(e: Any) -> dict[str, Any]:
    return {
        "element_id": e.stable_id,
        "category": e.element_type,
        "name": e.name,
        "level": e.storey,
        "discipline": e.discipline,
        "properties": e.properties or {},
        "quantities": e.quantities or {},
    }


class JsonWriter:
    """``{"elements": [...], "count": n}`` written element by element; ``close`` ends it."""

    def __init__(self, out: IO[str]) -> None:
        self.out, self.n = out, 0
        out.write('{"elements": [')

    def write(self, elements: Iterable[Any]) -> None:
        for e in elements:
            self.out.write(("," if self.n else "") + json.dumps(_json_element(e), ensure_ascii=False, default=str))
            self.n += 1

    def close(self) -> None:
        self.out.write(f'], "count": {self.n}}}')


def build_xlsx(elements: list[Any]) -> bytes:
    """A workbook of a bounded selection (the caller caps the row count)."""
    from openpyxl import Workbook

    props, qtys = columns(elements)
    p, q = sorted(props), sorted(qtys)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Elements")
    ws.append([safe_cell(h) for h in header(p, q)])
    for el in elements:
        ws.append([neutralise_formula(v) for v in _row(el, p, q)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _order(elements: Iterable[Any]) -> list[Any]:
    return sorted(elements, key=lambda e: (str(e.element_type or ""), str(e.stable_id or "")))


def build_elements_export(elements: Iterable[Any], fmt: str) -> tuple[bytes, str]:
    """Return ``(file_bytes, media_type)`` for an in-memory selection; ``ValueError`` for an unknown format."""
    if fmt not in ELEMENT_EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt}")
    els = _order(elements)
    if fmt == "xlsx":
        return build_xlsx(els), _MEDIA[fmt]
    buf = io.StringIO()
    if fmt == "json":
        jw = JsonWriter(buf)
        jw.write(els)
        jw.close()
        return buf.getvalue().encode("utf-8"), _MEDIA[fmt]
    props, qtys = columns(els)
    CsvWriter(buf, props, qtys).write(els)
    return buf.getvalue().encode("utf-8-sig"), _MEDIA[fmt]


def media_type(fmt: str) -> str:
    return _MEDIA[fmt]
