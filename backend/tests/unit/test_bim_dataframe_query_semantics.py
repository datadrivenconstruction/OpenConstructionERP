# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the BIM property search means by each operator, on both engines.

The property search panel in the BIM viewer sends ``column / op / value``
filters to ``dataframe_store.query_parquet``. Every Parquet column is stored as
text (``write_dataframe`` forces ``pa.string()``), so the operators have to say
what they do with text that came out of a Revit export:

* ``LIKE`` is "contains": case-insensitive, the value is wrapped in ``%`` by
  the store, and ``%`` / ``_`` typed by the user are literal characters.
* ``=`` and ``!=`` compare trimmed, case-insensitive text, and numerically when
  both sides read as numbers ("8" equals "8.0").
* ``!=`` keeps elements where the property is empty: "phase is not
  Progetto" includes an element with no phase at all.
* ``>``, ``>=``, ``<``, ``<=`` compare numbers, accepting a decimal comma
  ("12,5") on either side. A value that is not a number is a 400, not a 500.
* An unknown column, or anything DuckDB refuses, is a ``ValueError`` (a
  ``DataframeQueryError``; the router turns it into a 400 whose detail carries
  a code, see ``test_bim_dataframe_error_codes``).

DuckDB is the production engine; the pyarrow fallback runs when DuckDB is not
installed. Each case runs on both, because two engines that disagree on the
same filter make the same click return different elements on two installs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from app.modules.bim_hub import dataframe_store as ds

ROWS: list[dict[str, Any]] = [
    {"id": 312001, "category": "Walls", "phase created": "Stato di fatto", "area": 12.5, "fire": "REI 50% test"},
    {"id": 312002, "category": "Walls", "phase created": "Progetto", "area": 8.0, "fire": "REI 500"},
    {"id": 312003, "category": "Walls", "phase created": " New Construction ", "area": "12,5", "fire": "REI_60"},
    {"id": 312004, "category": "Doors", "phase created": "PROGETTO", "area": None, "fire": "REI X60"},
    {"id": 312005, "category": "Doors", "phase created": None, "area": "4", "fire": None},
]


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    ds.write_dataframe("p1", "m1", ROWS, data_root=tmp_path)
    return tmp_path


