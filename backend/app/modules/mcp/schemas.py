# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠MCP server request and response schemas (the settings surface, not the protocol)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.mcp.models import MAX_RATE_LIMIT_PER_MINUTE, MIN_RATE_LIMIT_PER_MINUTE

ToolKind = Literal["read", "propose"]
CallOutcome = Literal["ok", "error", "denied", "rate_limited"]


class McpSettingsResponse(BaseModel):
    """The caller's MCP switch and limits."""

    enabled: bool
    rate_limit_per_minute: int
    endpoint_path: str = "/api/v1/mcp"
    protocol_versions: list[str] = Field(default_factory=list)


class McpSettingsUpdate(BaseModel):
    """Change the caller's MCP switch or rate limit."""

    enabled: bool | None = None
    rate_limit_per_minute: int | None = Field(
        default=None,
        ge=MIN_RATE_LIMIT_PER_MINUTE,
        le=MAX_RATE_LIMIT_PER_MINUTE,
    )


class McpTokenCreate(BaseModel):
    """Create a personal MCP token."""

    name: str = Field(..., min_length=1, max_length=255)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)
    can_propose: bool = True


class McpTokenResponse(BaseModel):
    """An MCP token without its secret."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    is_active: bool
    can_propose: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class McpTokenCreatedResponse(McpTokenResponse):
    """The token as created: the only response that carries the secret."""

    token: str


class McpToolInfo(BaseModel):
    """One tool as the settings page lists it."""

    name: str
    kind: ToolKind
    description: str
    permission: str | None = None
    available: bool = True


class McpToolCallResponse(BaseModel):
    """One audited tool call."""

    id: UUID
    tool: str
    kind: ToolKind | None = None
    outcome: CallOutcome
    duration_ms: int | None = None
    project_id: str | None = None
    token_prefix: str | None = None
    action_id: str | None = None
    error: str | None = None
    created_at: datetime


class McpValidationFinding(BaseModel):
    """One validation finding with its i18n key and interpolation values."""

    rule_id: str
    severity: str
    key: str
    message: str
    params: dict[str, Any] = Field(default_factory=dict)
    element_ref: str | None = None


class McpValidationReport(BaseModel):
    """Traffic-light summary of the caller's MCP setup."""

    status: str
    score: float | None
    findings: list[McpValidationFinding] = Field(default_factory=list)


class McpTokenListResponse(BaseModel):
    """A page of McpTokenResponse with the count of rows the filters matched."""

    items: list[McpTokenResponse]
    total: int
    offset: int = 0
    limit: int = 50


class McpToolCallListResponse(BaseModel):
    """A page of McpToolCallResponse with the count of rows the filters matched."""

    items: list[McpToolCallResponse]
    total: int
    offset: int = 0
    limit: int = 50
