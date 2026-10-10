# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The shared payment tax calculation: VAT, VAT withholding, income withholding, stamp duty.

A payment certificate, the tax ledger and the e-invoice all print these
numbers. They are computed here once, so the three documents cannot disagree.
Four decisions live in this file and nowhere else.

**Three VAT figures, not one.** Where the buyer withholds part of the VAT, the
document has to show the VAT that was computed, the share the buyer keeps back
and remits itself, and the rest that the seller collects and declares. Each of
the three is declared to the tax office by somebody, so each is a figure of its
own with its own basis.

**Payable is a subtraction.** ``vat_payable = vat_computed - vat_withheld`` and
is never rounded on its own. Round the two shares separately and a VAT of 0.05
split in half becomes 0.03 + 0.03: the buyer's return and the seller's return
then add up to a cent more than the invoice shows. Because the withheld share
is rounded from the already rounded VAT and the remainder is whatever is left,
``vat_computed == vat_withheld + vat_payable`` holds for every input.

**Held is not zero.** A figure has three states. ``value`` is an amount, and
zero is an ordinary amount. ``not_applicable`` is a person's statement, with
their reason, that the tax does not arise. ``held`` means the figure cannot be
known yet: nobody chose a category, no rate is in force on the date, the VAT
rate is unknown, a threshold cannot be judged from one document. A held figure
has no amount at all. Printing it as ``0,00`` would be a tax return that says
"nothing was withheld" when the truth is "nobody has decided". Any total that
includes a held figure is itself held.

**No fallback into a plausible default.** An unknown currency does not round to
cents, a missing rate does not take the nearest row, an unknown VAT rate is not
zero, and an unreadable input raises instead of becoming zero. Each of those
defaults produces a number that looks right and is not, on a document somebody
signs.

Rounding is half-up (ties away from zero) to the quantum of the currency. A
negative net, as on a credit note, is therefore the exact mirror of the
positive one: every amount flips its sign and nothing else changes.

Standard library only, plus the currency table of
:mod:`app.core.currency_registry`. Nothing here may import from ``app.modules``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Context, Decimal
from typing import Literal

from app.core.currency_registry import CURRENCIES, money_quantum
from app.core.payment_taxes.tables import BASES, BUYER_SCOPES, OverlappingRowsError, RateRow, lookup

__all__ = [
    "ALL_REASON_KEYS",
    "CONSUMER_REASON_KEYS",
    "FIGURE_KINDS",
    "REASON_KEYS",
    "Choice",
    "Figure",
    "Override",
    "PaymentTaxInput",
    "PaymentTaxResult",
    "allocate",
    "compute_payment_taxes",
]

#: The five figures, in the order a document prints them.
FIGURE_KINDS: tuple[str, ...] = ("vat_computed", "vat_withheld", "vat_payable", "income_withheld", "stamp_duty")

#: Every ``Figure.reason_key`` the calculator can emit. The vocabulary is
#: closed: each key has a translation on the screen and on the printed
#: document, so a key invented in passing would reach a reader as raw text.
#: A test runs the calculator through every branch and compares the keys it
#: saw with this tuple, in both directions.
REASON_KEYS: tuple[str, ...] = (
    "",  # an ordinary value
    "not_chosen",
    "no_rate_on_date",
    "rate_ambiguous",
    "rate_row_invalid",
    "vat_rate_unknown",
    "withholding_needs_vat",
    "not_applicable_by_user",
    "not_applicable_reason_missing",
    "buyer_class_unknown",
    "buyer_not_designated",
    "work_value_unknown",
    "below_work_value",
    "below_threshold",
    "threshold_currency_mismatch",
    "threshold_needs_year_total",
    "capped",
    "cap_currency_mismatch",
    "override_reason_missing",
    "override_precision",
    "override_not_allowed",
    "currency_unknown",
)