@pytest.fixture(params=["duckdb", "pyarrow"])
def engine(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "pyarrow":
        # ``import duckdb`` inside query_parquet raises ImportError when the
        # module entry is None, which is exactly the "not installed" branch.
        monkeypatch.setitem(sys.modules, "duckdb", None)
    else:
        pytest.importorskip("duckdb")
    return request.param


def _ids(data_root: Path, column: str, op: str, value: Any) -> list[str]:
    rows = ds.query_parquet(
        "p1",
        "m1",
        columns=["id"],
        filters=[{"column": column, "op": op, "value": value}],
        limit=100,
        data_root=data_root,
    )
    return sorted(str(r["id"]) for r in rows)


# ── contains ──────────────────────────────────────────────────────────────


def test_contains_is_case_insensitive_and_wraps_the_value(data_root: Path, engine: str) -> None:
    assert _ids(data_root, "phase created", "LIKE", "prog") == ["312002", "312004"]


def test_contains_treats_percent_and_underscore_as_literal(data_root: Path, engine: str) -> None:
    assert _ids(data_root, "fire", "LIKE", "50%") == ["312001"]
    assert _ids(data_root, "fire", "LIKE", "REI_6") == ["312003"]


# ── equality ──────────────────────────────────────────────────────────────


def test_equals_ignores_case_and_surrounding_whitespace(data_root: Path, engine: str) -> None:
    assert _ids(data_root, "phase created", "=", "  stato di fatto ") == ["312001"]
    assert _ids(data_root, "phase created", "=", "new construction") == ["312003"]
    assert _ids(data_root, "phase created", "=", "Progetto") == ["312002", "312004"]


def test_equals_compares_numbers_as_numbers(data_root: Path, engine: str) -> None:
    assert _ids(data_root, "area", "=", 8) == ["312002"]
    assert _ids(data_root, "area", "=", "12,5") == ["312001", "312003"]


def test_not_equals_keeps_elements_where_the_property_is_empty(data_root: Path, engine: str) -> None:
    assert _ids(data_root, "phase created", "!=", "progetto") == ["312001", "312003", "312005"]


# ── numeric comparison ───────────────────────────────────────────────────


def test_greater_than_reads_a_decimal_comma_in_the_data(data_root: Path, engine: str) -> None:
    assert _ids(data_root, "area", ">", 10) == ["312001", "312003"]


def test_numeric_value_typed_with_a_decimal_comma(data_root: Path, engine: str) -> None:
    assert _ids(data_root, "area", ">=", "12,5") == ["312001", "312003"]
    assert _ids(data_root, "area", "<", "8,5") == ["312002", "312005"]


def test_numeric_operator_with_text_value_is_a_value_error(data_root: Path, engine: str) -> None:
    with pytest.raises(ValueError, match="number"):
        _ids(data_root, "area", ">", "big")


# ── refusals ─────────────────────────────────────────────────────────────


def test_unknown_column_is_a_value_error(data_root: Path, engine: str) -> None:
    with pytest.raises(ValueError, match="Unknown column"):
        _ids(data_root, "Phase Created", "=", "Progetto")


def test_unsupported_operator_is_a_value_error(data_root: Path, engine: str) -> None:
    with pytest.raises(ValueError):
        _ids(data_root, "area", "~", "x")


def test_a_duckdb_error_surfaces_as_value_error(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    duckdb = pytest.importorskip("duckdb")

    class _Conn:
        def execute(self, *_a: Any, **_k: Any) -> Any:
            raise duckdb.BinderException("Binder Error: simulated")

        def close(self) -> None:
            return None

    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: _Conn())
    with pytest.raises(ValueError, match="could not run"):
        _ids(data_root, "area", "=", "1")


# ── value counts for the dropdown ────────────────────────────────────────


def test_value_counts_list_every_distinct_value_with_its_count(data_root: Path, engine: str) -> None:
    counts = ds.column_value_counts("p1", "m1", "category", data_root=data_root)
    assert {c["value"]: c["count"] for c in counts} == {"Walls": 3, "Doors": 2}


def test_value_counts_unknown_column_is_a_value_error(data_root: Path) -> None:
    with pytest.raises(ValueError, match="Unknown column"):
        ds.column_value_counts("p1", "m1", "nope", data_root=data_root)


# ── display labels ───────────────────────────────────────────────────────


def test_schema_carries_the_original_header_as_label(tmp_path: Path) -> None:
    ds.write_dataframe(
        "p1",
        "m2",
        [{"id": 1, "phase created": "Progetto"}],
        data_root=tmp_path,
        labels={"phase created": "Phase Created", "id": "ID"},
    )
    schema = ds.read_schema("p1", "m2", data_root=tmp_path)
    assert {c["name"]: c["label"] for c in schema} == {"id": "ID", "phase created": "Phase Created"}


def test_schema_falls_back_to_the_key_when_no_label_was_stored(data_root: Path) -> None:
    schema = ds.read_schema("p1", "m1", data_root=data_root)
    assert all(c["label"] == c["name"] for c in schema)
    assert any(c["name"] == "phase created" for c in schema)


def test_cad_excel_headers_keep_their_original_text_as_labels(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from app.modules.boq.cad_import import parse_cad_excel, read_cad_excel_labels

    xlsx = tmp_path / "model_rvt.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Phase Created : String", "Area : Double", "Type Name"])
    ws.append([312001, "Stato di fatto", 12.5, "Muro 30"])
    wb.save(xlsx)

    # Keys stay lowercase: every downstream lookup and every saved rule uses them.
    assert parse_cad_excel(xlsx) == [
        {"id": 312001, "phase created": "Stato di fatto", "area": 12.5, "type name": "Muro 30"}
    ]
    assert read_cad_excel_labels(xlsx) == {
        "id": "ID",
        "phase created": "Phase Created",
        "area": "Area",
        "type name": "Type Name",
    }


def test_label_reader_is_best_effort(tmp_path: Path) -> None:
    from app.modules.boq.cad_import import read_cad_excel_labels

    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")
    assert read_cad_excel_labels(broken) == {}


def test_values_route_takes_the_column_as_a_query_parameter() -> None:
    from app.modules.bim_hub.router import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/models/{model_id}/dataframe/values/" in paths
    # The path-parameter form stays for existing callers.
    assert "/models/{model_id}/dataframe/columns/{column}/values/" in paths
