# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding service - what is deducted, at what rate, from what base.

Three decisions live here and nowhere else.

**The base.** ``taxable_base = gross - materials - VAT``, with each subtraction
made only where the scheme makes it. The UK scheme deducts on labour and takes
both away; section 48 EStG deducts from the Gegenleistung and takes neither.
Deducting on the gross where materials should have come out over-withholds on
every payment where a subcontractor supplied any, month after month, and the
subcontractor only sees it back at the end of their tax year. That is why the
subtraction is driven by a column on the scheme rather than by a constant.

**The band.** A reduced or zero rate is something a party is verified for, and
a verification runs out. When it has, the party falls to the scheme's default
band, which is always the highest one. Real life makes that drop silently; here
it is a named decision with a reason attached, so the figure can be explained.

**The rounding.** Money is quantised to two decimal places, half away from
zero, once, at the end. Rounding a rate or an intermediate would put the answer
a cent away from the one the authority computes.

Everything above is a plain function over plain values, so the arithmetic that
decides how much money leaves the business is testable without a database.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_registry import CURRENCIES, money_quantum
from app.core.payment_taxes import (
    Choice,
    Figure,
    Override,
    PaymentTaxInput,
    PaymentTaxResult,
    RateRow,
    compute_payment_taxes,
    lookup,
    rows_for,
)
from app.core.payment_taxes.tables import OverlappingRowsError
from app.modules.tax_withholding import repository
from app.modules.tax_withholding.data import WITHHOLDING_REGIMES
from app.modules.tax_withholding.models import (
    STATUTORY_CALC_STATUSES,
    STATUTORY_CHOICE_STATES,
    STATUTORY_DIRECTIONS,
    STATUTORY_LINE_KINDS,
    STATUTORY_SOURCE_KINDS,
    PartyTaxStatus,
    ReverseChargeDetermination,
    StatutoryTaxCalc,
    StatutoryTaxLine,
    WithholdingDeduction,
    WithholdingRegime,
)
from app.modules.tax_withholding.source_owners import source_belongs_to_project

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
_CENTS = Decimal("0.01")
_HUNDRED = Decimal("100")


def to_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    """Read a money-or-rate value from whatever shape it arrived in.

    Strings are the wire format for money in this platform, so a string is the
    expected input, not the fallback. A value that cannot be read at all
    becomes ``default`` rather than raising: a validation rule reporting "this
    figure does not add up" is more use than a 500 from a report.
    """
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    return parsed if parsed.is_finite() else default


def quantise(value: Decimal) -> Decimal:
    """Two decimal places, half away from zero - the way a tax figure rounds."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def compute_taxable_base(
    gross: Decimal,
    materials: Decimal,
    vat: Decimal,
    *,
    materials_excluded: bool = True,
    vat_excluded: bool = True,
) -> Decimal:
    """The figure the rate is applied to.

    Never negative: materials booked higher than the gross is a data error, and
    a negative base would turn a deduction into a payment to the subcontractor.
    The rules report it; the arithmetic floors it at zero rather than
    propagating an amount nobody could remit.
    """
    base = gross
    if materials_excluded:
        base -= materials
    if vat_excluded:
        base -= vat
    return quantise(base if base > ZERO else ZERO)


def compute_tax_withheld(base: Decimal, rate_pct: Decimal) -> Decimal:
    """Tax withheld from ``base`` at ``rate_pct`` percent."""
    if base <= ZERO or rate_pct <= ZERO:
        return ZERO
    return quantise(base * rate_pct / _HUNDRED)


# ── Bands and verification ───────────────────────────────────────────────────


@dataclass
class BandDecision:
    """Which band was applied, at what rate, and why it is not another one."""

    band_code: str
    rate_pct: Decimal
    requires_verification: bool = False
    downgraded_from: str = ""
    reasons: list[str] = field(default_factory=list)


def bands_of(regime: WithholdingRegime | dict[str, Any] | None) -> list[dict[str, Any]]:
    """The scheme's rate table as a list of dicts, whatever shape it came in."""
    if regime is None:
        return []
    raw = regime.get("bands") if isinstance(regime, dict) else regime.bands
    if not isinstance(raw, list):
        return []
    return [band for band in raw if isinstance(band, dict)]


def find_band(regime: WithholdingRegime | dict[str, Any] | None, band_code: str) -> dict[str, Any] | None:
    """One band of a scheme by code, or ``None`` when the scheme has no such band."""
    if not band_code:
        return None
    for band in bands_of(regime):
        if str(band.get("code") or "") == band_code:
            return band
    return None


def verification_is_current(status: PartyTaxStatus | None, as_of: date) -> bool:
    """Whether ``status`` evidences a verification that still holds on ``as_of``.

    Four things have to be true at once, and each of them is a way this fails
    in practice: the standing exists, it has not been revoked, the window it
    covers contains the date, and there is a reference to the authority's own
    answer. A standing marked active with no reference is somebody's intention,
    not a verification.
    """
    if status is None:
        return False
    if status.status in {"revoked", "expired"}:
        return False
    if not (status.verification_reference or "").strip():
        return False
    if status.valid_from and status.valid_from > as_of:
        return False
    return not (status.valid_to is not None and status.valid_to < as_of)


def resolve_band(
    regime: WithholdingRegime,
    *,
    requested_band: str = "",
    party_status: PartyTaxStatus | None = None,
    as_of: date | None = None,
) -> BandDecision:
    """Decide the band a payment is deducted at.

    The order is explicit request, then the party's recorded standing, then the
    scheme default. Whatever comes out of that, a band that requires
    verification is only kept if the verification is current on ``as_of``;
    otherwise the party drops to the scheme default, which is the highest-rate
    band, and the drop is reported rather than merely applied.
    """
    on_date = as_of or date.today()
    reasons: list[str] = []

    wanted = requested_band or (party_status.band_code if party_status else "") or regime.default_band_code
    band = find_band(regime, wanted)
    if band is None:
        available = bands_of(regime)
        fallback = find_band(regime, regime.default_band_code) or (available[-1] if available else None)
        if fallback is None:
            reasons.append(f"Scheme {regime.scheme_code} defines no rate bands, so no rate could be applied.")
            return BandDecision(band_code=wanted, rate_pct=ZERO, reasons=reasons)
        if wanted:
            reasons.append(
                f"Band '{wanted}' is not defined by scheme {regime.scheme_code}; "
                f"the scheme default '{fallback.get('code')}' was applied instead."
            )
        band = fallback
        wanted = str(band.get("code") or "")

    requires_verification = bool(band.get("requires_verification"))
    if requires_verification and not verification_is_current(party_status, on_date):
        default_band = find_band(regime, regime.default_band_code)
        if default_band is not None and str(default_band.get("code") or "") != wanted:
            if party_status is None:
                reasons.append(
                    f"Band '{wanted}' requires a verification and none is recorded for this party, "
                    f"so the higher band '{default_band.get('code')}' applies."
                )
            else:
                reasons.append(
                    f"The verification behind band '{wanted}' is not valid on {on_date.isoformat()}, "
                    f"so the higher band '{default_band.get('code')}' applies."
                )
            return BandDecision(
                band_code=str(default_band.get("code") or ""),
                rate_pct=to_decimal(default_band.get("rate_pct")),
                requires_verification=bool(default_band.get("requires_verification")),
                downgraded_from=wanted,
                reasons=reasons,
            )
        reasons.append(
            f"Band '{wanted}' requires a verification that is not valid on {on_date.isoformat()}, "
            "and the scheme names no higher band to fall back to."
        )

    return BandDecision(
        band_code=wanted,
        rate_pct=to_decimal(band.get("rate_pct")),
        requires_verification=requires_verification,
        reasons=reasons,
    )


@dataclass
class DeductionFigures:
    """A whole computed deduction: the base, the rate, the money, and the why."""

    band_code: str
    rate_pct: Decimal
    gross_amount: Decimal
    qualifying_materials: Decimal
    vat_amount: Decimal
    taxable_base: Decimal
    tax_withheld: Decimal
    net_payable: Decimal
    below_threshold: bool = False
    downgraded_from: str = ""
    reasons: list[str] = field(default_factory=list)


