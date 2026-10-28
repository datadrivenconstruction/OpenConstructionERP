# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Stakeholders on a project with a pinned phase model: evidence and frame documents by tag.

The world is the shipped neutral phase model. Nothing here names its areas or
document types: the expected place of each subject is read from the model
through the same port the module uses.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.project_governance.evidence import GateAttempt
from app.modules.project_governance.models import GovernanceDocument
from app.modules.project_governance.public import Host, host_for, project_gates
from app.modules.project_governance.service import GovernanceService
from app.modules.stakeholders import hosting
from app.modules.stakeholders.errors import StakeholderError
from app.modules.stakeholders.evidence import (
    CHECK_SUBJECT,
    NO_DOCUMENT_REASON,
    NO_HOST_REASON,
    governance_readiness,
    host_code,
)
from app.modules.stakeholders.service import StakeholderService
from tests._pg import isolated_engine
from tests.pg import governance_fixtures as gov

pytestmark = pytest.mark.asyncio

ATTEMPT = GateAttempt(gate_id=uuid.uuid4(), gate_code="any", attempt_no=1)


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await gov.build_world(factory)
        async with factory() as s:
            svc = StakeholderService(s)
            await svc.put_settings(w.project_id, {"framework_id": "neutral"}, actor_id=w.manager)
            await svc.create_stakeholder(
                w.project_id, {"display_name": "Road authority", "category": "permitting_authority"}, actor_id=w.editor
            )
            await s.commit()
        yield w


async def _hosts(w: gov.World) -> dict[str, Host]:
    async with w.factory() as s:
        found = {subject: await host_for(s, w.project_id, subject) for subject in hosting.SUBJECTS}
    assert all(found.values()), found
    return found


async def _evidence(w: gov.World) -> dict[str, list]:
    """Evidence items of this module per area code."""
    areas = await gov.areas(w)
    async with w.factory() as s:
        return {code: await governance_readiness(s, w.project_id, ATTEMPT, area) for code, area in areas.items()}


def _codes(items: list) -> set[str]:
    return {i.code for i in items}


async def test_each_subject_reports_on_the_area_that_hosts_it(world: gov.World) -> None:
    hosts = await _hosts(world)
    by_area = await _evidence(world)
    for subject, found in hosts.items():
        expected = {f"stakeholders:{c}" for c, s in CHECK_SUBJECT.items() if s == subject}
        assert expected <= _codes(by_area[found.area_code]), subject
    reported = [i.code for items in by_area.values() for i in items]
    assert sorted(reported) == sorted(f"stakeholders:{c}" for c in CHECK_SUBJECT)
    assert all(i.state in ("met", "not_met", "unknown") for items in by_area.values() for i in items)


async def test_a_project_without_the_document_row_reports_unknown_not_silence(world: gov.World) -> None:
    hosts = await _hosts(world)
    register = hosts[hosting.STAKEHOLDERS_TAG]
    async with world.factory() as s:
        # A project pinned before its model gained the document type has no row for it.
        await s.execute(
            delete(GovernanceDocument).where(
                GovernanceDocument.project_id == world.project_id, GovernanceDocument.doc_type == register.doc_type
            )
        )
        await s.commit()
    code = host_code(hosting.STAKEHOLDERS_TAG, NO_DOCUMENT_REASON)
    items = [i for i in (await _evidence(world))[register.area_code] if i.code == code]
    assert [(i.state, i.detail) for i in items] == [("unknown", NO_DOCUMENT_REASON)]


async def test_a_model_that_hosts_nothing_reports_one_unknown_per_subject(world: gov.World, monkeypatch) -> None:
    real = hosting.project_catalogue

    async def untagged(session, project_id):
        model = await real(session, project_id)
        return model.model_copy(
            update={"document_types": tuple(d.model_copy(update={"hosts": ()}) for d in model.document_types)}
        )

    monkeypatch.setattr(hosting, "project_catalogue", untagged)
    by_area = await _evidence(world)
    items = [i for area_items in by_area.values() for i in area_items]
    assert sorted(i.code for i in items) == sorted(host_code(s) for s in hosting.SUBJECTS)
    assert {(i.state, i.detail) for i in items} == {("unknown", NO_HOST_REASON)}
    assert len([code for code, area_items in by_area.items() if area_items]) == 1
    async with world.factory() as s:
        with pytest.raises(StakeholderError) as exc:
            await StakeholderService(s).file_frame_document(
                world.project_id,
                which="register",
                content=b"x",
                file_name="register.pdf",
                mime_type="application/pdf",
                actor_id=world.manager,
            )
    assert exc.value.code == "frame_document_missing"


