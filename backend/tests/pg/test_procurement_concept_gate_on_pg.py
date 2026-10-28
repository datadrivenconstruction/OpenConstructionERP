# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The procurement concept against the real governance module, and the demo seed, on PostgreSQL.

The governance world pins a shipped phase model with its approval routes, and the
module finds its area, its frame document and its release gate through the
model's tags (module 1's port). Where a test decides a gate for real it names the
first gate and a document that gate requires on the concept, which is what a
manager may do in any project, so the whole chain of earlier gates need not run.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.procurement_concept.events as pc_events
import app.modules.project_governance.events as gov_events
from app.modules.delivery_model.models import DeliveryModel
from app.modules.procurement_concept import plan_source as plan
from app.modules.procurement_concept.catalogue import register_kind
from app.modules.procurement_concept.evidence import PROVIDER_NAME, concept_ready, register_gate_evidence
from app.modules.procurement_concept.models import (
    AwardPackage,
    BidderCandidate,
    FrameworkAgreement,
    MarketSounding,
    ProcurementConcept,
)
from app.modules.procurement_concept.seed import seed_procurement_concept_demo
from app.modules.procurement_concept.service import ProcurementConceptService
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.evidence import GateAttempt, unregister_evidence_provider
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World, areas, build_world, decide, documents, gate, prepare_gate
from tests.pg.procurement_concept_fixtures import (
    AREA,
    DOC_TYPE,
    GATE_CODES,
    MODEL,
    MODEL_ID,
    OTHER_AREA,
    RELEASE_GATE,
    ensure_plan_tables,
)

pytestmark = pytest.mark.asyncio

G1 = GATE_CODES[0]
FRAME_DOC = next(d.code for d in MODEL.document_types if G1 in d.required_at_gates)


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    register_kind()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        monkeypatch.setattr(pc_events, "async_session_factory", factory)
        await ensure_plan_tables(factory)
        yield await build_world(factory)
    unregister_evidence_provider(PROVIDER_NAME)


async def _concept(w: World, **extra) -> None:
    async with w.factory() as s:
        await ProcurementConceptService(s).set_concept(
            w.project_id,
            {"catalogue_source": "shipped", "catalogue_id": "neutral", **extra},
            actor_id=w.manager,
            can_manage=True,
            tenant_id=str(w.manager),
        )
        await s.commit()


async def _submit(w: World) -> None:
    async with w.factory() as s:
        await ProcurementConceptService(s).transition(w.project_id, "in_review", actor_id=w.owner, can_manage=True)
        await s.commit()


async def _stored(w: World) -> ProcurementConcept:
    async with w.factory() as s:
        return (
            await s.execute(sa.select(ProcurementConcept).where(ProcurementConcept.project_id == w.project_id))
        ).scalar_one()


async def _evidence(w: World, gate_code: str, area_code: str) -> list:
    g = await gate(w, gate_code)
    area = (await areas(w))[area_code]
    async with w.factory() as s:
        return await concept_ready(s, w.project_id, GateAttempt(g.id, g.code, g.attempt_no or 1), area)


async def test_evidence_is_met_not_met_or_unknown_and_never_silently_empty(world: World) -> None:
    from app.modules.project_governance.models import GovernanceDocument

    assert await _evidence(world, RELEASE_GATE, AREA) == []  # no concept: the module has nothing to say
    await _concept(world)
    # The model's tags name the release gate and the area; a draft concept is not ready.
    (item,) = await _evidence(world, RELEASE_GATE, AREA)
    assert item.state == "not_met"
    # One item per gate, on one area; another gate is not this module's business.
    assert await _evidence(world, RELEASE_GATE, OTHER_AREA) == []
    assert await _evidence(world, G1, AREA) == []
    # A manager names another gate while the concept is a draft: the item moves with it.
    await _concept(world, release_gate_code=G1)
    assert await _evidence(world, RELEASE_GATE, AREA) == []
    (item,) = await _evidence(world, G1, AREA)
    assert item.state == "not_met"
    await _submit(world)
    (item,) = await _evidence(world, G1, AREA)
    assert item.state == "met"
    # The project has no row for the host document (pinned before the model hosted procurement): nothing
    # could ever approve the concept, so the answer is unknown and never "met".
    async with world.factory() as s:
        await s.execute(
            sa.delete(GovernanceDocument).where(
                GovernanceDocument.project_id == world.project_id, GovernanceDocument.doc_type == DOC_TYPE
            )
        )
        await s.commit()
    (item,) = await _evidence(world, G1, AREA)
    assert (item.state, item.detail) == ("unknown", "frame_document_unresolved")
    # A code of its own and a sentence of its own: the decider acknowledges the item by name.
    assert item.code == "procurement_concept_ready:frame_document_unresolved"
    assert item.label_key == "procurement_concept.evidence.unknown.frame_document_unresolved"
    # The named gate is not a gate of the project any more (the project moved to another model): unknown,
    # with the reason, at whichever gate asks.
    async with world.factory() as s:
        concept = await ProcurementConceptService(s).get_concept(world.project_id)
        concept.release_gate_code = "gate_of_a_model_the_project_left"
        await s.commit()
    for code in (G1, RELEASE_GATE):
        (item,) = await _evidence(world, code, AREA)
        assert (item.state, item.detail) == ("unknown", "release_gate_unresolved")
        assert item.label_key == "procurement_concept.evidence.unknown.release_gate_unresolved"


