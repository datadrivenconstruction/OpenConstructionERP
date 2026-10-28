# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management decisions that need no database.

Explicit nulls in PATCH bodies, the server-only container marker, the gates
that answer both a request and its ``can`` flag, the approval-route wiring and
the readiness evidence that must not fall silent. Database behaviour of the
same findings lives in ``tests/pg/test_design_release_on_pg.py`` and
``tests/pg/test_design_review_fixes_on_pg.py``.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.design_management import models as m
from app.modules.design_management import schemas as sc
from app.modules.design_management.service import DesignService

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "design_management"

# ── explicit null in a PATCH body ──

_BODY_OF = {
    sc.SetupPatch: m.DesignSetup,
    sc.RoleIn: m.DesignRole,
    sc.ApprovalPointIn: m.DesignApprovalPoint,
    sc.DeliverableIn: m.DesignDeliverable,
    sc.DrawingPatch: m.DesignDrawing,
    sc.DistRuleIn: m.DesignDistributionRule,
    sc.ReleaseIn: m.DesignRelease,
    sc.ReportIn: m.DesignReport,
    sc.PermitIn: m.DesignPermit,
}
#: Body keys stored under another column name.
_COLUMN = {"state": "status"}
#: Body keys the service maps from null to a stored non-null value on purpose.
_NULL_HAS_A_MEANING = {(sc.DistRuleIn, "purpose")}


@pytest.mark.parametrize("schema", list(_BODY_OF), ids=lambda s: s.__name__)
def test_every_body_key_of_a_not_null_column_refuses_null(schema) -> None:
    """A null that would reach a NOT NULL column must be named in ``NOT_NULL``, or the database answers 500."""
    columns = {c.name: c for c in _BODY_OF[schema].__table__.columns}
    for key in schema.model_fields:
        column = columns.get(_COLUMN.get(key, key))
        if column is None or column.nullable or (schema, key) in _NULL_HAS_A_MEANING:
            continue
        assert key in schema.NOT_NULL, f"{schema.__name__}.{key} maps to a NOT NULL column"


@pytest.mark.parametrize("schema", [*_BODY_OF, sc.WbsPatch], ids=lambda s: s.__name__)
def test_an_explicit_null_on_a_not_null_key_is_a_validation_error(schema) -> None:
    assert set(schema.model_fields) >= schema.NOT_NULL
    for key in sorted(schema.NOT_NULL):
        with pytest.raises(ValidationError) as err:
            schema.model_validate({key: None})
        assert key in str(err.value)
    # Leaving the key out is still a valid partial update.
    assert sc.dump(schema.model_validate({})) == {} or schema is sc.ReportIn


def test_a_matrix_rule_purpose_of_null_means_any_purpose() -> None:
    row = m.DesignDistributionRule(purpose="for_review")
    DesignService._fill_rule(row, {"purpose": None})
    assert row.purpose == ""


# ── the frame marker is server-only ──


def test_a_client_cannot_set_a_reserved_container_metadata_key() -> None:
    from app.core import cde_naming as cn
    from app.modules.design_management.service import FRAME_MARKER

    cn.register_server_metadata_key(FRAME_MARKER)
    sent = {FRAME_MARKER: "register", "note": "kept"}
    assert cn.client_metadata(sent) == {"note": "kept"}
    assert cn.client_metadata(None) is None
    with cn.server_write():
        assert cn.client_metadata(sent) == sent
    assert cn.client_metadata(sent) == {"note": "kept"}, "the server context does not leak past its block"


@pytest.mark.asyncio
async def test_the_naming_hook_is_skipped_only_inside_a_server_write() -> None:
    from fastapi import HTTPException

    from app.core import cde_naming as cn

    async def refuse(_session, _project_id, code, _parts):
        return [{"code": "numbering_invalid", "field": None, "value": code}]

    # Only this test's checker: another module's checker registered earlier in the run would be
    # called with the missing session and fail for a reason that has nothing to do with the hook.
    others = dict(cn._CHECKERS)
    cn._CHECKERS.clear()
    cn.register_container_code_checker("test.refuse_everything", refuse)
    try:
        with pytest.raises(HTTPException) as err:
            await cn.check_container_code(None, uuid.uuid4(), "DESIGN-FRAME-REGISTER", {})
        assert err.value.status_code == 422
        with cn.server_write():
            await cn.check_container_code(None, uuid.uuid4(), "DESIGN-FRAME-REGISTER", {})
    finally:
        cn._CHECKERS.clear()
        cn._CHECKERS.update(others)


