"""Model data export: one row per element, properties and quantities flattened."""

from __future__ import annotations

import csv
import io
import json
import types
import uuid

import pytest
from openpyxl import load_workbook

from app.modules.bim_hub.exporters.elements import (
    ELEMENT_EXPORT_FORMATS,
    build_elements_export,
)


def _el(stable_id, etype, **kw):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        stable_id=stable_id,
        element_type=etype,
        name=kw.get("name"),
        storey=kw.get("storey"),
        discipline=kw.get("discipline"),
        properties=kw.get("properties", {}),
        quantities=kw.get("quantities", {}),
    )


ELEMENTS = [
    _el("w1", "Walls", name="Wall A", storey="L1", properties={"Material": "Concrete"}, quantities={"area_m2": 12.5}),
    _el("s1", "Slabs", name="=HYPERLINK(x)", storey="L2", properties={"Fire": "REI60"}, quantities={"volume_m3": 3.2}),
]


def test_formats_are_csv_json_xlsx():
    assert set(ELEMENT_EXPORT_FORMATS) == {"csv", "json", "xlsx"}


def test_csv_has_fixed_columns_then_property_and_quantity_columns():
    data, media = build_elements_export(ELEMENTS, "csv")
    assert media.startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert len(rows) == 2
    by_id = {r["element_id"]: r for r in rows}
    rows = [by_id["w1"], by_id["s1"]]
    assert rows[0]["element_id"] == "w1"
    assert rows[0]["category"] == "Walls"
    assert rows[0]["level"] == "L1"
    assert rows[0]["prop:Material"] == "Concrete"
    assert rows[0]["qty:area_m2"] == "12.5"
    assert rows[1]["qty:volume_m3"] == "3.2"
    assert rows[1]["qty:area_m2"] == ""


def test_csv_neutralises_formula_cells():
    data, _ = build_elements_export(ELEMENTS, "csv")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert {r["name"] for r in rows} == {"Wall A", "'=HYPERLINK(x)"}


def test_json_keeps_structure():
    data, media = build_elements_export(ELEMENTS, "json")
    assert media == "application/json"
    payload = json.loads(data)
    assert payload["count"] == 2
    first = next(e for e in payload["elements"] if e["element_id"] == "w1")
    assert first["properties"] == {"Material": "Concrete"}
    assert first["quantities"] == {"area_m2": 12.5}


def test_xlsx_numbers_stay_numbers():
    data, media = build_elements_export(ELEMENTS, "xlsx")
    assert "spreadsheetml" in media
    ws = load_workbook(io.BytesIO(data)).active
    header = [c.value for c in ws[1]]
    col = header.index("qty:area_m2") + 1
    values = [ws.cell(row=r, column=col).value for r in (2, 3)]
    assert 12.5 in values


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        build_elements_export(ELEMENTS, "pdf")


def test_empty_model_still_yields_header():
    data, _ = build_elements_export([], "csv")
    assert data.decode("utf-8-sig").splitlines()[0].startswith("element_id,")