async def test_an_export_is_filed_into_the_document_its_subject_is_hosted_by(world: gov.World) -> None:
    hosts = await _hosts(world)
    organisation = hosts[hosting.ORGANISATION_TAG]
    async with world.factory() as s:
        container = await gov.add_container(s, world.project_id, "organisation-frame")
        document = next(
            d
            for d in await GovernanceService(s).repo.list_documents(world.project_id)
            if d.doc_type == organisation.doc_type
        )
        await GovernanceService(s).attach_container(
            world.project_id, document.id, container_id=container, actor_id=world.manager, is_manager=True
        )
        await s.commit()
    async with world.factory() as s:
        svc = StakeholderService(s)
        filed = await svc.file_frame_document(
            world.project_id,
            which="organisation",
            content=b"%PDF-1.4 organisation",
            file_name="organisation.pdf",
            mime_type="application/pdf",
            actor_id=world.manager,
        )
        await s.commit()
        # The register's own document has no container yet, so there is nothing to file into.
        with pytest.raises(StakeholderError) as exc:
            await svc.file_frame_document(
                world.project_id,
                which="register",
                content=b"x",
                file_name="register.pdf",
                mime_type="application/pdf",
                actor_id=world.manager,
            )
    assert (filed["document_id"], filed["doc_type"]) == (str(document.id), organisation.doc_type)
    assert filed["container_id"] == str(container)
    assert filed["change_request_id"] is None
    assert exc.value.code == "frame_document_missing"
    # What the screen is told before anybody presses the button is what the write answers.
    async with world.factory() as s:
        svc = StakeholderService(s)
        as_manager = await svc.filing_can(world.project_id, can_manage=True)
        as_reader = await svc.filing_can(world.project_id, can_manage=False)
    assert as_manager == {
        "register": {"applies": True, "allowed": False, "reason": "frame_document_missing"},
        "organisation": {"applies": True, "allowed": True, "reason": None},
    }
    assert {k: (v["applies"], v["reason"]) for k, v in as_reader.items()} == {
        "register": (True, "no_permission"),
        "organisation": (True, "no_permission"),
    }


async def test_a_read_only_frame_document_takes_no_revision(world: gov.World) -> None:
    hosts = await _hosts(world)
    organisation = hosts[hosting.ORGANISATION_TAG]
    async with world.factory() as s:
        container = await gov.add_container(s, world.project_id, "organisation-frame")
        document = next(
            d
            for d in await GovernanceService(s).repo.list_documents(world.project_id)
            if d.doc_type == organisation.doc_type
        )
        document.container_id = container
        document.read_only = True
        await s.commit()
    async with world.factory() as s:
        with pytest.raises(StakeholderError) as exc:
            await StakeholderService(s).file_frame_document(
                world.project_id,
                which="organisation",
                content=b"x",
                file_name="organisation.pdf",
                mime_type="application/pdf",
                actor_id=world.manager,
            )
    assert (exc.value.code, exc.value.status_code) == ("frame_document_read_only", 409)


async def test_the_gate_picker_lists_the_projects_gates_by_name(world: gov.World) -> None:
    async with world.factory() as s:
        listed = await StakeholderService(s).gates(world.project_id)
        expected = [g.code for g in await project_gates(s, world.project_id)]
    assert [g["code"] for g in listed] == expected
    assert listed and all(g["name"] and g["status"] for g in listed)
    assert any(g["name"] != g["code"] for g in listed)


async def test_a_plan_trigger_must_name_a_gate_of_the_project(world: gov.World) -> None:
    async with world.factory() as s:
        svc = StakeholderService(s)
        real = (await svc.gates(world.project_id))[0]["code"]
        base = {
            "title": "Gate briefing",
            "audience_categories": ["client"],
            "participation_level": "inform",
            "channel": "newsletter",
        }
        with pytest.raises(StakeholderError) as exc:
            await svc.create_plan_item(
                world.project_id, {**base, "trigger_kind": "gate", "trigger_ref": "no-such-gate"}, actor_id=world.editor
            )
        item = await svc.create_plan_item(
            world.project_id, {**base, "trigger_kind": "gate", "trigger_ref": real}, actor_id=world.editor
        )
        any_gate = await svc.create_plan_item(world.project_id, {**base, "trigger_kind": "gate"}, actor_id=world.editor)
        await s.commit()
    assert (exc.value.code, exc.value.status_code) == ("unknown_gate", 422)
    assert (item.trigger_ref, any_gate.trigger_ref) == (real, "")
    # Where gates are in use an item may wait for any of them: that is not the refusal of a gateless project.
    assert any_gate.trigger_kind == "gate"


