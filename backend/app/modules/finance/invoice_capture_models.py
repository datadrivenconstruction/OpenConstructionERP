# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Invoice-approval DMS models.

The invoice-capture inbox is the document-management side of accounts payable:
a supplier invoice or delivery note is captured (uploaded + read), a booking is
proposed and confirmed, an approver signs it off, and the confirmed booking is
posted to the general ledger. Once posted the record is sealed into a
tamper-evident, GoBD-style archive: the original document is kept unaltered, a
content hash covers the original bytes, an archive hash covers the confirmed
booking, and a retention marker records how long the record must be kept.

Tables:
    oe_finance_captured_invoice - one inbox item and its full lifecycle.

The heavy accounting truth is never duplicated here: posting reuses the finance
module's :meth:`FinanceService.post_journal_entry` double-entry ledger, and the
append-only action log reuses :func:`app.core.audit_log.log_activity`
(``entity_type="finance_captured_invoice"``). This table only owns the
document, the extracted/reviewed draft, the confirmed booking and the seal.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base


class CapturedInvoice(Base):
    """A captured supplier invoice / delivery note moving through the DMS flow.

    Status flow (see ``invoice_capture_service._CAPTURE_TRANSITIONS``)::

        captured -> coded -> approved -> posted   (happy path)
                 \\-> queried / rejected            (send back / decline)

    A ``posted`` row is read-only: the seal (``archive_hash``) is set and no
    further field edit or state change is allowed.
    """

    __tablename__ = "oe_finance_captured_invoice"
    __table_args__ = (
        Index("ix_captured_invoice_project_status", "project_id", "status"),
        # Duplicate detection: same supplier invoice number inside a project.
        Index("ix_captured_invoice_project_number", "project_id", "invoice_number"),
        # Archive integrity: find a record by the hash of the original document.
        Index("ix_captured_invoice_content_hash", "content_sha256"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "invoice" (bookable) or "delivery_note" (goods-received, not booked).
    doc_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="invoice")
    # Only "payable" is meaningful for the inbox today; kept for symmetry with
    # the Invoice model and to leave room for incoming credit notes.
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="payable")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="captured", index=True)

    # ── Original document (stored unaltered) ────────────────────────────────
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Key into the platform storage backend (local FS or S3/MinIO). NULL for a
    # manual-entry capture that has no source file.
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # SHA-256 over the original document bytes, captured at upload time. The
    # tamper-evident anchor: the verify endpoint re-hashes the stored bytes and
    # compares. NULL for manual entry.
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Extracted / human-reviewed header fields ────────────────────────────
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    supplier_tax_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    supplier_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    invoice_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    due_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    amount_net: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    amount_tax: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    amount_gross: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    # Draft line items as JSON (a captured draft, not a posted ledger record):
    # [{"description", "quantity", "unit_rate", "amount", "cost_code"}].
    line_items: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # ── Extraction provenance (AI-augmented, human-confirmed) ───────────────
    # How the draft was produced: manual | plaintext | pdfium (pymupdf on older rows) | pytesseract |
    # xml | llm | none. Drives the confidence UI and the audit story.
    extraction_engine: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    # First N chars of the extracted text, kept for provenance / re-review.
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {field_name: 0.0-1.0} confidence per extracted field.
    field_confidence: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Confirmed booking (set when the user "codes" the invoice) ───────────
    booking_expense_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    booking_tax_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    booking_payable_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    booking_cost_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Cost-allocation target project (defaults to project_id). Plain GUID: the
    # allocation may point at a different project in the same workspace.
    booking_project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    # ── Workflow actors + timestamps ────────────────────────────────────────
    approver_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    queried_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Posting + tamper-evident archive seal ───────────────────────────────
    posted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # transaction_ref of the GL journal entry this capture posted.
    posted_transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The payable Invoice row created for downstream payment tracking.
    posted_invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # SHA-256 seal over {content hash + confirmed booking + amounts + ref},
    # computed once at posting. The verify endpoint recomputes and compares, so
    # any post-hoc edit to the booking or amounts is detectable.
    archive_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_sealed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # ISO date until which the record must be retained (GoBD default 10 years).
    retention_until: Mapped[str | None] = mapped_column(String(40), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CapturedInvoice {self.invoice_number or '(no number)'} ({self.status})>"
