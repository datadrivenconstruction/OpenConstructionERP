# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo seed on PostgreSQL, on catalogues and governance models it must not assume.

A pack may pin delivery forms without the form the seed used to compare, and a
project may have no frame document for the decision. The seed tells its story
on what the project has, and reports what it could not do.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delivery_model import seed
from app.modules.delivery_model.catalogue import DELIVERY_FORMS_KIND
from app.modules.delivery_model.public import project_packages
from app.modules.delivery_model.service import DeliveryModelService
from app.modules.project_governance.catalogue_store import CatalogueStore
from app.modules.projects.models import Project
from tests._pg import isolated_engine
from tests.pg.delivery_fixtures import build_world, call, catalogue_body_with_forms, view
from tests.pg.governance_fixtures import add_project

pytestmark = pytest.mark.asyncio

PACK_FORMS = ("design_bid_build_split", "design_bid_build_single", "design_build", "partnering_two_stage", "integrator")


@pytest_asyncio.fixture
async def factory():
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _mark_demo(w) -> None:
    async with w.factory() as s:
        await s.execute(update(Project).where(Project.id == w.project_id).values(metadata_={"demo_id": "office-test"}))
        await s.commit()


async def _pin_forms(w, forms: tuple[str, ...]) -> str:
    """Re-pin the (still empty) delivery model on a tenant catalogue that has only ``forms``."""
    tenant = str(w.manager)
    async with w.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            tenant,
            code=f"forms_{uuid.uuid4().hex[:6]}",
            name="Pack-like forms",
            based_on_source=None,
            based_on_id=None,
            based_on_version=None,
            actor_id=w.manager,
            kind=DELIVERY_FORMS_KIND,
        )
        await store.update_draft(tenant, row.id, body=catalogue_body_with_forms(forms), name=None)
        await store.publish(tenant, row.id, actor_id=w.manager)
        await s.commit()
        cid = str(row.id)
    await call(
        w,
        "change_catalogue",
        actor_id=w.manager,
        tenant_id=tenant,
        catalogue_source="tenant",
        catalogue_id=cid,
        catalogue_version=None,
        form_mapping={},
        category_mapping={},
    )
    return cid


async def _seed(w) -> dict:
    async with w.factory() as s:
        out = await seed.seed_delivery_model_demo(s, [w.project_id])
        await s.commit()
        return out


async def test_the_seed_runs_on_a_catalogue_without_the_form_it_prefers(factory) -> None:
    w = await build_world(factory)
    await _mark_demo(w)
    cid = await _pin_forms(w, PACK_FORMS)
    out = await _seed(w)
    assert (out["ok"], out["failed"], out["no_decision"]) == (True, [], [])
    assert (out["projects"], out["decisions"], out["ofis"]) == (1, 1, 2)
    comparison = await call(w, "comparison")
    assert [o["form_code"] for o in comparison["options"]] == [
        "design_bid_build_single",
        "design_build",
        "design_bid_build_split",
    ]
    model = await view(w)
    leading = max(comparison["options"], key=lambda o: float(o["weighted_total"]))["form_code"]
    assert (model["status"], model["catalogue_id"], model["selected_form_code"]) == ("proposed", cid, leading)
    assert out["packages"] > 0
    async with w.factory() as s:
        packages = await project_packages(s, w.project_id)
    assert len(packages) == out["packages"] and all(p.code and p.title for p in packages)
    # A seeded item without a route would put a finding on the screen that nobody scripted, and an error
    # under a governance model that releases procurement from its first phase.
    items = await call(w, "ofi_views")
    assert {i["procurement_route"] for i in items} == {"framework", "existing_stock"}
    report = await call(w, "consistency")
    assert [i for i in report["items"] if i["code"] == "ofi_without_route"] == []
    # Run again: nothing is added.
    again = await _seed(w)
    assert (again["projects"], again["ok"]) == (0, True)


async def test_before_the_construction_gate_every_seeded_date_lies_after_the_start(factory) -> None:
    w = await build_world(factory)  # the gate into the phase that starts construction is not decided
    await _mark_demo(w)
    await _seed(w)
    today = datetime.now(UTC).date()
    start = today.toordinal() + seed.START
    items = {i["code"]: i for i in await call(w, "ofi_views")}
    assert date.fromisoformat(items["OFI-01"]["expected_delivery_date"]).toordinal() > start
    assert date.fromisoformat(items["OFI-01"]["need_by_date"]).toordinal() > start
    assert date.fromisoformat(items["OFI-02"]["need_by_date"]).toordinal() > start
    assert {i["status"] for i in items.values()} == {"route_set"}
    assert (await view(w))["status"] == "proposed"


async def test_a_project_without_a_phase_model_keeps_the_running_story_and_proposes_for_hand_approval(
    factory, caplog
) -> None:
    w = await build_world(factory, governance=False)
    await _mark_demo(w)
    with caplog.at_level(logging.INFO, logger="app.modules.delivery_model.seed"):
        out = await _seed(w)
    # A project without gates approves by hand, so it needs no frame document and the decision is proposed.
    assert out["ok"] is True and out["failed"] == [] and out["no_decision"] == []
    assert [
        r for r in caplog.records if r.name == "app.modules.delivery_model.seed" and r.levelno >= logging.WARNING
    ] == []
    assert (out["projects"], out["decisions"]) == (1, 1)
    today = datetime.now(UTC).date()
    items = {i["code"]: i for i in await call(w, "ofi_views")}
    assert date.fromisoformat(items["OFI-01"]["expected_delivery_date"]).toordinal() == today.toordinal() + 100
    assert (await view(w))["status"] == "proposed"


async def test_a_catalogue_with_one_form_cannot_be_published_so_no_project_is_pinned_to_one(factory) -> None:
    from app.modules.project_governance.errors import GovernanceError

    w = await build_world(factory)
    await _mark_demo(w)
    with pytest.raises(GovernanceError) as refused:
        await _pin_forms(w, ("design_build",))
    assert refused.value.code == "catalogue_invalid"


async def test_a_project_that_is_not_a_demo_project_is_left_alone(factory) -> None:
    w = await build_world(factory)
    async with w.factory() as s:
        other = await add_project(s, w.manager, [])
        await s.commit()
    out = await _seed(w)
    async with w.factory() as s:
        out2 = await seed.seed_delivery_model_demo(s, [other])
        assert await DeliveryModelService(s).get_model(other) is None
    assert (out["projects"], out2["projects"]) == (0, 0)