def compute_deduction(
    regime: WithholdingRegime,
    *,
    gross_amount: Decimal,
    currency_code: str,
    qualifying_materials: Decimal = ZERO,
    vat_amount: Decimal = ZERO,
    requested_band: str = "",
    party_status: PartyTaxStatus | None = None,
    as_of: date | None = None,
) -> DeductionFigures:
    """Work out one deduction from end to end.

    ``below_threshold`` is a flag and not a rate change on purpose. Where a
    scheme has an exemption limit it is normally an annual figure per payee -
    Germany's section 48 EStG limit is - and a single payment cannot tell
    whether the year is already over it. Reporting the possibility is honest;
    zeroing the deduction on one payment's evidence would not be.

    ``currency_code`` is the payment's currency and is required rather than
    defaulted, because the exemption limit is denominated in the scheme's
    currency and comparing across two of them is arithmetic on unlike units. A
    default would have made the wrong answer the quiet one.
    """
    decision = resolve_band(regime, requested_band=requested_band, party_status=party_status, as_of=as_of)
    base = compute_taxable_base(
        gross_amount,
        qualifying_materials,
        vat_amount,
        materials_excluded=regime.materials_excluded,
        vat_excluded=regime.vat_excluded,
    )
    withheld = compute_tax_withheld(base, decision.rate_pct)
    threshold = regime.threshold_amount
    paid_in = (currency_code or "").strip().upper()
    scheme_currency = (regime.currency_code or "").strip().upper()
    same_currency = bool(paid_in) and paid_in == scheme_currency
    below = threshold is not None and same_currency and gross_amount <= to_decimal(threshold)
    reasons = list(decision.reasons)
    if below:
        reasons.append(
            f"This payment is at or below the scheme's exemption limit of "
            f"{to_decimal(threshold)} {regime.currency_code}. The limit normally applies to the "
            "payee's total for the year, so check the year to date before treating it as exempt."
        )
    elif threshold is not None and not same_currency:
        # The limit is a figure in the scheme's own currency. Holding it up
        # against a payment in another one compares two different units and
        # would answer with whichever way the exchange rate happened to fall.
        reasons.append(
            f"The scheme's exemption limit is {to_decimal(threshold)} {regime.currency_code} and this "
            f"payment is in {paid_in or 'a currency that was not stated'}, so the limit has not been "
            "applied. Convert at the rate for the payment date before deciding whether the payee is under it."
        )
    return DeductionFigures(
        band_code=decision.band_code,
        rate_pct=decision.rate_pct,
        gross_amount=quantise(gross_amount),
        qualifying_materials=quantise(qualifying_materials),
        vat_amount=quantise(vat_amount),
        taxable_base=base,
        tax_withheld=withheld,
        net_payable=quantise(gross_amount - withheld),
        below_threshold=below,
        downgraded_from=decision.downgraded_from,
        reasons=reasons,
    )


# ── Seeding ──────────────────────────────────────────────────────────────────


async def seed_regimes(session: AsyncSession) -> tuple[int, int, list[str]]:
    """Install the shipped schemes. Returns ``(created, existing, scheme_codes)``.

    Only fills gaps. A scheme already present is left exactly as it is, because
    an operator who edited a rate did so for a reason - a rate that changed
    mid-year, a ruling specific to their business - and an upgrade silently
    restoring the shipped figure would change what the next return says.
    """
    created = 0
    existing = 0
    codes: list[str] = []
    for shipped in WITHHOLDING_REGIMES:
        codes.append(str(shipped["scheme_code"]))
        found = await repository.get_regime_by_scheme(
            session,
            country_code=str(shipped["country_code"]),
            scheme_code=str(shipped["scheme_code"]),
        )
        if found is not None:
            existing += 1
            continue
        threshold = shipped.get("threshold_amount")
        await repository.add_regime(
            session,
            WithholdingRegime(
                country_code=str(shipped["country_code"]),
                scheme_code=str(shipped["scheme_code"]),
                scheme_name=str(shipped["scheme_name"]),
                legal_reference=str(shipped.get("legal_reference") or ""),
                authority=str(shipped.get("authority") or ""),
                currency_code=str(shipped["currency_code"]),
                bands=[dict(band) for band in shipped.get("bands", [])],
                default_band_code=str(shipped.get("default_band_code") or ""),
                materials_excluded=bool(shipped.get("materials_excluded", True)),
                vat_excluded=bool(shipped.get("vat_excluded", True)),
                verification_validity_months=int(shipped.get("verification_validity_months") or 0),
                threshold_amount=to_decimal(threshold) if threshold is not None else None,
                notes=str(shipped.get("notes") or ""),
                is_active=True,
            ),
        )
        created += 1
    logger.info("tax_withholding: seeded %d scheme(s), %d already present", created, existing)
    return created, existing, codes


# ── Persistence ──────────────────────────────────────────────────────────────


def apply_regime_body(regime: WithholdingRegime, body: Any) -> None:
    """Copy the writable fields of a validated scheme request onto the row."""
    regime.country_code = body.country_code
    regime.scheme_code = body.scheme_code
    regime.scheme_name = body.scheme_name
    regime.legal_reference = body.legal_reference
    regime.authority = body.authority
    regime.currency_code = body.currency_code
    regime.bands = [band.model_dump(mode="json") for band in body.bands]
    regime.default_band_code = body.default_band_code
    regime.materials_excluded = body.materials_excluded
    regime.vat_excluded = body.vat_excluded
    regime.verification_validity_months = body.verification_validity_months
    regime.threshold_amount = body.threshold_amount
    regime.notes = body.notes
    regime.is_active = body.is_active


def apply_party_status_body(row: PartyTaxStatus, body: Any) -> None:
    """Copy the writable fields of a validated standing request onto the row."""
    row.party_id = body.party_id
    row.party_type = body.party_type
    row.party_name = body.party_name
    row.regime_id = body.regime_id
    row.band_code = body.band_code
    row.verification_reference = body.verification_reference
    row.verified_on = body.verified_on
    row.valid_from = body.valid_from
    row.valid_to = body.valid_to
    row.evidence_document_id = body.evidence_document_id
    row.evidence_reference = body.evidence_reference
    row.status = body.status
    row.notes = body.notes


def apply_deduction_body(row: WithholdingDeduction, body: Any, figures: DeductionFigures) -> None:
    """Copy a validated deduction request onto the row, computing what was left out.

    ``taxable_base``, ``tax_withheld`` and ``rate_pct`` are taken from the
    request when it supplied them and from ``figures`` when it did not. A
    caller that supplies its own numbers keeps them - an imported deduction has
    already been decided by whatever filed it, and quietly recomputing it would
    replace a record of what happened with a claim about what should have.
    The validation rules then have something real to disagree with.
    """
    row.project_id = body.project_id
    row.regime_id = body.regime_id
    row.party_status_id = body.party_status_id
    row.party_id = body.party_id
    row.party_name = body.party_name
    row.payment_reference = body.payment_reference
    row.period_start = body.period_start
    row.period_end = body.period_end
    row.gross_amount = body.gross_amount
    row.qualifying_materials = body.qualifying_materials
    row.vat_amount = body.vat_amount
    row.taxable_base = body.taxable_base if body.taxable_base is not None else figures.taxable_base
    row.rate_pct = body.rate_pct if body.rate_pct is not None else figures.rate_pct
    row.tax_withheld = body.tax_withheld if body.tax_withheld is not None else figures.tax_withheld
    row.band_code = body.band_code or figures.band_code
    row.currency_code = body.currency_code
    row.status = body.status
    row.remitted_at = body.remitted_at
    row.return_reference = body.return_reference
    row.notes = body.notes


def apply_determination_body(row: ReverseChargeDetermination, body: Any) -> None:
    """Copy the writable fields of a validated determination onto the row."""
    row.project_id = body.project_id
    row.invoice_id = body.invoice_id
    row.invoice_reference = body.invoice_reference
    row.country_code = body.country_code
    row.rule_code = body.rule_code
    row.buyer_accounts_for_vat = body.buyer_accounts_for_vat
    row.legal_reference = body.legal_reference
    row.invoice_wording = body.invoice_wording
    row.net_amount = body.net_amount
    row.vat_amount = body.vat_amount
    row.currency_code = body.currency_code
    row.status = body.status
    row.notes = body.notes


# ── Validation payloads ──────────────────────────────────────────────────────
#
# The rules run on a plain dict rather than on ORM instances so they can be
# exercised without a database, and so a figure arriving from an import can be
# checked before anything is stored.


def deduction_payload(
    body: Any,
    *,
    regime: WithholdingRegime | None,
    party_status: PartyTaxStatus | None,
    figures: DeductionFigures | None = None,
) -> dict[str, Any]:
    """The dict the deduction rules read. See :mod:`.validators` for the contract."""
    base = body.taxable_base if body.taxable_base is not None else (figures.taxable_base if figures else None)
    withheld = body.tax_withheld if body.tax_withheld is not None else (figures.tax_withheld if figures else None)
    rate = body.rate_pct if body.rate_pct is not None else (figures.rate_pct if figures else None)
    band_code = body.band_code or (figures.band_code if figures else "")
    payload: dict[str, Any] = {
        "record_type": "deduction",
        "gross_amount": body.gross_amount,
        "qualifying_materials": body.qualifying_materials,
        "vat_amount": body.vat_amount,
        "taxable_base": base if base is not None else ZERO,
        "tax_withheld": withheld if withheld is not None else ZERO,
        "rate_pct": rate if rate is not None else ZERO,
        "band_code": band_code,
        "currency_code": body.currency_code,
        "period_start": body.period_start,
        "period_end": body.period_end,
        "payment_reference": body.payment_reference,
    }
    if regime is not None:
        payload["regime"] = {
            "scheme_code": regime.scheme_code,
            "country_code": regime.country_code,
            "currency_code": regime.currency_code,
            "materials_excluded": regime.materials_excluded,
            "vat_excluded": regime.vat_excluded,
            "default_band_code": regime.default_band_code,
            "bands": bands_of(regime),
        }
    if party_status is not None:
        payload["party_status"] = {
            "band_code": party_status.band_code,
            "verification_reference": party_status.verification_reference,
            "valid_from": party_status.valid_from,
            "valid_to": party_status.valid_to,
            "status": party_status.status,
        }
    return payload


