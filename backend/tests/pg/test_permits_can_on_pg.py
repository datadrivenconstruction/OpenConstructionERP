# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permits on real PostgreSQL: the ``can`` flags against the writes they describe, and the notice extraction.

A flag is only worth serving if the write then does what it said, so every flag
asserted here is followed by the write it belongs to. The AI provider and the
file store are faked at their boundary (``ai_client`` and ``get_storage_backend``);
everything between them is the real code.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.permits import guards
from app.modules.permits.errors import PermitError
from app.modules.permits.service import PermitService, condition_out, roadmap_out
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_container, add_revision
from tests.pg.permits_fixtures import (
    World,
    application,
    build_world,
    cond,
    decide,
    depend,
    file,
    move,
    requirement,
)

TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio

BUILDING = "baugenehmigung"
PRELIMINARY = "bauvoranfrage"

NOTICE = (
    "Baugenehmigung Az. 2026-0815\n\n"
    "1. Vor Baubeginn ist der Standsicherheitsnachweis geprüft vorzulegen.\n"
    "2. Die Baustelle ist arbeitstäglich zu reinigen.\n"
    "3. Lärmintensive Arbeiten sind nur werktags von 7 bis 18 Uhr zulässig.\n"
)
ANSWER = {
    "conditions": [
        {
            "number": "1",
            "text": "Vor Baubeginn ist der Standsicherheitsnachweis geprüft vorzulegen.",
            "kind": "suspensive",
            "trigger": "before_start",
            "topic": "other",
            "confidence": 0.93,
            "text_span": "Nr. 1",
            "passage": "Vor Baubeginn ist der Standsicherheitsnachweis geprüft vorzulegen.",
        },
        {
            "number": "3",
            "text": "Lärmintensive Arbeiten sind nur werktags von 7 bis 18 Uhr zulässig.",
            "kind": "obligation",
            "trigger": "ongoing",
            "topic": "noise",
            "confidence": 0.71,
            "text_span": "Nr. 3",
            "passage": "A sentence the notice does not contain.",
        },
        {"number": "9", "text": "Invented.", "kind": "no_such_kind", "confidence": 0.5},
    ]
}


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


async def _code(coro) -> tuple[int, str]:
    with pytest.raises(PermitError) as exc:
        await coro
    return exc.value.status_code, exc.value.code


def _no(reason: str, applies: bool = True) -> dict:
    return {"allowed": False, "applies": applies, "reason": reason}


YES = {"allowed": True, "applies": True, "reason": None}


# ── applications ───────────────────────────────────────────────────────────