#: Reason keys the calculator itself never emits but that reach the same
#: screens and the same printed documents, set by whoever consumes its result:
#: the module that stores the figures of a payment document, and the payment
#: certificate that prints them among its other lines. They are listed here,
#: beside the calculator's own, so that one place names every reason a reader
#: can be shown. A consumer that invents a key outside this tuple fails the
#: vocabulary test, which reads the consumers' source for the keys they use.
CONSUMER_REASON_KEYS: tuple[str, ...] = (
    # Set by the module that stores a document's taxes.
    "stamp_duty_base_unknown",
    # Set by the certificate when it cannot take the stored figures as they are.
    "module_absent",
    "provider_failed",
    "missing_figure",
    "tax_base_mismatch",
    "taxes_stale",
    "taxes_outdated",
    "taxes_not_stored",
    "taxes_not_confirmed",
    "unconfirmed_rate",
    "overridden",
    # Set by the certificate for its own lines.
    "base_held",
    "operand_held",
    "not_entered",
    "manual_held",
    "retention_unknown",
    "previous_unknown",
    "previous_not_certified",
    "work_line_incomplete",
    "other",
)

#: Every reason key that can reach a screen or a printed document.
ALL_REASON_KEYS: tuple[str, ...] = (*REASON_KEYS, *CONSUMER_REASON_KEYS)

_CHOICE_STATES = ("selected", "not_applicable", "unset")
_OVERRIDE_KEYS = ("vat_computed", "vat_withheld", "vat_payable", "income_withheld", "stamp_duty")
#: A caller that thinks in row kinds may key an override by the row kind.
_OVERRIDE_ALIASES = {"vat_withholding": "vat_withheld", "income_withholding": "income_withheld"}
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")
# Wide enough that a product of two long decimals is exact before it is
# rounded once. The default 28 digits would round a long intermediate first.
_EXACT = Context(prec=80)


@dataclass(frozen=True)
class Choice:
    """What a person decided about one tax on one document.

    The category is always chosen by a person. Nothing is inferred from a work
    description, because the same words can fall under two categories with
    different fractions.

    Attributes:
        state: ``selected`` with a code, ``not_applicable`` with a reason, or
            ``unset`` when nobody has decided yet.
        code: The category code, required when ``state == "selected"``.
        reason: Why the tax does not arise, required when
            ``state == "not_applicable"``.
    """

    state: Literal["selected", "not_applicable", "unset"]
    code: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Override:
    """An amount a person entered in place of the computed one.

    Attributes:
        amount: The amount to use, in units the currency can express.
        reason: Why the computed amount was replaced. Without it the figure is
            held: an unexplained number on a tax line cannot be audited.
        by: Who entered it.
    """

    amount: Decimal
    reason: str
    by: str


@dataclass(frozen=True)
class PaymentTaxInput:
    """Everything the calculation needs for one document or one group of lines.

    Attributes:
        country_code: Jurisdiction whose rows apply.
        currency: ISO 4217 code of the document.
        on: The date the document is taxed on.
        net_amount: Amount before VAT. Negative on a credit note.
        vat_rate_pct: VAT rate in percent. ``None`` means unknown, never zero.
        vat_withholding: Choice for the VAT withholding category.
        income_withholding: Choice for the income tax withholding category.
        stamp_duty: Choice for the stamp duty category.
        overrides: Amounts entered by a person, keyed by figure kind
            (``vat_computed``, ``vat_withheld``, ``income_withheld``,
            ``stamp_duty``). The row kinds ``vat_withholding`` and
            ``income_withholding`` are accepted as names for the same figures.
        buyer_is_designated: Whether the buyer is one the law designates to
            withhold. ``None`` means nobody has said, never "no".
        work_value_incl_vat: Value of the whole work under the contract, VAT
            included, in the document currency. ``None`` means unknown.
    """

    country_code: str
    currency: str
    on: date
    net_amount: Decimal
    vat_rate_pct: Decimal | None
    vat_withholding: Choice
    income_withholding: Choice
    stamp_duty: Choice
    overrides: Mapping[str, Override] = field(default_factory=dict)
    buyer_is_designated: bool | None = None
    work_value_incl_vat: Decimal | None = None


