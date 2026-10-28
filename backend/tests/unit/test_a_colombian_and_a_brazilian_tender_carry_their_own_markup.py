"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Colombia and Brazil each price a job in a shape the generic cascade cannot state.

Both countries already had a template here, and both reached a total by the same
road as everywhere else: overhead, then profit, then tax on the lot. That road
gets the wrong number in each country, for a different reason.

In Colombia the markup is quoted as AIU and the three letters are each a share
of the costo directo, so nothing compounds; and IVA on a construction contract
for immovable property is charged on the utilidad, not on the contract value.

In Brazil the markup is BDI and its tax term divides instead of adding, because
PIS, COFINS and ISS are levied on the invoiced amount, which is the amount that
already contains them.

These pin the shapes rather than the percentages. The percentages are the
contractor's and are starting points.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.methodology.cascade import compute_cascade
from app.modules.methodology.templates import (
    TEMPLATES_BY_SLUG,
    build_cascade_spec_from_template,
    get_template,
)

# One million pesos of direct cost, split the way a Colombian APU splits it.
_CO_BASES = {
    "materiales": Decimal("600000"),
    "mano_de_obra": Decimal("300000"),
    "equipo_y_herramienta": Decimal("80000"),
    "transporte": Decimal("20000"),
}
_CO_COSTO_DIRECTO = Decimal("1000000")

# One hundred thousand reais of direct cost, so the BDI reads as a percentage.
_BR_BASES = {
    "mao_de_obra": Decimal("40000"),
    "materiais": Decimal("50000"),
    "equipamentos": Decimal("10000"),
}
_BR_CUSTO_DIRETO = Decimal("100000")


def _steps(slug: str) -> dict[str, dict]:
    return {step["key"]: step for step in get_template(slug)["cascade_steps"]}


def _amounts(slug: str, bases: dict[str, Decimal]) -> dict[str, Decimal]:
    result = compute_cascade(build_cascade_spec_from_template(slug), bases)
    return {line.key: line.amount for line in result.steps}


# ── Colombia ────────────────────────────────────────────────────────────────


def test_the_colombian_template_is_registered_under_colombia() -> None:
    template = TEMPLATES_BY_SLUG["colombia_aiu"]

    assert template["country_code"] == "CO"
    assert template["currency"] == "COP"
    assert template["vat_rate"] == "19"


def test_the_flat_colombian_template_survives_alongside_it() -> None:
    """An internal budget priced flat is not wrong and must keep working."""
    flat = TEMPLATES_BY_SLUG["colombia"]

    assert flat["country_code"] == "CO"
    assert {s["key"] for s in flat["cascade_steps"]} != set(_steps("colombia_aiu"))


def test_the_three_letters_are_the_three_steps_in_order() -> None:
    """A Colombian contract quotes AIU. The template has to spell it."""
    assert [s["key"] for s in get_template("colombia_aiu")["cascade_steps"]] == [
        "administracion",
        "imprevistos",
        "utilidad",
        "iva",
    ]


@pytest.mark.parametrize("key", ["administracion", "imprevistos", "utilidad"])
def test_none_of_the_aiu_letters_is_taken_on_another(key: str) -> None:
    """The whole difference from a cascade: each is a share of the direct cost.

    Compounding them would quote a total the client never asked for, which on
    these figures is more than eleven thousand pesos of invented markup.
    """
    assert _steps("colombia_aiu")[key]["base"] == ["costo_directo"]


def test_the_aiu_amounts_are_flat_percentages_of_the_costo_directo() -> None:
    amounts = _amounts("colombia_aiu", _CO_BASES)

    assert amounts["administracion"] == Decimal("200000")  # 20%
    assert amounts["imprevistos"] == Decimal("20000")  # 2%
    assert amounts["utilidad"] == Decimal("50000")  # 5%, not 5% of 1 220 000


def test_iva_falls_on_the_utilidad_alone() -> None:
    """Decreto 1372 de 1992 for a construction contract on immovable property.

    This is the expensive one. Charged on the contract value instead, the same
    19 percent would be 241 300 rather than 9 500, so the error is 18 percent
    of the job in whichever direction it is made.
    """
    assert _steps("colombia_aiu")["iva"]["base"] == ["utilidad"]

    amounts = _amounts("colombia_aiu", _CO_BASES)
    assert amounts["iva"] == Decimal("9500")

    everything_before = _CO_COSTO_DIRECTO + amounts["administracion"] + amounts["imprevistos"] + amounts["utilidad"]
    assert everything_before * Decimal("19") / Decimal("100") == Decimal("241300")


