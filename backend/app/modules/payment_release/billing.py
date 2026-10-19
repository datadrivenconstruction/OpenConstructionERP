# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read one project's supplier billing once: contracts, measurement, invoices, releases, payments.

Everything the invoice ledger, the retention register, the rules V11 to V18
and the cost control columns need comes out of :func:`load_billing`, in a
fixed number of queries and in the project currency, so the four readers can
never disagree about a figure.

**Which contract an invoice bills**, first answer wins: the contract a person
named on the invoice in the release view; the contract of the claim the
invoice was raised from; the contract of the schedule lines its lines bill
(the one holding most of the money); ``metadata.contract_id``. An invoice that
reaches none is listed on its own, and rule V15 (``cost_chain``) already asks
for its contract.

**Measured** is measured quantity times the contract rate, never the value a
claim certified. The quantity of a claim line is the most checked figure it
carries: certified, else assessed, else the quantity submitted. A schedule
line without a quantity (lump sum, a value-only line) has no rate to multiply,
so its measured value is the latest cumulative value claimed, and the row says
so (``basis = "value"``).

**Invoiced** is the net after the agreed deductions. On a cumulative contract
only the latest invoice of the series counts (it already holds the earlier
ones), on an incremental contract every interim adds, and a final supersedes
the interims in both. Day work and credit notes always add.

