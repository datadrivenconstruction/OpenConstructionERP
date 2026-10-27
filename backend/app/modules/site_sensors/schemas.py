# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ request and response schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SensorKind = Literal["concrete_maturity", "noise", "dust_pm10", "vibration", "weather", "water_level"]

#: Default unit per kind, used when a device is created without one.
DEFAULT_UNITS: dict[str, str] = {
    "concrete_maturity": "degC",
    "noise": "dB(A)",
    "dust_pm10": "ug/m3",
    "vibration": "mm/s",
    "weather": "m/s",
    "water_level": "m",
}


class DeviceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(default="", max_length=200)
    kind: SensorKind
    unit: str = Field(default="", max_length=20)
    limit_value: Decimal | None = None
    country_code: str = Field(default="", max_length=2)
    offline_after_minutes: int = Field(default=60, ge=1, le=10080)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    mix_id: UUID | None = None
    pour_ref: str = Field(default="", max_length=200)
    cast_at: datetime | None = None
    schedule_activity_id: UUID | None = None


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    limit_value: Decimal | None = None
    country_code: str | None = Field(default=None, max_length=2)
    offline_after_minutes: int | None = Field(default=None, ge=1, le=10080)
    active: bool | None = None
    mix_id: UUID | None = None
    pour_ref: str | None = Field(default=None, max_length=200)
    cast_at: datetime | None = None
    schedule_activity_id: UUID | None = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    code: str
    name: str
    kind: str
    unit: str
    limit_value: Decimal | None = None
    country_code: str
    offline_after_minutes: int
    token_prefix: str
    active: bool
    last_seen_at: datetime | None = None
    last_value: float | None = None
    lat: float | None = None
    lng: float | None = None
    mix_id: UUID | None = None
    pour_ref: str
    cast_at: datetime | None = None
    schedule_activity_id: UUID | None = None


class TokenResponse(BaseModel):
    device_id: UUID
    token: str
    token_prefix: str


class ReadingIn(BaseModel):
    recorded_at: datetime
    value: float = Field(allow_inf_nan=False)


class ReadingsIn(BaseModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=5000)


class MixCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(default="", max_length=200)
    datum_temp_c: Decimal = Decimal("-10")
    curve_a: Decimal
    curve_b: Decimal = Field(gt=0)
    strip_strength_mpa: Decimal | None = Field(default=None, gt=0)
    notes: str | None = None


class MixResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    code: str
    name: str
    datum_temp_c: Decimal
    curve_a: Decimal
    curve_b: Decimal
    strip_strength_mpa: Decimal | None = None
    notes: str | None = None


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    device_id: UUID
    kind: str
    status: str
    raised_at: datetime
    value: float | None = None
    limit_value: float | None = None
    limit_source: str
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None
    note: str | None = None
    diary_id: UUID | None = None
    inspection_id: UUID | None = None
    punch_item_id: UUID | None = None


class AcknowledgeIn(BaseModel):
    note: str = Field(default="", max_length=2000)


class AlertLinksIn(BaseModel):
    diary_id: UUID | None = None
    inspection_id: UUID | None = None
    punch_item_id: UUID | None = None


class StripCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    device_id: UUID
    element: str = Field(default="", max_length=200)
    schedule_activity_id: UUID | None = None
    target_strength_mpa: Decimal | None = Field(default=None, gt=0)
    planned_at: datetime | None = None


class StrikeIn(BaseModel):
    struck_at: datetime | None = None


class StripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    device_id: UUID
    element: str
    schedule_activity_id: UUID | None = None
    target_strength_mpa: Decimal
    planned_at: datetime | None = None
    released_at: datetime | None = None
    struck_at: datetime | None = None
    strength_at_strike_mpa: Decimal | None = None
    status: str