# ── gates that answer the request and the ``can`` flag alike ──


def _release(**kw):
    base = {"status": "ready", "approval_status": "approved", "content_changed_by": uuid.uuid4(), "approved_by": None}
    return SimpleNamespace(**{**base, **kw})


def test_a_release_is_issued_only_when_ready_permitted_and_approved() -> None:
    actor = uuid.uuid4()
    four_eyes, off = SimpleNamespace(four_eyes_release=True), SimpleNamespace(four_eyes_release=False)
    gate = DesignService._issue_gate
    assert gate(_release(), four_eyes, actor_id=actor, may_release=True) == {
        "allowed": True,
        "applies": True,
        "reason": None,
    }
    assert gate(_release(), four_eyes, actor_id=actor, may_release=False)["reason"] == "forbidden"
    assert gate(_release(status="draft"), four_eyes, actor_id=actor, may_release=True)["reason"] == "release_not_ready"
    for state in ("none", "pending", "rejected"):
        pending = _release(approval_status=state)
        assert gate(pending, four_eyes, actor_id=actor, may_release=True)["reason"] == "release_not_approved"
        assert gate(pending, off, actor_id=actor, may_release=True)["allowed"], "four-eyes off needs no approval"


def test_whoever_last_changed_a_release_cannot_approve_it() -> None:
    changer, other = uuid.uuid4(), uuid.uuid4()
    waiting = _release(approval_status="pending", content_changed_by=changer)
    assert DesignService._approve_gate(waiting, changer) == "release_four_eyes"
    assert DesignService._approve_gate(waiting, None) == "release_four_eyes"
    assert DesignService._approve_gate(waiting, other) is None
    assert DesignService._approve_gate(_release(), other) == "release_not_pending"


def _report(**kw):
    base = {
        "status": "required",
        "author_role_id": None,
        "checker_role_id": None,
        "external_check": False,
        "review_cycle_id": None,
        "required": True,
    }
    return SimpleNamespace(**{**base, **kw})


def test_report_fields_a_gate_reads_need_manage_and_freeze_on_submission() -> None:
    svc = DesignService(None)
    change = {"external_check": True}
    assert svc.report_gate_gate(_report(), {"title": "t"}, may_manage=False) is None
    assert svc.report_gate_gate(_report(), {"external_check": False}, may_manage=False) is None, "no change"
    assert svc.report_gate_gate(_report(), change, may_manage=False) == "manage_required"
    assert svc.report_gate_gate(_report(), change, may_manage=True) is None
    submitted = _report(status="submitted", author_role_id=uuid.uuid4())
    for data in (change, {"required": False}, {"author_role_id": None}, {"author_role_id": str(uuid.uuid4())}):
        assert svc.report_gate_gate(submitted, data, may_manage=True) == "report_fields_frozen", data
    # An empty checker or cycle link may still be filled in while the check runs.
    assert svc.report_gate_gate(submitted, {"review_cycle_id": str(uuid.uuid4())}, may_manage=True) is None
    assert svc.report_can(submitted, may_manage=True)["edit_gate_fields"]["reason"] == "report_fields_frozen"
    assert svc.report_can(_report(), may_manage=False)["edit_gate_fields"]["reason"] == "manage_required"
    assert svc.report_can(_report(), may_manage=True)["edit_gate_fields"] == {
        "allowed": True,
        "applies": True,
        "reason": None,
    }


def test_an_authority_decision_is_typed_only_without_a_cycle_or_for_a_partial_approval() -> None:
    gate = DesignService.permit_decision_gate
    loose = SimpleNamespace(review_cycle_id=None, status="submitted")
    linked = SimpleNamespace(review_cycle_id=uuid.uuid4(), status="under_review")
    assert gate(loose, "under_review", may_manage=True) is None
    assert gate(loose, "approved", may_manage=False) == "manage_required"
    assert gate(linked, "approved", may_manage=True) == "permit_state_read_from_cycle"
    assert gate(linked, "partially_approved", may_manage=True) is None
    assert gate(linked, "partially_approved", may_manage=False) == "manage_required"
    partial = SimpleNamespace(review_cycle_id=uuid.uuid4(), status="partially_approved")
    assert gate(partial, "approved", may_manage=True) is None


