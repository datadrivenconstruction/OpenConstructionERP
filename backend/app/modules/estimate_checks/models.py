# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check ORM models.

Tables:
    oe_estchk_settings    - one row per workspace (tenant): KPI on/off, thresholds,
                            comparables filter. No row means defaults.
    oe_estchk_user_pref   - per-user display preference (all / issues / badge / off).
    oe_estchk_acceptance  - a finding a person accepted, with reason, author and time.

Ratings are never stored: they are computed on demand and cached in memory per
estimate revision.
"""

import uuid

from sqlalchemy import JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class EstimateCheckSettings(Base):
    """Workspace settings of the estimate check."""

    __tablename__ = "oe_estchk_settings"
    __table_args__ = (UniqueConstraint("tenant_key", name="uq_estchk_settings_tenant"),)

    # Tenant id, or "" for a single-company install.
    tenant_key: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    settings_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "settings", JSON, nullable=False, default=dict, server_default="{}"
    )
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class EstimateCheckUserPref(Base):
    """How much of the estimate check one user wants to see."""

    __tablename__ = "oe_estchk_user_pref"
    __table_args__ = (UniqueConstraint("user_id", name="uq_estchk_user_pref_user"),)

    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    display_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="badge", server_default="badge")


class EstimateCheckAcceptance(Base):
    """A finding accepted by a person, with the reason. Soft link to the BOQ (no FK)."""

    __tablename__ = "oe_estchk_acceptance"
    __table_args__ = (UniqueConstraint("boq_id", "kpi_id", name="uq_estchk_acceptance_boq_kpi"),)

    boq_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    kpi_id: Mapped[str] = mapped_column(String(60), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status_at_accept: Mapped[str] = mapped_column(String(10), nullable=False, default="suspect")
    value_at_accept: Mapped[str | None] = mapped_column(String(50), nullable=True)
    accepted_by: Mapped[str] = mapped_column(String(36), nullable=False)
