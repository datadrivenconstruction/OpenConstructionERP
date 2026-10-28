# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo estate must give every project its own correspondence register.

Two defects, both reported by eye rather than by a gate, both fixed in
``0ada247a8``. What was seeded until then:

* Every demo project outside the five hand-curated ones ran the same ten
  hardcoded English tuples through ``_generate_module_data``. Heidelberg,
  Karlsruhe, New Delhi and Sao Paulo each carried the identical subjects in
  the identical order, on the identical day offsets. A fixed list applied once
  per project is not a register, and four projects opened side by side made
  that obvious to a reader in seconds.
* ``correspondence_type`` declares five values in the module's own schema and
  the seeder exercised three of them. ``notice`` and ``memo`` were legal,
  offered by the type filter, and unreachable in every demo on the platform,
  so two of the five labels selected nothing anywhere.

The vocabulary gate next door, ``test_demo_seed_speaks_module_vocabularies``,
passed throughout and was right to. It asks whether a seeded value falls
outside its schema's vocabulary. Identical registers are individually legal,
and an absent value is not a value, so a per-value check cannot see either
defect by construction. This file asks the two questions it structurally
cannot: are the registers distinct from one another, and does the estate as a
whole reach every word the schema declares.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data
from app.modules.correspondence.schemas import CORRESPONDENCE_TYPES

_BASE = datetime(2026, 1, 15, tzinfo=UTC)

# A letter in one of these states is finished with. A register in which every
# row is finished with is a filing cabinet, not a live register.
_TERMINAL_STATUSES = {"responded", "closed"}


def _generate(demo_id: str) -> dict[str, list[dict]]:
    """The module data one demo template generates, with throwaway ids.

    ``_generate_module_data`` is pure: no session, not async, and the ids it
    takes are only written into the rows it returns, so a fresh uuid per call
    is enough to run it for every template in a loop.
    """
    template = DEMO_TEMPLATES[demo_id]
    return _generate_module_data(
        template,
        project_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        demo_id=demo_id,
        base=_BASE,
    )


def _register(demo_id: str) -> list[dict]:
    """The correspondence rows one template generates.

    Emptiness is not asserted here. A helper that fails carries its complaint
    up under the name of whichever test called it, and a test reporting "no
    correspondence" while its own name promises something about duplicates or
    coverage is a false sentence about what was checked. Each test below says
    so in its own words instead.
    """
    return _generate(demo_id)["correspondence"]


# ── One register per project ─────────────────────────────────────────────


def test_no_two_projects_get_the_same_generated_correspondence_register() -> None:
    """Four demo projects on three continents carried the same ten letters.

    Only the content is compared - the subject line, which is the column a
    reader actually reads. ``reference_number`` is deliberately excluded and
    must stay excluded: OUT-2026-001 restarts at one in every project because
    a per-project register really does number from one, so comparing
    references would report a collision on every pair and fail on correct
    behaviour. Do not "fix" this test by widening the tuple to include it.

    The assertion is pairwise rather than "not all registers are identical".
    The weaker question passes on a handful of distinct registers shared out
    among thirty-odd projects, which is precisely the state that is still
    wrong and still visible: the reported defect was a pair, and only a
    pairwise check can see a pair.
    """
    registers = {demo_id: tuple(r["subject"] for r in _register(demo_id)) for demo_id in DEMO_TEMPLATES}
    empty = sorted(demo_id for demo_id, rows in registers.items() if not rows)
    assert not empty, f"{empty} generated no correspondence at all, so the comparison below would compare nothing"
    collisions = [(a, b) for a, b in itertools.combinations(sorted(registers), 2) if registers[a] == registers[b]]
    assert not collisions, (
        f"{len(collisions)} pair(s) of demo projects render an identical correspondence register: {collisions[:5]}"
    )


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_one_register_does_not_repeat_a_letter(demo_id: str) -> None:
    """A subject that appears twice in one register is a filing error.

    The subjects are interpolated from the project's own trades and firms, and
    a project with fewer trades than the register has slots wraps around the
    list. Two letters can therefore converge on the same words without anybody
    editing the seed, which is what this catches.
    """
    subjects = [r["subject"] for r in _register(demo_id)]
    assert subjects, f"{demo_id} generated no correspondence, so this check would pass on nothing"
    assert len(set(subjects)) == len(subjects), f"{demo_id} files the same letter more than once: {sorted(subjects)}"


# ── Every word the schema declares must be reachable ─────────────────────


def test_every_correspondence_type_is_reachable_somewhere_in_the_demo_estate() -> None:
    """``notice`` and ``memo`` were legal in the schema and seeded nowhere.

    The vocabulary is imported rather than restated so this follows the schema
    if it grows: a sixth type added to ``CORRESPONDENCE_TYPES`` and offered by
    the type filter has to appear in some demo, or it is another label that
    selects nothing.

    Coverage is measured across the whole estate rather than per project on
    purpose. A single project is not obliged to receive all five kinds; the
    platform is obliged to show a reader that all five exist.
    """
    seen = {r["correspondence_type"] for demo_id in DEMO_TEMPLATES for r in _register(demo_id)}
    assert seen, "no demo template generated any correspondence at all, so nothing was measured here"
    missing = set(CORRESPONDENCE_TYPES) - seen
    assert not missing, (
        f"the whole demo estate never seeds correspondence_type {sorted(missing)}, "
        f"so the type filter offers a value that selects nothing anywhere; seeded: {sorted(seen)}"
    )


# ── The register is alive ────────────────────────────────────────────────


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_a_generated_register_has_a_letter_still_outstanding(demo_id: str) -> None:
    """A register seeded entirely terminal shows a reader nothing to act on.

    Only the negative is asserted. Demanding that every status value appear
    would demand a seed containing states that are legitimately rare - the
    statuses are a lifecycle, and a demo whose every letter sat awaiting a
    reply would be as unrealistic as one where every letter is closed.

    A row with no status at all counts as outstanding, and that is not
    laxness: the column defaults to ``open`` at the writer, so a seed that
    states nothing produces an open letter in the database. Reading the key
    with ``[]`` instead would raise on such a row and report a missing key as
    though it were a dead register, which is a different claim.
    """
    rows = _register(demo_id)
    assert rows, f"{demo_id} generated no correspondence, so this check would pass on nothing"
    outstanding = [r for r in rows if r.get("status") not in _TERMINAL_STATUSES]
    assert outstanding, (
        f"{demo_id} seeds {len(rows)} letters and none is still outstanding, "
        f"so the register opens with nothing to act on; statuses: {sorted({r.get('status') for r in rows})}"
    )
