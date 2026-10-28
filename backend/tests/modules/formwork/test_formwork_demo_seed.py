# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo seeder must name systems the catalogue actually ships.

``seed_demo_formwork`` picks its systems out of the catalogue BY NAME, and a
name it cannot find is skipped with a debug log rather than an error. That is
the right behaviour at runtime - one renamed catalogue row should not fail a
whole demo install - but it means a rename silently empties the demo project
instead of breaking anything loudly. The formwork page would go back to being
the empty screen that started this work, and every test would still pass.

So the coupling gets its own gate here. These tests need no database: both
sides are module-level constants.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.formwork.demo import _GENERIC, _RC_STRUCTURE
from app.modules.formwork.schemas import default_seed_systems

_CATALOGUE = {row["name"]: row for row in default_seed_systems()}


@pytest.mark.parametrize(
    ("label", "rows"),
    [("rc-structure-formwork", _RC_STRUCTURE), ("generic", _GENERIC)],
)
def test_every_demo_row_names_a_system_the_catalogue_ships(label, rows):
    """A demo row naming a system nobody seeds is an assignment that never appears."""
    missing = sorted({name for name, *_ in rows} - set(_CATALOGUE))
    assert not missing, f"{label} demo names systems absent from the starter catalogue: {missing}"


@pytest.mark.parametrize(
    ("label", "rows"),
    [("rc-structure-formwork", _RC_STRUCTURE), ("generic", _GENERIC)],
)
def test_demo_quantities_are_positive(label, rows):
    """Zero area prices to zero, which teaches a visitor nothing about the choice."""
    for name, area, reuses, waste, _note in rows:
        assert Decimal(area) > 0, f"{label}: {name} carries no contact area"
        assert reuses >= 1, f"{label}: {name} claims fewer than one use"
        assert Decimal(waste) >= 0, f"{label}: {name} carries negative waste"


def test_the_rc_pack_crosses_element_types():
    """A demo showing three walls teaches nothing about choosing a system.

    The point of the pack is the comparison, so assert it actually spans the
    element types rather than trusting the list to stay varied.
    """
    types = {_CATALOGUE[name]["system_type"] for name, *_ in _RC_STRUCTURE}
    assert {"wall", "column", "table", "beam", "props", "climbing"} <= types


def test_the_single_use_liner_is_seeded_at_one_use():
    """The liner is in the pack precisely to show a system that cannot amortise.

    Seeding it at 40 uses would price it like a panel set and delete the lesson.
    """
    liner = next(row for row in _RC_STRUCTURE if row[0] == "Circular column form, single-use liner")
    assert liner[2] == 1
    assert _CATALOGUE[liner[0]]["reuses_max"] == 1


@pytest.mark.parametrize(
    ("label", "rows"),
    [("rc-structure-formwork", _RC_STRUCTURE), ("generic", _GENERIC)],
)
def test_no_demo_row_claims_more_uses_than_the_system_allows(label, rows):
    """The seeder caps at ``reuses_max``; this asserts the cap never has to fire.

    A row that needs capping is a row whose stated programme was fiction, and
    the seeded number would silently differ from the one written here.
    """
    for name, _area, reuses, _waste, _note in rows:
        allowed = _CATALOGUE[name]["reuses_max"]
        assert reuses <= allowed, f"{label}: {name} claims {reuses} uses, catalogue allows {allowed}"
