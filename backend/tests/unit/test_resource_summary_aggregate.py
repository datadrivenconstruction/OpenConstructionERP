"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the resource-summary aggregation library (pure, DB-free)."""

from decimal import Decimal

from app.modules.price_breakdown import ResourceKind
from app.modules.resource_summary.aggregate import (
    aggregate_resource_statement,
    render_csv,
)


def _positions():
    """Two priced positions sharing a concrete material and a mason labour line.

    Resource quantity/unit_rate are per one position unit, so procurement demand
    scales by the position quantity: concrete 1.02 m3 per m3 of wall, mason 3.5 h.
    """
    return [
        {
            "id": "p1",
            "quantity": "50",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "Concrete C30/37",
                        "unit": "m3",
                        "quantity": "1.02",
                        "unit_rate": "95",
                    },
                    {"type": "labor", "name": "Mason", "unit": "h", "quantity": "3.5", "unit_rate": "42"},
                ]
            },
        },
        {
            "id": "p2",
            "quantity": "20",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "Concrete C30/37",
                        "unit": "m3",
                        "quantity": "1.02",
                        "unit_rate": "95",
                    },
                    {"type": "labor", "name": "Mason", "unit": "h", "quantity": "3.5", "unit_rate": "42"},
                ]
            },
        },
    ]


def test_groups_by_kind_name_unit_and_scales_by_position_quantity():
    st = aggregate_resource_statement(_positions(), currency="EUR")

    # Labour comes first, then material (KIND_ORDER).
    assert [g.kind for g in st.groups] == [ResourceKind.LABOUR, ResourceKind.MATERIAL]

    labour = st.groups[0]
    assert len(labour.lines) == 1
    mason = labour.lines[0]
    # 3.5 h/unit * (50 + 20) units = 245 h; 3.5*42 = 147/unit -> 147*70 = 10290.
    assert mason.quantity == Decimal("245")
    assert mason.cost == Decimal("10290")
    assert mason.position_count == 2

    material = st.groups[1]
    concrete = material.lines[0]
    # 1.02 * 70 = 71.4 m3; 1.02*95 = 96.90/unit -> 96.90*70 = 6783.
    assert concrete.quantity == Decimal("71.4")
    assert concrete.cost == Decimal("6783")


def test_statement_totals_and_labor_hours():
    st = aggregate_resource_statement(_positions(), currency="EUR")
    assert st.currency == "EUR"
    assert st.position_count == 2
    assert st.line_count == 2
    assert st.labor_hours == Decimal("245")
    assert st.total_cost == Decimal("17073")  # 10290 + 6783


def test_to_dict_rounds_money_2dp_and_quantities_4dp():
    d = aggregate_resource_statement(_positions(), currency="EUR").to_dict()
    assert d["currency"] == "EUR"
    assert d["total_cost"] == "17073.00"
    assert d["labor_hours"] == "245.0000"
    labour = d["groups"][0]
    assert labour["kind"] == "labor"
    assert labour["kind_i18n_key"] == "price_breakdown.kind.labor"
    assert labour["total_cost"] == "10290.00"
    assert labour["total_hours"] == "245.0000"
    line = labour["lines"][0]
    assert line["quantity"] == "245.0000"
    assert line["cost"] == "10290.00"
    # Non-labour groups never carry an hours figure.
    assert "total_hours" not in d["groups"][1]


def test_lines_within_a_kind_sorted_by_cost_desc():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {"type": "material", "name": "Cheap filler", "unit": "kg", "quantity": "1", "unit_rate": "2"},
                    {"type": "material", "name": "Steel", "unit": "t", "quantity": "1", "unit_rate": "900"},
                ]
            },
        }
    ]
    st = aggregate_resource_statement(positions)
    names = [line.name for line in st.groups[0].lines]
    assert names == ["Steel", "Cheap filler"]


def test_same_resource_different_unit_is_not_merged():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {"type": "material", "name": "Sand", "unit": "t", "quantity": "1", "unit_rate": "30"},
                    {"type": "material", "name": "Sand", "unit": "m3", "quantity": "1", "unit_rate": "40"},
                ]
            },
        }
    ]
    st = aggregate_resource_statement(positions)
    assert len(st.groups[0].lines) == 2


def test_name_and_unit_grouping_is_case_insensitive():
    positions = [
        {
            "id": "p1",
            "quantity": "2",
            "metadata_": {
                "resources": [{"type": "labor", "name": "Mason", "unit": "H", "quantity": "1", "unit_rate": "40"}]
            },
        },
        {
            "id": "p2",
            "quantity": "3",
            "metadata_": {
                "resources": [{"type": "labor", "name": "mason", "unit": "h", "quantity": "1", "unit_rate": "40"}]
            },
        },
    ]
    st = aggregate_resource_statement(positions)
    assert len(st.groups[0].lines) == 1
    assert st.groups[0].lines[0].quantity == Decimal("5")  # 1*2 + 1*3


