# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Property search over column names and cell text straight from a CAD export.

Every sidecar column name is a CAD header, so it is text the person who built
the model chose: an imperial inch mark (``diameter 1"``), a balanced quote that
closes the identifier and adds SQL, two headers differing only by case, an
empty header. The DuckDB path interpolates column names into SQL (values bind
as parameters), so each name is quoted by one helper, and names DuckDB cannot
address exactly fall back to the pyarrow engine.

The second half pins the two engines to each other on cell text: number
parsing, padding and lower-casing. Where they still differ the case is listed
in ``KNOWN_DIFFERENCES`` so a change on either side shows up here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from app.modules.bim_hub import dataframe_store as ds

duckdb = pytest.importorskip("duckdb")


@pytest.fixture(params=["duckdb", "pyarrow"])
def engine(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "pyarrow":
        monkeypatch.setitem(sys.modules, "duckdb", None)
    return request.param


def _write(root: Path, rows: list[dict[str, Any]]) -> Path:
    ds.write_dataframe("p", "m", rows, data_root=root)
    return root


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(str(r["id"]) for r in rows)


def _query(root: Path, column: str, op: str, value: Any = None) -> list[str]:
    flt: dict[str, Any] = {"column": column, "op": op}
    if value is not None:
        flt["value"] = value
    return _ids(ds.query_parquet("p", "m", columns=["id"], filters=[flt], data_root=root))


def _both(root: Path, column: str, op: str, value: Any = None) -> tuple[list[str], list[str]]:
    duck = _query(root, column, op, value)
    saved = sys.modules.get("duckdb")
    sys.modules["duckdb"] = None  # type: ignore[assignment]
    try:
        arrow = _query(root, column, op, value)
    finally:
        sys.modules["duckdb"] = saved  # type: ignore[assignment]
    return duck, arrow


# ── Column names ───────────────────────────────────────────────────────────

BALANCED_QUOTE = "empty\" AS VARCHAR))), '') = ? OR 1=1 OR ''=NULLIF(lower(trim(CAST(\"empty"

ODD_COLUMNS = [
    'diameter 1" nominal',
    "x\" = '1' OR \"id",
    BALANCED_QUOTE,
    '""',
    "width/height",
    "pset_wallcommon.firerating",
    "[ifc] name",
    "costo %",
    "back\\slash",
    "phase\ncreated",
    "größe ß",
]


@pytest.mark.parametrize("col", ODD_COLUMNS, ids=range(len(ODD_COLUMNS)))
def test_any_header_can_be_searched(tmp_path: Path, engine: str, col: str) -> None:
    root = _write(tmp_path, [{"id": 1, col: "A"}, {"id": 2, col: "b"}])
    assert _query(root, col, "=", "a") == ["1"]
    assert _query(root, col, "LIKE", "B") == ["2"]


@pytest.mark.parametrize("col", ODD_COLUMNS, ids=range(len(ODD_COLUMNS)))
def test_any_header_lists_its_values(tmp_path: Path, engine: str, col: str) -> None:
    root = _write(tmp_path, [{"id": 1, col: "A"}, {"id": 2, col: "b"}])
    assert sorted(o["value"] for o in ds.column_value_counts("p", "m", col, data_root=root)) == ["A", "b"]


@pytest.mark.parametrize("col", ODD_COLUMNS, ids=range(len(ODD_COLUMNS)))
def test_any_header_can_be_selected(tmp_path: Path, engine: str, col: str) -> None:
    root = _write(tmp_path, [{"id": 1, col: "A"}])
    rows = ds.query_parquet("p", "m", columns=["id", col], data_root=root)
    assert rows == [{"id": "1", col: "A"}]


def test_a_header_cannot_add_sql_to_the_query(tmp_path: Path, engine: str) -> None:
    """The crafted column is empty, so ``= 'zzz'`` must find nothing.

    Before the identifiers were quoted, the header closed the quoted name and
    its ``OR 1=1`` returned the row with the secret.
    """
    root = _write(tmp_path, [{"id": 1, "secret": "TOPSECRET", BALANCED_QUOTE: None}])
    assert _query(root, BALANCED_QUOTE, "=", "zzz") == []


def test_a_header_cannot_read_another_file(tmp_path: Path, engine: str) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_text("token\nTOPSECRET\n", encoding="utf-8")
    path = str(secret).replace("\\", "/")
    evil = f"a\" IS NOT NULL OR (SELECT count(*) FROM read_csv_auto('{path}') WHERE token = 'TOPSECRET') > 0 OR \"a"
    root = _write(tmp_path / "model", [{"id": 1, evil: None, "a": None}])
    # IS NOT NULL on an all-empty column is empty; a hit means the header ran SQL.
    assert _query(root, evil, "IS NOT NULL") == []


def test_headers_that_differ_only_by_case_are_told_apart(tmp_path: Path, engine: str) -> None:
    """DuckDB matches identifiers case-insensitively and renames the twin ``Name_1``.

    Querying ``"Name"`` there silently read ``name``: a wrong answer, not an
    error. Such columns go to the pyarrow engine, which reads names exactly.
    """
    root = _write(tmp_path, [{"id": 1, "name": "x", "Name": "y"}, {"id": 2, "name": "y", "Name": "x"}])
    assert _query(root, "Name", "=", "y") == ["1"]
    assert _query(root, "name", "=", "y") == ["2"]
    assert [o["value"] for o in ds.column_value_counts("p", "m", "Name", data_root=root)] == ["x", "y"]
    rows = ds.query_parquet(
        "p", "m", columns=["id", "Name"], filters=[{"column": "Name", "op": "=", "value": "y"}], data_root=root
    )
    assert rows == [{"id": "1", "Name": "y"}]


def test_an_empty_header_is_searchable(tmp_path: Path, engine: str) -> None:
    root = _write(tmp_path, [{"id": 1, "": "x"}, {"id": 2, "": "y"}])
    assert _query(root, "", "=", "x") == ["1"]
    assert [o["value"] for o in ds.column_value_counts("p", "m", "", data_root=root)] == ["x", "y"]


# ── Cell text: the engines agree ───────────────────────────────────────────

ROUND_TRIP_CELLS = [
    "İç duvar",
    "ΣΑΣ",
    "Straße",
    "  Progetto\t",
    "DEMOLIZIONE È",
    "١٢",
    "1_000",
    "Muro [30 cm] 50% REI",
]


@pytest.mark.parametrize("cell", ROUND_TRIP_CELLS, ids=range(len(ROUND_TRIP_CELLS)))
def test_a_value_from_the_dropdown_finds_its_own_rows(tmp_path: Path, cell: str) -> None:
    """Picking a value the values endpoint listed must find that value with ``=``.

    "İç duvar" and "ΣΑΣ" used to fail even on DuckDB alone: the filter value
    was lowered by Python ("i̇ç duvar", "σας") and the cell by DuckDB
    ("iç duvar", "σασ").
    """
    root = _write(tmp_path, [{"id": 1, "v": cell}, {"id": 2, "v": "other"}])
    for value in (o["value"] for o in ds.column_value_counts("p", "m", "v", data_root=root)):
        if value == "other":
            continue
        duck, arrow = _both(root, "v", "=", value)
        assert duck == ["1"], f"duckdb lost {value!r}"
        assert arrow == ["1"], f"pyarrow lost {value!r}"


@pytest.mark.parametrize(
    ("cell", "value"),
    [
        ("Progetto\t", "progetto"),
        (" Progetto", "PROGETTO"),
        ("Progetto\n", " progetto "),
        ("İSTANBUL", "istanbul"),
        ("ΣΑΣ", "σασ"),
    ],
)
def test_padding_and_case_read_the_same_on_both_engines(tmp_path: Path, cell: str, value: str) -> None:
    root = _write(tmp_path, [{"id": 1, "v": cell}])
    assert _both(root, "v", "=", value) == (["1"], ["1"])
    assert _both(root, "v", "LIKE", value[1:-1] if len(value) > 2 else value) == (["1"], ["1"])


NUMBER_CELLS = [
    "1_000",
    "1__000",
    "_1000",
    "1000_",
    "1_000.5",
    "1.0_5",
    "1e1_0",
    "1._5",
    "1_.5",
    "0x10",
    "Infinity",
    "nan",
    "+.5",
    "12.",
    "1,5e3",
    "١٢",
    " 12 ",
    "\t12\t",
    " 12",
    "12 m",
    "-0",
    "1.",
    "..5",
    "1e",
    "e3",
    "00012",
    "1 000",
    "+-1",
]

# Where DuckDB's TRY_CAST accepts text the fallback refuses. DuckDB is the
# engine every installation ships; the fallback only runs without it.
KNOWN_DIFFERENCES = {"+-1"}


@pytest.mark.parametrize("cell", NUMBER_CELLS, ids=range(len(NUMBER_CELLS)))
def test_numbers_read_the_same_on_both_engines(tmp_path: Path, cell: str) -> None:
    root = _write(tmp_path, [{"id": 1, "v": cell}])
    duck, arrow = _both(root, "v", ">", "-1000000")
    if cell in KNOWN_DIFFERENCES:
        assert duck != arrow, f"{cell!r} now reads the same on both engines; drop it from KNOWN_DIFFERENCES"
    else:
        assert duck == arrow, f"{cell!r}: duckdb={duck} pyarrow={arrow}"


def test_underscore_grouping_reads_as_a_number_on_both_engines(tmp_path: Path) -> None:
    root = _write(tmp_path, [{"id": 1, "v": "1_000"}, {"id": 2, "v": "1__000"}])
    assert _both(root, "v", ">", "999") == (["1"], ["1"])


def test_arabic_indic_digits_are_not_a_number_on_either_engine(tmp_path: Path) -> None:
    root = _write(tmp_path, [{"id": 1, "v": "١٢"}])
    assert _both(root, "v", "=", "12") == ([], [])


# ── Reading a few cells for the rule engine ────────────────────────────────


def test_element_cells_resolve_keys_like_the_rule_engine(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        [
            {"id": "101", "phase created": "Progetto", "fase restauro": " Consolidamento ", "other": "x"},
            {"id": "102", "phase created": "Stato di fatto", "fase restauro": None, "other": "y"},
            {"id": "103", "phase created": "Progetto", "fase restauro": "Nuovo", "other": "z"},
        ],
    )
    columns, cells = ds.read_element_cells(
        "p", "m", keys=["Phase Created", " FASE RESTAURO ", "missing key"], ids=["101", "102"], data_root=root
    )
    assert columns == {"Phase Created": "phase created", " FASE RESTAURO ": "fase restauro"}
    # The writer trims cells, so the padded value comes back trimmed.
    assert cells == {
        "101": {"phase created": "Progetto", "fase restauro": "Consolidamento"},
        "102": {"phase created": "Stato di fatto", "fase restauro": None},
    }


def test_element_cells_read_only_the_columns_asked_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write(tmp_path, [{"id": "1", "a": "x", **{f"c{i}": "v" for i in range(50)}}])
    seen: list[list[str] | None] = []
    real = ds.pq.ParquetFile.iter_batches

    def spy(self: Any, *args: Any, columns: list[str] | None = None, **kw: Any) -> Any:
        seen.append(columns)
        return real(self, *args, columns=columns, **kw)

    monkeypatch.setattr(ds.pq.ParquetFile, "iter_batches", spy)
    ds.read_element_cells("p", "m", keys=["A"], ids=["1"], data_root=root)
    assert seen == [["id", "a"]]


def test_element_cells_without_a_sidecar_or_id_column_are_empty(tmp_path: Path) -> None:
    assert ds.read_element_cells("p", "m", keys=["a"], ids=["1"], data_root=tmp_path) == ({}, {})
    root = _write(tmp_path / "noid", [{"name": "x", "a": "1"}])
    assert ds.read_element_cells("p", "m", keys=["a"], ids=["1"], data_root=root) == ({}, {})


def test_element_cells_pair_a_retried_sidecar_by_stable_id(tmp_path: Path) -> None:
    """The Parquet retry rebuilds the sidecar from database rows and writes no ``id`` column."""
    root = _write(tmp_path, [{"stable_id": "guid-1", "element_type": "Walls", "a": "x"}])
    assert ds.read_element_cells("p", "m", keys=["a"], ids=["guid-1"], data_root=root) == (
        {"a": "a"},
        {"guid-1": {"a": "x"}},
    )


def test_element_cells_match_a_case_twin_by_its_exact_name(tmp_path: Path) -> None:
    root = _write(tmp_path, [{"id": "1", "mark": "lower", "Mark": "upper"}])
    columns, cells = ds.read_element_cells("p", "m", keys=["Mark", "MARK"], ids=["1"], data_root=root)
    assert columns == {"Mark": "Mark", "MARK": "mark"}
    assert cells == {"1": {"Mark": "upper", "mark": "lower"}}
