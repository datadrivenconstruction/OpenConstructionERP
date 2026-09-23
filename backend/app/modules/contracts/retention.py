# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Retention held on a contract, worked out from its policy. Pure, no I/O.

Retention used to be one flat rate, ``Contract.retention_percent``, applied in
two places that disagreed as soon as the rate could change: each claim accrued
``period gross × rate`` and the continuation sheet printed ``current rate ×
work to date`` in column I. A policy that steps down at half complete breaks
that at once, so this module is the one place that says how much retention a
contract holds, and every figure is derived from it:

* :func:`compute_retention` takes work completed to date and stored materials
  per SoV line plus the contract sum, and returns what is held on work (G702
  line 5a), on stored materials (5b) and per line (G703 column I), with the
  line figures summing exactly to the totals.
* :func:`plan_release` says what an event such as substantial completion
  releases, as a percentage of what is held at that event.
* :func:`step_down_release` says what a recompute-mode rate reduction frees.

Two tier modes exist because contracts write both. **Prospective**: each band
of work is retained at the rate of the tier it fell in, so crossing 50% moves
only the work after the threshold to the lower rate and nothing already held
comes back. The figure depends only on how much work is complete, never on
how many claims it took to get there. **Recompute**: the current tier's rate
applies to all work to date, so crossing the threshold lowers what should be
held, and the difference is released as a ``rate_step_down`` that needs the
documents the pack lists (in the US, the surety's consent where there is a
bond). The founder decision of 22.09 makes prospective the default.

Percent complete is work completed over the contract sum to date, without
stored materials: a threshold such as "50% complete" is about the work, and
counting materials sitting on site would step the rate down before half the
work is done.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
HUNDRED = Decimal("100")
CENT = Decimal("0.01")
RATE_PLACES = Decimal("0.0001")

TIER_MODES = ("prospective", "recompute")
DEFAULT_TIER_MODE = "prospective"

#: The completion events a release is booked against. Every vocabulary the
#: code base grew maps onto one of these through :data:`RELEASE_EVENT_ALIASES`.
CANONICAL_RELEASE_EVENTS = ("substantial_completion", "final_completion", "defects_period_end")

#: Releases that are not a completion event: a recompute-mode rate reduction,
#: and retention exchanged for a bond.
OTHER_RELEASE_EVENTS = ("rate_step_down", "security_substituted")

#: Three vocabularies grew for the same events: the contract schema
#: (practical_completion, final_account, handover), the old release planner
#: (substantial_completion, punch_list_complete, defects_liability_end) and the
#: clause templates (substantial_completion, performance_certificate,
#: completion, practical_completion). ``completion`` is the NEC4 term for the
#: point the works are taken over, which is substantial completion. The FIDIC
#: Performance Certificate follows the end of the defects notification period,
#: and under clause 14.9 that expiry is what releases the second half of the
#: retention, so it maps to ``defects_period_end``, not to final completion.
RELEASE_EVENT_ALIASES: dict[str, str] = {
    "practical_completion": "substantial_completion",
    "handover": "substantial_completion",
    "taking_over": "substantial_completion",
    "completion": "substantial_completion",
    "final_account": "final_completion",
    "punch_list_complete": "final_completion",
    "performance_certificate": "defects_period_end",
    "defects_liability_end": "defects_period_end",
}

#: What a policy built from ``Contract.retention_percent`` says about itself.
#: It is the honest fallback when no pack answers, never another country's
#: figure.
CONTRACT_RATE_SOURCE = "contract.retention_percent"


def canonical_release_event(event: str | None) -> str:
    """The canonical name of a release event; an unknown name comes back normalised."""
    key = (event or "").strip().lower()
    return RELEASE_EVENT_ALIASES.get(key, key)


def _decimal(value: Any, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} is not a number: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"{name} is not a finite number: {value!r}")
    return result


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RetentionTier:
    """From ``from_percent_complete`` of the contract sum on, retain at ``rate`` percent."""

    from_percent_complete: Decimal
    rate: Decimal


