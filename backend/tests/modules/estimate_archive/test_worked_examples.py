# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The three worked examples of the sealed-estimate spec, priced by the engine.

Rates follow the bill's markup cascade: resource lines to cents, the stack at
full precision, the rate rounded once half up. Where the spec's figures assumed
a rounding per markup step they differ by a cent, and the test says so.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.estimate_archive import engine
from app.modules.estimate_archive.fixtures import (
    example_de_trench,
    example_fidic_pipe_surround,
    example_uk_trench,
)


def test_de_sealed_rate_follows_the_bill_cascade() -> None:
    payload = example_de_trench()
    result = engine.derive_rate(payload, "02.03.0040")
    assert result["sealed_net"] == "28.88"
    # Per-step rounding would give 36.15; the bill carries full precision.
    assert result["sealed_rate"] == "36.16"
    names = [s["name"] for s in result["markup_steps"]]
    assert names == ["BGK", "AGK", "WuG"]


def test_de_change_n07_original_basis_and_cost_plus_side_by_side() -> None:
    payload = example_de_trench()
    result = engine.derive_rate(
        payload,
        "02.03.0040",
        quantity="310",
        changes=[{"code": "L-TRENCH", "consumption": "0.62", "note": "Deeper trench, more hand digging"}],
        additions=[
            {
                "kind": "plant",
                "code": "SHORING",
                "description": "Trench shoring hire",
                "unit": "m3",
                "consumption": "1",
                "unit_cost": "3.40",
                "quote_ref": "Q-118",
                "price_date": "2026-11-03",
            }
        ],
        current_unit_costs={"L-TRENCH": "55.10"},
    )
    assert result["changed_net"] == "41.26"
    assert result["original_basis_rate"] == "51.65"
    assert result["cost_plus_net"] == "42.68"
    assert result["cost_plus_rate"] == "53.43"
    by_method = {m["method"]: m for m in result["methods"]}
    assert by_method["original_basis"]["total"] == "16011.50"
    assert by_method["cost_plus_markup"]["total"] == "16563.30"
    assert "chosen" not in result, "the engine never picks a method"
    assert engine.deviations(result) == []
    assert engine.unevidenced_additions(result) == []


def test_uk_wet_ground_instruction_flags_a_change_without_a_note() -> None:
    payload = example_uk_trench()
    sealed = engine.derive_rate(payload, "D20.1")
    assert sealed["sealed_net"] == "37.88"
    assert sealed["sealed_rate"] == "42.62"

    pump = {
        "kind": "plant",
        "code": "PUMP",
        "description": "Dewatering pump",
        "unit": "day",
        "consumption": "0.025",
        "unit_cost": "95.00",
        "quote_ref": "Plant schedule P4",
    }
    no_note = engine.derive_rate(
        payload, "D20.1", quantity="180", changes=[{"code": "LAB", "consumption": "0.42"}], additions=[pump]
    )
    assert no_note["changed_net"] == "42.50"
    assert no_note["original_basis_rate"] == "47.81"
    assert {m["method"]: m["total"] for m in no_note["methods"]}["original_basis"] == "8605.80"
    assert engine.deviations(no_note) == [{"code": "LAB", "field": "consumption", "old": "0.35", "new": "0.42"}]

    with_note = engine.derive_rate(
        payload,
        "D20.1",
        quantity="180",
        changes=[{"code": "LAB", "consumption": "0.42", "note": "Wet ground, slower excavation"}],
        additions=[pump],
    )
    assert engine.deviations(with_note) == []


def test_fidic_higher_grade_concrete_and_net_change() -> None:
    payload = example_fidic_pipe_surround()
    sealed = engine.derive_rate(payload, "4.07")
    assert sealed["sealed_net"] == "165.80"
    # Per-step rounding would give 188.01; the bill cascade gives 188.02.
    assert sealed["sealed_rate"] == "188.02"

    varied = engine.derive_rate(
        payload,
        "4.07",
        quantity="64",
        changes=[{"code": "CONC", "unit_cost": "113.50", "note": "Higher grade, dated quote 2026-10-20"}],
    )
    assert varied["changed_net"] == "184.18"
    assert varied["original_basis_rate"] == "208.86"
    new_total = Decimal({m["method"]: m["total"] for m in varied["methods"]}["original_basis"])
    assert new_total == Decimal("13367.04")
    replaced = Decimal(sealed["sealed_rate"]) * 64
    assert replaced == Decimal("12033.28")
    assert new_total - replaced == Decimal("1333.76")


def test_fingerprint_ignores_key_order_and_trailing_zeros_but_not_content() -> None:
    payload = example_fidic_pipe_surround()
    digest = engine.seal_digest(payload)
    assert len(digest) == 64

    reordered = dict(reversed(list(payload.items())))
    assert engine.seal_digest(reordered) == digest

    rebuilt = example_fidic_pipe_surround()
    assert engine.seal_digest(rebuilt) == digest, "re-export of the same content gives the same hash"

    tampered = example_fidic_pipe_surround()
    tampered["positions"][1]["resources"][2]["unit_cost"] = "99"
    assert engine.seal_digest(tampered) != digest


def test_canonical_numbers() -> None:
    assert engine.canon("52.80") == engine.canon("52.8") == "52.8"
    assert engine.canon("100") == "100"
    assert engine.canon(None) == "0"


def test_tax_and_lump_sum_markups_stay_out_of_a_unit_rate() -> None:
    payload = example_fidic_pipe_surround()
    payload["markups"].append(
        {
            "key": "m99",
            "name": "VAT",
            "category": "tax",
            "markup_type": "percentage",
            "percentage": "5",
            "fixed_amount": "0",
            "apply_to": "cumulative",
            "sort_order": 99,
            "is_active": True,
            "scope_ordinal": None,
            "overrides_key": None,
        }
    )
    payload["markups"].append(
        {
            "key": "m98",
            "name": "Mobilisation",
            "category": "overhead",
            "markup_type": "fixed",
            "percentage": "0",
            "fixed_amount": "25000",
            "apply_to": "direct_cost",
            "sort_order": 98,
            "is_active": True,
            "scope_ordinal": None,
            "overrides_key": None,
        }
    )
    assert engine.derive_rate(payload, "4.07")["sealed_rate"] == "188.02"


def test_a_scoped_override_applies_inside_its_section_only() -> None:
    payload = example_de_trench()
    agk = next(m for m in payload["markups"] if m["name"] == "AGK")
    payload["markups"].append(
        {
            "key": "m10",
            "name": "AGK earthworks",
            "category": "overhead",
            "markup_type": "percentage",
            "percentage": "0",
            "fixed_amount": "0",
            "apply_to": "cumulative",
            "sort_order": 50,
            "is_active": True,
            "scope_ordinal": "02.03",
            "overrides_key": agk["key"],
        }
    )
    result = engine.derive_rate(payload, "02.03.0040")
    # BGK 9.5 % and WuG 3 % only: 28.88 x 1.095 x 1.03 = 32.57
    assert result["sealed_rate"] == "32.57"
    assert [s["name"] for s in result["markup_steps"]] == ["BGK", "AGK earthworks", "WuG"]


def test_unknown_position_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        engine.derive_rate(example_de_trench(), "99.99")
