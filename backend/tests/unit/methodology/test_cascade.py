# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure markup-cascade engine (methodology, section 5).

Covers:

* The Uzbekistan reference cascade (the canonical end-to-end case): a composite
  SMR plus five ordered percentage steps with explicit per-step base-sets,
  asserted to the cent with round-per-step / feed-forward semantics.
* A simple international-style flat cascade (overhead -> profit -> VAT), proving
  the engine generalizes beyond the UZ scheme.
* A fixed-amount step (``kind == "fixed"``).
* A rounding edge case that distinguishes ROUND_HALF_UP from banker's rounding.
* Validation: unknown token, forward reference, self reference, duplicate step
  key, composite referencing a non-existent leaf base, and unknown kind all
  raise :class:`CascadeError`.

This module imports the engine from the app package and therefore runs under the
backend's Python 3.12 test environment (CI). The same math is also validated
standalone on local Python 3.11 by loading ``cascade.py`` directly via
``importlib`` (the full backend cannot import on 3.11 because of PEP 695 syntax
elsewhere in the tree).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.methodology.cascade import (
    CascadeError,
    CascadeResult,
    CascadeSpec,
    MarkupStep,
    compute_cascade,
)


def _by_key(result: CascadeResult) -> dict[str, Decimal]:
    """Map each step key to its rounded amount for concise assertions."""
    return {step.key: step.amount for step in result.steps}


# ── 1. Uzbekistan reference cascade ──────────────────────────────────────


def _uz_spec() -> CascadeSpec:
    return CascadeSpec(
        slug="uzbekistan",
        currency="UZS",
        decimals=2,
        composites={"SMR": ("labor", "machinery", "materials")},
        steps=(
            MarkupStep(
                key="other_temp_winter",
                label="Other / temporary / winter",
                category="temp_winter",
                kind="percentage",
                rate=Decimal("10"),
                base=("SMR",),
            ),
            MarkupStep(
                key="contractor_other",
                label="Contractor other costs",
                category="contractor_other",
                kind="percentage",
                rate=Decimal("5"),
                base=("SMR", "other_temp_winter"),
            ),
            MarkupStep(
                key="insurance",
                label="Insurance",
                category="insurance",
                kind="percentage",
                rate=Decimal("0.32"),
                base=("SMR", "equipment", "other_temp_winter", "contractor_other"),
            ),
            MarkupStep(
                key="contingency",
                label="Contingency",
                category="contingency",
                kind="percentage",
                rate=Decimal("2"),
                base=(
                    "SMR",
                    "equipment",
                    "other_temp_winter",
                    "contractor_other",
                    "insurance",
                ),
            ),
            MarkupStep(
                key="vat",
                label="VAT",
                category="tax",
                kind="percentage",
                rate=Decimal("12"),
                base=(
                    "SMR",
                    "equipment",
                    "other_temp_winter",
                    "contractor_other",
                    "insurance",
                    "contingency",
                ),
            ),
        ),
    )


def test_uzbekistan_reference_cascade() -> None:
    bases = {
        "labor": Decimal("100000"),
        "machinery": Decimal("50000"),
        "materials": Decimal("200000"),
        "equipment": Decimal("150000"),
    }
    result = compute_cascade(_uz_spec(), bases)

    # Composite SMR = labor + machinery + materials.
    assert result.composites["SMR"] == Decimal("350000.00")

    amounts = _by_key(result)
    assert amounts["other_temp_winter"] == Decimal("35000.00")
    assert amounts["contractor_other"] == Decimal("19250.00")
    assert amounts["insurance"] == Decimal("1773.60")
    assert amounts["contingency"] == Decimal("11120.47")
    assert amounts["vat"] == Decimal("68057.29")

    assert result.direct_total == Decimal("500000.00")
    # markup_total = 35000.00 + 19250.00 + 1773.60 + 11120.47 + 68057.29
    assert result.markup_total == Decimal("135201.36")
    assert result.grand_total == Decimal("635201.36")

    # Running total accumulates direct_total + rounded step amounts in order.
    running = [step.running_total for step in result.steps]
    assert running == [
        Decimal("535000.00"),  # 500000.00 + 35000.00
        Decimal("554250.00"),  # + 19250.00
        Decimal("556023.60"),  # + 1773.60
        Decimal("567144.07"),  # + 11120.47
        Decimal("635201.36"),  # + 68057.29
    ]