@dataclass(frozen=True)
class Figure:
    """One tax figure together with everything needed to check it.

    Attributes:
        kind: One of :data:`FIGURE_KINDS`.
        status: ``value``, ``not_applicable`` or ``held``.
        amount: The amount, ``None`` unless ``status == "value"``.
        base: The amount the rate or fraction was applied to, when known.
        rate_pct: The percent applied, for a percent figure.
        numerator: The fraction applied, for withheld VAT.
        denominator: The fraction applied, for withheld VAT.
        code: The category code the figure was computed under.
        legal_reference: The article behind the row that was used.
        effective_from: First day of the row that was used.
        review_status: ``confirmed`` or ``unconfirmed`` from the row, empty
            when no row is involved.
        overridden: True when a person's amount replaced the computed one.
        reason_key: One of :data:`REASON_KEYS`; empty for an ordinary value.
        reason_params: Values for the translated reason text, all strings.
    """

    kind: str
    status: Literal["value", "not_applicable", "held"]
    amount: Decimal | None
    base: Decimal | None
    rate_pct: Decimal | None
    numerator: int | None
    denominator: int | None
    code: str
    legal_reference: str
    effective_from: date | None
    review_status: str
    overridden: bool
    reason_key: str
    reason_params: Mapping[str, str]


@dataclass(frozen=True)
class PaymentTaxResult:
    """The five figures of one calculation."""

    vat_computed: Figure
    vat_withheld: Figure
    vat_payable: Figure
    income_withheld: Figure
    stamp_duty: Figure

    @property
    def complete(self) -> bool:
        """True when no figure is ``held``, so totals may be drawn from the result."""
        return all(figure.status != "held" for figure in self.figures())

    def figures(self) -> tuple[Figure, ...]:
        """The five figures in the order of :data:`FIGURE_KINDS`."""
        return (self.vat_computed, self.vat_withheld, self.vat_payable, self.income_withheld, self.stamp_duty)


# ── Small helpers ────────────────────────────────────────────────────────────


def _currency(code: str) -> str:
    return (code or "").strip().upper()


def _round(value: Decimal, quantum: Decimal) -> Decimal:
    """Half-up to the currency quantum, with a negative zero written as zero."""
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP, context=_EXACT)
    # Decimal keeps the sign of a zero. "-0.00" on a tax line reads as a typo.
    return rounded if rounded else abs(rounded)