def test_partially_approved_is_reachable_and_leads_to_approved() -> None:
    from app.modules.design_management import fsm

    assert "partially_approved" in fsm.PERMIT_FSM.allowed_from("under_review")
    assert "approved" in fsm.PERMIT_FSM.allowed_from("partially_approved")
    assert "partially_approved" in DesignService.PERMIT_DECISIONS


# ── approval route wiring ──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "method"),
    [("design_approval_point", "apply_approval_verdict"), ("design_release", "apply_release_verdict")],
)
@pytest.mark.parametrize("decision", ["approved", "rejected", "cancelled"])
async def test_a_route_outcome_reaches_the_row_it_targets(monkeypatch, kind: str, method: str, decision: str) -> None:
    from app.modules.design_management import events

    calls: list[tuple] = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def commit(self):
            calls.append(("commit",))

    async def record(self, target_id, instance_id, *, decision, decided_by):
        calls.append((method, target_id, instance_id, decision, decided_by))
        return True

    monkeypatch.setattr(DesignService, method, record)
    target, instance, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    data = {"target_kind": kind, "target_id": str(target), "instance_id": str(instance), "decided_by": str(user)}
    await events.handle_route_event(data, decision=decision, session_factory=_Session)
    assert calls == [(method, target, instance, decision, str(user)), ("commit",)]


def test_the_cancelled_event_is_subscribed() -> None:
    source = (_MODULE / "events.py").read_text(encoding="utf-8")
    for name in ("completed", "rejected", "cancelled"):
        assert f'subscribe_once("approval_routes.instance.{name}"' in source
    assert "logger.debug" not in source, "a verdict that was not applied must be visible in the log"


@pytest.mark.asyncio
async def test_registering_again_after_the_bus_was_emptied_wires_the_handlers_again(monkeypatch) -> None:
    """A test or a restart may empty the bus; the next startup must subscribe again, exactly once."""
    from app.core.events import Event, event_bus
    from app.modules.design_management import events

    seen: list[tuple[dict, str]] = []

    async def record(data, *, decision, session_factory=None):
        seen.append((data, decision))

    monkeypatch.setattr(events, "handle_route_event", record)
    names = [f"approval_routes.instance.{n}" for n in ("completed", "rejected", "cancelled")]
    saved = {n: list(event_bus._handlers.get(n, [])) for n in names}
    try:
        events.register_design_subscribers()
        for n in names:
            event_bus._handlers[n] = []  # what a bus reset between tests leaves behind
        events.register_design_subscribers()
        events.register_design_subscribers()
        for n in names:
            ours = [h for h in event_bus._handlers[n] if getattr(h, "__module__", "") == events.__name__]
            assert len(ours) == 1, n
            await ours[0](Event(name=n, data={"target_kind": "design_release"}))
    finally:
        for n, handlers in saved.items():
            event_bus._handlers[n] = handlers
    assert [d for _data, d in seen] == ["approved", "rejected", "cancelled"]


@pytest.mark.asyncio
async def test_a_failed_verdict_is_logged_at_warning(monkeypatch, caplog) -> None:
    from app.modules.design_management import events

    class _Broken:
        async def __aenter__(self):
            raise RuntimeError("database gone")

        async def __aexit__(self, *_a):
            return False

    data = {"target_kind": "design_release", "target_id": str(uuid.uuid4())}
    with caplog.at_level("WARNING", logger=events.logger.name):
        await events.handle_route_event(data, decision="approved", session_factory=_Broken)
    assert [r.levelname for r in caplog.records] == ["WARNING"]


# ── readiness evidence never falls silent ──