def determination_payload(body: Any) -> dict[str, Any]:
    """The dict the reverse-charge rules read."""
    return {
        "record_type": "reverse_charge",
        "buyer_accounts_for_vat": body.buyer_accounts_for_vat,
        "invoice_reference": body.invoice_reference,
        "country_code": body.country_code,
        "rule_code": body.rule_code,
        "legal_reference": body.legal_reference,
        "invoice_wording": body.invoice_wording,
        "net_amount": body.net_amount,
        "vat_amount": body.vat_amount,
        "currency_code": body.currency_code,
        "status": body.status,
    }


# ── Reads that need more than one table ──────────────────────────────────────


async def load_deduction_context(
    session: AsyncSession,
    *,
    regime_id: uuid.UUID,
    party_status_id: uuid.UUID | None,
) -> tuple[WithholdingRegime | None, PartyTaxStatus | None]:
    """The scheme and the party standing a deduction is judged against."""
    regime = await repository.get_regime(session, regime_id)
    party_status = None
    if party_status_id is not None:
        party_status = await repository.get_party_status(session, party_status_id)
    return regime, party_status


def expiry_view(status: PartyTaxStatus, as_of: date) -> tuple[bool, int | None]:
    """``(is_expired, days_to_expiry)`` for one standing on one date.

    Computed on read and never stored. A stored expiry flag is only as fresh as
    the last job that wrote it, and an expiry nobody noticed is the entire
    failure this module is here to prevent.

    A standing is expired when the calendar says so or when the record does, and
    the two are separate evidence pointing the same way. The calendar overrides
    a record still reading "active", because nobody goes back to edit a row on
    the day it lapses. The record overrides an open window, because a standing
    marked expired with no end date has no calendar to consult at all, and
    answering "not expired" there contradicts ``verification_is_current``, which
    already refuses that row. There is no countdown in that case, since the date
    it would count to is the date that is missing. Revocation is deliberately
    not folded in here: a revoked standing is refused all the same, but calling
    it expired would put the wrong word on the screen for it.
    """
    if status.status == "expired":
        return True, None
    if status.valid_to is None:
        return False, None
    delta = (status.valid_to - as_of).days
    return delta < 0, delta


# ── Statutory tax lines on a payment document ────────────────────────────────
#
# Everything above this line is the party-and-band scheme (CIS, RCT, section
# 48). What follows stores the taxes of one payment document: computed VAT, the
# share of it the buyer withholds, the VAT left payable, income tax withheld
# and stamp duty.
#
# **This module does not compute them.** The calculation is
# :func:`app.core.payment_taxes.compute_payment_taxes`, shared with the payment
# certificate and the e-invoice so the three cannot disagree. What lives here
# is where the choice a person makes and the figures that follow from it are
# stored, confirmed by a person, and read back.
#
# **Nothing here turns unknown into zero.** ``to_decimal`` above answers zero
# for a value it cannot read, and ``resolve_band`` answers the default band for
# a band it cannot find. Both are deliberate for the scheme code and both are
# wrong for a tax line somebody signs, so neither is used below: an amount that
# is not known is ``None`` in memory and NULL in the table, and a value that
# cannot be stored exactly is refused rather than rounded.
#
# **Confirmed means frozen.** A draft is recomputed on every save. A confirmed
# set is answered from its stored rows and nothing else, so a correction to a
# rate table next year does not rewrite a document signed this year. Changing
# it takes a reopening, with a reason, which is written to the audit log.

#: Hands out the statutory rows of one country. Injected wherever a
#: calculation runs so that tests compute from rows they build themselves: a
#: test that breaks when an accountant corrects a shipped rate is testing the
#: wrong thing.
RowSource = Callable[[str], Sequence[RateRow]]

#: The row kind behind each figure that is computed from a rate row. The
#: payable VAT repeats the basis of the withheld VAT it is derived from.
FIGURE_ROW_KINDS: dict[str, str] = {
    "vat_withheld": "vat_withholding",
    "vat_payable": "vat_withholding",
    "income_withheld": "income_withholding",
    "stamp_duty": "stamp_duty",
}

#: The figure each of a person's three choices is stored on.
CHOICE_FIGURES: dict[str, str] = {
    "vat_withholding": "vat_withheld",
    "income_withholding": "income_withheld",
    "stamp_duty": "stamp_duty",
}

#: Figures a person may replace with their own amount. The payable VAT is not
#: one of them: it is a subtraction, and it changes by changing the withheld
#: VAT it is derived from.
OVERRIDABLE_KINDS: tuple[str, ...] = ("vat_computed", "vat_withheld", "income_withheld", "stamp_duty")

#: Reasons that mean a threshold could not be judged from this document.
THRESHOLD_UNEVALUATED_REASONS: tuple[str, ...] = (
    "threshold_currency_mismatch",
    "threshold_needs_year_total",
    "cap_currency_mismatch",
)

_AMOUNT_SCALE = 4
_AMOUNT_INTEGER_DIGITS = 14
_RATE_SCALE = 6
_RATE_INTEGER_DIGITS = 6

STATUTORY_ENTITY = "tax_withholding_statutory"