@dataclass(frozen=True)
class RetentionPolicy:
    """How a contract accrues retention. Rates and thresholds are percentages."""

    tiers: tuple[RetentionTier, ...]
    tier_mode: str = DEFAULT_TIER_MODE
    #: ``None`` retains stored materials at the tier rate in force.
    stored_materials_rate: Decimal | None = None
    #: ``None`` means no cap; the contract's agreed security sum governs.
    cap_percent_of_contract_sum: Decimal | None = None
    source: str = ""
    statute_reference: str | None = None
    effective_date: str | None = None

    def rate_at(self, percent_complete: Decimal) -> Decimal:
        """The rate of the last tier whose threshold ``percent_complete`` has reached."""
        rate = self.tiers[0].rate
        for tier in self.tiers:
            if percent_complete >= tier.from_percent_complete:
                rate = tier.rate
        return rate


def flat_policy(rate: Any, *, source: str = CONTRACT_RATE_SOURCE) -> RetentionPolicy:
    """One tier at ``rate`` from the first dollar, which is what a flat percentage means."""
    return RetentionPolicy(
        tiers=(RetentionTier(ZERO, _decimal(rate or 0, name="rate")),),
        source=source,
    )


def policy_from_rule(rule: Mapping[str, Any] | None, *, fallback_rate: Any) -> RetentionPolicy:
    """Read an accrual rule: a ``RetentionSchedule.accrual_rule`` or a pack's ``retention_policy``.

    A rule without tiers is no policy, and the contract's own flat rate stands
    in, labelled as such. A rule that has tiers but cannot be read raises
    ``ValueError`` rather than falling back: a policy someone wrote and the
    engine quietly replaced with a flat rate would retain the wrong amount
    with nothing on screen to say so.

    Every refusal is a ``ValueError``, including the shapes that are not
    tiers at all. That is load-bearing rather than tidy: three callers guard
    this with ``except ValueError`` and act on the refusal, one of them by
    declining to write the row. A rule that raised something else would walk
    straight through all three, be stored, and then answer 500 on the route
    whose whole point is to answer 422.

    Raises:
        ValueError: tiers that are not a list, a tier that is not an object,
            tiers that are not numbers, a negative or over-100 rate, a first
            tier that does not start at 0, two tiers on one threshold, or an
            unknown ``tier_mode``.
    """
    if not rule:
        return flat_policy(fallback_rate)
    if not isinstance(rule, Mapping):
        # The guard below covers rule["tiers"] being the wrong shape. It did not
        # cover the rule ITSELF being the wrong shape, and this value arrives
        # from a JSON column and from a pack's own file, so it can be any JSON
        # value at all. A string, a list, a number and a bool each reached .get
        # on the line above and raised AttributeError rather than the ValueError
        # the docstring promises. Measured on all four before fixing.
        #
        # How reachable that is today, stated because the first version of this
        # comment implied more than it had shown. Every caller happens to check
        # the shape before calling: schemas.py annotates the field as a dict so
        # Pydantic refuses a non-dict before the validator runs, and the three
        # in service.py each either build the mapping locally or guard with
        # isinstance first. So no live path reaches this line, and the four
        # shapes were measured by calling the function directly.
        #
        # That does not make it decoration. The promise is this function's, not
        # its callers', three of them act on the refusal and one declines to
        # write a row on it, and a guard held up by four separate coincidences
        # elsewhere is one tidy-up away from gone. It is here so those checks
        # are free to be removed rather than load bearing.
        #
        # It sits after the falsy check rather than before it so that None, an
        # empty mapping and an empty string keep standing in the flat rate the
        # way they always have. Only the four shapes that used to leak change.
        raise ValueError("a retention rule must be an object naming tiers")
    if not rule.get("tiers"):
        return flat_policy(fallback_rate)

    declared = rule["tiers"]
    if not isinstance(declared, list):
        # A mapping iterates as its keys and a string as its characters, so
        # without this the next line asks a str for .get and the caller sees
        # an AttributeError it is not catching.
        raise ValueError("retention tiers must be a list")
    if any(not isinstance(tier, Mapping) for tier in declared):
        raise ValueError("every retention tier must be an object naming from_percent_complete and rate")
    tiers = sorted(
        (
            RetentionTier(
                _decimal(tier.get("from_percent_complete", 0), name="from_percent_complete"),
                _decimal(tier.get("rate"), name="rate"),
            )
            for tier in declared
        ),
        key=lambda tier: tier.from_percent_complete,
    )
    if tiers[0].from_percent_complete != ZERO:
        # Work below the first threshold would be retained at no rate at all.
        raise ValueError("the first retention tier must start at 0 percent complete")
    thresholds = [tier.from_percent_complete for tier in tiers]
    if len(set(thresholds)) != len(thresholds):
        raise ValueError("two retention tiers start at the same percent complete")
    for tier in tiers:
        if not ZERO <= tier.rate <= HUNDRED:
            raise ValueError(f"a retention rate must be between 0 and 100, not {tier.rate}")

    mode = str(rule.get("tier_mode") or DEFAULT_TIER_MODE)
    if mode not in TIER_MODES:
        raise ValueError(f"tier_mode must be one of {', '.join(TIER_MODES)}, not {mode!r}")

    stored_rate = rule.get("stored_materials_rate")
    cap = rule.get("cap") or None
    cap_percent = cap.get("percent_of_contract_sum") if isinstance(cap, Mapping) else None
    return RetentionPolicy(
        tiers=tuple(tiers),
        tier_mode=mode,
        stored_materials_rate=None
        if stored_rate in (None, "")
        else _decimal(stored_rate, name="stored_materials_rate"),
        cap_percent_of_contract_sum=None if cap_percent in (None, "") else _decimal(cap_percent, name="cap"),
        source=str(rule.get("source") or ""),
        statute_reference=rule.get("statute_reference"),
        effective_date=rule.get("effective_date"),
    )


