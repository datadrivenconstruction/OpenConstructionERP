# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Timeline Pydantic v2 response schemas.

A :class:`TimelineEntry` is a read-only projection of one
:class:`app.core.audit_log.ActivityLog` row, and :class:`TimelineResponse`
wraps a page of entries with pagination metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TimelineEntry(BaseModel):
    """One activity-log row as a unified timeline event.

    Populated from an :class:`ActivityLog` ORM instance. The ORM attribute is
    ``metadata_`` (the ``metadata`` column), so the router maps it onto the
    ``metadata`` field explicitly rather than relying on attribute name match.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: str | None = None
    action: str
    module: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    parent_entity_type: str | None = None
    parent_entity_id: str | None = None
    actor_id: uuid.UUID | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class TimelineResponse(BaseModel):
    """A page of timeline entries plus pagination metadata."""

    model_config = ConfigDict(from_attributes=True)

    entries: list[TimelineEntry] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0
