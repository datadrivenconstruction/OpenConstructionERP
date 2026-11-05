# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Impact = Literal["low", "medium", "high"]
LessonStatus = Literal["draft", "confirmed"]


class LessonCreate(BaseModel):
    project_id: uuid.UUID
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=5000)
    recommendation: str = Field(default="", max_length=5000)
    trade: str = Field(default="", max_length=100)
    cost_code: str = Field(default="", max_length=100)
    risk_category: str = Field(default="", max_length=50)
    impact: Impact = "medium"


class LessonUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    recommendation: str | None = Field(default=None, max_length=5000)
    trade: str | None = Field(default=None, max_length=100)
    cost_code: str | None = Field(default=None, max_length=100)
    risk_category: str | None = Field(default=None, max_length=50)
    impact: Impact | None = None


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str


class LessonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str
    recommendation: str
    trade: str
    cost_code: str
    risk_category: str
    impact: Impact
    status: LessonStatus
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    findings: list[Finding] = []


class LessonListResponse(BaseModel):
    items: list[LessonResponse]
    total: int
    offset: int = 0
    limit: int = 200


class SeenLesson(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    recommendation: str
    impact: Impact
    matched: list[str]


class SeenResponse(BaseModel):
    """How many other projects met the same situation, plus the best few lessons."""

    projects: int
    lessons: int
    top: list[SeenLesson]
