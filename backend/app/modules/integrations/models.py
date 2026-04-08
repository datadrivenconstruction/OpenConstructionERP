"""Integrations ORM models.

Tables:
    oe_integrations_webhook  — user-defined webhook endpoints
    oe_integrations_delivery — delivery log for each webhook dispatch attempt
    oe_integrations_config   — chat connector configs (Teams, Slack, Telegram, etc.)
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class WebhookEndpoint(Base):
    """A user-configured outgoing webhook endpoint.

    When events matching the ``events`` list occur, an HTTP POST is sent
    to ``url`` with a JSON payload.  If a ``secret`` is set, the request
    includes an ``X-Webhook-Signature`` header (HMAC-SHA256).
    """

    __tablename__ = "oe_integrations_webhook"
    __table_args__ = (Index("ix_webhook_user_active", "user_id", "is_active"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    events: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    last_triggered_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        status = "active" if self.is_active else "disabled"
        return f"<WebhookEndpoint {self.name} [{status}] -> {self.url[:40]}>"


class WebhookDelivery(Base):
    """Log entry for a single webhook delivery attempt."""

    __tablename__ = "oe_integrations_delivery"
    __table_args__ = (Index("ix_delivery_webhook_created", "webhook_id", "created_at"),)

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_integrations_webhook.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<WebhookDelivery {self.event_type} -> {self.status_code}>"


class IntegrationConfig(Base):
    """A user-configured chat notification connector.

    Supported integration_type values: teams, slack, telegram, email, webhook.
    The ``config`` JSON column stores connector-specific credentials:
        - teams:    {"webhook_url": "https://..."}
        - slack:    {"webhook_url": "https://hooks.slack.com/..."}
        - telegram: {"bot_token": "123456:ABC...", "chat_id": "-100..."}
        - email:    {"smtp_host": "...", "smtp_port": 587, ...}
    """

    __tablename__ = "oe_integrations_config"
    __table_args__ = (
        Index("ix_intconfig_user_active", "user_id", "is_active"),
        Index("ix_intconfig_user_type", "user_id", "integration_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    integration_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    events: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=lambda: ["*"],
        server_default='["*"]',
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    last_triggered_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        status = "active" if self.is_active else "disabled"
        return f"<IntegrationConfig {self.integration_type}:{self.name} [{status}]>"