**Paid** is money paid on the invoice (refunds taken back), plus the early
payment discount where it was earned (paid in full by the discount date): the
discount counts as paid, or the final would show it as owed. Retention paid
back by a posting is paid on the contract too, spread over its lines the way
its invoiced money is.
"""

from __future__ import annotations

import uuid
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payment_release.release_math import (
    INVOICE_KINDS,
    SERIES_KINDS,
    InvoiceEntry,
    Ledger,
    LedgerRow,
    PaymentTerms,
    PostingEntry,
    Release,
    VatLine,
    compute_releases,
    measured_value,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")

#: Contract states that bind no money (the cost control commitment rules use the same three).
UNBOUND_CONTRACT_STATUSES: tuple[str, ...] = ("draft", "cancelled", "void")
#: Invoice states that no longer ask for money.
CLOSED_INVOICE_STATUSES: tuple[str, ...] = ("cancelled", "credit_note_issued")
#: Claims whose quantities count as measured: anything put forward and not thrown out.
MEASURED_CLAIM_STATUSES: tuple[str, ...] = ("submitted", "approved", "certified", "paid")

SOURCE_RELEASE = "release_view"
SOURCE_CLAIM = "claim"
SOURCE_LINES = "lines"
SOURCE_METADATA = "metadata"
#: Invoice metadata keys the statutory VAT rules read (see ``statutory_rules``).
VAT_FACT_KEYS: frozenset[str] = frozenset({"split_payment", "annex_15", "pkwiu_codes"})


def _dec(raw: object) -> Decimal:
    if isinstance(raw, Decimal):
        return raw if raw.is_finite() else ZERO
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except (ArithmeticError, ValueError):
        return ZERO
    return value if value.is_finite() else ZERO


def _uuid(raw: object) -> uuid.UUID | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _iso_date(raw: object) -> date | None:
    text = str(raw or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _is_lump_sum_unit(unit: object) -> bool:
    try:
        from app.modules.boq.units import is_lump_sum_unit
    except ImportError:  # pragma: no cover - the bill module is core
        return str(unit or "").strip().lower() in {"ls", "lsum", "lump sum"}
    return is_lump_sum_unit(str(unit or ""))


def allocate(total: Decimal, weights: Mapping[Hashable, Decimal]) -> dict[Hashable, Decimal]:
    """Cut ``total`` over positive weights to the cent, largest remainder; the parts add up to it.

    Negative totals are cut as their absolute value and given back negative.
    With no positive weight the whole amount stays with the first key, so
    money never disappears; with no key at all it returns nothing.
    """
    out: dict[Hashable, Decimal] = dict.fromkeys(weights, ZERO)
    if not weights or total == ZERO:
        return out
    sign = Decimal(1) if total > ZERO else Decimal(-1)
    amount = abs(total)
    positive = {k: w for k, w in weights.items() if w > ZERO}
    if not positive:
        first = next(iter(weights))
        out[first] = total
        return out
    weight_sum = sum(positive.values(), ZERO)
    floored_total = amount.quantize(CENT, rounding=ROUND_DOWN)
    rests: list[tuple[Decimal, int, Hashable]] = []
    for order, (key, weight) in enumerate(positive.items()):
        exact = floored_total * weight / weight_sum
        part = exact.quantize(CENT, rounding=ROUND_DOWN)
        out[key] = part
        rests.append((exact - part, order, key))
    left = int((floored_total - sum(out.values(), ZERO)) / CENT)
    rests.sort(key=lambda r: (-r[0], r[1]))
    for _rest, _order, key in rests[:left]:
        out[key] += CENT
    # A sub-cent rest (four-decimal money) stays on the biggest share.
    biggest = max(positive, key=lambda k: positive[k])
    out[biggest] += amount - floored_total
    return {k: sign * v for k, v in out.items()}


# ── What the loader returns ──────────────────────────────────────────────


@dataclass(slots=True)
class LineMeasure:
    """Measured quantity and value on one schedule line."""

    quantity: Decimal = ZERO
    value: Decimal = ZERO
    basis: str = "quantity"


@dataclass(slots=True)
class InvoiceLine:
    id: str
    amount: Decimal
    vat_rate: Decimal | None
    vat_category: str
    contract_line_id: str | None
    cost_line_id: str | None


@dataclass(slots=True)
class InvoiceRecord:
    """One supplier invoice in the project currency, with what the release view added to it."""

    id: str
    number: str
    contact_id: str
    invoice_date: date | None
    status: str
    currency: str
    net: Decimal
    vat: Decimal
    gross_total: Decimal
    lines: list[InvoiceLine]
    payments: list[tuple[date | None, Decimal]]
    contract_id: str | None
    contract_source: str | None
    kind: str
    kind_set: bool
    net_deduction: Decimal
    gross_deduction: Decimal
    net_deduction_note: str
    gross_deduction_note: str
    release_status: str
    released_at: str | None
    frozen: Release | None
    claim_retention: Decimal | None
    purchase_order_id: str | None
    #: The keys of the invoice metadata the statutory VAT rules read, and only
    #: those: ``split_payment``, ``annex_15``, ``pkwiu_codes``.
    vat_facts: dict[str, Any] = field(default_factory=dict)
    #: How each payment was made, from the payment's ``metadata.method``; an
    #: empty string where none is recorded.
    payment_methods: list[str] = field(default_factory=list)

    @property
    def paid_cash(self) -> Decimal:
        return sum((amount for _on, amount in self.payments), ZERO)

    @property
    def last_payment_on(self) -> date | None:
        dates = [on for on, _a in self.payments if on is not None]
        return max(dates) if dates else None


@dataclass(slots=True)
class PostingRecord:
    id: str
    contract_id: str
    retention_kind: str
    event: str
    event_on: date | None
    amount: Decimal
    posted_on: date
    status: str
    document_ref: str
    note: str


@dataclass(slots=True)
class ContractRecord:
    """One supplier contract and everything billed on it."""

    id: str
    code: str
    title: str
    status: str
    contract_type: str
    counterparty_id: str | None
    original_value: Decimal
    current_value: Decimal
    retention_percent: Decimal
    retention_release_event: str
    terms: PaymentTerms
    terms_set: bool
    warranty_release_event: str
    warranty_period_months: int | None
    #: The contract's own account (lump sum, or the default of its lines).
    cost_line_id: str | None = None
    lines: dict[str, Any] = field(default_factory=dict)
    measured: dict[str, LineMeasure] = field(default_factory=dict)
    invoices: list[InvoiceRecord] = field(default_factory=list)
    postings: list[PostingRecord] = field(default_factory=list)
    ledger: Ledger | None = None

    @property
    def measured_value(self) -> Decimal:
        return sum((m.value for m in self.measured.values()), ZERO)

    @property
    def has_measurement(self) -> bool:
        return any(m.quantity != ZERO or m.value != ZERO for m in self.measured.values())


@dataclass(slots=True)
class Billing:
    """One project's supplier billing."""

    currency: str
    contracts: list[ContractRecord]
    loose_invoices: list[InvoiceRecord]
    #: The project's country, works (public or private) and the dwelling its
    #: VAT rate depends on (``metadata.vat_housing``), for the statutory rules.
    country: str | None = None
    works: str | None = None
    housing: dict[str, Any] = field(default_factory=dict)

    def contract(self, contract_id: str) -> ContractRecord | None:
        return next((c for c in self.contracts if c.id == contract_id), None)


