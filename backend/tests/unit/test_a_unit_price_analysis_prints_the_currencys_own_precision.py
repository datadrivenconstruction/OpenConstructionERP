"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A unit price analysis must print money at the currency's own precision.

Reported from a self-hosted install in Chile: a rate read ``82000.00 CLP``. The
peso has no minor unit, so those two decimals are not just noise, they are false
precision on a number that goes into a public tender. Three currency tables in
this repository already know CLP has no cents; this serialisation was not asking
any of them.

The same rounding lives on the assembly screens and was fixed there separately.
This pins the backend half, on the module closest to unit price work.
"""

from decimal import Decimal

import pytest

from app.modules.price_breakdown import build_breakdown, efb_221_view, render_csv, render_markdown
from app.modules.price_breakdown.model import money_quantum

# The money keys in the serialised view. Percentages and quantities are
# deliberately absent: they do not follow the currency.
_MONEY_KEYS = (
    "direct_unit_cost",
    "overhead_amount",
    "risk_amount",
    "profit_amount",
    "unit_rate",
    "position_total",
)


def _breakdown(currency: str):
    """One concrete wall, priced the way a Chilean APU is built up."""
    return build_breakdown(
        position_ref="01.02.003",
        description="Hormigón H-25 wall",
        unit="m3",
        position_quantity=Decimal("50"),
        components=[
            {"kind": "material", "description": "Hormigón H-25", "unit": "m3", "quantity": "1", "unit_cost": "82000"},
            {"kind": "labor", "description": "Cuadrilla", "unit": "h", "quantity": "3", "unit_cost": "7500"},
        ],
        overhead_pct="12.5",
        profit_pct="8",
        currency=currency,
    )


def test_a_currency_with_no_minor_unit_prints_no_cents() -> None:
    """The reported defect: 82000.00 CLP."""
    view = _breakdown("CLP").to_dict()

    for key in _MONEY_KEYS:
        assert "." not in view[key], f"{key} printed {view[key]!r}, but the peso has no minor unit"
    for component in view["components"]:
        assert "." not in component["unit_cost"], component
        assert "." not in component["amount"], component
    for kind, total in view["kind_totals"].items():
        assert "." not in total, f"kind total {kind} printed {total!r}"

    assert view["components"][0]["unit_cost"] == "82000"


def test_a_currency_with_cents_is_unchanged() -> None:
    """The euro path is the one that was already right; it must stay right."""
    view = _breakdown("EUR").to_dict()

    for key in _MONEY_KEYS:
        assert view[key].count(".") == 1, f"{key} printed {view[key]!r}"
        assert len(view[key].split(".")[1]) == 2, f"{key} printed {view[key]!r}"


@pytest.mark.parametrize("code", ["JPY", "KRW", "CLP", "HUF", "PYG"])
def test_every_zero_decimal_currency_on_the_registry_is_honoured(code: str) -> None:
    """Not a Chile special case. The registry is the authority, not one country."""
    assert money_quantum(code) == Decimal("1")
    assert "." not in _breakdown(code).to_dict()["unit_rate"]


def test_percentages_do_not_follow_the_currency() -> None:
    """A 12.5% markup is 12.5% in Santiago and in Frankfurt.

    Rounding the percentage to the currency's precision would have read 13%,
    silently restating the contractor's own markup.
    """
    view = _breakdown("CLP").to_dict()

    assert view["overhead_pct"] == "12.50"
    assert view["profit_pct"] == "8.00"
    # Quantities carry their own precision too, four decimals regardless.
    assert view["position_quantity"] == "50.0000"


def test_an_unknown_currency_keeps_the_historical_two_decimals() -> None:
    """A code the registry does not carry must not lose precision silently.

    Two decimals is both the old behaviour and the right guess for most codes,
    so an unrecognised currency degrades to it rather than to whole units.
    """
    assert money_quantum("ZZZ") == Decimal("0.01")
    assert money_quantum(None) == Decimal("0.01")
    assert money_quantum("") == Decimal("0.01")
    assert _breakdown("ZZZ").to_dict()["unit_rate"].split(".")[1] == "50"


def test_the_currency_code_is_read_case_and_space_insensitively() -> None:
    """Callers pass whatever the project stored, not a normalised code."""
    assert money_quantum("clp") == Decimal("1")
    assert money_quantum(" CLP ") == Decimal("1")


def test_a_half_unit_rounds_up_rather_than_being_dropped() -> None:
    """Whole-unit rounding must round, not truncate.

    Truncation would bias every line of a tender downward, which on a bill of
    thousands of positions is a real amount of money.
    """
    view = build_breakdown(
        position_ref="1",
        description="rounding probe",
        unit="u",
        position_quantity="1",
        components=[{"kind": "material", "description": "x", "unit": "u", "quantity": "0.5", "unit_cost": "1"}],
        currency="CLP",
    ).to_dict()

    assert view["components"][0]["amount"] == "1"
    assert view["unit_rate"] == "1"


# ── Every way this module hands a rate to a person ─────────────────────────
#
# The JSON view is one of four. Fixing it alone would leave the exported CSV a
# contractor actually submits still printing cents, which is harder to notice
# than fixing none of them, so each renderer gets its own check.


def test_the_efb_sheet_view_follows_the_currency() -> None:
    view = efb_221_view(_breakdown("CLP"))

    assert "." not in view["unit_rate"], view["unit_rate"]
    assert "." not in view["direct_unit_cost"], view["direct_unit_cost"]
    assert all("." not in row["amount"] for row in view["rows"]), view["rows"]


def test_the_markdown_analysis_follows_the_currency() -> None:
    text = render_markdown(_breakdown("CLP"))

    assert "82000 " in text, text
    assert "82000.00" not in text, text
    assert ".00 CLP" not in text, text


def test_the_exported_csv_follows_the_currency() -> None:
    """The CSV is the artefact that leaves the building and goes into a tender."""
    csv_text = render_csv(_breakdown("CLP"))

    assert ",82000\r\n" in csv_text or ",82000\n" in csv_text, csv_text
    assert "82000.00" not in csv_text, csv_text


def test_the_euro_renderers_still_print_cents() -> None:
    """The regression guard: the currencies that do have cents keep them."""
    bd = _breakdown("EUR")

    assert "82000.00" in render_markdown(bd)
    assert "82000.00" in render_csv(bd)
    assert "." in efb_221_view(bd)["unit_rate"]
