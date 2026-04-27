# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic DTOs for the compliance DSL API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DSLValidateRequest(BaseModel):
    """Body for ``POST /dsl/validate-syntax``.

    Either ``definition_yaml`` (raw text) or ``definition`` (already
    parsed mapping) — exactly one must be supplied.
    """

    definition_yaml: str | None = None
    definition: dict[str, Any] | None = None


class DSLValidateResponse(BaseModel):
    valid: bool
    error: str | None = None
    # Normalised echo of the parsed metadata, only populated when
    # ``valid`` is true. Useful for the UI to confirm what would be
    # stored without the user committing.
    rule_id: str | None = None
    severity: str | None = None
    standard: str | None = None


class DSLCompileRequest(BaseModel):
    """Body for ``POST /dsl/compile`` — persists + registers."""

    definition_yaml: str = Field(..., min_length=1, max_length=64_000)
    activate: bool = True


class DSLRuleOut(BaseModel):
    """List / detail row shape."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: str
    name: str
    severity: str
    standard: str
    description: str | None = None
    definition_yaml: str
    owner_user_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DSLRuleListResponse(BaseModel):
    total: int
    items: list[DSLRuleOut]


# ── T13: NL → DSL builder ──────────────────────────────────────────────────


class DSLFromNlRequest(BaseModel):
    """Body for ``POST /dsl/from-nl``.

    ``text`` is the user's plain-language sentence. ``lang`` tells the
    pattern matcher which alias table to apply before regex matching;
    unknown values fall back to ``en``. ``use_ai`` is a hint — even when
    true, the call degrades gracefully if no API key is configured for
    the caller (the deterministic pattern still runs).
    """

    text: str = Field(..., min_length=1, max_length=2_000)
    lang: str = Field("en", min_length=2, max_length=12)
    use_ai: bool = False


class DSLFromNlResponse(BaseModel):
    """Result envelope for ``POST /dsl/from-nl``."""

    dsl_definition: dict[str, Any] = Field(default_factory=dict)
    dsl_yaml: str | None = None
    confidence: float = 0.0
    used_method: str = "fallback"
    matched_pattern: str | None = None
    errors: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class DSLNlPatternOut(BaseModel):
    pattern_id: str
    name_key: str
    confidence: float


class DSLNlPatternsResponse(BaseModel):
    items: list[DSLNlPatternOut]


__all__ = [
    "DSLCompileRequest",
    "DSLFromNlRequest",
    "DSLFromNlResponse",
    "DSLNlPatternOut",
    "DSLNlPatternsResponse",
    "DSLRuleListResponse",
    "DSLRuleOut",
    "DSLValidateRequest",
    "DSLValidateResponse",
]
