# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release: terms, the invoice ledger, releasing an invoice, the retention register, the rules.

Every figure is computed on the server from :func:`billing.load_billing`; the
screens only show it. A person confirms a release (it is then frozen) and
posts a retention release; nothing here moves money on its own.

Releasing goes in order: an invoice is released only when every earlier
invoice of its contract is released, because its ``previous_releases`` reads
them, and it is reopened only while no later invoice is released. For the same
reason nothing is slipped in under a released cumulative invoice: neither an
invoice dated before it nor a retention posting dated on or before it is
released, posted or voided until that invoice is reopened. An ERROR
finding of the ``payment_release`` rules on the invoice blocks its release.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payment_release.billing import (
    SERIES_KINDS,
    Billing,
    ContractRecord,
    InvoiceRecord,
    contract_invoiced,
    counted_invoices,
    discount_taken,
    invoice_paid,
    load_billing,
    released_invoices_counting,
    released_retention_held,
)
from app.modules.payment_release.models import InvoiceRelease, PaymentTerms, RetentionPosting
from app.modules.payment_release.release_certificates import ENFORCEMENT_KEY, normalise_enforcement
from app.modules.payment_release.repository import PaymentReleaseRepository
from app.modules.payment_release.statutory_rules import STATUTORY_RULE_NUMBERS
from app.modules.payment_release.validators import PAYLOAD_KEY, RULE_NUMBERS, RULE_SET

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
TENTH = Decimal("0.1")


def _problem(code: int, problem: str, message: str, **params: Any) -> HTTPException:
    return HTTPException(status_code=code, detail={"problem": problem, "message": message, **params})


def _later_released(invoices: list[InvoiceRecord]) -> HTTPException:
    return _problem(
        409,
        "later_invoice_released",
        "A later invoice of this contract is released and builds on this one; reopen that first",
        numbers=[inv.number for inv in invoices],
    )


def _pct(part: Decimal, whole: Decimal) -> str | None:
    if whole == ZERO:
        return None
    return str((part / whole * 100).quantize(TENTH))


def _money(value: Decimal) -> str:
    return str(value)


