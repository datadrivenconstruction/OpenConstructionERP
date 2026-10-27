# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCOPE_KEY_PATTERN = r"^[A-Za-z0-9_./:-]{1,200}$"
MAX_COLUMNS = 200
MAX_FILTERS = 50


class ListSort(BaseModel):
    """Sort of a list: one column, ascending or descending."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=120)
    dir: Literal["asc", "desc"] = "asc"


class ListViewState(BaseModel):
    """What a view restores on a list page."""

    model_config = ConfigDict(extra="forbid")

    #: Column key -> filter text (contains match) or a page-specific token.
    filters: dict[str, str] = Field(default_factory=dict)
    #: Visible columns in display order; empty means the page default.
    columns: list[str] = Field(default_factory=list)
    #: Column key -> width in pixels.
    widths: dict[str, int] = Field(default_factory=dict)
    sort: ListSort | None = None
    #: Free page filters (search text, status chips) the page itself owns.
    query: dict[str, str | int | float | bool | list[str] | None] = Field(default_factory=dict)

    @field_validator("filters")
    @classmethod
    def _limit_filters(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > MAX_FILTERS:
            raise ValueError(f"at most {MAX_FILTERS} filters")
        return {k[:120]: s[:500] for k, s in v.items()}

    @field_validator("columns")
    @classmethod
    def _limit_columns(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_COLUMNS:
            raise ValueError(f"at most {MAX_COLUMNS} columns")
        return [c[:120] for c in v]

    @field_validator("widths")
    @classmethod
    def _clamp_widths(cls, v: dict[str, int]) -> dict[str, int]:
        return {k[:120]: max(24, min(int(w), 2000)) for k, w in list(v.items())[:MAX_COLUMNS]}


class ListViewCreate(BaseModel):
    """Save the current layout of a list page under a name."""

    model_config = ConfigDict(extra="forbid")

    scope_key: str = Field(pattern=SCOPE_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    state: ListViewState = Field(default_factory=ListViewState)
    is_shared: bool = False
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class ListViewUpdate(BaseModel):
    """Rename, re-share or overwrite the layout of an existing view."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    state: ListViewState | None = None
    is_shared: bool | None = None
    is_default: bool | None = None


class ListViewResponse(BaseModel):
    """A view as the picker shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope_key: str
    name: str
    state: ListViewState
    is_shared: bool
    is_default: bool
    is_own: bool
    created_at: datetime
    updated_at: datetime
