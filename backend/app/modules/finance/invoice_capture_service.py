# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Invoice-approval DMS service.

Orchestrates the capture -> code -> approve -> post -> archive lifecycle by
composing existing platform primitives rather than duplicating them:

* storage:   :mod:`app.core.storage` + :mod:`app.core.upload_streaming`
             (stream to temp, SHA-256 the bytes, put unaltered into the backend).
* extraction: :func:`app.modules.file_search.extractors.extract_text`
             (PDFium text layer -> Tesseract OCR) with an
             optional LLM structuring pass; a pure heuristic fallback means the
             flow works with zero AI.
* booking:   pure :mod:`app.modules.finance.invoice_capture_logic`, posted
             through :meth:`FinanceService.post_journal_entry` (the one GL path).
* audit:     append-only :func:`app.core.audit_log.log_activity`.

Everything money is Decimal here; the router/schemas handle the string wire.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import get_activity_for_entity, log_activity
from app.core.file_signature import (
    FileSignatureMismatch,
    mime_for_signature,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.core.storage import get_storage_backend
from app.core.upload_streaming import stream_upload_to_temp
from app.modules.finance import invoice_capture_logic as logic
from app.modules.finance.invoice_capture_models import CapturedInvoice
from app.modules.finance.invoice_capture_schemas import (
    BookingInput,
    CaptureManualCreate,
    CaptureUpdate,
)
from app.modules.finance.schemas import (
    InvoiceCreate,
    InvoiceLineItemCreate,
    JournalEntryCreate,
    JournalLineInput,
)
from app.modules.finance.service import FinanceService

logger = logging.getLogger(__name__)

ENTITY_TYPE = "finance_captured_invoice"
MODULE = "finance"

# Invoices are small documents; cap uploads and in-memory extraction generously.
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_EXTRACT_BYTES = 25 * 1024 * 1024
EXTRACTED_TEXT_CAP = 20_000

# PDF, raster image, and UBL / CII e-invoice XML. The strict signature gate
# keeps executables / archives out of the inbox.
ALLOWED_INVOICE_TYPES = frozenset({"pdf", "png", "jpeg", "gif", "webp", "xml"})

# Status machine. A posted row is terminal and sealed (read-only).
_CAPTURE_TRANSITIONS: dict[str, set[str]] = {
    "captured": {"coded", "queried", "rejected"},
    "coded": {"approved", "captured", "queried", "rejected"},
    "approved": {"posted", "coded", "rejected"},
    "queried": {"captured", "coded", "rejected"},
    "rejected": {"captured"},
    "posted": set(),
}


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _retention_until_iso(years: int = logic.DEFAULT_RETENTION_YEARS) -> str:
    now = datetime.now(UTC)
    day = now.day
    if now.month == 2 and day == 29:
        day = 28  # keep a valid date after a decade shift
    return f"{now.year + years:04d}-{now.month:02d}-{day:02d}"


def _po_err(status_code: int, code: str, message: str, **params: object) -> HTTPException:
    """An HTTP error whose ``detail`` carries a translatable key (``api_errors.invoice_capture_<code>``)."""
    return HTTPException(
        status_code,
        detail={
            "code": f"invoice_capture_{code}",
            "message": message,
            "params": params,
        },
    )


class InvoiceCaptureService:
    """Business logic for the invoice-approval DMS inbox."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.finance = FinanceService(session)

    # ── Read ────────────────────────────────────────────────────────────────

    async def get(self, capture_id: uuid.UUID) -> CapturedInvoice:
        row = await self.session.get(CapturedInvoice, capture_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Captured invoice not found")
        return row

    async def list(
        self,
        *,
        project_id: uuid.UUID,
        status_filter: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[CapturedInvoice], int]:
        base = select(CapturedInvoice).where(CapturedInvoice.project_id == project_id)
        if status_filter:
            base = base.where(CapturedInvoice.status == status_filter)
        total = await self.session.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
        rows = (
            (await self.session.execute(base.order_by(CapturedInvoice.created_at.desc()).limit(limit).offset(offset)))
            .scalars()
            .all()
        )
        return list(rows), int(total or 0)

    # ── Capture (intake) ────────────────────────────────────────────────────

    async def capture_from_upload(
        self,
        *,
        project_id: uuid.UUID,
        file: UploadFile,
        user_id: str | None,
        doc_kind: str = "invoice",
    ) -> CapturedInvoice:
        """Store the uploaded document unaltered, hash it, and extract a draft."""
        capture_id = uuid.uuid4()
        filename = (file.filename or "document").strip()[:255]

        payload: bytes | None = None
        try:
            async with stream_upload_to_temp(file, max_bytes=MAX_UPLOAD_BYTES) as up:
                if up.size == 0:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
                try:
                    detected = require_signature(up.head, ALLOWED_INVOICE_TYPES, filename=filename)
                except FileSignatureMismatch as exc:
                    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
                mime = mime_for_signature(detected)
                sha = up.sha256_hex
                size = up.size
                if size <= MAX_EXTRACT_BYTES:
                    payload = up.path.read_bytes()
                key = f"finance-invoices/{project_id}/{capture_id}/{sha}"
                await get_storage_backend().put_stream(key, up.path)
        except ValueError as exc:
            # stream_upload_to_temp raises ValueError on the size cap.
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc

        engine, text, fields, conf = self._extract(payload, mime)
        if "po_reference" not in fields and text:
            ref = logic.extract_po_reference(text)
            if ref:
                fields["po_reference"] = ref
                conf["po_reference"] = 0.5

        row = CapturedInvoice(
            id=capture_id,
            project_id=project_id,
            doc_kind=doc_kind if doc_kind in {"invoice", "delivery_note"} else "invoice",
            direction="payable",
            status="captured",
            original_filename=filename,
            storage_key=key,
            mime_type=mime,
            file_size=size,
            content_sha256=sha,
            extraction_engine=engine,
            extracted_text=(text or "")[:EXTRACTED_TEXT_CAP] or None,
            field_confidence=conf,
            created_by=uuid.UUID(user_id) if user_id else None,
        )
        self._apply_fields(row, fields)
        if fields.get("line_items"):
            row.line_items = list(fields["line_items"])
        self.session.add(row)
        await self.session.flush()
        await self._resolve_po_reference(row)

        await self._log(
            row,
            action="captured",
            to_status="captured",
            actor_id=user_id,
            metadata={"engine": engine, "filename": filename, "sha256": sha},
        )
        return row

    async def capture_manual(self, data: CaptureManualCreate, user_id: str | None) -> CapturedInvoice:
        """Create a captured invoice from hand-entered fields (no document)."""
        row = CapturedInvoice(
            project_id=data.project_id,
            doc_kind=data.doc_kind,
            direction="payable",
            status="captured",
            original_filename="",
            supplier_name=data.supplier_name,
            supplier_tax_id=data.supplier_tax_id,
            supplier_contact_id=data.supplier_contact_id,
            invoice_number=data.invoice_number,
            invoice_date=data.invoice_date,
            due_date=data.due_date,
            currency_code=data.currency_code,
            amount_net=logic.to_decimal(data.amount_net),
            amount_tax=logic.to_decimal(data.amount_tax),
            amount_gross=logic.to_decimal(data.amount_gross),
            line_items=[li.model_dump() for li in data.line_items],
            extraction_engine="manual",
            field_confidence={},
            created_by=uuid.UUID(user_id) if user_id else None,
        )
        row.po_reference = (data.po_reference or "").strip() or None
        self.session.add(row)
        await self.session.flush()
        await self._resolve_po_reference(row)
        await self._log(row, action="captured", to_status="captured", actor_id=user_id, metadata={"engine": "manual"})
        return row

    def _extract(self, payload: bytes | None, mime: str | None) -> tuple[str, str, dict, dict[str, float]]:
        """Run text extraction + heuristic parsing. Returns (engine, text, fields, conf)."""
        if not payload:
            return "none", "", {}, {}
        if mime == "application/xml":
            return self._extract_einvoice(payload)
        try:
            from app.modules.file_search.extractors import extract_text

            result = extract_text(payload, mime)
            text, engine = result.text or "", result.engine
        except Exception as exc:  # noqa: BLE001 - extraction is best-effort
            logger.warning("Invoice text extraction failed: %s", exc)
            return "none", "", {}, {}

        fields, conf = logic.extract_fields_from_text(text)
        return engine, text, fields, conf

    @staticmethod
    def _extract_einvoice(payload: bytes) -> tuple[str, str, dict, dict[str, float]]:
        """Read a structured UBL / CII e-invoice. Fields are exact, so confidence is 1."""
        from app.modules.einvoice.inbound import InboundParseError, parse_inbound

        try:
            parsed = parse_inbound(payload)
        except InboundParseError as exc:
            logger.info("Inbound XML is not a UBL/CII invoice: %s", exc)
            return "none", "", {}, {}
        fields = {k: v for k, v in parsed.capture_fields().items() if v not in ("", None)}
        if parsed.order_reference:
            fields["po_reference"] = parsed.order_reference
        if parsed.lines:
            fields["line_items"] = parsed.lines
        summary = (
            f"{parsed.syntax.upper()} e-invoice {parsed.invoice_number} from {parsed.supplier_name}"
            f" ({parsed.supplier_endpoint or 'no endpoint'})"
        )
        return f"einvoice_{parsed.syntax}", summary, fields, dict.fromkeys(fields, 1.0)

    async def enrich_with_llm(self, capture_id: uuid.UUID, user_id: str | None) -> CapturedInvoice:
        """Optional AI pass over the stored text to fill gaps. Degrades to no-op."""
        row = await self.get(capture_id)
        self._guard_editable(row)
        text = row.extracted_text or ""
        if not text.strip():
            return row
        fields, conf = await self._maybe_llm_extract(text, user_id)
        if not fields:
            return row
        # Only fill blanks - never overwrite a value the human already reviewed.
        before = self._snapshot(row)
        self._apply_fields(row, fields, only_if_blank=True)
        merged_conf = dict(row.field_confidence or {})
        for k, v in conf.items():
            merged_conf.setdefault(k, v)
        row.field_confidence = merged_conf
        if row.extraction_engine in {"manual", "none", "plaintext"}:
            row.extraction_engine = "llm"
        await self.session.flush()
        await self._log(
            row,
            action="ai_enriched",
            actor_id=user_id,
            before=before,
            after=self._snapshot(row),
            metadata={"fields": sorted(fields.keys())},
        )
        return row

    async def _maybe_llm_extract(self, text: str, user_id: str | None) -> tuple[dict, dict[str, float]]:
        """Ask a configured LLM to structure the invoice. Returns ({}, {}) if unavailable."""
        try:
            from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
            from app.modules.ai.repository import AISettingsRepository

            settings = None
            if user_id:
                try:
                    settings = await AISettingsRepository(self.session).get_by_user_id(uuid.UUID(user_id))
                except Exception:  # noqa: BLE001
                    settings = None
            provider, api_key, model = resolve_provider_key_model(settings)
        except Exception:  # noqa: BLE001 - no key / no module -> skip AI
            return {}, {}

        system = (
            "You extract structured data from a construction supplier invoice. "
            "Return ONLY a JSON object with these optional keys: supplier_name, "
            "supplier_tax_id, invoice_number, invoice_date (YYYY-MM-DD), currency_code "
            "(ISO 4217), amount_net, amount_tax, amount_gross (plain decimal strings). "
            "Omit any key you are not confident about. Do not invent values."
        )
        prompt = f"Invoice text:\n\n{text[:6000]}"
        try:
            raw, _tokens = await call_ai(
                provider=provider, api_key=api_key, system=system, prompt=prompt, max_tokens=800, model=model
            )
            parsed = extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.info("Invoice LLM extraction skipped: %s", exc)
            return {}, {}
        if not isinstance(parsed, dict):
            return {}, {}

        fields: dict = {}
        conf: dict[str, float] = {}
        for key in ("supplier_name", "supplier_tax_id", "invoice_number", "invoice_date", "currency_code"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                fields[key] = val.strip()
                conf[key] = 0.75
        for key in ("amount_net", "amount_tax", "amount_gross"):
            if key in parsed and parsed[key] is not None:
                d = logic.to_decimal(parsed[key])
                if d >= 0:
                    fields[key] = logic.money_str(d)
                    conf[key] = 0.75
        return fields, conf

    # ── Update draft ─────────────────────────────────────────────────────────

    async def update(self, capture_id: uuid.UUID, data: CaptureUpdate, user_id: str | None) -> CapturedInvoice:
        row = await self.get(capture_id)
        self._guard_editable(row)
        before = self._snapshot(row)
        patch = data.model_dump(exclude_unset=True)
        for field_name in (
            "supplier_name",
            "supplier_tax_id",
            "supplier_contact_id",
            "invoice_number",
            "invoice_date",
            "due_date",
            "currency_code",
        ):
            if field_name in patch and patch[field_name] is not None:
                setattr(row, field_name, patch[field_name])
        for money_field in ("amount_net", "amount_tax", "amount_gross"):
            if money_field in patch and patch[money_field] is not None:
                setattr(row, money_field, logic.to_decimal(patch[money_field]))
        if "line_items" in patch and patch["line_items"] is not None:
            row.line_items = [dict(li) for li in patch["line_items"]]
        if "po_reference" in patch and patch["po_reference"] is not None:
            row.po_reference = patch["po_reference"].strip() or None
            if row.purchase_order_id is None:
                await self._resolve_po_reference(row)
        await self.session.flush()
        await self._log(row, action="updated", actor_id=user_id, before=before, after=self._snapshot(row))
        return row

    # ── Booking proposal ─────────────────────────────────────────────────────

    async def propose_booking(self, row: CapturedInvoice) -> logic.BookingProposal:
        accounts = await self._chart_accounts(row.project_id)
        desc = " ".join(str(li.get("description", "")) for li in (row.line_items or []))
        return logic.propose_booking(
            accounts=accounts,
            supplier_name=row.supplier_name or "",
            description_text=desc,
            has_tax=logic.to_decimal(row.amount_tax) > 0,
            cost_code=row.booking_cost_code,
        )

    async def _chart_accounts(self, project_id: uuid.UUID) -> list[logic.ChartAccount]:
        accounts, _ = await self.finance.list_accounts(project_id=project_id, active_only=True)
        return [
            logic.ChartAccount(code=a.account_code, name=a.name, account_type=a.account_type, is_active=a.is_active)
            for a in accounts
        ]

    # ── State transitions ─────────────────────────────────────────────────────

    async def code(self, capture_id: uuid.UUID, booking: BookingInput, user_id: str | None) -> CapturedInvoice:
        row = await self.get(capture_id)
        self._require_transition(row, "coded")
        findings = await self._validate(row, require_booking=True, override_booking=booking)
        self._raise_on_errors(findings)
        before = self._snapshot(row)
        row.booking_expense_account = booking.expense_account
        row.booking_payable_account = booking.payable_account
        row.booking_tax_account = booking.tax_account
        row.booking_cost_code = booking.cost_code
        row.booking_project_id = booking.booking_project_id or row.project_id
        row.status = "coded"
        await self.session.flush()
        await self._log(
            row,
            action="coded",
            from_status=before["status"],
            to_status="coded",
            actor_id=user_id,
            metadata={"expense": booking.expense_account, "payable": booking.payable_account},
        )
        return row

    async def approve(
        self, capture_id: uuid.UUID, user_id: str | None, *, acknowledge_match: bool = False
    ) -> CapturedInvoice:
        row = await self.get(capture_id)
        self._require_transition(row, "approved")
        findings = await self._validate(
            row, require_booking=True, require_approval=False, enforce_match_ack=True, ack_all=acknowledge_match
        )
        self._raise_on_errors(findings)
        match_codes = sorted({f.code for f in findings if f.code.startswith("po_match:")})
        if match_codes:
            # Reassign, not mutate: a JSON column does not track in-place edits.
            row.metadata_ = {
                **(row.metadata_ or {}),
                "po_match_ack": {"codes": match_codes, "by": user_id, "at": _utcnow_iso()},
            }
        prior = row.status
        row.status = "approved"
        row.approver_id = uuid.UUID(user_id) if user_id else None
        row.approved_at = _utcnow_iso()
        await self.session.flush()
        await self._log(
            row,
            action="approved",
            from_status=prior,
            to_status="approved",
            actor_id=user_id,
            metadata={"acknowledged_match": match_codes} if match_codes else None,
        )
        return row

    async def reject(self, capture_id: uuid.UUID, reason: str, user_id: str | None) -> CapturedInvoice:
        row = await self.get(capture_id)
        self._require_transition(row, "rejected")
        prior = row.status
        row.status = "rejected"
        row.rejected_reason = reason
        await self.session.flush()
        await self._log(
            row, action="rejected", from_status=prior, to_status="rejected", actor_id=user_id, reason=reason
        )
        return row

    async def query(self, capture_id: uuid.UUID, note: str, user_id: str | None) -> CapturedInvoice:
        row = await self.get(capture_id)
        self._require_transition(row, "queried")
        prior = row.status
        row.status = "queried"
        row.queried_note = note
        await self.session.flush()
        await self._log(row, action="queried", from_status=prior, to_status="queried", actor_id=user_id, reason=note)
        return row

    async def reopen(self, capture_id: uuid.UUID, user_id: str | None) -> CapturedInvoice:
        row = await self.get(capture_id)
        self._require_transition(row, "captured")
        prior = row.status
        row.status = "captured"
        await self.session.flush()
        await self._log(row, action="reopened", from_status=prior, to_status="captured", actor_id=user_id)
        return row

    # ── Post to the general ledger + seal the archive ─────────────────────────

    async def post(self, capture_id: uuid.UUID, user_id: str | None) -> CapturedInvoice:
        row = await self.get(capture_id)
        if row.status == "posted":
            # Idempotent: already posted and sealed - return unchanged.
            return row
        self._require_transition(row, "posted")

        findings = await self._validate(row, require_booking=True, require_approval=True, enforce_match_ack=True)
        self._raise_on_errors(findings)

        net = logic.to_decimal(row.amount_net)
        tax = logic.to_decimal(row.amount_tax)
        gross = logic.to_decimal(row.amount_gross)
        booking_project = row.booking_project_id or row.project_id
        description = f"Supplier invoice {row.invoice_number or '(no number)'} - {row.supplier_name or 'supplier'}"
        transaction_ref = f"AP-CAP-{row.id}"

        lines = logic.build_journal_lines(
            net=net,
            tax=tax,
            expense_account=row.booking_expense_account or "",
            payable_account=row.booking_payable_account or "",
            tax_account=row.booking_tax_account,
            description=description,
        )

        # Reuse the one double-entry GL path (balances + idempotency enforced there).
        await self.finance.post_journal_entry(
            JournalEntryCreate(
                project_id=booking_project,
                transaction_ref=transaction_ref,
                lines=[JournalLineInput(**ln) for ln in lines],
                description=description,
                currency_code=row.currency_code or "",
                source_type=ENTITY_TYPE,
                source_id=str(row.id),
                idempotency_key=f"capture-post:{row.id}",
            )
        )

        cost_lines = await self._resolve_cost_lines(row, booking_project, net)

        # Create the payable Invoice for downstream payment tracking, linked back.
        linked = await self.finance.create_invoice(
            InvoiceCreate(
                project_id=booking_project,
                contact_id=row.supplier_contact_id,
                invoice_direction="payable",
                invoice_number=row.invoice_number or None,
                invoice_date=row.invoice_date or "",
                due_date=row.due_date,
                currency_code=row.currency_code or "",
                amount_subtotal=logic.money_str(net),
                tax_amount=logic.money_str(tax),
                amount_total=logic.money_str(gross),
                status="approved",
                purchase_order_id=row.purchase_order_id,
                line_items=self._invoice_line_items(row, cost_lines),
                metadata={
                    "captured_invoice_id": str(row.id),
                    "gl_transaction_ref": transaction_ref,
                    "source": "invoice_capture",
                },
            ),
            user_id=user_id,
            # The lines here are what the reader could make out of a scanned
            # document, while the net is the figure the document states in its
            # own header and the one a person approved. They do not have to add
            # up, and refusing the booking because a line went unread would
            # strand an approved invoice with its journal entry already posted.
            # Net, tax and gross are checked against each other on the way in
            # by ``logic.validate_amounts``.
            enforce_line_sum=False,
        )
        actuals = await self._post_actuals(row, linked.id, booking_project, cost_lines)

        sealed_at = _utcnow_iso()
        row.status = "posted"
        row.posted_at = sealed_at
        row.posted_transaction_ref = transaction_ref
        row.posted_invoice_id = linked.id
        row.archive_sealed_at = sealed_at
        row.retention_until = _retention_until_iso()
        row.archive_hash = self._archive_hash(row, transaction_ref)
        await self.session.flush()

        await self._log(
            row,
            action="posted",
            from_status="approved",
            to_status="posted",
            actor_id=user_id,
            metadata={
                "transaction_ref": transaction_ref,
                "linked_invoice_id": str(linked.id),
                "archive_hash": row.archive_hash,
                "retention_until": row.retention_until,
                "cost_actuals": actuals,
            },
        )
        return row

    # ── Cost control: actuals on the cost line ────────────────────────────────

    async def _resolve_cost_lines(
        self, row: CapturedInvoice, project_id: uuid.UUID, net: Decimal
    ) -> list[tuple[int | None, uuid.UUID | None, Decimal]]:
        """Pair each posted amount with the cost line its code names, as (line index, cost line, amount).

        Draft lines are used one by one only when they add up to the net; otherwise the whole net goes to
        the booking cost code (index ``None``), so cost control and the ledger always carry the same figure.
        """
        lines = [dict(li) for li in (row.line_items or [])]
        amounts = [logic.to_decimal(li.get("amount")) for li in lines]
        per_line = bool(lines) and abs(sum(amounts, Decimal("0")) - net) <= logic.AMOUNT_TOLERANCE
        if not per_line:
            lines, amounts = [{"cost_code": row.booking_cost_code}], [net]
        codes = {str(li.get("cost_code") or row.booking_cost_code or "").strip() for li in lines} - {""}
        by_code: dict[str, uuid.UUID] = {}
        if codes:
            try:
                from app.modules.costmodel.models import CostLine
            except ImportError:
                logger.debug("costmodel not installed; invoice actuals stay on the ledger only")
            else:
                found = await self.session.execute(
                    select(CostLine.code, CostLine.id).where(
                        CostLine.project_id == project_id, CostLine.code.in_(sorted(codes))
                    )
                )
                by_code = {code: cid for code, cid in found.all()}
        out: list[tuple[int | None, uuid.UUID | None, Decimal]] = []
        for idx, (li, amount) in enumerate(zip(lines, amounts, strict=True)):
            code = str(li.get("cost_code") or row.booking_cost_code or "").strip()
            out.append((idx if per_line else None, by_code.get(code), amount))
        return out

    async def _post_actuals(
        self,
        row: CapturedInvoice,
        invoice_id: uuid.UUID,
        project_id: uuid.UUID,
        cost_lines: list[tuple[int | None, uuid.UUID | None, Decimal]],
    ) -> dict[str, Any]:
        """Post the approved invoice's net as actual cost on the cost spine, once per line.

        Never fails the booking: the ledger entry is already written, so a spine problem (no project base
        currency, costmodel not installed) is recorded in the audit trail and the row metadata instead.
        """
        try:
            from app.modules.costmodel.service import CostSpineService
            from app.modules.finance.service import _convert_to_base, _project_fx_map
            from app.modules.projects.repository import ProjectRepository
        except ImportError:
            return {"posted": 0, "skipped": "costmodel_unavailable"}

        project = await ProjectRepository(self.session).get_by_id(project_id)
        base = (getattr(project, "currency", "") or "").strip().upper() if project else ""
        fx_map = _project_fx_map(project)
        currency = row.currency_code or ""
        spine = CostSpineService(self.session)
        posted = uncoded = 0
        errors: list[str] = []
        for idx, (_line, cost_line_id, amount) in enumerate(cost_lines):
            if amount == 0:
                continue
            ref = f"{row.id}:{idx}"
            base_amount, missing = _convert_to_base({currency: amount}, base_currency=base, fx_rates_map=fx_map)
            if missing and base:
                # A foreign amount summed as base units would corrupt the line's actuals.
                errors.append(f"no FX rate for {','.join(missing)}; actual not posted")
                continue
            try:
                async with self.session.begin_nested():
                    await spine.post_actual_to_budget_line(
                        project_id=project_id,
                        cost_line_id=cost_line_id,
                        cost_category=None,
                        amount_base=base_amount,
                        currency=currency,
                        source_kind="inbox_invoice",
                        source_ref=ref,
                        idempotency_key=f"capture-actual:{ref}",
                    )
                posted += 1
                uncoded += cost_line_id is None
            except HTTPException as exc:
                errors.append(str(exc.detail)[:200])
        result: dict[str, Any] = {"posted": posted, "uncoded": uncoded, "invoice_id": str(invoice_id)}
        if errors:
            result["errors"] = errors
            logger.warning("Invoice %s: cost actuals not posted: %s", row.id, errors)
        row.metadata_ = {**(row.metadata_ or {}), "cost_actuals": result}
        return result

    def _invoice_line_items(
        self,
        row: CapturedInvoice,
        cost_lines: list[tuple[int | None, uuid.UUID | None, Decimal]] | None = None,
    ) -> list[InvoiceLineItemCreate]:
        line_ids = {idx: cid for idx, cid, _ in (cost_lines or []) if idx is not None}
        items: list[InvoiceLineItemCreate] = []
        for idx, li in enumerate(row.line_items or []):
            items.append(
                InvoiceLineItemCreate(
                    description=str(li.get("description") or "Invoice line")[:500],
                    quantity=logic.money_str(li.get("quantity", "1")),
                    unit_rate=logic.money_str(li.get("unit_rate", "0")),
                    amount=logic.money_str(li.get("amount", "0")),
                    cost_category=(str(li["cost_code"])[:100] if li.get("cost_code") else None),
                    cost_line_id=line_ids.get(idx),
                )
            )
        if not items:
            # A single summary line so the payable is never empty.
            items.append(
                InvoiceLineItemCreate(
                    description=(f"{row.supplier_name or 'Supplier'} invoice {row.invoice_number}").strip()[:500],
                    quantity="1",
                    unit_rate=logic.money_str(row.amount_net),
                    amount=logic.money_str(row.amount_net),
                )
            )
        return items

    # ── Archive integrity ─────────────────────────────────────────────────────

    def _archive_hash(self, row: CapturedInvoice, transaction_ref: str | None) -> str:
        return logic.compute_archive_hash(
            content_hash=row.content_sha256,
            supplier_name=row.supplier_name or "",
            invoice_number=row.invoice_number or "",
            invoice_date=row.invoice_date or "",
            currency_code=row.currency_code or "",
            net=logic.to_decimal(row.amount_net),
            tax=logic.to_decimal(row.amount_tax),
            gross=logic.to_decimal(row.amount_gross),
            expense_account=row.booking_expense_account,
            tax_account=row.booking_tax_account,
            payable_account=row.booking_payable_account,
            cost_code=row.booking_cost_code,
            transaction_ref=transaction_ref,
        )

    async def verify_archive(self, capture_id: uuid.UUID) -> dict[str, Any]:
        row = await self.get(capture_id)
        sealed = bool(row.archive_hash)
        recomputed_archive = self._archive_hash(row, row.posted_transaction_ref)
        booking_intact = sealed and recomputed_archive == row.archive_hash

        document_present = False
        document_intact: bool | None = None
        recomputed_doc: str | None = None
        if row.storage_key:
            try:
                data = await get_storage_backend().get(row.storage_key)
                document_present = True
                recomputed_doc = logic.content_sha256(data)
                document_intact = recomputed_doc == row.content_sha256
            except Exception as exc:  # noqa: BLE001
                logger.warning("Archive document read failed for %s: %s", capture_id, exc)
                document_present = False
                document_intact = False

        overall = booking_intact and (document_intact is not False)
        if not sealed:
            message = "This record is not posted yet, so it has not been sealed."
        elif overall:
            message = "Archive verified: the document and the booking are unchanged since posting."
        else:
            message = "Archive integrity check FAILED - the document or booking differs from the sealed record."

        return {
            "id": row.id,
            "sealed": sealed,
            "document_present": document_present,
            "document_intact": document_intact,
            "booking_intact": booking_intact,
            "overall_intact": bool(overall) if sealed else False,
            "content_sha256": row.content_sha256,
            "recomputed_document_sha256": recomputed_doc,
            "archive_hash": row.archive_hash,
            "recomputed_archive_hash": recomputed_archive if sealed else None,
            "retention_until": row.retention_until,
            "message": message,
        }

    async def read_document(self, capture_id: uuid.UUID) -> tuple[bytes, str, str]:
        row = await self.get(capture_id)
        if not row.storage_key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This capture has no stored document.")
        try:
            data = await get_storage_backend().get(row.storage_key)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored document is unavailable.") from exc
        return data, row.mime_type or "application/octet-stream", row.original_filename or "invoice"

    async def audit_trail(self, capture_id: uuid.UUID) -> list[Any]:
        return await get_activity_for_entity(self.session, entity_type=ENTITY_TYPE, entity_id=str(capture_id))

    # ── Validation ─────────────────────────────────────────────────────────────

    async def build_validation(self, row: CapturedInvoice) -> list[logic.Finding]:
        """Advisory validation for display (no gating)."""
        return await self._validate(row, require_booking=False, require_approval=False)

    async def _validate(
        self,
        row: CapturedInvoice,
        *,
        require_booking: bool,
        require_approval: bool,
        override_booking: BookingInput | None = None,
        enforce_match_ack: bool = False,
        ack_all: bool = False,
    ) -> list[logic.Finding]:
        expense = override_booking.expense_account if override_booking else row.booking_expense_account
        payable = override_booking.payable_account if override_booking else row.booking_payable_account
        tax_acct = override_booking.tax_account if override_booking else row.booking_tax_account
        duplicate = await self._find_duplicate(row)
        po_summary, match_results = await self._po_summary_and_match(row)
        findings = logic.validate_capture(
            status=row.status,
            net=logic.to_decimal(row.amount_net),
            tax=logic.to_decimal(row.amount_tax),
            gross=logic.to_decimal(row.amount_gross),
            expense_account=expense,
            payable_account=payable,
            tax_account=tax_acct,
            invoice_number=row.invoice_number or "",
            supplier_name=row.supplier_name or "",
            has_approver=row.approver_id is not None,
            duplicate=duplicate,
            require_booking=require_booking,
            require_approval=require_approval,
        )
        findings.extend(
            logic.validate_po_link(
                po=po_summary,
                po_reference=row.po_reference or "",
                supplier_contact_id=row.supplier_contact_id,
                currency_code=row.currency_code or "",
            )
        )
        findings.extend(logic.negative_line_findings(row.line_items or []))
        match = logic.match_report_findings(match_results)
        findings.extend(match)
        if enforce_match_ack:
            stored = (row.metadata_ or {}).get("po_match_ack") or {}
            acked = {f.code for f in match} if ack_all else set(stored.get("codes") or [])
            findings.extend(logic.match_unacknowledged(match, acked))
        return findings

    # ── Order link ──────────────────────────────────────────────────────────────

    @staticmethod
    def _procurement(session: AsyncSession) -> Any | None:
        try:
            from app.modules.procurement.service import ProcurementService
        except ImportError:
            return None
        return ProcurementService(session)

    async def _po_summary_and_match(self, row: CapturedInvoice) -> tuple[dict | None, list[dict]]:
        """The linked order as a summary dict plus the failed/passed ``invoice_po_match`` rule results.

        The matching itself is procurement's: invoiced-so-far, confirmed goods receipts and the order's own
        tolerances live there, so the inbox neither re-implements them nor drifts from the invoice form.
        """
        if row.purchase_order_id is None:
            return None, []
        procurement = self._procurement(self.session)
        if procurement is None:
            return None, []
        try:
            po = await procurement.get_po(row.purchase_order_id)
        except HTTPException:
            return {}, []
        summary = {
            "number": po.po_number,
            "status": po.status,
            "vendor_contact_id": po.vendor_contact_id,
            "currency_code": po.currency_code,
        }
        report = await procurement.check_invoice_against_po(
            po.id,
            invoice_net=format(logic.to_decimal(row.amount_net), "f"),
            lines=[dict(li) for li in (row.line_items or [])],
            exclude_invoice_id=row.posted_invoice_id,
            invoice_ref=row.invoice_number or None,
        )
        return summary, list(report.get("results") or [])

    async def _resolve_po_reference(self, row: CapturedInvoice) -> None:
        """Link the order whose number the invoice names, when exactly one open order on the project has it."""
        ref = (row.po_reference or "").strip()
        if not ref or row.purchase_order_id is not None:
            return
        try:
            from app.modules.procurement.models import PurchaseOrder
        except ImportError:
            return
        found = (
            await self.session.execute(
                select(PurchaseOrder.id, PurchaseOrder.status, PurchaseOrder.vendor_contact_id).where(
                    PurchaseOrder.project_id == row.project_id,
                    func.lower(PurchaseOrder.po_number) == ref.lower(),
                )
            )
        ).all()
        if len(found) == 1 and found[0][1] in logic.BILLABLE_PO_STATUSES:
            row.purchase_order_id = found[0][0]
            if not row.supplier_contact_id and found[0][2]:
                row.supplier_contact_id = found[0][2]
            await self.session.flush()

    async def link_purchase_order(
        self, capture_id: uuid.UUID, purchase_order_id: uuid.UUID | None, user_id: str | None
    ) -> CapturedInvoice:
        """Link (or unlink) the order a captured invoice bills; any earlier acknowledgement is dropped."""
        row = await self.get(capture_id)
        self._guard_editable(row)
        before = self._snapshot(row)
        if purchase_order_id is not None:
            procurement = self._procurement(self.session)
            if procurement is None:
                raise _po_err(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "procurement_missing", "Procurement is not installed."
                )
            po = await procurement.get_po(purchase_order_id)
            if po.project_id != row.project_id:
                # Same answer as a missing order, so another project's order ids cannot be probed.
                raise _po_err(status.HTTP_404_NOT_FOUND, "po_not_found", "Purchase order not found")
            if po.status not in logic.BILLABLE_PO_STATUSES:
                raise _po_err(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "po_not_billable",
                    f"Order {po.po_number} is '{po.status}'; only an issued order can be invoiced.",
                    po_number=po.po_number,
                )
            row.purchase_order_id = po.id
            row.po_reference = po.po_number
            if not row.supplier_contact_id and po.vendor_contact_id:
                row.supplier_contact_id = po.vendor_contact_id
        else:
            row.purchase_order_id = None
        row.metadata_ = {k: v for k, v in (row.metadata_ or {}).items() if k != "po_match_ack"}
        await self.session.flush()
        await self._log(
            row,
            action="po_linked" if purchase_order_id else "po_unlinked",
            actor_id=user_id,
            before=before,
            after=self._snapshot(row),
        )
        return row

    async def _find_duplicate(self, row: CapturedInvoice) -> dict | None:
        if not (row.invoice_number or "").strip():
            return None
        stmt = (
            select(CapturedInvoice.id, CapturedInvoice.supplier_name, CapturedInvoice.invoice_number)
            .where(CapturedInvoice.project_id == row.project_id)
            .where(CapturedInvoice.id != row.id)
            .where(CapturedInvoice.invoice_number == row.invoice_number)
            .where(CapturedInvoice.status != "rejected")
        )
        candidates = [
            {"id": str(r.id), "supplier_name": r.supplier_name, "invoice_number": r.invoice_number}
            for r in (await self.session.execute(stmt)).all()
        ]
        return logic.find_duplicate(
            supplier_name=row.supplier_name or "", invoice_number=row.invoice_number or "", candidates=candidates
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _apply_fields(self, row: CapturedInvoice, fields: dict, *, only_if_blank: bool = False) -> None:
        str_fields = ("supplier_name", "supplier_tax_id", "invoice_number", "invoice_date", "currency_code")
        for key in str_fields:
            if key not in fields:
                continue
            if only_if_blank and (getattr(row, key) or "").strip():
                continue
            setattr(row, key, str(fields[key])[:255])
        for money_field in ("amount_net", "amount_tax", "amount_gross"):
            if money_field not in fields:
                continue
            if only_if_blank and logic.to_decimal(getattr(row, money_field)) > 0:
                continue
            setattr(row, money_field, logic.to_decimal(fields[money_field]))

    def _guard_editable(self, row: CapturedInvoice) -> None:
        if row.status in {"approved", "posted"}:
            raise _po_err(
                status.HTTP_409_CONFLICT,
                "invoice_read_only",
                "An approved or posted invoice is read-only. Move it back to draft first.",
            )

    def _require_transition(self, row: CapturedInvoice, target: str) -> None:
        allowed = _CAPTURE_TRANSITIONS.get(row.status, set())
        if target not in allowed:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot move a '{row.status}' invoice to '{target}'.",
            )

    def _raise_on_errors(self, findings: list[logic.Finding]) -> None:
        errors = [f for f in findings if f.is_error]
        if errors:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"message": "Validation failed", "findings": logic.findings_to_dicts(findings)},
            )

    def _snapshot(self, row: CapturedInvoice) -> dict:
        return {
            "status": row.status,
            "supplier_name": row.supplier_name,
            "invoice_number": row.invoice_number,
            "amount_net": logic.money_str(row.amount_net),
            "amount_tax": logic.money_str(row.amount_tax),
            "amount_gross": logic.money_str(row.amount_gross),
            "expense_account": row.booking_expense_account,
            "payable_account": row.booking_payable_account,
        }

    async def _log(
        self,
        row: CapturedInvoice,
        *,
        action: str,
        from_status: str | None = None,
        to_status: str | None = None,
        reason: str | None = None,
        actor_id: str | None = None,
        metadata: dict | None = None,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        """Append-only audit write. Best-effort: never fails the business op."""
        try:
            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type=ENTITY_TYPE,
                entity_id=str(row.id),
                action=action,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                metadata=metadata,
                module=MODULE,
                parent_entity_type="project",
                parent_entity_id=str(row.project_id),
                before_state=before,
                after_state=after,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audit log for captured invoice %s failed: %s", row.id, exc)
