# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design numbering, frame documents, approval points, reports and permits against PostgreSQL.

One test per defect an independent review found: the generator that wedged on
a taken code, numbers reserved whichever door they came through, a register
per frame container with its file stored, the title block reader, a cancelled
approval route, report and permit fields a gate reads, project checks on
patch, races on codes and originators, and the demo seed.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.design_management.errors import DesignError
from app.modules.design_management.models import DesignApprovalPoint, DesignDrawing, DesignNumberReservation
from app.modules.design_management.service import FRAME_MARKER, FRAME_REGISTERS, DesignService
from tests._pg import isolated_engine
from tests.pg.design_fixtures import DesignWorld, build_design_world, drawing_with_revision
from tests.pg.governance_fixtures import add_container, add_route

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        yield await build_design_world(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


async def _number(w: DesignWorld, drawing_id: uuid.UUID) -> str:
    from app.modules.cde.models import DocumentContainer

    async with w.factory() as s:
        d = await s.get(DesignDrawing, drawing_id)
        return (await s.get(DocumentContainer, d.container_id)).container_code


# ── numbering (findings 2, 16) ──


async def test_the_generator_steps_over_a_code_a_container_already_holds(world: DesignWorld) -> None:
    """Finding 2: a container made before the counter knew about it must not wedge every later drawing."""
    first, _rev = await drawing_with_revision(world, "ARCH")
    taken = await _number(world, first)
    prefix, seq = taken.rsplit("-", 1)
    squatters = [f"{prefix}-{int(seq) + n:0{len(seq)}d}" for n in (1, 2)]
    async with world.factory() as s:
        for code in squatters:
            await add_container(s, world.project_id, code)  # straight into the table: no hook, no counter
        await s.commit()
    made = []
    for _ in range(2):
        d, _rev = await drawing_with_revision(world, "ARCH")
        made.append(await _number(world, d))
    assert not set(made) & {taken, *squatters}
    assert len(set(made)) == 2


async def test_a_number_typed_in_cde_is_reserved_and_never_typed_again(world: DesignWorld) -> None:
    """Finding 16: the reservation is written by the hook, so the CDE door reserves too."""
    from fastapi import HTTPException

    from app.modules.cde.models import DocumentContainer
    from app.modules.cde.schemas import ContainerCreate
    from app.modules.cde.service import CDEService

    body = ContainerCreate(project_id=world.project_id, container_code="A-777", title="typed in CDE", cde_state="wip")
    async with world.factory() as s:
        container = await CDEService(s).create_container(body, user_id=str(world.editor))
        await s.commit()
    async with world.factory() as s:
        reserved = (await s.execute(select(DesignNumberReservation.number))).scalars().all()
        assert "A-777" in reserved
        await s.delete(await s.get(DocumentContainer, container.id))
        await s.commit()
    async with world.factory() as s:
        with pytest.raises(HTTPException) as again:
            await CDEService(s).create_container(body, user_id=str(world.editor))
    assert again.value.status_code == 422
    assert [v["code"] for v in again.value.detail["violations"]] == ["number_reserved"]


async def test_renumbering_to_the_same_number_changes_nothing(world: DesignWorld) -> None:
    d, _rev = await drawing_with_revision(world, "ARCH")
    number = await _number(world, d)
    async with world.factory() as s:
        out = await DesignService(s).renumber_apply(world.project_id, {str(d): number}, actor_id=world.manager)
        await s.commit()
    assert out == []
    async with world.factory() as s:
        assert (await s.get(DesignDrawing, d)).aliases in ([], None)
    assert await _number(world, d) == number


# ── frame documents (findings 1, 10) ──


async def test_each_register_has_its_own_revision_stream_and_its_file(world: DesignWorld) -> None:
    """Findings 1 and 10: the pinned scheme does not refuse the frame container; the PDF is stored."""
    from app.core.storage import get_storage_backend
    from app.modules.cde.models import DocumentContainer, DocumentRevision

    out = {}
    async with world.factory() as s:
        svc = DesignService(s)
        for register in FRAME_REGISTERS:
            out[register] = await svc.generate_frame_document(
                world.project_id,
                register,
                governance_manager=True,
                actor_id=world.manager,
                file_bytes=f"%PDF-1.7 {register}".encode(),
                file_name=f"{register}.pdf",
            )
        second = await svc.generate_frame_document(
            world.project_id,
            "matrix",
            governance_manager=True,
            actor_id=world.manager,
            file_bytes=b"%PDF-1.7 matrix v2",
            file_name="m.pdf",
        )
        await s.commit()
    assert len({o["container_id"] for o in out.values()}) == len(FRAME_REGISTERS)
    assert len({o["document_id"] for o in out.values()}) == 1
    assert second["container_id"] == out["matrix"]["container_id"]
    assert second["revision_id"] != out["matrix"]["revision_id"]
    async with world.factory() as s:
        for register, o in out.items():
            rev = await s.get(DocumentRevision, uuid.UUID(o["revision_id"]))
            assert rev.storage_key == o["storage_key"]
            assert await get_storage_backend().get(rev.storage_key) == f"%PDF-1.7 {register}".encode()
            container = await s.get(DocumentContainer, rev.container_id)
            assert container.metadata_[FRAME_MARKER] == register
        streams = (
            (
                await s.execute(
                    select(DocumentRevision.id).where(
                        DocumentRevision.container_id == uuid.UUID(out["matrix"]["container_id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(streams) == 2
        reserved = (await s.execute(select(DesignNumberReservation.number))).scalars().all()
    assert not [n for n in reserved if n.startswith("DESIGN-FRAME-")], "a frame code is not a drawing number"


async def test_a_client_cannot_mark_its_own_container_as_a_frame_document(world: DesignWorld) -> None:
    """Finding 1: the marker that skips the scheme is dropped from request metadata."""
    from fastapi import HTTPException

    from app.modules.cde.models import DocumentContainer
    from app.modules.cde.schemas import ContainerCreate, ContainerUpdate
    from app.modules.cde.service import CDEService

    async with world.factory() as s:
        with pytest.raises(HTTPException) as refused:
            await CDEService(s).create_container(
                ContainerCreate(
                    project_id=world.project_id,
                    container_code="NOT-A-NUMBER",
                    title="x",
                    metadata={FRAME_MARKER: "register"},
                ),
                user_id=str(world.editor),
            )
        assert refused.value.status_code == 422
    async with world.factory() as s:
        ok = await CDEService(s).create_container(
            ContainerCreate(
                project_id=world.project_id, container_code="A-300", title="x", metadata={FRAME_MARKER: "register"}
            ),
            user_id=str(world.editor),
        )
        await CDEService(s).update_container(ok.id, ContainerUpdate(metadata={FRAME_MARKER: "matrix", "note": "n"}))
        await s.commit()
    async with world.factory() as s:
        meta = (await s.get(DocumentContainer, ok.id)).metadata_ or {}
    assert FRAME_MARKER not in meta and meta.get("note") == "n"


# ── title block (finding 8) ──


async def test_the_title_block_reader_stores_the_sheet_number_or_nothing(world: DesignWorld) -> None:
    d, _rev = await drawing_with_revision(world, "ARCH")
    number = await _number(world, d)
    async with world.factory() as s:
        svc = DesignService(s)
        read = await svc.read_title_block(
            world.project_id, d, f"Ground floor plan\nScale 1:100\nDrawing No: {number}\n", actor_id=world.editor
        )
        assert read.title_block_number == number
        other = await svc.read_title_block(
            world.project_id, d, "Ground floor plan\nDrawing No: A-999\n", actor_id=world.editor
        )
        assert other.title_block_number == "A-999"
        row = next(r for r in await svc.register(world.project_id) if r["container"].container_code == number)
        assert row["title_block_mismatch"] is True
        nothing = await svc.read_title_block(
            world.project_id, d, "General arrangement of the entrance hall, see notes", actor_id=world.editor
        )
        assert nothing.title_block_number is None, "free text is not a sheet number"


# ── approval points (findings 9, 14) ──


async def test_a_cancelled_route_reopens_the_approval_point(world: DesignWorld) -> None:
    from app.modules.approval_routes.service import ApprovalRouteService

    async with world.factory() as s:
        await add_route(s, world.project_id, "design_approval_point", world.approver)
        svc = DesignService(s)
        ap = await svc.create_approval_point(world.project_id, {"kind": "owner_approval"}, actor_id=world.editor)
        sent = await svc.submit_approval_point(world.project_id, ap.id, actor_id=world.editor)
        await ApprovalRouteService(s).cancel_instance(sent.approval_instance_id, actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        assert (await s.get(DesignApprovalPoint, ap.id)).status == "in_review"
        assert await svc.catch_up_approvals(world.project_id) == 1
        row = await s.get(DesignApprovalPoint, ap.id)
        assert (row.status, row.approval_instance_id) == ("open", None)
        await svc.patch_approval_point(world.project_id, ap.id, {"title": "again"}, actor_id=world.editor)
        again = await svc.submit_approval_point(world.project_id, ap.id, actor_id=world.editor)
        assert again.status == "in_review"


async def test_a_role_of_another_project_is_refused_on_patch_as_on_create(world: DesignWorld) -> None:
    other = await build_design_world(world.factory)
    foreign = str(other.roles["ARCH"])
    async with world.factory() as s:
        svc = DesignService(s)
        phase = (await svc.phases(world.project_id))[0]["code"]
        dl = await svc.create_deliverable(world.project_id, {"phase_code": phase}, actor_id=world.editor)
        ap = await svc.create_approval_point(world.project_id, {"kind": "owner_approval"}, actor_id=world.editor)
        for write in (
            svc.patch_deliverable(world.project_id, dl.id, {"role_id": foreign}, actor_id=world.editor),
            svc.patch_approval_point(world.project_id, ap.id, {"approver_role_id": foreign}, actor_id=world.editor),
        ):
            with pytest.raises(DesignError) as err:
                await write
            assert (err.value.code, err.value.status_code) == ("role_not_found", 404)


# ── reports and permits (findings 11, 20) ──


async def test_report_fields_a_gate_reads_cannot_be_edited_away(world: DesignWorld) -> None:
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
        with pytest.raises(DesignError) as editor:
            await svc.patch_report(world.project_id, report.id, {"external_check": False}, actor_id=world.editor)
        assert (editor.value.code, editor.value.status_code) == ("manage_required", 403)
        with pytest.raises(DesignError) as silent:
            await svc.patch_report(
                world.project_id, report.id, {"required": False}, actor_id=world.manager, may_manage=True
            )
        assert silent.value.code == "not_required_needs_rationale"
        for step in ("commissioned", "in_progress", "submitted"):
            await svc.report_transition(world.project_id, report.id, step, actor_id=world.editor)
        for data in ({"external_check": False}, {"author_role_id": None}, {"required": False, "rationale": "no"}):
            with pytest.raises(DesignError) as frozen:
                await svc.patch_report(world.project_id, report.id, data, actor_id=world.manager, may_manage=True)
            assert (frozen.value.code, frozen.value.status_code) == ("report_fields_frozen", 409), data
        kept = await svc.patch_report(world.project_id, report.id, {"title": "Proof check"}, actor_id=world.editor)
        assert (kept.external_check, kept.author_role_id, kept.required) == (True, world.roles["STRU"], True)


async def test_a_permit_without_a_cycle_is_decided_by_a_manager_and_keeps_its_links(world: DesignWorld) -> None:
    from app.modules.review_authority.models import ReviewCycle

    d, _rev = await drawing_with_revision(world, "ARCH")
    async with world.factory() as s:
        svc = DesignService(s)
        container = (await s.get(DesignDrawing, d)).container_id
        permit = await svc.create_permit(world.project_id, {"profile_code": "neutral"}, actor_id=world.editor)
        await svc.add_permit_item(
            world.project_id, permit.id, {"kind": "drawing", "container_id": str(container)}, actor_id=world.editor
        )
        await svc.permit_transition(world.project_id, permit.id, "submitted", actor_id=world.editor)
        with pytest.raises(DesignError) as editor:
            await svc.permit_transition(world.project_id, permit.id, "under_review", actor_id=world.editor)
        assert (editor.value.code, editor.value.status_code) == ("manage_required", 403)
        for target in ("under_review", "partially_approved"):
            row = await svc.permit_transition(
                world.project_id, permit.id, target, actor_id=world.manager, may_manage=True
            )
        assert row.status == "partially_approved"
        with pytest.raises(DesignError) as stranger:
            await svc.propose_conditions(
                world.project_id,
                permit.id,
                [{"text": "Fire damper schedule", "owner_user_id": str(world.outsider), "due_date": "2027-01-31"}],
                actor_id=world.manager,
            )
        assert (stranger.value.code, stranger.value.status_code) == ("condition_owner_not_member", 422)
        noted = await svc.propose_conditions(
            world.project_id,
            permit.id,
            [{"text": "Fire damper schedule", "owner_user_id": str(world.editor), "due_date": "2027-01-31"}],
            actor_id=world.manager,
        )
        assert [c["state"] for c in noted.conditions] == ["proposed"]
        approved = await svc.permit_transition(
            world.project_id, permit.id, "approved", actor_id=world.manager, may_manage=True
        )
        assert approved.status == "approved"
        cycles = []
        for _ in range(2):
            cycle = ReviewCycle(project_id=world.project_id, authority_name="Authority", status="approved")
            s.add(cycle)
            await s.flush()
            cycles.append(str(cycle.id))
        with pytest.raises(DesignError) as editor_link:
            await svc.patch_permit(world.project_id, permit.id, {"review_cycle_id": cycles[0]}, actor_id=world.editor)
        assert editor_link.value.code == "manage_required"
        await svc.patch_permit(
            world.project_id, permit.id, {"review_cycle_id": cycles[0]}, actor_id=world.manager, may_manage=True
        )
        with pytest.raises(DesignError) as swapped:
            await svc.patch_permit(
                world.project_id, permit.id, {"review_cycle_id": cycles[1]}, actor_id=world.manager, may_manage=True
            )
        assert (swapped.value.code, swapped.value.status_code) == ("permit_link_frozen", 409)


async def test_a_wbs_node_named_by_a_role_or_the_matrix_cannot_be_deleted(world: DesignWorld) -> None:
    """Finding 20: the JSON lists count as references too."""
    async with world.factory() as s:
        svc = DesignService(s)
        by_role = await svc.create_wbs(world.project_id, {"code": "7", "name": "Role"}, actor_id=world.manager)
        by_rule = await svc.create_wbs(world.project_id, {"code": "8", "name": "Rule"}, actor_id=world.manager)
        free = await svc.create_wbs(world.project_id, {"code": "9", "name": "Free"}, actor_id=world.manager)
        await svc.patch_role(
            world.project_id, world.roles["ARCH"], {"responsible_wbs_ids": [str(by_role.id)]}, actor_id=world.manager
        )
        await svc.create_dist_rule(
            world.project_id,
            {"recipient_role_id": str(world.roles["ARCH"]), "wbs_node_ids": [str(by_rule.id)]},
            actor_id=world.manager,
        )
        for node in (by_role, by_rule):
            with pytest.raises(DesignError) as held:
                await svc.delete_wbs(world.project_id, node.id, actor_id=world.manager)
            assert held.value.code == "wbs_node_referenced"
        await svc.delete_wbs(world.project_id, free.id, actor_id=world.manager)


# ── races (finding 19) and rule 21 ──


async def test_two_roles_created_at_once_cannot_share_an_originator_or_a_code(world: DesignWorld) -> None:
    async def create(data: dict) -> str:
        async with world.factory() as s:
            try:
                role = await DesignService(s).create_role(world.project_id, data, actor_id=world.manager)
                await s.commit()
            except DesignError as exc:
                await s.rollback()
                return exc.code
            return role.code

    same_originator = {"party_kind": "discipline_designer", "discipline_code": "M", "originator_code": "MEP"}
    outcomes = await asyncio.gather(*(create(dict(same_originator)) for _ in range(4)))
    assert sorted(o for o in outcomes if o == "originator_duplicate") == ["originator_duplicate"] * 3, outcomes
    generated = await asyncio.gather(*(create({"party_kind": "specialist"}) for _ in range(4)))
    assert len(set(generated)) == 4 and all(code.startswith("ROLE-") for code in generated), generated


async def test_a_drawing_originator_must_belong_to_an_appointed_or_active_role(world: DesignWorld) -> None:
    """Rule 21: a planned role does not count, and a project with no coded role does not switch the check off."""
    async with world.factory() as s:
        svc = DesignService(s)
        assert await svc._active_originators(world.project_id) == set()
        await svc.patch_role(world.project_id, world.roles["ARCH"], {"state": "appointed"}, actor_id=world.manager)
        assert await svc._active_originators(world.project_id) == {"ORA"}
        await svc.change_scheme(
            world.project_id,
            actor_id=world.manager,
            tenant_id=str(world.manager),
            source="shipped",
            scheme_id="iso19650_generic",
        )
        fields = {"project": "PRJ1", "functional": "ZZ", "spatial": "00", "form": "DR"}
        _d, made = await svc.create_drawing(
            world.project_id,
            {"role_id": str(world.roles["ARCH"]), "title": "t", "fields": fields},
            actor_id=world.editor,
        )
        assert "-ORA-" in made.container_code
        with pytest.raises(DesignError) as unknown:
            await svc.create_drawing(
                world.project_id,
                {"role_id": str(world.roles["STRU"]), "title": "t", "fields": fields},
                actor_id=world.editor,
            )
        assert unknown.value.code == "originator_unknown"


# ── demo seed (finding 21) ──


async def _pin_default_model(s: AsyncSession, pid: uuid.UUID, owner: uuid.UUID) -> None:
    """What the governance demo seed does before the design seed runs: pin the default phase model."""
    from app.modules.project_governance.public import default_catalogue_pin
    from app.modules.project_governance.service import GovernanceService

    # No country: the neutral model, whose construction phase is the one that enables the start on site.
    pin = default_catalogue_pin()
    await GovernanceService(s).set_model(
        pid,
        source=pin.source,
        catalogue_id=pin.catalogue_id,
        version=pin.version,
        four_eyes=True,
        actor_id=owner,
        tenant_id=str(owner),
    )


def _cost_login() -> str:
    from app.core.demo_cast import CAST

    return CAST["cost"]


async def test_the_demo_seed_puts_no_account_from_outside_the_cast_on_a_row(world: DesignWorld, caplog) -> None:
    """An installation of real people: a demo login outside the cast is on no seeded row, and nothing is louder than info."""
    from app.core.demo_accounts import DEMO_ACCOUNT_EMAILS, SHOWCASE_OWNER_EMAIL
    from app.core.demo_cast import CAST
    from app.modules.design_management import seed
    from app.modules.design_management.models import ALL_MODELS, DesignSetup
    from app.modules.projects.models import Project
    from app.modules.users.models import User
    from tests.pg.governance_fixtures import add_project, add_user

    async with world.factory() as s:
        owner, stranger, real = await add_user(s, "admin"), await add_user(s, "manager"), await add_user(s, "manager")
        (await s.get(User, owner)).email = SHOWCASE_OWNER_EMAIL
        # The account the old lookup picked: any demo login that is not the owner. No cast part plays here.
        outside = sorted(DEMO_ACCOUNT_EMAILS - {SHOWCASE_OWNER_EMAIL} - set(CAST.values()))
        if outside:
            (await s.get(User, stranger)).email = outside[0]
        pid = await add_project(s, owner, [])
        project = await s.get(Project, pid)
        project.country_code = "DE"
        project.metadata_ = {**(project.metadata_ or {}), "demo_id": "design-seed-alone"}
        await _pin_default_model(s, pid, owner)
        await s.commit()
    with caplog.at_level("DEBUG", logger="app.modules.design_management"):
        async with world.factory() as s:
            totals = await seed.seed_design_management_demo(s, [pid])
            await s.commit()
    assert (totals["projects"], totals["one_person_stories"]) == (1, 1)
    loud = [r for r in caplog.records if r.name.startswith("app.modules.design_management") and r.levelno > 20]
    assert not loud, [(r.name, r.levelname, r.getMessage()) for r in loud]
    foreign = {stranger, real}
    async with world.factory() as s:
        svc = DesignService(s)
        for model in ALL_MODELS:
            rows = await svc._list(model, pid)
            assert rows, f"{model.__tablename__} is empty in the one-person demo"
            for row in rows:
                for column in model.__table__.columns:
                    value = getattr(row, column.key, None)
                    # JSON columns hold lists and dicts, which a set cannot be asked about.
                    assert isinstance(value, (list, dict)) or value not in foreign, (model.__tablename__, column.name)
        setup = (await svc._list(DesignSetup, pid))[0]
        assert setup.four_eyes_release is False


async def test_the_demo_seed_lets_the_demo_user_approve_issue_and_submit(world: DesignWorld) -> None:
    """Every list is filled, the release waits for the demo user and an approval point can be submitted."""
    from app.core.demo_accounts import SHOWCASE_OWNER_EMAIL
    from app.modules.design_management import seed
    from app.modules.design_management.models import ALL_MODELS, DesignRelease
    from app.modules.projects.models import Project
    from app.modules.users.models import User
    from tests.pg.governance_fixtures import add_project, add_user

    async with world.factory() as s:
        owner, second = await add_user(s, "admin"), await add_user(s, "manager")
        (await s.get(User, owner)).email = SHOWCASE_OWNER_EMAIL
        # The cast's second person of every four-eyes step, under the demo login that plays the part.
        (await s.get(User, second)).email = _cost_login()
        pid = await add_project(s, owner, [second])
        project = await s.get(Project, pid)
        project.country_code = "DE"
        project.metadata_ = {**(project.metadata_ or {}), "demo_id": "design-seed-test"}
        await s.commit()
    async with world.factory() as s:
        # No phase model yet: the governance seed runs first, and without it design has no phases to plan along.
        assert (await seed.seed_design_management_demo(s, [pid]))["projects"] == 0
        await _pin_default_model(s, pid, owner)
        await s.commit()
    async with world.factory() as s:
        from app.core.demo_marker import demo_id_of

        assert demo_id_of((await s.get(Project, pid)).metadata_), "the fixture project must carry the demo marker"
        totals = await seed.seed_design_management_demo(s, [pid])
        await s.commit()
    assert totals["projects"] == 1
    async with world.factory() as s:
        svc = DesignService(s)
        for model in ALL_MODELS:
            assert await svc._list(model, pid), f"{model.__tablename__} is empty in the demo"
        releases = {r.code: r for r in await svc._list(DesignRelease, pid)}
        waiting = releases["REL-001"]
        assert (waiting.status, waiting.approval_status, waiting.content_changed_by) == ("ready", "pending", second)
        assert (await svc.release_can(waiting, actor_id=owner, may_release=True))["approve"]["allowed"]
        assert await svc.apply_release_verdict(
            waiting.id, waiting.approval_instance_id, decision="approved", decided_by=owner
        )
        issued = await svc.issue_release(pid, waiting.id, actor_id=owner)
        assert issued.status == "issued" and issued.transmittal_ids
        point = (await svc._list(DesignApprovalPoint, pid, DesignApprovalPoint.code))[0]
        assert (await svc.submit_approval_point(pid, point.id, actor_id=owner)).status == "in_review"
        again = await seed.seed_design_management_demo(s, [pid])
    assert again["projects"] == 0, "a second run touches nothing"


# ── module 1's read port: tenant catalogues and the governance write rule ──


async def test_a_scheme_of_another_tenant_cannot_be_pinned(world: DesignWorld) -> None:
    """An id from a request resolves for the caller's tenant only; a foreign one is unknown, not readable."""
    from app.modules.design_management.catalogue import NUMBERING_KIND, register_kinds
    from app.modules.project_governance.catalogue_store import CatalogueStore
    from app.modules.project_governance.errors import GovernanceError

    owner, stranger = str(world.manager), str(world.outsider)
    register_kinds()
    async with world.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            owner,
            code="own_scheme",
            name="Own scheme",
            based_on_source="shipped",
            based_on_id="iso19650_generic",
            based_on_version=None,
            actor_id=world.manager,
            kind=NUMBERING_KIND,
        )
        await store.publish(owner, row.id, actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        with pytest.raises(GovernanceError) as foreign:
            await svc.change_scheme(
                world.project_id, actor_id=world.outsider, tenant_id=stranger, source="tenant", scheme_id=str(row.id)
            )
        assert (foreign.value.code, foreign.value.status_code) == ("unknown_catalogue", 404)
        with pytest.raises(GovernanceError) as nobody:
            await svc._pinnable(None, "tenant", str(row.id), None, NUMBERING_KIND)
        assert nobody.value.code == "unknown_catalogue", "no tenant fails closed"
        assert await svc._pinnable(owner, "tenant", str(row.id), None, NUMBERING_KIND) == 1


async def test_a_frame_document_follows_the_governance_write_rule(world: DesignWorld) -> None:
    """Design does not lend its own permission: without governance.manage only the area's owner may write."""
    from app.modules.cde.models import DocumentContainer
    from app.modules.project_governance.errors import GovernanceError

    async with world.factory() as s:
        before = (
            await s.execute(select(DocumentContainer.id).where(DocumentContainer.project_id == world.project_id))
        ).all()
        with pytest.raises(GovernanceError) as refused:
            await DesignService(s).generate_frame_document(
                world.project_id, "register", actor_id=world.editor, file_bytes=b"%PDF-1.7 r", file_name="r.pdf"
            )
        assert (refused.value.code, refused.value.status_code) == ("not_area_owner", 403)
    async with world.factory() as s:
        left = (
            await s.execute(select(DocumentContainer.id).where(DocumentContainer.project_id == world.project_id))
        ).all()
        assert sorted(left) == sorted(before), "a refused request leaves no container behind"


# ── demo seed: one moment before construction, read from the project's state ──


async def _demo_project(world: DesignWorld) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.core.demo_accounts import SHOWCASE_OWNER_EMAIL
    from app.modules.projects.models import Project
    from app.modules.users.models import User
    from tests.pg.governance_fixtures import add_project, add_user

    async with world.factory() as s:
        owner, second = await add_user(s, "admin"), await add_user(s, "manager")
        (await s.get(User, owner)).email = SHOWCASE_OWNER_EMAIL
        # The cast's second person of every four-eyes step, under the demo login that plays the part.
        (await s.get(User, second)).email = _cost_login()
        pid = await add_project(s, owner, [second])
        project = await s.get(Project, pid)
        project.country_code = "DE"
        project.metadata_ = {**(project.metadata_ or {}), "demo_id": "design-seed-story"}
        await _pin_default_model(s, pid, owner)
        await s.commit()
    return pid, owner, second


async def test_before_construction_the_seed_leaves_one_report_between_the_project_and_its_gate(
    world: DesignWorld,
) -> None:
    """The gate into construction is undecided: one submitted report blocks its phase, one move clears it."""
    from app.modules.design_management import seed
    from app.modules.design_management.models import DesignRelease, DesignReport
    from app.modules.project_governance.public import phases_enabling, project_gates

    pid, owner, second = await _demo_project(world)
    async with world.factory() as s:
        enabling = set(await phases_enabling(s, pid, "construction_start"))
        gate = next(g for g in await project_gates(s, pid) if g.to_phase in enabling)
        assert gate.status != "decided"
        assert await seed._pre_construction(s, pid) == (gate.from_phase, gate.to_phase)
        assert (await seed.seed_design_management_demo(s, [pid]))["projects"] == 1
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        blockers = await svc.readiness(pid, gate.from_phase)
        assert (blockers.deliverables, blockers.major_comments) == ([], 0), blockers
        assert len(blockers.reports) == 1, blockers
        reports = await svc._list(DesignReport, pid, DesignReport.code)
        open_now = [r for r in reports if r.phase_code == gate.from_phase and r.status != "accepted"]
        assert [r.status for r in open_now] == ["submitted"]
        later = [r for r in reports if r.phase_code == gate.to_phase]
        assert later and all(r.status in ("required", "commissioned") for r in later)
        for phase in {p["code"] for p in await svc.phases(pid)} - {gate.from_phase}:
            early = await svc.readiness(pid, phase)
            if phase != gate.to_phase:
                assert (early.deliverables, early.reports, early.major_comments) == ([], [], 0), (phase, early)
        releases = {r.code: r for r in await svc._list(DesignRelease, pid)}
        assert (releases["REL-001"].status, releases["REL-001"].approval_status) == ("ready", "pending")
        assert releases["REL-001"].content_changed_by == second
        assert releases["REL-002"].status == "issued" and releases["REL-002"].transmittal_ids
        assert releases["REL-002"].approved_by == owner
        # The single step the film takes: the demo user accepts the report, the phase is clear.
        await svc.report_transition(pid, open_now[0].id, "accepted", actor_id=owner)
        cleared = await svc.readiness(pid, gate.from_phase)
        assert (cleared.deliverables, cleared.reports, cleared.major_comments) == ([], [], 0)


async def test_past_the_construction_gate_the_seed_tells_its_running_story(world: DesignWorld, monkeypatch) -> None:
    """A project past that gate, or with a model that has none, keeps reports and lines in progress."""
    from app.modules.design_management import seed
    from app.modules.design_management.models import DesignRelease, DesignReport

    pid, _owner, _second = await _demo_project(world)

    async def decided(_session, _project_id):
        return None

    monkeypatch.setattr(seed, "_pre_construction", decided)
    async with world.factory() as s:
        assert (await seed.seed_design_management_demo(s, [pid]))["projects"] == 1
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        states = sorted(r.status for r in await svc._list(DesignReport, pid))
        assert states == ["accepted", "commissioned", "in_progress", "required", "required"]
        releases = {r.code: r.status for r in await svc._list(DesignRelease, pid)}
        assert releases == {"REL-001": "ready", "REL-002": "draft"}


async def test_on_a_running_site_the_concept_and_permit_set_went_out_on_their_story_days(
    world: DesignWorld, monkeypatch
) -> None:
    """Past a decided gate nothing of the design phases waits: both releases are issued, dated and received."""
    from datetime import UTC, date, datetime, timedelta

    from app.modules.design_management import seed
    from app.modules.design_management.models import DesignRelease
    from app.modules.transmittals.models import Transmittal, TransmittalRecipient

    pid, _owner, _second = await _demo_project(world)

    async def undecided(_session, _project_id):
        return None

    async def released(_session, _project_id):
        return True

    monkeypatch.setattr(seed, "_pre_construction", undecided)
    monkeypatch.setattr(seed, "_construction_released", released)
    async with world.factory() as s:
        assert (await seed.seed_design_management_demo(s, [pid]))["projects"] == 1
        await s.commit()
    async with world.factory() as s:
        releases = {r.code: r for r in await DesignService(s)._list(DesignRelease, pid)}
        today = datetime.now(UTC).date()
        for code in ("REL-001", "REL-002"):
            row = releases[code]
            assert row.status == "issued" and row.transmittal_ids, code
            days = seed._RUNNING_ISSUED_DAYS_AGO[code]
            assert row.issued_at.date() == today - timedelta(days=days), code
            ids = [uuid.UUID(t) for t in row.transmittal_ids]
            sent = (await s.execute(select(Transmittal).where(Transmittal.id.in_(ids)))).scalars().all()
            assert {date.fromisoformat(t.issued_date) for t in sent} == {today - timedelta(days=days)}, code
            acks = (
                (
                    await s.execute(
                        select(TransmittalRecipient.acknowledged_at).where(TransmittalRecipient.transmittal_id.in_(ids))
                    )
                )
                .scalars()
                .all()
            )
            assert acks and all(a is not None for a in acks), code
        # The concept went out before the permit set.
        assert releases["REL-001"].issued_at < releases["REL-002"].issued_at