def test_uzbekistan_step_base_amounts() -> None:
    """Each step's resolved base_amount is the sum it applied the rate to."""
    bases = {
        "labor": Decimal("100000"),
        "machinery": Decimal("50000"),
        "materials": Decimal("200000"),
        "equipment": Decimal("150000"),
    }
    result = compute_cascade(_uz_spec(), bases)
    base_amounts = {step.key: step.base_amount for step in result.steps}

    assert base_amounts["other_temp_winter"] == Decimal("350000.00")  # SMR
    assert base_amounts["contractor_other"] == Decimal("385000.00")  # SMR + 35000
    # SMR + equipment + 35000 + 19250 = 350000 + 150000 + 35000 + 19250
    assert base_amounts["insurance"] == Decimal("554250.00")
    # previous + insurance(1773.60)
    assert base_amounts["contingency"] == Decimal("556023.60")
    # previous + contingency(11120.47)
    assert base_amounts["vat"] == Decimal("567144.07")


# ── 2. Simple international-style flat cascade ────────────────────────────


def test_international_flat_cascade() -> None:
    spec = CascadeSpec(
        slug="international",
        currency="EUR",
        decimals=2,
        composites={},
        steps=(
            MarkupStep(
                key="overhead",
                label="Overhead",
                category="overhead",
                kind="percentage",
                rate=Decimal("10"),
                base=("direct",),
            ),
            MarkupStep(
                key="profit",
                label="Profit",
                category="profit",
                kind="percentage",
                rate=Decimal("8"),
                base=("direct", "overhead"),
            ),
            MarkupStep(
                key="vat",
                label="VAT",
                category="tax",
                kind="percentage",
                rate=Decimal("20"),
                base=("direct", "overhead", "profit"),
            ),
        ),
    )
    result = compute_cascade(spec, {"direct": Decimal("1000")})

    amounts = _by_key(result)
    # overhead = 10% of 1000 = 100.00
    assert amounts["overhead"] == Decimal("100.00")
    # profit = 8% of (1000 + 100) = 88.00
    assert amounts["profit"] == Decimal("88.00")
    # vat = 20% of (1000 + 100 + 88) = 237.60
    assert amounts["vat"] == Decimal("237.60")

    assert result.direct_total == Decimal("1000.00")
    assert result.markup_total == Decimal("425.60")
    assert result.grand_total == Decimal("1425.60")


# ── 3. Fixed-amount step ──────────────────────────────────────────────────


def test_fixed_amount_step() -> None:
    spec = CascadeSpec(
        slug="fixed-demo",
        currency="USD",
        decimals=2,
        composites={},
        steps=(
            MarkupStep(
                key="mobilization",
                label="Mobilization (lump sum)",
                category="other",
                kind="fixed",
                amount=Decimal("2500.005"),  # rounds to 2500.01 (HALF_UP)
                base=(),
            ),
            MarkupStep(
                key="profit",
                label="Profit",
                category="profit",
                kind="percentage",
                rate=Decimal("10"),
                # Applies on top of direct cost AND the fixed mobilization step.
                base=("direct", "mobilization"),
            ),
        ),
    )
    result = compute_cascade(spec, {"direct": Decimal("1000")})

    amounts = _by_key(result)
    # Fixed amount is rounded HALF_UP and ignores rate.
    assert amounts["mobilization"] == Decimal("2500.01")
    fixed_step = result.steps[0]
    assert fixed_step.kind == "fixed"
    assert fixed_step.rate == Decimal("0")
    assert fixed_step.base_amount == Decimal("0.00")
    # profit = 10% of (1000 + 2500.01) = 350.001 -> 350.00
    assert amounts["profit"] == Decimal("350.00")

    assert result.direct_total == Decimal("1000.00")
    assert result.markup_total == Decimal("2850.01")
    assert result.grand_total == Decimal("3850.01")


# ── 4. Rounding edge (ROUND_HALF_UP, not banker's) ────────────────────────


def test_round_half_up_third_decimal() -> None:
    """A rate yielding a .xx5 third decimal must round UP, not to-even.

    100 * 12.345 / 100 = 12.345 -> 12.35 under ROUND_HALF_UP (banker's rounding
    would give 12.34, since 4 is even). And 100 * 2.345 / 100 = 2.345 -> 2.35
    (banker's would give 2.34). Asserting 12.35 / 2.35 proves HALF_UP.
    """
    spec = CascadeSpec(
        slug="rounding",
        currency="EUR",
        decimals=2,
        composites={},
        steps=(
            MarkupStep(
                key="up_even_boundary",
                label="rate -> .345",
                category="other",
                kind="percentage",
                rate=Decimal("12.345"),
                base=("direct",),
            ),
            MarkupStep(
                key="up_odd_boundary",
                label="rate -> .345 (odd preceding digit)",
                category="other",
                kind="percentage",
                rate=Decimal("2.345"),
                base=("direct",),
            ),
        ),
    )
    result = compute_cascade(spec, {"direct": Decimal("100")})
    amounts = _by_key(result)
    assert amounts["up_even_boundary"] == Decimal("12.35")
    assert amounts["up_odd_boundary"] == Decimal("2.35")


