# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""From an invoice to the amount to release. Pure, no I/O, Decimal throughout.

One contract's invoices are walked in order. Every invoice goes through the
same steps, and every step is kept so the release view can print it:

1. ``net`` as invoiced, less the agreed ``net_deduction`` (a discount on the
   contract, an agreed reduction, a back-charge) gives ``net_after``.
2. VAT is the tax the invoice states (finance and the tax modules own it);
   only the part that falls on the net deduction is taken off, line by line at
   each line's rate (:func:`vat_on_deduction`). ``gross`` is ``net_after`` plus
   that VAT, and ``gross_after`` is ``gross`` less the ``gross_deduction``
   (contra charges, site cost apportionment).
3. ``previous_releases``: what was released before on the same contract,
   before any early payment discount. A discount taken counts as paid, so it
   never comes back as an open balance on the final invoice.
4. ``retention`` per the contract's terms, on ``net_after`` or on
   ``gross_after`` as the contract says.
5. ``release_before_rounding``, then the optional ``rounding`` down to a step.
6. ``release``, then the optional early payment ``discount`` and ``payable``.

**Two invoice modes.** In *cumulative* mode each interim states the total to
date, so ``release = gross_after - retention - previous_releases``, and the
retention on it is what is held on the whole work to date: it replaces what
the last invoice held. In *incremental* mode each interim bills only the new
work, ``release = gross_after - retention`` and the retention adds up. A
*final* invoice is a statement of the whole contract in both modes, so it is
always computed the cumulative way, and its retention is the warranty
retention when one is agreed (zero otherwise): everything else held comes
back with it.

*Day work* and *credit notes* stand outside that series. They add to what the
contract is billed, carry no retention and no rounding, and their releases are
not part of a later cumulative invoice's ``previous_releases``.

**Rounding** cuts the release of an interim down to a round figure. It is
safe only because the remainder comes back: on the next cumulative invoice
through ``previous_releases``, in incremental mode on the final. A final is
never rounded, nothing would follow it.

**Retention postings** release held retention as cash. They count as previous
releases for every cumulative invoice dated on the same day or later (otherwise
the final would pay the same retention again) and reduce what is held.

**A released invoice is frozen.** Its figures are kept as they were confirmed
(``frozen``) and later invoices build on them; the recomputed figures are kept
next to them so a rule can say when terms or amounts changed afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.core.currency_registry import money_quantum

ZERO = Decimal("0")
HUNDRED = Decimal("100")

INVOICE_MODES: tuple[str, ...] = ("incremental", "cumulative")
DEFAULT_INVOICE_MODE = "incremental"
#: Interim and final make the contract's series; day work and credit notes add to it.
INVOICE_KINDS: tuple[str, ...] = ("interim", "final", "daywork", "credit_note")
SERIES_KINDS = frozenset({"interim", "final"})
RETENTION_BASES: tuple[str, ...] = ("net", "gross")
DISCOUNT_SCOPES: tuple[str, ...] = ("interim", "final", "both")

#: Where the retention on a row came from.
RETENTION_FROM_TERMS = "terms"
RETENTION_FROM_CLAIM = "claim"


