# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Whether an invoice falls under mandatory split payment (MPP).

Two conditions, both required (VAT Act art. 108a ust. 1a): at least one line
covers goods or services listed in Annex 15 to the VAT Act, and the gross total
of the invoice exceeds PLN 15,000 or its equivalent. The threshold is per
invoice, not per line, and it is strictly "exceeds": 15,000.00 is not above it.

A line is Annex 15 because the data says so. Annex 15 lists individual PKWiU
codes, so a code prefix cannot decide it; the prefix only feeds an advisory
warning on a construction line nobody flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.modules.einvoice_ksef.facts import CONSTRUCTION_PKWIU_SECTIONS, SPLIT_PAYMENT_THRESHOLD_PLN

DECIDED_YES = "required"
DECIDED_NO = "not_required"
UNDECIDABLE = "undecidable"


@dataclass(frozen=True)
class SplitPaymentDecision:
    verdict: str
    gross_pln: Decimal | None
    annex_15_lines: int
    reason: str

    @property
    def required(self) -> bool:
        return self.verdict == DECIDED_YES


def decide(
    *,
    gross: Decimal,
    currency: str,
    annex_15_lines: int,
    exchange_rate: Decimal | None = None,
) -> SplitPaymentDecision:
    """Decide P_18A for one invoice.

    Args:
        gross: The invoice's gross total in its own currency.
        currency: ISO currency code of the invoice.
        annex_15_lines: How many lines are flagged Annex 15.
        exchange_rate: PLN per unit of ``currency``; ignored for PLN.
    """
    if annex_15_lines <= 0:
        return SplitPaymentDecision(DECIDED_NO, None, 0, "no line covers goods or services listed in Annex 15")
    if (currency or "").upper() == "PLN":
        gross_pln: Decimal | None = gross
    elif exchange_rate is not None and exchange_rate > 0:
        gross_pln = (gross * exchange_rate).quantize(Decimal("0.01"))
    else:
        return SplitPaymentDecision(
            UNDECIDABLE,
            None,
            annex_15_lines,
            f"the invoice is in {currency} and no exchange rate is given, so its PLN equivalent is unknown",
        )
    if abs(gross_pln) > SPLIT_PAYMENT_THRESHOLD_PLN:
        return SplitPaymentDecision(
            DECIDED_YES,
            gross_pln,
            annex_15_lines,
            f"Annex 15 lines and a gross total of PLN {gross_pln} above PLN {SPLIT_PAYMENT_THRESHOLD_PLN}",
        )
    return SplitPaymentDecision(
        DECIDED_NO,
        gross_pln,
        annex_15_lines,
        f"the gross total of PLN {gross_pln} does not exceed PLN {SPLIT_PAYMENT_THRESHOLD_PLN}",
    )


def looks_like_construction(pkwiu: str) -> bool:
    """Whether a PKWiU code sits in a construction section (41, 42, 43). A hint only."""
    code = (pkwiu or "").strip()
    return any(code.startswith(section) for section in CONSTRUCTION_PKWIU_SECTIONS)


__all__ = [
    "DECIDED_NO",
    "DECIDED_YES",
    "UNDECIDABLE",
    "SplitPaymentDecision",
    "decide",
    "looks_like_construction",
]
