# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""VAT regimes a contract can be taxed under, and who may choose which.

A VAT rate answers "how much of the price is tax". Some countries also ask
two more questions of a contract, and the rate alone cannot answer them:

* **How much of the price is the base.** A regime may tax only a share of
  the consideration, for example 14 percent on 36 percent of the invoice.
  That is ``base_fraction``; the full price is ``Decimal(1)``.
* **Whether the supplier may deduct the VAT on its own costs.** A regime may
  tax the output at a low effective rate on condition that no input VAT is
  recovered. That is ``input_credit``.

And the choice is not free: a transitional regime is open only to contracts
signed before a date, with evidence that billing had started before it.
Those conditions are data on the regime (:class:`Eligibility`) and are
checked by :func:`eligibility_findings`, which the contract's validation rules
call, so a contract that does not qualify is reported rather than taxed
quietly at the wrong rate.

**No rate lives here.** A regime names the ``tax_code`` of the dated tax seed
whose row supplies the nominal rate on a given day; this module multiplies
that rate by the base fraction and nothing else. One rate, one source.

A country's regimes live in a module of this package named ``data_<cc>``
exporting ``REGIMES``. Adding a country is adding that file.

Standard library only. Nothing here may import from ``app.modules``.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from importlib.resources import files
from typing import Literal

__all__ = [
    "EVIDENCE_KINDS",
    "FINDING_KEYS",
    "ContractFacts",
    "Eligibility",
    "Evidence",
    "Finding",
    "VatRegime",
    "countries_with_regimes",
    "effective_rate_pct",
    "eligibility_findings",
    "in_force",
    "lookup",
    "regimes_for",
    "validate_regimes",
    "window_findings",
]

#: The kinds of evidence a regime can ask a contract to hold. Closed, because
#: each one is a field on the contract screen and a sentence in the findings.
EVIDENCE_KINDS: tuple[str, ...] = (
    # A payment certificate approved by the engineer or consultant.
    "approved_certificate",
    # An electronic invoice or receipt issued to the tax authority's platform.
    "einvoice",
    # A certificate from the main contractor that it paid VAT on the same
    # project, for a subcontractor that claims the main contractor's regime.
    "main_contractor_certificate",
)

#: Every finding key :func:`eligibility_findings` and :func:`window_findings`
#: emit. Each has a sentence in the contracts message bundle.
FINDING_KEYS: tuple[str, ...] = (
    "contract_date_missing",
    "contract_too_late",
    "evidence_missing",
    "evidence_date_missing",
    "evidence_too_late",
    "scope_increase_unjudged",
    "scope_increase_new_contract",
    "not_in_force",
)

_REVIEW_STATUSES = ("confirmed", "needs_expert_review")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_DATA_MODULE_PREFIX = "data_"
_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Eligibility:
    """Who may choose a regime, as data.

    Attributes:
        contract_signed_before: The contract must have been signed (or, when
            no signature date is recorded, started) before this day.
        required_evidence: Evidence kinds every contract on the regime holds.
        subcontract_evidence: Further evidence kinds a subcontract holds.
        evidence_dated_before: Every piece of evidence must be dated before
            this day. ``None`` places no condition on the evidence date.
        scope_increase_ends_regime: When true, a contract whose value has
            grown beyond the increase the contract itself allows is treated
            as a new contract and leaves the regime.
    """

    contract_signed_before: date | None = None
    required_evidence: tuple[str, ...] = ()
    subcontract_evidence: tuple[str, ...] = ()
    evidence_dated_before: date | None = None
    scope_increase_ends_regime: bool = False


@dataclass(frozen=True)
class VatRegime:
    """One way a country taxes an activity's supplies, valid for a range of dates.

    Attributes:
        country_code: ISO 3166-1 alpha-2 code.
        code: House key, unique within the country.
        labels: Name per locale.
        activity: The activity the regime belongs to, for example
            ``construction_services``. Regimes of one activity are the
            alternatives a contract chooses between.
        tax_code: The tax seed line whose row in force supplies the nominal rate.
        base_fraction: Share of the consideration that is taxed, in (0, 1].
        input_credit: Whether VAT on the supplier's own costs is deductible.
        effective_from: First day the regime applies (inclusive).
        effective_to: Last day (inclusive), ``None`` for open.
        is_default: The regime a contract of this activity is on when it
            chooses none. At most one per activity on any day.
        eligibility: Conditions for choosing it, ``None`` when anyone may.
        legal_reference: Law, decree and article the regime comes from.
        source_url: Where it was read.
        read_date: ISO date the source was read.
        review_status: ``confirmed`` or ``needs_expert_review``. The second
            still applies; it travels with the regime to the screen.
        conditions: A short statement per locale shown beside the choice.
    """

    country_code: str
    code: str
    labels: Mapping[str, str]
    activity: str
    tax_code: str
    base_fraction: Decimal
    input_credit: bool
    effective_from: date
    effective_to: date | None
    is_default: bool
    eligibility: Eligibility | None
    legal_reference: str
    source_url: str
    read_date: str
    review_status: Literal["confirmed", "needs_expert_review"]
    conditions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Evidence:
    """One document a contract holds as evidence for its regime."""

    reference: str
    issued_on: date | None