# ── Figures derived from a contract's ledger ─────────────────────────────


def counted_invoices(contract: ContractRecord) -> set[str]:
    """The invoices whose net counts as invoiced: the latest of a cumulative series, every addition."""
    series = [inv for inv in contract.invoices if inv.kind in SERIES_KINDS]
    finals = [inv for inv in series if inv.kind == "final"]
    if finals:
        kept = {finals[-1].id}
    elif contract.terms.invoice_mode == "cumulative":
        terms_series = [inv for inv in series if inv.claim_retention is None]
        claim_series = [inv for inv in series if inv.claim_retention is not None]
        kept = {terms_series[-1].id} if terms_series else set()
        kept |= {inv.id for inv in claim_series}
    else:
        kept = {inv.id for inv in series}
    kept |= {inv.id for inv in contract.invoices if inv.kind not in SERIES_KINDS}
    return kept


def row_of(contract: ContractRecord, invoice_id: str) -> LedgerRow | None:
    if contract.ledger is None:
        return None
    for inv, row in zip(contract.invoices, contract.ledger.rows, strict=True):
        if inv.id == invoice_id:
            return row
    return None


def discount_taken(invoice: InvoiceRecord, release: Release) -> Decimal:
    """The early payment discount earned: the rest paid in full by the discount date."""
    if release.discount <= ZERO or release.discount_until is None:
        return ZERO
    last = invoice.last_payment_on
    if last is None or last > release.discount_until:
        return ZERO
    if invoice.paid_cash + CENT < release.payable:
        return ZERO
    return release.discount


def invoice_paid(invoice: InvoiceRecord, release: Release | None) -> Decimal:
    """Paid on one invoice: cash, plus the discount where it was earned."""
    return invoice.paid_cash + (discount_taken(invoice, release) if release is not None else ZERO)


def contract_invoiced(contract: ContractRecord) -> Decimal:
    """Net invoiced to date on the contract (after the agreed deductions)."""
    if contract.ledger is None:
        return ZERO
    counted = counted_invoices(contract)
    return sum(
        (
            row.effective.net_after
            for inv, row in zip(contract.invoices, contract.ledger.rows, strict=True)
            if inv.id in counted
        ),
        ZERO,
    )


def invoice_line_money(invoice: InvoiceRecord, net_after: Decimal) -> dict[str, Decimal]:
    """The invoice's net after deductions, spread over its lines (by line id)."""
    weights = {ln.id: ln.amount for ln in invoice.lines}
    if not weights:
        return {}
    if sum(weights.values(), ZERO) == net_after:
        return dict(weights)
    return {str(k): v for k, v in allocate(net_after, weights).items()}


def invoice_entry(inv: InvoiceRecord) -> InvoiceEntry:
    """One invoice as :func:`compute_releases` reads it."""
    return InvoiceEntry(
        key=inv.id,
        kind=inv.kind,
        on=inv.invoice_date,
        net=inv.net,
        vat=inv.vat,
        net_deduction=inv.net_deduction,
        gross_deduction=inv.gross_deduction,
        vat_lines=tuple(VatLine(net=ln.amount, rate=ln.vat_rate) for ln in inv.lines),
        fixed_retention=inv.claim_retention,
        frozen=inv.frozen,
    )


def posting_entries(contract: ContractRecord) -> list[PostingEntry]:
    return [PostingEntry(key=p.id, on=p.posted_on, amount=p.amount) for p in contract.postings]