async def test_application_flags_follow_the_project_setting_and_the_write_agrees(world: World) -> None:
    p = world.project_id
    rid = await requirement(world, BUILDING)
    aid = await application(world, rid)
    await move(world, aid, "preparing")
    editor = guards.Caller(world.editor, edit=True)
    async with world.factory() as s:
        svc = PermitService(s)
        roadmap = await svc.get_roadmap(p)
        can = await svc.application_can(await svc.repo.get_application(p, aid), roadmap, editor, deep=True)
        assert list(can["transition"]) == list(guards.TARGET_ORDER)
        assert can["transition"]["internal_review"] == _no("internal_review_not_enabled", applies=False)
        assert can["transition"]["submitted"] == YES
        assert can["transition"]["withdrawn"] == YES
        assert can["transition"]["validated"] == _no("invalid_transition", applies=False)
        assert can["edit"] == YES
        assert can["clock"] == _no("clock_not_running")
        assert can["decide"] == _no("manage_required")
        # A reader is offered the same moves as an editor, each one refused for the missing right.
        seen = await svc.application_can(await svc.repo.get_application(p, aid), roadmap, guards.Caller(world.editor))
        assert {t: f["applies"] for t, f in seen["transition"].items()} == {
            t: f["applies"] for t, f in can["transition"].items()
        }
        assert seen["transition"]["submitted"] == _no("edit_required")
        assert [t for t in guards.TARGET_ORDER if seen["transition"][t]["applies"]] == ["submitted", "withdrawn"]
        # The write refuses with the very code the flag gave.
        assert await _code(
            svc.transition_application(p, aid, "internal_review", actor_id=world.editor, can_manage=False)
        ) == (409, "internal_review_not_enabled")
    async with world.factory() as s:
        await PermitService(s).set_roadmap(
            p, tenant_id=None, actor_id=world.manager, settings={"internal_review": True}
        )
        await s.commit()
    async with world.factory() as s:
        svc = PermitService(s)
        roadmap = await svc.get_roadmap(p)
        can = await svc.application_can(await svc.repo.get_application(p, aid), roadmap, editor, deep=True)
        assert can["transition"]["internal_review"] == YES
        assert can["transition"]["submitted"] == _no("internal_review_required", applies=False)
        assert await _code(
            svc.transition_application(p, aid, "submitted", actor_id=world.editor, can_manage=False)
        ) == (409, "internal_review_required")
        await svc.transition_application(p, aid, "internal_review", actor_id=world.editor, can_manage=False)
        await s.commit()
    async with world.factory() as s:
        svc = PermitService(s)
        roadmap = await svc.get_roadmap(p)
        app = await svc.repo.get_application(p, aid)
        # Without an approval route the release is a manager's: the deep flag asks the same check as the write.
        assert (await svc.application_can(app, roadmap, editor, deep=True))["transition"]["submitted"] == _no(
            "release_needs_manager"
        )
        manager = guards.Caller(world.manager, edit=True, manage=True)
        assert (await svc.application_can(app, roadmap, manager, deep=True))["transition"]["submitted"] == YES
        # A list does not run the queries; it says what the state alone allows.
        assert (await svc.application_can(app, roadmap, editor))["transition"]["submitted"] == YES
        assert await _code(
            svc.transition_application(p, aid, "submitted", actor_id=world.editor, can_manage=False)
        ) == (403, "release_needs_manager")


async def test_the_deep_flag_names_an_unmet_dependency(world: World) -> None:
    p = world.project_id
    first = await requirement(world, PRELIMINARY)
    second = await requirement(world, BUILDING)
    await depend(world, second, first)
    aid = await application(world, second)
    await move(world, aid, "preparing")
    editor = guards.Caller(world.editor, edit=True)
    async with world.factory() as s:
        svc = PermitService(s)
        roadmap = await svc.get_roadmap(p)
        can = await svc.application_can(await svc.repo.get_application(p, aid), roadmap, editor, deep=True)
        assert can["transition"]["submitted"] == _no("dependency_not_met")
        assert await _code(
            svc.transition_application(p, aid, "submitted", actor_id=world.editor, can_manage=False)
        ) == (422, "dependency_not_met")


async def test_requirement_decision_and_roadmap_flags(world: World) -> None:
    p = world.project_id
    rid = await requirement(world, BUILDING)
    aid = await file(world, rid)
    out = await decide(world, aid, "granted", conditions_pending=True)
    viewer = guards.Caller(world.editor)
    editor = guards.Caller(world.editor, edit=True)
    manager = guards.Caller(world.manager, edit=True, manage=True)
    async with world.factory() as s:
        svc = PermitService(s)
        apps = await svc.repo.list_applications(p)
        req = await svc.repo.get_requirement(p, rid)
        # The requirement is the manager's: another editor may not change it, and nobody deletes a filed one.
        assert svc.requirement_can(req, apps, editor, False)["edit"] == _no("not_requirement_owner")
        assert svc.requirement_can(req, apps, viewer, False)["edit"] == _no("edit_required")
        mine = svc.requirement_can(req, apps, manager, True)
        assert mine["edit"] == YES
        assert mine["delete"] == {**_no("requirement_has_applications"), "change_request_required": True}
        assert mine["set_dependencies"] == {**YES, "change_request_required": True}
        assert await _code(svc.delete_requirement(p, rid, actor_id=world.manager)) == (
            409,
            "requirement_has_applications",
        )
        decision = out["decision"]
        assert svc.decision_can(decision, decision, editor) == {
            "correct": _no("manage_required"),
            "complete_register": _no("manage_required"),
        }
        assert svc.decision_can(decision, decision, manager) == {"correct": YES, "complete_register": YES}
        await svc.complete_register(p, decision.id, actor_id=world.manager)
        done = await svc.repo.get_decision(p, decision.id)
        assert svc.decision_can(done, done, manager)["complete_register"] == _no(
            "register_already_complete", applies=False
        )
        assert await _code(svc.complete_register(p, decision.id, actor_id=world.manager)) == (
            409,
            "register_already_complete",
        )
        # No governance model: there is no frame document to publish to, and the roadmap says so.
        can = await svc.roadmap_can(p, manager)
        assert can["edit"] == YES and can["escalate"] == YES
        assert can["add_requirement"] == {**YES, "change_request_required": False}
        assert can["publish_frame_document"] == _no("frame_document_not_found")
        assert (await svc.roadmap_can(p, editor))["edit"] == _no("manage_required")
        assert roadmap_out(await svc.get_roadmap(p))["consumed_change_request_ids"] == []


