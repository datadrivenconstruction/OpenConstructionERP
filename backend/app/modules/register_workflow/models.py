# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow ORM models.

Tables:
    oe_register_workflow_item - one register item (the record itself)
    oe_register_workflow_step - its ordered workflow steps

The item row is deliberately thin: reference, kind, title, the due date
and a JSON ``fields`` bag holding the per-kind raise-form answers. The
platform's own registers (RFQ, RFI, correspondence) keep their native
tables; this module is the WORKFLOW over an item, plus a home for the
kinds the platform has no native register for (toolbox, delay).
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

STEP_TYPES = ("step", "gate", "route")
STEP_STATES = ("open", "done", "not_required")


class RegisterItem(Base):
    """One register entry - an RFI, RFQ, order, variation, delay or talk."""

    __tablename__ = "oe_register_workflow_item"
    __table_args__ = (
        # Reference is unique per project: the auto-generator takes MAX+1
        # which races under concurrent creates; the constraint turns the
        # loser into an IntegrityError the service retries.
        UniqueConstraint("project_id", "reference", name="uq_oe_register_workflow_item_ref"),
        Index("ix_register_item_project_kind", "project_id", "kind"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    #: open | closed - closed when the last step completes.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open", index=True)
    #: The date this item is due back (per kind: response required by,
    #: quotes due, ETA…). ISO yyyy-mm-dd; drives the overdue colour.
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Raise-form answers, {label: value}. Internal (money) labels live
    #: here too - the email builder strips them, the register shows them.
    fields: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    #: Who it went to (contact ids) and what it links to.
    recipient_contact_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    #: Cross-register provenance: "raised from RFI-004" both ways.
    raised_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    #: The native record this item mirrors, when one exists (an RFQ row,
    #: a correspondence row) - so the workspace can deep-link.
    linked_entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    linked_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    steps: Mapped[list["RegisterStep"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RegisterStep.position",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RegisterItem {self.reference} ({self.kind}/{self.status})>"


class RegisterCounter(Base):
    """One row per (prefix, scope). The number is the record.

    References were once MAX+1 of the ones already on a PROJECT, which
    made them per-project and three digits: two jobs both held an
    ``RFI-004``, so a forwarded reply carrying only its reference was
    ambiguous, and deleting an item let its number be re-issued.

    The fix then was to make the series GLOBAL per prefix. That removed
    the ambiguity but lost the job: ``REG-RFI-000001`` does not say which
    job it belongs to, and people read these out on the phone.

    ``scope`` gets both. The job number goes INTO the reference
    (``REG-RFI-25406-0001``), so each job owns its own series and a
    reference is still unique across the business - the job number is what
    disambiguates, not the width of a shared counter.

    An empty scope is the un-scoped series, still global: that is where
    ``REG-MSG-000042`` lives, because a mail number answers "which email"
    rather than "which job", and the job is already named by the item
    reference quoted in the same mail.

    Read with a row lock and never goes backwards, so a number is burned
    exactly once even when two people raise in the same second.
    """

    __tablename__ = "oe_register_workflow_counter"
    __table_args__ = (UniqueConstraint("prefix", "scope", name="uq_register_workflow_counter_prefix_scope"),)

    #: "RFQ", "RFI", "ORD"… uppercase, from templates.KIND_PREFIX.
    prefix: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    #: The job number this series belongs to; "" for global series.
    scope: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="", index=True)
    #: The last number ISSUED. The next mint is value + 1.
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RegisterCounter {self.prefix}/{self.scope or '-'}={self.value}>"


class RegisterStep(Base):
    """One workflow step. Order is ``position``; history is immutable."""

    __tablename__ = "oe_register_workflow_step"
    __table_args__ = (Index("ix_register_step_item_pos", "item_id", "position"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_register_workflow_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: step | gate | route
    step_type: Mapped[str] = mapped_column(String(10), nullable=False, default="step")
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Who signs a gate ("PM", "Client", "Site lead").
    owner: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    #: Route branches {label: [step names]}; empty for other types.
    branches: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    #: open | done | not_required
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    #: The branch a route actually took - the path on the record.
    chosen_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    completed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: A gate passed below its rule records WHY, on the record, forever.
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Set when this step raises another register; carries the new item's
    #: reference once raised ("Variation raised → VO-009").
    raises_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    raised_reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_gate_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    item: Mapped["RegisterItem"] = relationship(back_populates="steps")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RegisterStep {self.position}:{self.name[:30]} ({self.state})>"
