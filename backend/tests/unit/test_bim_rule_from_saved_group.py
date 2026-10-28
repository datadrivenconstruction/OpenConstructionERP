# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A saved element group or Smart View can be a BOQ position's quantity source.

It goes through a quantity rule that names the group (``metadata.element_group_id``)
and targets the position, so preview, apply, the links and the change review
on a new model version are the ones every rule already has. These pin the
membership the rule engine reads: a filter group re-evaluated on each model,
a hand-picked group carried to a new version by ``stable_id``, and nothing at
all for a group that is gone or belongs to another project.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.bim_hub.models import BIMElement, BIMElementGroup, BIMModel, BIMQuantityMap, BOQElementLink
from app.modules.bim_hub.schemas import (
    BIMQuantityMapCreate,
    BIMQuantityMapUpdate,
    QuantityMapApplyRequest,
    QuantityRuleDraft,
    QuantityRulePreviewRequest,
)
from app.modules.bim_hub.service import BIMHubService, rule_element_group_id
from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as value:
        yield value


async def seed(session):
    owner = User(email=f"group-rule-{uuid.uuid4().hex}@test.io", hashed_password="x", full_name="Group")
    session.add(owner)
    await session.flush()
    project = Project(name="Restauro", owner_id=owner.id, currency="EUR")
    other = Project(name="Elsewhere", owner_id=owner.id, currency="EUR")
    session.add_all([project, other])
    await session.flush()
    v1 = BIMModel(project_id=project.id, name="Palazzo", version="1", status="ready")
    session.add(v1)
    await session.flush()
    v2 = BIMModel(project_id=project.id, name="Palazzo", version="2", status="ready", parent_model_id=v1.id)
    boq = BOQ(project_id=project.id, name="Bill", is_locked=False)
    session.add_all([v2, boq])
    await session.flush()

    def wall(model, stable, phase, area):
        return BIMElement(
            model_id=model.id,
            stable_id=stable,
            element_type="Walls",
            properties={"phase demolished": phase} if phase else {},
            quantities={"area": area},
        )

    rows = [
        wall(v1, "w-1", None, 10),
        wall(v1, "w-2", "Demolizione", 4),
        wall(v2, "w-1", None, 12),
        wall(v2, "w-2", "Demolizione", 4),
        wall(v2, "w-3", None, 7),
    ]
    session.add_all(rows)
    position = Position(boq_id=boq.id, ordinal="01.001", description="Muratura conservata", unit="m2", quantity="0")
    session.add(position)
    await session.flush()
    smart_view = BIMElementGroup(
        project_id=project.id,
        model_id=v1.id,
        name="Kept walls",
        is_dynamic=True,
        filter_criteria={
            "rule_tree": {
                "op": "AND",
                "rules": [{"field": "properties.phase demolished", "op": "is_empty"}],
            }
        },
    )
    picked = BIMElementGroup(
        project_id=project.id,
        model_id=v1.id,
        name="Picked",
        is_dynamic=False,
        filter_criteria={},
        element_ids=[str(rows[1].id)],
        element_count=1,
    )
    foreign = BIMElementGroup(project_id=other.id, name="Foreign", is_dynamic=True, filter_criteria={})
    session.add_all([smart_view, picked, foreign])
    await session.flush()
    return {
        "project": project,
        "v1": v1,
        "v2": v2,
        "boq": boq,
        "position": position,
        "smart_view": smart_view,
        "picked": picked,
        "foreign": foreign,
        "rows": rows,
    }


def draft(group_id, **extra):
    return QuantityRuleDraft(quantity_source="area", element_group_id=group_id, **extra)


async def preview(service, model, rule):
    return await service.preview_quantity_rule(QuantityRulePreviewRequest(model_id=model.id, rule=rule))


def test_the_group_id_is_read_from_a_draft_or_a_saved_rule():
    gid = uuid.uuid4()
    assert rule_element_group_id(draft(gid)) == gid
    assert rule_element_group_id(BIMQuantityMap(metadata_={"element_group_id": str(gid)})) == gid
    assert rule_element_group_id(BIMQuantityMap(metadata_={"element_group_id": "not-a-uuid"})) is None
    assert rule_element_group_id(BIMQuantityMap(metadata_={})) is None


@pytest.mark.asyncio
async def test_a_smart_view_selects_its_elements_on_every_version(session):
    s = await seed(session)
    service = BIMHubService(session)
    on_v1 = await preview(service, s["v1"], draft(s["smart_view"].id))
    assert sorted(m.stable_id for m in on_v1.matches) == ["w-1"]
    assert on_v1.total_adjusted == 10
    on_v2 = await preview(service, s["v2"], draft(s["smart_view"].id))
    assert sorted(m.stable_id for m in on_v2.matches) == ["w-1", "w-3"]
    assert on_v2.total_adjusted == 19


