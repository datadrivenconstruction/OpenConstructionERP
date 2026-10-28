"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A tax charged on the price that includes it cannot be a percentage of the subtotal.

Brazilian BDI is the case that forces this. The composition the federal audit
court lays out is multiplicative, and its tax term divides rather than adds:

    BDI = [(1 + AC + S + R + G)(1 + DF)(1 + L) / (1 - I)] - 1

Everything before the division is an ordinary compounding cascade, which the
engine already does. The division is not. PIS, COFINS and ISS are levied on the
invoiced amount, so the amount they are levied on is the one that already
contains them, and recovering them as a flat percentage of the subtotal
under-recovers every time.

The gap is not academic. At the rates below it is a thousand reais on a hundred
thousand of direct cost, which is the contractor's margin on the job.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.methodology.cascade import (
    KIND_GROSS_UP,
    KIND_PERCENTAGE,
    CascadeError,
    CascadeSpec,
    MarkupStep,
    compute_cascade,
)

_CUSTO_DIRETO = {"custo_direto": Decimal("100000")}


def _spec(tax_kind: str, tax_rate: str) -> CascadeSpec:
    return CascadeSpec(
        slug="bdi-probe",
        currency="BRL",
        decimals=2,
        composites={},
        steps=(
            MarkupStep(
                key="administracao_central",
                label="Administracao central",
                category="overhead",
                kind=KIND_PERCENTAGE,
                rate=Decimal("4"),
                base=("custo_direto",),
            ),
            MarkupStep(
                key="despesas_financeiras",
                label="Despesas financeiras",
                category="other",
                kind=KIND_PERCENTAGE,
                rate=Decimal("1"),
                base=("custo_direto", "administracao_central"),
            ),
            MarkupStep(
                key="lucro",
                label="Lucro",
                category="profit",
                kind=KIND_PERCENTAGE,
                rate=Decimal("7"),
                base=("custo_direto", "administracao_central", "despesas_financeiras"),
            ),
            MarkupStep(
                key="tributos",
                label="Tributos",
                category="tax",
                kind=tax_kind,
                rate=Decimal(tax_rate),
                base=("custo_direto", "administracao_central", "despesas_financeiras", "lucro"),
            ),
        ),
    )


def _amounts(spec: CascadeSpec) -> dict[str, Decimal]:
    return {line.key: line.amount for line in compute_cascade(spec, _CUSTO_DIRETO).steps}


def test_the_steps_before_the_tax_compound_as_they_always_did() -> None:
    """The multiplicative part is an ordinary cascade and must not change."""
    amounts = _amounts(_spec(KIND_GROSS_UP, "9.25"))

    assert amounts["administracao_central"] == Decimal("4000.00")
    # 1% of 104 000, not of 100 000
    assert amounts["despesas_financeiras"] == Decimal("1040.00")
    # 7% of 105 040
    assert amounts["lucro"] == Decimal("7352.80")


def test_a_grossed_up_tax_is_the_share_of_a_total_that_does_not_exist_yet() -> None:
    """9.25 percent OF THE TOTAL, recovered from a subtotal of 112 392.80."""
    amounts = _amounts(_spec(KIND_GROSS_UP, "9.25"))

    # 112 392.80 * 9.25 / (100 - 9.25)
    assert amounts["tributos"] == Decimal("11456.02")


def test_the_grand_total_is_the_subtotal_divided_by_one_minus_the_rate() -> None:
    """The defining property. If this holds, the tax really is inside the price."""
    result = compute_cascade(_spec(KIND_GROSS_UP, "9.25"), _CUSTO_DIRETO)
    subtotal = Decimal("112392.80")

    assert result.grand_total == Decimal("123848.82")
    # Read back the other way: strip the rate off the total and the subtotal is
    # what is left. That is what "the tax is inside the price" means.
    net = (result.grand_total * (Decimal("100") - Decimal("9.25")) / Decimal("100")).quantize(Decimal("0.01"))
    assert net == subtotal


def test_the_naive_percentage_under_recovers_and_that_is_the_whole_point() -> None:
    """Same rate, same base, read the other way: 1 059.69 of margin gone."""
    grossed = _amounts(_spec(KIND_GROSS_UP, "9.25"))["tributos"]
    naive = _amounts(_spec(KIND_PERCENTAGE, "9.25"))["tributos"]

    assert naive == Decimal("10396.33")
    assert grossed - naive == Decimal("1059.69")


def test_a_rate_of_one_hundred_percent_is_refused_rather_than_dividing_by_zero() -> None:
    """There is no price that is entirely tax, and the engine must say so."""
    with pytest.raises(CascadeError, match="gross_up"):
        compute_cascade(_spec(KIND_GROSS_UP, "100"), _CUSTO_DIRETO)


def test_a_rate_above_one_hundred_percent_is_refused_too() -> None:
    """Left alone this returns a negative tax and a total below the subtotal."""
    with pytest.raises(CascadeError, match="gross_up"):
        compute_cascade(_spec(KIND_GROSS_UP, "120"), _CUSTO_DIRETO)


def test_a_zero_rate_grosses_up_to_nothing() -> None:
    """A contractor outside the regime carries the line at zero, not an error."""
    assert _amounts(_spec(KIND_GROSS_UP, "0"))["tributos"] == Decimal("0.00")
