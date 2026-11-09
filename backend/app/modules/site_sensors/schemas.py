# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ request and response schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.decimal_types import Decimal6_2, Decimal8_2, Decimal10_4, Decimal14_4

SensorKind = Literal["concrete_maturity", "noise", "dust_pm10", "vibration", "weather", "water_level", "custom"]
UserReadingSource = Literal["manual", "import"]
MaturityMethod = Literal["nurse_saul", "equivalent_age"]
NoiseZone = Literal["", "a", "b", "c", "d", "e", "f"]
BuildingClass = Literal["", "1", "2", "3"]
FrequencyBand = Literal["", "lt10", "10_50", "50_100", "gt100"]

#: Default unit per kind, used when a device is created without one.
DEFAULT_UNITS: dict[str, str] = {
    "concrete_maturity": "°C",
    "noise": "dB(A)",
    "dust_pm10": "µg/m³",
    "vibration": "mm/s",
    "weather": "m/s",
    "water_level": "m",
}


def check_limits(
    kind: str,
    unit: str,
    upper: Decimal | None,
    lower: Decimal | None,
    record_only: bool,
) -> str | None:
    """The first broken rule of a device's limits as an error key, or None.

    Any kind: the lower limit sits below the upper one. A custom sensor also
    needs a unit and at least one limit, unless it is explicitly record-only.
    """
    if upper is not None and lower is not None and lower >= upper:
        return "lower_limit_not_below_upper"
    if kind == "custom":
        if not (unit or "").strip():
            return "custom_unit_required"
        if upper is None and lower is None and not record_only:
            return "custom_limit_or_record_only"
    return None


class DeviceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(default="", max_length=200)
    kind: SensorKind
    unit: str = Field(default="", max_length=20)
    limit_value: Decimal14_4 | None = None
    lower_limit: Decimal14_4 | None = None
    limit_note: str = Field(default="", max_length=300)
    rolling_mean_hours: float | None = Field(default=None, gt=0, le=720, allow_inf_nan=False)
    record_only: bool = False
    country_code: str = Field(default="", max_length=2)
    offline_after_minutes: int = Field(default=60, ge=1, le=10080)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    mix_id: UUID | None = None
    pour_ref: str = Field(default="", max_length=200)
    cast_at: datetime | None = None
    schedule_activity_id: UUID | None = None
    noise_zone: NoiseZone = ""
    building_class: BuildingClass = ""
    frequency_band: FrequencyBand = ""
    bim_model_id: UUID | None = None
    bim_element_id: UUID | None = None

    @model_validator(mode="after")
    def _bim_element_needs_model(self) -> Self:
        if self.bim_element_id is not None and self.bim_model_id is None:
            raise ValueError("bim_element_needs_model")
        return self

    @model_validator(mode="after")
    def _limits_consistent(self) -> Self:
        err = check_limits(self.kind, self.unit, self.limit_value, self.lower_limit, self.record_only)
        if err:
            raise ValueError(err)
        return self


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    limit_value: Decimal14_4 | None = None
    lower_limit: Decimal14_4 | None = None
    limit_note: str | None = Field(default=None, max_length=300)
    rolling_mean_hours: float | None = Field(default=None, gt=0, le=720, allow_inf_nan=False)
    record_only: bool | None = None
    country_code: str | None = Field(default=None, max_length=2)
    offline_after_minutes: int | None = Field(default=None, ge=1, le=10080)
    active: bool | None = None
    mix_id: UUID | None = None
    pour_ref: str | None = Field(default=None, max_length=200)
    cast_at: datetime | None = None
    schedule_activity_id: UUID | None = None
    noise_zone: NoiseZone | None = None
    building_class: BuildingClass | None = None
    frequency_band: FrequencyBand | None = None
    bim_model_id: UUID | None = None
    bim_element_id: UUID | None = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    code: str
    name: str
    kind: str
    unit: str
    limit_value: Decimal | None = None
    lower_limit: Decimal | None = None
    limit_note: str = ""
    rolling_mean_hours: float | None = None
    record_only: bool = False
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
    noise_zone: str = ""
    building_class: str = ""
    frequency_band: str = ""
    # The limit that applies now and where it comes from (device, or the country's text).
    effective_limit: float | None = None
    limit_source: str = ""
    night_limit_by_ordinance: bool = False
    # The country figure the device limit replaces, when it overrides one.
    country_limit: float | None = None
    country_limit_source: str = ""
    bim_model_id: UUID | None = None
    bim_element_id: UUID | None = None


class TokenResponse(BaseModel):
    device_id: UUID
    token: str
    token_prefix: str


