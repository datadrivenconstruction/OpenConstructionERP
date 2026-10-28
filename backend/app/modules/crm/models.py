# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CRM ORM models.

Tables:
    oe_crm_account                    - customer / prospect accounts
    oe_crm_lead                       - sales leads (pre-qualification)
    oe_crm_opportunity                - qualified deals in pipeline
    oe_crm_pipeline_stage             - pipeline stage catalogue
    oe_crm_opportunity_stage_history  - stage transition log
    oe_crm_activity                   - call/meeting/email/task/note touches
    oe_crm_forecast                   - period forecast snapshots
    oe_crm_win_loss_reason            - win/loss reason catalogue
    oe_crm_pipeline_stage_config      - singleton config row

Notes:
    * ``primary_contact_id`` columns on Account / Opportunity are plain UUID
      (no SQLAlchemy ForeignKey). The Alembic migration may declare a DB-level
      FK to ``oe_contacts_contact`` but the ORM stays unaware so the unit
      test fixtures (which never load Contacts) don't trip
      ``NoReferencedTableError``.
    * No duplicate index names: every indexed column uses column-level
      ``index=True`` only - never combined with a table-level ``Index(...)``
      pointing at the same column.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# ── Catalogue tables ──────────────────────────────────────────────────────


class PipelineStage(Base):
    """A configurable stage in the sales pipeline (Lead → Won/Lost)."""

    __tablename__ = "oe_crm_pipeline_stage"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    default_probability_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_won: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_lost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<PipelineStage {self.code}>"


class WinLossReason(Base):
    """Catalogue entry for the reason an opportunity was won or lost."""

    __tablename__ = "oe_crm_win_loss_reason"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="other",
        server_default="other",
    )
    is_win_reason: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_loss_reason: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    def __repr__(self) -> str:
        return f"<WinLossReason {self.code} ({self.category})>"


class PipelineStageConfig(Base):
    """Singleton config row (``id``-keyed by string 'default')."""

    __tablename__ = "oe_crm_pipeline_stage_config"

    # Override the UUID PK with a deterministic string key so the singleton
    # is trivial to fetch / upsert.
    id: Mapped[str] = mapped_column(  # type: ignore[assignment]
        String(64),
        primary_key=True,
        default="default",
    )
    kanban_columns: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    defaults: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )


# ── Core tables ───────────────────────────────────────────────────────────


class Account(Base):
    """A customer or prospect organisation."""

    __tablename__ = "oe_crm_account"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_category: Mapped[str] = mapped_column(String(32), nullable=False, default="sme", server_default="sme")
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # NOTE: plain UUID - no SQLAlchemy FK to oe_contacts_contact (see header).
    primary_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Hierarchy: owner / GC / sub. Plain ORM FK to self.
    parent_account_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Account role within the hierarchy: owner / general_contractor / subcontractor / consultant / supplier
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="general_contractor",
        server_default="general_contractor",
        index=True,
    )

    def __repr__(self) -> str:
        return f"<Account {self.name} ({self.status})>"


class Lead(Base):
    """A sales lead (pre-qualification / pre-opportunity)."""

    __tablename__ = "oe_crm_lead"

    account_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="inbound", server_default="inbound")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="new",
        server_default="new",
        index=True,
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    qualification_notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    qualified_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    converted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    converted_opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_opportunity.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<Lead {self.contact_name} ({self.status})>"


class Opportunity(Base):
    """A qualified deal moving through the sales pipeline."""

    __tablename__ = "oe_crm_opportunity"

    account_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    estimated_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="", server_default="")
    expected_close_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    probability_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    stage_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_pipeline_stage.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    weighted_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="inbound", server_default="inbound")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )
    won_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lost_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lost_reason_code: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("oe_crm_win_loss_reason.code", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # NOTE: plain UUID - no SQLAlchemy FK to oe_contacts_contact (see header).
    # The CRM does NOT own contacts: this points at a row in the shared
    # Contacts directory (``oe_contacts_contact``). People/companies are
    # always created & edited through the Contacts module, never duplicated
    # here.
    primary_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Link to a delivery Project (``oe_projects_project``). Plain UUID for
    # the same reason as primary_contact_id - the ORM stays unaware so unit
    # fixtures that never load the Projects module don't trip
    # NoReferencedTableError. A won deal references the project it spawned;
    # an open deal can be pre-linked to a tender/estimate project.
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    competitor_names: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )

    def __repr__(self) -> str:
        return f"<Opportunity {self.title} ({self.status})>"


class OpportunityStageHistory(Base):
    """An immutable record of an opportunity moving between pipeline stages."""

    __tablename__ = "oe_crm_opportunity_stage_history"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_opportunity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_pipeline_stage.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_stage_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_pipeline_stage.id", ondelete="RESTRICT"),
        nullable=False,
    )
    changed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    duration_in_previous_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<OpportunityStageHistory opp={self.opportunity_id} → {self.to_stage_id}>"


class CrmActivity(Base):
    """A CRM touch - call / meeting / email / task / note.

    Class is prefixed ``Crm`` to avoid clashing with
    ``app.modules.schedule.models.Activity`` in the shared declarative
    registry.
    """

    __tablename__ = "oe_crm_activity"

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_account.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_opportunity.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_crm_lead.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="note", server_default="note")
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    due_at: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<Activity {self.kind} '{self.subject[:40]}'>"


class Forecast(Base):
    """A snapshot of pipeline forecast for a period (year-quarter)."""

    __tablename__ = "oe_crm_forecast"

    period: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    pipeline_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    weighted_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    won_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    committed_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    computed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The four scalars above blend ISO currencies across the period's deals.
    # ``compute_forecast`` has always produced these two alongside them - the
    # per-currency breakdown and the flag warning that the scalars are a blend -
    # and the snapshot had nowhere to keep them, so they were computed and
    # dropped on every call. Money as a JSON string, per the module convention.
    #
    # Nullable rather than defaulted, and that is the whole point: a row written
    # before this column existed was never checked, and "not checked" must not
    # read as "checked, and not mixed". False is an assurance.
    by_currency: Mapped[list | None] = mapped_column(JSON, nullable=True)
    mixed_currency: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    def __repr__(self) -> str:
        return f"<Forecast {self.period} pipeline={self.pipeline_value}>"
