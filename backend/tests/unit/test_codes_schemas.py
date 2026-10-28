# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the T2.3 layout-spec grammar and schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.schedule.codes_schemas import (
    LayoutSpec,
    UdfCreate,
    parse_layout_key,
)

_UUID = "123e4567-e89b-12d3-a456-426614174000"
_UUID2 = "123e4567-e89b-12d3-a456-426614174001"


def test_parse_static_key() -> None:
    assert parse_layout_key("total_float") == ("static", "total_float")


def test_parse_code_key() -> None:
    assert parse_layout_key(f"code:{_UUID}") == ("code", _UUID)


def test_parse_udf_key() -> None:
    assert parse_layout_key(f"udf:{_UUID}") == ("udf", _UUID)


def test_layout_accepts_static_and_namespaced_keys() -> None:
    spec = LayoutSpec(
        columns=[{"key": "name", "width": 280}, {"key": f"code:{_UUID}"}, {"key": f"udf:{_UUID2}"}],
        group_by=[{"key": f"code:{_UUID}", "color_band": True}, {"key": "status"}],
    )
    assert len(spec.columns) == 3
    assert len(spec.group_by) == 2


def test_layout_rejects_malformed_column_key() -> None:
    with pytest.raises(ValidationError):
        LayoutSpec(columns=[{"key": "Bad Key!"}])


def test_layout_rejects_dotted_key() -> None:
    with pytest.raises(ValidationError):
        LayoutSpec(group_by=[{"key": "project.owner_id"}])


def test_layout_group_by_capped_at_three_levels() -> None:
    with pytest.raises(ValidationError):
        LayoutSpec(
            group_by=[
                {"key": "name"},
                {"key": "wbs_code"},
                {"key": "status"},
                {"key": "activity_type"},
            ]
        )


def test_layout_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError):
        LayoutSpec(not_a_field=1)


def test_layout_default_is_empty_but_valid() -> None:
    spec = LayoutSpec()
    assert spec.timescale == "week"
    assert spec.columns == []
    assert spec.bar_style.show_critical is True


def test_udf_create_accepts_snake_case_key() -> None:
    udf = UdfCreate(key="area_code", value_type="number")
    assert udf.key == "area_code"
    assert udf.value_type == "number"


def test_udf_create_rejects_bad_key() -> None:
    with pytest.raises(ValidationError):
        UdfCreate(key="Bad Key", value_type="text")


def test_udf_create_rejects_unknown_value_type() -> None:
    with pytest.raises(ValidationError):
        UdfCreate(key="x", value_type="geojson")
