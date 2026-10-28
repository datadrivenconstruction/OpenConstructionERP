# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design data that follows other modules, against PostgreSQL.

Deliverable state read from CDE (rule 15), a report following an external
check cycle (rules 17-18), a permit package pinning and detecting superseded
revisions (rule 19), the WBS reference resolver and delete guard (rules 3-4),
and the frame document going binding (rule 23).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.design_management.errors import DesignError
from app.modules.design_management.service import DesignService
from tests._pg import isolated_engine
from tests.pg.design_fixtures import DesignWorld, build_design_world, drawing_with_revision, new_revision

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        yield await build_design_world(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


async def _first_phase(w: DesignWorld) -> str:
    async with w.factory() as s:
        phases = await DesignService(s).phases(w.project_id)
    assert phases, "the governance world pins a model, so phases exist"
    return phases[0]["code"]


async def _cycle(w: DesignWorld, status: str = "submitted") -> uuid.UUID:
    from app.modules.review_authority.models import ReviewCycle

    async with w.factory() as s:
        c = ReviewCycle(project_id=w.project_id, authority_name="Checking engineer", status=status)
        s.add(c)
        await s.commit()
        return c.id


async def _set_cycle(w: DesignWorld, cycle_id: uuid.UUID, status: str) -> None:
    from app.modules.review_authority.models import ReviewCycle

    async with w.factory() as s:
        (await s.get(ReviewCycle, cycle_id)).status = status
        await s.commit()


# ── rule 15: deliverable state is computed from CDE ──────────────────────


async def test_deliverable_state_follows_its_drawings_suitability(world: DesignWorld) -> None:
    phase = await _first_phase(world)
    async with world.factory() as s:
        dl = await DesignService(s).create_deliverable(
            world.project_id,
            {"code": "DL-1", "phase_code": phase, "planned_count": 2, "target_suitability": "S4"},
            actor_id=world.editor,
        )
        await s.commit()
    assert dl.status == "not_started"

    await drawing_with_revision(world, "ARCH", "S0", deliverable_id=str(dl.id))
    await drawing_with_revision(world, "ARCH", "S2", deliverable_id=str(dl.id))
    async with world.factory() as s:
        rows = {d.code: d for d in await DesignService(s).deliverables(world.project_id)}
        await s.commit()
    assert rows["DL-1"].status == "in_progress"  # one drawing is still work in progress

    await drawing_with_revision(world, "ARCH", "S4", deliverable_id=str(dl.id))
    async with world.factory() as s:
        svc = DesignService(s)
        with pytest.raises(DesignError) as no_reason:
            await svc.patch_deliverable(world.project_id, dl.id, {"waived": True}, actor_id=world.editor)
        assert no_reason.value.code == "waiver_needs_rationale"
        row = await svc.patch_deliverable(
            world.project_id,
            dl.id,
            {"waived": True, "waived_rationale": "Covered by the shell package"},
            actor_id=world.editor,
        )
        await s.commit()
    assert row.status == "waived"


# ── rules 17-18: report and its external check ───────────────────────────


async def test_an_externally_checked_report_is_accepted_only_through_an_approved_cycle(world: DesignWorld) -> None:
    cycle = await _cycle(world)
    async with world.factory() as s:
        svc = DesignService(s)
        report = await svc.create_report(
            world.project_id,
            {
                "kind_code": "structural_proof_check",
                "author_role_id": str(world.roles["STRU"]),
                "checker_role_id": str(world.roles["ARCH"]),
                "external_check": True,
            },
            actor_id=world.editor,
        )
        for step in ("commissioned", "in_progress", "submitted", "under_check"):
            await svc.report_transition(world.project_id, report.id, step, actor_id=world.editor)
        # The cycle link is read by the acceptance rule: an editor may not set it, a manager fills it in once.
        with pytest.raises(DesignError) as editor:
            await svc.patch_report(world.project_id, report.id, {"review_cycle_id": str(cycle)}, actor_id=world.editor)
        assert editor.value.code == "manage_required"
        await svc.patch_report(
            world.project_id, report.id, {"review_cycle_id": str(cycle)}, actor_id=world.manager, may_manage=True
        )
        with pytest.raises(DesignError) as early:
            await svc.report_transition(world.project_id, report.id, "accepted", actor_id=world.editor)
        assert early.value.code == "report_external_check_not_approved"
        await s.commit()

    await _set_cycle(world, cycle, "remarks_issued")
    async with world.factory() as s:
        row = await DesignService(s).sync_report(world.project_id, report.id, actor_id=world.editor)
        await s.commit()
    assert row.status == "remarks"

    await _set_cycle(world, cycle, "approved")
    async with world.factory() as s:
        svc = DesignService(s)
        await svc.report_transition(world.project_id, report.id, "in_progress", actor_id=world.editor)
        await svc.report_transition(world.project_id, report.id, "submitted", actor_id=world.editor)
        await svc.report_transition(world.project_id, report.id, "under_check", actor_id=world.editor)
        row = await svc.sync_report(world.project_id, report.id, actor_id=world.editor)
        await s.commit()
    assert row.status == "accepted"


async def test_a_report_checked_by_its_own_author_is_refused(world: DesignWorld) -> None:
    async with world.factory() as s:
        svc = DesignService(s)
        report = await svc.create_report(
            world.project_id,
            {
                "kind_code": "structural_proof_check",
                "author_role_id": str(world.roles["STRU"]),
                "checker_role_id": str(world.roles["STRU"]),
            },
            actor_id=world.editor,
        )
        for step in ("commissioned", "in_progress", "submitted", "under_check"):
            await svc.report_transition(world.project_id, report.id, step, actor_id=world.editor)
        with pytest.raises(DesignError) as err:
            await svc.report_transition(world.project_id, report.id, "accepted", actor_id=world.editor)
    assert err.value.code == "report_checker_same_party"


# ── rule 19: permit package pins revisions and detects supersession ──────


async def test_a_permit_pins_revisions_on_submit_and_flags_a_later_revision(world: DesignWorld) -> None:
    d, rev1 = await drawing_with_revision(world, "ARCH", "S2")
    _wip, _r = await drawing_with_revision(world, "STRU", "S0")
    cycle = await _cycle(world)
    async with world.factory() as s:
        svc = DesignService(s)
        from app.modules.design_management.models import DesignDrawing

        container = (await s.get(DesignDrawing, d)).container_id
        wip_container = (await s.get(DesignDrawing, _wip)).container_id
        permit = await svc.create_permit(
            world.project_id, {"profile_code": "neutral", "review_cycle_id": str(cycle)}, actor_id=world.editor
        )
        await svc.add_permit_item(
            world.project_id, permit.id, {"kind": "drawing", "container_id": str(container)}, actor_id=world.editor
        )
        wip_item = await svc.add_permit_item(
            world.project_id, permit.id, {"kind": "drawing", "container_id": str(wip_container)}, actor_id=world.editor
        )
        with pytest.raises(DesignError) as incomplete:
            await svc.permit_transition(world.project_id, permit.id, "submitted", actor_id=world.editor)
        assert incomplete.value.code == "permit_incomplete"
        await svc.remove_permit_item(world.project_id, permit.id, wip_item.id, actor_id=world.editor)
        submitted = await svc.permit_transition(world.project_id, permit.id, "submitted", actor_id=world.editor)
        items = await svc.permit_items(world.project_id, permit.id)
        with pytest.raises(DesignError) as typed:
            await svc.permit_transition(world.project_id, permit.id, "approved", actor_id=world.editor)
        assert typed.value.code == "permit_state_read_from_cycle"
        await s.commit()
    assert submitted.status == "submitted"
    assert [i.included_revision_id for i in items] == [rev1]

    await new_revision(world, d, 2)
    await _set_cycle(world, cycle, "approved")
    async with world.factory() as s:
        row = await DesignService(s).sync_permit(world.project_id, permit.id, actor_id=world.editor)
        await s.commit()
    assert row.status == "approved"
    assert row.superseded_content is True


# ── rules 3-4: WBS references across modules ─────────────────────────────


async def test_the_resolver_finds_dangling_references_and_the_delete_guard_holds(world: DesignWorld) -> None:
    from app.modules.finance.models import ProjectBudget

    async with world.factory() as s:
        svc = DesignService(s)
        root = await svc.create_wbs(world.project_id, {"code": "1", "name": "Building"}, actor_id=world.manager)
        leaf = await svc.create_wbs(
            world.project_id, {"code": "1.1", "name": "Shell", "parent_id": str(root.id)}, actor_id=world.manager
        )
        for value in (str(leaf.id), "1", "9.9"):  # by id, by code, dangling
            s.add(ProjectBudget(project_id=world.project_id, wbs_id=value, currency_code="EUR"))
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        unresolved = await svc.unresolved_wbs(world.project_id)
        assert [(u.module, u.value) for u in unresolved] == [("finance", "9.9")]
        with pytest.raises(DesignError) as guarded:
            await svc.delete_wbs(world.project_id, root.id, actor_id=world.manager)
    assert guarded.value.status_code == 409


# ── rule 23: frame document and binding ──────────────────────────────────


@pytest_asyncio.fixture
async def m07_world():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_design_world(factory, governance="elf_module_framework")


async def test_every_governance_model_gets_a_frame_document_on_first_use(world: DesignWorld) -> None:
    """The frame document is the one the phase model tags for design, in that document's own area."""
    from sqlalchemy import select

    from app.modules.design_management.hosting import design_host
    from app.modules.project_governance.models import GovernanceArea, GovernanceDocument

    async with world.factory() as s:
        out = await DesignService(s).generate_frame_document(
            world.project_id,
            "register",
            governance_manager=True,
            actor_id=world.manager,
            file_bytes=b"%PDF-1.7 r",
            file_name="r.pdf",
        )
        await s.commit()
    async with world.factory() as s:
        doc = await s.get(GovernanceDocument, uuid.UUID(out["document_id"]))
        area = await s.get(GovernanceArea, doc.area_id)
        hosted = (
            await s.execute(select(GovernanceDocument).where(GovernanceDocument.project_id == world.project_id))
        ).scalars()
        assert area.code == (await design_host(s, world.project_id)).area_code
        assert str(doc.container_id) == out["container_id"]
        assert [d.id for d in hosted if d.doc_type == doc.doc_type] == [doc.id]


async def test_an_unknown_register_is_refused(world: DesignWorld) -> None:
    async with world.factory() as s:
        with pytest.raises(DesignError) as err:
            await DesignService(s).generate_frame_document(
                world.project_id,
                "drawing_register",
                governance_manager=True,
                actor_id=world.manager,
                file_bytes=b"x",
                file_name="r.pdf",
            )
    assert (err.value.code, err.value.status_code) == ("frame_register_unknown", 422)


async def test_a_frame_document_revision_is_written_and_binding_freezes_the_standard(m07_world: DesignWorld) -> None:

    from app.modules.cde.models import DocumentRevision
    from app.modules.project_governance.models import GovernanceDocument

    async with m07_world.factory() as s:
        out = await DesignService(s).generate_frame_document(
            m07_world.project_id,
            "register",
            governance_manager=True,
            actor_id=m07_world.manager,
            file_bytes=b"%PDF-1.7 register",
            file_name="r.pdf",
        )
        await s.commit()
    async with m07_world.factory() as s:
        rev = await s.get(DocumentRevision, uuid.UUID(out["revision_id"]))
        assert str(rev.container_id) == out["container_id"]
        doc = await s.get(GovernanceDocument, uuid.UUID(out["document_id"]))
        assert str(doc.container_id) == out["container_id"]
        doc.status = "binding"
        await s.commit()
    async with m07_world.factory() as s:
        svc = DesignService(s)
        with pytest.raises(DesignError) as frozen:
            await svc.change_scheme(
                m07_world.project_id,
                actor_id=m07_world.manager,
                tenant_id=str(m07_world.manager),
                source="shipped",
                scheme_id="iso19650_generic",
            )
        assert frozen.value.code == "binding_requires_change_request"
        with pytest.raises(DesignError) as again:
            await svc.generate_frame_document(
                m07_world.project_id,
                "register",
                governance_manager=True,
                actor_id=m07_world.manager,
                file_bytes=b"x",
                file_name="r.pdf",
            )
        assert again.value.code == "binding_requires_change_request"
        # Rule 23 also freezes the design organisation and the matrix.
        role = {"code": "X1", "party_kind": "specialist"}
        rule = {"recipient_role_id": str(m07_world.roles["ARCH"])}
        for write in (
            svc.create_role(m07_world.project_id, role, actor_id=m07_world.manager),
            svc.patch_role(m07_world.project_id, m07_world.roles["ARCH"], {"title": "t"}, actor_id=m07_world.manager),
            svc.delete_role(m07_world.project_id, m07_world.roles["STRU"], actor_id=m07_world.manager),
            svc.create_dist_rule(m07_world.project_id, rule, actor_id=m07_world.manager),
        ):
            with pytest.raises(DesignError) as bound:
                await write
            assert bound.value.code == "binding_requires_change_request"
