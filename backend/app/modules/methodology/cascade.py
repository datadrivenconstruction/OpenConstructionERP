# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure markup-cascade engine for the estimating-methodology module.

This is the deterministic math core that the whole methodology feature depends
on. It computes an ordered markup cascade where each step applies to an
EXPLICIT set of prior amounts (a leaf base, a named composite, or an earlier
step), unlike the existing binary direct_cost/cumulative markup model.

Design constraints (intentional, see internal design note ESTIMATE_METHODOLOGIES_PLAN
section 5):

* Standard library only - ``decimal``, ``dataclasses``, ``typing``. No imports
  from ``app.*`` and no third-party packages, so this single file can be loaded
  and unit-tested standalone via ``importlib`` on Python 3.11 (the local
  interpreter), while the rest of the backend requires Python 3.12.
* No PEP 695 ``type X = ...`` aliases (3.12+ only). ``from __future__ import
  annotations`` keeps every annotation a string so nothing is evaluated at
  import time.
* All money is :class:`decimal.Decimal`; never ``float``. Each step result is
  quantized to ``decimals`` places with ``ROUND_HALF_UP`` IMMEDIATELY, and
  later steps that reference an earlier step consume its already-rounded amount
  (round-per-step, feed-forward).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

__all__ = [
    "CascadeError",
    "MarkupStep",
    "CascadeSpec",
    "StepResult",
    "CascadeResult",
    "compute_cascade",
]

# Allowed step kinds.
KIND_PERCENTAGE = "percentage"
KIND_FIXED = "fixed"
#: A rate levied on the total that already contains it, recovered from a
#: subtotal that does not. ``base * rate / (100 - rate)``, so the grand total
#: comes out as ``subtotal / (1 - rate)``. Brazilian BDI needs this for PIS,
#: COFINS and ISS: they are charged on the invoiced amount, and taking the same
#: percentage of the subtotal under-recovers on every job.
KIND_GROSS_UP = "gross_up"
_VALID_KINDS = frozenset({KIND_PERCENTAGE, KIND_FIXED, KIND_GROSS_UP})


class CascadeError(ValueError):
    """Raised when a cascade specification is invalid.

    Subclasses :class:`ValueError` so callers that only catch ``ValueError``
    still handle it, while code that wants to distinguish cascade-spec problems
    from other value errors can catch this type specifically.
    """


@dataclass(frozen=True)
class MarkupStep:
    """A single ordered markup step.

    Attributes:
        key: Unique identifier of the step. Later steps may reference this key
            in their ``base`` to apply on top of this step's rounded amount.
        label: Human-readable name (display only).
        category: Classification bucket (e.g. ``overhead``, ``temp_winter``,
            ``insurance``, ``contingency``, ``tax``, ``profit``, ``other``).
            Free-form; not validated here.
        kind: ``"percentage"`` or ``"fixed"``.
        rate: Percentage rate used when ``kind == "percentage"``. Expressed as a
            percent, e.g. ``Decimal("0.32")`` means 0.32 percent. Ignored for
            fixed steps.
        amount: Fixed amount used when ``kind == "fixed"``. Ignored for
            percentage steps.
        base: Tokens this step applies to. Each token is a leaf base key, a
            composite key, or the key of an EARLIER step. May be empty for a
            fixed step (a fixed step does not need a base).
        threshold: Optional floor for a percentage step: when the step's base is
            at or below it the step charges nothing, above it the full rate on
            the whole base (a statutory levy on works over a stated value).
    """

    key: str
    label: str
    category: str
    kind: str
    rate: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    base: tuple[str, ...] = ()
    threshold: Decimal | None = None


@dataclass(frozen=True)
class CascadeSpec:
    """The calc part of a methodology: composites + ordered markup steps.

    Attributes:
        slug: Methodology identifier (informational).
        currency: ISO currency code (informational; the engine is
            currency-agnostic and never converts).
        decimals: Number of fractional digits to round every monetary value to.
        composites: Named sums of leaf base keys, e.g.
            ``{"SMR": ("labor", "machinery", "materials")}``. A composite's
            members must all be leaf base keys present in ``bases`` at compute
            time.
        steps: Ordered markup steps.
    """

    slug: str
    currency: str
    decimals: int = 2
    composites: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    steps: tuple[MarkupStep, ...] = ()