async def _prepare_and_decide(w: World) -> None:
    g = await prepare_gate(w, G1)
    await decide(w, g.id)


async def test_a_draft_concept_blocks_the_release_gate(world: World) -> None:
    from app.modules.project_governance.evidence import evidence_link_href

    register_gate_evidence()
    # The gate screen can open the item: the link kind is registered with the module's own page.
    assert (
        evidence_link_href("procurement_concept", str(world.project_id), world.project_id)
        == f"/projects/{world.project_id}/procurement-concept"
    )
    await _concept(world, release_gate_code=G1, governance_document_id=(await documents(world))[FRAME_DOC].id)
    with pytest.raises(GovernanceError):
        await _prepare_and_decide(world)
    assert (await documents(world))[FRAME_DOC].status != "binding"
    assert (await _stored(world)).state == "draft"


async def test_the_gate_decision_approves_the_submitted_concept_through_the_event_bus(world: World) -> None:
    register_gate_evidence()
    pc_events.register_procurement_concept_subscribers()
    doc = (await documents(world))[FRAME_DOC]
    await _concept(world, release_gate_code=G1, governance_document_id=doc.id)
    await _submit(world)
    g = await prepare_gate(world, G1)
    await decide(world, g.id)
    assert (await documents(world))[FRAME_DOC].status == "binding"
    for _ in range(100):
        if (await _stored(world)).state == "approved":
            break
        await asyncio.sleep(0.1)
    concept = await _stored(world)
    assert concept.state == "approved"
    assert (concept.submitted_by, concept.approved_by) == (world.owner, world.decider)
    async with world.factory() as s:
        svc = ProcurementConceptService(s)
        assert await svc.effective_state(await svc.get_concept(world.project_id)) == "binding"
        caps = await svc.capabilities(world.project_id, world.manager, True)
    assert caps["edit_plan"] == {"allowed": False, "reason": "binding_requires_change_request", "applies": True}


# ── Demo seed (finding 17) ──────────────────────────────────────────────


async def _demo_project(w: World, *, currency: str, country: str, public: bool) -> uuid.UUID:
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with w.factory() as s:
        s.add(
            Project(
                id=pid,
                name=f"Demo {pid.hex[:6]}",
                currency=currency,
                country_code=country,
                status="active",
                owner_id=w.manager,
                metadata_={"demo_id": f"demo-{pid.hex[:6]}"},
            )
        )
        await s.flush()
        for i, (code, kind) in enumerate(
            (("GC", "construction"), ("DES", "design"), ("STL", "supply"), ("FAC", "supply_and_install"))
        ):
            await s.execute(
                sa.insert(plan.PACKAGE_TABLE).values(
                    id=uuid.uuid4(),
                    project_id=pid,
                    code=code,
                    title=f"{code} package",
                    kind=kind,
                    scope="",
                    wbs_ref="",
                    boq_ref="",
                    status="planned",
                    sort_order=i,
                )
            )
        await s.execute(
            sa.insert(DeliveryModel.__table__).values(
                id=uuid.uuid4(),
                project_id=pid,
                catalogue_id="neutral",
                catalogue_version=1,
                selected_form_code="design_bid_build_split",
                status="approved",
                owner_capability={"public_client": public},
            )
        )
        # The governance demo seed runs first and pins the phase model; this module's seed only reads it.
        await GovernanceService(s).set_model(
            pid,
            source="shipped",
            catalogue_id=MODEL_ID,
            version=None,
            four_eyes=True,
            actor_id=w.manager,
            tenant_id=str(w.manager),
        )
        await s.commit()
    return pid