class PaymentReleaseService:
    """Terms, ledger, release, retention and findings of one project's supplier contracts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PaymentReleaseRepository(session)

    # ── Loading what a route names ───────────────────────────────────────

    async def contract(self, contract_id: uuid.UUID) -> Any:
        from app.modules.contracts.models import Contract

        contract = await self.session.get(Contract, contract_id)
        if contract is None:
            raise _problem(404, "contract_not_found", "Contract not found")
        return contract

    async def supplier_contract(self, contract_id: uuid.UUID) -> Any:
        contract = await self.contract(contract_id)
        if (contract.counterparty_type or "") != "subcontractor":
            raise _problem(
                409,
                "not_a_supplier_contract",
                "Payment release works on contracts with a subcontractor or supplier, not on client contracts",
            )
        return contract

    async def invoice(self, invoice_id: uuid.UUID) -> Any:
        from app.modules.finance.models import Invoice

        invoice = await self.session.get(Invoice, invoice_id)
        if invoice is None:
            raise _problem(404, "invoice_not_found", "Invoice not found")
        if (invoice.invoice_direction or "") != "payable":
            raise _problem(409, "not_a_supplier_invoice", "Only supplier invoices are released for payment")
        return invoice

    async def posting(self, posting_id: uuid.UUID) -> RetentionPosting:
        row = await self.repo.posting(posting_id)
        if row is None:
            raise _problem(404, "posting_not_found", "Retention posting not found")
        return row

    # ── Terms ────────────────────────────────────────────────────────────

    async def terms(self, contract: Any) -> dict[str, Any]:
        from app.modules.costmodel.repository import CostSpineRepository

        row = await self.repo.terms_for(contract.id)
        currency, _fx = await CostSpineRepository(self.session)._fx_context(contract.project_id)
        return {
            "contract_id": str(contract.id),
            "terms_set": row is not None,
            "currency": currency,
            "invoice_mode": row.invoice_mode if row else "incremental",
            "retention_percent": Decimal(str(contract.retention_percent or 0)),
            "retention_release_event": contract.retention_release_event or "substantial_completion",
            "retention_basis": row.retention_basis if row else "net",
            "warranty_enabled": bool(row.warranty_enabled) if row else False,
            "warranty_percent": Decimal(str(row.warranty_percent)) if row else ZERO,
            "warranty_release_event": row.warranty_release_event if row else "defects_period_end",
            "warranty_period_months": row.warranty_period_months if row else None,
            "discount_enabled": bool(row.discount_enabled) if row else False,
            "discount_percent": Decimal(str(row.discount_percent)) if row else ZERO,
            "discount_days": int(row.discount_days or 0) if row else 0,
            "discount_applies_to": row.discount_applies_to if row else "both",
            "rounding_enabled": bool(row.rounding_enabled) if row else False,
            "rounding_step": Decimal(str(row.rounding_step)) if row else ZERO,
            "interim_due_days": row.interim_due_days if row else None,
            "final_due_days": row.final_due_days if row else None,
            "release_certificates_enforcement": normalise_enforcement((row.metadata_ or {}).get(ENFORCEMENT_KEY))
            if row
            else "pack",
        }

    async def put_terms(self, contract: Any, body: Any, actor: str | None) -> dict[str, Any]:
        """Store the terms. The interim retention rate and its event are written onto the contract."""
        row = await self.repo.terms_for(contract.id)
        if row is None:
            row = PaymentTerms(contract_id=contract.id, project_id=contract.project_id)
            self.session.add(row)
        values = body.model_dump()
        enforcement = values.pop("release_certificates_enforcement", None)
        if enforcement is not None:
            row.metadata_ = {**(row.metadata_ or {}), ENFORCEMENT_KEY: enforcement}
        contract.retention_percent = values.pop("retention_percent")
        contract.retention_release_event = values.pop("retention_release_event")
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_by = actor
        await self.session.flush()
        return await self.terms(contract)

    # ── Ledger ───────────────────────────────────────────────────────────

    def _ledger_invoice(self, contract: ContractRecord, inv: InvoiceRecord, row: Any, to_date: Decimal) -> dict:
        release = row.effective
        paid = invoice_paid(inv, release)
        counted = inv.id in counted_invoices(contract)
        share = to_date if inv.kind in SERIES_KINDS else release.net_after
        return {
            "invoice_id": inv.id,
            "number": inv.number,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "finance_status": inv.status,
            "kind": inv.kind,
            "kind_set": inv.kind_set,
            "contract_source": inv.contract_source,
            "release_status": "released" if inv.frozen is not None else "open",
            "released_at": inv.released_at,
            "net_deduction_note": inv.net_deduction_note,
            "gross_deduction_note": inv.gross_deduction_note,
            "figures": release.as_dict(),
            "computed": row.computed.as_dict(),
            "differs": row.differs,
            "counted": counted,
            "progress_pct": _pct(share, contract.current_value),
            "paid": _money(paid),
            "paid_cash": _money(inv.paid_cash),
            "discount_taken": _money(discount_taken(inv, release)),
            "open_amount": _money(release.release - paid),
        }

    def _contract_block(self, contract: ContractRecord) -> dict[str, Any]:
        rows = contract.ledger.rows if contract.ledger is not None else []
        invoices: list[dict[str, Any]] = []
        running = ZERO
        for inv, row in zip(contract.invoices, rows, strict=True):
            if inv.kind in SERIES_KINDS:
                cumulative = inv.kind == "final" or (
                    contract.terms.invoice_mode == "cumulative" and inv.claim_retention is None
                )
                running = row.effective.net_after if cumulative else running + row.effective.net_after
            invoices.append(self._ledger_invoice(contract, inv, row, running))
        posted = contract.ledger.retention_posted if contract.ledger else ZERO
        invoiced = contract_invoiced(contract)
        # Retention paid back is money due to the supplier as well, so "due" less "paid" stays the open amount.
        released = sum((row.effective.release for row in rows), ZERO) + posted
        payable = sum((row.effective.payable for row in rows), ZERO)
        paid = sum((Decimal(i["paid"]) for i in invoices), ZERO)
        open_amount = sum((Decimal(i["open_amount"]) for i in invoices), ZERO)
        changes = contract.current_value - contract.original_value
        return {
            "contract_id": contract.id,
            "code": contract.code,
            "title": contract.title,
            "status": contract.status,
            "invoice_mode": contract.terms.invoice_mode,
            "terms_set": contract.terms_set,
            "original_value": _money(contract.original_value),
            "changes": _money(changes),
            "current_value": _money(contract.current_value),
            "changes_pct": _pct(changes, contract.original_value),
            "measured": _money(contract.measured_value),
            "measured_pct": _pct(contract.measured_value, contract.current_value),
            "has_measurement": contract.has_measurement,
            "invoices": invoices,
            "totals": {
                "contract_value": _money(contract.current_value),
                "invoiced": _money(invoiced),
                "invoiced_pct": _pct(invoiced, contract.current_value),
                "released": _money(released),
                "payable": _money(payable),
                "paid": _money(paid + posted),
                "open_amount": _money(open_amount),
                "retention_held": _money(contract.ledger.retention_held if contract.ledger else ZERO),
                "retention_posted": _money(posted),
            },
        }

    async def ledger(self, project_id: uuid.UUID, billing: Billing | None = None) -> dict[str, Any]:
        """The invoice ledger of the whole project: one block per supplier contract, then other invoices."""
        billing = billing or await load_billing(self.session, project_id)
        blocks = [self._contract_block(c) for c in billing.contracts]
        others = [
            {
                "invoice_id": inv.id,
                "number": inv.number,
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "finance_status": inv.status,
                "net": _money(inv.net),
                "gross": _money(inv.gross_total),
                "paid": _money(inv.paid_cash),
                "purchase_order_id": inv.purchase_order_id,
            }
            for inv in billing.loose_invoices
        ]

        def total(key: str) -> Decimal:
            return sum((Decimal(b["totals"][key]) for b in blocks), ZERO)

        value = total("contract_value")
        loose_net = sum((inv.net for inv in billing.loose_invoices), ZERO)
        loose_gross = sum((inv.gross_total for inv in billing.loose_invoices), ZERO)
        loose_paid = sum((inv.paid_cash for inv in billing.loose_invoices), ZERO)
        invoiced = total("invoiced") + loose_net
        return {
            "project_id": str(project_id),
            "currency": billing.currency,
            "contracts": blocks,
            "other_invoices": others,
            "totals": {
                "contract_value": _money(value),
                "invoiced": _money(invoiced),
                "invoiced_pct": _pct(invoiced, value),
                "released": _money(total("released")),
                "payable": _money(total("payable") + loose_gross),
                "paid": _money(total("paid") + loose_paid),
                "open_amount": _money(total("open_amount") + loose_gross - loose_paid),
                "retention_held": _money(total("retention_held")),
                "retention_posted": _money(total("retention_posted")),
            },
        }

    # ── One invoice ──────────────────────────────────────────────────────

    async def _release_row(self, invoice: Any) -> InvoiceRelease:
        row = await self.repo.release_for(invoice.id)
        if row is None:
            row = InvoiceRelease(invoice_id=invoice.id, project_id=invoice.project_id)
            self.session.add(row)
            await self.session.flush()
        return row

    async def update_invoice(self, invoice: Any, body: Any, actor: str | None) -> InvoiceRelease:
        """Set the kind, contract and deductions of an open invoice."""
        row = await self._release_row(invoice)
        if row.status == "released":
            raise _problem(409, "invoice_released", "The release is confirmed; reopen it before changing the invoice")
        fields = body.model_dump(exclude_unset=True)
        if "contract_id" in fields:
            raw = fields.pop("contract_id")
            if raw in (None, ""):
                row.contract_id = None
            else:
                try:
                    target = uuid.UUID(str(raw))
                except ValueError as exc:
                    raise _problem(422, "contract_not_found", "Contract not found") from exc
                contract = await self.supplier_contract(target)
                if contract.project_id != invoice.project_id:
                    raise _problem(409, "contract_in_other_project", "The contract belongs to another project")
                row.contract_id = contract.id
        for key, value in fields.items():
            if value is None and key in ("net_deduction", "gross_deduction", "kind"):
                continue
            setattr(row, key, value)
        await self.session.flush()
        return row

    def _locate(self, billing: Billing, invoice_id: str) -> tuple[ContractRecord, int]:
        for contract in billing.contracts:
            for index, inv in enumerate(contract.invoices):
                if inv.id == invoice_id:
                    return contract, index
        raise _problem(
            409,
            "invoice_without_contract",
            "The invoice is on no supplier contract; name its contract before releasing it",
        )

    async def release_invoice(self, invoice: Any, actor: str | None, *, locale: str = "en") -> InvoiceRelease:
        """Freeze the invoice's release as computed now. A person's confirmation; nothing is paid by it."""
        row = await self._release_row(invoice)
        if row.status == "released":
            raise _problem(409, "invoice_released", "The release is already confirmed")
        billing = await load_billing(self.session, invoice.project_id)
        contract, index = self._locate(billing, str(invoice.id))
        earlier = [inv for inv in contract.invoices[:index] if inv.frozen is None]
        if earlier:
            raise _problem(
                409,
                "earlier_invoice_open",
                "Release the earlier invoices of this contract first; this release builds on them",
                numbers=[inv.number for inv in earlier],
            )
        if contract.invoices[index].kind in SERIES_KINDS:
            later = [
                inv for inv in contract.invoices[index + 1 :] if inv.frozen is not None and inv.frozen.previous_counted
            ]
            if later:
                raise _later_released(later)
        blocking = [
            f
            for f in await self.findings(invoice.project_id, locale=locale, billing=billing)
            if f["severity"] == "error" and f.get("element_ref") == str(invoice.id)
        ]
        if blocking:
            raise _problem(
                409,
                "release_blocked_by_findings",
                "Errors on this invoice must be resolved before it is released",
                findings=blocking,
            )
        assert contract.ledger is not None
        computed = contract.ledger.rows[index].computed
        terms = contract.terms
        row.contract_id = row.contract_id or uuid.UUID(contract.id)
        row.kind = computed.kind
        row.status = "released"
        row.released_at = datetime.now(UTC)
        row.released_by = actor
        row.release_amount = computed.release
        row.payable_amount = computed.payable
        row.retention_amount = computed.retention
        row.rounding_amount = computed.rounding
        row.discount_amount = computed.discount
        row.snapshot = {
            "release": computed.as_dict(),
            "terms": {
                "invoice_mode": terms.invoice_mode,
                "retention_percent": str(terms.retention_percent),
                "retention_basis": terms.retention_basis,
                "warranty_enabled": terms.warranty_enabled,
                "warranty_percent": str(terms.warranty_percent),
                "discount_enabled": terms.discount_enabled,
                "discount_percent": str(terms.discount_percent),
                "discount_days": terms.discount_days,
                "discount_applies_to": terms.discount_applies_to,
                "rounding_enabled": terms.rounding_enabled,
                "rounding_step": str(terms.rounding_step),
            },
            "currency": billing.currency,
        }
        await self.session.flush()
        logger.info("payment_release: invoice %s released at %s by %s", invoice.id, computed.release, actor)
        return row

    async def reopen_invoice(self, invoice: Any, actor: str | None) -> InvoiceRelease:
        """Unfreeze a confirmed release, while no later invoice of the contract builds on it."""
        row = await self._release_row(invoice)
        if row.status != "released":
            raise _problem(409, "invoice_open", "The release is not confirmed")
        billing = await load_billing(self.session, invoice.project_id)
        try:
            contract, index = self._locate(billing, str(invoice.id))
        except HTTPException:
            contract, index = None, -1
        if contract is not None:
            later = [inv for inv in contract.invoices[index + 1 :] if inv.frozen is not None]
            if later:
                raise _later_released(later)
        row.status = "open"
        row.snapshot = {**(row.snapshot or {}), "reopened_at": datetime.now(UTC).isoformat(), "reopened_by": actor}
        row.snapshot.pop("release", None)
        row.release_amount = row.payable_amount = row.retention_amount = None
        row.rounding_amount = row.discount_amount = None
        row.released_at = None
        row.released_by = None
        await self.session.flush()
        return row

    # ── Retention register ───────────────────────────────────────────────

    async def retention_register(self, project_id: uuid.UUID, billing: Billing | None = None) -> dict[str, Any]:
        """Retention withheld, paid back and still held per supplier contract.

        A contract is listed once it has an invoice, a posting (void ones too) or any retention.
        Held is what the released invoices withheld less what postings paid back, the same
        figure a new posting is capped at; an open invoice has withheld nothing yet.
        """
        billing = billing or await load_billing(self.session, project_id)
        rows = (
            (
                await self.session.execute(
                    select(RetentionPosting)
                    .where(RetentionPosting.project_id == project_id)
                    .order_by(RetentionPosting.posted_on, RetentionPosting.created_at)
                )
            )
            .scalars()
            .all()
        )
        by_contract: dict[str, list[RetentionPosting]] = {}
        for row in rows:
            by_contract.setdefault(str(row.contract_id), []).append(row)
        contracts: list[dict[str, Any]] = []
        held_total = ZERO
        posted_total = ZERO
        for c in billing.contracts:
            ledger = c.ledger
            held = released_retention_held(c)
            posted = ledger.retention_posted if ledger else ZERO
            postings = by_contract.get(c.id, [])
            if not c.invoices and not postings and held == ZERO and posted == ZERO:
                continue
            held_total += held
            posted_total += posted
            contracts.append(
                {
                    "contract_id": c.id,
                    "code": c.code,
                    "title": c.title,
                    "status": c.status,
                    "retention_percent": str(c.terms.retention_percent),
                    "retention_release_event": c.retention_release_event,
                    "warranty_enabled": c.terms.warranty_enabled,
                    "warranty_percent": str(c.terms.warranty_percent),
                    "warranty_release_event": c.warranty_release_event,
                    "warranty_period_months": c.warranty_period_months,
                    "withheld": _money(held + posted),
                    "posted": _money(posted),
                    "held": _money(held),
                    "postings": [self.posting_out(p) for p in postings],
                }
            )
        return {
            "project_id": str(project_id),
            "currency": billing.currency,
            "contracts": contracts,
            "held": _money(held_total),
            "posted": _money(posted_total),
        }

    @staticmethod
    def posting_out(row: RetentionPosting) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "contract_id": str(row.contract_id),
            "retention_kind": row.retention_kind,
            "event": row.event,
            "event_on": row.event_on.isoformat() if row.event_on else None,
            "amount": _money(Decimal(str(row.amount))),
            "posted_on": row.posted_on.isoformat(),
            "status": row.status,
            "document_ref": row.document_ref or "",
            "note": row.note or "",
        }

    async def post_retention(self, contract: Any, body: Any, actor: str | None) -> RetentionPosting:
        """Pay back held retention: never more than the released invoices hold.

        Not dated on or before a released cumulative invoice either: that invoice
        already paid what it found, and would pay the posted amount again.
        """
        billing = await load_billing(self.session, contract.project_id)
        record = billing.contract(str(contract.id))
        if record is not None:
            counting = released_invoices_counting(record, body.posted_on)
            if counting:
                raise _later_released(counting)
        held = released_retention_held(record) if record is not None else ZERO
        if body.amount > held:
            raise _problem(
                409,
                "exceeds_held",
                "The contract holds less retention than this release",
                held=str(held),
            )
        row = RetentionPosting(
            project_id=contract.project_id,
            contract_id=contract.id,
            retention_kind=body.retention_kind,
            event=body.event,
            event_on=body.event_on,
            amount=body.amount,
            posted_on=body.posted_on,
            status="posted",
            document_ref=(body.document_ref or "").strip() or None,
            note=(body.note or "").strip() or None,
            created_by=actor,
        )
        await self.repo.add(row)
        return row

    async def void_posting(self, row: RetentionPosting, actor: str | None) -> RetentionPosting:
        if row.status == "void":
            raise _problem(409, "posting_void", "The retention posting is already void")
        billing = await load_billing(self.session, row.project_id)
        record = billing.contract(str(row.contract_id))
        counting = released_invoices_counting(record, row.posted_on) if record is not None else []
        if counting:
            raise _later_released(counting)
        row.status = "void"
        row.voided_at = datetime.now(UTC)
        row.voided_by = actor
        await self.session.flush()
        return row

    # ── Rules ────────────────────────────────────────────────────────────

    @staticmethod
    def rules_payload(billing: Billing) -> dict[str, Any]:
        """Everything rules V11 to V18 read, as plain data in the project currency."""
        contracts: list[dict[str, Any]] = []
        invoices: list[dict[str, Any]] = []

        def invoice_facts(inv: InvoiceRecord, contract_id: str | None) -> dict[str, Any]:
            return {
                "id": inv.id,
                "number": inv.number,
                "contact": inv.contact_id,
                "contract": contract_id or "",
                "on": inv.invoice_date.isoformat() if inv.invoice_date else "",
                "gross": str(inv.gross_total),
                "vat": str(inv.vat),
                "lines": [
                    {"rate": str(ln.vat_rate) if ln.vat_rate is not None else None, "category": ln.vat_category}
                    for ln in inv.lines
                ],
                "vat_facts": dict(inv.vat_facts),
                "payment_methods": list(inv.payment_methods),
            }

        for c in billing.contracts:
            rows = c.ledger.rows if c.ledger is not None else []
            counted = counted_invoices(c)
            series = ZERO
            entries = []
            for inv, row in zip(c.invoices, rows, strict=True):
                e = row.effective
                if inv.id in counted and inv.kind in SERIES_KINDS:
                    series += e.net_after
                entries.append(
                    {
                        "id": inv.id,
                        "number": inv.number,
                        "kind": inv.kind,
                        "on": inv.invoice_date.isoformat() if inv.invoice_date else "",
                        "claim": inv.claim_retention is not None,
                        "net_after": str(e.net_after),
                        "released": inv.frozen is not None,
                        "release": str(e.release),
                        "release_computed": str(row.computed.release),
                        "rounding": str(e.rounding),
                        "discount": str(e.discount),
                        "retention": str(e.retention),
                        "retention_source": e.retention_source,
                        "payable": str(e.payable),
                        "paid_cash": str(inv.paid_cash),
                        "last_payment_on": inv.last_payment_on.isoformat() if inv.last_payment_on else "",
                        "discount_until": e.discount_until.isoformat() if e.discount_until else "",
                    }
                )
                invoices.append(invoice_facts(inv, c.id))
            contracts.append(
                {
                    "id": c.id,
                    "code": c.code,
                    "status": c.status,
                    "invoice_mode": c.terms.invoice_mode,
                    "warranty_enabled": c.terms.warranty_enabled,
                    "warranty_period_months": c.warranty_period_months,
                    "discount_enabled": c.terms.discount_enabled,
                    "rounding_enabled": c.terms.rounding_enabled,
                    "rounding_step": str(c.terms.rounding_step),
                    "has_measurement": c.has_measurement,
                    "measured": str(c.measured_value),
                    "invoiced_series": str(series),
                    "current_value": str(c.current_value),
                    "retention_held": str(c.ledger.retention_held if c.ledger else ZERO),
                    "interim_due_days": c.terms.interim_due_days,
                    "final_due_days": c.terms.final_due_days,
                    "invoices": entries,
                    "postings": [
                        {
                            "id": p.id,
                            "retention_kind": p.retention_kind,
                            "event": p.event,
                            "event_on": p.event_on.isoformat() if p.event_on else "",
                            "posted_on": p.posted_on.isoformat(),
                            "amount": str(p.amount),
                        }
                        for p in c.postings
                    ],
                }
            )
        invoices.extend(invoice_facts(inv, None) for inv in billing.loose_invoices)
        return {
            "currency": billing.currency,
            "contracts": contracts,
            "invoices": invoices,
            "country": billing.country or "",
            "works": billing.works or "",
            "housing": dict(billing.housing),
        }

    async def _attach_release_certificates(
        self, payload: dict[str, Any], project_id: uuid.UUID, billing: Billing
    ) -> None:
        """Add what V19 reads: the release date, and per contract the gated requirements and the payee's certificates.

        Nothing is attached when the project's pack gates no payment on a
        certificate, so every other project's payload stays as it was.
        """
        from app.core.regional_packs import resolve_progress_billing  # noqa: PLC0415
        from app.modules.payment_release.release_certificates import (  # noqa: PLC0415
            counterparty_certificates,
            gated_requirements,
        )
        from app.modules.projects.models import Project  # noqa: PLC0415

        payload["as_of"] = datetime.now(UTC).date().isoformat()
        project = await self.session.get(Project, project_id)
        if project is None:
            return
        requirements = gated_requirements(
            resolve_progress_billing(
                country_code=getattr(project, "country_code", None), region=getattr(project, "region", None)
            )
        )
        if not requirements or not billing.contracts:
            return
        ids = [uuid.UUID(c.id) for c in billing.contracts]
        rows = (await self.session.execute(select(PaymentTerms).where(PaymentTerms.contract_id.in_(ids)))).scalars()
        enforcement = {
            str(r.contract_id): normalise_enforcement((r.metadata_ or {}).get(ENFORCEMENT_KEY)) for r in rows
        }
        held = await counterparty_certificates(self.session, [c.counterparty_id for c in billing.contracts])
        by_id = {c.id: c for c in billing.contracts}
        for entry in payload.get("contracts") or []:
            record = by_id.get(entry.get("id"))
            if record is None:
                continue
            entry["release_certificates"] = {
                "enforcement": enforcement.get(record.id, "pack"),
                "requirements": requirements,
                "certificates": held.get(str(record.counterparty_id or ""), []),
            }

    async def findings(
        self, project_id: uuid.UUID, *, locale: str, billing: Billing | None = None
    ) -> list[dict[str, Any]]:
        """Run the ``payment_release`` rule set, worst first."""
        from app.core.validation.engine import ValidationContext, rule_registry

        billing = billing or await load_billing(self.session, project_id)
        payload = self.rules_payload(billing)
        await self._attach_release_certificates(payload, project_id, billing)
        context = ValidationContext(
            data={PAYLOAD_KEY: payload},
            project_id=str(project_id),
            metadata={"locale": locale},
        )
        out: list[dict[str, Any]] = []
        for rule in rule_registry.get_rules_for_sets([RULE_SET]):
            if not rule.enabled:
                continue
            for r in await rule.validate(context):
                if r.passed:
                    continue
                out.append(
                    {
                        "rule_id": r.rule_id,
                        "rule_number": RULE_NUMBERS.get(r.rule_id) or STATUTORY_RULE_NUMBERS.get(r.rule_id, ""),
                        "severity": r.severity.value,
                        "message": r.message,
                        "suggestion": r.suggestion or "",
                        "element_ref": r.element_ref,
                        "problem": str((r.details or {}).get("problem") or ""),
                    }
                )
        order = {"error": 0, "warning": 1, "info": 2}
        out.sort(key=lambda f: (order.get(f["severity"], 3), f["rule_number"], f["message"]))
        return out