class StatutoryRefusal(Exception):
    """A request about statutory tax lines that is refused, with the reason.

    Attributes:
        code: Machine key the screen translates.
        message: English sentence shown where no translation exists yet.
        http_status: The status the router answers with.
        details: Values for the translated message.
        findings: Validation findings behind the refusal, if any.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 409,
        details: dict[str, Any] | None = None,
        findings: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}
        self.findings = findings or []


class StatutoryDataError(RuntimeError):
    """Stored statutory tax lines that cannot be read back as a calculation.

    Raised instead of patching the gap. A missing line read as "nothing
    withheld" would be the zero this module exists to keep off a tax document.
    """


@dataclass(frozen=True)
class StatutoryInputs:
    """What one calculation is computed from, as plain values.

    Attributes:
        country_code: Jurisdiction whose rows apply.
        currency_code: Currency of the document.
        document_date: The date the document is taxed on.
        net_amount: Amount before VAT. Negative on a credit note.
        vat_rate_pct: VAT rate in percent, supplied by the caller. ``None``
            means unknown and holds every VAT figure.
        buyer_is_designated: Whether the buyer is one the law designates to
            withhold. ``None`` means nobody has said.
        work_value_incl_vat: Value of the whole work, VAT included. ``None``
            means unknown.
        work_value_note: The person's own description of what that value is
            the value of. Stored, never interpreted.
        stamp_duty_base: The amount stamp duty is charged on, when it differs
            from the net amount.
        stamp_duty_base_same_as_net: A person's statement that stamp duty is
            charged on the net amount. With neither this nor a base, a
            selected stamp duty is held.
        vat_withholding: The person's choice for the VAT withholding.
        income_withholding: The person's choice for the income tax withholding.
        stamp_duty: The person's choice for the stamp duty.
    """

    country_code: str
    currency_code: str
    document_date: date
    net_amount: Decimal
    vat_rate_pct: Decimal | None
    buyer_is_designated: bool | None = None
    work_value_incl_vat: Decimal | None = None
    work_value_note: str = ""
    stamp_duty_base: Decimal | None = None
    stamp_duty_base_same_as_net: bool = False
    vat_withholding: Choice = Choice("unset")
    income_withholding: Choice = Choice("unset")
    stamp_duty: Choice = Choice("unset")


@dataclass(frozen=True)
class StoredOverride:
    """An amount a person entered for one figure, with who and when."""

    amount: Decimal
    reason: str
    by: uuid.UUID | None
    at: datetime | None


#: The certificate tax registry of ``contracts``, imported by name and only
#: when it is needed, so this module loads on an install without it.
_CERTIFICATE_REGISTRY = "app.modules.contracts.certificate_taxes"


def shipped_rows(country: str) -> Sequence[RateRow]:
    """The statutory rows that ship for one country: the default row source."""
    return rows_for(country)


# ── Exact values in, exact values out ────────────────────────────────────────


def currency_quantum(currency_code: str) -> Decimal | None:
    """The smallest amount a currency can express, or ``None`` when it is unknown.

    ``None`` rather than a guess. The registry helper answers two decimals for
    a code it does not know, and rounding to cents on that guess is wrong
    without looking wrong.
    """
    code = (currency_code or "").strip().upper()
    return money_quantum(code) if code in CURRENCIES else None


def _is_exact_at(value: Decimal, quantum: Decimal) -> bool:
    try:
        return value == value.quantize(quantum)
    except InvalidOperation:
        return False


def _fits_column(value: Decimal, *, scale: int, integer_digits: int) -> bool:
    """Whether the database can hold ``value`` without rounding or overflow."""
    if not value.is_finite():
        return False
    if abs(value) >= Decimal(10) ** integer_digits:
        return False
    return _is_exact_at(value, Decimal(1).scaleb(-scale))


def plain_decimal(value: Decimal) -> Decimal:
    """The same number without padding zeros and without an exponent."""
    normal = value.normalize()
    exponent = normal.as_tuple().exponent
    return normal.quantize(Decimal(1)) if isinstance(exponent, int) and exponent > 0 else normal


def money_as_stored(value: Decimal | None, currency_code: str) -> Decimal | None:
    """Put an amount read from the table back on the precision of its currency.

    The column keeps four decimals for every currency, so a lira amount comes
    back as ``8000.0000`` and a yen amount would print decimals a yen does not
    have. ``None`` stays ``None``.

    Raises:
        StatutoryDataError: The stored amount is finer than the currency can
            express. Rounding it here would print an amount nobody stored.
    """
    if value is None:
        return None
    quantum = currency_quantum(currency_code)
    if quantum is None:
        return plain_decimal(value)
    if not _is_exact_at(value, quantum):
        raise StatutoryDataError(
            f"stored amount {value} is finer than {currency_code} can express; it is not rounded on read"
        )
    return value.quantize(quantum)


def _require_storable(value: Decimal | None, name: str, currency_code: str) -> None:
    """Refuse an amount that would not come back from the table as it went in."""
    if value is None:
        return
    if not _fits_column(value, scale=_AMOUNT_SCALE, integer_digits=_AMOUNT_INTEGER_DIGITS):
        raise StatutoryRefusal(
            "amount_not_storable",
            f"{name} of {value} cannot be stored exactly.",
            http_status=422,
            details={"field": name, "value": str(value)},
        )
    quantum = currency_quantum(currency_code)
    if quantum is not None and not _is_exact_at(value, quantum):
        raise StatutoryRefusal(
            "amount_finer_than_currency",
            f"{name} of {value} is finer than {currency_code} can express. Enter the amount as the document shows it.",
            http_status=422,
            details={"field": name, "value": str(value), "currency_code": currency_code},
        )


def _require_storable_rate(value: Decimal | None, name: str) -> None:
    if value is None:
        return
    if not _fits_column(value, scale=_RATE_SCALE, integer_digits=_RATE_INTEGER_DIGITS):
        raise StatutoryRefusal(
            "rate_not_storable",
            f"{name} of {value} cannot be stored exactly.",
            http_status=422,
            details={"field": name, "value": str(value)},
        )


def check_statutory_inputs(inputs: StatutoryInputs) -> None:
    """Refuse inputs that could not be stored and read back unchanged.

    Raises:
        StatutoryRefusal: An amount is finer than its currency, or a value
            exceeds what the table holds exactly.
    """
    _require_storable(inputs.net_amount, "net_amount", inputs.currency_code)
    _require_storable(inputs.work_value_incl_vat, "work_value_incl_vat", inputs.currency_code)
    _require_storable(inputs.stamp_duty_base, "stamp_duty_base", inputs.currency_code)
    _require_storable_rate(inputs.vat_rate_pct, "vat_rate_pct")
    if inputs.stamp_duty_base is not None and inputs.stamp_duty_base_same_as_net:
        raise StatutoryRefusal(
            "stamp_duty_base_contradiction",
            "A stamp duty base was entered and the base was also stated to be the net amount. State one of the two.",
            http_status=422,
        )


# ── From inputs to figures, and from figures to rows ─────────────────────────


def build_tax_input(
    inputs: StatutoryInputs,
    overrides: Mapping[str, StoredOverride] | None = None,
) -> PaymentTaxInput:
    """The shared calculation's input for one document.

    Every stored input is passed on, including the two the buyer conditions
    read. None of them is defaulted here: ``None`` reaches the calculation as
    ``None`` and comes back as a held figure.
    """
    return PaymentTaxInput(
        country_code=inputs.country_code,
        currency=inputs.currency_code,
        on=inputs.document_date,
        net_amount=inputs.net_amount,
        vat_rate_pct=inputs.vat_rate_pct,
        vat_withholding=inputs.vat_withholding,
        income_withholding=inputs.income_withholding,
        stamp_duty=inputs.stamp_duty,
        overrides={
            kind: Override(amount=entry.amount, reason=entry.reason, by=str(entry.by) if entry.by else "")
            for kind, entry in (overrides or {}).items()
        },
        buyer_is_designated=inputs.buyer_is_designated,
        work_value_incl_vat=inputs.work_value_incl_vat,
    )


def compute_statutory(
    inputs: StatutoryInputs,
    rows: Sequence[RateRow],
    overrides: Mapping[str, StoredOverride] | None = None,
) -> PaymentTaxResult:
    """The five figures of one document, every one from the shared calculation.

    The shared calculation takes one net amount per call, and stamp duty is
    charged on a base of its own. So a selected stamp duty is computed by a
    second call on that base, unless a person has stated that the base is the
    net amount. With neither a base nor that statement the stamp duty figure
    is held for ``stamp_duty_base_unknown``: the VAT base is never reused for
    it in silence. No arithmetic happens here, only the choice of which call a
    figure is taken from.

    Args:
        inputs: The document and the person's choices.
        rows: The statutory rows to compute from.
        overrides: Amounts a person entered, keyed by figure kind.

    Returns:
        The result of the shared calculation, with the stamp duty figure taken
        from the call made on its own base.

    Raises:
        StatutoryRefusal: An input could not be stored exactly, so the result
            would show a figure that saving it could not reproduce.
    """
    check_statutory_inputs(inputs)
    entered = dict(overrides or {})
    own_base = inputs.stamp_duty.state == "selected" and not inputs.stamp_duty_base_same_as_net
    if not own_base:
        return compute_payment_taxes(build_tax_input(inputs, entered), rows)

    others = {kind: entry for kind, entry in entered.items() if kind != "stamp_duty"}
    result = compute_payment_taxes(build_tax_input(inputs, others), rows)
    if inputs.stamp_duty_base is None:
        waiting = Figure(
            kind="stamp_duty",
            status="held",
            amount=None,
            base=None,
            rate_pct=None,
            numerator=None,
            denominator=None,
            code=(inputs.stamp_duty.code or "").strip(),
            legal_reference="",
            effective_from=None,
            review_status="",
            overridden=False,
            reason_key="stamp_duty_base_unknown",
            reason_params={},
        )
        return replace(result, stamp_duty=waiting)
    on_its_base = replace(
        inputs,
        net_amount=inputs.stamp_duty_base,
        vat_withholding=Choice("unset"),
        income_withholding=Choice("unset"),
    )
    only_stamp = {kind: entry for kind, entry in entered.items() if kind == "stamp_duty"}
    second = compute_payment_taxes(build_tax_input(on_its_base, only_stamp), rows)
    return replace(result, stamp_duty=second.stamp_duty)


def preview_statutory(inputs: StatutoryInputs, rows: Sequence[RateRow]) -> PaymentTaxResult:
    """Compute the five figures of a document without storing anything.

    Args:
        inputs: The document and the person's choices.
        rows: The statutory rows to compute from.

    Returns:
        What :func:`compute_statutory` answers, with no amount entered by hand.

    Raises:
        StatutoryRefusal: An input could not be stored exactly, so the preview
            would show a figure that saving it could not reproduce.
    """
    return compute_statutory(inputs, rows)


def row_behind(figure: Figure, inputs: StatutoryInputs, rows: Sequence[RateRow]) -> RateRow | None:
    """The rate row a figure was computed from, or ``None`` when no row was used.

    The figure carries the article and the start date of its row but not the
    end date or the source address, and the screen shows both.
    """
    row_kind = FIGURE_ROW_KINDS.get(figure.kind)
    if row_kind is None or figure.effective_from is None or not figure.code:
        return None
    try:
        row = lookup(rows, country=inputs.country_code, kind=row_kind, code=figure.code, on=inputs.document_date)
    except OverlappingRowsError:
        return None
    if row is None or row.effective_from != figure.effective_from:
        return None
    return row


def line_values(figure: Figure, inputs: StatutoryInputs, rows: Sequence[RateRow]) -> dict[str, Any]:
    """The column values that store one figure.

    One key per column a figure fills. An amount is stored only for a
    ``value`` figure; held and not applicable stay ``None``.

    Raises:
        StatutoryDataError: The figure contradicts itself (a value without an
            amount, or an amount on a figure that is not a value).
        StatutoryRefusal: A number in the figure cannot be stored exactly.
    """
    if figure.kind not in STATUTORY_LINE_KINDS:
        raise StatutoryDataError(f"the calculation returned an unknown figure kind {figure.kind!r}")
    if figure.status not in STATUTORY_CALC_STATUSES:
        raise StatutoryDataError(f"figure {figure.kind} has an unknown status {figure.status!r}")
    if (figure.status == "value") != (figure.amount is not None):
        raise StatutoryDataError(f"figure {figure.kind} is {figure.status} but its amount is {figure.amount!r}")
    _require_storable(figure.amount, f"{figure.kind} amount", inputs.currency_code)
    _require_storable(figure.base, f"{figure.kind} base", inputs.currency_code)
    _require_storable_rate(figure.rate_pct, f"{figure.kind} rate")
    row = row_behind(figure, inputs, rows)
    return {
        "kind": figure.kind,
        "calc_status": figure.status,
        "tax_amount": figure.amount,
        "base_amount": figure.base,
        "rate_pct": figure.rate_pct,
        "numerator": figure.numerator,
        "denominator": figure.denominator,
        "code": figure.code,
        "currency_code": inputs.currency_code,
        "legal_reference": figure.legal_reference,
        "source_url": row.source_url if row is not None else "",
        "rate_effective_from": figure.effective_from,
        "rate_effective_to": row.effective_to if row is not None else None,
        "review_status": figure.review_status,
        "overridden": figure.overridden,
        "reason_key": figure.reason_key,
        "reason_params": {str(key): str(value) for key, value in dict(figure.reason_params).items()},
    }


def result_line_values(
    result: PaymentTaxResult,
    inputs: StatutoryInputs,
    rows: Sequence[RateRow],
) -> list[dict[str, Any]]:
    """The five figures of a result as column values, in printed order."""
    return [line_values(figure, inputs, rows) for figure in result.figures()]


def stored_line_values(line: StatutoryTaxLine) -> dict[str, Any]:
    """One stored line as plain values, amounts back on the currency's precision."""
    currency = line.currency_code
    return {
        "kind": line.kind,
        "calc_status": line.calc_status,
        "tax_amount": money_as_stored(line.tax_amount, currency),
        "base_amount": money_as_stored(line.base_amount, currency),
        "rate_pct": plain_decimal(line.rate_pct) if line.rate_pct is not None else None,
        "numerator": line.numerator,
        "denominator": line.denominator,
        "code": line.code or "",
        "currency_code": currency,
        "legal_reference": line.legal_reference or "",
        "source_url": line.source_url or "",
        "rate_effective_from": line.rate_effective_from,
        "rate_effective_to": line.rate_effective_to,
        "review_status": line.review_status or "",
        "overridden": bool(line.overridden),
        "reason_key": line.reason_key or "",
        "reason_params": dict(line.reason_params or {}),
        "choice_state": line.choice_state or "",
        "choice_code": line.choice_code or "",
        "choice_reason": line.choice_reason or "",
        "override_amount": money_as_stored(line.override_amount, currency),
        "override_reason": line.override_reason or "",
        "overridden_by": line.overridden_by,
        "overridden_at": line.overridden_at,
    }


