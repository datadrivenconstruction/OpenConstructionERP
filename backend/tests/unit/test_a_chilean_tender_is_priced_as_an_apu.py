"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Chile must be able to price the way a Chilean public client reads a price.

Reported from a self-hosted install in Chile: the platform carried the peso,
the 19 percent IVA and the country, but wired Chile to the flat method, direct
cost plus overhead plus profit plus tax. That reaches a total. It is not an
analisis de precio unitario, which is what a public tender is submitted and
compared as: an itemised costo directo that carries gastos generales and then
utilidades, with IVA outside the unit price.

These pin the cascade, its order and each step's base, because those are the
parts a client dictates. The percentages are the contractor's own and are only
starting points here.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.modules.methodology.cascade import compute_cascade
from app.modules.methodology.templates import (
    TEMPLATES_BY_SLUG,
    build_cascade_spec_from_template,
    get_template,
)

_SLUG = "chile_apu"

# One cubic metre of concrete wall, priced the way a Chilean APU is built up.
# Round numbers so every intermediate below is checkable by hand.
_BASES = {
    "mano_de_obra": Decimal("22500"),
    "materiales": Decimal("82000"),
    "equipos": Decimal("15500"),
}
_COSTO_DIRECTO = Decimal("120000")


def _result():
    return compute_cascade(build_cascade_spec_from_template(_SLUG), _BASES)


def _steps() -> dict[str, dict]:
    return {step["key"]: step for step in get_template(_SLUG)["cascade_steps"]}


def test_the_template_is_in_the_catalogue_under_chile() -> None:
    template = TEMPLATES_BY_SLUG[_SLUG]

    assert template["country_code"] == "CL"
    assert template["currency"] == "CLP"
    assert template["vat_rate"] == "19"


def test_the_peso_is_displayed_without_cents() -> None:
    """The currency has no minor unit, and a tendered rate must not invent one."""
    assert TEMPLATES_BY_SLUG[_SLUG]["decimals"] == 0


def test_the_flat_chile_template_is_still_offered() -> None:
    """Both traditions are legitimate; which one applies depends on the reader.

    An internal budget priced flat is not wrong, so adding the APU must not
    take the flat route away from projects already using it.
    """
    flat = TEMPLATES_BY_SLUG["chile"]

    assert flat["country_code"] == "CL"
    assert {step["key"] for step in flat["cascade_steps"]} != set(_steps())


def test_the_costo_directo_is_the_three_chilean_buckets() -> None:
    """Labour, materials and equipment, named the way a Chilean sheet names them."""
    template = get_template(_SLUG)

    assert set(template["base_mapping"]) == {"mano_de_obra", "materiales", "equipos"}
    assert template["composites"]["costo_directo"] == ["mano_de_obra", "materiales", "equipos"]
    # "maquinaria" is the Mexican word for the same bucket and must not leak here.
    assert "maquinaria" not in template["base_mapping"]


def test_the_cascade_runs_in_the_order_a_tender_expects() -> None:
    """Contingency, then overhead, then profit, then tax. The order is the method."""
    assert [step["key"] for step in get_template(_SLUG)["cascade_steps"]] == [
        "imprevistos",
        "gastos_generales",
        "utilidades",
        "iva",
    ]


def test_each_step_is_calculated_on_everything_before_it() -> None:
    """A cascade, not four independent percentages of the direct cost.

    This is the difference from the flat method, and it is worth money: at
    13 and 8 percent, compounding is a percent of the bid.
    """
    steps = _steps()

    assert steps["gastos_generales"]["base"] == ["costo_directo", "imprevistos"]
    assert steps["utilidades"]["base"] == ["costo_directo", "imprevistos", "gastos_generales"]
    assert steps["iva"]["base"] == [
        "costo_directo",
        "imprevistos",
        "gastos_generales",
        "utilidades",
    ]


def test_the_arithmetic_compounds_rather_than_adding_up() -> None:
    """120 000 of direct cost at 13 and 8 percent, checked step by step."""
    amounts = {line.key: line.amount for line in _result().steps}

    assert amounts["imprevistos"] == Decimal("0")
    # 13% of 120 000
    assert amounts["gastos_generales"] == Decimal("15600")
    # 8% of 135 600, NOT 8% of 120 000, which would be 9 600
    assert amounts["utilidades"] == Decimal("10848")
    # 19% of 146 448 is 27 825.12, quantized to whole pesos by decimals=0.
    assert amounts["iva"] == Decimal("27825")


def test_the_precio_unitario_excludes_iva() -> None:
    """What the bid is compared on is the net rate. IVA sits outside it.

    Comparing an IVA-inclusive rate against a net one is a 19 percent error in
    whichever direction, so this is the number that has to be right.
    """
    amounts = {line.key: line.amount for line in _result().steps}
    precio_unitario = _COSTO_DIRECTO + amounts["imprevistos"] + amounts["gastos_generales"] + amounts["utilidades"]

    assert precio_unitario == Decimal("146448")
    assert _result().grand_total == precio_unitario + amounts["iva"]


def test_a_contingency_is_offered_and_starts_empty() -> None:
    """Present so it can be filled in, zero so it is never charged unasked.

    Tenders differ on whether imprevistos is carried at all. A line invented at
    some plausible rate would have to be noticed and removed by every project
    that does not carry one, which is the failure that is hard to see.
    """
    assert _steps()["imprevistos"]["rate"] == "0"
    assert {line.key: line.amount for line in _result().steps}["imprevistos"] == Decimal("0")


def test_a_contingency_that_is_filled_in_lands_before_the_markups() -> None:
    """The whole point of the empty line: filling it moves everything after it."""
    base_spec = build_cascade_spec_from_template(_SLUG)
    spec = replace(
        base_spec,
        steps=[replace(step, rate=Decimal("5")) if step.key == "imprevistos" else step for step in base_spec.steps],
    )

    amounts = {line.key: line.amount for line in compute_cascade(spec, _BASES).steps}

    assert amounts["imprevistos"] == Decimal("6000")
    # 13% of 126 000, so the contingency is marked up like any other direct cost
    assert amounts["gastos_generales"] == Decimal("16380")


@pytest.mark.parametrize("key", ["imprevistos", "gastos_generales", "utilidades", "iva"])
def test_every_step_is_labelled_in_the_language_of_the_tender(key: str) -> None:
    """An estimator matches these against the client's own form, word for word."""
    labels = {
        "imprevistos": "Imprevistos",
        "gastos_generales": "Gastos generales",
        "utilidades": "Utilidades",
        "iva": "IVA",
    }

    assert _steps()[key]["label"] == labels[key]


def test_the_iva_rate_matches_the_statutory_one() -> None:
    """19 percent, and it must agree with what the tax module already carries."""
    from app.core.tax import get_vat_rate

    assert _steps()["iva"]["rate"] == "19"
    # The tax module carries the rate as a fraction, the cascade as a percent.
    assert Decimal(str(get_vat_rate("CL"))) * 100 == Decimal("19")