def _require_decimal(value: object, name: str) -> Decimal:
    """Refuse anything that is not a finite Decimal.

    A float has already lost the cents it is asked about, and a value that
    cannot be read must not quietly become zero: a zero base computes a zero
    tax that looks like an answer.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be a finite number, got {value}")
    return value


def _figure(
    kind: str,
    status: Literal["value", "not_applicable", "held"],
    *,
    amount: Decimal | None = None,
    base: Decimal | None = None,
    rate_pct: Decimal | None = None,
    row: RateRow | None = None,
    code: str = "",
    overridden: bool = False,
    reason_key: str = "",
    params: Mapping[str, str] | None = None,
) -> Figure:
    """Build a figure, taking the legal basis from ``row`` when there is one."""
    return Figure(
        kind=kind,
        status=status,
        amount=amount if status == "value" else None,
        base=base,
        rate_pct=rate_pct if row is None else row.rate_pct,
        numerator=None if row is None else row.numerator,
        denominator=None if row is None else row.denominator,
        code=code if row is None else row.code,
        legal_reference="" if row is None else row.legal_reference,
        effective_from=None if row is None else row.effective_from,
        review_status="" if row is None else row.review_status,
        overridden=overridden,
        reason_key=reason_key,
        reason_params=dict(params or {}),
    )


@dataclass(frozen=True)
class _Run:
    """The parts of one calculation that every figure needs."""

    inp: PaymentTaxInput
    rows: Sequence[RateRow]
    currency: str
    quantum: Decimal
    overrides: Mapping[str, Override]

    def round(self, value: Decimal) -> Decimal:
        return _round(value, self.quantum)


def _check_input(inp: PaymentTaxInput) -> dict[str, Override]:
    """Reject inputs that are programming errors and normalise override keys."""
    _require_decimal(inp.net_amount, "net_amount")
    if inp.vat_rate_pct is not None and _require_decimal(inp.vat_rate_pct, "vat_rate_pct") < 0:
        raise ValueError(f"vat_rate_pct must not be negative, got {inp.vat_rate_pct}")
    if inp.work_value_incl_vat is not None:
        _require_decimal(inp.work_value_incl_vat, "work_value_incl_vat")
    if inp.buyer_is_designated is not None and not isinstance(inp.buyer_is_designated, bool):
        raise TypeError("buyer_is_designated must be True, False or None")
    for name in ("vat_withholding", "income_withholding", "stamp_duty"):
        choice: Choice = getattr(inp, name)
        if choice.state not in _CHOICE_STATES:
            raise ValueError(f"{name}.state {choice.state!r} is not one of {_CHOICE_STATES}")

    overrides: dict[str, Override] = {}
    for key, override in inp.overrides.items():
        target = _OVERRIDE_ALIASES.get(key, key)
        # An override under a key nobody reads would be dropped in silence,
        # and the person who entered it would see the computed amount instead.
        if target not in _OVERRIDE_KEYS:
            raise ValueError(f"override key {key!r} names no figure; use one of {_OVERRIDE_KEYS}")
        if target in overrides:
            raise ValueError(f"figure {target!r} is overridden twice, under two names")
        _require_decimal(override.amount, f"override amount for {target}")
        overrides[target] = override
    return overrides


def _apply_override(
    run: _Run,
    kind: str,
    override: Override,
    computed: Decimal | None,
    *,
    base: Decimal | None = None,
    rate_pct: Decimal | None = None,
    row: RateRow | None = None,
    code: str = "",
) -> Figure:
    """Put a person's amount in place of the computed one, or hold it.

    The basis of the computed figure stays on the result, so the reader sees
    what was replaced and under which article.
    """

    def build(status: Literal["value", "held"], reason_key: str, params: Mapping[str, str]) -> Figure:
        return _figure(
            kind,
            status,
            amount=run.round(override.amount) if status == "value" else None,
            base=base,
            rate_pct=rate_pct,
            row=row,
            code=code,
            overridden=status == "value",
            reason_key=reason_key,
            params=params,
        )

    if not (override.reason or "").strip():
        return build("held", "override_reason_missing", {})
    # Rounding a person's figure would print an amount they did not enter.
    if override.amount != override.amount.quantize(run.quantum, rounding=ROUND_HALF_UP, context=_EXACT):
        return build("held", "override_precision", {"amount": str(override.amount), "currency": run.currency})
    params = {"reason": override.reason.strip(), "by": override.by}
    if computed is not None:
        params["computed"] = str(computed)
    return build("value", "", params)


def _row_is_computable(row: RateRow, row_kind: str) -> bool:
    """Whether a row carries what the arithmetic needs.

    Narrower than :func:`app.core.payment_taxes.tables.validate_rows`, which
    also checks the provenance of a row. This asks only whether an amount can
    be computed without guessing a missing part.
    """
    if row.base not in BASES or row.buyer_scope not in BUYER_SCOPES:
        return False
    if row_kind == "vat_withholding":
        if row.base != "vat" or row.numerator is None or row.denominator is None:
            return False
        if row.denominator <= 0 or not 0 <= row.numerator <= row.denominator:
            return False
    elif row.rate_pct is None or not row.rate_pct.is_finite() or row.rate_pct < 0:
        return False
    if row.threshold_amount is not None:
        if row.threshold_scope not in ("per_document", "per_payee_year"):
            return False
        if row.threshold_measure not in ("net", "net_plus_vat"):
            return False
    return not (row.buyer_scope == "designated_or_work_value" and row.work_value_threshold is None)


# ── The figures ──────────────────────────────────────────────────────────────


def _vat_computed(run: _Run) -> Figure:
    """VAT on the net amount, rounded once."""
    inp = run.inp
    rate = inp.vat_rate_pct
    computed = None if rate is None else run.round(_EXACT.divide(_EXACT.multiply(inp.net_amount, rate), _HUNDRED))
    override = run.overrides.get("vat_computed")
    if override is not None:
        return _apply_override(run, "vat_computed", override, computed, base=inp.net_amount, rate_pct=rate)
    if computed is None:
        # Unknown is not zero. Zero would print a VAT-free document.
        return _figure("vat_computed", "held", base=inp.net_amount, reason_key="vat_rate_unknown")
    return _figure("vat_computed", "value", amount=computed, base=inp.net_amount, rate_pct=rate)


def _buyer_condition(run: _Run, row: RateRow) -> tuple[Literal["not_applicable", "held"], str, dict[str, str]] | None:
    """Judge whether the tax applies to this buyer, or say why it cannot be judged.

    Who the buyer is decides whether a withholding arises at all, and the
    answer is never assumed: an unknown buyer class holds the figure.
    """
    designated = run.inp.buyer_is_designated
    if row.buyer_scope == "designated_only":
        if designated is None:
            return ("held", "buyer_class_unknown", {})
        return None if designated else ("not_applicable", "buyer_not_designated", {})
    if row.buyer_scope != "designated_or_work_value" or designated:
        return None

    # An ordinary buyer withholds only when the whole work is large enough.
    # A work at or above the limit is taxed whoever the buyer is, so an
    # unknown buyer class only matters below it.
    limit = row.work_value_threshold
    work_value = run.inp.work_value_incl_vat
    if limit is None:  # ruled out by _row_is_computable
        return ("held", "rate_row_invalid", {})
    if work_value is None:
        return ("held", "buyer_class_unknown" if designated is None else "work_value_unknown", {})
    row_currency = _currency(row.threshold_currency)
    if row_currency != run.currency:
        params = {"threshold_currency": row_currency, "document_currency": run.currency}
        return ("held", "threshold_currency_mismatch", params)
    if work_value >= limit:
        return None
    if designated is None:
        return ("held", "buyer_class_unknown", {})
    params = {"threshold": str(limit), "currency": row_currency, "work_value": str(work_value)}
    return ("not_applicable", "below_work_value", params)


def _threshold_condition(
    run: _Run, row: RateRow, vat: Figure
) -> tuple[Literal["not_applicable", "held"], str, dict[str, str]] | None:
    """Judge the row's threshold against this document."""
    if row.threshold_amount is None:
        return None
    net = run.inp.net_amount
    if row.threshold_scope == "per_document" and net < 0:
        # A credit note corrects a document on which the threshold was already
        # tested. Its own size says nothing: a small credit against a large
        # invoice reverses a share of a withholding that did apply.
        return None
    row_currency = _currency(row.threshold_currency)
    if row_currency != run.currency:
        params = {"threshold_currency": row_currency, "document_currency": run.currency}
        return ("held", "threshold_currency_mismatch", params)
    if row.threshold_scope == "per_payee_year":
        # One payment cannot prove a yearly total, in either direction.
        return (
            "held",
            "threshold_needs_year_total",
            {"threshold": str(row.threshold_amount), "currency": row_currency},
        )
    measured = net
    if row.threshold_measure == "net_plus_vat":
        if vat.amount is None:
            return ("held", "withholding_needs_vat", {})
        measured = net + vat.amount
    if measured < row.threshold_amount:
        params = {
            "threshold": str(row.threshold_amount),
            "currency": row_currency,
            "measure": row.threshold_measure,
            "measured": str(measured),
        }
        return ("not_applicable", "below_threshold", params)
    return None


