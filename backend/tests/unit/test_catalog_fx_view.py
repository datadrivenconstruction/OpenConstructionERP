"""A EUR catalogue row opened from a USD project is priced into USD, or flagged unpriced."""

from decimal import Decimal

from app.modules.assemblies.fx_bridge import FxContext
from app.modules.catalog.fx_view import build_fx_view


def _ctx(**kw) -> FxContext:
    base = {
        "project_base": "USD",
        "register_rates": {"USD": Decimal("1.25"), "GBP": Decimal("0.8")},
        "register_base": "EUR",
        "register_provenance": {"fx_as_of": "2026-10-30", "fx_feed": "ecb"},
    }
    base.update(kw)
    return FxContext(**base)


def test_eur_row_gets_a_dated_usd_rate() -> None:
    view = build_fx_view(_ctx(), ["EUR"])
    rate = view.rates["EUR"]
    assert view.project_currency == "USD"
    assert Decimal(rate.rate) == Decimal("1.25")
    assert rate.source == "oe_fx"
    assert rate.as_of == "2026-10-30"


def test_same_currency_is_identity() -> None:
    assert Decimal(build_fx_view(_ctx(), ["USD"]).rates["USD"].rate) == 1


def test_project_override_outranks_the_register() -> None:
    view = build_fx_view(_ctx(project_rates={"EUR": "1.10"}), ["EUR"])
    assert Decimal(view.rates["EUR"].rate) == Decimal("1.10")
    assert view.rates["EUR"].source == "project_fx_rates"


def test_unknown_currency_is_unpriced_not_guessed() -> None:
    rate = build_fx_view(_ctx(), ["XTS"]).rates["XTS"]
    assert rate.rate is None
    assert rate.reason == "no_rate"


def test_project_without_currency_prices_nothing() -> None:
    rate = build_fx_view(_ctx(project_base=""), ["EUR"]).rates["EUR"]
    assert rate.rate is None
    assert rate.reason == "missing_currency"


def test_codes_are_cleaned_and_deduplicated() -> None:
    view = build_fx_view(_ctx(), ["eur", " EUR ", "", "12", "GBP"])
    assert list(view.rates) == ["EUR", "GBP"]
