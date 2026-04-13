"""Pydantic v2 schemas for collaboration locks."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Allowlist ──────────────────────────────────────────────────────────────
#
# Mirrors the entity_type allowlist used by the ``collaboration`` module
# (comments/viewpoints).  Keeping the two lists in sync is deliberate: a
# row you can comment on is a row you may want to lock.  Any client that
# tries to lock an arbitrary string is rejected at the router boundary so
# the lock table never accumulates orphaned references.

ALLOWED_LOCK_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "boq",
        "boq_position",
        "boq_section",
        "project",
        "document",
        "task",
        "schedule_activity",
        "bim_model",
        "bim_element",
        "requirement",
        "rfi",
        "submittal",
        "ncr",
        "punchlist_item",
        "inspection",
        "meeting",
        "transmittal",
        "tender_package",
        "change_order",
        "risk",
    }
)


DEFAULT_TTL_SECONDS = 60
MIN_TTL_SECONDS = 10
MAX_TTL_SECONDS = 600

DEFAULT_EXTEND_SECONDS = 30
MIN_EXTEND_SECONDS = 5
MAX_EXTEND_SECONDS = 600


# ── Requests ───────────────────────────────────────────────────────────────


class CollabLockAcquire(BaseModel):
    """Payload for ``POST /collab_locks/``."""

    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: uuid.UUID
    ttl_seconds: int = Field(
        default=DEFAULT_TTL_SECONDS,
        ge=MIN_TTL_SECONDS,
        le=MAX_TTL_SECONDS,
    )


class CollabLockHeartbeat(BaseModel):
    """Payload for ``POST /collab_locks/{lock_id}/heartbeat/``."""

    extend_seconds: int = Field(
        default=DEFAULT_EXTEND_SECONDS,
        ge=MIN_EXTEND_SECONDS,
        le=MAX_EXTEND_SECONDS,
    )


# ── Responses ──────────────────────────────────────────────────────────────


class CollabLockResponse(BaseModel):
    """A live lock, held by the current user."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    locked_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    remaining_seconds: int


class CollabLockConflict(BaseModel):
    """Body of the 409 response when an entity is already locked."""

    detail: str
    current_holder_user_id: uuid.UUID
    current_holder_name: str
    locked_at: datetime
    expires_at: datetime
    remaining_seconds: int