async def _subcontractors(w: World) -> None:
    from app.modules.subcontractors.models import Subcontractor

    async with w.factory() as s:
        # A company a user registered, which would sort first under any ordering by name or tax id.
        s.add(Subcontractor(legal_name="AAA real customer company", tax_id="0000", website="https://real.example.org"))
        for n in range(1, 7):
            s.add(
                Subcontractor(
                    legal_name=f"Demo contractor {n:02d}",
                    tax_id=f"DEMO-{n:02d}",
                    website=f"https://contractor-{n:02d}.example.com",
                )
            )
        await s.commit()


async def _cleared_condition(w: World, project_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    from app.modules.project_governance.models import GovernanceCondition, GovernanceDecision, GovernanceGate

    async with w.factory() as s:
        g = (
            await s.execute(
                sa.select(GovernanceGate).where(GovernanceGate.project_id == project_id, GovernanceGate.code == G1)
            )
        ).scalar_one()
        d = GovernanceDecision(
            project_id=project_id,
            gate_id=g.id,
            gate_code=G1,
            attempt_no=1,
            outcome="go_with_conditions",
            decided_by=w.decider,
            decided_at=datetime.now(UTC),
        )
        s.add(d)
        await s.flush()
        c = GovernanceCondition(
            project_id=project_id,
            decision_id=d.id,
            gate_id=g.id,
            gate_code=G1,
            text="Fabrication slot reserved",
            status="cleared",
            cleared_at=datetime.now(UTC),
        )
        s.add(c)
        await s.commit()
        return c.id, G1


async def _seed(w: World, pids: list[uuid.UUID]) -> dict:
    async with w.factory() as s:
        out = await seed_procurement_concept_demo(s, pids)
        await s.commit()
        return out


async def test_the_seed_leaves_a_concept_that_can_go_to_the_gate(world: World) -> None:
    await _subcontractors(world)
    pid = await _demo_project(world, currency="EUR", country="DE", public=True)
    condition_id, gate_code = await _cleared_condition(world, pid)
    assert (await _seed(world, [pid]))["projects"] == 1
    assert (await _seed(world, [pid]))["projects"] == 0  # a re-run adds nothing
    async with world.factory() as s:
        svc = ProcurementConceptService(s)
        concept = await svc.get_concept(pid)
        cat = await svc.catalogue_of(concept)
        found = await svc.findings(pid)
        rows = (await s.execute(sa.select(AwardPackage).where(AwardPackage.project_id == pid))).scalars().all()
        cands = (await s.execute(sa.select(BidderCandidate).where(BidderCandidate.project_id == pid))).scalars().all()
        from app.modules.subcontractors.models import Subcontractor

        names = sorted(
            [(await s.get(Subcontractor, c.subcontractor_id)).legal_name for c in cands if c.subcontractor_id]
        )
        advance = next(r for r in rows if r.is_advance)
        release = await svc.advance_release_status(pid, advance, await svc.release_gate(pid, concept))
        soundings = (await s.execute(sa.select(MarketSounding).where(MarketSounding.project_id == pid))).scalars().all()
    assert "DE" in cat.jurisdiction_countries
    assert (concept.public_client, concept.state, concept.release_gate_code) == (True, "draft", gate_code)
    assert concept.client_type in cat.jurisdiction(concept.jurisdiction).client_types
    assert [f for f in found if f["blocks_approval"]] == []
    assert len(rows) == 4
    assert {r.currency for r in rows} == {"EUR"}
    # The design appointment is a fact of the past; every other package is a plan that waits for the gate.
    assert sorted(r.state for r in rows) == ["awarded", "procedure_set", "procedure_set", "procedure_set"]
    held = sorted((datetime.now(UTC).date() - date.fromisoformat(m.held_on)).days for m in soundings)
    # Held one to four months before the seed day (a day of slack for a run across midnight).
    assert len(held) == 3 and held[0] >= 30 and held[-1] <= 120
    assert names == [f"Demo contractor {n:02d}" for n in range(1, 5)]
    assert (advance.advance_release_id, release) == (condition_id, "released")


async def test_the_seed_plans_in_the_project_currency_and_never_borrows_a_regime(world: World) -> None:
    await _subcontractors(world)
    pid = await _demo_project(world, currency="JPY", country="JP", public=True)
    await _seed(world, [pid])
    async with world.factory() as s:
        concept = await ProcurementConceptService(s).get_concept(pid)
        rows = (await s.execute(sa.select(AwardPackage).where(AwardPackage.project_id == pid))).scalars().all()
        fw = (
            (await s.execute(sa.select(FrameworkAgreement).where(FrameworkAgreement.tenant_id == str(world.manager))))
            .scalars()
            .one()
        )
        found = await ProcurementConceptService(s).findings(pid)
    # No shipped catalogue covers this country in this currency: no threshold regime is pretended.
    assert (concept.catalogue_id, concept.public_client, concept.client_type) == ("neutral", False, "private")
    assert {r.currency for r in rows} == {"JPY"} and fw.currency == "JPY"
    assert max(r.estimated_value for r in rows) == Decimal("2400000") * 150
    # Without a cleared condition nothing is planned as an advance package it could never release.
    assert [r for r in rows if r.is_advance] == []
    assert [f for f in found if f["severity"] == "error"] == []


# ── The model's own tags, through module 1's port ───────────────────────


async def test_the_pinned_model_names_the_area_the_document_and_the_release_gate(world: World) -> None:
    w = world
    await _concept(w)
    async with w.factory() as s:
        svc = ProcurementConceptService(s)
        hosting = await svc.hosting(w.project_id)
        concept = await svc.get_concept(w.project_id)
        area = await svc._procurement_area(w.project_id)
        doc = await svc._frame_document(w.project_id, concept)
        release = await svc.release_gate(w.project_id, concept)
        found = {f["code"] for f in await svc.findings(w.project_id)}
    # Rows of this project, found without this module knowing one code of the model.
    assert area is not None and area.code == hosting.area_code
    assert doc is not None and (doc.code,) == hosting.document_types and doc.area_id == area.id
    assert release is not None and release.code in hosting.release_gate_codes
    assert "release_gate_unresolved" not in found
    # The owner of that area steers; another editor of the project does not.
    async with w.factory() as s:
        from app.modules.project_governance.models import GovernanceArea

        (await s.get(GovernanceArea, area.id)).owner_user_id = w.owner
        await s.commit()
    async with w.factory() as s:
        svc = ProcurementConceptService(s)
        assert await svc.can_steer(w.project_id, w.owner, False) is True
        assert await svc.can_steer(w.project_id, w.editor, False) is False


async def test_a_catalogue_of_another_company_cannot_be_pinned_or_read(world: World) -> None:
    from app.modules.procurement_concept.catalogue import PROCUREMENT_KIND
    from app.modules.procurement_concept.errors import ProcurementError
    from app.modules.project_governance.catalogue_store import CatalogueStore, resolve_catalogue

    w = world
    foreign_tenant = str(w.outsider)
    async with w.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            foreign_tenant,
            code="their_rules",
            name="Their procedures",
            based_on_source="shipped",
            based_on_id="neutral",
            based_on_version=None,
            actor_id=w.outsider,
            kind=PROCUREMENT_KIND,
        )
        await store.publish(foreign_tenant, row.id, actor_id=w.outsider)
        await s.commit()
        foreign_id = str(row.id)
    async with w.factory() as s:
        with pytest.raises(ProcurementError) as exc:
            await ProcurementConceptService(s).set_concept(
                w.project_id,
                {"catalogue_source": "tenant", "catalogue_id": foreign_id},
                actor_id=w.manager,
                can_manage=True,
                tenant_id=str(w.manager),
            )
        assert (exc.value.code, exc.value.status_code) == ("unknown_catalogue", 404)
    async with w.factory() as s:
        # The resolver itself fails closed for a request-supplied id: foreign tenant, and no tenant at all.
        for tenant in (str(w.manager), None):
            with pytest.raises(GovernanceError) as denied:
                await resolve_catalogue(s, "tenant", foreign_id, 1, kind=PROCUREMENT_KIND, tenant_id=tenant)
            assert denied.value.status_code == 404
        assert (await _stored_or_none(w)) is None
    # Its owner pins it, and the stored pin keeps resolving for every reader of that project.
    async with w.factory() as s:
        svc = ProcurementConceptService(s)
        concept = await svc.set_concept(
            w.project_id,
            {"catalogue_source": "tenant", "catalogue_id": foreign_id},
            actor_id=w.manager,
            can_manage=True,
            tenant_id=foreign_tenant,
        )
        assert (await svc.catalogue_of(concept)).jurisdictions
        await s.rollback()