def figure_from_values(values: Mapping[str, Any]) -> Figure:
    """Rebuild the figure a line was stored from."""
    return Figure(
        kind=values["kind"],
        status=values["calc_status"],
        amount=values["tax_amount"],
        base=values["base_amount"],
        rate_pct=values["rate_pct"],
        numerator=values["numerator"],
        denominator=values["denominator"],
        code=values["code"],
        legal_reference=values["legal_reference"],
        effective_from=values["rate_effective_from"],
        review_status=values["review_status"],
        overridden=values["overridden"],
        reason_key=values["reason_key"],
        reason_params=dict(values["reason_params"]),
    )


def result_from_lines(lines: Sequence[StatutoryTaxLine]) -> PaymentTaxResult:
    """Rebuild the result of a calculation from its stored lines, exactly.

    No calculation runs and no rate row is read: this is what lets a confirmed
    document keep its figures when the rate tables change.

    Raises:
        StatutoryDataError: A line is missing, duplicated, or carries an
            amount on a status that has none. Nothing is filled in.
    """
    by_kind: dict[str, Figure] = {}
    for line in lines:
        if line.kind in by_kind:
            raise StatutoryDataError(f"two stored lines of kind {line.kind!r} on one document")
        figure = figure_from_values(stored_line_values(line))
        if (figure.status == "value") != (figure.amount is not None):
            raise StatutoryDataError(f"stored line {line.kind} is {figure.status} but its amount is {figure.amount!r}")
        by_kind[line.kind] = figure
    missing = [kind for kind in STATUTORY_LINE_KINDS if kind not in by_kind]
    if missing:
        raise StatutoryDataError(f"stored statutory lines are incomplete, missing {missing}")
    return PaymentTaxResult(
        vat_computed=by_kind["vat_computed"],
        vat_withheld=by_kind["vat_withheld"],
        vat_payable=by_kind["vat_payable"],
        income_withheld=by_kind["income_withheld"],
        stamp_duty=by_kind["stamp_duty"],
    )


def inputs_from_stored(calc: StatutoryTaxCalc, lines: Sequence[StatutoryTaxLine]) -> StatutoryInputs:
    """The inputs a stored calculation was computed from."""
    by_kind = {line.kind: line for line in lines}
    choices: dict[str, Choice] = {}
    for field_name, figure_kind in CHOICE_FIGURES.items():
        line = by_kind.get(figure_kind)
        if line is None or line.choice_state not in STATUTORY_CHOICE_STATES:
            raise StatutoryDataError(f"the stored choice for {field_name} cannot be read")
        choices[field_name] = Choice(
            state=line.choice_state, code=line.choice_code or "", reason=line.choice_reason or ""
        )  # type: ignore[arg-type]
    net = money_as_stored(calc.net_amount, calc.currency_code)
    if net is None:
        raise StatutoryDataError("the stored net amount is missing")
    return StatutoryInputs(
        country_code=calc.country_code,
        currency_code=calc.currency_code,
        document_date=calc.document_date,
        net_amount=net,
        vat_rate_pct=plain_decimal(calc.vat_rate_pct) if calc.vat_rate_pct is not None else None,
        buyer_is_designated=calc.buyer_is_designated,
        work_value_incl_vat=money_as_stored(calc.work_value_incl_vat, calc.currency_code),
        work_value_note=calc.work_value_note or "",
        stamp_duty_base=money_as_stored(calc.stamp_duty_base, calc.currency_code),
        stamp_duty_base_same_as_net=bool(calc.stamp_duty_base_same_as_net),
        **choices,
    )


def overrides_from_stored(lines: Sequence[StatutoryTaxLine]) -> dict[str, StoredOverride]:
    """The amounts a person entered, keyed by figure kind."""
    found: dict[str, StoredOverride] = {}
    for line in lines:
        amount = money_as_stored(line.override_amount, line.currency_code)
        if amount is None:
            continue
        found[line.kind] = StoredOverride(
            amount=amount,
            reason=line.override_reason or "",
            by=line.overridden_by,
            at=line.overridden_at,
        )
    return found


# ── Guards a person's confirmation has to pass ───────────────────────────────


def held_kinds(lines: Sequence[Mapping[str, Any]]) -> list[str]:
    """The figures that are held, in printed order."""
    return [str(line["kind"]) for line in lines if line["calc_status"] == "held"]


def unconfirmed_codes(lines: Sequence[Mapping[str, Any]]) -> list[str]:
    """The category codes whose rate row has not been confirmed on its source.

    Every line counts, not only the ones holding an amount: a figure marked
    not applicable because it fell under a threshold was decided by that row
    just as much as a figure computed from its rate.
    """
    codes: list[str] = []
    for line in lines:
        if line["review_status"] == "unconfirmed" and line["code"] not in codes:
            codes.append(str(line["code"]))
    return codes


def confirmation_refusal(lines: Sequence[Mapping[str, Any]], *, acknowledged: bool) -> StatutoryRefusal | None:
    """Why these figures may not be confirmed, or ``None`` when they may.

    Checked here and not only by the validation rules. The rule engine is
    guarded so that a broken rule cannot lose somebody's save, which also means
    a broken rule reports nothing; a confirmation that depended on it alone
    would then go through on held figures.
    """
    held = held_kinds(lines)
    if held:
        return StatutoryRefusal(
            "statutory_held",
            "These figures cannot be confirmed while one of them is held: " + ", ".join(held) + ".",
            http_status=422,
            details={"held": held},
        )
    unconfirmed = unconfirmed_codes(lines)
    if unconfirmed and not acknowledged:
        return StatutoryRefusal(
            "statutory_unconfirmed_rates",
            (
                "A rate used here has not been confirmed against its primary source: "
                + ", ".join(unconfirmed)
                + ". Check it by hand and acknowledge that to confirm."
            ),
            http_status=422,
            details={"codes": unconfirmed},
        )
    return None


