# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MCP server ORM models.

One table, ``oe_mcp_settings``: whether a person lets external AI clients
reach their data through the MCP endpoint, and how fast. Everything else the
module needs already has a home:

* tokens are rows of ``oe_users_api_key`` whose declared scopes carry
  ``mcp.access`` (see :mod:`app.modules.mcp.auth`), so revocation, expiry and
  ``last_used_at`` behave exactly like every other API key;
* every tool call is a row of ``oe_activity_log`` with ``module="mcp"``;
* every proposed change is a row of ``oe_erp_chat_action`` with
  ``source="mcp"``, reviewed in the same Changes view as the in-app assistant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

DEFAULT_RATE_LIMIT_PER_MINUTE = 60
MIN_RATE_LIMIT_PER_MINUTE = 1
MAX_RATE_LIMIT_PER_MINUTE = 600


class McpSettings(Base):
    """Per-user switch and rate limit for the MCP endpoint.

    A missing row reads as "disabled": nobody is reachable by an external
    client until they turn it on themselves.
    """

    __tablename__ = "oe_mcp_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_RATE_LIMIT_PER_MINUTE,
        server_default=str(DEFAULT_RATE_LIMIT_PER_MINUTE),
    )

    def __repr__(self) -> str:
        return f"<McpSettings user={self.user_id} enabled={self.enabled}>"
