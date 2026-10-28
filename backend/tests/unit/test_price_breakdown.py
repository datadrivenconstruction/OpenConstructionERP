"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the price-breakdown library (pure, DB-free)."""

from decimal import Decimal

import pytest

from app.modules.price_breakdown import (
    LINE_I18N_KEYS,
    MAX_MARKUP_PCT,
    PriceBreakdownError,
    ResourceKind,
    build_breakdown,
    coerce_kind,
    efb_221_view,
    from_position,
    get_preset,
    kind_i18n_key,
    render_csv,
    render_markdown,
)


def _sample():
    # A reinforced-concrete wall, per m3, priced from resources.
    return build_breakdown(
        position_ref="01.02.003",
        description="Reinforced concrete wall C30/37",
        unit="m3",
        position_quantity=Decimal("50"),
        components=[
            {"kind": "material", "description": "Concrete C30/37", "unit": "m3", "quantity": "1.02", "unit_cost": "95"},
            {"kind": "material", "description": "Rebar", "unit": "t", "quantity": "0.12", "unit_cost": "900"},
            {"kind": "labor", "description": "Steelfixer + mason", "unit": "h", "quantity": "3.5", "unit_cost": "42"},
            {"kind": "machinery", "description": "Concrete pump", "unit": "h", "quantity": "0.3", "unit_cost": "80"},
        ],
        overhead_pct="8",
        profit_pct="5",
        currency="EUR",
    )


def test_direct_cost_and_kind_totals():
    bd = _sample()
    # 96.90 concrete + 108 rebar + 147 labour + 24 machinery
    assert bd.direct_unit_cost == Decimal("375.90")
    kt = bd.kind_totals
    assert kt[ResourceKind.MATERIAL] == Decimal("204.90")
    assert kt[ResourceKind.LABOUR] == Decimal("147.00")
    assert kt[ResourceKind.MACHINERY] == Decimal("24.00")
    assert kt[ResourceKind.SUBCONTRACT] == Decimal("0")


def test_markup_stacks_in_order():
    bd = _sample()
    direct = Decimal("375.90")
    overhead = direct * Decimal("8") / 100
    risk = Decimal("0")
    profit = (direct + overhead + risk) * Decimal("5") / 100
    assert bd.overhead_amount == overhead
    assert bd.profit_amount == profit
    assert bd.unit_rate == direct + overhead + profit
    # Position total = unit rate * quantity.
    assert bd.position_total == bd.unit_rate * Decimal("50")


def test_to_dict_rounds_and_reconciles():
    d = _sample().to_dict()
    assert d["direct_unit_cost"] == "375.90"
    assert d["currency"] == "EUR"
    # kind_totals covers every category.
    assert set(d["kind_totals"]) == {k.value for k in ResourceKind}
    # unit_rate 2dp string.
    assert d["unit_rate"] == "426.27"


def test_component_amount_from_quantity_when_not_given():
    bd = build_breakdown(
        position_ref="1",
        description="x",
        unit="m2",
        position_quantity="10",
        components=[{"kind": "material", "description": "paint", "quantity": "0.25", "unit_cost": "12"}],
    )
    assert bd.components[0].amount == Decimal("3.00")
    assert bd.unit_rate == Decimal("3.00")  # no markup


def test_empty_components_raise():
    with pytest.raises(PriceBreakdownError):
        build_breakdown(position_ref="1", description="x", unit="m", position_quantity="1", components=[])


def test_coerce_kind_aliases():
    assert coerce_kind("Labour") is ResourceKind.LABOUR
    assert coerce_kind("operator") is ResourceKind.LABOUR
    assert coerce_kind("plant") is ResourceKind.MACHINERY
    assert coerce_kind("equipment") is ResourceKind.EQUIPMENT
    assert coerce_kind("subcontractor") is ResourceKind.SUBCONTRACT
    assert coerce_kind("overhead") is ResourceKind.OTHER
    assert coerce_kind("something weird") is ResourceKind.OTHER