def _row_figure(run: _Run, kind: str, row_kind: str, choice: Choice, vat: Figure) -> Figure:
    """One figure that comes from a rate row: withheld VAT, income withholding, stamp duty."""
    inp = run.inp
    override = run.overrides.get(kind)
    code = (choice.code or "").strip()

    # 1. The person's decision. An override does not stand in for it: an
    #    amount entered against a tax nobody chose has no category to file under.
    if choice.state == "unset" or (choice.state == "selected" and not code):
        return _figure(kind, "held", code=code, reason_key="not_chosen")
    if choice.state == "not_applicable":
        reason = (choice.reason or "").strip()
        if not reason:
            return _figure(kind, "held", code=code, reason_key="not_applicable_reason_missing")
        return _figure(
            kind, "not_applicable", code=code, reason_key="not_applicable_by_user", params={"reason": reason}
        )

    # 2. The row in force on the date. Never the nearest one.
    problem = ""
    params: dict[str, str] = {"code": code, "on": inp.on.isoformat()}
    row: RateRow | None = None
    try:
        row = lookup(run.rows, country=inp.country_code, kind=row_kind, code=code, on=inp.on)
    except OverlappingRowsError:
        problem = "rate_ambiguous"
    if not problem and row is None:
        problem = "no_rate_on_date"
    if not problem and row is not None and not _row_is_computable(row, row_kind):
        problem, row = "rate_row_invalid", None
    if row is None:
        if override is not None:
            return _apply_override(run, kind, override, None, code=code)
        return _figure(kind, "held", code=code, reason_key=problem, params=params)

    # 3. The base. A base that needs the VAT waits for the VAT.
    base: Decimal | None = inp.net_amount
    if row.base in ("vat", "net_plus_vat"):
        if vat.amount is None:
            base = None
        elif row.base == "vat":
            base = vat.amount
        else:
            base = inp.net_amount + vat.amount
    computed: Decimal | None = None
    if base is not None:
        if row_kind == "vat_withholding":
            # From the rounded VAT, so the line follows from the one above it.
            exact = _EXACT.divide(_EXACT.multiply(base, Decimal(row.numerator or 0)), Decimal(row.denominator or 1))
        else:
            exact = _EXACT.divide(_EXACT.multiply(base, row.rate_pct or _ZERO), _HUNDRED)
        computed = run.round(exact)

    if override is not None:
        return _apply_override(run, kind, override, computed, base=base, row=row)
    if computed is None:
        waiting = "vat_rate_unknown" if kind == "vat_withheld" and vat.reason_key == "vat_rate_unknown" else ""
        return _figure(kind, "held", row=row, reason_key=waiting or "withholding_needs_vat")
    if inp.net_amount == 0:
        # Nothing was invoiced, so nothing is taxed. The conditions below ask
        # about a transaction that did not happen.
        return _figure(kind, "value", amount=computed, base=base, row=row)

    # 4. Whether the tax arises for this buyer and this document.
    for outcome in (_buyer_condition(run, row), _threshold_condition(run, row, vat)):
        if outcome is not None:
            status, reason_key, why = outcome
            return _figure(kind, status, base=base, row=row, reason_key=reason_key, params=why)

    # 5. The cap limits the size of the amount, whichever its sign.
    if row.cap_amount is not None:
        row_currency = _currency(row.threshold_currency)
        if row_currency != run.currency:
            why = {"cap_currency": row_currency, "document_currency": run.currency}
            return _figure(kind, "held", base=base, row=row, reason_key="cap_currency_mismatch", params=why)
        cap = run.round(row.cap_amount)
        if abs(computed) > cap:
            why = {"cap": str(cap), "currency": row_currency, "computed": str(computed)}
            capped = cap if computed > 0 else -cap
            return _figure(kind, "value", amount=capped, base=base, row=row, reason_key="capped", params=why)
    return _figure(kind, "value", amount=computed, base=base, row=row)


