"""Weather and bulk-entry inputs are bounded so they cannot reach the DB column or the response as junk."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.daily_diary.router import bulk_create_entries
from app.modules.daily_diary.schemas import ProductivityFactorRequest, WeatherRecordCreate, WeatherRecordUpdate


@pytest.mark.parametrize(
    ("field", "value"),
    [("temperature_c", "99999999"), ("wind_speed_kmh", "100000"), ("precipitation_mm", "1e30")],
)
def test_weather_values_beyond_the_numeric_column_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        WeatherRecordCreate(project_id=uuid.uuid4(), captured_at=datetime.now(UTC), **{field: value})
    with pytest.raises(ValidationError):
        WeatherRecordUpdate(**{field: value})


@pytest.mark.parametrize(
    "kw",
    [{"temperature_c": float("nan")}, {"wind_speed_kmh": float("inf")}, {"precipitation_mm": float("inf")}],
)
def test_productivity_request_rejects_non_finite_weather(kw: dict) -> None:
    with pytest.raises(ValidationError):
        ProductivityFactorRequest(trade="concrete", **kw)


def test_bulk_entry_list_is_capped() -> None:
    ann = inspect.signature(bulk_create_entries).parameters["payloads"].annotation
    if isinstance(ann, str):
        ann = eval(ann, bulk_create_entries.__globals__)  # noqa: S307 - postponed annotation from our own module
    item = {"entry_type": "general", "entry_time": "2026-01-01T00:00:00Z"}
    adapter = TypeAdapter(ann)
    adapter.validate_python([item] * 500)
    with pytest.raises(ValidationError):
        adapter.validate_python([item] * 501)


@pytest.mark.parametrize("kw", [{"accuracy_mm": "1e9"}, {"point_count_estimate": 3_000_000_000}])
def test_reality_capture_values_stay_inside_their_columns(kw: dict) -> None:
    from app.modules.daily_diary.schemas import RealityCaptureCreate, RealityCaptureUpdate

    with pytest.raises(ValidationError):
        RealityCaptureCreate(project_id=uuid.uuid4(), captured_at=datetime.now(UTC), file_url="x", **kw)
    with pytest.raises(ValidationError):
        RealityCaptureUpdate(**kw)