def test_from_position_reads_metadata_resources():
    # Resource quantities are PER-UNIT norms: 1.05 m2 of blocks and half an hour
    # of mason go into one m2 of wall. The position is 20 m2, and that quantity
    # belongs to the position total, not to the norms.
    position = {
        "ordinal": "02.01.001",
        "description": "Blockwork wall",
        "unit": "m2",
        "quantity": "20",
        # 52.50 of direct cost, plus 10% overhead and 6% profit on the running
        # subtotal, so this position adds up rather than merely looking priced.
        "unit_rate": "61.22",
        "metadata_": {
            "resources": [
                {
                    "type": "material",
                    "name": "Blocks",
                    "unit": "m2",
                    "quantity": "1.05",
                    "unit_rate": "30",
                    "total": "31.50",
                },
                {"type": "labor", "name": "Mason", "unit": "h", "quantity": "0.5", "unit_rate": "42", "total": "21.00"},
            ]
        },
    }
    bd = from_position(position, overhead_pct="10", profit_pct="6")
    # Per-unit direct = 31.50 + 21.00 = 52.50, with no division by the 20.
    assert bd.direct_unit_cost == Decimal("52.50")
    assert bd.position_quantity == Decimal("20")
    # Overhead then profit.
    assert bd.overhead_amount == Decimal("52.50") * Decimal("10") / 100
    assert bd.currency == "EUR"


def test_from_position_derives_markup_from_boq_markups():
    position = {
        "ordinal": "1",
        "unit": "m",
        "quantity": "1",
        "unit_rate": "100",
        "metadata_": {
            "resources": [{"type": "material", "name": "pipe", "total": "100", "quantity": "1", "unit_rate": "100"}]
        },
    }
    markups = [
        {"category": "overhead", "markup_type": "percentage", "percentage": "12"},
        {"category": "profit", "markup_type": "percentage", "percentage": "8"},
        {"category": "tax", "markup_type": "percentage", "percentage": "19"},  # ignored
    ]
    bd = from_position(position, markups=markups)
    assert bd.overhead_pct == Decimal("12")
    assert bd.profit_pct == Decimal("8")


def test_from_position_without_resources_falls_back_to_unit_rate():
    position = {"ordinal": "9", "unit": "pcs", "quantity": "3", "unit_rate": "250", "metadata_": {}}
    bd = from_position(position)
    assert bd.direct_unit_cost == Decimal("250")
    assert bd.components[0].kind is ResourceKind.OTHER
    assert bd.position_total == Decimal("750")


def test_efb_view_and_markdown_render():
    bd = _sample()
    efb = efb_221_view(bd)
    labels = {row["label"] for row in efb["rows"]}
    assert any("221" in lbl for lbl in labels)  # Lohnkosten (221)
    assert efb["unit_rate"] == "426.27"

    md = render_markdown(bd, preset="efb")
    assert "EFB price sheets" in md
    assert "Position total:" in md
    # International preset labels differ.
    assert get_preset("international").label == "Unit price analysis"
    assert "Labour" in render_markdown(bd, preset="international")


# ---- new presets ---------------------------------------------------------


def test_new_presets_registered_with_labels_and_region():
    nrm = get_preset("nrm")
    assert nrm.region == "UK"
    assert "NRM" in nrm.label
    us = get_preset("us_bid")
    assert us.region == "US"
    cp = get_preset("cost_plus")
    assert cp.name == "cost_plus"
    # All presets cover every ResourceKind exactly once.
    for name in ("international", "efb", "nrm", "us_bid", "cost_plus"):
        p = get_preset(name)
        kinds = [k for k, _ in p.kind_labels]
        assert set(kinds) == set(ResourceKind)
        assert len(kinds) == len(set(ResourceKind))
    # Unknown name falls back to the international default.
    assert get_preset("does-not-exist").name == "international"


def test_nrm_and_us_presets_use_local_wording():
    assert dict(get_preset("nrm").kind_labels)[ResourceKind.MACHINERY] == "Plant"
    assert dict(get_preset("us_bid").kind_labels)[ResourceKind.LABOUR] == "Labor"
    assert "Plant" in render_markdown(_sample(), preset="nrm")


# ---- i18n keys -----------------------------------------------------------