def test_round_half_up_with_zero_decimals() -> None:
    """decimals=0 rounds to whole units, half up."""
    spec = CascadeSpec(
        slug="whole",
        currency="JPY",
        decimals=0,
        composites={},
        steps=(
            MarkupStep(
                key="tax",
                label="Tax",
                category="tax",
                kind="percentage",
                rate=Decimal("0.5"),  # 0.5% of 100 = 0.5 -> 1 (HALF_UP)
                base=("direct",),
            ),
        ),
    )
    result = compute_cascade(spec, {"direct": Decimal("100")})
    assert _by_key(result)["tax"] == Decimal("1")
    assert result.grand_total == Decimal("101")


# ── 5. Validation ─────────────────────────────────────────────────────────


def test_unknown_token_raises() -> None:
    spec = CascadeSpec(
        slug="bad",
        currency="EUR",
        steps=(
            MarkupStep(
                key="overhead",
                label="Overhead",
                category="overhead",
                kind="percentage",
                rate=Decimal("10"),
                base=("nonexistent",),
            ),
        ),
    )
    with pytest.raises(CascadeError, match="unknown token 'nonexistent'"):
        compute_cascade(spec, {"direct": Decimal("1000")})


def test_forward_reference_raises() -> None:
    spec = CascadeSpec(
        slug="bad",
        currency="EUR",
        steps=(
            MarkupStep(
                key="overhead",
                label="Overhead",
                category="overhead",
                kind="percentage",
                rate=Decimal("10"),
                # References a step that appears LATER in the order.
                base=("direct", "profit"),
            ),
            MarkupStep(
                key="profit",
                label="Profit",
                category="profit",
                kind="percentage",
                rate=Decimal("8"),
                base=("direct",),
            ),
        ),
    )
    with pytest.raises(CascadeError, match="forward-references step 'profit'"):
        compute_cascade(spec, {"direct": Decimal("1000")})


def test_self_reference_raises() -> None:
    spec = CascadeSpec(
        slug="bad",
        currency="EUR",
        steps=(
            MarkupStep(
                key="overhead",
                label="Overhead",
                category="overhead",
                kind="percentage",
                rate=Decimal("10"),
                base=("direct", "overhead"),  # references itself
            ),
        ),
    )
    with pytest.raises(CascadeError, match="references itself"):
        compute_cascade(spec, {"direct": Decimal("1000")})


def test_duplicate_step_key_raises() -> None:
    spec = CascadeSpec(
        slug="bad",
        currency="EUR",
        steps=(
            MarkupStep(
                key="overhead",
                label="Overhead",
                category="overhead",
                kind="percentage",
                rate=Decimal("10"),
                base=("direct",),
            ),
            MarkupStep(
                key="overhead",  # duplicate
                label="Overhead again",
                category="overhead",
                kind="percentage",
                rate=Decimal("5"),
                base=("direct",),
            ),
        ),
    )
    with pytest.raises(CascadeError, match="duplicate step key 'overhead'"):
        compute_cascade(spec, {"direct": Decimal("1000")})


def test_composite_bad_leaf_raises() -> None:
    spec = CascadeSpec(
        slug="bad",
        currency="UZS",
        composites={"SMR": ("labor", "ghost")},  # 'ghost' is not a base
        steps=(),
    )
    with pytest.raises(CascadeError, match="composite 'SMR' references unknown leaf base 'ghost'"):
        compute_cascade(spec, {"labor": Decimal("100")})


def test_unknown_kind_raises() -> None:
    spec = CascadeSpec(
        slug="bad",
        currency="EUR",
        steps=(
            MarkupStep(
                key="overhead",
                label="Overhead",
                category="overhead",
                kind="multiplicative",  # not a valid kind
                rate=Decimal("10"),
                base=("direct",),
            ),
        ),
    )
    with pytest.raises(CascadeError, match="unknown kind 'multiplicative'"):
        compute_cascade(spec, {"direct": Decimal("1000")})


def test_float_base_rejected() -> None:
    """Floats are rejected to keep the engine exact."""
    spec = CascadeSpec(slug="x", currency="EUR", steps=())
    with pytest.raises(CascadeError, match="must be a Decimal"):
        compute_cascade(spec, {"direct": 1000.0})  # type: ignore[dict-item]


def test_cascade_error_is_value_error() -> None:
    """CascadeError subclasses ValueError so broad handlers still catch it."""
    assert issubclass(CascadeError, ValueError)