class ReadingIn(BaseModel):
    recorded_at: datetime
    value: float = Field(allow_inf_nan=False)
    frequency_hz: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    note: str = Field(default="", max_length=500)


class ReadingsIn(BaseModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=5000)


class UserReadingsIn(ReadingsIn):
    """Readings a person adds: typed in one by one, or pasted or imported from CSV."""

    source: UserReadingSource = "manual"


class ReadingEdit(BaseModel):
    recorded_at: datetime
    value: float = Field(allow_inf_nan=False)
    note: str = Field(default="", max_length=500)


class ReadingAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: UUID
    recorded_at: datetime
    action: str
    value_before: float | None = None
    value_after: float | None = None
    note: str = ""
    user_id: UUID | None = None
    created_at: datetime
    user_name: str = ""


class MixCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(default="", max_length=200)
    datum_temp_c: Decimal6_2 = Decimal("0")
    method: MaturityMethod = "nurse_saul"
    activation_energy_kj_mol: Decimal6_2 = Field(default=Decimal("40"), gt=0, le=100)
    reference_temp_c: Decimal6_2 = Decimal("20")
    curve_a: Decimal10_4
    curve_b: Decimal10_4 = Field(gt=0)
    strip_strength_mpa: Decimal8_2 | None = Field(default=None, gt=0)
    notes: str | None = None


class MixUpdate(BaseModel):
    """Manual concrete mode: the site's own datum, method constants, curve and strike strength."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    datum_temp_c: Decimal6_2 | None = Field(default=None, ge=-30, le=30)
    method: MaturityMethod | None = None
    activation_energy_kj_mol: Decimal6_2 | None = Field(default=None, gt=0, le=100)
    reference_temp_c: Decimal6_2 | None = None
    curve_a: Decimal10_4 | None = None
    curve_b: Decimal10_4 | None = Field(default=None, gt=0)
    strip_strength_mpa: Decimal8_2 | None = Field(default=None, gt=0)
    notes: str | None = None


class MixResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    code: str
    name: str
    datum_temp_c: Decimal
    method: str = "nurse_saul"
    activation_energy_kj_mol: Decimal = Decimal("40")
    reference_temp_c: Decimal = Decimal("20")
    curve_a: Decimal
    curve_b: Decimal
    strip_strength_mpa: Decimal | None = None
    notes: str | None = None
    fit_r2: float | None = None
    calibrated_min: float | None = None
    calibrated_max: float | None = None


class CalibrationPointIn(BaseModel):
    maturity_index: float = Field(gt=0, allow_inf_nan=False)
    strength_mpa: Decimal8_2 = Field(gt=0)
    age_hours: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    note: str = Field(default="", max_length=200)


class CalibrationIn(BaseModel):
    """The whole calibration table of a mix; replaces the previous one and refits the curve."""

    points: list[CalibrationPointIn] = Field(max_length=200)


class CalibrationPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    maturity_index: float
    strength_mpa: Decimal
    age_hours: float | None = None
    note: str


class CalibrationResponse(BaseModel):
    mix: MixResponse
    points: list[CalibrationPointOut]


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
    target_strength_mpa: Decimal8_2 | None = Field(default=None, gt=0)
    planned_at: datetime | None = None
    bim_model_id: UUID | None = None
    bim_element_id: UUID | None = None

    @model_validator(mode="after")
    def _bim_element_needs_model(self) -> Self:
        if self.bim_element_id is not None and self.bim_model_id is None:
            raise ValueError("bim_element_needs_model")
        return self


class StrikeIn(BaseModel):
    struck_at: datetime | None = None
    # Required when the estimate is below target: cube result, back-propping.
    reason: str = Field(default="", max_length=2000)


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
    strike_reason: str | None = None
    struck_by: UUID | None = None
    status: str
    bim_model_id: UUID | None = None
    bim_element_id: UUID | None = None


class ReadingAuditListResponse(BaseModel):
    """Page of ReadingAuditOut."""

    items: list[ReadingAuditOut]
    total: int
    offset: int = 0
    limit: int = 200


class AlertListResponse(BaseModel):
    """Page of AlertResponse."""

    items: list[AlertResponse]
    total: int
    offset: int = 0
    limit: int = 50


class DeviceListResponse(BaseModel):
    """Page of DeviceResponse."""

    items: list[DeviceResponse]
    total: int
    offset: int = 0
    limit: int = 50


class MixListResponse(BaseModel):
    """Page of MixResponse."""

    items: list[MixResponse]
    total: int
    offset: int = 0
    limit: int = 50


class StripListResponse(BaseModel):
    """Page of StripResponse."""

    items: list[StripResponse]
    total: int
    offset: int = 0
    limit: int = 50