def test_kind_i18n_keys_are_stable():
    assert kind_i18n_key(ResourceKind.LABOUR) == "price_breakdown.kind.labor"
    assert kind_i18n_key("plant") == "price_breakdown.kind.machinery"
    assert kind_i18n_key(ResourceKind.SUBCONTRACT) == "price_breakdown.kind.subcontractor"


def test_to_dict_exposes_i18n_keys():
    d = _sample().to_dict()
    assert d["i18n_keys"] == LINE_I18N_KEYS
    assert d["kind_i18n_keys"]["labor"] == "price_breakdown.kind.labor"
    assert d["components"][0]["kind_i18n_key"] == "price_breakdown.kind.material"


def test_preset_to_dict_carries_labels_and_keys():
    pd = get_preset("nrm").to_dict()
    assert pd["name"] == "nrm"
    assert pd["label_i18n_key"] == "price_breakdown.preset.nrm"
    plant = next(row for row in pd["kinds"] if row["kind"] == "machinery")
    assert plant["label"] == "Plant"
    assert plant["i18n_key"] == "price_breakdown.kind.machinery"
    assert pd["line_i18n_keys"]["unit_rate"] == "price_breakdown.line.unit_rate"


# ---- CSV renderer --------------------------------------------------------


def test_render_csv_structure_and_totals():
    import csv
    import io

    text = render_csv(_sample(), preset="international")
    rows = list(csv.reader(io.StringIO(text)))
    # Header block then column header then components.
    assert rows[0][0] == "Price analysis"
    header_idx = next(i for i, r in enumerate(rows) if r[:1] == ["Kind"])
    assert rows[header_idx] == ["Kind", "Description", "Unit", "Quantity", "Unit cost", "Amount"]
    # One row per component (four in the sample) directly after the header.
    comp_rows = rows[header_idx + 1 : header_idx + 5]
    assert len(comp_rows) == 4
    assert comp_rows[0][0] == "Material"
    assert comp_rows[0][5] == "96.90"  # 1.02 x 95
    # Summary lines present and carrying the computed amounts.
    flat = {r[0]: r for r in rows if r}
    assert flat["Direct cost per unit"][5] == "375.90"
    assert flat["Unit rate"][5] == "426.27"
    assert flat["Position total"][5] == "21313.53"  # 426.2706 x 50, rounded


def test_render_csv_quotes_awkward_descriptions_safely():
    import csv
    import io

    bd = build_breakdown(
        position_ref="7",
        description='Wall, "special", 24cm',
        unit="m2",
        position_quantity="1",
        components=[{"kind": "material", "description": 'Block, grade "A"', "quantity": "1", "unit_cost": "10"}],
    )
    text = render_csv(bd)
    rows = list(csv.reader(io.StringIO(text)))
    # Round-trips through the csv reader without breaking the columns.
    comp = next(r for r in rows if r and r[0] == "Material")
    assert comp[1] == 'Block, grade "A"'


# ---- robustness and edge cases -------------------------------------------


def test_negative_markup_is_clamped_to_zero():
    bd = build_breakdown(
        position_ref="1",
        description="x",
        unit="m",
        position_quantity="1",
        components=[{"kind": "material", "description": "m", "quantity": "1", "unit_cost": "100"}],
        overhead_pct="-25",
        profit_pct="-5",
    )
    assert bd.overhead_pct == Decimal("0")
    assert bd.profit_pct == Decimal("0")
    # Never falls below direct cost.
    assert bd.unit_rate == bd.direct_unit_cost == Decimal("100")


def test_absurd_markup_is_capped():
    bd = build_breakdown(
        position_ref="1",
        description="x",
        unit="m",
        position_quantity="1",
        components=[{"kind": "material", "description": "m", "quantity": "1", "unit_cost": "100"}],
        overhead_pct="99999",
    )
    assert bd.overhead_pct == MAX_MARKUP_PCT


def test_kind_totals_reconcile_exactly_to_direct_cost():
    bd = _sample()
    assert sum(bd.kind_totals.values(), Decimal("0")) == bd.direct_unit_cost