@dataclass(frozen=True)
class StepResult:
    """The computed outcome of one :class:`MarkupStep`.

    Attributes:
        key: The step key.
        label: The step label.
        category: The step category.
        kind: The step kind.
        rate: The percentage rate applied (``Decimal("0")`` for fixed steps).
        base_amount: The resolved sum of the step's base tokens that the rate
            applied to (``Decimal("0")`` for fixed steps with no base).
        amount: The rounded step result.
        running_total: ``direct_total`` plus the sum of all step amounts up to
            and including this step.
    """

    key: str
    label: str
    category: str
    kind: str
    rate: Decimal
    base_amount: Decimal
    amount: Decimal
    running_total: Decimal


@dataclass(frozen=True)
class CascadeResult:
    """The full result of computing a cascade.

    Attributes:
        bases: The (quantized) leaf base amounts as supplied.
        composites: Resolved (quantized) composite sums, keyed by composite name.
        steps: One :class:`StepResult` per spec step, in order.
        direct_total: Sum of all leaf base amounts.
        markup_total: Sum of all rounded step amounts.
        grand_total: ``direct_total + markup_total``.
    """

    bases: dict[str, Decimal]
    composites: dict[str, Decimal]
    steps: list[StepResult]
    direct_total: Decimal
    markup_total: Decimal
    grand_total: Decimal


def _quantizer(decimals: int) -> Decimal:
    """Return the ``Decimal`` exponent template for ``decimals`` places."""
    if decimals < 0:
        raise CascadeError(f"decimals must be non-negative, got {decimals}")
    if decimals == 0:
        return Decimal(1)
    return Decimal(1).scaleb(-decimals)


