# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost recovery ORM models.

Tables:
    oe_cost_recovery_back_charge - a cost the project intends to recover from
        the responsible party, with its commercial state and amounts.
    oe_cost_recovery_apportionment - one party's share of a single back-charge
        when responsibility is split across several parties, persisted as the
        Decimal money assigned to that party so the split is durable and
        auditable rather than recomputed on every read.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base


class BackCharge(Base):
    """A back-charge: a cost recoverable from the party responsible for it."""

    __tablename__ = "oe_cost_recovery_back_charge"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The originating record (a change order, NCR, defect, delay event). A free
    # reference string so the module stays decoupled from any one source table.
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Who the cost is charged to, as a label. Kept as the fallback when no
    # subcontractor or contact is linked, and filled from the linked record's
    # name when left blank.
    responsible_party: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # The party as a record. Plain GUIDs with no foreign key, like every
    # cross-module link (the tables belong to the subcontractors and contacts
    # modules); the service checks that each id resolves before it is stored.
    # A contact that belongs to a subcontractor stamps both, so a query by
    # subcontractor finds the charge either way.
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # The record the cost arose from, checked to sit in the same project.
    ncr_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    punch_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # How the liability is grounded (a contract clause, an NCR, an instruction).
    basis: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    gross_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    # Share of the gross cost judged recoverable, 0..1. NUMERIC(6,4) keeps four
    # decimal places (for example 0.3333) and always reads back as Decimal.
    chargeable_pct: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("1"))
    # Platform rule: no model-/DB-level hardcoded currency. The column defaults
    # to empty; the service stamps the project's currency on create.
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default="", default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed", index=True)
    recovered_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    # ISO-8601 timestamp strings stamped when the back-charge is agreed and when
    # it is fully recovered (String(40) leaves margin for any offset form).
    agreed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recovered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BackCharge {self.id} {self.responsible_party!r} {self.status}>"


class BackChargeApportionment(Base):
    """One party's apportioned share of a single back-charge.

    A back-charge usually has one ``responsible_party``, but liability is often
    split - a defect may be 60% the subcontractor's and 40% the designer's. Each
    row here records the money assigned to one party by a split of one
    back-charge: the ``share_pct`` that was applied (0..1) and the resulting
    ``share_amount`` in the back-charge's currency. The amounts for a given
    back-charge always sum back to its chargeable amount exactly (the pure
    apportionment engine reconciles the rounding residual into the largest
    share), so the persisted rows are a faithful, auditable record of the split
    rather than a lossy approximation.
    """

    __tablename__ = "oe_cost_recovery_apportionment"

    # The back-charge this apportionment splits. Cascades so deleting a
    # back-charge clears its apportionment rows.
    back_charge_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cost_recovery_back_charge.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised project id (also carried on the parent back-charge) so the
    # rows are project-scoped for access control and listing without a join.
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Who this share is charged to: a contact / subcontractor id or a label.
    party: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # How the share is grounded (a contract clause, an apportionment finding).
    basis: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Share of the chargeable amount assigned to this party, 0..1. NUMERIC(6,4)
    # keeps four decimal places (for example 0.6000) and reads back as Decimal.
    share_pct: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0"))
    # The money assigned to this party, in the back-charge's currency.
    share_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    # Platform rule: no model-/DB-level hardcoded currency. The service copies
    # the parent back-charge's currency onto each row.
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default="", default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BackChargeApportionment {self.id} {self.party!r} {self.share_amount}>"
