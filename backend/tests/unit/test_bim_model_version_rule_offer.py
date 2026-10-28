# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An upload can be a new version of a model, and then offers its quantity rules again.

The upload names the model it replaces (``parent_model_id``); the server checks
that the parent is a finished model of the same project that no finished newer
version has replaced yet, and numbers the new one after it. On the new version
the viewer asks how many quantity rules priced the earlier one, per BOQ, and
sends the user to each BOQ's change review. Nothing here applies a rule.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.bim_hub import router as bim_router
from app.modules.bim_hub.models import BIMElement, BIMModel, BIMQuantityMap, BOQElementLink
from app.modules.bim_hub.service import BIMHubService, next_model_version
from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as value:
        yield value


async def seed(session, *, v2_status="ready"):
    owner = User(email=f"version-{uuid.uuid4().hex}@test.io", hashed_password="x", full_name="Version")
    session.add(owner)
    await session.flush()
    project = Project(name="Restauro", owner_id=owner.id, currency="EUR")
    other = Project(name="Elsewhere", owner_id=owner.id, currency="EUR")
    session.add_all([project, other])
    await session.flush()
    v1 = BIMModel(project_id=project.id, name="Palazzo", version="1", status="ready")
    foreign = BIMModel(project_id=other.id, name="Foreign", version="1", status="ready")
    session.add_all([v1, foreign])
    await session.flush()
    v2 = BIMModel(project_id=project.id, name="Palazzo", version="2", status=v2_status, parent_model_id=v1.id)
    boq = BOQ(project_id=project.id, name="Bill", is_locked=False)
    session.add_all([v2, boq])
    await session.flush()
    walls = [
        BIMElement(model_id=v1.id, stable_id=f"w-{i}", element_type="Walls", quantities={"area": 10}) for i in range(2)
    ]
    session.add_all(walls)
    walls_pos = Position(boq_id=boq.id, ordinal="01.001", description="Muratura", unit="m2", quantity="20")
    doors_pos = Position(boq_id=boq.id, ordinal="01.002", description="Porte", unit="m2", quantity="0")
    session.add_all([walls_pos, doors_pos])
    rule = BIMQuantityMap(project_id=project.id, name="Walls", element_type_filter="Walls", quantity_source="area")
    retired = BIMQuantityMap(project_id=project.id, name="Old", quantity_source="area", is_active=False)
    session.add_all([rule, retired])
    await session.flush()
    links = [
        BOQElementLink(boq_position_id=walls_pos.id, bim_element_id=w.id, link_type="rule_based", rule_id=str(rule.id))
        for w in walls
    ]
    links.append(
        BOQElementLink(
            boq_position_id=doors_pos.id, bim_element_id=walls[0].id, link_type="rule_based", rule_id=str(retired.id)
        )
    )
    links.append(BOQElementLink(boq_position_id=doors_pos.id, bim_element_id=walls[1].id, link_type="manual"))
    session.add_all(links)
    await session.flush()
    return {"project": project, "v1": v1, "v2": v2, "foreign": foreign, "boq": boq, "rule": rule, "retired": retired}


@pytest.mark.parametrize(
    ("version", "expected"),
    [("1", "2"), ("9", "10"), ("v3", "v4"), ("R-12", "R-13"), ("", "2"), (None, "2"), ("final", "2")],
)
def test_the_next_version_counts_up_from_the_parent(version, expected):
    assert next_model_version(version) == expected


def test_both_upload_routes_take_the_model_they_replace():
    for route in (bim_router.upload_bim_data, bim_router.upload_cad_file):
        assert "parent_model_id" in inspect.signature(route).parameters


def test_every_model_an_upload_creates_carries_the_version_link():
    # The data upload, the CAD upload and the placeholder a CAD upload saves
    # when its converter is missing all create a model; each must carry the
    # parent, or a retry after installing the converter loses the link.
    source = inspect.getsource(bim_router.upload_bim_data) + inspect.getsource(bim_router.upload_cad_file)
    assert source.count("BIMModelCreate(") == 3
    assert source.count("**version_fields") == 3


@pytest.mark.asyncio
async def test_a_finished_model_of_the_project_is_accepted_as_parent(session):
    s = await seed(session, v2_status="error")
    parent = await BIMHubService(session).version_parent(s["project"].id, s["v1"].id)
    assert parent.id == s["v1"].id


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["foreign", "missing"])
async def test_a_parent_outside_the_project_is_refused(session, which):
    s = await seed(session)
    parent_id = s["foreign"].id if which == "foreign" else uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await BIMHubService(session).version_parent(s["project"].id, parent_id)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "bim_versions.parent_not_found"
    assert exc.value.detail["message"] and "bim_versions" not in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_a_parent_still_importing_is_refused(session):
    s = await seed(session)
    s["v2"].status = "processing"
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await BIMHubService(session).version_parent(s["project"].id, s["v2"].id)
    assert exc.value.detail["code"] == "bim_versions.parent_not_ready"
    assert "Palazzo" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_a_parent_already_replaced_is_refused_naming_the_newer_version(session):
    s = await seed(session)
    with pytest.raises(HTTPException) as exc:
        await BIMHubService(session).version_parent(s["project"].id, s["v1"].id)
    assert exc.value.detail["code"] == "bim_versions.parent_superseded"
    assert "2" in exc.value.detail["message"]
    # The newest version is the one to build on.
    assert (await BIMHubService(session).version_parent(s["project"].id, s["v2"].id)).id == s["v2"].id


@pytest.mark.asyncio
async def test_the_new_version_offers_the_active_rules_that_priced_the_old_one(session):
    s = await seed(session)
    offer = await BIMHubService(session).quantity_rule_offer(s["v2"].id)
    assert offer["parent_model_id"] == s["v1"].id
    assert offer["rule_count"] == 1
    assert offer["boqs"] == [
        {"boq_id": s["boq"].id, "boq_name": "Bill", "rule_count": 1, "position_count": 1},
    ]


@pytest.mark.asyncio
async def test_a_third_version_still_finds_the_rules_linked_on_the_first(session):
    s = await seed(session)
    v3 = BIMModel(project_id=s["project"].id, name="Palazzo", version="3", status="ready", parent_model_id=s["v2"].id)
    session.add(v3)
    await session.flush()
    assert (await BIMHubService(session).quantity_rule_offer(v3.id))["rule_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["first_upload", "still_importing", "rule_retired", "missing"])
async def test_nothing_is_offered_without_a_finished_version_and_an_active_rule(session, case):
    s = await seed(session, v2_status="processing" if case == "still_importing" else "ready")
    model_id = {"first_upload": s["v1"].id, "missing": uuid.uuid4()}.get(case, s["v2"].id)
    if case == "rule_retired":
        s["rule"].is_active = False
        await session.flush()
    offer = await BIMHubService(session).quantity_rule_offer(model_id)
    assert offer["rule_count"] == 0
    assert offer["boqs"] == []