@dataclass(frozen=True)
class ContractFacts:
    """What the eligibility check needs to know about one contract.

    Attributes:
        signed_on: Day the contract was signed, or ``None`` when not recorded.
        started_on: Day the contract started, used when ``signed_on`` is not
            recorded.
        is_subcontract: Whether the contract is a subcontract.
        evidence: Evidence held, by kind.
        original_value: Value at signature, ``None`` when not recorded.
        current_value: Value today, ``None`` when not recorded.
        allowed_increase_pct: The increase the contract itself allows, in
            percent of the original value, ``None`` when it states none.
    """

    signed_on: date | None
    started_on: date | None
    is_subcontract: bool
    evidence: Mapping[str, Evidence]
    original_value: Decimal | None = None
    current_value: Decimal | None = None
    allowed_increase_pct: Decimal | None = None


@dataclass(frozen=True)
class Finding:
    """One reason a contract does not qualify, with values for its sentence."""

    key: str
    params: Mapping[str, str]


# ── Finding the regimes ──────────────────────────────────────────────────────


def _country(value: str) -> str:
    return (value or "").strip().upper()


def regimes_for(country: str) -> tuple[VatRegime, ...]:
    """The regimes that ship for one country, empty when none do.

    Raises:
        TypeError: The country's data module exists and its ``REGIMES`` is not
            a tuple of :class:`VatRegime`.
    """
    wanted = _country(country)
    if not _COUNTRY_RE.match(wanted):
        return ()
    name = f"{__package__}.{_DATA_MODULE_PREFIX}{wanted.lower()}"
    if importlib.util.find_spec(name) is None:
        return ()
    regimes = getattr(importlib.import_module(name), "REGIMES", None)
    if not isinstance(regimes, tuple) or not all(isinstance(regime, VatRegime) for regime in regimes):
        raise TypeError(f"{name}.REGIMES must be a tuple of VatRegime")
    return regimes


def countries_with_regimes() -> tuple[str, ...]:
    """Every country that ships a regime data module, in code order."""
    found: list[str] = []
    for entry in files(__package__).iterdir():
        stem, _, suffix = entry.name.partition(".")
        if suffix != "py" or not stem.startswith(_DATA_MODULE_PREFIX):
            continue
        code = stem.removeprefix(_DATA_MODULE_PREFIX).upper()
        if _COUNTRY_RE.match(code):
            found.append(code)
    return tuple(sorted(found))


def _covers(regime: VatRegime, on: date) -> bool:
    return regime.effective_from <= on and (regime.effective_to is None or on <= regime.effective_to)


def in_force(regimes: Sequence[VatRegime], *, country: str, activity: str, on: date) -> list[VatRegime]:
    """The regimes of one activity a document dated ``on`` may be taxed under, default first."""
    wanted = _country(country)
    found = [
        regime
        for regime in regimes
        if _country(regime.country_code) == wanted and regime.activity == activity and _covers(regime, on)
    ]
    return sorted(found, key=lambda regime: (not regime.is_default, regime.code))


def lookup(regimes: Sequence[VatRegime], *, country: str, code: str) -> VatRegime | None:
    """The regime with this code in this country, whatever its dates."""
    wanted = _country(country)
    for regime in regimes:
        if _country(regime.country_code) == wanted and regime.code == code:
            return regime
    return None


def effective_rate_pct(regime: VatRegime, nominal_rate_pct: Decimal) -> Decimal:
    """The rate on the full consideration: the nominal rate times the base fraction.

    Exact, never rounded: 14 percent on 36 percent of the price is 5.04.
    """
    return nominal_rate_pct * regime.base_fraction


# ── Who may choose a regime ──────────────────────────────────────────────────