def test_the_colombian_total_is_the_direct_cost_plus_aiu_plus_that_iva() -> None:
    result = compute_cascade(build_cascade_spec_from_template("colombia_aiu"), _CO_BASES)

    assert result.composites["costo_directo"] == _CO_COSTO_DIRECTO
    assert result.grand_total == Decimal("1279500")


# ── Brazil ──────────────────────────────────────────────────────────────────


def test_the_brazilian_template_is_registered_under_brazil() -> None:
    template = TEMPLATES_BY_SLUG["brazil_bdi"]

    assert template["country_code"] == "BR"
    assert template["currency"] == "BRL"
    # Brazil has no VAT; the consumption tax is ISS and it lives in the cascade.
    assert template["vat_rate"] == "0"


def test_the_flat_brazilian_template_survives_alongside_it() -> None:
    flat = TEMPLATES_BY_SLUG["brazil"]

    assert flat["country_code"] == "BR"
    assert {s["key"] for s in flat["cascade_steps"]} != set(_steps("brazil_bdi"))


def test_the_first_bracket_of_the_formula_shares_one_base() -> None:
    """(1 + AC + S + R + G): four terms added together, then applied once.

    Each is a share of the custo direto and none of them sees the others, which
    is what makes it a sum inside a bracket rather than a chain.
    """
    steps = _steps("brazil_bdi")

    for key in ("administracao_central", "seguros_e_garantias", "riscos"):
        assert steps[key]["base"] == ["custo_direto"]


def test_the_later_factors_apply_to_everything_before_them() -> None:
    """(1 + DF) and (1 + L) are separate factors, so these do compound."""
    steps = _steps("brazil_bdi")

    assert steps["despesas_financeiras"]["base"] == [
        "custo_direto",
        "administracao_central",
        "seguros_e_garantias",
        "riscos",
    ]
    assert "lucro" not in steps["despesas_financeiras"]["base"]
    assert steps["lucro"]["base"][-1] == "despesas_financeiras"


def test_the_tax_step_is_a_gross_up_and_not_a_percentage() -> None:
    """The division in the formula. A percentage step here under-recovers."""
    assert _steps("brazil_bdi")["tributos"]["kind"] == "gross_up"


def test_the_tax_comes_out_as_its_rate_of_the_total_not_of_the_subtotal() -> None:
    """8.65 percent of what is invoiced, which is the number the statute names."""
    result = compute_cascade(build_cascade_spec_from_template("brazil_bdi"), _BR_BASES)
    tributos = {line.key: line.amount for line in result.steps}["tributos"]

    assert tributos == Decimal("10919.77")
    assert (result.grand_total * Decimal("8.65") / Decimal("100")).quantize(Decimal("0.01")) == tributos


def test_the_bdi_lands_inside_the_band_the_audit_court_publishes() -> None:
    """A sanity check on the defaults as a set, not on any one of them.

    Acordao 2622/2013 puts building work around a fifth to a quarter over direct
    cost. A default set that landed outside that would be wrong as a set even
    with every individual rate defensible.
    """
    result = compute_cascade(build_cascade_spec_from_template("brazil_bdi"), _BR_BASES)
    bdi = (result.grand_total / _BR_CUSTO_DIRETO - 1) * 100

    assert Decimal("20") < bdi < Decimal("30")


def test_the_default_rates_multiply_out_to_the_total_they_multiply_out_to() -> None:
    """Deliberately separate from the band above.

    Pinning the exact total in the same test would make the band assertion
    unreachable: change one default rate and the equality fires first, so the
    band never gets to say whether the set as a whole is still sane.
    """
    result = compute_cascade(build_cascade_spec_from_template("brazil_bdi"), _BR_BASES)

    assert result.grand_total == Decimal("126240.15")


def test_only_one_tax_line_carries_the_three_taxes() -> None:
    """They share a denominator, so three gross_up steps would compound them.

    PIS, COFINS and ISS all sit inside the same (1 - I). Splitting them into
    separate steps reads tidier and returns a bigger number than the formula.
    """
    steps = get_template("brazil_bdi")["cascade_steps"]

    assert [s["key"] for s in steps if s["kind"] == "gross_up"] == ["tributos"]