async def test_a_binding_frame_document_changes_only_through_a_reasoned_change_request(world: gov.World) -> None:
    from app.modules.cde.models import DocumentContainer

    hosts = await _hosts(world)
    organisation = hosts[hosting.ORGANISATION_TAG]
    async with world.factory() as s:
        container = await gov.add_container(s, world.project_id, "organisation-frame")
        document = next(
            d
            for d in await GovernanceService(s).repo.list_documents(world.project_id)
            if d.doc_type == organisation.doc_type
        )
        # The state a decided gate leaves behind: the current revision is the binding one.
        document.container_id = container
        document.status = "binding"
        document.bound_revision_id = (await s.get(DocumentContainer, container)).current_revision_id
        await s.commit()

    async def file(reason: str, *, manages: bool):
        async with world.factory() as s:
            result = await StakeholderService(s).file_frame_document(
                world.project_id,
                which="organisation",
                content=b"%PDF-1.4 organisation v2",
                file_name="organisation.pdf",
                mime_type="application/pdf",
                actor_id=world.manager,
                change_reason=reason,
                change_impact="Two new members on the steering committee",
                can_manage_governance=manages,
            )
            await s.commit()
            return result

    with pytest.raises(StakeholderError) as silent:
        await file("", manages=True)
    with pytest.raises(StakeholderError) as not_owner:
        await file("New committee members", manages=False)
    filed = await file("New committee members", manages=True)
    with pytest.raises(StakeholderError) as second:
        await file("Another change", manages=True)
    assert (silent.value.code, silent.value.status_code) == ("change_reason_required", 422)
    assert (not_owner.value.code, not_owner.value.status_code) == ("not_area_owner", 403)
    assert filed["change_request_id"] is not None
    assert filed["warnings"] == ["frame_document_binding"]
    assert (second.value.code, second.value.status_code) == ("change_request_not_open", 409)


async def test_the_demo_seed_keeps_site_promises_agreed_until_the_gate_into_construction() -> None:
    from datetime import UTC, datetime, timedelta

    from app.modules.project_governance.public import phases_enabling, project_gates
    from app.modules.stakeholders.seed import _seed_project, gate_before_construction

    today = datetime.now(UTC).date()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await gov.build_world(factory)
        async with factory() as s:
            gate = gate_before_construction(
                await project_gates(s, w.project_id), await phases_enabling(s, w.project_id, "construction_start")
            )
            await _seed_project(s, w.project_id)
            await s.commit()
        async with factory() as s:
            svc = StakeholderService(s)
            commitments = await svc.repo.commitments(w.project_id)
            events = await svc.repo.events(w.project_id)
    assert gate is not None, "the shipped neutral model must name the phase that starts construction"
    assert {c.status for c in commitments} == {"agreed", "proposed"}
    overdue = [c for c in commitments if c.due_date < today]
    assert [c.status for c in overdue] == ["agreed"]
    planned = [e for e in events if e.status == "planned"]
    assert len(planned) == 1 and planned[0].occurrence_date > today
    held = [e for e in events if e.status == "held"]
    assert held and all(e.held_on < today for e in held)
    assert min(e.held_on for e in held if e.attendance_count == 64) == today - timedelta(days=40)


async def test_the_seeded_overdue_promise_is_one_warning_on_the_stakeholders_area(monkeypatch) -> None:
    from app.modules.project_governance import evidence as governance_evidence
    from app.modules.stakeholders import evidence as own
    from app.modules.stakeholders.seed import _seed_project

    async def read(w: gov.World) -> tuple[str, dict[str, list]]:
        hosts = await _hosts(w)
        return hosts["stakeholders"].area_code, await _evidence(w)

    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        w = await gov.build_world(factory)
        async with factory() as s:
            await _seed_project(s, w.project_id)
            await s.commit()
        async with factory() as s:
            (late,) = await StakeholderService(s).overdue_commitments(
                w.project_id, today=own.datetime.now(own.UTC).date()
            )

        # Without the state the promise can only fail the check it belongs to.
        monkeypatch.setattr(own, "EVIDENCE_STATES", ("met", "not_met", "unknown"))
        area, before = await read(w)
        tracked = [i for i in before[area] if i.code == "stakeholders:commitments_tracked"]
        assert [i.state for i in tracked] == ["not_met"]
        assert not [i for items in before.values() for i in items if i.code.startswith(own.OVERDUE_CODE)]

        # With it the check is met and the promise is an item of its own.
        served = ("met", "not_met", "unknown", "warning")
        monkeypatch.setattr(own, "EVIDENCE_STATES", served)
        monkeypatch.setattr(governance_evidence, "EVIDENCE_STATES", served)
        area, after = await read(w)
    tracked = [i for i in after[area] if i.code == "stakeholders:commitments_tracked"]
    assert [i.state for i in tracked] == ["met"]
    warnings = [(code, i) for code, items in after.items() for i in items if i.state == "warning"]
    assert [(code, i.code) for code, i in warnings] == [(area, f"{own.OVERDUE_CODE}:{late['code']}")]
    item = warnings[0][1]
    assert item.link == (own.LINK_KIND, str(w.project_id))
    assert late["code"] in item.labels["en"] and late["due_date"] in item.labels["de"]
