# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Value-realized ORM models.

The value module is otherwise a pure composition layer that owns no records; the
single exception is this small admin-tunable lookup.

``oe_value_time_factor`` holds a tenant's overrides for the hours-saved minute
factors. Each row says "for this tenant, one assisted ``(module, action)`` is
worth this many minutes of saved manual work", overriding the conservative
seed default baked into :data:`app.modules.value.time_saved.DEFAULT_FACTORS`.
Only the overridden pairs are stored; an unset pair simply falls back to the
default, so a fresh install needs no rows at all and the table stays sparse.

These are minutes of effort, never money - there is no currency anywhere on this
table. ``minutes`` is a ``Numeric`` so it never touches float, matching how the
pure engine carries every factor as a ``Decimal``.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TimeSavedFactor(Base):
    """One tenant's override of a single hours-saved minute factor.

    A row exists only for a ``(module, action)`` pair the tenant has explicitly
    tuned. ``tenant_id`` is the access-scoping key (the owning user's id in the
    single-tenant installs shipped today, matching ``Contact.tenant_id``). The
    ``(tenant_id, module, action)`` triple is unique so an upsert tunes the one
    row rather than accumulating duplicates.
    """

    __tablename__ = "oe_value_time_factor"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "module",
            "action",
            name="uq_value_time_factor_scope",
        ),
    )

    # Access-scoping key. Indexed because every read filters on it. Nullable to
    # match the platform tenant_id convention, though the endpoint never writes a
    # null (an anonymous caller cannot reach the admin-gated route).
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # The activity-log ``module`` + ``action`` this factor applies to.
    module: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    # Minutes of manual work one assisted action of this kind displaces. A
    # Numeric (not Float) so the value stays exact through the Decimal engine.
    # Non-negative; the service rejects negatives before persisting.
    minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    def __repr__(self) -> str:
        return f"<TimeSavedFactor {self.tenant_id} {self.module}/{self.action}={self.minutes}>"
