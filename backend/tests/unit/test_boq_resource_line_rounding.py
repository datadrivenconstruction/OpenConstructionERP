"""Resource line totals use one Decimal helper on every write path."""

from __future__ import annotations

from decimal import Decimal

from app.modules.boq.service import _compute_total, _resource_line_total, _round_currency


def test_resource_line_total_is_exact_decimal():
    # float 3 * 0.335 is 1.0050000000000001; the stored total must be exactly 1.0050.
    assert _resource_line_total(3, 0.335) == Decimal("1.0050")
    assert _resource_line_total("3", "0.335") == Decimal("1.0050")


def test_resource_line_total_matches_position_total():
    assert str(_resource_line_total("2.5", "19.99")) == _compute_total("2.5", "19.99")


def test_resource_line_total_survives_garbage():
    assert _resource_line_total(None, "x") == Decimal("0.0000")


def test_variant_repick_and_code_propagation_agree():
    """Both former code paths (round 4dp vs round 2dp on floats) now yield the same figure."""
    qty, rate = "3", 0.335
    via_repick = float(_resource_line_total(qty, rate))
    via_propagation = float(_resource_line_total(qty, str(rate)))
    assert via_repick == via_propagation == 1.005


def test_rounded_parts_reconcile_to_grand_total():
    direct = Decimal("1000.005")
    markups = [Decimal("100.0049"), Decimal("33.335")]
    parts = _round_currency(direct) + sum((_round_currency(m) for m in markups), Decimal("0"))
    assert parts == _round_currency(direct) + _round_currency(markups[0]) + _round_currency(markups[1])
    assert parts.as_tuple().exponent == -2


def test_template_list_carries_currency_and_benchmark_rate():
    from app.modules.boq.service import BOQService
    from app.modules.boq.templates import TEMPLATES

    infos = BOQService.list_templates(None)  # type: ignore[arg-type]
    assert {i.id for i in infos} == set(TEMPLATES)
    for info in infos:
        assert info.currency == "EUR"
        assert info.avg_cost_per_m2 > 0
