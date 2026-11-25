# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Model elements to BOQ quantities: figure, provenance, manual edits, link check.

Worked examples, all exact:

* 2.5 m3 + 1.5 m3 into an m3 line is 4.0000 m3, formula ``sum(volume_m3) x 1``.
* 1500 kg + 2500 kg into a t line is 4.0000 t.
* 0.764554857984 m3 (one cubic yard by definition) into a cy line is 1.0000 cy;
  0.09290304 m2 into sf is 1.0000 sf; 3.048 m into ft is 10.0000 ft.
* A line in hours gets no figure: ``unit_unsupported``, quantity untouched.
* An estimator who overwrote 4 with 10 keeps 10 when a third element is linked;
  the model figure 5.0000 is recorded beside it until they restore it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.bim_hub.link_quantity import (
    STATUS_NO_QUANTITY,
    STATUS_OK,
    STATUS_UNIT_UNSUPPORTED,
    link_quantity,
)
from app.modules.bim_hub.service import _COUNT_UNITS, BIMHubService, normalize_unit_token


def _lq(unit: str, *quantities: dict):
    return link_quantity(
        normalize_unit_token(unit),
        [(f"E{i}", q) for i, q in enumerate(quantities)],
        count_units=_COUNT_UNITS,
    )


def test_volume_sum_and_formula() -> None:
    r = _lq("m³", {"volume_m3": 2.5}, {"Volume": "1.5"})
    assert r.quantity == Decimal("4.0000")
    assert r.status == STATUS_OK
    assert r.contributing == 2
    assert r.key_counts == {"volume_m3": 1, "Volume": 1}
    assert r.formula == "sum(volume_m3+Volume) x 1 [m3 -> m3]"


def test_tonne_divides_kilograms() -> None:
    assert _lq("t", {"weight_kg": 1500}, {"weight_kg": 2500}).quantity == Decimal("4.0000")


@pytest.mark.parametrize(
    ("unit", "quantities", "expected"),
    [
        ("cy", {"volume_m3": "0.764554857984"}, "1.0000"),
        ("yd³", {"volume_m3": "7.64554857984"}, "10.0000"),
        ("sf", {"area_m2": "0.09290304"}, "1.0000"),
        ("ft", {"length_m": "3.048"}, "10.0000"),
        ("lb", {"weight_kg": "0.45359237"}, "1.0000"),
        ("mm", {"length_m": "1.25"}, "1250.0000"),
    ],
)
def test_exact_unit_conversion(unit: str, quantities: dict, expected: str) -> None:
    assert _lq(unit, quantities).quantity == Decimal(expected)


def test_unknown_unit_gets_no_figure() -> None:
    r = _lq("h", {"volume_m3": 3})
    assert r.status == STATUS_UNIT_UNSUPPORTED
    assert r.quantity is None


def test_missing_dimension_is_listed_not_summed() -> None:
    r = _lq("m", {"area_m2": 37.5}, {"length_m": 2})
    assert r.quantity == Decimal("2.0000")
    assert r.missing_ids == ["E0"]
    assert r.missing_count == 1
    only_area = _lq("m", {"area_m2": 37.5})
    assert only_area.status == STATUS_NO_QUANTITY
    assert only_area.quantity is None


def test_count_unit_counts_elements() -> None:
    r = _lq("Stk.", {"volume_m3": 7.5}, {})
    assert r.quantity == Decimal(2)
    assert r.formula == "count(elements) = 2"


# ── Through the service on PostgreSQL ────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as s:
        yield s


async def _project(s) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="O")
    s.add(owner)
    await s.flush()
    project = Project(id=uuid.uuid4(), name="P", description="", owner_id=owner.id)
    s.add(project)
    await s.flush()
    return project.id


