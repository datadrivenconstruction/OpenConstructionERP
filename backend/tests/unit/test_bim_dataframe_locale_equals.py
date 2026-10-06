# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Property search "=" / "!=" with a number read in the user's convention.

``=`` matches the text, or the number when the value reads as one. The
server read the typed text as a number itself, dot-decimal, so an Italian
"= 1.500" (fifteen hundred) matched the cells holding 1.5: a wrong result, not
a missed one. The panel now reads the number in the user's convention and
sends it next to the text as ``number``. When ``number`` is in the filter the
store matches the text or that number, and never reads the text as a number
of its own; ``number: null`` says the text is no number at all. A filter
without the key behaves as before, for other API clients.

Each case runs on DuckDB and on the pyarrow fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from app.modules.bim_hub import dataframe_store as ds

AREAS = {
    "e1500": "1500",
    "e1500f": "1500.0",
    "e1_5": "1.5",
    "e1_50": "1.50",
    "emuro": "Muro 1.500",
    "eempty": None,
}


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    rows = [{"id": k, "area": v} for k, v in AREAS.items()]
    ds.write_dataframe("p1", "m1", rows, data_root=tmp_path)
    return tmp_path


@pytest.fixture(params=["duckdb", "pyarrow"])
def engine(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "pyarrow":
        monkeypatch.setitem(sys.modules, "duckdb", None)
    else:
        pytest.importorskip("duckdb")
    return request.param


def _ids(data_root: Path, f: dict[str, Any]) -> set[str]:
    rows = ds.query_parquet("p1", "m1", columns=["id"], filters=[{"column": "area", **f}], data_root=data_root)
    return {r["id"] for r in rows}


ALL = set(AREAS)

# (what the panel sends, the elements "=" finds)
CASES = [
    # Italian "1.500": fifteen hundred, never 1.5.
    pytest.param({"value": "1.500", "number": 1500}, {"e1500", "e1500f"}, id="italian-1.500"),
    # English "1.500": one and a half.
    pytest.param({"value": "1.500", "number": 1.5}, {"e1_5", "e1_50"}, id="english-1.500"),
    # Text that is no number stays text, digits inside or not.
    pytest.param({"value": "Muro 1.500", "number": None}, {"emuro"}, id="text-with-a-number-in-it"),
    # The literal text still matches a cell written the same way.
    pytest.param({"value": "1.50", "number": 1.5}, {"e1_5", "e1_50"}, id="text-or-number"),
]


@pytest.mark.parametrize(("sent", "found"), CASES)
def test_equals_matches_the_text_or_the_number_the_user_meant(
    data_root: Path, engine: str, sent: dict[str, Any], found: set[str]
) -> None:
    assert _ids(data_root, {"op": "=", **sent}) == found


@pytest.mark.parametrize(("sent", "found"), CASES)
def test_not_equals_is_the_rest_including_empty_cells(
    data_root: Path, engine: str, sent: dict[str, Any], found: set[str]
) -> None:
    assert _ids(data_root, {"op": "!=", **sent}) == ALL - found


def test_a_filter_without_number_reads_as_before(data_root: Path, engine: str) -> None:
    # Other API clients send only the text; the store still reads it dot-decimal.
    assert _ids(data_root, {"op": "=", "value": "1.500"}) == {"e1_5", "e1_50"}


@pytest.mark.parametrize("number", ["1500", True, [1500], float("inf")])
def test_number_must_be_a_json_number(data_root: Path, engine: str, number: Any) -> None:
    with pytest.raises(ds.DataframeQueryError) as info:
        _ids(data_root, {"op": "=", "value": "1.500", "number": number})
    assert info.value.code == "needs_number"