async def _evidence(monkeypatch, *, setup, host, area: str, gate=None, document: bool = True):
    """Run the provider on a project whose areas are ``a`` and ``b``, read through module 1's port."""
    from app.modules.design_management import evidence, hosting
    from app.modules.design_management.hosting import Host
    from app.modules.project_governance import public

    gate_id = uuid.uuid4()

    async def areas(_session, _project_id):
        return (SimpleNamespace(code="b"), SimpleNamespace(code="a"))

    async def documents(_session, _project_id):
        return (SimpleNamespace(code="frame", area_code=host),) if document else ()

    async def gates(_session, _project_id):
        return (SimpleNamespace(id=gate_id, from_phase=gate.from_phase),) if gate is not None else ()

    monkeypatch.setattr(public, "project_areas", areas)
    monkeypatch.setattr(public, "project_documents", documents)
    monkeypatch.setattr(public, "project_gates", gates)

    async def get_setup(self, _project_id):
        return setup

    async def host_code(_session, _project_id):
        return Host(area_code=host, doc_type="frame") if host else None

    async def readiness(self, _project_id, _phase):
        from app.modules.design_management.rules import PhaseBlockers

        return PhaseBlockers(["DL-1"], [], 0)

    monkeypatch.setattr(DesignService, "get_setup", get_setup)
    monkeypatch.setattr(DesignService, "readiness", readiness)
    monkeypatch.setattr(hosting, "design_host", host_code)
    attempt = SimpleNamespace(gate_id=gate_id)
    return await evidence.phase_readiness(object(), uuid.uuid4(), attempt, SimpleNamespace(code=area))


@pytest.mark.asyncio
async def test_without_a_design_setup_the_provider_has_nothing_to_say(monkeypatch) -> None:
    assert await _evidence(monkeypatch, setup=None, host="b", area="b") == []


@pytest.mark.asyncio
async def test_design_data_without_a_hosting_area_is_unknown_once_not_silent(monkeypatch) -> None:
    items = await _evidence(monkeypatch, setup=object(), host=None, area="a")
    assert [(i.code, i.state, i.detail) for i in items] == [
        ("design_readiness:no_host_area", "unknown", "no_host_area")
    ]
    assert await _evidence(monkeypatch, setup=object(), host=None, area="b") == [], "reported on one area only"


@pytest.mark.asyncio
async def test_a_gate_that_closes_no_phase_is_unknown_not_silent(monkeypatch) -> None:
    gate = SimpleNamespace(from_phase="")
    items = await _evidence(monkeypatch, setup=object(), host="b", area="b", gate=gate)
    assert [(i.code, i.state) for i in items] == [("design_readiness:no_phase", "unknown")]
    assert await _evidence(monkeypatch, setup=object(), host="b", area="a", gate=gate) == []


@pytest.mark.asyncio
async def test_a_host_without_its_document_row_is_unknown(monkeypatch) -> None:
    """A project pinned before the model named the design frame document."""
    items = await _evidence(monkeypatch, setup=object(), host="b", area="b", document=False)
    assert [(i.code, i.state) for i in items] == [("design_readiness:no_host_document", "unknown")]


@pytest.mark.asyncio
async def test_open_deliverables_are_not_met_on_the_hosting_area(monkeypatch) -> None:
    gate = SimpleNamespace(from_phase="lph3")
    items = await _evidence(monkeypatch, setup=object(), host="b", area="b", gate=gate)
    assert {i.code: i.state for i in items} == {
        "design_deliverables:lph3": "not_met",
        "design_reports:lph3": "met",
        "design_major_comments:lph3": "met",
    }


# ── no national or governance code in module code ──


def test_the_demo_seed_tests_no_scheme_id_and_names_no_national_code() -> None:
    """Finding 21: codes come from the pinned scheme's data, never from a comparison in code."""
    tree = ast.parse((_MODULE / "seed.py").read_text(encoding="utf-8"))
    literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    shipped = {p.stem for p in (_MODULE / "catalogues" / "drawing_numbering").glob("*.json")}
    assert not literals & shipped, "a scheme id is compared or named in seed code"
    assert not literals & {"AR", "TW", "HL", "GR", "SC", "LP", "AN", "EG", "UG", "LPH5"}