def statutory_payload(
    lines: Sequence[Mapping[str, Any]],
    *,
    currency_code: str,
    document_date: date,
    action: str = "save",
    acknowledged: bool = False,
    source_reference: str = "",
) -> dict[str, Any]:
    """The dict the statutory rules read. See :mod:`.validators` for the contract."""
    return {
        "record_type": "statutory_taxes",
        "action": action,
        "acknowledged_unconfirmed_rates": acknowledged,
        "currency_code": currency_code,
        "document_date": document_date,
        "source_reference": source_reference,
        "lines": [dict(line) for line in lines],
    }


# ── Stored calculations ──────────────────────────────────────────────────────


def _user_uuid(user_id: uuid.UUID | str | None) -> uuid.UUID:
    """The acting user as a GUID. A change nobody can be named for is refused."""
    if isinstance(user_id, uuid.UUID):
        return user_id
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise StatutoryRefusal(
            "user_required",
            "This change has to be made by a signed-in person.",
            http_status=403,
        ) from exc


def _require_reason(reason: str, code: str, message: str) -> str:
    text = (reason or "").strip()
    if not text:
        raise StatutoryRefusal(code, message, http_status=422)
    return text


def _require_draft(calc: StatutoryTaxCalc) -> None:
    if calc.status == "confirmed":
        raise StatutoryRefusal(
            "statutory_confirmed",
            "These figures are confirmed and are not recalculated. Reopen them with a reason first.",
            details={"status": calc.status},
        )
    if calc.status != "draft":
        raise StatutoryRefusal(
            "statutory_void",
            "These figures are void. Reopen them with a reason before changing them.",
            details={"status": calc.status},
        )


def _require_overrides_applied(result: PaymentTaxResult, overrides: Mapping[str, StoredOverride]) -> None:
    """Refuse a calculation that left a person's amount out.

    The calculation does not apply an override to a tax nobody chose or to one
    marked not applicable. Storing the result anyway would keep an amount on
    file that prints nowhere, so the caller is told to remove it first.
    """
    for kind in overrides:
        figure: Figure = getattr(result, kind)
        if not figure.overridden:
            raise StatutoryRefusal(
                "override_not_applied",
                (
                    f"The amount entered for {kind} cannot be applied to these figures "
                    f"({figure.reason_key or figure.status}). Remove the override or change the choice it depends on."
                ),
                details={"kind": kind, "reason_key": figure.reason_key, "calc_status": figure.status},
            )


async def _write_lines(
    session: AsyncSession,
    calc: StatutoryTaxCalc,
    existing: Sequence[StatutoryTaxLine],
    result: PaymentTaxResult,
    inputs: StatutoryInputs,
    overrides: Mapping[str, StoredOverride],
    rows: Sequence[RateRow],
) -> list[StatutoryTaxLine]:
    """Store the five figures, updating the rows already there by kind."""
    by_kind = {line.kind: line for line in existing}
    choice_by_figure = {figure_kind: getattr(inputs, field_name) for field_name, figure_kind in CHOICE_FIGURES.items()}
    for values in result_line_values(result, inputs, rows):
        kind = values["kind"]
        line = by_kind.get(kind)
        is_new = line is None
        if line is None:
            line = StatutoryTaxLine(calc_id=calc.id)
        line.project_id = calc.project_id
        line.source_kind = calc.source_kind
        line.source_id = calc.source_id
        for column, value in values.items():
            setattr(line, column, value)
        choice: Choice | None = choice_by_figure.get(kind)
        line.choice_state = choice.state if choice is not None else ""
        line.choice_code = (choice.code or "").strip() if choice is not None else ""
        line.choice_reason = (choice.reason or "").strip() if choice is not None else ""
        entry = overrides.get(kind)
        line.override_amount = entry.amount if entry is not None else None
        line.override_reason = entry.reason if entry is not None else ""
        line.overridden_by = entry.by if entry is not None else None
        line.overridden_at = entry.at if entry is not None else None
        if is_new:
            await repository.add_statutory_line(session, line)
    await session.flush()
    return await repository.list_statutory_lines(session, calc.id)


async def get_statutory(
    session: AsyncSession,
    *,
    source_kind: str,
    source_id: uuid.UUID,
) -> tuple[StatutoryTaxCalc, list[StatutoryTaxLine]] | None:
    """The stored header and lines of one source document, or ``None``."""
    calc = await repository.get_statutory_calc(session, source_kind=source_kind, source_id=source_id)
    if calc is None:
        return None
    return calc, await repository.list_statutory_lines(session, calc.id)


async def upsert_statutory(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_kind: str,
    source_id: uuid.UUID,
    inputs: StatutoryInputs,
    direction: str,
    user_id: uuid.UUID | str,
    source_reference: str = "",
    row_source: RowSource = shipped_rows,
) -> tuple[StatutoryTaxCalc, list[StatutoryTaxLine]]:
    """Compute a document's statutory taxes and store them as a draft.

    Saving the same inputs twice leaves the same rows: the header is found by
    its source and the lines by their kind, and both are updated in place.
    Amounts a person entered earlier are applied again.

    Args:
        session: The request's session. Flushed, not committed.
        project_id: The project the source document belongs to.
        source_kind: One of ``STATUTORY_SOURCE_KINDS``.
        source_id: Id of the source document in its own module.
        inputs: The document and the person's choices.
        direction: One of ``STATUTORY_DIRECTIONS``.
        user_id: Who is saving.
        source_reference: The number printed on the document.
        row_source: Where the statutory rows come from.

    Returns:
        The header and its five lines.

    Raises:
        StatutoryRefusal: The set is confirmed or void, belongs to another
            project, an input cannot be stored exactly, or an amount entered
            earlier no longer applies.
    """
    if source_kind not in STATUTORY_SOURCE_KINDS:
        raise StatutoryRefusal("source_kind_unknown", f"Unknown source kind '{source_kind}'.", http_status=422)
    if direction not in STATUTORY_DIRECTIONS:
        raise StatutoryRefusal("direction_unknown", f"Unknown direction '{direction}'.", http_status=422)
    _user_uuid(user_id)
    check_statutory_inputs(inputs)

    not_found = StatutoryRefusal("statutory_not_found", "Statutory tax lines not found", http_status=404)
    # The owning module says whose document this is. Without that, the first
    # caller to name an unclaimed id would own its taxes, whatever project the
    # document really belongs to.
    if not await source_belongs_to_project(
        session, source_kind=source_kind, source_id=source_id, project_id=project_id
    ):
        raise not_found
    calc = await repository.get_statutory_calc(session, source_kind=source_kind, source_id=source_id)
    existing: list[StatutoryTaxLine] = []
    if calc is not None:
        if calc.project_id != project_id:
            # The same answer as for a document with nothing stored: a
            # different one would tell the caller that another project's
            # document exists.
            raise not_found
        _require_draft(calc)
        existing = await repository.list_statutory_lines(session, calc.id)

    # Computed before anything is written, so a calculation that fails leaves
    # no header behind without its lines.
    overrides = overrides_from_stored(existing)
    rows = row_source(inputs.country_code)
    result = compute_statutory(inputs, rows, overrides)
    _require_overrides_applied(result, overrides)
    result_line_values(result, inputs, rows)

    if calc is None:
        calc = await repository.add_statutory_calc(
            session,
            StatutoryTaxCalc(
                project_id=project_id,
                source_kind=source_kind,
                source_id=source_id,
                direction=direction,
                country_code=inputs.country_code,
                currency_code=inputs.currency_code,
                document_date=inputs.document_date,
                net_amount=inputs.net_amount,
                status="draft",
            ),
        )
        if calc is None:
            # Another request stored it between the read and the insert. Its
            # row is read and updated like any other existing one.
            calc = await repository.get_statutory_calc(session, source_kind=source_kind, source_id=source_id)
            if calc is None or calc.project_id != project_id:
                raise not_found
            _require_draft(calc)
            existing = await repository.list_statutory_lines(session, calc.id)
            if overrides_from_stored(existing):
                raise StatutoryRefusal(
                    "statutory_changed",
                    "These figures were changed by someone else while you were saving. Load them again.",
                )

    calc.source_reference = source_reference
    calc.direction = direction
    calc.country_code = inputs.country_code
    calc.currency_code = inputs.currency_code
    calc.document_date = inputs.document_date
    calc.net_amount = inputs.net_amount
    calc.vat_rate_pct = inputs.vat_rate_pct
    calc.buyer_is_designated = inputs.buyer_is_designated
    calc.work_value_incl_vat = inputs.work_value_incl_vat
    calc.work_value_note = (inputs.work_value_note or "").strip()
    calc.stamp_duty_base = inputs.stamp_duty_base
    calc.stamp_duty_base_same_as_net = inputs.stamp_duty_base_same_as_net
    lines = await _write_lines(session, calc, existing, result, inputs, overrides, rows)
    return calc, lines