def _round(value: Decimal, quant: Decimal) -> Decimal:
    """Quantize ``value`` with ROUND_HALF_UP to the given exponent template."""
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _coerce_decimal(value: object, what: str) -> Decimal:
    """Coerce ``value`` to ``Decimal`` (accepting int/str), or raise CascadeError.

    Floats are rejected to keep the engine exact; callers must pass Decimals
    (or ints/strings) for monetary inputs.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly.
        raise CascadeError(f"{what} must be a Decimal, got bool")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception as exc:  # noqa: BLE001 - re-raised as a clear error.
            raise CascadeError(f"{what} is not a valid number: {value!r}") from exc
    raise CascadeError(f"{what} must be a Decimal (or int/str), got {type(value).__name__}")


def compute_cascade(spec: CascadeSpec, bases: Mapping[str, Decimal]) -> CascadeResult:
    """Compute the ordered markup cascade for one scope.

    OWNERSHIP. This is the reusable estimating methodology of a company or a
    project. It is NOT the markup stack of a bill. A bill's markup lines are
    :class:`~app.modules.boq.models.BOQMarkup` rows and their amounts come from
    :func:`app.modules.boq.service._calculate_markup_amounts`, which is
    authoritative for anything a bill puts its name to. The bridge runs one
    way: a methodology may seed a bill's markup lines. Nothing here is summed
    into a bill's total. Two engines with stated, different jobs is the
    intended arrangement; two engines with the same job is what it avoids.

    ROUNDING. Every step here is quantized immediately (see the module
    docstring) and later steps consume the rounded amount. The bill's cascade
    keeps full precision to the rollup and quantizes once. On the same inputs
    the two differ by cents, deliberately. They are not reconciled, because
    changing either moves the total of estimates already stored in customer
    databases, which is its own decision with its own migration.

    Args:
        spec: The cascade specification (composites + ordered steps).
        bases: Leaf direct-cost amounts keyed by leaf base name. Values may be
            ``Decimal`` (preferred), ``int``, or numeric ``str``; ``float`` is
            rejected to keep arithmetic exact.

    Returns:
        A :class:`CascadeResult` with the resolved bases/composites, per-step
        results, and the direct/markup/grand totals.

    Raises:
        CascadeError: For any invalid specification - unknown token, forward or
            self reference, duplicate step key, a composite that references a
            non-existent leaf base, or an unknown step kind.
    """
    quant = _quantizer(spec.decimals)

    # Resolve and quantize the leaf bases up front.
    resolved_bases: dict[str, Decimal] = {}
    for name, raw in bases.items():
        resolved_bases[name] = _round(_coerce_decimal(raw, f"base {name!r}"), quant)

    # Validate + resolve composites against the leaf bases.
    resolved_composites: dict[str, Decimal] = {}
    for comp_name, members in spec.composites.items():
        if comp_name in resolved_bases:
            raise CascadeError(f"composite {comp_name!r} collides with a leaf base of the same name")
        total = Decimal(0)
        for member in members:
            if member not in resolved_bases:
                raise CascadeError(f"composite {comp_name!r} references unknown leaf base {member!r}")
            total += resolved_bases[member]
        resolved_composites[comp_name] = _round(total, quant)

    direct_total = _round(sum(resolved_bases.values(), Decimal(0)), quant)

    # Walk the steps in order. A step may reference a leaf base, a composite, or
    # the rounded amount of any EARLIER step (by key). We build the set of legal
    # tokens incrementally so any reference to the current or a later step is a
    # forward/self reference and fails.
    seen_step_keys: set[str] = set()
    step_amounts: dict[str, Decimal] = {}
    step_results: list[StepResult] = []
    running_total = direct_total
    markup_total = Decimal(0)

    for index, step in enumerate(spec.steps):
        if step.kind not in _VALID_KINDS:
            raise CascadeError(
                f"step {step.key!r} has unknown kind {step.kind!r}; expected one of {sorted(_VALID_KINDS)}"
            )
        if step.key in seen_step_keys:
            raise CascadeError(f"duplicate step key {step.key!r}")
        if step.key in resolved_bases or step.key in resolved_composites:
            raise CascadeError(f"step key {step.key!r} collides with a base or composite name")

        base_amount = Decimal(0)
        for token in step.base:
            if token in resolved_bases:
                base_amount += resolved_bases[token]
            elif token in resolved_composites:
                base_amount += resolved_composites[token]
            elif token in step_amounts:
                base_amount += step_amounts[token]
            elif token == step.key:
                raise CascadeError(f"step {step.key!r} references itself in its base")
            elif _is_later_step(spec.steps, token, index):
                raise CascadeError(
                    f"step {step.key!r} forward-references step {token!r} (a step may only reference earlier steps)"
                )
            else:
                raise CascadeError(
                    f"step {step.key!r} references unknown token {token!r} (not a base, composite, or earlier step)"
                )

        base_amount = _round(base_amount, quant)

        if step.kind == KIND_PERCENTAGE:
            amount = _round(base_amount * step.rate / Decimal(100), quant)
            if step.threshold is not None and base_amount <= step.threshold:
                amount = Decimal(0)
            applied_rate = step.rate
        elif step.kind == KIND_GROSS_UP:
            if step.rate >= Decimal(100):
                raise CascadeError(
                    f"step {step.key!r} is a gross_up at {step.rate}%; a rate of 100% or more has no "
                    f"price to be a share of (it would divide by zero or return a negative tax)"
                )
            amount = _round(base_amount * step.rate / (Decimal(100) - step.rate), quant)
            applied_rate = step.rate
        else:  # KIND_FIXED
            amount = _round(_coerce_decimal(step.amount, f"step {step.key!r} amount"), quant)
            applied_rate = Decimal(0)

        seen_step_keys.add(step.key)
        step_amounts[step.key] = amount
        markup_total += amount
        running_total += amount

        step_results.append(
            StepResult(
                key=step.key,
                label=step.label,
                category=step.category,
                kind=step.kind,
                rate=applied_rate,
                base_amount=base_amount,
                amount=amount,
                running_total=running_total,
            )
        )

    markup_total = _round(markup_total, quant)
    grand_total = _round(direct_total + markup_total, quant)

    return CascadeResult(
        bases=resolved_bases,
        composites=resolved_composites,
        steps=step_results,
        direct_total=direct_total,
        markup_total=markup_total,
        grand_total=grand_total,
    )


def _is_later_step(steps: tuple[MarkupStep, ...], token: str, current_index: int) -> bool:
    """Return True if ``token`` names a step at ``current_index`` or later.

    Used purely to produce a precise "forward reference" error message instead
    of a generic "unknown token" one.
    """
    for later_index in range(current_index, len(steps)):
        if steps[later_index].key == token:
            return True
    return False