# ── permits and conditions ─────────────────────────────────────────────────


async def _granted(w: World, *conditions: dict, **kw) -> tuple[object, dict]:
    rid = await requirement(w, BUILDING)
    aid = await file(w, rid)
    outcome = "granted_with_conditions" if conditions else "granted"
    out = await decide(w, aid, outcome, conditions=list(conditions), **kw)
    async with w.factory() as s:
        rows = await PermitService(s).repo.conditions_of_permit(w.project_id, out["permit"].id)
    return out["permit"], {c.number: c for c in rows}


async def test_permit_flags_and_the_writes_behind_them(world: World, monkeypatch) -> None:
    p = world.project_id
    permit, _conds = await _granted(world, cond("1"))
    monkeypatch.setattr("app.modules.ai.ai_client.resolve_provider_key_model", lambda *_a, **_k: ("fake", "key", None))
    editor = guards.Caller(world.editor, edit=True)
    manager = guards.Caller(world.manager, edit=True, manage=True)
    async with world.factory() as s:
        svc = PermitService(s)
        (row,) = await svc.permit_rows(p, TODAY, editor)
        can = row["can"]
        assert can["start"] == YES
        assert can["interrupt"] == _no("work_not_started", applies=False)
        assert can["resume"] == _no("work_not_started", applies=False)
        assert can["transition"]["suspended"] == _no("manage_required")
        assert can["add_condition"] == _no("manage_required")
        # The decision was recorded without its notice: there is nothing to read.
        assert can["propose_conditions"] == _no("permit_has_no_document")
        assert await _code(svc.extract_conditions(p, permit.id, actor_id=world.editor)) == (
            409,
            "permit_has_no_document",
        )
        assert await _code(svc.notify_interruption(p, permit.id, TODAY, resumed=False, actor_id=world.editor)) == (
            409,
            "work_not_started",
        )
        await svc.notify_start(p, permit.id, TODAY, actor_id=world.editor)
        await s.commit()
    async with world.factory() as s:
        svc = PermitService(s)
        (row,) = await svc.permit_rows(p, TODAY, manager)
        can = row["can"]
        assert can["start"] == _no("start_already_notified", applies=False)
        assert can["interrupt"] == YES
        assert can["resume"] == _no("work_not_interrupted", applies=False)
        assert can["transition"] == {
            "suspended": YES,
            "in_force": _no("invalid_transition", applies=False),
            "revoked": YES,
            "expired": YES,
            "lapsed": YES,
        }
        assert await _code(svc.notify_start(p, permit.id, TODAY, actor_id=world.editor)) == (
            409,
            "start_already_notified",
        )
        # Rows served without a caller carry no flags (exports, the frame document).
        assert "can" not in (await svc.permit_rows(p, TODAY))[0]


