# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saved element groups as the BIM viewer lists them for one model.

A project-wide group (no model) must appear in every model's list, and a
dynamic group must carry its live members even when its cached snapshot is
empty, as the seeded demo groups are.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.modules.bim_hub.models import BIMElement, BIMElementGroup, BIMModel
from app.modules.bim_hub.schemas import BIMElementGroupCreate, BIMElementGroupUpdate
from app.modules.bim_hub.service import BIMHubService
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as value:
        yield value


async def seed(session):
    owner = User(email=f"groups-list-{uuid.uuid4().hex}@test.io", hashed_password="x", full_name="Groups")
    session.add(owner)
    await session.flush()
    project = Project(name="House", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    model = BIMModel(project_id=project.id, name="House IFC", version="1", status="ready")
    other_model = BIMModel(project_id=project.id, name="House RVT", version="1", status="ready")
    session.add_all([model, other_model])
    await session.flush()
    rows = [
        BIMElement(model_id=model.id, stable_id="w1", element_type="IfcWall", storey="Ground Floor"),
        BIMElement(model_id=model.id, stable_id="w2", element_type="IfcWall", storey="Roof"),
        BIMElement(model_id=model.id, stable_id="d1", element_type="IfcDoor", storey="Ground Floor"),
    ]
    session.add_all(rows)
    project_wide = BIMElementGroup(
        project_id=project.id,
        model_id=None,
        name="All Walls",
        is_dynamic=True,
        filter_criteria={"element_type": ["IfcWall", "Wall"]},
        element_ids=[],
        element_count=0,
    )
    other_model_group = BIMElementGroup(
        project_id=project.id,
        model_id=other_model.id,
        name="Elsewhere",
        is_dynamic=True,
        filter_criteria={"element_type": "IfcWall"},
    )
    session.add_all([project_wide, other_model_group])
    await session.flush()
    return {"project": project, "model": model, "rows": rows}


@pytest.mark.asyncio
async def test_a_project_wide_dynamic_group_lists_its_live_members_for_a_model(session):
    s = await seed(session)
    groups = await BIMHubService(session).list_element_groups(s["project"].id, model_id=s["model"].id)
    assert [g.name for g in groups] == ["All Walls"]
    walls = {s["rows"][0].id, s["rows"][1].id}
    assert set(groups[0].member_element_ids) == walls
    assert groups[0].element_count == 2


def test_a_group_filter_with_non_text_values_is_rejected():
    with pytest.raises(ValidationError):
        BIMElementGroupCreate(name="Bad", filter_criteria={"storey": [1, 2]})
    with pytest.raises(ValidationError):
        BIMElementGroupUpdate(filter_criteria={"name_contains": 5})


def test_a_group_colour_must_be_hex():
    with pytest.raises(ValidationError):
        BIMElementGroupCreate(name="Bad", color="red;")
    assert BIMElementGroupCreate(name="Ok", color="#2979ff").color == "#2979ff"
    ok = BIMElementGroupCreate(name="Ok", filter_criteria={"storey": "Roof", "element_type": ["IfcWall"]})
    assert ok.filter_criteria["storey"] == "Roof"
