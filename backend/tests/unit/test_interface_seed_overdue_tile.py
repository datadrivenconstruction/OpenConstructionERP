# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠No project id can seed a demo register with an empty overdue tile.

The seeder derives its random number generator from the project id, so the
register is redrawn for every project and everything the demo screens show is a
draw. The overdue tile lost that draw: the seeder decided a row was settled
using its own pair of statuses while the report exempts a third, paused, from
ever counting as overdue, so a paused row got a past date the report then
refused to count. Measured over twenty thousand drawn ids, that emptied the tile
on 229 of them - roughly one register in eighty-seven, which fails a lane once
and then passes for a week.

The fix reserves the second position of every register for a status the report
can count and dates it into the past, so an overdue row is there by
construction. This asserts that as a property of the seeder rather than as an
observation about one project: the invariants that make it structural, checked
across drawn ids, party-pool sizes and ordinals.

The seeder itself is driven here, against a stub session that answers the three
lookups the way an empty database would. A paraphrase of the draw would only
test this reading of it. ``_seed_project`` is called directly rather than
through ``seed_interface_management_demo`` because the wrapper swallows a
per-project exception, which would turn a broken seeder into a silently smaller
population.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from app.modules.interface_management.models import InterfaceRecord
from app.modules.interface_management.register import can_be_overdue, is_overdue
from app.modules.interface_management.seed import (
    _MIN_PARTIES,
    _OVERDUE_CAPABLE_STATUSES,
    _REGISTER_SIZES,
    _RESERVED_OVERDUE_INDEX,
    _SETTLED_STATUSES,
    _TRADE_DISCIPLINE,
    _package_label,
    _Party,
    _seed_project,
)

# How many project ids the property is drawn over. The guarantee holds on every
# single draw, so this is not a sample size the property depends on - it is the
# backstop that catches a future change which makes the tile probabilistic
# again. At the losing rate this test exists to keep at zero, a few hundred draws
# see the failure many times over.
_DRAWS = 400

# The trades the PostgreSQL fixture registers, in the order
# ``_subcontractor_parties`` reads them back (active rows ordered by legal name).
# The pool size is part of the random stream, so it is varied rather than fixed:
# the property has to hold for the smallest register the seeder will build one
# for as well as for the demo's own six.
_FIXTURE_TRADES = ("concrete", "hvac", "electrical", "facade", "plumbing", "steel_erection")
_POOL_SIZES = (_MIN_PARTIES, 6)


def _parties(count: int) -> list[_Party]:
    return [
        _Party(
            name=f"Fixture Trades {index:02d}",
            work_package=_package_label(_FIXTURE_TRADES[index % len(_FIXTURE_TRADES)]),
            discipline=_TRADE_DISCIPLINE[_FIXTURE_TRADES[index % len(_FIXTURE_TRADES)]],
            subcontractor_id=uuid.uuid4(),
        )
        for index in range(count)
    ]


class _EmptyResult:
    """What an empty database answers to each of the seeder's three lookups."""

    def all(self) -> list:
        return []

    def scalars(self) -> _EmptyResult:
        return self

    def first(self) -> None:
        return None


class _StubSession:
    """Collects what the seeder adds and answers every query as empty."""

    def __init__(self) -> None:
        self.added: list[object] = []

    async def execute(self, _stmt: object) -> _EmptyResult:
        return _EmptyResult()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


async def _seed(project_id: uuid.UUID, parties: list[_Party], ordinal: int) -> list[InterfaceRecord]:
    """Seed one register through the real seeder and return its interfaces."""
    session = _StubSession()
    counts = await _seed_project(session, project_id, parties, ordinal)
    rows = [obj for obj in session.added if isinstance(obj, InterfaceRecord)]
    assert counts["interfaces"] == len(rows), (
        f"{project_id}: the seeder counted {counts['interfaces']} interface(s) and added {len(rows)}"
    )
    return rows


def _diagnosis(rows: list[InterfaceRecord], as_of: date) -> str:
    """Why a register has nothing overdue, in the terms the report decides it on."""
    reserved = rows[_RESERVED_OVERDUE_INDEX].status if len(rows) > _RESERVED_OVERDUE_INDEX else None
    census = dict(sorted(Counter(row.status for row in rows).items()))
    past_due = dict(sorted(Counter(row.status for row in rows if row.need_by_date < as_of).items()))
    exempt = sorted(status for status in census if not can_be_overdue(status))
    return (
        f"{len(rows)} row(s) as of {as_of}; statuses {census}; already past their need-by date {past_due}; "
        f"of those, statuses this report never counts as overdue: {exempt}; "
        f"reserved position {_RESERVED_OVERDUE_INDEX} holds {reserved!r}"
    )


