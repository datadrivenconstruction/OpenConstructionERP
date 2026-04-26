# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance DSL ORM models.

Single table — :class:`ComplianceDSLRule` — stores the raw YAML/JSON
definition of a user-authored validation rule plus the parsed metadata
the engine needs to register it (``rule_id``, ``severity``,
``standard``).

The full AST is *not* persisted: it is reconstructed on load by feeding
the stored ``definition_yaml`` back through
:func:`app.core.validation.dsl.parse_definition`. This keeps the on-disk
shape forward-compatible with future grammar extensions and avoids
schema migrations whenever the AST changes shape.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ComplianceDSLRule(Base):
    """A user-authored DSL validation rule.

    ``rule_id`` is unique per tenant so two tenants in the same database
    can both author ``custom.boq.no_zero_quantities`` without collision.
    ``definition_yaml`` is the source of truth — every other column is
    a denormalised hint computed at save time.
    """

    __tablename__ = "oe_compliance_dsl_rule"

    tenant_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    rule_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    standard: Mapped[str] = mapped_column(
        String(64), nullable=False, default="custom",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Original YAML/JSON the user submitted — re-parsed on every load.
    definition_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    __table_args__ = (
        # rule_id must be unique per tenant — admin / system rules use
        # tenant_id NULL and must therefore be globally unique among
        # other ``tenant_id IS NULL`` rows. SQLite treats every NULL as
        # distinct so this constraint behaves correctly there too.
        UniqueConstraint(
            "tenant_id", "rule_id",
            name="uq_oe_compliance_dsl_rule_tenant_rule_id",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return (
            f"ComplianceDSLRule(id={self.id}, rule_id={self.rule_id!r}, "
            f"severity={self.severity}, is_active={self.is_active})"
        )


__all__ = ["ComplianceDSLRule"]