def released_retention_held(contract: ContractRecord) -> Decimal:
    """Retention held on the released invoices only, less what postings paid back.

    An open invoice has paid nothing yet, so it has withheld nothing either:
    its retention cannot be paid back before its release is confirmed.
    """
    released = [invoice_entry(inv) for inv in contract.invoices if inv.frozen is not None]
    return compute_releases(contract.terms, released, posting_entries(contract)).retention_held


def released_invoices_counting(contract: ContractRecord, on: date) -> list[InvoiceRecord]:
    """Released invoices that subtract every payment dated on or before ``on``.

    These are the cumulative releases (a final, or an interim on a cumulative
    contract) dated ``on`` or later. A posting or a release slipped in before
    them would change what they should have paid after they were frozen.
    """
    return [
        inv
        for inv in contract.invoices
        if inv.frozen is not None
        and inv.frozen.previous_counted
        and inv.invoice_date is not None
        and inv.invoice_date >= on
    ]


# ── The loader ───────────────────────────────────────────────────────────


def _terms_of(row: Any, contract: Any, currency: str) -> PaymentTerms:
    rate = _dec(getattr(contract, "retention_percent", None))
    if row is None:
        return PaymentTerms(retention_percent=rate, currency=currency)
    return PaymentTerms(
        invoice_mode=row.invoice_mode or "incremental",
        retention_percent=rate,
        retention_basis=row.retention_basis or "net",
        warranty_enabled=bool(row.warranty_enabled),
        warranty_percent=_dec(row.warranty_percent),
        discount_enabled=bool(row.discount_enabled),
        discount_percent=_dec(row.discount_percent),
        discount_days=int(row.discount_days or 0),
        discount_applies_to=row.discount_applies_to or "both",
        rounding_enabled=bool(row.rounding_enabled),
        rounding_step=_dec(row.rounding_step),
        interim_due_days=row.interim_due_days,
        final_due_days=row.final_due_days,
        currency=currency,
    )


def frozen_release(snapshot: Mapping[str, Any] | None) -> Release | None:
    """A confirmed release back from its stored snapshot, or None when it cannot be read."""
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("release"), Mapping):
        return None
    raw = snapshot["release"]
    try:
        values: dict[str, Any] = {}
        for name in Release.__slots__:  # type: ignore[attr-defined]
            value = raw.get(name)
            if name in ("key", "kind", "retention_source"):
                values[name] = str(value or "")
            elif name == "previous_counted":
                values[name] = bool(value)
            elif name in ("due_on", "discount_until"):
                values[name] = _iso_date(value)
            else:
                values[name] = _dec(value)
        return Release(**values)
    except (TypeError, ValueError):
        return None