def percent_complete(completed: Decimal, contract_sum: Decimal) -> Decimal:
    """Work completed as a percent of the contract sum; 0 when there is no sum."""
    if contract_sum <= ZERO:
        return ZERO
    return completed / contract_sum * HUNDRED


def work_retention(completed: Decimal, contract_sum: Decimal, policy: RetentionPolicy) -> Decimal:
    """Retention on the work completed to date, for the whole contract, unrounded.

    In prospective mode each band of work between two thresholds is retained
    at its tier's rate, so the result depends only on how far the work has
    got. In recompute mode, and whenever there is no contract sum to measure
    percent complete against, the rate in force applies to all of it.
    """
    completed = max(completed, ZERO)
    if policy.tier_mode == "recompute" or len(policy.tiers) == 1 or contract_sum <= ZERO:
        return completed * policy.rate_at(percent_complete(completed, contract_sum)) / HUNDRED

    held = ZERO
    for index, tier in enumerate(policy.tiers):
        band_start = contract_sum * tier.from_percent_complete / HUNDRED
        if completed <= band_start:
            break
        following = policy.tiers[index + 1] if index + 1 < len(policy.tiers) else None
        band_end = (
            completed if following is None else min(completed, contract_sum * following.from_percent_complete / HUNDRED)
        )
        held += (band_end - band_start) * tier.rate / HUNDRED
    return held


def allocate_cents(total: Decimal, weights: Mapping[Hashable, Decimal]) -> dict[Hashable, Decimal]:
    """Split ``total`` over ``weights`` pro rata, in cents that add up to ``total`` exactly.

    Largest remainder: every share is rounded down to the cent, and the cents
    left over go one each to the shares that lost the most in rounding, ties
    in the order the weights were given. Only positive weights take a share:
    a credit line has no retention of its own to carry. When no weight is
    positive every share is 0, and a nonzero ``total`` is reported by raising,
    since money with nowhere to go must not vanish.

    Raises:
        ValueError: ``total`` is not zero but no weight is positive.
    """
    total = _cents(total)
    shares: dict[Hashable, Decimal] = dict.fromkeys(weights, ZERO)
    positive = {key: weight for key, weight in weights.items() if weight > ZERO}
    weight_sum = sum(positive.values(), ZERO)
    if weight_sum == ZERO:
        if total != ZERO:
            raise ValueError(f"cannot allocate {total} over lines with no positive weight")
        return shares

    remainders: list[tuple[Decimal, int, Hashable]] = []
    for order, (key, weight) in enumerate(positive.items()):
        exact = total * weight / weight_sum
        floored = exact.quantize(CENT, rounding=ROUND_DOWN)
        shares[key] = floored
        remainders.append((exact - floored, order, key))
    left = int((total - sum(shares.values(), ZERO)) / CENT)
    # Largest remainder first, then input order, so equal remainders are stable.
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for _remainder, _order, key in remainders[:left]:
        shares[key] += CENT
    return shares


@dataclass(frozen=True)
class LineRetention:
    """G703 column I for one SoV line, split into work and stored materials."""

    retention_to_date: Decimal
    retention_stored_to_date: Decimal
    #: Effective percent over the line's work and stored materials, the rate
    #: a reader can multiply column G by to get column I.
    retention_rate: Decimal