async def _position(s, project_id, *, unit: str, quantity: str = "0", rate: str = "10", ordinal: str = "1"):
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="B", description="", status="draft")
    s.add(boq)
    await s.flush()
    pos = Position(
        boq_id=boq.id,
        ordinal=ordinal,
        description="p",
        unit=unit,
        quantity=quantity,
        unit_rate=rate,
        total="0",
        source="manual",
    )
    s.add(pos)
    await s.flush()
    return pos


async def _model(s, project_id, elements: list[tuple[str, dict]], *, version: str = "3"):
    from app.modules.bim_hub.models import BIMElement, BIMModel

    model = BIMModel(project_id=project_id, name="Tower", status="ready", version=version)
    s.add(model)
    await s.flush()
    rows = [
        BIMElement(model_id=model.id, stable_id=f"S{i}", element_type=etype, quantities=q)
        for i, (etype, q) in enumerate(elements)
    ]
    s.add_all(rows)
    await s.flush()
    return model, rows


@pytest.mark.asyncio
async def test_link_records_provenance(session) -> None:
    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="m3")
    model, elems = await _model(session, pid, [("Wall", {"volume_m3": 2.5}), ("Wall", {"volume_m3": 1.5})])
    await svc.create_links_bulk(pos.id, elems)
    await session.refresh(pos)
    assert pos.quantity == "4.0000"
    assert pos.total == "40.00"
    rec = pos.metadata_["bim_link_quantity"]
    assert rec["formula"] == "sum(volume_m3) x 1 [m3 -> m3]"
    assert rec["element_count"] == 2
    assert rec["models"] == [{"model_id": str(model.id), "name": "Tower", "version": "3", "elements": 2}]
    assert rec["applied_quantity"] == "4.0000"
    assert rec["manual_kept"] is False


@pytest.mark.asyncio
async def test_manual_quantity_survives_a_new_link(session) -> None:
    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="m3")
    _model_row, elems = await _model(
        session, pid, [("Wall", {"volume_m3": 2.5}), ("Wall", {"volume_m3": 1.5}), ("Wall", {"volume_m3": 1})]
    )
    await svc.create_links_bulk(pos.id, elems[:2])
    pos.quantity = "10"
    await session.flush()
    await svc.create_links_bulk(pos.id, elems[2:])
    await session.refresh(pos)
    assert pos.quantity == "10"
    rec = pos.metadata_["bim_link_quantity"]
    assert rec["manual_kept"] is True
    assert rec["model_quantity"] == "5.0000"
    await svc.restore_model_quantity(pos.id)
    await session.refresh(pos)
    assert pos.quantity == "5.0000"
    assert pos.metadata_["bim_link_quantity"]["manual_kept"] is False


@pytest.mark.asyncio
async def test_cubic_yard_line_from_si_model(session) -> None:
    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="CY", rate="150")
    _m, elems = await _model(session, pid, [("Slab", {"volume_m3": "7.64554857984"})])
    await svc.create_links_bulk(pos.id, elems)
    await session.refresh(pos)
    assert pos.quantity == "10.0000"
    assert pos.total == "1500.00"


@pytest.mark.asyncio
async def test_link_check_flags_gaps(session) -> None:
    from app.modules.bim_hub.validators import register_bim_link_validation_rules

    register_bim_link_validation_rules()
    svc = BIMHubService(session)
    pid = await _project(session)
    model, elems = await _model(
        session, pid, [("Wall", {"volume_m3": 2}), ("Wall", {"volume_m3": 3}), ("Door", {}), ("Door", {})]
    )
    hours = await _position(session, pid, unit="h", quantity="8", ordinal="2")
    await svc.create_links_bulk(hours.id, elems[:2])
    bound = await _position(session, pid, unit="m2", ordinal="3")
    bound.cad_model_id = str(model.id)
    await session.flush()

    report = await svc.link_check(model.id)
    assert report["element_total"] == 4
    assert report["unlinked_total"] == 2
    assert report["unlinked_by_type"] == [{"element_type": "Door", "count": 2}]
    by_rule = {f["rule_id"]: f for f in report["findings"]}
    assert by_rule["bim_link.elements_linked"]["params"]["count"] == "2"
    assert by_rule["bim_link.unit_supplied"]["params"]["ordinal"] == "2"
    assert by_rule["bim_link.positions_have_elements"]["params"]["ordinal"] == "3"
    await session.refresh(hours)
    assert hours.quantity == "8"


