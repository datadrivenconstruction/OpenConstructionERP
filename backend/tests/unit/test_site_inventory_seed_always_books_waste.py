"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A seeded yard always books waste, because a waste report that reads zero is a bug report.

The waste ratio is the number this module's report exists to state. It was
computed for every metered material and then booked or not booked on a coin
flip, so a project whose materials all came up the other way produced a report
stating a waste ratio of zero - not an error, just a screen that looks broken.
Measured over twenty thousand freshly drawn project ids at the smallest register
the seeder can produce, that happened at the rate the weights predict, which is
roughly one project in two hundred and seventy.

The repair is a reserved position rather than a heavier coin: the first metered
material that consumed anything books its waste whatever the draw says, and
every material after it is drawn exactly as before. The draw is still made for
the reserved material, so the generator advances identically and the rest of the
register is unchanged.

These tests drive the real seeder. What is supplied is what the database would
answer - which priced lines the project meters, its currency, and the in-project
reference guards - because none of that is a draw. The guarantee is asserted the
way the fix states it: with the draw turned off entirely, the register must
still book exactly one waste movement, and it must be the reserved material
carrying it. Asserting only that the tile is non-empty would go on passing by
luck the moment the reserve broke.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from decimal import Decimal

import pytest

from app.modules.site_inventory import seed as si
from app.modules.site_inventory.ledger import MovementType
from app.modules.site_inventory.service import SiteInventoryService

_DRAWS_PER_ORDINAL = 25
_CATALOGUE = 40


class _EmptyResult:
    """What a query against a project nothing has seeded yet comes back with."""

    def scalars(self):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _StubSession:
    """Absorbs exactly what the seeder and the service ask of a session."""

    def __init__(self) -> None:
        self.added: list[object] = []

    async def execute(self, _stmt):
        return _EmptyResult()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        # The one thing a real flush does that this seeder depends on: the row
        # gets its id, because the movement payloads carry the item id.
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def rows(self, name: str) -> list:
        return [obj for obj in self.added if type(obj).__name__ == name]


def _material(index: int):
    """One priced material line, as the estimate hands it over.

    Every one of them carries an installed quantity, so every one of them
    consumes something and is therefore eligible to waste something. That makes
    the first material the reserved one, which is what the assertions below
    name.
    """
    return si._MeteredMaterial(
        position_id=uuid.uuid4(),
        name=f"Material {index}",
        code=f"MAT-{index:03d}",
        unit="m3",
        unit_cost=Decimal("120.50"),
        bill_quantity=Decimal("240") + Decimal(index),
        installed_quantity=Decimal("210") + Decimal(index),
        description=f"Material {index} priced in the estimate",
    )


@pytest.fixture
def seeded(monkeypatch):
    """Drive the real _seed_project, answering only what the database would."""
    materials = [_material(i) for i in range(_CATALOGUE)]

    async def metered_materials(_session, _project_id, _rng, limit):
        return list(materials[:limit])

    async def project_currency(_session, _project_id):
        return "EUR"

    async def _allow(self, *_args, **_kwargs) -> None:
        return None

    async def _get_item(self, _project_id, item_id):
        for obj in self.session.added:
            if type(obj).__name__ == "StockItem" and getattr(obj, "id", None) == item_id:
                return obj
        return None

    monkeypatch.setattr(si, "_metered_materials", metered_materials)
    monkeypatch.setattr(si, "_project_currency", project_currency)
    monkeypatch.setattr(SiteInventoryService, "_require_location_in_project", _allow)
    monkeypatch.setattr(SiteInventoryService, "_require_boq_position_in_project", _allow)
    monkeypatch.setattr(SiteInventoryService, "_require_req_item_in_project", _allow)
    monkeypatch.setattr(SiteInventoryService, "_require_goods_receipt_in_project", _allow)
    monkeypatch.setattr(SiteInventoryService, "get_item", _get_item)

    def _run(project_id: uuid.UUID, ordinal: int) -> _StubSession:
        session = _StubSession()
        asyncio.run(si._seed_project(session, project_id, "seeder", ordinal))
        return session

    return _run


def _waste(session: _StubSession) -> list:
    return [m for m in session.rows("StockMovement") if m.movement_type == MovementType.WASTE.value]


def _census(session: _StubSession) -> str:
    movements = session.rows("StockMovement")
    return (
        f"{len(session.rows('StockItem'))} item(s), {len(movements)} movement(s), "
        f"types {dict(sorted(Counter(m.movement_type for m in movements).items()))}"
    )


def test_every_seeded_yard_books_some_waste(seeded) -> None:
    """The property, over every register size the estate can produce."""
    for ordinal in range(len(si._METERED_POSITIONS)):
        for draw in range(_DRAWS_PER_ORDINAL):
            project_id = uuid.uuid4()
            session = seeded(project_id, ordinal)
            assert _waste(session), (
                f"{project_id} at ordinal {ordinal} (draw {draw}) seeded a yard that wasted nothing, "
                f"so its waste report states a ratio of zero: {_census(session)}"
            )


def test_the_reserved_material_is_what_carries_the_waste_ratio(seeded, monkeypatch) -> None:
    """Turn the draw off completely; the reserve alone must still carry the report.

    With the share at zero no material can be drawn into booking waste, so
    anything that survives is the reserved position and nothing else. This is
    the assertion that fails if the reserve is removed while the coin is merely
    made more generous - a wider distribution is not a guarantee.
    """
    monkeypatch.setattr(si, "_WASTE_DRAW_SHARE", 0.0)
    for ordinal in range(len(si._METERED_POSITIONS)):
        project_id = uuid.uuid4()
        session = seeded(project_id, ordinal)
        waste = _waste(session)
        assert len(waste) == 1, (
            f"{project_id} at ordinal {ordinal} booked {len(waste)} waste movement(s) with the draw "
            f"turned off, so something other than the reserved material is producing them: {_census(session)}"
        )
        items = session.rows("StockItem")
        assert waste[0].item_id == items[0].id, (
            f"{project_id} at ordinal {ordinal} carries its waste on {waste[0].item_id} rather than on the "
            f"first metered material {items[0].id}, so the reserve is not what the report is reading"
        )


def test_a_yard_that_wasted_nothing_is_visible_to_this_property(seeded) -> None:
    """The instrument has to be able to see the failure it is looking for.

    A property that cannot fail proves nothing when it passes, and the way this
    one would silently stop working is the movement type drifting away from the
    value being matched - which already happened once while measuring this, and
    reported every register as wasting nothing.
    """
    session = seeded(uuid.uuid4(), 0)
    assert _waste(session), "the fixture itself seeded no waste, so the checks above are vacuous"

    stripped = _StubSession()
    stripped.added = [obj for obj in session.added if obj not in _waste(session)]
    assert not _waste(stripped), "a yard with its waste movements removed still reads as having wasted something"
    assert stripped.rows("StockMovement"), "removing the waste removed every movement, so this control proves nothing"