@dataclass(frozen=True)
class RetentionPosition:
    """What a contract should hold at one claim, contract-wide and per line."""

    completed_to_date: Decimal
    stored_to_date: Decimal
    percent_complete: Decimal
    rate_now: Decimal
    work_retention: Decimal
    stored_retention: Decimal
    capped: bool
    lines: dict[Hashable, LineRetention]

    @property
    def total(self) -> Decimal:
        """G702 line 5 before any release is taken off it."""
        return self.work_retention + self.stored_retention


def compute_retention(
    completed_by_line: Mapping[Hashable, Any],
    *,
    contract_sum: Any,
    policy: RetentionPolicy,
    stored_by_line: Mapping[Hashable, Any] | None = None,
) -> RetentionPosition:
    """The retention a contract should hold, given work and stored materials per line.

    Args:
        completed_by_line: Work completed to date per SoV line (G703 D + E).
            A credit line's negative value reduces the contract's total but
            takes no share of the retention.
        contract_sum: The contract sum to date (G702 line 3), the base that
            percent complete and a cap are measured against.
        policy: See :func:`policy_from_rule`.
        stored_by_line: Stored materials balance per SoV line (G703 F).

    Returns:
        The contract-wide figures, rounded to cents, and one
        :class:`LineRetention` per line in ``completed_by_line`` or
        ``stored_by_line``, whose cents add up exactly to the totals. A cap
        cuts work retention first, then stored.
    """
    total_sum = _decimal(contract_sum or 0, name="contract_sum")
    completed = {key: _decimal(value or 0, name="completed") for key, value in completed_by_line.items()}
    stored = {key: max(_decimal(value or 0, name="stored"), ZERO) for key, value in (stored_by_line or {}).items()}

    completed_total = max(sum(completed.values(), ZERO), ZERO)
    stored_total = sum(stored.values(), ZERO)
    pct = percent_complete(completed_total, total_sum)
    rate_now = policy.rate_at(pct)

    work = _cents(work_retention(completed_total, total_sum, policy))
    stored_rate = policy.stored_materials_rate if policy.stored_materials_rate is not None else rate_now
    on_stored = _cents(stored_total * stored_rate / HUNDRED)

    capped = False
    if policy.cap_percent_of_contract_sum is not None:
        cap = _cents(max(total_sum, ZERO) * policy.cap_percent_of_contract_sum / HUNDRED)
        if work + on_stored > cap:
            capped = True
            work = min(work, cap)
            on_stored = min(on_stored, cap - work)

    keys = list(dict.fromkeys([*completed, *stored]))
    work_shares = allocate_cents(work, {key: completed.get(key, ZERO) for key in keys})
    stored_shares = allocate_cents(on_stored, {key: stored.get(key, ZERO) for key in keys})
    lines: dict[Hashable, LineRetention] = {}
    for key in keys:
        base = max(completed.get(key, ZERO), ZERO) + stored.get(key, ZERO)
        held = work_shares[key] + stored_shares[key]
        rate = (held / base * HUNDRED).quantize(RATE_PLACES, rounding=ROUND_HALF_UP) if base > ZERO else ZERO
        lines[key] = LineRetention(work_shares[key], stored_shares[key], rate)

    return RetentionPosition(
        completed_to_date=completed_total,
        stored_to_date=stored_total,
        percent_complete=pct.quantize(RATE_PLACES, rounding=ROUND_HALF_UP),
        rate_now=rate_now,
        work_retention=work,
        stored_retention=on_stored,
        capped=capped,
        lines=lines,
    )


def step_down_release(
    policy: RetentionPolicy,
    *,
    held_before: Any,
    required_now: Any,
    rate_before: Any,
    rate_now: Any,
) -> Decimal:
    """What a recompute-mode rate reduction releases; 0 in every other case.

    Only a lower rate frees retention. In prospective mode a threshold never
    lowers what is held on work already done. A requirement that falls while
    the rate stays put (a line corrected downwards) is left held for a person
    to look at: releasing money is not something a correction should do on
    its own, and ``pay_application.retention_matches_policy`` shows the gap.
    """
    if policy.tier_mode != "recompute":
        return ZERO
    if _decimal(rate_now or 0, name="rate_now") >= _decimal(rate_before or 0, name="rate_before"):
        return ZERO
    freed = _decimal(held_before or 0, name="held_before") - _decimal(required_now or 0, name="required_now")
    return max(_cents(freed), ZERO)