async def _recompute_with_overrides(
    session: AsyncSession,
    calc: StatutoryTaxCalc,
    overrides: Mapping[str, StoredOverride],
    existing: Sequence[StatutoryTaxLine],
    row_source: RowSource,
) -> list[StatutoryTaxLine]:
    inputs = inputs_from_stored(calc, existing)
    rows = row_source(inputs.country_code)
    result = compute_statutory(inputs, rows, overrides)
    _require_overrides_applied(result, overrides)
    return await _write_lines(session, calc, existing, result, inputs, overrides, rows)


async def override_statutory(
    session: AsyncSession,
    *,
    calc: StatutoryTaxCalc,
    kind: str,
    amount: Decimal,
    reason: str,
    user_id: uuid.UUID | str,
    row_source: RowSource = shipped_rows,
) -> list[StatutoryTaxLine]:
    """Replace the computed amount of one figure with a person's own.

    The figures are recomputed from the stored inputs with the amount applied,
    so the payable VAT follows an override of the withheld VAT.

    Raises:
        StatutoryRefusal: The set is not a draft, the figure cannot be
            overridden, the reason is blank, the amount is finer than the
            currency, or the calculation did not apply the amount.
    """
    _require_draft(calc)
    actor = _user_uuid(user_id)
    if kind not in OVERRIDABLE_KINDS:
        raise StatutoryRefusal(
            "override_not_allowed",
            f"The figure '{kind}' cannot be overridden. To change the payable VAT, change the withheld VAT.",
            http_status=422,
            details={"kind": kind},
        )
    text = _require_reason(reason, "override_reason_required", "An overridden amount needs a reason.")
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise StatutoryRefusal("amount_not_storable", "The override amount is not a number.", http_status=422)
    if currency_quantum(calc.currency_code) is None:
        raise StatutoryRefusal(
            "currency_unknown",
            f"An amount cannot be entered in the unknown currency '{calc.currency_code}'.",
            http_status=422,
            details={"currency_code": calc.currency_code},
        )
    _require_storable(amount, "override amount", calc.currency_code)

    existing = await repository.list_statutory_lines(session, calc.id)
    overrides = overrides_from_stored(existing)
    overrides[kind] = StoredOverride(amount=amount, reason=text, by=actor, at=datetime.now(UTC))
    return await _recompute_with_overrides(session, calc, overrides, existing, row_source)


async def clear_statutory_override(
    session: AsyncSession,
    *,
    calc: StatutoryTaxCalc,
    kind: str,
    user_id: uuid.UUID | str,
    row_source: RowSource = shipped_rows,
) -> list[StatutoryTaxLine]:
    """Remove a person's amount from one figure and recompute.

    Raises:
        StatutoryRefusal: The set is not a draft, or the figure carries no
            override.
    """
    _require_draft(calc)
    _user_uuid(user_id)
    existing = await repository.list_statutory_lines(session, calc.id)
    overrides = overrides_from_stored(existing)
    if kind not in overrides:
        raise StatutoryRefusal("override_not_found", "Override not found", http_status=404, details={"kind": kind})
    del overrides[kind]
    return await _recompute_with_overrides(session, calc, overrides, existing, row_source)


async def _audit(
    session: AsyncSession,
    calc: StatutoryTaxCalc,
    action: str,
    actor: uuid.UUID,
    details: dict[str, Any],
) -> None:
    from app.core.audit import audit_log

    await audit_log(
        session,
        action=action,
        entity_type=STATUTORY_ENTITY,
        entity_id=str(calc.id),
        user_id=str(actor),
        details={
            "source_kind": calc.source_kind,
            "source_id": str(calc.source_id),
            "project_id": str(calc.project_id),
            **details,
        },
    )


async def confirm_statutory(
    session: AsyncSession,
    *,
    calc: StatutoryTaxCalc,
    user_id: uuid.UUID | str,
    acknowledge_unconfirmed_rates: bool = False,
) -> tuple[list[StatutoryTaxLine], list[Any]]:
    """Put a person's signature under the stored figures and freeze them.

    Nothing is recomputed. What is confirmed is what was stored and shown, and
    from here on the rows answer for the document whatever the rate tables do.

    Args:
        session: The request's session.
        calc: The header, already checked to be the caller's.
        user_id: Who confirms.
        acknowledge_unconfirmed_rates: Set by a person who has checked by hand
            a rate this platform has not confirmed against its source. Stored
            with their id and the time.

    Returns:
        The lines and the validation findings that did not block.

    Raises:
        StatutoryRefusal: The set is not a draft, a figure is held, an
            unconfirmed rate is not acknowledged, or a rule reports an error.
    """
    from app.modules.tax_withholding.validators import blocking_findings, evaluate_record

    _require_draft(calc)
    actor = _user_uuid(user_id)
    lines = await repository.list_statutory_lines(session, calc.id)
    result_from_lines(lines)
    values = [stored_line_values(line) for line in lines]
    findings = await evaluate_record(
        statutory_payload(
            values,
            currency_code=calc.currency_code,
            document_date=calc.document_date,
            action="confirm",
            acknowledged=acknowledge_unconfirmed_rates,
            source_reference=calc.source_reference,
        ),
        record_id=str(calc.id),
    )
    refusal = confirmation_refusal(values, acknowledged=acknowledge_unconfirmed_rates)
    if refusal is not None:
        refusal.findings = findings
        raise refusal
    blocking = blocking_findings(findings)
    if blocking:
        raise StatutoryRefusal(
            "statutory_invalid",
            "These figures cannot be confirmed until their errors are fixed.",
            http_status=422,
            findings=blocking,
        )

    now = datetime.now(UTC)
    unconfirmed = unconfirmed_codes(values)
    calc.status = "confirmed"
    calc.confirmed_by = actor
    calc.confirmed_at = now
    calc.unconfirmed_rates_acknowledged_by = actor if unconfirmed else None
    calc.unconfirmed_rates_acknowledged_at = now if unconfirmed else None
    await session.flush()
    await _audit(
        session,
        calc,
        "confirm",
        actor,
        {"acknowledged_unconfirmed_codes": unconfirmed},
    )
    return lines, findings


async def reopen_statutory(
    session: AsyncSession,
    *,
    calc: StatutoryTaxCalc,
    user_id: uuid.UUID | str,
    reason: str,
) -> list[StatutoryTaxLine]:
    """Take a confirmed or void set back to draft, on the record.

    The earlier confirmation is written to the audit log before it is cleared
    from the header, so who signed what, and when, survives the reopening.

    Raises:
        StatutoryRefusal: The set is already a draft, or the reason is blank.
    """
    actor = _user_uuid(user_id)
    text = _require_reason(reason, "reopen_reason_required", "Reopening confirmed figures needs a reason.")
    if calc.status == "draft":
        raise StatutoryRefusal("statutory_already_draft", "These figures are a draft already.")
    await _audit(
        session,
        calc,
        "reopen",
        actor,
        {
            "reason": text,
            "previous_status": calc.status,
            "confirmed_by": str(calc.confirmed_by) if calc.confirmed_by else None,
            "confirmed_at": calc.confirmed_at.isoformat() if calc.confirmed_at else None,
            "unconfirmed_rates_acknowledged_by": (
                str(calc.unconfirmed_rates_acknowledged_by) if calc.unconfirmed_rates_acknowledged_by else None
            ),
            "voided_by": str(calc.voided_by) if calc.voided_by else None,
            "void_reason": calc.void_reason or "",
        },
    )
    calc.status = "draft"
    calc.confirmed_by = None
    calc.confirmed_at = None
    calc.unconfirmed_rates_acknowledged_by = None
    calc.unconfirmed_rates_acknowledged_at = None
    calc.voided_by = None
    calc.voided_at = None
    calc.void_reason = ""
    calc.reopened_by = actor
    calc.reopened_at = datetime.now(UTC)
    calc.reopen_reason = text
    await session.flush()
    return await repository.list_statutory_lines(session, calc.id)


async def void_statutory(
    session: AsyncSession,
    *,
    calc: StatutoryTaxCalc,
    user_id: uuid.UUID | str,
    reason: str,
) -> list[StatutoryTaxLine]:
    """Take a set out of use and keep its rows as evidence.

    Raises:
        StatutoryRefusal: The set is void already, or the reason is blank.
    """
    actor = _user_uuid(user_id)
    text = _require_reason(reason, "void_reason_required", "Voiding statutory tax lines needs a reason.")
    if calc.status == "void":
        raise StatutoryRefusal("statutory_already_void", "These figures are void already.")
    await _audit(session, calc, "void", actor, {"reason": text, "previous_status": calc.status})
    calc.status = "void"
    calc.voided_by = actor
    calc.voided_at = datetime.now(UTC)
    calc.void_reason = text
    await session.flush()
    return await repository.list_statutory_lines(session, calc.id)


