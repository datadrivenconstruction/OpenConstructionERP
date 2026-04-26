# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic v2 schemas for EAC v2 parameter aliases (RFC 35 §6).

Kept in a sibling module to the resolver/service so the request/response
layer can evolve independently of the storage layer.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.eac.models import (
    ALIAS_SCOPES,
    ALIAS_SOURCE_FILTERS,
    ALIAS_SYNONYM_KINDS,
    ALIAS_VALUE_TYPE_HINTS,
)

_ALIAS_SCOPE_VALUES = ALIAS_SCOPES
_ALIAS_VTH_VALUES = ALIAS_VALUE_TYPE_HINTS
_ALIAS_KIND_VALUES = ALIAS_SYNONYM_KINDS
_ALIAS_SOURCE_VALUES = ALIAS_SOURCE_FILTERS


class _ApiBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Synonym ──────────────────────────────────────────────────────────────


class EacAliasSynonymCreate(BaseModel):
    """Synonym payload nested inside an alias create/update body."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="exact", description="exact | regex")
    case_sensitive: bool = False
    priority: int = Field(default=100, ge=0, le=100_000)
    pset_filter: str | None = Field(default=None, max_length=255)
    source_filter: str = Field(
        default="any",
        description="any | instance | type | pset | external_classification",
    )
    unit_multiplier: Decimal = Field(default=Decimal("1"))


class EacAliasSynonymRead(_ApiBase):
    """Response shape for a synonym row."""

    id: UUID
    alias_id: UUID
    pattern: str
    kind: str
    case_sensitive: bool
    priority: int
    pset_filter: str | None = None
    source_filter: str
    unit_multiplier: Decimal
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Parameter alias ─────────────────────────────────────────────────────


class EacParameterAliasCreate(BaseModel):
    """Payload for ``POST /aliases``."""

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(description="org | project")
    scope_id: UUID | None = None
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    value_type_hint: str = Field(default="any")
    default_unit: str | None = Field(default=None, max_length=64)
    synonyms: list[EacAliasSynonymCreate] = Field(default_factory=list)


class EacParameterAliasUpdate(BaseModel):
    """Payload for ``PUT /aliases/{id}``. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    value_type_hint: str | None = None
    default_unit: str | None = Field(default=None, max_length=64)
    synonyms: list[EacAliasSynonymCreate] | None = Field(
        default=None,
        description="When provided, replaces the synonym set entirely.",
    )


class EacParameterAliasRead(_ApiBase):
    """Response shape for an alias (with synonyms)."""

    id: UUID
    scope: str
    scope_id: UUID | None = None
    name: str
    description: str | None = None
    value_type_hint: str
    default_unit: str | None = None
    version: int
    is_built_in: bool
    tenant_id: UUID | None = None
    synonyms: list[EacAliasSynonymRead] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Resolve / test endpoints ────────────────────────────────────────────


class EacAliasResolveRequest(BaseModel):
    """Payload for ``POST /aliases:resolve``."""

    model_config = ConfigDict(extra="forbid")

    alias_id: UUID
    element: dict[str, Any]


class EacAliasBulkResolveRequest(BaseModel):
    """Payload for ``POST /aliases:resolve-bulk``."""

    model_config = ConfigDict(extra="forbid")

    alias_ids: list[UUID] = Field(min_length=1)
    element: dict[str, Any]


class EacAliasResolveResponse(BaseModel):
    """Response for ``POST /aliases:resolve``."""

    alias_id: UUID
    alias_name: str
    matched: bool
    matched_synonym_id: UUID | None = None
    raw_value: Any = None
    value_after_unit_conversion: Any = None
    pset_name: str | None = None


class EacAliasTestRequest(BaseModel):
    """Payload for ``POST /aliases/{id}/test``."""

    model_config = ConfigDict(extra="forbid")

    property_name: str = Field(min_length=1)
    pset_name: str | None = None
    source: str = Field(default="any", description="See ALIAS_SOURCE_FILTERS")


class EacAliasTestResponse(BaseModel):
    """Response for ``POST /aliases/{id}/test``."""

    matched: bool
    matched_synonym_id: UUID | None = None
    pset_name: str | None = None


# ── Usage discovery ─────────────────────────────────────────────────────


class EacAliasUsageRow(BaseModel):
    """A rule that references this alias (for "where is this used?" UI)."""

    model_config = ConfigDict(from_attributes=True)

    rule_id: UUID
    rule_name: str
    rule_output_mode: str


class EacAliasUsageResponse(BaseModel):
    """Response for ``GET /aliases/{id}/usages``."""

    usages: list[EacAliasUsageRow] = Field(default_factory=list)
    can_delete: bool = True


# ── Import / export ─────────────────────────────────────────────────────


class EacAliasExportRequest(BaseModel):
    """Optional filters for ``POST /aliases:export``."""

    model_config = ConfigDict(extra="forbid")

    scope: str | None = None
    scope_id: UUID | None = None
    include_built_in: bool = False


class EacAliasImportSummary(BaseModel):
    """Result of ``POST /aliases:import``."""

    inserted: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


__all__ = [
    "EacAliasBulkResolveRequest",
    "EacAliasExportRequest",
    "EacAliasImportSummary",
    "EacAliasResolveRequest",
    "EacAliasResolveResponse",
    "EacAliasSynonymCreate",
    "EacAliasSynonymRead",
    "EacAliasTestRequest",
    "EacAliasTestResponse",
    "EacAliasUsageResponse",
    "EacAliasUsageRow",
    "EacParameterAliasCreate",
    "EacParameterAliasRead",
    "EacParameterAliasUpdate",
]