@pytest.mark.asyncio
async def test_a_saved_smart_view_group_no_longer_resolves_to_every_element(session):
    s = await seed(session)
    members = await BIMHubService(session).resolve_element_group_members(s["smart_view"].id)
    assert members == [s["rows"][0].id]


@pytest.mark.asyncio
async def test_a_hand_picked_group_follows_its_elements_to_a_new_version(session):
    s = await seed(session)
    service = BIMHubService(session)
    on_v2 = await preview(service, s["v2"], draft(s["picked"].id))
    assert [m.stable_id for m in on_v2.matches] == ["w-2"]
    assert on_v2.matches[0].element_id == str(s["rows"][3].id)


@pytest.mark.asyncio
async def test_the_rule_filters_narrow_the_group(session):
    s = await seed(session)
    narrowed = await preview(
        BIMHubService(session),
        s["v2"],
        draft(s["smart_view"].id, property_filter={"phase demolished": {"$op": "is_not_empty"}}),
    )
    assert narrowed.match_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["foreign", "missing"])
async def test_a_group_outside_the_project_selects_nothing(session, which):
    s = await seed(session)
    gid = s["foreign"].id if which == "foreign" else uuid.uuid4()
    result = await preview(BIMHubService(session), s["v2"], draft(gid))
    assert result.match_count == 0 and result.skip_count == 0


@pytest.mark.asyncio
async def test_saving_a_rule_with_a_foreign_group_is_refused(session):
    s = await seed(session)
    service = BIMHubService(session)
    payload = {
        "project_id": s["project"].id,
        "name": "Foreign",
        "quantity_source": "area",
        "metadata": {"element_group_id": str(s["foreign"].id)},
    }
    with pytest.raises(HTTPException) as exc:
        await service.create_quantity_map(BIMQuantityMapCreate(**payload))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "bim_rules.group_not_found"
    rule = await service.create_quantity_map(
        BIMQuantityMapCreate(**{**payload, "metadata": {"element_group_id": str(s["smart_view"].id)}})
    )
    with pytest.raises(HTTPException):
        await service.update_quantity_map(
            rule.id, BIMQuantityMapUpdate(metadata={"element_group_id": str(uuid.uuid4())})
        )
    cleared = await service.update_quantity_map(rule.id, BIMQuantityMapUpdate(metadata={"element_group_id": None}))
    assert rule_element_group_id(cleared) is None


@pytest.mark.asyncio
async def test_applying_links_the_group_to_the_position(session):
    s = await seed(session)
    service = BIMHubService(session)
    await service.create_quantity_map(
        BIMQuantityMapCreate(
            project_id=s["project"].id,
            name="Kept walls",
            quantity_source="area",
            unit="m2",
            boq_target={"position_id": str(s["position"].id)},
            metadata={"element_group_id": str(s["smart_view"].id)},
        )
    )
    request = {"model_id": str(s["v2"].id), "target_boq_id": str(s["boq"].id)}
    dry = await service.apply_quantity_maps(QuantityMapApplyRequest.model_validate(request))
    assert dry.links_to_create == 2
    applied = await service.apply_quantity_maps(
        QuantityMapApplyRequest.model_validate(
            {**request, "dry_run": False, "preview_fingerprint": dry.preview_fingerprint}
        )
    )
    assert applied.links_created == 2
    linked = (
        await session.execute(
            select(BIMElement.stable_id)
            .join(BOQElementLink, BOQElementLink.bim_element_id == BIMElement.id)
            .where(BOQElementLink.boq_position_id == s["position"].id)
        )
    ).scalars()
    assert sorted(linked.all()) == ["w-1", "w-3"]


@pytest.mark.asyncio
async def test_an_edited_group_refuses_the_old_preview(session):
    s = await seed(session)
    service = BIMHubService(session)
    await service.create_quantity_map(
        BIMQuantityMapCreate(
            project_id=s["project"].id,
            name="Kept walls",
            quantity_source="area",
            unit="m2",
            boq_target={"position_id": str(s["position"].id)},
            metadata={"element_group_id": str(s["smart_view"].id)},
        )
    )
    request = {"model_id": str(s["v2"].id), "target_boq_id": str(s["boq"].id)}
    dry = await service.apply_quantity_maps(QuantityMapApplyRequest.model_validate(request))
    s["smart_view"].filter_criteria = {}
    await session.flush()
    with pytest.raises(HTTPException) as exc:
        await service.apply_quantity_maps(
            QuantityMapApplyRequest.model_validate(
                {**request, "dry_run": False, "preview_fingerprint": dry.preview_fingerprint}
            )
        )
    assert exc.value.status_code == 409