def _vat_payable(run: _Run, vat: Figure, withheld: Figure) -> Figure:
    """The VAT the seller collects: what is left after the buyer's share.

    A subtraction and nothing else. It is never rounded, never looked up and
    never overridden, which is what keeps the three figures summing exactly.
    """

    def build(status: Literal["value", "held"], amount: Decimal | None, reason_key: str = "") -> Figure:
        params = vat.reason_params if vat.amount is None else withheld.reason_params
        return Figure(
            kind="vat_payable",
            status=status,
            amount=amount,
            base=vat.amount,
            rate_pct=None,
            numerator=None,
            denominator=None,
            code=withheld.code,
            legal_reference=withheld.legal_reference,
            effective_from=withheld.effective_from,
            review_status=withheld.review_status,
            overridden=False,
            reason_key=reason_key,
            reason_params=dict(params) if status == "held" and reason_key != "override_not_allowed" else {},
        )

    if "vat_payable" in run.overrides:
        # To change the payable VAT, change the withheld VAT it is derived from.
        return build("held", None, "override_not_allowed")
    if vat.amount is None:
        return build("held", None, vat.reason_key)
    if withheld.status == "held":
        return build("held", None, withheld.reason_key)
    if withheld.amount is None:
        # Nothing is withheld, so the whole VAT is the seller's to collect.
        return build("value", vat.amount)
    return build("value", vat.amount - withheld.amount)