@dataclass(frozen=True)
class ReleasePlan:
    """What one release event pays out of retention held."""

    event: str
    held: Decimal
    percent_of_held: Decimal | None
    withheld_for_open_items: Decimal
    amount: Decimal
    remaining: Decimal
    required_documents: tuple[str, ...]
    required_documents_when_bonded: tuple[str, ...]
    statute_reference: str | None


def release_spec(release_rule: Mapping[str, Any] | None, event: str) -> Mapping[str, Any] | None:
    """The entry for ``event`` in a release rule or a pack's ``release_events``, by canonical name."""
    wanted = canonical_release_event(event)
    for spec in (release_rule or {}).get("events") or []:
        if canonical_release_event(spec.get("event")) == wanted:
            return spec
    return None


def _open_items_multiplier(spec: Mapping[str, Any]) -> Decimal:
    # The policy shape writes the multiplier flat, the pack shape nests it
    # with its own source; both mean the same thing.
    nested = spec.get("open_items_withholding")
    raw = nested.get("multiplier") if isinstance(nested, Mapping) else spec.get("withhold_open_items_multiplier")
    return _decimal(raw, name="open items multiplier") if raw not in (None, "") else Decimal("1")


def plan_release(
    held: Any,
    event: str,
    release_rule: Mapping[str, Any] | None = None,
    *,
    open_items_value: Any = 0,
    amount: Any = None,
) -> ReleasePlan:
    """What ``event`` releases from ``held``, the retention held at that event.

    The percentage is of what is held when the event happens, not of what was
    ever retained. A schedule of 50 then 100 therefore releases half and then
    the rest; the old planner promised "percent of the original" while being
    called with what was still held, so 50/30/20 released 50, 15 and 7 and
    kept 28 for ever.

    Args:
        held: Retention held at the event (G702 line 5 less releases billed).
        event: Any release event name; aliases are resolved.
        release_rule: ``RetentionSchedule.release_rule`` or a pack's
            ``release_events``. The event's entry gives the percentage, the
            open-items multiplier and the documents it needs.
        open_items_value: Estimated cost of work still open, withheld at the
            entry's multiplier (1 when it names none).
        amount: An explicit amount, for events that carry no percentage
            (``rate_step_down``) or a release a person sized by hand. It is
            still limited to what is held.

    Raises:
        ValueError: no ``amount`` was given and the rule has no percentage
            for the event, so there is nothing to compute it from.
    """
    canonical = canonical_release_event(event)
    spec = release_spec(release_rule, canonical) or {}
    held_now = max(_decimal(held or 0, name="held"), ZERO)

    percent: Decimal | None = None
    withheld = ZERO
    if amount is not None:
        gross = _decimal(amount, name="amount")
    else:
        raw = spec.get("release_percent_of_held")
        if raw in (None, ""):
            raise ValueError(f"no release percentage for {canonical!r}; give the amount")
        percent = min(max(_decimal(raw, name="release_percent_of_held"), ZERO), HUNDRED)
        gross = held_now * percent / HUNDRED
        open_items = max(_decimal(open_items_value or 0, name="open_items_value"), ZERO)
        withheld = _cents(open_items * _open_items_multiplier(spec))

    released = min(max(_cents(gross) - withheld, ZERO), _cents(held_now))
    return ReleasePlan(
        event=canonical,
        held=_cents(held_now),
        percent_of_held=percent,
        withheld_for_open_items=withheld,
        amount=released,
        remaining=_cents(held_now) - released,
        required_documents=tuple(spec.get("required_documents") or ()),
        required_documents_when_bonded=tuple(spec.get("required_documents_when_bonded") or ()),
        statute_reference=spec.get("statute_reference"),
    )


__all__ = [
    "CANONICAL_RELEASE_EVENTS",
    "CONTRACT_RATE_SOURCE",
    "DEFAULT_TIER_MODE",
    "OTHER_RELEASE_EVENTS",
    "RELEASE_EVENT_ALIASES",
    "TIER_MODES",
    "LineRetention",
    "ReleasePlan",
    "RetentionPolicy",
    "RetentionPosition",
    "RetentionTier",
    "allocate_cents",
    "canonical_release_event",
    "compute_retention",
    "flat_policy",
    "percent_complete",
    "plan_release",
    "policy_from_rule",
    "release_spec",
    "step_down_release",
    "work_retention",
]


