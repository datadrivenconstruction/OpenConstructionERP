# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tenant catalogues: clone, validate, publish frozen versions, pin, and stay in their tenant."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance.catalogue_store import CatalogueStore, resolve_catalogue
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.models import GovernanceCatalogueVersion, ImmutableRecordError
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World, add_project, build_world

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        yield await build_world(factory)


async def _clone(w: World, tenant: str, code: str = "acme"):
    async with w.factory() as s:
        row = await CatalogueStore(s).create(
            tenant,
            code=code,
            name="Acme model",
            based_on_source="shipped",
            based_on_id="neutral",
            based_on_version=None,
            actor_id=w.manager,
        )
        await s.commit()
        return row


async def test_a_broken_draft_is_refused_by_the_same_validator(world: World) -> None:
    tenant = str(world.manager)
    row = await _clone(world, tenant)
    async with world.factory() as s:
        store = CatalogueStore(s)
        body = dict(row.draft_body)
        body["gates"] = body["gates"][1:]
        await store.update_draft(tenant, row.id, body=body, name=None)
        assert any(e.startswith("gate_missing") for e in store.validation_errors(await store.get(tenant, row.id)))
        with pytest.raises(GovernanceError) as exc:
            await store.publish(tenant, row.id, actor_id=world.manager)
    assert exc.value.code == "catalogue_invalid"


async def test_publish_freezes_and_a_project_on_v1_ignores_v2(world: World) -> None:
    tenant = str(world.manager)
    row = await _clone(world, tenant)
    async with world.factory() as s:
        v1 = await CatalogueStore(s).publish(tenant, row.id, actor_id=world.manager)
        await s.commit()
    assert v1.version == 1 and len(v1.content_hash) == 64

    async with world.factory() as s:
        pid = await add_project(s, world.manager, [])
        await GovernanceService(s).set_model(
            pid,
            source="tenant",
            catalogue_id=str(row.id),
            version=None,
            four_eyes=True,
            actor_id=world.manager,
            tenant_id=tenant,
        )
        await s.commit()

    async with world.factory() as s:
        store = CatalogueStore(s)
        draft = await store.get(tenant, row.id)
        body = dict(draft.draft_body)
        body["phases"] = [dict(p) for p in body["phases"]]
        body["phases"][0]["labels"] = {"en": "Renamed strategy"}
        await store.update_draft(tenant, row.id, body=body, name=None)
        v2 = await store.publish(tenant, row.id, actor_id=world.manager)
        diff = await store.diff(tenant, row.id, 1, 2)
        await s.commit()
    assert v2.version == 2
    assert diff["groups"]["phases"]["changed"] == [body["phases"][0]["code"]]

    async with world.factory() as s:
        svc = GovernanceService(s)
        model = await svc.require_model(pid)
        cat = await svc.catalogue_for(model)
        latest = await resolve_catalogue(s, "tenant", str(row.id), 2, tenant_id=tenant)
    assert model.catalogue_version == 1
    # The rename is real in v2, so its absence from the pinned v1 says something.
    assert (latest.phases[0].labels or {}).get("en") == "Renamed strategy"
    assert (cat.phases[0].labels or {}).get("en") != "Renamed strategy"

    async with world.factory() as s:
        frozen = await s.get(GovernanceCatalogueVersion, v1.id)
        frozen.body = {}
        with pytest.raises(ImmutableRecordError):
            await s.flush()


async def test_another_tenant_cannot_see_read_or_pin_it(world: World) -> None:
    tenant = str(world.manager)
    other = str(world.outsider)
    row = await _clone(world, tenant)
    async with world.factory() as s:
        await CatalogueStore(s).publish(tenant, row.id, actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        store = CatalogueStore(s)
        listed = await store.list_available(other)
        # Not "all shipped": an installation with an active pack lists its catalogues too.
        assert listed and all(i["source"] != "tenant" for i in listed)
        with pytest.raises(GovernanceError) as read:
            await store.get(other, row.id)
        pid = await add_project(s, world.outsider, [])
        with pytest.raises(GovernanceError) as pin:
            await GovernanceService(s).set_model(
                pid,
                source="tenant",
                catalogue_id=str(row.id),
                version=1,
                four_eyes=True,
                actor_id=world.outsider,
                tenant_id=other,
            )
    assert read.value.status_code == 404
    assert pin.value.status_code == 404


async def test_a_retired_catalogue_cannot_be_pinned(world: World) -> None:
    tenant = str(world.manager)
    row = await _clone(world, tenant)
    async with world.factory() as s:
        store = CatalogueStore(s)
        await store.publish(tenant, row.id, actor_id=world.manager)
        await store.retire(tenant, row.id)
        pid = await add_project(s, world.manager, [])
        with pytest.raises(GovernanceError) as exc:
            await GovernanceService(s).set_model(
                pid,
                source="tenant",
                catalogue_id=str(row.id),
                version=1,
                four_eyes=True,
                actor_id=world.manager,
                tenant_id=tenant,
            )
    assert exc.value.code == "catalogue_retired"
