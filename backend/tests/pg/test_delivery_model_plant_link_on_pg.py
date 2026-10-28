# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An owner-furnished item that is also a plant item, on PostgreSQL.

The register's read port is stood in for by a small module with the same two
functions, so these tests run with and without the plant register installed:
what is under test is this module's side of the port, which figure wins, what
is refused, and that nothing changes when there is no register.
"""

from __future__ import annotations

import sys
import types
import uuid
from dataclasses import dataclass, replace
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delivery_model import plant, seed
from app.modules.delivery_model.errors import DeliveryModelError
from app.modules.delivery_model.service import DeliveryModelService
from tests._pg import isolated_engine
from tests.pg.delivery_fixtures import build_world, call
from tests.pg.test_delivery_model_seed_on_pg import _mark_demo, _seed

pytestmark = pytest.mark.asyncio

READS = "app.modules.plant_register.reads"


@dataclass(frozen=True)
class Dates:
    plant_item_id: uuid.UUID
    code: str
    need_date: date | None
    date_basis: str
    latest_order_date: date | None
    effective_lead_weeks: int | None
    lead_time_days: int | None
    enquiry_date: date | None
    lead_source: str
    long_lead: bool
    procurement_route: str = "owner_furnished_contractor_installed"
    status: str = "identified"


def _register(monkeypatch, items: dict[tuple[uuid.UUID, uuid.UUID], Dates]) -> None:
    """A read port that holds ``items`` by ``(project id, plant item id)``, as the register looks them up."""
    reads = types.ModuleType(READS)

    async def plant_item_dates(session, project_id, plant_item_id, *, today=None):
        return items.get((project_id, plant_item_id))

    async def plant_item_id_by_code(session, project_id, code):
        return next((d.plant_item_id for (pid, _), d in items.items() if pid == project_id and d.code == code), None)

    reads.plant_item_dates = plant_item_dates
    reads.plant_item_id_by_code = plant_item_id_by_code
    monkeypatch.setitem(sys.modules, READS, reads)


def _no_register(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, READS, None)  # the import raises ImportError


def _dates(code: str = "PL-010", **kw) -> Dates:
    base = {
        "plant_item_id": uuid.uuid4(),
        "code": code,
        "need_date": date(2027, 6, 1),
        "date_basis": "fixed",
        "latest_order_date": date(2026, 12, 1),
        "effective_lead_weeks": 20,
        "lead_time_days": 140,
        "enquiry_date": date(2026, 9, 1),
        "lead_source": "supplier_quote",
        "long_lead": True,
    }
    return Dates(**{**base, **kw})


OWN = {"enquiry_date": "2026-10-01", "lead_time_days": 90}


def _item(code: str = "OFI-A", **kw) -> dict:
    return {"code": code, "description": "Switchboard", "item_kind": "equipment", "install_by": "owner", **OWN, **kw}


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        yield await build_world(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


async def _views(w) -> dict[str, dict]:
    return {v["code"]: v for v in await call(w, "ofi_views")}


async def _refused(w, fn: str, *args) -> tuple[str, int]:
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, fn, *args)
    return exc.value.code, exc.value.status_code


async def test_a_linked_item_shows_the_registers_dates_and_an_unlinked_one_its_own(world, monkeypatch) -> None:
    w = world
    d = _dates()
    _register(monkeypatch, {(w.project_id, d.plant_item_id): d})
    await call(w, "create_ofi", _item("OFI-A", plant_item_id=d.plant_item_id), w.manager)
    await call(w, "create_ofi", _item("OFI-B"), w.manager)
    views = await _views(w)
    linked, own = views["OFI-A"], views["OFI-B"]
    assert (linked["enquiry_date"], linked["lead_time_days"], linked["latest_order_date"]) == (
        "2026-09-01",
        140,
        "2026-12-01",
    )
    assert linked["dates_source"] == plant.REGISTER and linked["plant_item"] == {"code": "PL-010", "missing": False}
    assert linked["plant_item_id"] == str(d.plant_item_id)
    assert (own["enquiry_date"], own["lead_time_days"], own["latest_order_date"]) == ("2026-10-01", 90, None)
    assert (own["dates_source"], own["plant_item"], own["plant_item_id"]) == (plant.OWN, None, None)


async def test_the_register_wins_also_where_it_has_no_figure(world, monkeypatch) -> None:
    """An item the register holds is not described twice: its empty enquiry date is not filled from here."""
    w = world
    d = _dates(enquiry_date=None, lead_source="catalogue_default")
    _register(monkeypatch, {(w.project_id, d.plant_item_id): d})
    await call(w, "create_ofi", _item(plant_item_id=d.plant_item_id), w.manager)
    view = (await _views(w))["OFI-A"]
    assert (view["enquiry_date"], view["lead_time_days"], view["dates_source"]) == (None, 140, plant.REGISTER)


async def test_unlinking_brings_the_own_figures_back(world, monkeypatch) -> None:
    w = world
    d = _dates()
    _register(monkeypatch, {(w.project_id, d.plant_item_id): d})
    row = await call(w, "create_ofi", _item(plant_item_id=d.plant_item_id), w.manager)
    # The register has let the item go (no owner-furnished route any more); only then is the link ours to remove.
    let_go = replace(d, procurement_route="none_yet")
    _register(monkeypatch, {(w.project_id, d.plant_item_id): let_go})
    await call(w, "update_ofi", row.id, {"plant_item_id": None}, w.manager)
    view = (await _views(w))["OFI-A"]
    assert (view["enquiry_date"], view["lead_time_days"], view["dates_source"]) == ("2026-10-01", 90, plant.OWN)


async def test_a_plant_item_of_another_project_is_refused_like_a_missing_one(world, monkeypatch) -> None:
    w = world
    foreign = _dates()
    _register(monkeypatch, {(uuid.uuid4(), foreign.plant_item_id): foreign})
    assert await _refused(w, "create_ofi", _item(plant_item_id=foreign.plant_item_id), w.manager) == (
        "plant_item_not_found",
        404,
    )
    assert await _refused(w, "create_ofi", _item(plant_item_id=uuid.uuid4()), w.manager) == (
        "plant_item_not_found",
        404,
    )
    row = await call(w, "create_ofi", _item(), w.manager)
    assert await _refused(w, "update_ofi", row.id, {"plant_item_id": foreign.plant_item_id}, w.manager) == (
        "plant_item_not_found",
        404,
    )
    assert (await _views(w))["OFI-A"]["plant_item_id"] is None


async def test_one_plant_item_is_one_owner_furnished_item(world, monkeypatch) -> None:
    w = world
    d = _dates()
    _register(monkeypatch, {(w.project_id, d.plant_item_id): d})
    first = await call(w, "create_ofi", _item("OFI-A", plant_item_id=d.plant_item_id), w.manager)
    assert await _refused(w, "create_ofi", _item("OFI-B", plant_item_id=d.plant_item_id), w.manager) == (
        "plant_item_already_linked",
        409,
    )
    # Saying again what the item already is, is not a second claim.
    await call(w, "update_ofi", first.id, {"plant_item_id": d.plant_item_id}, w.manager)


async def test_without_the_plant_register_the_module_is_unchanged(world, monkeypatch) -> None:
    w = world
    _no_register(monkeypatch)
    assert plant.installed() is False
    row = await call(w, "create_ofi", _item(), w.manager)
    view = (await _views(w))["OFI-A"]
    assert (view["enquiry_date"], view["lead_time_days"], view["dates_source"]) == ("2026-10-01", 90, plant.OWN)
    assert await _refused(w, "update_ofi", row.id, {"plant_item_id": uuid.uuid4()}, w.manager) == (
        "plant_register_unavailable",
        422,
    )


async def test_a_link_whose_plant_item_is_gone_keeps_the_own_figures_and_says_so(world, monkeypatch) -> None:
    w = world
    d = _dates()
    _register(monkeypatch, {(w.project_id, d.plant_item_id): d})
    await call(w, "create_ofi", _item(plant_item_id=d.plant_item_id), w.manager)
    _register(monkeypatch, {})
    gone = (await _views(w))["OFI-A"]
    assert (gone["enquiry_date"], gone["lead_time_days"], gone["dates_source"]) == ("2026-10-01", 90, plant.OWN)
    assert gone["plant_item"] == {"code": None, "missing": True}
    _no_register(monkeypatch)
    assert (await _views(w))["OFI-A"]["plant_item"] == {"code": None, "missing": True}


async def test_the_demo_links_the_switchboard_once_the_register_has_seeded(world, monkeypatch) -> None:
    w = world
    await _mark_demo(w)
    _no_register(monkeypatch)
    await _seed(w)
    async with w.factory() as s:
        assert await seed.link_demo_plant_items(s, [w.project_id]) == {
            "linked": 0,
            "skipped": [{"project_id": str(w.project_id), "reason": "plant_register_unavailable"}],
        }
    # The register has the item but no owner-furnished route yet; setting it is the register's own write, which
    # asks this module for the owner-furnished item and then holds the route.
    d = _dates(seed.DEMO_PLANT_ITEM, procurement_route="none_yet")
    items = {(w.project_id, d.plant_item_id): d}
    _register(monkeypatch, items)

    async def set_route(session, project_id, plant_item_id, *, installer_package_id, actor_id):
        await DeliveryModelService(session).ensure_ofi_for_plant_item(
            project_id, plant_item_id, title="Switchboard", installer_package_id=installer_package_id, actor_id=actor_id
        )
        items[(project_id, plant_item_id)] = replace(d, procurement_route=plant.CONTRACTOR_INSTALLS)

    monkeypatch.setattr(plant, "set_owner_furnished_route", set_route)
    async with w.factory() as s:
        assert await seed.link_demo_plant_items(s, [w.project_id]) == {"linked": 1, "skipped": []}
        await s.commit()
    async with w.factory() as s:  # the second run finds it linked and asks nothing
        assert await seed.link_demo_plant_items(s, [w.project_id]) == {
            "linked": 0,
            "skipped": [{"project_id": str(w.project_id), "reason": "already_owner_furnished"}],
        }
    views = await _views(w)
    # The register asked for its own item; the story's other items stay what they were.
    assert views[f"OFI-{d.code}"]["plant_item"] == {"code": d.code, "missing": False}
    assert views["OFI-01"]["plant_item"] is None and views["OFI-02"]["plant_item"] is None