@dataclass(frozen=True)
class ClaimRetention:
    """The retention figures one payment application prints.

    ``held`` is G702 line 5: what the policy requires on the work and stored
    materials to date, never less than what earlier claims already accrued,
    less the releases billed on this claim and the ones before it. ``lines``
    is G703 column I per SoV line, and adds up to ``held`` to the cent.
    """

    position: RetentionPosition
    #: Accrued by this claim, the claim's ``retention_amount``. Never negative:
    #: retention already held comes back only through a release.
    accrual: Decimal
    held: Decimal
    held_on_work: Decimal
    held_on_stored: Decimal
    completed_stored_to_date: Decimal
    lines: dict[Hashable, LineRetention]
    #: Retention accrued by this claim and the ones before it.
    accrued_to_date: Decimal
    #: Releases billed on this claim and the ones before it. Above
    #: ``accrued_to_date`` more was paid back than was ever held; ``held`` is
    #: then 0 and pay_application.retention_release_within_held says so.
    released_to_date: Decimal


def claim_retention(
    position: RetentionPosition,
    *,
    completed_by_line: Mapping[Hashable, Any],
    stored_by_line: Mapping[Hashable, Any] | None = None,
    accrued_before: Any,
    released_to_date: Any,
) -> ClaimRetention:
    """G702 line 5, 5a and 5b and G703 column I for one claim, from its policy position.

    Args:
        position: :func:`compute_retention` over the claim's work and stored
            materials to date.
        completed_by_line: The same work to date per SoV line, the weights
            column I is split by.
        stored_by_line: The same stored materials per SoV line.
        accrued_before: The retention the claims before this one accrued.
        released_to_date: The releases billed on this claim and the ones
            before it.

    A release takes retention off line 5 and so off column I on every line
    pro rata, stored materials last: retention on materials not yet built in
    is the last to go, because the materials are not yet part of the work.
    """
    required = position.total
    before = _cents(_decimal(accrued_before or 0, name="accrued_before"))
    released = _cents(_decimal(released_to_date or 0, name="released_to_date"))
    accrual = max(required - before, ZERO)
    held = max(before + accrual - released, ZERO)
    on_stored = min(position.stored_retention, held)
    on_work = held - on_stored

    completed = {key: _decimal(value or 0, name="completed") for key, value in completed_by_line.items()}
    stored = {key: max(_decimal(value or 0, name="stored"), ZERO) for key, value in (stored_by_line or {}).items()}
    keys = list(dict.fromkeys([*completed, *stored]))
    work_weights = {key: completed.get(key, ZERO) for key in keys}
    stored_weights = {key: stored.get(key, ZERO) for key in keys}
    if on_work > ZERO and not any(weight > ZERO for weight in work_weights.values()):
        # Held on work with no work left to carry it (every line credited
        # back): it sits on the lines that still have something on them.
        work_weights = {key: max(completed.get(key, ZERO), ZERO) + stored.get(key, ZERO) for key in keys}
    if on_work > ZERO and not any(weight > ZERO for weight in work_weights.values()):
        work_weights = dict.fromkeys(keys, Decimal("1"))
    work_shares = allocate_cents(on_work, work_weights) if keys else {}
    stored_shares = allocate_cents(on_stored, stored_weights) if keys else {}

    lines: dict[Hashable, LineRetention] = {}
    for key in keys:
        base = max(completed.get(key, ZERO), ZERO) + stored.get(key, ZERO)
        line_held = work_shares[key] + stored_shares[key]
        rate = (line_held / base * HUNDRED).quantize(RATE_PLACES, rounding=ROUND_HALF_UP) if base > ZERO else ZERO
        lines[key] = LineRetention(work_shares[key], stored_shares[key], rate)

    completed_total = sum(completed.values(), ZERO)
    stored_total = sum(stored.values(), ZERO)
    return ClaimRetention(
        position=position,
        accrual=accrual,
        held=held,
        held_on_work=on_work,
        held_on_stored=on_stored,
        completed_stored_to_date=_cents(completed_total + stored_total),
        lines=lines,
        accrued_to_date=before + accrual,
        released_to_date=released,
    )