def test_zero_position_quantity_does_not_divide_by_zero():
    position = {
        "ordinal": "1",
        "unit": "m2",
        "quantity": "0",
        "unit_rate": "50",
        "metadata_": {
            "resources": [{"type": "material", "name": "block", "quantity": "1", "unit_rate": "30", "total": "600"}]
        },
    }
    bd = from_position(position)
    # Nothing divides by the position quantity any more, so a zero quantity is
    # not a special case here at all - the per-unit amounts are read as stored
    # and only the position total collapses.
    assert bd.position_quantity == Decimal("0")
    assert bd.direct_unit_cost == Decimal("600")
    assert bd.position_total == Decimal("0")


def test_a_position_quantity_never_shrinks_the_price_sheet():
    """A per-unit norm stays per-unit however large the position is.

    The 250 m3 case: dividing the stored amounts by the position quantity used
    to print 0.008 h of mason per m3, a direct cost of 0.40 and a position total
    of 100.00 under a rate of 100.00 per m3. Every figure except the position
    total was 250 times too small, and the sheet still reconciled against
    itself, so nothing flagged it. Each assertion below is written twice, once
    for the honest figure and once against the one the division produced.
    """

    def _sheet(quantity: str):
        return from_position(
            {
                "ordinal": "01.01",
                "description": "Concrete C30/37",
                "unit": "m3",
                "quantity": quantity,
                "unit_rate": "100.00",
                "metadata_": {
                    "resources": [
                        {"type": "labor", "name": "Mason", "unit": "h", "quantity": "2", "unit_rate": "20.00"},
                        {
                            "type": "material",
                            "name": "Concrete",
                            "unit": "m3",
                            "quantity": "1",
                            "unit_rate": "60.00",
                        },
                    ]
                },
            }
        )

    at_250 = _sheet("250")
    at_one = _sheet("1")

    # Same rate, same norms: the quantity moves the position total and nothing
    # else. A sheet that read correctly only at quantity 1 is the whole defect.
    assert at_250.direct_unit_cost == at_one.direct_unit_cost == Decimal("100.00")
    assert at_250.direct_unit_cost != Decimal("0.40")
    assert at_250.unit_rate == Decimal("100.00")
    assert at_250.position_total == Decimal("25000.00")
    assert at_250.position_total != Decimal("100.00")
    assert at_one.position_total == Decimal("100.00")

    # Two hours of mason per m3 of concrete. 0.008 h is not a buildable norm and
    # an estimator reading it would have known - nobody was shown it, because
    # the number only appears on a sheet nothing reconciles against.
    labour = next(c for c in at_250.components if c.kind is ResourceKind.LABOUR)
    assert labour.quantity == Decimal("2.0000")
    assert labour.quantity != Decimal("0.0080")
    assert labour.amount == Decimal("40.00")


def test_explicit_amount_overrides_quantity_times_unit_cost():
    bd = build_breakdown(
        position_ref="1",
        description="x",
        unit="m",
        position_quantity="1",
        components=[
            # quantity x unit_cost would be 50, but an explicit amount wins.
            {"kind": "labor", "description": "gang", "quantity": "2", "unit_cost": "25", "amount": "111"}
        ],
    )
    assert bd.components[0].amount == Decimal("111")
    assert bd.direct_unit_cost == Decimal("111")


def test_international_language_aliases():
    # German
    assert coerce_kind("Lohnkosten") is ResourceKind.LABOUR
    assert coerce_kind("Baustoffe") is ResourceKind.MATERIAL
    # French
    assert coerce_kind("main d'oeuvre") is ResourceKind.LABOUR
    assert coerce_kind("materiel") is ResourceKind.EQUIPMENT
    assert coerce_kind("sous-traitant") is ResourceKind.SUBCONTRACT
    # Spanish
    assert coerce_kind("Mano de obra") is ResourceKind.LABOUR
    assert coerce_kind("maquinaria") is ResourceKind.MACHINERY
    # Italian
    assert coerce_kind("manodopera") is ResourceKind.LABOUR
    assert coerce_kind("noli") is ResourceKind.MACHINERY
    # Russian
    assert coerce_kind("материалы") is ResourceKind.MATERIAL
    assert coerce_kind("оборудование") is ResourceKind.EQUIPMENT
