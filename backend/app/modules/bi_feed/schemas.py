# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Response models of the data feed endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeedColumnInfo(BaseModel):
    """One column of a feed."""

    name: str
    kind: str


class FeedInfo(BaseModel):
    """A feed the caller can read, with the number of rows visible to the caller."""

    id: str
    title_key: str
    columns: list[FeedColumnInfo]
    row_count: int = Field(ge=0)


class SqlAccessStatus(BaseModel):
    """Whether the opt-in ``oe_bi`` schema exists. Never carries a password."""

    enabled: bool
    schema_name: str
    role: str
    views: list[str] = Field(default_factory=list)
