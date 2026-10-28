# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The allowances demo seed hands every project a register of its own.

A demo estate in which two projects list the same allowances teaches the reader
that the data is generated, which is the one thing a demo must not say. The
database-side test asserts that on six seeded projects; it cannot assert it on
the eleven the estate actually holds, and while the register was sampled at
random it could not assert it at all - a sample only makes a repeat unlikely, so
a green run meant nothing in particular.

These are the properties stated over the selection itself, with no database in
the way, so they hold for every position rather than for the six a fixture
happens to build:

* no two positions produce the same register (the property the seed exists for);
* there are far more registers to hand out than there are projects to hand them
  to, which is the arithmetic underneath that property. A pool no longer than
  the estate cannot help but repeat itself;
* every register leaves at least one allowance untouched, carries all three
  kinds, and stops short of the whole catalogue (the properties the register has
  to keep while the first one is being widened);
* the size pool never reaches the ceiling, which is what flattened eight of
  eleven projects onto one length in the first place.
"""

from __future__ import annotations

from app.modules.allowances.seed import (
    _CATALOGUE,
    _CORE_SPECS,
    _MAX_REGISTER,
    _OPTIONAL_SPECS,
    _REGISTER_SIZES,
    _optional_registers,
    _select_specs,
)

# Comfortably past the eleven demo projects the estate holds, so the properties
# are stated over a longer run than the product ever seeds.
_POSITIONS = 44


def _register(ordinal: int) -> list:
    slot = ordinal % len(_REGISTER_SIZES)
    return _select_specs(ordinal, min(_REGISTER_SIZES[slot], _MAX_REGISTER))


def _labels(ordinal: int) -> frozenset[str]:
    return frozenset(spec.label for spec in _register(ordinal))


def test_no_two_positions_are_handed_the_same_register() -> None:
    seen: dict[frozenset[str], int] = {}
    for ordinal in range(_POSITIONS):
        labels = _labels(ordinal)
        clash = seen.get(labels)
        assert clash is None, f"positions {clash} and {ordinal} list exactly the same allowances"
        seen[labels] = ordinal


def test_there_are_far_more_registers_than_projects_to_hand_them_to() -> None:
    """The arithmetic the guarantee rests on, stated per size.

    Rotating over a pool yields no more distinct registers than the pool is
    long, which is why the choice is a combination of the optional catalogue
    rather than a position in it. The tightest size is the widest register, ten
    optional specs out of thirteen, and even that leaves 286 registers against
    an estate of eleven projects.
    """
    for size in _REGISTER_SIZES:
        available = len(_optional_registers(size - len(_CORE_SPECS)))
        assert available >= 250, f"a register of {size} has only {available} form(s) to take"


def test_every_register_leaves_an_allowance_untouched() -> None:
    """Every core spec is drawn against, so the untouched state comes from the rest."""
    for ordinal in range(_POSITIONS):
        register = _register(ordinal)
        assert any(not spec.draws for spec in register), f"position {ordinal} draws against every allowance it holds"


def test_every_register_carries_the_core_and_all_three_kinds() -> None:
    core = {spec.label for spec in _CORE_SPECS}
    for ordinal in range(_POSITIONS):
        register = _register(ordinal)
        assert core <= {spec.label for spec in register}, f"position {ordinal} dropped a core allowance"
        assert {spec.allowance_type for spec in register} == {"provisional_sum", "pc_sum", "contingency"}
        assert len(register) == len(set(spec.key for spec in register)), f"position {ordinal} repeats an allowance"


def test_a_register_is_a_part_of_the_catalogue_not_the_whole_of_it() -> None:
    for ordinal in range(_POSITIONS):
        register = _register(ordinal)
        assert len(register) <= _MAX_REGISTER < len(_CATALOGUE), (
            f"position {ordinal} asks for {len(register)} of {len(_CATALOGUE)} allowances"
        )


def test_the_size_pool_stays_clear_of_the_ceiling() -> None:
    """The root cause, stated so it cannot come back.

    Sizes used to grow with each wrap and get clamped at the ceiling, which put
    most of the estate on one length. A size at or over the ceiling is the shape
    of that bug, and a size pool with a repeat in it wastes a position.
    """
    assert len(set(_REGISTER_SIZES)) == len(_REGISTER_SIZES), "the size pool repeats a length"
    assert max(_REGISTER_SIZES) <= _MAX_REGISTER, "a register size reaches the ceiling and is clamped to it"
    assert min(_REGISTER_SIZES) > len(_CORE_SPECS), "the smallest register is all core and has nothing to vary"
    assert _MAX_REGISTER - len(_CORE_SPECS) <= len(_OPTIONAL_SPECS), "the ceiling asks for more than the catalogue has"
