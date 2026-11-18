# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An RFQ scope picked from BOQ resources: summed per resource, checked against the project.

The quantities a supplier is asked to price are the BOQ totals (norm times
position quantity), recomputed on the server from the picked keys. A pick that
is empty, repeated, from another project's BOQ or no longer in the BOQ is a
4xx with a message an estimator can act on.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.rfq_bidding import service as service_module
from app.modules.rfq_bidding.boq_resources import aggregate_resources, resource_key
from app.modules.rfq_bidding.schemas import RFQCreate
from app.modules.rfq_bidding.service import RFQService

_POSITIONS = [
    (
        "p1",
        "10",
        {
            "resources": [
                {"name": "Concrete C30/37", "type": "material", "unit": "m3", "quantity": 1.05},
                {"name": "Mason", "type": "Labour", "unit": "h", "quantity": "2"},
            ]
        },
    ),
    (
        "p2",
        "5",
        {
            "resources": [
                {"name": "concrete c30/37", "type": "material", "unit": "m3", "quantity": "1"},
                {"name": "Crane", "type": "machinery", "unit": "h", "quantity": "0.5"},
                {"name": "", "type": "material", "unit": "m3", "quantity": "1"},
                {"name": "Broken", "type": "material", "unit": "m3", "quantity": "n/a"},
            ]
        },
    ),
    ("p3", "not a number", {"resources": [{"name": "Ghost", "type": "material", "unit": "kg", "quantity": "1"}]}),
    ("p4", "3", None),
]


def test_resources_are_summed_per_resource_across_positions() -> None:
    options = {o.name.lower(): o for o in aggregate_resources(_POSITIONS)}
    assert set(options) == {"concrete c30/37", "mason", "crane"}
    concrete = options["concrete c30/37"]
    assert concrete.quantity == Decimal("15.5000")
    assert concrete.position_ids == ["p1", "p2"]
    assert concrete.category == "material"
    assert options["mason"].category == "labor"
    assert options["mason"].quantity == Decimal("20.0000")
    assert options["crane"].category == "machinery"


def test_a_resource_without_a_unit_is_priced_as_a_lot() -> None:
    [option] = aggregate_resources([("p1", "2", {"resources": [{"name": "Site setup", "quantity": "1"}]})])
    assert option.unit == "lot"
    assert option.category == "other"


def test_the_key_names_the_resource_not_its_position() -> None:
    assert resource_key("material", None, "Concrete", "m3") == resource_key("material", None, " concrete ", "M3")
    assert resource_key("material", None, "Concrete", "m3") != resource_key("material", None, "Concrete", "t")


def _create(**extra: object) -> RFQCreate:
    return RFQCreate(project_id=uuid.uuid4(), title="Concrete package", **extra)


def test_the_dialog_body_without_boq_fields_is_valid() -> None:
    data = _create(description="Béton", submission_deadline="2026-12-15")
    assert data.boq_resource_keys is None
    assert data.currency_code == "EUR"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"boq_id": uuid.uuid4(), "boq_resource_keys": []}, "at least one BOQ resource"),
        ({"boq_resource_keys": ["a"]}, "boq_id is required"),
        ({"boq_id": uuid.uuid4(), "boq_resource_keys": ["a", "a"]}, "only once"),
    ],
)
def test_a_bad_boq_pick_is_a_clear_validation_error(extra: dict, message: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _create(**extra)
    assert message in str(exc.value)


class _Result:
    def __init__(self, row: object) -> None:
        self.row = row

    def scalar_one_or_none(self) -> object:
        return self.row


class _Session:
    """Enough of an AsyncSession for ``RFQRepository.create``: add, flush, re-read."""

    def __init__(self) -> None:
        self.added: object | None = None
        self.reads = 0

    def add(self, obj: object) -> None:
        self.added = obj

    async def flush(self) -> None:
        return None

    async def execute(self, _stmt: object) -> _Result:
        self.reads += 1
        return _Result(self.added)


async def test_a_created_rfq_is_read_back_with_its_collections_loaded() -> None:
    """A flushed new RFQ has no loaded ``bids``; the response lazy-loaded them and answered 500."""
    from app.modules.rfq_bidding.models import RFQ
    from app.modules.rfq_bidding.repository import RFQRepository

    session = _Session()
    rfq = RFQ(project_id=uuid.uuid4(), rfq_number="RFQ-001", title="Ductwork")
    created = await RFQRepository(session).create(rfq)  # type: ignore[arg-type]
    assert created is rfq
    assert session.reads == 1


def _service_over(monkeypatch: pytest.MonkeyPatch, boq_project: uuid.UUID) -> RFQService:
    async def _project_of(_session: object, _boq_id: uuid.UUID) -> uuid.UUID:
        return boq_project

    async def _load(_session: object, _boq_id: uuid.UUID) -> list:
        return aggregate_resources(_POSITIONS)

    monkeypatch.setattr(service_module, "boq_project_id", _project_of)
    monkeypatch.setattr(service_module, "load_boq_resources", _load)
    service = RFQService(_Session())  # type: ignore[arg-type]

    async def _next(_project_id: uuid.UUID) -> str:
        return "RFQ-001"

    service.rfqs.next_rfq_number = _next  # type: ignore[method-assign]
    return service


async def test_picked_resources_become_numbered_scope_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid.uuid4()
    service = _service_over(monkeypatch, project_id)
    options = {o.name: o for o in aggregate_resources(_POSITIONS)}
    data = RFQCreate(
        project_id=project_id,
        title="Concrete and crane",
        boq_id=uuid.uuid4(),
        boq_resource_keys=[options["Concrete C30/37"].key, options["Crane"].key],
    )
    rfq = await service.create_rfq(data)
    assert [(ln.line_no, ln.description, ln.unit, ln.quantity) for ln in rfq.lines] == [
        (1, "Concrete C30/37", "m3", Decimal("15.5000")),
        (2, "Crane", "h", Decimal("2.5000")),
    ]
    assert rfq.lines[0].metadata_["source"] == "boq_resource"
    assert rfq.lines[0].metadata_["position_ids"] == ["p1", "p2"]


async def test_another_projects_boq_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service_over(monkeypatch, uuid.uuid4())
    key = aggregate_resources(_POSITIONS)[0].key
    data = RFQCreate(project_id=uuid.uuid4(), title="Cross", boq_id=uuid.uuid4(), boq_resource_keys=[key])
    with pytest.raises(HTTPException) as exc:
        await service.create_rfq(data)
    assert exc.value.status_code == 422
    assert "does not belong to this project" in exc.value.detail


async def test_a_key_no_longer_in_the_boq_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid.uuid4()
    service = _service_over(monkeypatch, project_id)
    data = RFQCreate(project_id=project_id, title="Stale", boq_id=uuid.uuid4(), boq_resource_keys=["0" * 20])
    with pytest.raises(HTTPException) as exc:
        await service.create_rfq(data)
    assert exc.value.status_code == 422
    assert "no longer in this BOQ" in exc.value.detail