async def _wall_rule(svc, pid, pos) -> None:
    from app.modules.bim_hub.schemas import BIMQuantityMapCreate

    await svc.create_quantity_map(
        BIMQuantityMapCreate(
            project_id=pid,
            name="Walls",
            element_type_filter="Wall",
            quantity_source="volume_m3",
            unit="m3",
            boq_target={"position_id": str(pos.id)},
        )
    )


async def _apply(svc, model_id) -> None:
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest

    preview = await svc.apply_quantity_maps(QuantityMapApplyRequest(model_id=model_id, dry_run=True))
    await svc.apply_quantity_maps(
        QuantityMapApplyRequest(model_id=model_id, dry_run=False, preview_fingerprint=preview.preview_fingerprint)
    )


@pytest.mark.asyncio
async def test_rule_into_existing_position_recomputes_its_quantity(session) -> None:
    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="m3", rate="100")
    model, _elems = await _model(session, pid, [("Wall", {"volume_m3": 2.5}), ("Wall", {"volume_m3": 1.5})])
    await _wall_rule(svc, pid, pos)
    await _apply(svc, model.id)
    await session.refresh(pos)
    assert pos.quantity == "4.0000"
    assert pos.total == "400.00"
    rec = pos.metadata_["bim_link_quantity"]
    assert rec["applied_quantity"] == "4.0000"
    assert rec["element_count"] == 2
    assert rec["manual_kept"] is False


@pytest.mark.asyncio
async def test_rule_into_existing_position_keeps_a_manual_quantity_flagged(session) -> None:
    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="m3", quantity="12", rate="100")
    model, _elems = await _model(session, pid, [("Wall", {"volume_m3": 2.5}), ("Wall", {"volume_m3": 1.5})])
    await _wall_rule(svc, pid, pos)
    await _apply(svc, model.id)
    await session.refresh(pos)
    assert pos.quantity == "12"
    rec = pos.metadata_["bim_link_quantity"]
    assert rec["manual_kept"] is True
    assert rec["model_quantity"] == "4.0000"

    restored = await svc.restore_model_quantity(pos.id)
    assert restored["quantity"] == "4.0000"
    assert restored["provenance"]["manual_kept"] is False
    assert restored["provenance"]["applied_quantity"] == "4.0000"
    assert restored["provenance"]["formula"] == "sum(volume_m3) x 1 [m3 -> m3]"


@pytest.mark.asyncio
async def test_unlinked_element_ids_are_the_elements_without_a_link(session) -> None:
    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="m3")
    model, elems = await _model(session, pid, [("Wall", {"volume_m3": 2}), ("Door", {}), ("Door", {})])
    await svc.create_links_bulk(pos.id, elems[:1])
    assert await svc.unlinked_element_ids(model.id) == [str(elems[1].id), str(elems[2].id)]


@pytest.mark.asyncio
async def test_unlinked_ids_are_the_ids_the_viewer_loads_not_stable_ids(session) -> None:
    """The viewer keys meshes by the element ``id`` of the elements list; the stable id is another field."""
    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="m3")
    model, elems = await _model(session, pid, [("Wall", {"volume_m3": 2}), ("Door", {}), ("Door", {})])
    await svc.create_links_bulk(pos.id, elems[:1])
    viewer_ids = {str(e.id) for e in (await svc.list_elements(model.id))[0]}
    unlinked = await svc.unlinked_element_ids(model.id)
    assert len(unlinked) == 2
    assert set(unlinked) <= viewer_ids
    assert not set(unlinked) & {e.stable_id for e in elems}
