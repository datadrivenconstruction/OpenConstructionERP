# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views ORM model.

Tables:
    oe_list_views_view - one named layout of one list page, owned by a user,
                         visible to its owner or, when shared, to the tenant.
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ListView(Base):
    """A named list layout (filters, columns, sort) for one page key."""

    __tablename__ = "oe_list_views_view"
    __table_args__ = (
        Index("ix_list_views_tenant_scope", "tenant_id", "scope_key"),
        UniqueConstraint("user_id", "scope_key", "name", name="uq_list_views_owner_scope_name"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Access key: a shared view is visible to every user of this tenant only.
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: Page key, e.g. boq.positions or a route such as /tasks.
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
