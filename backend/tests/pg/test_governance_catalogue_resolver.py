# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The resolver keeps a tenant catalogue inside its tenant; a stored pin keeps resolving."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance import catalogue as cat
from app.modules.project_governance import public
from app.modules.project_governance.catalogue_store import CatalogueStore, resolve_catalogue
from app.modules.project_governance.errors import GovernanceError
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


async def _published(w: World, tenant: str) -> str:
    async with w.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            tenant,
            code="acme",
            name="Acme model",
            based_on_source="shipped",
            based_on_id="neutral",
            based_on_version=None,
            actor_id=w.manager,
        )
        await store.publish(tenant, row.id, actor_id=w.manager)
        await s.commit()
        return str(row.id)


async def test_a_request_id_resolves_only_for_its_own_tenant(world: World) -> None:
    owner, stranger = str(world.manager), str(world.outsider)
    cid = await _published(world, owner)
    async with world.factory() as s:
        own = await resolve_catalogue(s, "tenant", cid, 1, tenant_id=owner)
        assert own.version == 1 and own.host_of("design") is not None
        with pytest.raises(GovernanceError) as foreign:
            await resolve_catalogue(s, "tenant", cid, 1, tenant_id=stranger)
        with pytest.raises(GovernanceError) as latest:
            await resolve_catalogue(s, "tenant", cid, None, tenant_id=stranger)
        with pytest.raises(GovernanceError) as anonymous:
            await resolve_catalogue(s, "tenant", cid, 1)
        # A shipped catalogue is public and needs no tenant.
        assert (await resolve_catalogue(s, "shipped", "neutral", None)).id == "neutral"
    assert [e.value.status_code for e in (foreign, latest, anonymous)] == [404, 404, 404]
    assert {e.value.code for e in (foreign, latest, anonymous)} == {"unknown_catalogue"}


async def test_a_retired_catalogue_is_refused_by_id_but_a_pin_on_it_keeps_resolving(world: World) -> None:
    owner = str(world.manager)
    cid = await _published(world, owner)
    async with world.factory() as s:
        pid = await add_project(s, world.manager, [world.outsider])
        await GovernanceService(s).set_model(
            pid,
            source="tenant",
            catalogue_id=cid,
            version=1,
            four_eyes=True,
            actor_id=world.manager,
            tenant_id=owner,
        )
        await CatalogueStore(s).retire(owner, uuid.UUID(cid))
        await s.commit()
    async with world.factory() as s:
        with pytest.raises(GovernanceError) as retired:
            await resolve_catalogue(s, "tenant", cid, 1, tenant_id=owner)
        # The project pinned it before; the pin, not the reader, names the version.
        service = GovernanceService(s)
        pinned = await service.catalogue_for(await service.require_model(pid))
        assert pinned.version == 1
        host = await public.host_for(s, pid, "design")
        assert host == public.Host(area_code="scope", doc_type="scope_statement")
        assert await public.phases_enabling(s, pid, "construction_start") == ("construction",)
    assert retired.value.code == "catalogue_retired" and retired.value.status_code == 409


async def test_a_project_without_a_model_hosts_nothing(world: World) -> None:
    async with world.factory() as s:
        pid = await add_project(s, world.manager, [])
        assert await public.project_catalogue(s, pid) is None
        assert await public.host_for(s, pid, "design") is None
        assert await public.phases_enabling(s, pid, "handover") == ()


