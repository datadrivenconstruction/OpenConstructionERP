# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Whether an invoice falls under mandatory split payment (MPP), for P_18A.

Two conditions, both required (VAT Act art. 108a ust. 1a): at least one line
covers goods or services listed in Annex 15 to the VAT Act, and the gross total
of the invoice exceeds the threshold. The threshold is per invoice, not per
line, and it is strictly "exceeds".

Split payment is a VAT rule, so the threshold and the Annex 15 sections are not
held here. They are read from the Polish VAT data
(:func:`app.core.vat_construction.split_payment_rules`). When that data cannot
be read the answer is :data:`NOT_CHECKED`, never a number remembered here.

A line is Annex 15 because the data says so. Annex 15 lists individual PKWiU
codes, so a code prefix cannot decide it; the prefix only feeds an advisory
warning on a construction line nobody flagged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

COUNTRY = "PL"

DECIDED_YES = "required"
DECIDED_NO = "not_required"
UNDECIDABLE = "undecidable"
NOT_CHECKED = "not_checked"


@dataclass(frozen=True)
class SplitPaymentDecision:
    verdict: str
    gross_pln: Decimal | None
    annex_15_lines: int
    reason: str
    threshold_pln: Decimal | None = None

    @property
    def required(self) -> bool:
        return self.verdict == DECIDED_YES


def rules() -> dict[str, Any] | None:
    """The Polish split payment block of the VAT data, or ``None`` when it cannot be read."""
    try:
        from app.core.vat_construction import split_payment_rules

        block = split_payment_rules(COUNTRY)
    except Exception:  # noqa: BLE001 - unreadable data is "not checked", whatever the cause
        logger.warning("Polish split payment data could not be read", exc_info=True)
        return None
    return block if isinstance(block, dict) else None


def threshold_pln() -> Decimal | None:
    """The gross invoice total split payment applies above, from the VAT data."""
    block = rules()
    if block is None:
        return None
    try:
        value = Decimal(str(block.get("threshold_gross")))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


def annex_15_sections() -> tuple[str, ...]:
    """The PKWiU sections Annex 15 lists positions from, from the VAT data. Empty when unread."""
    block = rules() or {}
    return tuple(str(p).strip() for p in block.get("annex_pkwiu_prefixes") or () if str(p).strip())


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
    threshold = threshold_pln()
    if threshold is None:
        return SplitPaymentDecision(
            NOT_CHECKED,
            gross_pln,
            annex_15_lines,
            "the split payment threshold could not be read from the Polish VAT data",
        )
    if abs(gross_pln) > threshold:
        return SplitPaymentDecision(
            DECIDED_YES,
            gross_pln,
            annex_15_lines,
            f"Annex 15 lines and a gross total of PLN {gross_pln} above PLN {threshold}",
            threshold,
        )
    return SplitPaymentDecision(
        DECIDED_NO,
        gross_pln,
        annex_15_lines,
        f"the gross total of PLN {gross_pln} does not exceed PLN {threshold}",
        threshold,
    )


def looks_like_construction(pkwiu: str) -> bool:
    """Whether a PKWiU code sits in an Annex 15 section (``43`` or ``43.x``). A hint only."""
    code = (pkwiu or "").strip()
    return bool(code) and any(code == s or code.startswith(s + ".") for s in annex_15_sections())


__all__ = [
    "DECIDED_NO",
    "DECIDED_YES",
    "NOT_CHECKED",
    "UNDECIDABLE",
    "SplitPaymentDecision",
    "annex_15_sections",
    "decide",
    "looks_like_construction",
    "rules",
    "threshold_pln",
]
