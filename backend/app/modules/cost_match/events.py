"""Event taxonomy for cost_match."""

from __future__ import annotations

from typing import Final

MATCH_COMPLETED: Final = "cost.match.completed"
"""Emitted at the end of a batch matching run. Payload:
``{snapshot_id, matched, needs_review, unmatched, tenant_id}``."""

MATCH_REVIEWED: Final = "cost.match.reviewed"
"""Emitted when a user overrides or confirms a single mapping. Payload:
``{mapping_id, snapshot_id, method, tenant_id}``."""

SOURCE_MODULE: Final = "oe_cost_match"
