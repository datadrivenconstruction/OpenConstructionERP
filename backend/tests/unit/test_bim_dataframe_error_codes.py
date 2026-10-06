# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A refused property search carries a code, not only an English sentence.

The 400 ``detail`` used to be the store's message as a bare string, and the
panel rendered it as written, so an Italian reader got "Unknown column" and
"The > operator needs a number". The store now raises ``DataframeQueryError``
with a ``code`` (still a ``ValueError``, so existing callers keep working),
and the router returns ``{"code", "message", "params"}``; the panel picks its
own text by code.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.bim_hub import dataframe_store as ds
from app.modules.bim_hub import router as bim_router

ROWS: list[dict[str, Any]] = [
    {"id": 312001, "category": "Walls", "area": 12.5},
    {"id": 312002, "category": "Doors", "area": 4},
]


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    ds.write_dataframe("p1", "m1", ROWS, data_root=tmp_path)
    return tmp_path


@pytest.fixture(params=["duckdb", "pyarrow"])
def engine(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "pyarrow":
        monkeypatch.setitem(sys.modules, "duckdb", None)
    else:
        pytest.importorskip("duckdb")
    return request.param


def _refusal(data_root: Path, filters: list[dict[str, Any]]) -> ds.DataframeQueryError:
    with pytest.raises(ds.DataframeQueryError) as info:
        ds.query_parquet("p1", "m1", filters=filters, data_root=data_root)
    return info.value


@pytest.mark.parametrize(
    ("filters", "code", "params"),
    [
        ([{"column": "Area", "op": "=", "value": "1"}], "unknown_column", {"column": "Area"}),
        ([{"column": "area", "op": ">", "value": "big"}], "needs_number", {"op": ">"}),
        ([{"column": "area", "op": "~", "value": "x"}], "unsupported_operator", {"op": "~"}),
        ([{"column": "area", "op": "IN", "value": "x"}], "needs_list", {"op": "IN"}),
        ([{"column": "area", "op": "=", "value": ["x"]}], "needs_single_value", {"op": "="}),
        ([{"column": "area"}], "bad_filter", {}),
    ],
)
def test_each_refusal_names_its_code(
    data_root: Path, engine: str, filters: list[dict[str, Any]], code: str, params: dict[str, str]
) -> None:
    err = _refusal(data_root, filters)
    assert isinstance(err, ValueError)
    assert (err.code, err.params) == (code, params)


def test_a_duckdb_failure_is_query_failed(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    duckdb = pytest.importorskip("duckdb")

    class _Conn:
        def execute(self, *_a: Any, **_k: Any) -> Any:
            raise duckdb.BinderException("Binder Error: simulated")

        def close(self) -> None:
            return None

    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: _Conn())
    err = _refusal(data_root, [{"column": "area", "op": "=", "value": "1"}])
    assert err.code == "query_failed"
    with pytest.raises(ds.DataframeQueryError) as info:
        ds.column_value_counts("p1", "m1", "area", data_root=data_root)
    assert info.value.code == "query_failed"


def test_value_counts_unknown_column_is_coded(data_root: Path) -> None:
    with pytest.raises(ds.DataframeQueryError) as info:
        ds.column_value_counts("p1", "m1", "nope", data_root=data_root)
    assert (info.value.code, info.value.params) == ("unknown_column", {"column": "nope"})


async def test_the_query_route_returns_the_code_in_the_400(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_id = uuid.uuid4()

    async def _access(_service: Any, _model_id: Any, _user: Any) -> Any:
        return SimpleNamespace(project_id="p1")

    real_query = ds.query_parquet

    def _query(project_id: str, _model: str, **kwargs: Any) -> Any:
        return real_query(project_id, "m1", data_root=data_root, **kwargs)

    monkeypatch.setattr(bim_router, "_verify_model_access", _access)
    monkeypatch.setattr(ds, "query_parquet", _query)
    body = {"filters": [{"column": "area", "op": ">", "value": "1.234,56"}]}
    with pytest.raises(HTTPException) as info:
        await bim_router.query_dataframe(model_id, body, service=None, _user="u1")  # type: ignore[arg-type]
    assert info.value.status_code == 400
    assert info.value.detail["code"] == "needs_number"
    assert info.value.detail["params"] == {"op": ">"}
    assert "needs a number" in info.value.detail["message"]


async def test_the_values_route_returns_the_code_in_the_400(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _access(_service: Any, _model_id: Any, _user: Any) -> Any:
        return SimpleNamespace(project_id="p1")

    real_counts = ds.column_value_counts

    def _counts(project_id: str, _model: str, **kwargs: Any) -> Any:
        return real_counts(project_id, "m1", data_root=data_root, **kwargs)

    monkeypatch.setattr(bim_router, "_verify_model_access", _access)
    monkeypatch.setattr(ds, "column_value_counts", _counts)
    with pytest.raises(HTTPException) as info:
        await bim_router._column_value_counts(None, uuid.uuid4(), "u1", "nope", 10)  # type: ignore[arg-type]
    assert info.value.status_code == 400
    assert info.value.detail == {
        "code": "unknown_column",
        "message": "Unknown column: 'nope'. The model has no property with that name.",
        "params": {"column": "nope"},
    }
