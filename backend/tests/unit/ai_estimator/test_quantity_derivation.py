# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the WorkGroup derivation + assumptions descriptor.

Pure tests (no DB, no AI). They pin the human-facing provenance the dialogue
composer writes onto every group (design section 3.1): a short formula
sentence (``derivation``) and a list of plain-language proxy ``assumptions``.

Invariants:
    * Every real ``qty_formula`` resolves to a non-empty derivation sentence,
      so the integrity surface stays in lock-step with :mod:`quantities`.
    * Assumptions are non-empty only when a proxy was actually applied (the
      ``estimated`` flag), and name the proxy in plain language; a quantity
      taken straight from a confirmed value carries no assumptions.
    * An unknown formula degrades to an empty description, never raises.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_quantity_derivation.py -q
"""

from __future__ import annotations

from app.modules.ai_estimator.quantities import (
    FORMULAS,
    compute_quantity,
    describe_derivation,
)


def test_every_formula_has_a_human_derivation_sentence():
    """Each curated formula id resolves to a non-empty derivation sentence."""
    for formula_id in FORMULAS:
        qty = compute_quantity(formula_id, {}, "m2")
        derivation, _assumptions = describe_derivation(formula_id, {}, qty)
        assert derivation, f"formula {formula_id!r} must carry a derivation sentence"


def test_unknown_formula_degrades_to_empty():
    """An unknown formula id yields an empty description, never raises."""
    qty = compute_quantity("does_not_exist", {}, "m2")
    derivation, assumptions = describe_derivation("does_not_exist", {}, qty)
    assert derivation == ""
    assert assumptions == []


def test_inferred_perimeter_is_disclosed_as_an_assumption():
    """A wall area derived from a floor-area perimeter proxy names the proxy."""
    # Floor area only, no perimeter / ceiling height -> proxies fire.
    params = {"floor_area_m2": 12.0}
    qty = compute_quantity("wall_full", params, "m2")
    assert qty.estimated is True
    derivation, assumptions = describe_derivation("wall_full", params, qty)
    assert derivation == "perimeter x height less openings"
    assert any("perimeter inferred" in a for a in assumptions)
    assert any("ceiling height defaulted" in a for a in assumptions)


def test_confirmed_values_carry_no_assumptions():
    """A wall area built from confirmed perimeter + height has no assumptions."""
    params = {"perimeter_m": 14.0, "ceiling_height_m": 2.6}
    qty = compute_quantity("wall_full", params, "m2")
    assert qty.estimated is False
    derivation, assumptions = describe_derivation("wall_full", params, qty)
    assert derivation == "perimeter x height less openings"
    assert assumptions == []


def test_points_density_proxy_is_disclosed():
    """Electrical points derived from a floor-area density proxy disclose it."""
    params = {"floor_area_m2": 20.0}
    qty = compute_quantity("points", params, "pcs")
    assert qty.estimated is True
    _derivation, assumptions = describe_derivation("points", params, qty)
    assert any("points density proxy" in a for a in assumptions)


def test_lump_has_derivation_and_no_assumptions():
    """A lump-sum line has a derivation sentence but never a proxy assumption."""
    qty = compute_quantity("lump", {}, "lsum")
    assert qty.estimated is False
    derivation, assumptions = describe_derivation("lump", {}, qty)
    assert derivation == "single lump-sum line"
    assert assumptions == []