async def _stored_or_none(w: World) -> ProcurementConcept | None:
    async with w.factory() as s:
        return (
            await s.execute(sa.select(ProcurementConcept).where(ProcurementConcept.project_id == w.project_id))
        ).scalar_one_or_none()


async def test_the_seed_links_the_advance_package_to_a_released_long_lead_commitment(world: World) -> None:
    """No gate decision and no condition exists; the commitment matrix holds a released reservation."""
    from app.modules.procurement_concept import commitments

    pid = await _demo_project(world, currency="EUR", country="DE", public=True)
    options = [
        commitments.CommitmentOption(uuid.uuid4(), "CR-DES", "Design appointment", "released", True),
        commitments.CommitmentOption(uuid.uuid4(), "CR-LL", "Reservation", "released", True, lead_time_days=150),
        commitments.CommitmentOption(uuid.uuid4(), "CR-LL2", "Planned slot", "planned", False, lead_time_days=300),
    ]

    async def listing(_session, project_id):
        return options if project_id == pid else []

    async def check(_session, project_id, item_id):
        hit = next((o for o in options if o.id == item_id and project_id == pid), None)
        return commitments.CommitmentAnswer(found=hit is not None, released=bool(hit and hit.released))

    commitments.register_commitment_lister(listing)
    commitments.register_commitment_checker(check)
    try:
        await _seed(world, [pid])
        async with world.factory() as s:
            svc = ProcurementConceptService(s)
            concept = await svc.get_concept(pid)
            rows = (await s.execute(sa.select(AwardPackage).where(AwardPackage.project_id == pid))).scalars().all()
            (advance,) = [r for r in rows if r.is_advance]
            release = await svc.advance_release_status(pid, advance, await svc.release_gate(pid, concept))
            found = await svc.findings(pid)
    finally:
        commitments.register_commitment_lister(None)
        commitments.register_commitment_checker(None)
    # The released item with a lead time, not the released design appointment and not the planned slot.
    assert (advance.advance_release_kind, advance.advance_release_id) == ("commitment", options[1].id)
    assert (release, concept.release_gate_code, concept.state) == ("released", "", "draft")
    assert [f for f in found if f["blocks_approval"]] == []


