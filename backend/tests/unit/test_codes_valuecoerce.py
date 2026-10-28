# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure UDF typed-value coercion (T2.3, acceptance #4)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.modules.schedule.codes_valuecoerce import (
    _to_bool,
    coerce_udf_value,
    udf_value_readback,
)


def test_text_value_lands_in_text_column() -> None:
    cols = coerce_udf_value("text", None, "Tower A")
    assert cols == {"value_text": "Tower A", "value_number": None, "value_date": None, "value_bool": None}


def test_number_value_is_decimal() -> None:
    cols = coerce_udf_value("number", None, "42.50")
    assert cols["value_number"] == Decimal("42.50")
    assert cols["value_text"] is None


def test_number_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="not a number"):
        coerce_udf_value("number", None, "abc")


def test_date_value_round_trips_iso() -> None:
    cols = coerce_udf_value("date", None, "2026-06-23")
    assert cols["value_date"] == "2026-06-23"


def test_date_rejects_impossible_date() -> None:
    with pytest.raises(ValueError, match="ISO date"):
        coerce_udf_value("date", None, "2026-13-40")


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("false", False), (1, True), (0, False), ("yes", True)])
def test_bool_coercion(raw: object, expected: bool) -> None:
    assert coerce_udf_value("bool", None, raw)["value_bool"] is expected


def test_bool_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="boolean"):
        _to_bool("maybe")


def test_enum_accepts_allowed_value() -> None:
    cols = coerce_udf_value("enum", ["red", "amber", "green"], "amber")
    assert cols["value_text"] == "amber"


def test_enum_rejects_value_outside_set() -> None:
    with pytest.raises(ValueError, match="enum"):
        coerce_udf_value("enum", ["red", "amber", "green"], "purple")


def test_none_clears_all_columns() -> None:
    assert coerce_udf_value("text", None, None) == {
        "value_text": None,
        "value_number": None,
        "value_date": None,
        "value_bool": None,
    }


def test_empty_string_clears_value() -> None:
    assert coerce_udf_value("number", None, "")["value_number"] is None


def test_unknown_type_rejected() -> None:
    with pytest.raises(ValueError, match="unknown UDF value_type"):
        coerce_udf_value("geometry", None, "x")


@dataclass
class _Row:
    value_text: object = None
    value_number: object = None
    value_date: object = None
    value_bool: object = None


def test_readback_picks_the_typed_column() -> None:
    assert udf_value_readback("number", _Row(value_number=Decimal("7"))) == Decimal("7")
    assert udf_value_readback("date", _Row(value_date="2026-01-01")) == "2026-01-01"
    assert udf_value_readback("bool", _Row(value_bool=True)) is True
    assert udf_value_readback("text", _Row(value_text="hi")) == "hi"
    assert udf_value_readback("enum", _Row(value_text="amber")) == "amber"
