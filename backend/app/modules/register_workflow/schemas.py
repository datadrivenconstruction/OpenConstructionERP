# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register workflow response envelopes.

The module answers with plain dicts assembled by ``service`` - the shape
of a register item depends on its kind, so a row model here would be a
second, thinner description of something the workflow already owns. What
belongs here is the envelope around a list, which is the one thing an
array cannot express: whether the caller is holding all of it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RegisterWorkflowListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int