async def test_the_seed_plans_every_ordinary_package_to_start_after_the_release_gate(world: World) -> None:
    """The gate that releases procurement is three weeks out and undecided; nothing is released."""
    from datetime import timedelta

    from app.modules.project_governance.models import GovernanceGate

    pid = await _demo_project(world, currency="EUR", country="DE", public=False)
    target = datetime.now(UTC).date() + timedelta(days=21)
    async with world.factory() as s:
        g = (
            await s.execute(
                sa.select(GovernanceGate).where(GovernanceGate.project_id == pid, GovernanceGate.code == RELEASE_GATE)
            )
        ).scalar_one()
        g.target_date = target.isoformat()
        await s.commit()
    await _seed(world, [pid])
    async with world.factory() as s:
        svc = ProcurementConceptService(s)
        found = await svc.findings(pid)
        schedule = await svc.schedule_view(pid)
        rows = (await s.execute(sa.select(AwardPackage).where(AwardPackage.project_id == pid))).scalars().all()
    # No commitment matrix and no cleared condition: no advance package, and never an unreleased one.
    assert [r for r in rows if r.is_advance] == []
    assert [f for f in found if f["blocks_approval"]] == []
    assert "award_schedule_infeasible" not in {f["code"] for f in found}
    starts = [date.fromisoformat(r["proposed_start_date"]) for r in schedule["items"] if r["proposed_start_date"]]
    assert starts and min(starts) > target
