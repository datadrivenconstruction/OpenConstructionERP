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


__all__ = [
    "DSLCompileRequest",
    "DSLRuleListResponse",
    "DSLRuleOut",
    "DSLValidateRequest",
    "DSLValidateResponse",
]
