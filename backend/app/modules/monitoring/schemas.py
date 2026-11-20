# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring request and response schemas.

Coordinates and values travel as JSON numbers in metres; displacements in
millimetres with one decimal, rates in mm/day with two.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PointType = Literal["prism", "settlement_pin", "convergence_chord", "inclinometer"]
Axis = Literal["z", "horizontal", "3d", "value"]
Level = Literal["none", "ok", "alert", "action", "alarm"]
AckState = Literal["none", "pending", "done"]


class ThresholdsOut(BaseModel):
    alert_mm: float | None = None
    action_mm: float | None = None
    alarm_mm: float | None = None
    rate_alert: float | None = None
    rate_action: float | None = None
    rate_alarm: float | None = None


class ProfileOut(BaseModel):
    key: str
    name: str
    source: Literal["demo", "pack", "project"]
    country: str = ""
    reference: str = ""
    edition: str = ""
    clause: str = ""
    #: ``verified`` | ``to_verify`` | "" (demo and project profiles).
    status: str = ""
    thresholds: ThresholdsOut


class ProfileCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    reference: str = Field(default="", max_length=255)
    alert_mm: float | None = Field(default=None, gt=0, le=100000)
    action_mm: float | None = Field(default=None, gt=0, le=100000)
    alarm_mm: float | None = Field(default=None, gt=0, le=100000)
    rate_alert: float | None = Field(default=None, gt=0, le=100000)
    rate_action: float | None = Field(default=None, gt=0, le=100000)
    rate_alarm: float | None = Field(default=None, gt=0, le=100000)

    @model_validator(mode="after")
    def _rising(self) -> ProfileCreate:
        for family in (
            (self.alert_mm, self.action_mm, self.alarm_mm),
            (self.rate_alert, self.rate_action, self.rate_alarm),
        ):
            given = [v for v in family if v is not None]
            if given != sorted(given) or len(set(given)) != len(given):
                raise ValueError("thresholds must rise from alert to action to alarm")
        if all(
            v is None
            for v in (self.alert_mm, self.action_mm, self.alarm_mm, self.rate_alert, self.rate_action, self.rate_alarm)
        ):
            raise ValueError("set at least one threshold")
        return self


class SettingsOut(BaseModel):
    profile_key: str
    profile: ProfileOut | None = None


class SettingsUpdate(BaseModel):
    profile_key: str = Field(default="", max_length=80)


class PointCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=255)
    point_type: PointType = "settlement_pin"
    #: Advanced: how displacement is read. Empty uses the point type's usual axis.
    axis: Axis | None = None
    location: str = Field(default="", max_length=255)


class PointUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    point_type: PointType | None = None
    axis: Axis | None = None
    location: str | None = Field(default=None, max_length=255)


class ForecastLevelOut(BaseModel):
    level: Literal["alert", "action", "alarm"]
    limit_mm: float
    #: The fitted trend value has already reached this level.
    reached: bool = False
    #: Days until the trend reaches it; null when reached or not approaching.
    days: float | None = None


class PointOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    point_type: PointType
    axis: Axis
    location: str
    epochs: int
    baseline_at: datetime | None = None
    latest_at: datetime | None = None
    #: Z (or the value) in metres; null for points read in plan only.
    baseline_value: float | None = None
    latest_value: float | None = None
    displacement_mm: float | None = None
    rate_mm_day: float | None = None
    level: Level = "none"
    ack_state: AckState = "none"
    #: Linear fit over the last epochs: the next threshold it reaches and in how many days.
    forecast_level: str = ""
    forecast_days: float | None = None
    forecast_rate_mm_day: float | None = None
    #: False when the trend is flat or runs back towards zero.
    forecast_approaching: bool = False
    forecast_epochs: int = 0
    forecast_levels: list[ForecastLevelOut] = []


class SeriesEntry(BaseModel):
    at: datetime
    e: float | None = None
    n: float | None = None
    z: float | None = None
    value: float | None = None
    displacement_mm: float | None = None
    rate_mm_day: float | None = None
    level: Level = "none"
    #: The risk register entry this reading's alert opened, if any.
    risk_id: str | None = None


class AlertOut(BaseModel):
    id: uuid.UUID
    reading_id: uuid.UUID
    level: Literal["alert", "action", "alarm"]
    displacement_mm: float
    rate_mm_day: float | None = None
    observed_at: datetime
    profile_label: str = ""
    thresholds: ThresholdsOut
    notified: bool = False
    risk_id: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by_name: str = ""
    note: str = ""


class PointDetail(PointOut):
    profile_label: str = ""
    thresholds: ThresholdsOut | None = None
    series: list[SeriesEntry]
    alerts: list[AlertOut]


class Acknowledge(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    note: str = Field(default="", max_length=2000)


class ReadingsImport(BaseModel):
    text: str = Field(min_length=1, max_length=6_000_000)
    filename: str = Field(default="", max_length=255)


class ImportProblem(BaseModel):
    line: int
    point_id: str
    message: str


class ReadingsPreview(BaseModel):
    rows_read: int
    readings: int
    new_points: list[str]
    epochs: list[datetime]
    already_imported: int
    problems: list[ImportProblem]
    problem_count: int


class ReadingsResult(BaseModel):
    rows_read: int
    readings_added: int
    readings_skipped: int
    new_points: list[str]
    epochs_added: int
    alerts: list[AlertOut]
    problems: list[ImportProblem]
    problem_count: int


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class ValidationReportOut(BaseModel):
    status: str
    error_count: int
    warning_count: int
    info_count: int
    findings: list[Finding]


class MonitoringSummary(BaseModel):
    points: int
    ok: int
    alert: int
    action: int
    alarm: int
    unacknowledged: int
    last_epoch: datetime | None = None


class PointListResponse(BaseModel):
    items: list[PointOut]
    total: int
    offset: int = 0
    limit: int = 50


class ProfileListResponse(BaseModel):
    items: list[ProfileOut]
    total: int
    offset: int = 0
    limit: int = 50