def test_no_governance_area_or_phase_code_is_matched_in_module_code() -> None:
    from app.modules.project_governance import catalogue as cat

    codes: set[str] = set()
    for cid in cat.CATALOGUE_IDS:
        c = cat.get_catalogue(cid)
        codes |= {a.code for a in c.areas} | {p.code for p in c.phases} | {g.code for g in c.gates}
    # Only compound identifiers (``scope_quality``, ``lph3``, ``lph2_to_lph3``). A code that is also an
    # ordinary word (``design``, ``tender``) cannot be told from vocabulary by a literal scan; those are
    # covered by resolving the host and the phases through the catalogue everywhere they are needed.
    codes = {c for c in codes if "_" in c or any(ch.isdigit() for ch in c)}
    assert codes, "the shipped catalogues carry compound codes to look for"
    for path in _MODULE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not literals & codes, (path.name, sorted(literals & codes))


# ── can flags ──


def test_a_can_flag_says_whether_the_action_exists_and_why_it_is_refused() -> None:
    from app.modules.design_management.errors import conflict
    from app.modules.design_management.service import _flag

    assert _flag() == {"allowed": True, "applies": True, "reason": None}
    assert _flag(conflict("review_comments_open")) == {
        "allowed": False,
        "applies": True,
        "reason": "review_comments_open",
    }
    assert _flag("forbidden") == {"allowed": False, "applies": True, "reason": "forbidden"}
    assert _flag(applies=False) == {"allowed": False, "applies": False, "reason": None}


@pytest.mark.asyncio
async def test_rows_without_a_typed_state_list_no_transition() -> None:
    """A schedule line's state is computed; a comment's moves are exactly those of its state machine."""
    from app.modules.design_management import fsm
    from app.modules.design_management.models import DesignDeliverable, DesignReviewComment
    from app.modules.design_management.service import Caller

    svc = DesignService(None)  # type: ignore[arg-type]
    editor = Caller(actor_id=uuid.uuid4(), edit=True, manage=False, release=False)
    viewer = Caller(actor_id=uuid.uuid4(), edit=False, manage=False, release=False)
    line = await svc.capabilities(DesignDeliverable(waived=False), editor)
    assert line["transitions"] == {} and line["waive"]["allowed"] and not line["unwaive"]["applies"]
    for state in fsm.COMMENT_STATES:
        can = await svc.capabilities(DesignReviewComment(status=state), editor)
        assert sorted(can["transitions"]) == fsm.COMMENT_FSM.allowed_from(state), state
        assert all(f["allowed"] for f in can["transitions"].values())
        refused = await svc.capabilities(DesignReviewComment(status=state), viewer)
        assert all(f["reason"] == "forbidden" and f["applies"] for f in refused["transitions"].values())
    assert await svc.capabilities(object(), editor) == {}


def test_the_caller_is_built_from_the_permission_registry_not_from_a_role_name() -> None:
    from app.modules.design_management import router
    from app.modules.design_management.permissions import register_design_permissions

    register_design_permissions()
    uid = str(uuid.uuid4())
    viewer = router._caller(uid, {"role": "viewer"})
    editor = router._caller(uid, {"role": "editor"})
    manager = router._caller(uid, {"role": "manager"})
    assert (viewer.edit, viewer.manage, viewer.release) == (False, False, False)
    assert editor.edit and not editor.manage
    assert manager.edit and manager.manage and manager.release
    assert str(manager.actor_id) == uid


def test_every_record_route_answers_through_the_function_that_adds_can() -> None:
    """A route that returns a stateful record with the bare serializer would ship it without ``can``."""
    import ast
    from pathlib import Path

    from app.modules.design_management import router

    tree = ast.parse(Path(router.__file__).read_text(encoding="utf-8"))
    bare = {
        "roles", "ap", "dl", "rev", "comment", "rpt", "permit", "rel",
    }  # fmt: skip
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef) or fn.name.split("_")[0] not in bare:
            continue
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_out":
                offenders.append(fn.name)
    assert offenders == [], offenders


def test_the_readiness_evidence_link_opens_the_design_page_the_web_app_declares() -> None:
    from app.modules.design_management import evidence

    evidence.register_gate_evidence()
    route = "/projects/{project_id}/design"
    app_routes = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "App.tsx").read_text("utf-8")
    assert 'path="/projects/:projectId/design"' in app_routes, "the registered path must be a declared route"
    from app.modules.project_governance.evidence import evidence_link_href

    pid = uuid.uuid4()
    assert evidence_link_href(evidence.LINK_KIND, str(pid), pid) == route.format(project_id=pid)