async def test_the_port_lists_gates_areas_and_documents_of_a_project(world: World) -> None:
    async with world.factory() as s:
        empty = await add_project(s, world.manager, [])
        assert await public.project_gates(s, empty) == ()
        assert await public.project_areas(s, empty) == ()
        assert await public.project_documents(s, empty) == ()

        gates = await public.project_gates(s, world.project_id)
        areas = await public.project_areas(s, world.project_id)
        documents = await public.project_documents(s, world.project_id)
    assert [g.order for g in gates] == list(range(1, 11))
    assert (gates[0].code, gates[0].from_phase, gates[0].to_phase, gates[0].status) == (
        "strategy_to_brief",
        "strategy",
        "brief",
        "not_started",
    )
    assert [a.code for a in areas][:2] == ["integration", "scope"] and len(areas) == 10
    assert {a.status for a in areas} == {"applicable"}
    by_code = {d.code: d for d in documents}
    assert by_code["business_case"].area_code == "cost_finance"
    assert by_code["business_case"].required_at_gates == ("strategy_to_brief",)
    assert by_code["business_case"].area_id == next(a.id for a in areas if a.code == "cost_finance")
    assert [d.order for d in documents] == list(range(1, len(documents) + 1))
    # The host of a subject is one of the listed documents, in one of the listed areas.
    host = public.host_in(cat.get_catalogue("neutral"), "design")
    assert by_code[host.doc_type].area_code == host.area_code


async def test_the_port_reads_decisions_conditions_and_change_requests(world: World) -> None:
    from datetime import date, timedelta

    from app.modules.project_governance import evaluator as ev
    from tests.pg.governance_fixtures import decide, prepare_gate

    other = await build_world(world.factory)
    async with world.factory() as s:
        assert await public.project_gate_decisions(s, world.project_id) == ()
        assert await public.project_conditions(s, world.project_id) == ()
        assert await public.project_change_requests(s, world.project_id) == ()

    g = await prepare_gate(world, "strategy_to_brief")
    await decide(
        world,
        g.id,
        "go_with_conditions",
        conditions=[
            ev.ProposedCondition(
                area_code="scope",
                document_type=None,
                text="Late already",
                owner_user_id=str(world.owner),
                due_date=date.today() - timedelta(days=3),
            ),
            ev.ProposedCondition(
                area_code=None,
                document_type=None,
                text="Still time",
                owner_user_id=str(world.owner),
                due_date=date.today() + timedelta(days=30),
            ),
        ],
    )
    async with world.factory() as s:
        decisions = await public.project_gate_decisions(s, world.project_id, g.id)
        conditions = await public.project_conditions(s, world.project_id, g.id)
        gates = {v.code: v for v in await public.project_gates(s, world.project_id)}
        documents = {d.code: d for d in await public.project_documents(s, world.project_id)}
        # Nothing of this project is listed under the other one, and a foreign gate id lists nothing here.
        assert await public.project_gate_decisions(s, other.project_id, g.id) == ()
        assert await public.project_conditions(s, other.project_id) == ()
        assert await public.project_change_requests(s, world.project_id, open_only=True) == ()
    assert [(d.outcome, d.gate_id, d.decided_by) for d in decisions] == [("go_with_conditions", g.id, world.decider)]
    assert [(c.text, c.status, c.area_code) for c in conditions] == [
        ("Late already", "overdue", "scope"),
        ("Still time", "open", None),
    ]
    assert {c.decision_id for c in conditions} == {decisions[0].id}
    assert gates["strategy_to_brief"].status == "decided" and gates["strategy_to_brief"].target_date is None
    approved = documents["business_case"]
    assert approved.approved_gate_id == g.id and approved.container_id == world.containers["business_case"]
    assert approved.bound_revision_id is not None


async def test_the_port_answers_who_may_be_named_on_a_project(world: World) -> None:
    async with world.factory() as s:
        answers = {
            "owner": await public.user_can_access_project(s, world.project_id, world.manager),
            "member": await public.user_can_access_project(s, world.project_id, world.editor),
            "stranger": await public.user_can_access_project(s, world.project_id, world.outsider),
            "nobody": await public.user_can_access_project(s, world.project_id, uuid.uuid4()),
            "no project": await public.user_can_access_project(s, uuid.uuid4(), world.manager),
        }
    assert answers == {"owner": True, "member": True, "stranger": False, "nobody": False, "no project": False}
