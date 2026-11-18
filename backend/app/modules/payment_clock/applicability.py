# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Whether a statutory payment regime covers one contract, and the windows it opens.

Pure functions over the plain regime mapping (one entry of
:data:`app.modules.payment_clock.data.PAYMENT_REGIMES`, or
:func:`app.modules.payment_clock.service.regime_spec` of a row) and a plain
contract mapping. No database.

A security-of-payment statute rarely covers every contract. It names a date the
contract must be made on or after, a minimum contract value (often a lower one
for a contract that only supplies goods and services), and for private work it
may cover only some kinds of work. A subcontract is covered at any value when
the main contract above it is. Each of those is a column on the regime, so the
same function answers for every country that writes one down.

The contract mapping keys, all optional:

* ``contract_date`` - date or ISO string the contract was made.
* ``contract_value`` - the value as at that date.
* ``supply_only`` - True when the contract supplies goods and services only.
* ``sector`` - ``"public"`` or ``"private"``.
* ``is_subcontract`` and ``main_contract_covered`` - a subcontract and whether
  the main contract above it is covered.
* ``private_scope_confirmed`` - for a private main contract under a regime with a
  ``private_scope_rule``: True when the user confirmed the works are in scope,
  False when confirmed out of scope, None when nobody said.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.modules.payment_clock.clock import parse_date, parse_money

#: The answers :func:`regime_applicability` gives.
APPLIES = "applies"
DOES_NOT_APPLY = "does_not_apply"
NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass(frozen=True)
class Applicability:
    """The verdict and the reason, as a stable code a rule or a UI can render."""

    status: str
    reason: str


def regime_applicability(regime: Mapping[str, Any], contract: Mapping[str, Any]) -> Applicability:
    """Whether ``regime`` covers ``contract``.

    Returns ``needs_confirmation`` only for a private main contract whose works
    have to be of a kind the statute names and nobody has said whether they are.
    """
    applies_from = parse_date(regime.get("applies_from"))
    made = parse_date(contract.get("contract_date"))
    if applies_from is not None and made is not None and made < applies_from:
        return Applicability(DOES_NOT_APPLY, "made_before_commencement")

    if contract.get("is_subcontract"):
        if contract.get("main_contract_covered"):
            return Applicability(APPLIES, "subcontract_of_covered_contract")
        return Applicability(DOES_NOT_APPLY, "main_contract_not_covered")

    threshold_key = "min_contract_value_supply" if contract.get("supply_only") else "min_contract_value"
    threshold = parse_money(regime.get(threshold_key))
    value = parse_money(contract.get("contract_value"))
    if threshold is not None and (value is None or value < threshold):
        return Applicability(DOES_NOT_APPLY, "below_value_threshold")

    if regime.get("private_scope_rule") and str(contract.get("sector") or "").lower() == "private":
        confirmed = contract.get("private_scope_confirmed")
        if confirmed is None:
            return Applicability(NEEDS_CONFIRMATION, "private_scope_unconfirmed")
        if not confirmed:
            return Applicability(DOES_NOT_APPLY, "private_scope_excluded")

    return Applicability(APPLIES, "in_scope")


def dispute_date(response_deadline: date | None) -> date | None:
    """The day a payment dispute arises when no (or a short) response came: the day after the deadline."""
    return response_deadline + timedelta(days=1) if response_deadline else None


def adjudication_window_closes(regime: Mapping[str, Any], dispute_arises: date | None) -> date | None:
    """Last day to serve an adjudication notice: N days *beginning on* the dispute date.

    "Within 28 days beginning on the date the dispute arises" counts the dispute
    date as day one, so the last day is that date plus N - 1.
    """
    window = regime.get("adjudication_window_days")
    if dispute_arises is None or window in (None, ""):
        return None
    return dispute_arises + timedelta(days=int(window) - 1)


__all__ = [
    "APPLIES",
    "DOES_NOT_APPLY",
    "NEEDS_CONFIRMATION",
    "Applicability",
    "adjudication_window_closes",
    "dispute_date",
    "regime_applicability",
]
