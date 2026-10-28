# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the base-wage constraint on labor rate template payloads.

A template whose base wage is zero builds up to an all-in rate of ``0.00``.
That is a number, not ``None``, so a consumer asking "is this priced?" is told
yes and the labour hours are costed at nothing without a single flag. These
tests pin the schema constraint that refuses such a payload at the edge.

Pure Pydantic, no database, no ORM: the schemas validate on construction.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.labor_rates import rate_math
from app.modules.labor_rates.schemas import TemplateCreate, TemplateUpdate

D = Decimal


def _errors(exc: pytest.ExceptionInfo[ValidationError]) -> list[tuple[str, str]]:
    """Field name and error type for every complaint the payload drew."""
    return [(str(err["loc"][0]), err["type"]) for err in exc.value.errors()]


# ---------------------------------------------------------------------------
# What a zero wage actually costs, if it is allowed through
# ---------------------------------------------------------------------------


def test_a_zero_base_wage_builds_up_to_a_rate_that_reads_as_priced() -> None:
    """The reason the constraint exists: zero is a number, not an absence.

    Percentage on-costs are a share of the base wage, so they cannot rescue a
    zero: 30 per cent of nothing is nothing. The result is an all-in rate that
    every downstream check treats as a real price.
    """
    zero = rate_math.all_in_rate(D("0"), [rate_math.OnCost("Statutory", "percentage", D("30"))])
    assert zero == D("0.00")
    assert zero is not None  # the whole defect in one line

    priced = rate_math.all_in_rate(D("2500"), [rate_math.OnCost("Statutory", "percentage", D("30"))])
    assert priced == D("3250.00")


# ---------------------------------------------------------------------------
# TemplateCreate
# ---------------------------------------------------------------------------


def test_create_refuses_a_zero_base_wage() -> None:
    with pytest.raises(ValidationError) as exc:
        TemplateCreate(name="Plasterer", base_wage=D("0"), currency="EUR")
    assert ("base_wage", "greater_than") in _errors(exc)


def test_create_refuses_an_omitted_base_wage() -> None:
    """Omission is the payload that reported the defect, and it is separate.

    Constraining a field that still carries a default would leave this path
    open: Pydantic does not validate defaults, so ``Field(default=0, gt=0)``
    hands back a zero for a payload that never mentioned the wage. Only making
    the field required closes it, and only this test can tell the two apart.
    """
    with pytest.raises(ValidationError) as exc:
        TemplateCreate(name="Plasterer", currency="EUR")
    assert ("base_wage", "missing") in _errors(exc)


def test_create_refuses_a_negative_base_wage() -> None:
    with pytest.raises(ValidationError) as exc:
        TemplateCreate(name="Plasterer", base_wage=D("-1"), currency="EUR")
    assert ("base_wage", "greater_than") in _errors(exc)


def test_create_accepts_a_positive_base_wage() -> None:
    payload = TemplateCreate(name="Plasterer", base_wage=D("2500"), currency="EUR")
    assert payload.base_wage == D("2500")


# ---------------------------------------------------------------------------
# TemplateUpdate
# ---------------------------------------------------------------------------


def test_update_refuses_correcting_a_wage_down_to_zero() -> None:
    """Create-at-30-then-update-to-0 would otherwise reopen the same hole."""
    with pytest.raises(ValidationError) as exc:
        TemplateUpdate(base_wage=D("0"))
    assert ("base_wage", "greater_than") in _errors(exc)


def test_update_still_allows_leaving_the_wage_alone() -> None:
    """A rename must not have to restate the wage.

    ``None`` means "not part of this update" here, so the constraint has to
    apply to a supplied value without making the field mandatory.
    """
    payload = TemplateUpdate(name="Plasterer (night shift)")
    assert payload.base_wage is None
    assert "base_wage" not in payload.model_dump(exclude_unset=True)