def _q(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class PaymentTerms:
    """A contract's payment terms. Optional features are off unless switched on."""

    invoice_mode: str = DEFAULT_INVOICE_MODE
    retention_percent: Decimal = ZERO
    retention_basis: str = "net"
    warranty_enabled: bool = False
    warranty_percent: Decimal = ZERO
    discount_enabled: bool = False
    discount_percent: Decimal = ZERO
    discount_days: int = 0
    discount_applies_to: str = "both"
    rounding_enabled: bool = False
    rounding_step: Decimal = ZERO
    interim_due_days: int | None = None
    final_due_days: int | None = None
    currency: str = ""

    @property
    def quantum(self) -> Decimal:
        return money_quantum(self.currency or None)

    def check(self) -> None:
        """Refuse a vocabulary the computation does not know."""
        if self.invoice_mode not in INVOICE_MODES:
            raise ValueError(f"unknown invoice mode {self.invoice_mode!r}")
        if self.retention_basis not in RETENTION_BASES:
            raise ValueError(f"unknown retention basis {self.retention_basis!r}")
        if self.discount_applies_to not in DISCOUNT_SCOPES:
            raise ValueError(f"unknown discount scope {self.discount_applies_to!r}")

    def discount_applies(self, kind: str) -> bool:
        if not self.discount_enabled or self.discount_percent <= ZERO or kind == "credit_note":
            return False
        scope = self.discount_applies_to
        if kind == "final":
            return scope in ("final", "both")
        return scope in ("interim", "both")


@dataclass(frozen=True, slots=True)
class VatLine:
    """One invoice line as the VAT on a deduction needs it. ``rate`` in percent, None = not stated."""

    net: Decimal
    rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Release:
    """Every step of one invoice's release, in the order the view prints them."""

    key: str
    kind: str
    net: Decimal
    net_deduction: Decimal
    net_after: Decimal
    vat: Decimal
    vat_deduction: Decimal
    vat_after: Decimal
    gross: Decimal
    gross_deduction: Decimal
    gross_after: Decimal
    previous_releases: Decimal
    previous_counted: bool
    retention_percent: Decimal
    retention_base: Decimal
    retention: Decimal
    retention_source: str
    release_before_rounding: Decimal
    rounding: Decimal
    release: Decimal
    discount_percent: Decimal
    discount: Decimal
    payable: Decimal
    due_on: date | None = None
    discount_until: date | None = None
    retention_held_after: Decimal = ZERO

    def as_dict(self) -> dict[str, str | bool | None]:
        """Plain strings for JSON: money as decimal strings, dates as ISO."""
        out: dict[str, str | bool | None] = {}
        for name in self.__slots__:  # type: ignore[attr-defined]
            value = getattr(self, name)
            if isinstance(value, Decimal):
                out[name] = str(value)
            elif isinstance(value, date):
                out[name] = value.isoformat()
            else:
                out[name] = value
        return out


@dataclass(frozen=True, slots=True)
class InvoiceEntry:
    """One invoice as the computation reads it."""

    key: str
    kind: str
    on: date | None
    net: Decimal
    vat: Decimal
    net_deduction: Decimal = ZERO
    gross_deduction: Decimal = ZERO
    vat_lines: tuple[VatLine, ...] = ()
    #: A claim invoice carries the retention its claim certified; the terms do not apply twice.
    fixed_retention: Decimal | None = None
    #: The figures confirmed at release; None while the invoice is open.
    frozen: Release | None = None


@dataclass(frozen=True, slots=True)
class PostingEntry:
    """Held retention released as cash on a date."""

    key: str
    on: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One invoice: what the terms give today, and what counts (the frozen figures once released)."""

    computed: Release
    effective: Release

    @property
    def differs(self) -> bool:
        return self.effective is not self.computed and self.effective.release != self.computed.release


@dataclass(slots=True)
class Ledger:
    """A contract's invoices in order, and the retention position after them."""

    rows: list[LedgerRow] = field(default_factory=list)
    retention_held: Decimal = ZERO
    retention_posted: Decimal = ZERO
    released_total: Decimal = ZERO


def vat_on_deduction(
    deduction: Decimal, *, net: Decimal, vat: Decimal, lines: Sequence[VatLine] = (), currency: str | None = None
) -> Decimal:
    """The VAT that falls on a net deduction.

    The deduction is spread over the lines in proportion to their net (largest
    remainder, so it adds up to the cent), and each share takes its line's
    rate. A line without a stated rate, or an invoice without lines, takes the
    rate the invoice states as a whole (``vat / net``). A reverse charged line
    has rate zero and gives nothing.
    """
    quantum = money_quantum(currency)
    if deduction == ZERO:
        return _q(ZERO, quantum)
    effective = (vat / net * HUNDRED) if net != ZERO else ZERO
    weights = [(ln.net, effective if ln.rate is None else ln.rate) for ln in lines if ln.net > ZERO]
    if not weights:
        return _q(deduction * effective / HUNDRED, quantum)
    sign = Decimal(1) if deduction > ZERO else Decimal(-1)
    total = abs(deduction)
    weight_sum = sum((w for w, _ in weights), ZERO)
    shares: list[Decimal] = []
    remainders: list[tuple[Decimal, int]] = []
    for order, (weight, _rate) in enumerate(weights):
        exact = total * weight / weight_sum
        floored = exact.quantize(quantum, rounding=ROUND_DOWN)
        shares.append(floored)
        remainders.append((exact - floored, order))
    left = int((total - sum(shares, ZERO)) / quantum)
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for _rest, order in remainders[:left]:
        shares[order] += quantum
    tax = sum((_q(share * rate / HUNDRED, quantum) for share, (_w, rate) in zip(shares, weights, strict=True)), ZERO)
    return sign * tax


def measured_value(quantity: Decimal, unit_rate: Decimal, *, currency: str | None = None) -> Decimal:
    """Measured value of a line: measured quantity times the contract rate, to the cent."""
    return _q(quantity * unit_rate, money_quantum(currency))


def _plus_days(on: date | None, days: int | None) -> date | None:
    if on is None or days is None:
        return None
    return on + timedelta(days=int(days))


def _compute_one(
    terms: PaymentTerms, entry: InvoiceEntry, *, series_previous: Decimal, all_previous: Decimal
) -> Release:
    quantum = terms.quantum
    kind = entry.kind
    in_series = kind in SERIES_KINDS
    cumulative = in_series and (kind == "final" or terms.invoice_mode == "cumulative")

    net = _q(entry.net, quantum)
    net_deduction = _q(entry.net_deduction, quantum)
    net_after = net - net_deduction
    vat = _q(entry.vat, quantum)
    vat_deduction = vat_on_deduction(
        net_deduction, net=net, vat=vat, lines=entry.vat_lines, currency=terms.currency or None
    )
    vat_after = vat - vat_deduction
    gross = net_after + vat_after
    gross_deduction = _q(entry.gross_deduction, quantum)
    gross_after = gross - gross_deduction

    # Retention: from the claim behind the invoice, else the terms; never on day work or credits.
    if entry.fixed_retention is not None:
        retention_percent = ZERO
        retention_base = ZERO
        retention = _q(entry.fixed_retention, quantum)
        source = RETENTION_FROM_CLAIM
    else:
        source = RETENTION_FROM_TERMS
        if not in_series:
            retention_percent = ZERO
        elif kind == "final":
            retention_percent = terms.warranty_percent if terms.warranty_enabled else ZERO
        else:
            retention_percent = terms.retention_percent
        retention_base = gross_after if terms.retention_basis == "gross" else net_after
        retention = (
            _q(retention_base * retention_percent / HUNDRED, quantum) if retention_percent else _q(ZERO, quantum)
        )
        if retention_percent == ZERO:
            retention_base = _q(retention_base, quantum)

    previous = series_previous if in_series else all_previous
    counted = cumulative and entry.fixed_retention is None
    before_rounding = gross_after - retention - (series_previous if counted else ZERO)

    rounding = _q(ZERO, quantum)
    step = terms.rounding_step
    if (
        terms.rounding_enabled
        and step > ZERO
        and kind == "interim"
        and entry.fixed_retention is None
        and before_rounding > ZERO
    ):
        rounded = (before_rounding / step).to_integral_value(rounding=ROUND_FLOOR) * step
        rounding = _q(before_rounding - rounded, quantum)
    release = before_rounding - rounding

    discount_percent = terms.discount_percent if terms.discount_applies(kind) and release > ZERO else ZERO
    discount = _q(release * discount_percent / HUNDRED, quantum) if discount_percent else _q(ZERO, quantum)
    payable = release - discount

    due_days = terms.final_due_days if kind == "final" else terms.interim_due_days
    return Release(
        key=entry.key,
        kind=kind,
        net=net,
        net_deduction=net_deduction,
        net_after=net_after,
        vat=vat,
        vat_deduction=vat_deduction,
        vat_after=vat_after,
        gross=gross,
        gross_deduction=gross_deduction,
        gross_after=gross_after,
        previous_releases=_q(previous, quantum),
        previous_counted=counted,
        retention_percent=retention_percent,
        retention_base=retention_base,
        retention=retention,
        retention_source=source,
        release_before_rounding=before_rounding,
        rounding=rounding,
        release=release,
        discount_percent=discount_percent,
        discount=discount,
        payable=payable,
        due_on=_plus_days(entry.on, due_days),
        discount_until=_plus_days(entry.on, terms.discount_days) if discount_percent else None,
    )


def compute_releases(
    terms: PaymentTerms, invoices: Sequence[InvoiceEntry], postings: Sequence[PostingEntry] = ()
) -> Ledger:
    """Walk one contract's invoices in the given order, with its retention postings by date.

    A posting dated on or before an invoice's date is applied before it, a
    later one after. On the same day the posting goes first: a cumulative
    invoice subtracts everything paid, so counting the posting can never pay
    too much, while leaving it out pays the posted retention twice. Raises ``ValueError`` on an unknown mode,
    basis, scope or invoice kind.
    """
    terms.check()
    for entry in invoices:
        if entry.kind not in INVOICE_KINDS:
            raise ValueError(f"unknown invoice kind {entry.kind!r}")
    quantum = terms.quantum
    pending = sorted(postings, key=lambda p: (p.on, p.key))
    ledger = Ledger()
    series_previous = ZERO
    all_previous = ZERO
    held = ZERO

    def apply_postings(before: date | None) -> None:
        nonlocal series_previous, all_previous, held
        while pending and (before is None or pending[0].on <= before):
            posting = pending.pop(0)
            amount = _q(posting.amount, quantum)
            series_previous += amount
            all_previous += amount
            held -= amount
            ledger.retention_posted += amount
            ledger.released_total += amount

    for entry in invoices:
        if entry.on is not None:
            apply_postings(entry.on)
        computed = _compute_one(terms, entry, series_previous=series_previous, all_previous=all_previous)
        effective = entry.frozen if entry.frozen is not None else computed
        in_series = effective.kind in SERIES_KINDS
        if in_series:
            resets = effective.retention_source == RETENTION_FROM_TERMS and (
                effective.kind == "final" or terms.invoice_mode == "cumulative"
            )
            held = effective.retention if resets else held + effective.retention
            series_previous += effective.release
        all_previous += effective.release
        ledger.released_total += effective.release
        held_after = _q(held, quantum)
        if effective is computed:
            computed = effective = replace(computed, retention_held_after=held_after)
        else:
            effective = replace(effective, retention_held_after=held_after)
            computed = replace(computed, retention_held_after=held_after)
        ledger.rows.append(LedgerRow(computed=computed, effective=effective))
    apply_postings(None)
    ledger.retention_held = _q(held, quantum)
    return ledger