async def load_billing(session: AsyncSession, project_id: uuid.UUID) -> Billing:
    """Read every supplier contract and invoice of one project; compute each contract's ledger."""
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
    from app.modules.costmodel.repository import CostSpineRepository, _amount_in_base
    from app.modules.finance.models import Invoice
    from app.modules.payment_release.models import InvoiceRelease, RetentionPosting
    from app.modules.payment_release.models import PaymentTerms as TermsRow

    base, fx = await CostSpineRepository(session)._fx_context(project_id)

    def money(raw: object, ccy: object) -> Decimal:
        return _amount_in_base(str(_dec(raw)), str(ccy or "").strip().upper(), base, fx)

    contract_rows = (
        (
            await session.execute(
                select(Contract)
                .where(
                    Contract.project_id == project_id,
                    Contract.counterparty_type == "subcontractor",
                    Contract.status.not_in(UNBOUND_CONTRACT_STATUSES),
                )
                .order_by(Contract.code)
            )
        )
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in contract_rows}
    terms_rows = {
        t.contract_id: t
        for t in ((await session.execute(select(TermsRow).where(TermsRow.project_id == project_id))).scalars().all())
    }
    contracts: dict[str, ContractRecord] = {}
    for c in contract_rows:
        row = terms_rows.get(c.id)
        current = money(c.total_value, c.currency)
        original = money(c.original_contract_value, c.currency) if c.original_contract_value is not None else current
        contracts[str(c.id)] = ContractRecord(
            id=str(c.id),
            code=c.code or "",
            title=c.title or "",
            status=(c.status or "").strip().lower(),
            contract_type=c.contract_type or "",
            counterparty_id=str(c.counterparty_id) if c.counterparty_id else None,
            original_value=original,
            current_value=current,
            retention_percent=_dec(c.retention_percent),
            retention_release_event=c.retention_release_event or "",
            terms=_terms_of(row, c, base),
            terms_set=row is not None,
            warranty_release_event=(row.warranty_release_event if row is not None else "defects_period_end"),
            warranty_period_months=(row.warranty_period_months if row is not None else None),
            cost_line_id=str(c.cost_line_id) if getattr(c, "cost_line_id", None) else None,
        )

    line_rows = (
        (await session.execute(select(ContractLine).where(ContractLine.contract_id.in_(list(by_id))))).scalars().all()
        if by_id
        else []
    )
    line_contract: dict[str, str] = {}
    for ln in line_rows:
        contracts[str(ln.contract_id)].lines[str(ln.id)] = ln
        line_contract[str(ln.id)] = str(ln.contract_id)

    # ── Measured: quantity times rate per schedule line ──────────────────
    if line_rows:
        claim_rows = (
            await session.execute(
                select(
                    ProgressClaimLine.contract_line_id,
                    ProgressClaimLine.period_completed_qty,
                    ProgressClaimLine.assessed_qty,
                    ProgressClaimLine.certified_qty,
                    ProgressClaimLine.cumulative_completed_value,
                )
                .join(ProgressClaim, ProgressClaim.id == ProgressClaimLine.progress_claim_id)
                .where(
                    ProgressClaim.contract_id.in_(list(by_id)),
                    ProgressClaim.status.in_(MEASURED_CLAIM_STATUSES),
                )
            )
        ).all()
        qty: dict[str, Decimal] = {}
        latest_value: dict[str, Decimal] = {}
        for cl_id, submitted, assessed, certified, cumulative in claim_rows:
            key = str(cl_id)
            stage = next((_dec(q) for q in (certified, assessed, submitted) if _dec(q) != ZERO), ZERO)
            qty[key] = qty.get(key, ZERO) + stage
            value = _dec(cumulative)
            if value > latest_value.get(key, ZERO):
                latest_value[key] = value
        for ln in line_rows:
            key = str(ln.id)
            if key not in qty and key not in latest_value:
                continue
            contract = contracts[str(ln.contract_id)]
            ccy = by_id[ln.contract_id].currency
            if _dec(ln.quantity) > ZERO and not _is_lump_sum_unit(ln.unit):
                q = qty.get(key, ZERO)
                value = measured_value(q, _dec(ln.unit_rate), currency=(ccy or None))
                contract.measured[key] = LineMeasure(quantity=q, value=money(value, ccy), basis="quantity")
            else:
                contract.measured[key] = LineMeasure(
                    quantity=qty.get(key, ZERO), value=money(latest_value.get(key, ZERO), ccy), basis="value"
                )

    # ── Supplier invoices and what the release view added to them ────────
    invoices = (
        (
            await session.execute(
                select(Invoice).where(
                    Invoice.project_id == project_id,
                    Invoice.invoice_direction == "payable",
                    Invoice.status.not_in(CLOSED_INVOICE_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    releases = {
        r.invoice_id: r
        for r in (
            (await session.execute(select(InvoiceRelease).where(InvoiceRelease.project_id == project_id)))
            .scalars()
            .all()
        )
    }
    claim_ids = {inv.source_claim_id for inv in invoices if inv.source_claim_id is not None}
    claim_contract: dict[uuid.UUID, uuid.UUID] = {}
    if claim_ids:
        claim_contract = dict(
            (
                await session.execute(
                    select(ProgressClaim.id, ProgressClaim.contract_id).where(ProgressClaim.id.in_(list(claim_ids)))
                )
            ).all()
        )

    loose: list[InvoiceRecord] = []
    for inv in invoices:
        ccy = (inv.currency_code or "").strip().upper()
        rel = releases.get(inv.id)
        lines = [
            InvoiceLine(
                id=str(li.id),
                amount=money(li.amount, ccy),
                vat_rate=_dec(li.vat_rate) if li.vat_rate is not None else None,
                vat_category=(li.vat_category or "").strip().upper(),
                contract_line_id=str(li.contract_line_id) if li.contract_line_id else None,
                cost_line_id=str(li.cost_line_id) if li.cost_line_id else None,
            )
            for li in sorted(inv.line_items or [], key=lambda li: (li.sort_order or 0, str(li.id)))
        ]
        payments = [
            (_iso_date(p.payment_date), money(p.amount, p.currency_code or ccy) * (-1 if p.is_refund else 1))
            for p in inv.payments or []
        ]
        contract_id, source = None, None
        if rel is not None and rel.contract_id is not None and str(rel.contract_id) in contracts:
            contract_id, source = str(rel.contract_id), SOURCE_RELEASE
        elif inv.source_claim_id is not None and str(claim_contract.get(inv.source_claim_id)) in contracts:
            contract_id, source = str(claim_contract[inv.source_claim_id]), SOURCE_CLAIM
        else:
            weight: dict[str, Decimal] = {}
            for ln in lines:
                owner = line_contract.get(ln.contract_line_id or "")
                if owner:
                    weight[owner] = weight.get(owner, ZERO) + abs(ln.amount)
            if weight:
                contract_id, source = max(weight, key=lambda k: (weight[k], k)), SOURCE_LINES
            else:
                meta_id = str(_uuid((inv.metadata_ or {}).get("contract_id")) or "")
                if meta_id in contracts:
                    contract_id, source = meta_id, SOURCE_METADATA
        net = money(inv.amount_subtotal, ccy)
        kind = (
            rel.kind if rel is not None and rel.kind in INVOICE_KINDS else ("credit_note" if net < ZERO else "interim")
        )
        record = InvoiceRecord(
            id=str(inv.id),
            number=inv.invoice_number or "",
            contact_id=str(inv.contact_id or ""),
            invoice_date=_iso_date(inv.invoice_date),
            status=inv.status or "",
            currency=ccy,
            net=net,
            vat=money(inv.tax_amount, ccy),
            gross_total=money(inv.amount_total, ccy),
            lines=lines,
            payments=payments,
            contract_id=contract_id,
            contract_source=source,
            kind=kind,
            kind_set=rel is not None,
            net_deduction=money(rel.net_deduction, ccy) if rel is not None else ZERO,
            gross_deduction=money(rel.gross_deduction, ccy) if rel is not None else ZERO,
            net_deduction_note=(rel.net_deduction_note or "") if rel is not None else "",
            gross_deduction_note=(rel.gross_deduction_note or "") if rel is not None else "",
            release_status=(rel.status if rel is not None else "open") or "open",
            released_at=rel.released_at.isoformat() if rel is not None and rel.released_at else None,
            frozen=frozen_release(rel.snapshot) if rel is not None and rel.status == "released" else None,
            claim_retention=money(inv.retention_amount, ccy) if inv.source_claim_id is not None else None,
            purchase_order_id=str(inv.purchase_order_id) if inv.purchase_order_id else None,
            vat_facts={k: v for k, v in (inv.metadata_ or {}).items() if k in VAT_FACT_KEYS},
            payment_methods=[str((p.metadata_ or {}).get("method") or "") for p in inv.payments or []],
        )
        if contract_id is None:
            loose.append(record)
        else:
            contracts[contract_id].invoices.append(record)

    postings = (
        (
            await session.execute(
                select(RetentionPosting).where(
                    RetentionPosting.project_id == project_id, RetentionPosting.status == "posted"
                )
            )
        )
        .scalars()
        .all()
    )
    for p in postings:
        owner = contracts.get(str(p.contract_id))
        if owner is None:
            continue
        owner.postings.append(
            PostingRecord(
                id=str(p.id),
                contract_id=str(p.contract_id),
                retention_kind=p.retention_kind or "interim",
                event=p.event or "",
                event_on=p.event_on,
                amount=_dec(p.amount),
                posted_on=p.posted_on,
                status=p.status,
                document_ref=p.document_ref or "",
                note=p.note or "",
            )
        )

    for contract in contracts.values():
        contract.invoices.sort(key=lambda i: (i.invoice_date or date.max, i.number, i.id))
        contract.postings.sort(key=lambda p: (p.posted_on, p.id))
        contract.ledger = compute_releases(
            contract.terms, [invoice_entry(inv) for inv in contract.invoices], posting_entries(contract)
        )
    loose.sort(key=lambda i: (i.invoice_date or date.max, i.number, i.id))
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    housing = (project.metadata_ or {}).get("vat_housing") if project is not None else None
    return Billing(
        currency=base,
        contracts=list(contracts.values()),
        loose_invoices=loose,
        country=(project.country_code or None) if project is not None else None,
        works=(project.works or None) if project is not None else None,
        housing=housing if isinstance(housing, dict) else {},
    )


# ── Per schedule line and per cost line, for cost control ────────────────


@dataclass(slots=True)
class LineBilling:
    """Measured, invoiced and paid per schedule line, plus invoice money that reaches no schedule line."""

    measured: dict[str, Decimal] = field(default_factory=dict)
    invoiced: dict[str, Decimal] = field(default_factory=dict)
    paid: dict[str, Decimal] = field(default_factory=dict)
    #: Invoice lines on no bound schedule line: (invoice line id, cost line id or None, invoiced, paid).
    direct: list[tuple[str, str | None, Decimal, Decimal]] = field(default_factory=list)


def _add(acc: dict[str, Decimal], key: str, amount: Decimal) -> None:
    acc[key] = acc.get(key, ZERO) + amount


def line_billing(billing: Billing) -> LineBilling:
    """Spread every contract's measured, invoiced and paid money over its schedule lines."""
    out = LineBilling()
    for contract in billing.contracts:
        for line_id, measure in contract.measured.items():
            _add(out.measured, line_id, measure.value)
        counted = counted_invoices(contract)
        invoiced_by_line: dict[str, Decimal] = {}
        rows = contract.ledger.rows if contract.ledger is not None else []
        for inv, row in zip(contract.invoices, rows, strict=True):
            release = row.effective
            money = invoice_line_money(inv, release.net_after)
            paid = invoice_paid(inv, release)
            paid_by_line = (
                {str(k): v for k, v in allocate(paid, {ln.id: abs(ln.amount) for ln in inv.lines}).items()}
                if inv.lines
                else {}
            )
            for ln in inv.lines:
                part = money.get(ln.id, ZERO) if inv.id in counted else ZERO
                cash = paid_by_line.get(ln.id, ZERO)
                if ln.contract_line_id and ln.contract_line_id in contract.lines:
                    _add(out.invoiced, ln.contract_line_id, part)
                    _add(out.paid, ln.contract_line_id, cash)
                    _add(invoiced_by_line, ln.contract_line_id, part)
                else:
                    out.direct.append((ln.id, ln.cost_line_id or contract.cost_line_id, part, cash))
            if not inv.lines:
                out.direct.append(
                    (inv.id, contract.cost_line_id, release.net_after if inv.id in counted else ZERO, paid)
                )
        posted = sum((p.amount for p in contract.postings), ZERO)
        if posted:
            weights = {k: v for k, v in invoiced_by_line.items() if v > ZERO}
            if weights:
                for key, part in allocate(posted, weights).items():
                    _add(out.paid, str(key), part)
            else:
                out.direct.append((contract.id, contract.cost_line_id, ZERO, posted))
    for inv in billing.loose_invoices:
        paid = invoice_paid(inv, None)
        net_after = inv.net
        money = invoice_line_money(inv, net_after)
        paid_by_line = (
            {str(k): v for k, v in allocate(paid, {ln.id: abs(ln.amount) for ln in inv.lines}).items()}
            if inv.lines
            else {}
        )
        for ln in inv.lines:
            out.direct.append((ln.id, ln.cost_line_id, money.get(ln.id, ZERO), paid_by_line.get(ln.id, ZERO)))
        if not inv.lines:
            out.direct.append((inv.id, None, net_after, paid))
    return out