async def test_condition_flags_per_caller_and_the_writes_behind_them(world: World) -> None:
    p = world.project_id
    _permit, conds = await _granted(
        world,
        cond("1", owner_user_id=world.owner_user),
        cond("2", trigger="ongoing", owner_user_id=world.owner_user),
    )
    one = conds["1"].id
    owner = guards.Caller(world.owner_user, edit=True)
    editor = guards.Caller(world.editor, edit=True)
    verifier = guards.Caller(world.verifier, edit=True, manage=True, verify=True)
    async with world.factory() as s:
        svc = PermitService(s)
        rows = {r["number"]: r["can"] for r in await svc.condition_rows(p, TODAY, editor)}
        # Another editor is not the owner; a breach anyone with the right to edit may raise.
        assert rows["1"]["edit"] == _no("not_condition_owner")
        assert rows["1"]["add_evidence"] == _no("not_condition_owner")
        assert rows["1"]["breach"] == _no("condition_not_ongoing", applies=False)
        assert rows["2"]["breach"] == YES
        assert rows["2"]["in_compliance"] == _no("not_condition_owner")
        assert rows["1"]["assign"] == _no("manage_required")
        assert rows["1"]["confirm"] == _no("condition_already_confirmed", applies=False)
        assert rows["1"]["discharge"]["self_certified"] == _no("verify_required")
        assert await _code(svc.update_condition(p, one, {"purpose": ""}, actor_id=world.editor, can_manage=False)) == (
            403,
            "not_condition_owner",
        )
        mine = {r["number"]: r["can"] for r in await svc.condition_rows(p, TODAY, owner)}
        assert mine["1"]["edit"] == YES and mine["1"]["add_evidence"] == YES
        assert mine["1"]["submit_evidence"] == _no("evidence_required")
        assert await _code(svc.submit_evidence(p, one, actor_id=world.owner_user, can_manage=False)) == (
            422,
            "evidence_required",
        )
        await svc.add_evidence(p, one, {"kind": "photo", "note": "Photo"}, actor_id=world.owner_user, can_manage=False)
        await svc.submit_evidence(p, one, actor_id=world.owner_user, can_manage=False)
        await s.commit()
    async with world.factory() as s:
        svc = PermitService(s)
        mine = {
            r["number"]: r["can"]
            for r in await svc.condition_rows(p, TODAY, guards.Caller(world.owner_user, edit=True, verify=True))
        }
        # The owner who certified cannot be the second pair of eyes; the list says so before the click.
        assert mine["1"]["discharge"]["self_certified"] == _no("verifier_is_owner")
        assert mine["1"]["submit_evidence"] == _no("invalid_transition", applies=False)
        theirs = {r["number"]: r["can"] for r in await svc.condition_rows(p, TODAY, verifier)}
        assert theirs["1"]["discharge"]["self_certified"] == YES
        assert theirs["1"]["discharge"]["not_triggered"] == _no("invalid_transition")
        # Once the condition left ``open`` what a gate reads and who owns it are frozen.
        assert theirs["1"]["manage_fields"] == _no("condition_field_frozen")
        assert theirs["1"]["assign"] == _no("condition_field_frozen")
        assert await _code(
            svc.update_condition(p, one, {"kind": "suspensive"}, actor_id=world.verifier, can_manage=True)
        ) == (409, "condition_field_frozen")
        assert theirs["2"]["manage_fields"] == YES
        # The list and the detail read agree.
        c = await svc.repo.get_condition(p, one)
        assert svc.condition_can(c, verifier, 1, await svc._involved(c)) == theirs["1"]
        await svc.discharge(p, one, {"mode": "self_certified"}, actor_id=world.verifier, today=TODAY)
        await s.commit()
    async with world.factory() as s:
        svc = PermitService(s)
        done = {r["number"]: r["can"] for r in await svc.condition_rows(p, TODAY, verifier)}
        assert done["1"]["add_evidence"] == _no("condition_closed", applies=False)
        assert done["1"]["discharge"]["self_certified"] == _no("evidence_not_submitted", applies=False)
        # A limit can be tracked from a condition once; the flag is the write's own refusal.
        assert done["2"]["link_requirement"] == YES
        linked = await svc.repo.get_condition(p, one)
        linked.requirement_id = uuid.uuid4()
        involved = await svc._involved(linked)
        assert svc.condition_can(linked, verifier, 1, involved)["link_requirement"] == _no(
            "condition_already_linked", applies=False
        )
        assert await _code(
            svc.condition_to_requirement(p, one, {"entity": "noise", "attribute": "level"}, actor_id=world.verifier)
        ) == (409, "condition_already_linked")
        await s.rollback()