def compute_payment_taxes(inp: PaymentTaxInput, rows: Sequence[RateRow]) -> PaymentTaxResult:
    """Compute the five payment tax figures of one document from statutory rows.

    Order of work, which is also the order of rounding:

    1. ``vat_computed = round(net * rate / 100)``.
    2. ``vat_withheld = round(vat_computed * numerator / denominator)``, from
       the already rounded VAT.
    3. ``vat_payable = vat_computed - vat_withheld``, a subtraction.
    4. Income withholding and stamp duty are ``round(base * rate / 100)``, each
       rounded once, then limited by the row's cap.

    For each row figure the person's choice is read first, then the row in
    force on the date, then an override, then the conditions of the row (buyer
    class, value of the work, threshold), then the cap. An override therefore
    replaces a figure that is held for want of data, but not one that is held
    because nobody chose a category, and not one a person marked as not
    applicable.

    Negative and zero amounts. A credit note carries a negative net. Rounding
    is half-up away from zero, so every figure of ``-net`` is the negation of
    the figure of ``net``, and a cap limits the absolute amount. A
    ``per_document`` threshold is not applied to a negative net: it was tested
    on the document being corrected, and the size of the correction says
    nothing about whether that document was above it. A ``per_payee_year``
    threshold holds the figure whatever the sign. Conditions about the buyer
    and the value of the work describe the contract, not the document, and
    apply to a credit note as they do to an invoice. A zero net gives a zero
    ``value`` for every selected kind that has a row, with no condition tested.

    Args:
        inp: The document: amounts, date, currency and the person's choices.
        rows: The statutory rows to compute from, usually
            :func:`app.core.payment_taxes.tables.rows_for` of the country.
            Rows of other countries are ignored.

    Returns:
        The five figures. Check :attr:`PaymentTaxResult.complete` before
        drawing a total from them.

    Raises:
        TypeError: An amount or rate is not a ``Decimal``.
        ValueError: An amount is not finite, the VAT rate is negative, a choice
            has an unknown state, or an override names no figure.
    """
    overrides = _check_input(inp)
    currency = _currency(inp.currency)
    if currency not in CURRENCIES:
        # The quantum helper answers two decimals for a code it does not know.
        # Rounding a forint or a dinar amount to cents on that guess would be
        # wrong without looking wrong, so nothing is computed at all.
        held = [
            _figure(kind, "held", reason_key="currency_unknown", params={"currency": inp.currency or ""})
            for kind in FIGURE_KINDS
        ]
        return PaymentTaxResult(*held)

    run = _Run(inp=inp, rows=rows, currency=currency, quantum=money_quantum(currency), overrides=overrides)
    vat = _vat_computed(run)
    withheld = _row_figure(run, "vat_withheld", "vat_withholding", inp.vat_withholding, vat)
    return PaymentTaxResult(
        vat_computed=vat,
        vat_withheld=withheld,
        vat_payable=_vat_payable(run, vat, withheld),
        income_withheld=_row_figure(run, "income_withheld", "income_withholding", inp.income_withholding, vat),
        stamp_duty=_row_figure(run, "stamp_duty", "stamp_duty", inp.stamp_duty, vat),
    )


