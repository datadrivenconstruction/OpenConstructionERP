# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure checks on a bid leveling and the award that follows it.

The core rule classes (``bid_leveling.*`` in ``app.core.validation.rules``)
wrap these. Standard library only, no ORM, so each check is testable alone.

Payload::

    {
      "package": "BP-001", "currency": "EUR", "threshold_pct": "10",
      "leveling_computed": true,
      "bidders": [{"name": "...", "plug_total": "...", "plugged_total": "...",
                   "unpriced_gap_lines": 0}]
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import sentence_amount

#: Plugs above this share of a leveled total make the comparison mostly guesswork.
DEFAULT_PLUG_SHARE_THRESHOLD_PCT = Decimal("10")


@dataclass(frozen=True)
class Finding:
    """One failed check; ``params`` fill the translated message."""

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def check_plug_share(payload: dict[str, Any]) -> list[Finding]:
    """Warn when plugs are more than the threshold share of a bidder's leveled total."""
    threshold = _dec(payload.get("threshold_pct")) or DEFAULT_PLUG_SHARE_THRESHOLD_PCT
    currency = str(payload.get("currency") or "")
    findings: list[Finding] = []
    for bidder in payload.get("bidders") or []:
        plugs = _dec(bidder.get("plug_total")) or Decimal("0")
        leveled = _dec(bidder.get("plugged_total")) or Decimal("0")
        if plugs <= 0 or leveled <= 0:
            continue
        share = (plugs / leveled * 100).quantize(Decimal("0.1"))
        if share <= threshold:
            continue
        name = str(bidder.get("name") or "bidder")
        findings.append(
            Finding(
                element_ref=name,
                params={
                    "bidder": name,
                    "plug_total": sentence_amount(plugs, currency),
                    "leveled_total": sentence_amount(leveled, currency),
                    "share": f"{share:f}",
                    "threshold": f"{threshold:f}",
                },
                details={"share_pct": str(share)},
            )
        )
    return findings


def check_gaps_plugged(payload: dict[str, Any]) -> list[Finding]:
    """Warn for each bidder with gaps nothing could be plugged from."""
    findings: list[Finding] = []
    for bidder in payload.get("bidders") or []:
        count = int(bidder.get("unpriced_gap_lines") or 0)
        if count <= 0:
            continue
        name = str(bidder.get("name") or "bidder")
        findings.append(Finding(element_ref=name, params={"bidder": name, "count": str(count)}))
    return findings


def check_award_leveled(payload: dict[str, Any]) -> list[Finding]:
    """Warn when a package is awarded without a computed leveling."""
    if payload.get("leveling_computed"):
        return []
    package = str(payload.get("package") or "package")
    return [Finding(element_ref=package, params={"package": package})]


def check_linked_tender_awarded(payload: dict[str, Any]) -> list[Finding]:
    """Flag a package linked to a main contract tender that is still not awarded.

    The tender drafts no contract of its own while a package is linked (the
    package award does), so an unawarded package leaves the tender contract-less.
    """
    tender = payload.get("linked_tender")
    if not tender or payload.get("status") in ("awarded", "cancelled"):
        return []
    package = str(payload.get("package") or "package")
    return [Finding(element_ref=package, params={"package": package, "tender": str(tender)})]