async def test_linked_document_evidence_carries_title_and_revision_label(world: World) -> None:
    p = world.project_id
    _permit, conds = await _granted(world, cond("1", owner_user_id=world.owner_user))
    cid = conds["1"].id
    async with world.factory() as s:
        container = await add_container(s, p, "STATIK-001")
        revision = await add_revision(s, container, 2, "statik-hash-2")
        svc = PermitService(s)
        await svc.add_evidence(
            p, cid, {"kind": "cde_revision", "ref_id": str(revision)}, actor_id=world.owner_user, can_manage=False
        )
        await svc.add_evidence(p, cid, {"kind": "photo", "note": "Photo"}, actor_id=world.owner_user, can_manage=False)
        await s.commit()
    async with world.factory() as s:
        rows = {r["kind"]: r for r in await PermitService(s).evidence_rows(p, cid)}
    assert (rows["cde_revision"]["ref_title"], rows["cde_revision"]["ref_revision"]) == ("STATIK-001", "P02")
    assert rows["cde_revision"]["content_hash"] == "statik-hash-2"
    assert (rows["photo"]["ref_title"], rows["photo"]["ref_revision"]) == (None, None)


# ── reading the conditions out of the notice (rule 15) ─────────────────────


class _Store:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes:
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]


class _Provider:
    """What stands in for the platform's AI client: it records the call and gives the next answer."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list[dict] = []
        self.answer: object = json.dumps(ANSWER)
        self.configured = True
        monkeypatch.setattr("app.modules.ai.ai_client.resolve_provider_key_model", self._resolve)
        monkeypatch.setattr("app.modules.ai.ai_client.call_ai", self._call)

    def _resolve(self, settings, preferred_model=None):
        if not self.configured:
            raise ValueError("No AI API key configured.")
        return "fake", "key", None

    async def _call(self, provider, api_key, system, prompt, **kw):
        self.calls.append({"provider": provider, "system": system, "prompt": prompt, **kw})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer, 10


@pytest.fixture
def store(monkeypatch) -> _Store:
    fake = _Store()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)
    return fake


async def _noticed(w: World, store: _Store, payload: bytes | None, mime: str = "text/plain", *conditions: dict):
    """A granted permit whose decision carries a notice document with ``payload`` as its file."""
    from app.modules.cde.models import DocumentRevision

    key = f"notices/{uuid.uuid4().hex}"
    async with w.factory() as s:
        container = await add_container(s, w.project_id, f"NOTICE-{uuid.uuid4().hex[:6]}")
        rid = await add_revision(s, container, 2, "notice-hash-2")
        rev = await s.get(DocumentRevision, rid)
        rev.storage_key, rev.mime_type = key, mime
        await s.commit()
    if payload is not None:
        store.files[key] = payload
    permit, _conds = await _granted(w, *conditions, document_revision_id=rid)
    return permit


async def _proposals(w: World, permit_id) -> list:
    async with w.factory() as s:
        rows = await PermitService(s).repo.conditions_of_permit(w.project_id, permit_id)
    return sorted((c for c in rows if not c.confirmed), key=lambda c: c.number)


async def test_extraction_stores_unconfirmed_proposals_once(world: World, store: _Store, monkeypatch) -> None:
    p = world.project_id
    provider = _Provider(monkeypatch)
    permit = await _noticed(world, store, NOTICE.encode("utf-8"), "text/plain", cond("2"))
    editor = guards.Caller(world.editor, edit=True)
    async with world.factory() as s:
        svc = PermitService(s)
        (row,) = await svc.permit_rows(p, TODAY, editor)
        assert row["can"]["propose_conditions"] == YES
        assert (await svc.permit_rows(p, TODAY, guards.Caller(world.editor)))[0]["can"]["propose_conditions"] == _no(
            "edit_required"
        )
        out = await svc.extract_conditions(p, permit.id, actor_id=world.editor)
        await s.commit()
    assert (out["already_known"], out["rejected"], out["document_cut"]) == (0, 1, False)
    # The provider was asked once, with the notice text and the instruction of this module.
    (call,) = provider.calls
    assert "Standsicherheitsnachweis" in call["prompt"] and "JSON" in call["system"]
    first, third = await _proposals(world, permit.id)
    assert (first.number, first.kind, first.trigger, first.source, first.confirmed) == (
        "1",
        "suspensive",
        "before_start",
        "ai_extracted",
        False,
    )
    assert str(first.confidence).startswith("0.93") and first.text_span == "Nr. 1"
    served = condition_out(first)
    assert served["passage"] == "Vor Baubeginn ist der Standsicherheitsnachweis geprüft vorzulegen."
    assert served["text_span"] == "Nr. 1" and served["confirmed"] is False
    # A quotation the notice does not contain is dropped; the proposal itself stays for the reviewer.
    assert (third.number, third.topic, condition_out(third)["passage"]) == ("3", "noise", "")
    assert first.decision_id == permit.decision_id and first.owner_user_id is None
    # Unconfirmed, a proposal counts nowhere: the register of confirmed conditions is as it was.
    async with world.factory() as s:
        svc = PermitService(s)
        assert [r["number"] for r in await svc.register_rows(p, "conditions", TODAY)] == ["2"]
        # Reading the same notice again proposes nothing twice.
        again = await svc.extract_conditions(p, permit.id, actor_id=world.editor)
        await s.commit()
    assert (again["items"], again["already_known"]) == ([], 2)
    assert len(await _proposals(world, permit.id)) == 2
    # A person decides: any editor may correct the unowned proposal, then confirm it.
    async with world.factory() as s:
        svc = PermitService(s)
        await svc.update_condition(
            p, first.id, {"evidence_required": "Prüfbericht"}, actor_id=world.editor, can_manage=False
        )
        await svc.confirm_proposal(p, first.id, True, actor_id=world.editor)
        await svc.confirm_proposal(p, third.id, False, actor_id=world.editor)
        await s.commit()
        assert sorted(r["number"] for r in await svc.register_rows(p, "conditions", TODAY)) == ["1", "2"]


async def test_extraction_without_a_provider_or_a_readable_document(world: World, store: _Store, monkeypatch) -> None:
    p = world.project_id
    provider = _Provider(monkeypatch)
    provider.configured = False
    permit = await _noticed(world, store, NOTICE.encode("utf-8"))
    editor = guards.Caller(world.editor, edit=True)
    async with world.factory() as s:
        svc = PermitService(s)
        (row,) = await svc.permit_rows(p, TODAY, editor)
        assert row["can"]["propose_conditions"] == _no("ai_not_configured")
        assert await _code(svc.extract_conditions(p, permit.id, actor_id=world.editor)) == (409, "ai_not_configured")
    assert provider.calls == []
    provider.configured = True
    # An empty file stands for a scan without a text layer: the extractor returns no text for it.
    blank = await _noticed(world, store, b"   \n ")
    missing = await _noticed(world, store, None)
    async with world.factory() as s:
        svc = PermitService(s)
        assert await _code(svc.extract_conditions(p, blank.id, actor_id=world.editor)) == (422, "document_has_no_text")
        assert await _code(svc.extract_conditions(p, missing.id, actor_id=world.editor)) == (
            422,
            "document_unreadable",
        )
        assert await _code(svc.extract_conditions(p, uuid.uuid4(), actor_id=world.editor)) == (404, "permit_not_found")
    # The provider is never called for a document that cannot be read.
    assert provider.calls == []


async def test_a_failing_or_unreadable_provider_answer_stores_nothing(world: World, store: _Store, monkeypatch) -> None:
    p = world.project_id
    provider = _Provider(monkeypatch)
    permit = await _noticed(world, store, NOTICE.encode("utf-8"))
    for answer, expected in (
        (httpx.ConnectError("no route to host"), (502, "ai_request_failed")),
        (ValueError("Unknown AI provider"), (502, "ai_request_failed")),
        ("I could not find any conditions, sorry.", (502, "ai_response_unreadable")),
        (json.dumps({"summary": "three conditions"}), (502, "ai_response_unreadable")),
    ):
        provider.answer = answer
        async with world.factory() as s:
            assert await _code(PermitService(s).extract_conditions(p, permit.id, actor_id=world.editor)) == expected
            await s.commit()
    assert await _proposals(world, permit.id) == []
    # A notice that states no conditions is an answer, not a failure.
    provider.answer = json.dumps({"conditions": []})
    async with world.factory() as s:
        out = await PermitService(s).extract_conditions(p, permit.id, actor_id=world.editor)
    assert (out["items"], out["rejected"], out["already_known"]) == ([], 0, 0)