async def as_payment_tax_result(
    session: AsyncSession,
    *,
    source_kind: str,
    source_id: uuid.UUID,
) -> PaymentTaxResult | None:
    """The stored figures of one source document as a calculation result.

    Draft or confirmed, the answer is rebuilt from the rows. A void set and a
    document with nothing stored both answer ``None``: neither has figures a
    certificate may print.
    """
    stored = await get_statutory(session, source_kind=source_kind, source_id=source_id)
    if stored is None:
        return None
    calc, lines = stored
    if calc.status == "void":
        return None
    return result_from_lines(lines)


def _certificate_taxes(registry: Any, calc: StatutoryTaxCalc, lines: Sequence[StatutoryTaxLine]) -> Any:
    """A stored set in the shape the certificate registry defines.

    ``registry`` is the certificate tax module of ``contracts``, handed in
    rather than imported so this file still loads without it.
    """
    inputs = inputs_from_stored(calc, lines)
    return registry.CertificateTaxes(
        result=result_from_lines(lines),
        status=calc.status,
        net_amount=inputs.net_amount,
        stamp_duty_base=inputs.stamp_duty_base,
        stamp_duty_base_same_as_net=inputs.stamp_duty_base_same_as_net,
        vat_rate_pct=inputs.vat_rate_pct,
        document_date=inputs.document_date,
        currency=inputs.currency_code,
        choices={
            "vat_withholding": inputs.vat_withholding,
            "income_withholding": inputs.income_withholding,
            "stamp_duty": inputs.stamp_duty,
        },
        buyer_is_designated=inputs.buyer_is_designated,
        work_value_incl_vat=inputs.work_value_incl_vat,
        work_value_note=inputs.work_value_note,
    )


async def certificate_tax_provider(
    session: AsyncSession,
    source_kind: str,
    source_id: uuid.UUID | str,
) -> Any:
    """What this module tells a payment certificate about one document's taxes.

    Registered with the certificate tax registry of ``contracts`` when that
    module is installed. ``None`` means nothing usable is stored, and the
    certificate then holds its tax lines. Otherwise the answer is the result
    together with the header it was stored under: the certificate needs the
    status to say whether the figures are confirmed, and the amounts they
    were computed on to notice that its own amount has moved since.
    """
    if source_kind not in STATUTORY_SOURCE_KINDS:
        return None
    wanted = source_id if isinstance(source_id, uuid.UUID) else uuid.UUID(str(source_id))
    stored = await get_statutory(session, source_kind=source_kind, source_id=wanted)
    if stored is None:
        return None
    calc, lines = stored
    if calc.status == "void":
        return None
    registry = importlib.import_module(_CERTIFICATE_REGISTRY)
    return _certificate_taxes(registry, calc, lines)


async def certificate_tax_writer(
    session: AsyncSession,
    request: Any,
    *,
    row_source: RowSource | None = None,
) -> Any:
    """Compute and store a certificate's taxes on the amounts the certificate states.

    The certificate knows its own amount before VAT and the base of its stamp
    duty line, so it passes both; a person passes only the choices and the two
    facts about the buyer. A request without choices keeps the stored ones,
    which is a recalculation on new amounts.

    The stamp duty base is stated as "the net amount" when the two are equal
    and as its own amount when they differ. When the certificate cannot say
    what it is, neither is stated and a selected stamp duty is held.

    Raises:
        CertificateTaxRefusalError: Whatever :func:`upsert_statutory` refuses,
            in the registry's own exception so ``contracts`` need not know
            this module's.
    """
    registry = importlib.import_module(_CERTIFICATE_REGISTRY)
    stored = await get_statutory(session, source_kind=request.source_kind, source_id=request.source_id)
    previous: StatutoryInputs | None = None
    if stored is not None and stored[0].project_id == request.project_id:
        try:
            previous = inputs_from_stored(*stored)
        except StatutoryDataError:
            previous = None

    def choice(name: str) -> Choice:
        if request.choices is not None:
            return request.choices.get(name) or Choice("unset")
        return getattr(previous, name) if previous is not None else Choice("unset")

    keep = request.keep_buyer_facts and previous is not None
    same_as_net = request.stamp_duty_base is not None and request.stamp_duty_base == request.net_amount
    inputs = StatutoryInputs(
        country_code=request.country_code,
        currency_code=request.currency,
        document_date=request.document_date,
        net_amount=request.net_amount,
        vat_rate_pct=request.vat_rate_pct,
        buyer_is_designated=previous.buyer_is_designated if keep and previous else request.buyer_is_designated,
        work_value_incl_vat=previous.work_value_incl_vat if keep and previous else request.work_value_incl_vat,
        work_value_note=previous.work_value_note if keep and previous else request.work_value_note,
        stamp_duty_base=None if same_as_net else request.stamp_duty_base,
        stamp_duty_base_same_as_net=same_as_net,
        vat_withholding=choice("vat_withholding"),
        income_withholding=choice("income_withholding"),
        stamp_duty=choice("stamp_duty"),
    )
    try:
        calc, lines = await upsert_statutory(
            session,
            project_id=request.project_id,
            source_kind=request.source_kind,
            source_id=request.source_id,
            inputs=inputs,
            direction=request.direction,
            user_id=request.user_id,
            source_reference=request.source_reference,
            row_source=row_source or _certificate_row_source,
        )
    except StatutoryRefusal as refusal:
        raise registry.CertificateTaxRefusalError(
            refusal.code, refusal.message, http_status=refusal.http_status, details=refusal.details
        ) from refusal
    return _certificate_taxes(registry, calc, lines)


def _certificate_row_source(country: str) -> Sequence[RateRow]:
    """The rows a certificate's taxes are computed from.

    Looked up through :data:`certificate_rows` on every call, so a test can
    put synthetic rows in place of the shipped ones for this path as well.
    """
    return certificate_rows(country)


#: Where a certificate's taxes take their statutory rows from. The shipped
#: rows; a test replaces it to inject synthetic ones.
certificate_rows: RowSource = shipped_rows


def register_certificate_tax_provider(importer: Callable[[str], Any] = importlib.import_module) -> bool:
    """Offer :func:`certificate_tax_provider` to the certificate module.

    Args:
        importer: How the registry module is imported. A seam for tests.

    Returns:
        True when the provider was registered, False when ``contracts`` ships
        no certificate tax registry on this install. Only that absence is
        tolerated: an import that fails inside the registry is raised, because
        reading it as "not installed" would print certificates with held tax
        lines and no error anywhere.
    """
    target = _CERTIFICATE_REGISTRY
    try:
        registry = importer(target)
    except ModuleNotFoundError as exc:
        if exc.name not in {target, "app.modules.contracts"}:
            raise
        logger.info("tax_withholding: no certificate tax registry on this install, provider not registered")
        return False
    registry.register_certificate_tax_provider(certificate_tax_provider)
    # A registry from before certificates could ask for their taxes has no
    # writer slot; the provider alone is then all there is to register.
    register_writer = getattr(registry, "register_certificate_tax_writer", None)
    if register_writer is not None:
        register_writer(certificate_tax_writer)
    return True


__all__ = [
    "CHOICE_FIGURES",
    "FIGURE_ROW_KINDS",
    "OVERRIDABLE_KINDS",
    "STATUTORY_ENTITY",
    "THRESHOLD_UNEVALUATED_REASONS",
    "ZERO",
    "BandDecision",
    "DeductionFigures",
    "RowSource",
    "StatutoryDataError",
    "StatutoryInputs",
    "StatutoryRefusal",
    "StoredOverride",
    "apply_deduction_body",
    "apply_determination_body",
    "apply_party_status_body",
    "apply_regime_body",
    "as_payment_tax_result",
    "bands_of",
    "build_tax_input",
    "certificate_tax_provider",
    "certificate_tax_writer",
    "check_statutory_inputs",
    "clear_statutory_override",
    "compute_deduction",
    "compute_statutory",
    "compute_tax_withheld",
    "compute_taxable_base",
    "confirm_statutory",
    "confirmation_refusal",
    "currency_quantum",
    "deduction_payload",
    "determination_payload",
    "expiry_view",
    "figure_from_values",
    "find_band",
    "get_statutory",
    "held_kinds",
    "inputs_from_stored",
    "line_values",
    "load_deduction_context",
    "money_as_stored",
    "override_statutory",
    "overrides_from_stored",
    "plain_decimal",
    "preview_statutory",
    "quantise",
    "register_certificate_tax_provider",
    "reopen_statutory",
    "resolve_band",
    "result_from_lines",
    "result_line_values",
    "row_behind",
    "seed_regimes",
    "shipped_rows",
    "statutory_payload",
    "stored_line_values",
    "to_decimal",
    "unconfirmed_codes",
    "upsert_statutory",
    "verification_is_current",
    "void_statutory",
]