def test_the_reserved_pools_can_still_be_drawn_from() -> None:
    """The two pools the reserved prefix samples have to be big enough to sample.

    Both draws ask for two values without replacement, so a status removed from
    the weights or newly exempted from the overdue rule would not make the tile
    thin - it would raise inside the seeder, and the wrapper would swallow that
    into a project that quietly seeds nothing. Named here so the cause arrives
    instead of the symptom.
    """
    assert len(_SETTLED_STATUSES) >= 2, f"the settled pool is {_SETTLED_STATUSES} and two are drawn from it"
    assert len(_OVERDUE_CAPABLE_STATUSES) >= 2, (
        f"the overdue-capable pool is {_OVERDUE_CAPABLE_STATUSES} and two are drawn from it"
    )
    for status in _OVERDUE_CAPABLE_STATUSES:
        assert can_be_overdue(status), f"{status!r} is in the overdue-capable pool yet the report exempts it"


def test_every_register_is_long_enough_to_reach_its_reserved_overdue_row() -> None:
    """The guaranteed row only exists if every register is longer than the prefix.

    The sizes and the reserved index are two numbers in the same module, and a
    register shortened below the index would move the guarantee off the end of
    its own register without changing anything the seeder asserts about itself.
    """
    for size in _REGISTER_SIZES:
        assert size > _RESERVED_OVERDUE_INDEX, (
            f"a register of {size} row(s) never reaches reserved position {_RESERVED_OVERDUE_INDEX}"
        )


def test_no_drawn_project_id_seeds_a_register_with_nothing_overdue() -> None:
    """The property: every id, every pool size, every ordinal, at least one overdue row.

    Read through the register's own ``is_overdue`` rather than by looking for a
    past date, because the two disagreeing is the whole fault: a paused row with
    a past date looks overdue to anyone reading the table and is not overdue to
    the report that draws the tile.
    """
    rng = random.Random(20260823)
    as_of = datetime.now(UTC).date()

    async def run() -> None:
        for draw in range(_DRAWS):
            project_id = uuid.UUID(bytes=rng.randbytes(16), version=4)
            parties = _parties(_POOL_SIZES[draw % len(_POOL_SIZES)])
            ordinal = draw % (len(_REGISTER_SIZES) + 1)
            rows = await _seed(project_id, parties, ordinal)

            assert rows, f"{project_id} at ordinal {ordinal} seeded no register at all"
            overdue = [row for row in rows if is_overdue(row, as_of)]
            assert overdue, (
                f"{project_id} at ordinal {ordinal} with {len(parties)} part(y/ies) seeded a register "
                f"with nothing overdue: {_diagnosis(rows, as_of)}"
            )
            # Not merely that something is overdue, but that the row the design
            # relies on is the one carrying it. Without this the test would go
            # on passing on luck alone once the guarantee was broken.
            reserved = rows[_RESERVED_OVERDUE_INDEX]
            assert is_overdue(reserved, as_of), (
                f"{project_id}: the reserved overdue row is {reserved.status!r} due "
                f"{reserved.need_by_date} against {as_of}, which this report does not count"
            )

    asyncio.run(run())


def test_a_register_with_nothing_overdue_is_visible_to_this_property() -> None:
    """The other polarity: the assertion above has to be able to fail.

    A test that only ever sees registers with an overdue row cannot tell a
    guarantee from an instrument that returns a non-empty list whatever it is
    handed. The same rows are dated forward here, and the same reading of them
    must then come back empty.
    """

    async def run() -> None:
        rows = await _seed(uuid.UUID(int=0x0E5EED), _parties(6), 0)
        as_of = datetime.now(UTC).date()
        assert [row for row in rows if is_overdue(row, as_of)], "the register under test has nothing to take away"

        ahead = as_of + timedelta(days=90)
        for row in rows:
            row.need_by_date = ahead
        assert not [row for row in rows if is_overdue(row, as_of)], (
            f"a register dated wholly into the future still reads as overdue: {_diagnosis(rows, as_of)}"
        )

    asyncio.run(run())