def test_cost_falls_back_to_total_when_factors_missing():
    # A lump-sum resource carrying only a stored total, no quantity/unit_rate.
    positions = [
        {
            "id": "p1",
            "quantity": "10",
            "metadata_": {
                "resources": [{"type": "subcontractor", "name": "Waterproofing sub", "unit": "ls", "total": "5"}]
            },
        }
    ]
    st = aggregate_resource_statement(positions)
    line = st.groups[0].lines[0]
    assert st.groups[0].kind is ResourceKind.SUBCONTRACT
    assert line.cost == Decimal("50")  # 5 (per unit) * 10
    assert line.quantity == Decimal("0")  # no resource quantity to scale


def test_stale_total_is_ignored_when_factors_present():
    # quantity*unit_rate wins over a stale stored total (self-heal).
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {"type": "material", "name": "X", "unit": "u", "quantity": "2", "unit_rate": "3", "total": "999"}
                ]
            },
        }
    ]
    st = aggregate_resource_statement(positions)
    assert st.groups[0].lines[0].cost == Decimal("6")


def test_foreign_currency_line_converted_via_fx_map():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "Imported panel",
                        "unit": "pcs",
                        "quantity": "1",
                        "unit_rate": "100",
                        "currency": "USD",
                    }
                ]
            },
        }
    ]
    st = aggregate_resource_statement(positions, currency="EUR", fx_rates={"USD": "0.90"})
    assert st.currency == "EUR"
    assert st.groups[0].lines[0].cost == Decimal("90.00")


def test_missing_fx_rate_leaves_line_in_own_units():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "Imported panel",
                        "unit": "pcs",
                        "quantity": "1",
                        "unit_rate": "100",
                        "currency": "USD",
                    }
                ]
            },
        }
    ]
    # No rate for USD -> not zeroed, kept at face value (deterministic).
    st = aggregate_resource_statement(positions, currency="EUR", fx_rates={})
    assert st.groups[0].lines[0].cost == Decimal("100")


def test_currency_falls_back_to_first_resource_currency_when_base_unset():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {"type": "material", "name": "X", "unit": "u", "quantity": "1", "unit_rate": "5", "currency": "GBP"}
                ]
            },
        }
    ]
    st = aggregate_resource_statement(positions, currency="")
    assert st.currency == "GBP"


def test_positions_without_resources_are_skipped():
    positions = [
        {"id": "section", "quantity": "1", "metadata_": {}},
        {"id": "p1", "quantity": "1", "metadata_": {"resources": []}},
        {
            "id": "p2",
            "quantity": "4",
            "metadata_": {
                "resources": [{"type": "material", "name": "Brick", "unit": "pcs", "quantity": "10", "unit_rate": "1"}]
            },
        },
    ]
    st = aggregate_resource_statement(positions)
    assert st.position_count == 1
    assert st.line_count == 1
    assert st.groups[0].lines[0].quantity == Decimal("40")


def test_zero_quantity_position_contributes_nothing():
    positions = [
        {
            "id": "p1",
            "quantity": "0",
            "metadata_": {
                "resources": [{"type": "material", "name": "Brick", "unit": "pcs", "quantity": "10", "unit_rate": "1"}]
            },
        }
    ]
    st = aggregate_resource_statement(positions)
    # A position not yet measured (qty 0) implies nothing to procure.
    assert st.groups[0].lines[0].quantity == Decimal("0")
    assert st.groups[0].lines[0].cost == Decimal("0")
    assert st.total_cost == Decimal("0")


def test_type_aliases_map_onto_canonical_kinds():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {"type": "Lohn", "name": "Crew", "unit": "h", "quantity": "1", "unit_rate": "50"},
                    {"type": "Nachunternehmer", "name": "Sub", "unit": "ls", "quantity": "1", "unit_rate": "500"},
                ]
            },
        }
    ]
    st = aggregate_resource_statement(positions)
    kinds = {g.kind for g in st.groups}
    assert ResourceKind.LABOUR in kinds
    assert ResourceKind.SUBCONTRACT in kinds


def test_empty_input_produces_empty_statement():
    st = aggregate_resource_statement([])
    assert st.groups == []
    assert st.total_cost == Decimal("0")
    assert st.labor_hours == Decimal("0")
    assert st.position_count == 0
    d = st.to_dict()
    assert d["total_cost"] == "0.00"
    assert d["labor_hours"] == "0.0000"
    assert d["groups"] == []


def test_render_csv_contains_lines_subtotals_and_grand_total():
    csv_text = render_csv(aggregate_resource_statement(_positions(), currency="EUR"))
    assert "Resource / procurement statement" in csv_text
    assert "Currency,EUR" in csv_text
    assert "Mason" in csv_text
    assert "Concrete C30/37" in csv_text
    # Grand total row carries the summed cost.
    assert "Grand total,,,,17073.00," in csv_text
    # Labour subtotal present.
    assert "Labour subtotal,,,,10290.00," in csv_text


def test_render_csv_escapes_commas_in_names():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "Bolt, M12, galvanised",
                        "unit": "pcs",
                        "quantity": "1",
                        "unit_rate": "2",
                    }
                ]
            },
        }
    ]
    csv_text = render_csv(aggregate_resource_statement(positions))
    # The comma-bearing name is quoted so it stays a single CSV field.
    assert '"Bolt, M12, galvanised"' in csv_text
