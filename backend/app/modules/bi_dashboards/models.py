# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍BI Dashboards ORM models.

All tables prefixed ``oe_bi_dashboards_``. Cross-module references
(project_id, owner_user_id, widget→dashboard) deliberately omit ORM
foreign keys to other modules' tables — this is a read-only consumer
module and must not be coupled to upstream model lifecycles. Only
intra-module FKs (widget → dashboard, snapshot → widget,
schedule → report_definition) use SQLAlchemy ForeignKey because they're
guaranteed to be created together.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class KPIDefinition(Base):
    """‌⁠‍A registered KPI in the library.

    The ``formula_ref`` column is the lookup key into the in-process
    :data:`app.modules.bi_dashboards.kpis.KPI_FORMULAS` registry. System
    KPIs are seeded on startup; users may register custom KPIs by adding
    a row here and a Python function via the ``@register_kpi`` decorator.
    """

    __tablename__ = "oe_bi_dashboards_kpi_definition"

    code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    formula_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    source_modules: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    unit: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ratio",
        server_default="ratio",
    )
    target_default: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6),
        nullable=True,
    )
    aggregation: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="last",
        server_default="last",
    )
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="operational",
        server_default="operational",
        index=True,
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )


class Dashboard(Base):
    """‌⁠‍A dashboard configuration (collection of widgets)."""

    __tablename__ = "oe_bi_dashboards_dashboard"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    # No ORM FK to oe_users_user — keep the consumer module decoupled
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="personal",
        server_default="personal",
        index=True,
    )
    role_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # No ORM FK to oe_projects_project — read-only consumer
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    layout_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    refresh_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=300,
        server_default="300",
    )
    # Wave 4 / T11 — cross-filter opt-in flag. When True the evaluate
    # endpoint propagates a caller-supplied filter dict into every widget.
    # Default False keeps the v3.x static-render contract for existing rows.
    cross_filter_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )


class DashboardWidget(Base):
    """A widget placed on a dashboard."""

    __tablename__ = "oe_bi_dashboards_widget"

    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_bi_dashboards_dashboard.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    widget_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="kpi_card",
        server_default="kpi_card",
    )
    kpi_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    config_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    position_x: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    position_y: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    width: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
    )
    height: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default="2",
    )
    order_seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Wave 4 / T11 — drill-path JSON describes how a click on this widget
    # propagates a filter to the rest of the dashboard. None means the
    # widget is not clickable for cross-filter purposes. Shape:
    # ``{"filter_field": "project_id", "filter_value_from": "row.project_id"}``.
    drill_path: Mapped[dict | None] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=True,
        default=None,
    )


class ReportDefinition(Base):
    """A reusable report template."""

    __tablename__ = "oe_bi_dashboards_report_definition"

    code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    source_modules: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    query_spec_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    output_format: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pdf",
        server_default="pdf",
    )
    template_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="personal",
        server_default="personal",
        index=True,
    )


class ReportSchedule(Base):
    """A cron-style schedule for a :class:`ReportDefinition`."""

    __tablename__ = "oe_bi_dashboards_report_schedule"

    report_definition_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_bi_dashboards_report_definition.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    frequency: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="daily",
        server_default="daily",
    )
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_of_day: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="08:00",
        server_default="08:00",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        server_default="UTC",
    )
    recipients_json: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    filter_overrides_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


class AlertRule(Base):
    """A threshold-based alert tied to a single KPI.

    The default mode is a single ``condition + threshold_value`` against
    ``kpi_code``. For composite rules (e.g. ``cpi < 0.95 AND project.phase
    == 'execution'``), populate ``expression_json`` with a tree of
    ``{op, lhs, rhs}`` nodes — see :func:`evaluate_alert_expression` for
    the supported grammar. When ``expression_json`` is non-empty it takes
    precedence over ``condition`` / ``threshold_value``.
    """

    __tablename__ = "oe_bi_dashboards_alert_rule"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kpi_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    condition: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="below",
        server_default="below",
    )
    threshold_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
    )
    threshold_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="warning",
        server_default="warning",
    )
    scope_project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    recipients_json: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    channels_json: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    throttle_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3600,
        server_default="3600",
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    # Composite expression — JSON tree of {op, lhs, rhs}; empty for single KPI
    expression_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


class SavedFilter(Base):
    """A reusable filter set scoped to a UI module.

    Sharing model: ``owner_user_id`` is the creator. ``shared_with_user_ids``
    is the explicit allow-list of additional users who see the filter in
    their personal library. ``scope='global'`` or ``'role'`` bypasses the
    list — everyone in scope sees it.
    """

    __tablename__ = "oe_bi_dashboards_saved_filter"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="personal",
        server_default="personal",
    )
    module: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    filter_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    shared_with_user_ids_json: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )


class ReportRun(Base):
    """An execution of a ReportDefinition — for audit + download history.

    ``file_path`` is a server-local path to the rendered PDF/XLSX/CSV; the
    HTTP layer exposes it via a streamed download endpoint and does NOT
    return raw paths to callers.
    """

    __tablename__ = "oe_bi_dashboards_report_run"

    report_definition_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_bi_dashboards_report_definition.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    output_format: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pdf",
    )
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    row_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="running",
        server_default="running",
        index=True,
    )  # running | success | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DashboardWidgetSnapshot(Base):
    """Cached computed value for a widget."""

    __tablename__ = "oe_bi_dashboards_widget_snapshot"

    widget_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_bi_dashboards_widget.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    value_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class KPIValue(Base):
    """Historical KPI value for trend analysis."""

    __tablename__ = "oe_bi_dashboards_kpi_value"

    kpi_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    period_start: Mapped[_date] = mapped_column(Date, nullable=False)
    period_end: Mapped[_date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(
        Numeric(20, 6),
        nullable=False,
        default=Decimal("0"),
    )
    unit: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ratio",
        server_default="ratio",
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    source_record_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )


__all__ = [
    "AlertRule",
    "Dashboard",
    "DashboardWidget",
    "DashboardWidgetSnapshot",
    "KPIDefinition",
    "KPIValue",
    "ReportDefinition",
    "ReportRun",
    "ReportSchedule",
    "SavedFilter",
]
