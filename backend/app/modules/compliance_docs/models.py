# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Compliance documents ORM models.

Tables:
    oe_compliance_docs_doc — project-scoped tracker for any document
        (insurance / permit / bond / certification) that has an
        ``effective_date`` / ``expires_at`` window and a reminder
        threshold.

Status is derived in :mod:`app.modules.compliance_docs.service` and
persisted on every write so list endpoints can filter on
``status='expiring_soon'`` without a window function. ``status`` is
indexed for that exact reason.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from decimal import Decimal

from sqlalchemy import JSON, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ComplianceDoc(Base):
    """‌⁠‍A tracked compliance document (insurance / permit / bond / cert)."""

    __tablename__ = "oe_compliance_docs_doc"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Type & identification ──────────────────────────────────────────
    doc_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # ── Coverage / amount ──────────────────────────────────────────────
    coverage_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )

    # ── Lifecycle dates ────────────────────────────────────────────────
    effective_date: Mapped[_date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[_date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    notify_days_before: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )

    # ── Derived status (recomputed on every write) ────────────────────
    # One of: active | expiring_soon | expired | cancelled | void.
    # Stored (not computed) so the index hits without a window function.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )

    # ── Optional attachment to a previously-uploaded document ──────────
    # Same-project guard enforced in the service layer.
    attachment_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_documents_document.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Free-form ──────────────────────────────────────────────────────
    notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Audit ─────────────────────────────────────────────────────────
    created_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    # ``updated_by`` is recorded on every PATCH inside ``metadata_``
    # under the ``"updated_by"`` key — kept off the SQL schema so this
    # bug-fix doesn't require an alembic migration. The local upload
    # (path / mime / size) lives in ``metadata_["attachment"]`` for the
    # same reason; see :mod:`service` for the read/write helpers.

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return f"<ComplianceDoc {self.doc_type} {self.name[:30]!r} expires={self.expires_at} status={self.status}>"


__all__ = ["ComplianceDoc"]
