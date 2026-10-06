# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deadline register transport schemas.

``DeadlineItem`` is the single normalized row every cross-module adapter emits,
mirroring the ``InboxItem`` style in :mod:`app.modules.dashboard.schemas`. This
is a read-time transport shape, NOT a table - item #18 aggregates due/overdue
work already stored per module and ships no new SQLAlchemy model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeadlineItem(BaseModel):
    """One due-dated item, normalized from any source module."""

    id: str = Field(description="Stable per-source id, e.g. 'punchlist:<uuid>'.")
    module: str = Field(description="Source module key, e.g. 'correspondence' | 'rfi' | 'punchlist'.")
    entity_type: str = Field(description="Notification entity_type used for dedup + linking.")
    entity_id: str = Field(description="Source row id (dedup + action link).")
    project_id: str
    project_name: str | None = None
    title: str
    due_date: str | None = Field(default=None, description="Normalized ISO date (yyyy-mm-dd) or full ISO.")
    owner_user_id: str | None = None
    owner_name: str | None = Field(default=None, description="Resolved owner display name (best-effort).")
    status: str = Field(description="Source-native status string.")
    classification: str = Field(description="'overdue' | 'approaching' | 'on_time'.")
    days_overdue: int = Field(description="Signed: >0 overdue, <0 days until due, 0 due today.")
    severity: str = Field(description="'critical' (overdue) | 'warning' (approaching) | 'info'.")
    action_url: str = Field(description="Relative app route the row links to.")
    source_label: str | None = Field(
        default=None,
        description="Readable name of the source when ``module`` alone does not say it (built modules).",
    )
    remind_days: int | None = Field(
        default=None,
        description="Days ahead the source wants its due-soon reminder; None uses the sweeper's window.",
    )


class DeadlineRegisterResponse(BaseModel):
    """Cross-module deadline register payload.

    ``items`` is capped to the requested limit; the counts reflect the full
    in-scope classified totals BEFORE the status filter and the cap, so the
    KPI chips stay stable as the user switches the all/overdue/approaching tab.
    """

    items: list[DeadlineItem]
    overdue_count: int = Field(description="In-scope overdue total (pre-filter, pre-cap).")
    approaching_count: int = Field(description="In-scope approaching total (pre-filter, pre-cap).")
    generated_at: str = Field(description="ISO-8601 timestamp.")


class DeadlineSweepResponse(BaseModel):
    """Result of a manual sweep pass."""

    actioned: int = Field(description="Fresh overdue items notified this pass.")
