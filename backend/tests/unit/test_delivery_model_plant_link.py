# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Which figure of an owner-furnished item is in force: the plant register's or its own.

Pure checks of ``delivery_model.plant``; the writes and refusals are in
``tests/pg/test_delivery_model_plant_link_on_pg.py``.
"""

from __future__ import annotations

import sys
import types
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.modules.delivery_model import models, plant, schemas
from app.modules.delivery_model.messages import is_key_present

READS = "app.modules.plant_register.reads"
OWN = {"enquiry_date": "2026-10-01", "lead_time_days": 90}


def _dates(**kw) -> SimpleNamespace:
    base = {
        "code": "PL-010",
        "enquiry_date": date(2026, 9, 1),
        "lead_time_days": 140,
        "latest_order_date": date(2026, 12, 1),
    }
    return SimpleNamespace(**{**base, **kw})


def test_an_unlinked_item_keeps_its_own_figures() -> None:
    view = plant.with_dates({"plant_item_id": None, **OWN}, None)
    assert (view["enquiry_date"], view["lead_time_days"], view["latest_order_date"]) == ("2026-10-01", 90, None)
    assert (view["dates_source"], view["plant_item"]) == (plant.OWN, None)


def test_a_linked_item_takes_the_registers_figures() -> None:
    view = plant.with_dates({"plant_item_id": "x", **OWN}, _dates())
    assert (view["enquiry_date"], view["lead_time_days"], view["latest_order_date"]) == (
        "2026-09-01",
        140,
        "2026-12-01",
    )
    assert (view["dates_source"], view["plant_item"]) == (plant.REGISTER, {"code": "PL-010", "missing": False})


def test_the_register_wins_also_where_it_has_no_figure() -> None:
    view = plant.with_dates({"plant_item_id": "x", **OWN}, _dates(enquiry_date=None, lead_time_days=None))
    assert (view["enquiry_date"], view["lead_time_days"], view["dates_source"]) == (None, None, plant.REGISTER)


def test_a_link_the_register_does_not_answer_keeps_the_own_figures_and_says_so() -> None:
    view = plant.with_dates({"plant_item_id": "x", **OWN}, None)
    assert (view["enquiry_date"], view["lead_time_days"], view["dates_source"]) == ("2026-10-01", 90, plant.OWN)
    assert view["plant_item"] == {"code": None, "missing": True}


def test_the_view_passed_in_is_not_changed() -> None:
    given = {"plant_item_id": "x", **OWN}
    plant.with_dates(given, _dates())
    assert given == {"plant_item_id": "x", **OWN}


async def test_without_the_plant_register_nothing_is_read(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, READS, None)  # the import raises ImportError
    assert plant.installed() is False
    assert await plant.plant_item_dates(None, uuid.uuid4(), uuid.uuid4()) is None
    assert await plant.plant_item_id_by_code(None, uuid.uuid4(), "PL-010") is None


async def test_with_the_plant_register_its_port_is_asked_for_this_project(monkeypatch) -> None:
    asked: list[tuple] = []
    reads = types.ModuleType(READS)

    async def plant_item_dates(session, project_id, plant_item_id, *, today=None):
        asked.append((project_id, plant_item_id, today))
        return "dates"

    reads.plant_item_dates = plant_item_dates
    monkeypatch.setitem(sys.modules, READS, reads)
    pid, item, day = uuid.uuid4(), uuid.uuid4(), date(2026, 10, 13)
    assert plant.installed() is True
    assert await plant.plant_item_dates(None, pid, item, today=day) == "dates"
    assert asked == [(pid, item, day)]
    # A register that has no lookup by code yet answers nothing, it does not raise.
    assert await plant.plant_item_id_by_code(None, pid, "PL-010") is None


def test_the_link_is_a_soft_column_on_the_item_that_carries_the_own_lead_time() -> None:
    column = models.OwnerFurnishedItem.__table__.c.plant_item_id
    assert column.nullable and not column.foreign_keys
    assert {"enquiry_date", "lead_time_days"} <= set(models.OwnerFurnishedItem.__table__.c.keys())
    for schema in (schemas.OfiIn, schemas.OfiPatch):
        assert "plant_item_id" in schema.model_fields


def test_only_the_two_plant_files_of_the_module_name_the_plant_register() -> None:
    """plant.py reads the register, plant_port.py answers the register's package plan port."""
    root = Path(plant.__file__).parent
    readers = sorted(p.name for p in root.glob("*.py") if "modules.plant_register" in p.read_text(encoding="utf-8"))
    assert readers == ["plant.py", "plant_port.py"]


def test_every_refusal_of_the_link_has_a_sentence_in_both_languages() -> None:
    for code in ("plant_item_not_found", "plant_item_already_linked", "plant_register_unavailable"):
        for locale in ("en", "de"):
            assert is_key_present(f"delivery_model.errors.{code}", locale), (code, locale)
