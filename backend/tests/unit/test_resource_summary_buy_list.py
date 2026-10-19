"""Unit tests for the material procurement buy-list aggregation (pure, DB-free)."""

from decimal import Decimal

from app.modules.resource_summary.aggregate import aggregate_material_buy_list


def _positions():
    """Two priced positions sharing a concrete material and a mason labour line.

    Resource quantity/unit_rate are per one position unit, so procurement demand
    scales by the position quantity: concrete 1.02 m3 per m3 of wall, mason 3.5 h.
    Only the material line belongs in a buy-list.
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


def test_groups_materials_by_name_unit_and_scales_by_position_quantity():
    bl = aggregate_material_buy_list(_positions(), currency="EUR")

    # Only the concrete material survives; the mason labour line is excluded.
    assert bl.item_count == 1
    concrete = bl.items[0]
    assert concrete.name == "Concrete C30/37"
    assert concrete.unit == "m3"
    # 1.02 m3/unit * (50 + 20) units = 71.4 m3; 1.02*95 = 96.90/unit -> 96.90*70 = 6783.
    assert concrete.quantity == Decimal("71.4")
    assert concrete.cost == Decimal("6783")
    assert concrete.position_count == 2


def test_buy_list_totals_and_position_count():
    bl = aggregate_material_buy_list(_positions(), currency="EUR")
    assert bl.currency == "EUR"
    assert bl.position_count == 2  # both positions carry a material line
    assert bl.total_cost == Decimal("6783")


def test_non_material_lines_are_excluded():
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {"type": "labor", "name": "Mason", "unit": "h", "quantity": "1", "unit_rate": "40"},
                    {"type": "machinery", "name": "Crane", "unit": "h", "quantity": "1", "unit_rate": "120"},
                    {"type": "equipment", "name": "Scaffold", "unit": "day", "quantity": "1", "unit_rate": "15"},
                    {
                        "type": "subcontractor",
                        "name": "Waterproofing",
                        "unit": "ls",
                        "quantity": "1",
                        "unit_rate": "500",
                    },
                    {"type": "other", "name": "Sundries", "unit": "ls", "quantity": "1", "unit_rate": "10"},
                    {"type": "material", "name": "Brick", "unit": "pcs", "quantity": "100", "unit_rate": "1"},
                ]
            },
        }
    ]
    bl = aggregate_material_buy_list(positions)
    assert bl.item_count == 1
    assert bl.items[0].name == "Brick"
    assert bl.items[0].quantity == Decimal("100")
    assert bl.items[0].cost == Decimal("100")


def test_material_type_aliases_are_recognised():
    # German/Spanish material tokens map onto the canonical MATERIAL kind.
    positions = [
        {
            "id": "p1",
            "quantity": "1",
            "metadata_": {
                "resources": [
                    {"type": "Baustoff", "name": "Zement", "unit": "kg", "quantity": "10", "unit_rate": "0.2"},
                    {"type": "materiales", "name": "Arena", "unit": "t", "quantity": "1", "unit_rate": "30"},
                ]
            },
        }
    ]
    bl = aggregate_material_buy_list(positions)
    assert bl.item_count == 2


def test_same_material_different_unit_is_not_merged():
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
    bl = aggregate_material_buy_list(positions)
    assert bl.item_count == 2
    assert {item.unit for item in bl.items} == {"t", "m3"}


def test_material_name_and_unit_grouping_is_case_insensitive():
    positions = [
        {
            "id": "p1",
            "quantity": "2",
            "metadata_": {
                "resources": [{"type": "material", "name": "Cement", "unit": "KG", "quantity": "5", "unit_rate": "0.2"}]
            },
        },
        {
            "id": "p2",
            "quantity": "3",
            "metadata_": {
                "resources": [{"type": "material", "name": "cement", "unit": "kg", "quantity": "5", "unit_rate": "0.2"}]
            },
        },
    ]
    bl = aggregate_material_buy_list(positions)
    assert bl.item_count == 1
    # 5*2 + 5*3 = 25 kg; first-seen name/unit casing is kept.
    assert bl.items[0].quantity == Decimal("25")
    assert bl.items[0].name == "Cement"
    assert bl.items[0].unit == "KG"
    assert bl.items[0].position_count == 2


def test_gross_quantity_applies_waste_pct_from_nested_metadata():
    # A norm-expansion material carries waste in metadata; the buy-list buys gross.
    positions = [
        {
            "id": "p1",
            "quantity": "100",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "Tiles",
                        "unit": "m2",
                        "quantity": "1.05",
                        "unit_rate": "20",
                        "metadata": {"waste_pct": "10", "net_qty": "1.05", "gross_qty": "1.155"},
                    }
                ]
            },
        }
    ]
    bl = aggregate_material_buy_list(positions)
    # Gross quantity applies the waste factor: 1.05 * (1 + 10/100) = 1.155; * 100 = 115.5 m2.
    assert bl.items[0].quantity == Decimal("115.500")
    # Cost follows the stored per-unit price (1.05 * 20) * 100 = 2100.
    assert bl.items[0].cost == Decimal("2100.00")


def test_gross_quantity_honours_top_level_waste_pct():
    positions = [
        {
            "id": "p1",
            "quantity": "10",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "Rebar",
                        "unit": "kg",
                        "quantity": "2",
                        "unit_rate": "1",
                        "waste_pct": "5",
                    }
                ]
            },
        }
    ]
    bl = aggregate_material_buy_list(positions)
    # 2 * 1.05 = 2.1 per unit; * 10 = 21 kg.
    assert bl.items[0].quantity == Decimal("21.0")


def test_zero_or_missing_waste_leaves_net_equals_gross():
    positions = [
        {
            "id": "p1",
            "quantity": "10",
            "metadata_": {
                "resources": [
                    {
                        "type": "material",
                        "name": "A",
                        "unit": "u",
                        "quantity": "1",
                        "unit_rate": "1",
                        "metadata": {"waste_pct": "0"},
                    },
                    {"type": "material", "name": "B", "unit": "u", "quantity": "1", "unit_rate": "1"},
                ]
            },
        }
    ]
    bl = aggregate_material_buy_list(positions)
    for item in bl.items:
        assert item.quantity == Decimal("10")


def test_items_sorted_by_cost_desc_then_name():
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
    bl = aggregate_material_buy_list(positions)
    assert [item.name for item in bl.items] == ["Steel", "Cheap filler"]


def test_foreign_currency_material_converted_via_fx_map():
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
    bl = aggregate_material_buy_list(positions, currency="EUR", fx_rates={"USD": "0.90"})
    assert bl.currency == "EUR"
    assert bl.items[0].cost == Decimal("90.00")


def test_cost_falls_back_to_total_when_factors_missing():
    positions = [
        {
            "id": "p1",
            "quantity": "10",
            "metadata_": {"resources": [{"type": "material", "name": "Bagged mix", "unit": "bag", "total": "4"}]},
        }
    ]
    bl = aggregate_material_buy_list(positions)
    assert bl.items[0].cost == Decimal("40")  # 4 (per unit) * 10
    assert bl.items[0].quantity == Decimal("0")  # no resource quantity to scale


def test_positions_without_material_lines_produce_empty_list():
    positions = [
        {"id": "section", "quantity": "1", "metadata_": {}},
        {
            "id": "p1",
            "quantity": "5",
            "metadata_": {
                "resources": [{"type": "labor", "name": "Mason", "unit": "h", "quantity": "3", "unit_rate": "40"}]
            },
        },
    ]
    bl = aggregate_material_buy_list(positions)
    assert bl.items == []
    assert bl.item_count == 0
    assert bl.position_count == 0
    assert bl.total_cost == Decimal("0")


def test_empty_input_produces_empty_buy_list():
    bl = aggregate_material_buy_list([])
    assert bl.items == []
    assert bl.total_cost == Decimal("0")
    assert bl.position_count == 0
    d = bl.to_dict()
    assert d["items"] == []
    assert d["total_cost"] == "0.00"
    assert d["item_count"] == 0


def test_to_dict_rounds_money_2dp_and_quantities_4dp():
    d = aggregate_material_buy_list(_positions(), currency="EUR").to_dict()
    assert d["currency"] == "EUR"
    assert d["total_cost"] == "6783.00"
    assert d["item_count"] == 1
    assert d["position_count"] == 2
    item = d["items"][0]
    assert item["quantity"] == "71.4000"
    assert item["cost"] == "6783.00"
    assert item["position_count"] == 2


def test_currency_falls_back_to_first_material_currency_when_base_unset():
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
    bl = aggregate_material_buy_list(positions, currency="")
    assert bl.currency == "GBP"


def _coded(position_id: str, name: str, catalog_item_id: str | None, unit: str = "m3") -> dict:
    resource = {"type": "material", "name": name, "unit": unit, "quantity": "1", "unit_rate": "10"}
    if catalog_item_id is not None:
        resource["catalog_item_id"] = catalog_item_id
    return {"id": position_id, "quantity": "2", "metadata_": {"resources": [resource]}}


def test_a_catalogue_item_groups_by_its_id_not_by_its_name():
    """Issue #516: a shared name is not a shared material; the catalogue item is."""
    bl = aggregate_material_buy_list(
        [
            _coded("p1", "Concrete C30/37", "item-a"),
            _coded("p2", "Concrete C30/37", "item-b"),
            _coded("p3", "Beton C30/37 (supplier wording)", "item-a"),
            _coded("p4", "Concrete C30/37", None),
        ],
        currency="EUR",
    )

    rows = {(tuple(sorted({s.catalog_item_id or "-" for s in i.sources})), i.quantity) for i in bl.items}
    assert rows == {(("item-a",), Decimal("4")), (("item-b",), Decimal("2")), (("-",), Decimal("2"))}
    item_a = next(i for i in bl.items if i.sources[0].catalog_item_id == "item-a")
    assert [s.position_id for s in item_a.sources] == ["p1", "p3"], "both sources stay traceable"


def test_the_same_catalogue_item_in_two_units_stays_two_rows():
    bl = aggregate_material_buy_list(
        [_coded("p1", "Rebar", "item-r", unit="t"), _coded("p2", "Rebar", "item-r", unit="kg")],
        currency="EUR",
    )
    assert sorted(i.unit for i in bl.items) == ["kg", "t"]
