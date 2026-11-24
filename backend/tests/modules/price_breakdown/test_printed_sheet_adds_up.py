"""A printed unit price analysis adds up line by line at the currency's precision."""

from decimal import Decimal

from app.modules.price_breakdown.model import build_breakdown


def _sheet(**kw):
    base = {
        "position_ref": "01.001",
        "description": "Wall",
        "unit": "m3",
        "position_quantity": "3",
        "components": [
            {"kind": "labour", "quantity": "1", "unit_cost": "10.005"},
            {"kind": "material", "quantity": "1", "unit_cost": "10.005"},
            {"kind": "plant", "quantity": "1", "unit_cost": "10.005"},
        ],
        "overhead_pct": "10",
        "profit_pct": "5",
    }
    base.update(kw)
    return build_breakdown(**base).to_dict()


def test_kind_totals_and_markups_sum_to_the_printed_rate():
    d = _sheet()
    kinds = sum(Decimal(v) for v in d["kind_totals"].values())
    assert kinds == Decimal(d["direct_unit_cost"]) == Decimal("30.03")
    lines = sum(Decimal(d[k]) for k in ("direct_unit_cost", "overhead_amount", "risk_amount", "profit_amount"))
    assert lines == Decimal(d["unit_rate"])


def test_position_total_is_the_printed_rate_times_quantity():
    d = _sheet()
    assert Decimal(d["position_total"]) == Decimal(d["unit_rate"]) * 3


def test_zero_decimal_currency_prints_whole_numbers_that_add_up():
    d = _sheet(currency="JPY", components=[{"kind": "labor", "quantity": "1", "unit_cost": "100.6"}] * 3)
    assert d["direct_unit_cost"] == "303"
    assert sum(Decimal(v) for v in d["kind_totals"].values()) == Decimal("303")


def test_an_explicit_zero_quantity_is_not_one_unit():
    comps = [{"kind": "material", "quantity": 0, "unit_cost": "50"}, {"kind": "labor", "unit_cost": "5"}]
    d = _sheet(components=comps)
    assert d["components"][0]["amount"] == "0.00"
    assert d["direct_unit_cost"] == "5.00"