def allocate(total: Decimal, weights: Sequence[Decimal], currency: str) -> list[Decimal]:
    """Split a rounded total across weights so that the parts sum to it exactly.

    Figures are computed once per document, or per group of lines sharing a
    VAT rate and a withholding code. The values printed against each line come
    from here, so a column of lines always adds up to the figure at its foot.
    Rounding each line on its own does not: a hundred lines of 0.005 would
    print a column of 1.00 under a total of 0.50.

    The method is largest remainder. Each share is taken down to the unit
    below it, and the units the column is then short go one each to the rows
    that lost the most, ties in row order. A weight of zero has an exact share
    of zero and loses nothing, so it never receives a spare unit. A negative
    weight, a credit line among the lines, takes a negative share like any
    other row. A negative total is split as its absolute value and negated, so
    the lines of a credit note mirror the lines of the document it reverses.

    Args:
        total: The amount to split, already on the quantum of the currency.
        weights: One weight per line, usually the line net amounts.
        currency: ISO 4217 code deciding the size of one unit.

    Returns:
        One amount per weight, each on the quantum, summing to ``total``.

    Raises:
        TypeError: ``total`` or a weight is not a ``Decimal``.
        ValueError: The currency is unknown, the total is finer than the
            quantum, or the total is not zero while the weights sum to zero.
            There is no honest split in that last case: an even split or the
            first row would print an amount against a line that did not earn it.
    """
    _require_decimal(total, "total")
    for weight in weights:
        _require_decimal(weight, "weight")
    code = _currency(currency)
    if code not in CURRENCIES:
        raise ValueError(f"unknown currency {currency!r}: the size of one unit cannot be guessed")
    quantum = money_quantum(code)
    if total != total.quantize(quantum, rounding=ROUND_HALF_UP, context=_EXACT):
        raise ValueError(f"total {total} is finer than the {code} quantum {quantum}")

    zero = _ZERO.quantize(quantum)
    if total == 0:
        return [zero for _ in weights]
    weight_sum = sum(weights, _ZERO)
    if weight_sum == 0:
        raise ValueError(f"weights sum to zero, so a total of {total} cannot be shared between them")

    magnitude = abs(total).quantize(quantum)
    exact = [_EXACT.divide(_EXACT.multiply(magnitude, weight), weight_sum) for weight in weights]
    floors = [share.quantize(quantum, rounding=ROUND_FLOOR, context=_EXACT) for share in exact]
    short = int((magnitude - sum(floors, _ZERO)) / quantum)
    parts = list(floors)
    # Largest rounding loss first, then row order, so the result is stable.
    for index in sorted(range(len(exact)), key=lambda i: (-_EXACT.subtract(exact[i], floors[i]), i))[:short]:
        parts[index] += quantum
    if total < 0:
        parts = [-part for part in parts]
    return [part if part else abs(part) for part in parts]
