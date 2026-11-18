# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What every US state table shares: the vocabulary and the US-wide rule ids.

The state packs (``us_ca_pack``, ``us_tx_pack``, ``us_ny_pack``, ``us_fl_pack``)
each contribute a ``JURISDICTION_RULES`` table to the neutral statutory engines.
The words a US user reads for the same check in every state live here once, so
four states cannot drift into four phrasings of one rule.
"""

from __future__ import annotations

from typing import Any

#: Claimant roles a US lien statute distinguishes.
US_CLAIMANT_ROLES: list[str] = ["direct_contractor", "subcontractor", "supplier"]

#: Sectors the retention and payment statutes distinguish.
US_SECTORS: list[str] = ["public", "private"]

VERIFY_NOTE = (
    "Statutory deadlines and limits are computed from the statute cited beside each one. They are not legal "
    "advice: verify every date with counsel before relying on it."
)

RETAINAGE_OVER_CAP: dict[str, Any] = {
    "id": "us.retainage.over_cap",
    "check": "retention.over_cap",
    "severity": "error",
    "name": "Retainage over the statutory cap",
    "message": "Retainage {pct}% exceeds the {state} cap of {cap}% for this contract ({source}).",
}

TAX_RATE_IS_STATE_BASE: dict[str, Any] = {
    "id": "us.tax.rate_is_state_base",
    "check": "tax.rate_is_base_rate",
    "severity": "warning",
    "name": "Tax at the state base rate only",
    "message": "Tax uses the state base rate only; resolve the jobsite address rate.",
}

LIEN_NOTICE_DUE: dict[str, Any] = {
    "id": "us.lien.notice_due",
    "check": "notice.due",
    "severity": "warning",
    "name": "Lien or payment notice due",
    "message": "{notice} due {date} for {month} work ({source}).",
    "message_without_period": "{notice} due {date} ({source}).",
}


def common_bindings() -> list[dict[str, Any]]:
    """Fresh copies of the US-wide bindings, so a state cannot mutate another's."""
    return [dict(RETAINAGE_OVER_CAP), dict(TAX_RATE_IS_STATE_BASE), dict(LIEN_NOTICE_DUE)]


__all__ = [
    "LIEN_NOTICE_DUE",
    "RETAINAGE_OVER_CAP",
    "TAX_RATE_IS_STATE_BASE",
    "US_CLAIMANT_ROLES",
    "US_SECTORS",
    "VERIFY_NOTE",
    "common_bindings",
]