def eligibility_findings(regime: VatRegime, facts: ContractFacts) -> list[Finding]:
    """Every reason the contract may not be taxed under ``regime``; empty when it may.

    Nothing is assumed in the contract's favour: a date that is not recorded
    is a finding of its own, never a pass.
    """
    rules = regime.eligibility
    if rules is None:
        return []
    findings: list[Finding] = []

    if rules.contract_signed_before is not None:
        cutoff = rules.contract_signed_before.isoformat()
        contract_day = facts.signed_on or facts.started_on
        if contract_day is None:
            findings.append(Finding("contract_date_missing", {"cutoff": cutoff}))
        elif contract_day >= rules.contract_signed_before:
            findings.append(Finding("contract_too_late", {"cutoff": cutoff, "contract_date": contract_day.isoformat()}))

    wanted = list(rules.required_evidence)
    if facts.is_subcontract:
        wanted += [kind for kind in rules.subcontract_evidence if kind not in wanted]
    for kind in wanted:
        held = facts.evidence.get(kind)
        if held is None or not (held.reference or "").strip():
            findings.append(Finding("evidence_missing", {"evidence": kind}))
            continue
        if rules.evidence_dated_before is None:
            continue
        cutoff = rules.evidence_dated_before.isoformat()
        if held.issued_on is None:
            findings.append(Finding("evidence_date_missing", {"evidence": kind, "cutoff": cutoff}))
        elif held.issued_on >= rules.evidence_dated_before:
            findings.append(
                Finding(
                    "evidence_too_late", {"evidence": kind, "cutoff": cutoff, "issued_on": held.issued_on.isoformat()}
                )
            )

    if rules.scope_increase_ends_regime and facts.original_value is not None and facts.current_value is not None:
        grown = facts.current_value - facts.original_value
        if grown > 0:
            if facts.allowed_increase_pct is None:
                findings.append(
                    Finding(
                        "scope_increase_unjudged",
                        {"original_value": str(facts.original_value), "current_value": str(facts.current_value)},
                    )
                )
            else:
                limit = facts.original_value * (1 + facts.allowed_increase_pct / _HUNDRED)
                if facts.current_value > limit:
                    findings.append(
                        Finding(
                            "scope_increase_new_contract",
                            {
                                "original_value": str(facts.original_value),
                                "current_value": str(facts.current_value),
                                "allowed_increase_pct": str(facts.allowed_increase_pct),
                            },
                        )
                    )
    return findings


def window_findings(regime: VatRegime, regimes: Sequence[VatRegime], on: date) -> list[Finding]:
    """Whether a document dated ``on`` can be taxed under ``regime`` at all.

    Returns one ``not_in_force`` finding naming the regimes of the same
    activity that are in force that day, or nothing when ``regime`` is.
    """
    if _covers(regime, on):
        return []
    instead = in_force(regimes, country=regime.country_code, activity=regime.activity, on=on)
    return [
        Finding(
            "not_in_force",
            {
                "regime": regime.code,
                "on": on.isoformat(),
                "effective_from": regime.effective_from.isoformat(),
                "effective_to": regime.effective_to.isoformat() if regime.effective_to else "",
                "instead": ", ".join(other.code for other in instead),
            },
        )
    ]


# ── The table checked before anything is taxed from it ───────────────────────


def _regime_problems(regime: VatRegime) -> list[str]:
    problems: list[str] = []
    if not _COUNTRY_RE.match(_country(regime.country_code)):
        problems.append("country_code is not an ISO alpha-2 code")
    for name in ("code", "activity", "tax_code", "legal_reference"):
        if not (getattr(regime, name) or "").strip():
            problems.append(f"{name} is empty")
    if not regime.labels or any(not (text or "").strip() for text in regime.labels.values()):
        problems.append("labels are missing or blank")
    if not regime.source_url.startswith("https://"):
        problems.append("source_url is not an https address")
    if not (regime.base_fraction.is_finite() and Decimal(0) < regime.base_fraction <= 1):
        problems.append("base_fraction must lie in (0, 1]")
    if regime.effective_to is not None and regime.effective_to < regime.effective_from:
        problems.append("effective_to lies before effective_from")
    if regime.review_status not in _REVIEW_STATUSES:
        problems.append(f"review_status {regime.review_status!r} is not one of {_REVIEW_STATUSES}")
    try:
        date.fromisoformat(regime.read_date)
    except (TypeError, ValueError):
        problems.append(f"read_date {regime.read_date!r} is not an ISO date")
    rules = regime.eligibility
    if rules is not None:
        unknown = sorted(set(rules.required_evidence + rules.subcontract_evidence) - set(EVIDENCE_KINDS))
        if unknown:
            problems.append(f"unknown evidence kinds {unknown}")
    return problems


def validate_regimes(regimes: Sequence[VatRegime]) -> list[str]:
    """Everything that makes a regime table unsafe to tax from; empty for a sound one."""
    problems = [f"{regime.country_code}/{regime.code}: {p}" for regime in regimes for p in _regime_problems(regime)]
    seen: set[tuple[str, str]] = set()
    for regime in regimes:
        key = (_country(regime.country_code), regime.code)
        if key in seen:
            problems.append(f"{key[0]}/{key[1]}: code is used twice")
        seen.add(key)
    defaults = [regime for regime in regimes if regime.is_default]
    for index, first in enumerate(defaults):
        for second in defaults[index + 1 :]:
            if (_country(first.country_code), first.activity) != (_country(second.country_code), second.activity):
                continue
            first_ends = first.effective_to is not None and first.effective_to < second.effective_from
            second_ends = second.effective_to is not None and second.effective_to < first.effective_from
            if not (first_ends or second_ends):
                problems.append(f"{first.country_code}/{first.code}: two default regimes overlap with {second.code}")
    return problems
