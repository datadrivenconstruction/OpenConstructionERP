"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The read port other modules use: listings as small frozen read models."""

from __future__ import annotations

import dataclasses
import uuid
from types import SimpleNamespace

import pytest

from app.modules.project_governance import catalogue as cat
from app.modules.project_governance import public


def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _gate(n: int, code: str, order: int, status: str = "not_started", outcome: str = "") -> SimpleNamespace:
    c = cat.get_catalogue("neutral").gate(code)
    return SimpleNamespace(
        id=_id(n),
        code=code,
        sort_order=order,
        status=status,
        from_phase=c.from_phase,
        to_phase=c.to_phase,
        last_outcome=outcome,
    )


def _area(n: int, code: str, order: int, **kw) -> SimpleNamespace:
    base = {"name_override": "", "applicable": True, "owner_user_id": None, "deputy_user_id": None}
    return SimpleNamespace(id=_id(n), code=code, sort_order=order, **{**base, **kw})


def _doc(n: int, doc_type: str, area: int, **kw) -> SimpleNamespace:
    base = {"status": "draft", "required_at_gates": [], "read_only": False}
    return SimpleNamespace(id=_id(n), doc_type=doc_type, area_id=_id(area), **{**base, **kw})


def test_gate_views_are_ordered_and_labelled() -> None:
    neutral = cat.get_catalogue("neutral")
    rows = [_gate(2, "brief_to_concept", 2), _gate(1, "strategy_to_brief", 1, "decided", "go")]
    views = public.gate_views(neutral, rows)
    assert [(v.code, v.order, v.status, v.last_outcome) for v in views] == [
        ("strategy_to_brief", 1, "decided", "go"),
        ("brief_to_concept", 2, "not_started", ""),
    ]
    assert (views[0].from_phase, views[0].to_phase) == ("strategy", "brief")
    assert views[0].label == {"key": "governance.catalogue.neutral.gate.strategy_to_brief", "text": None}
    assert views[0].id == _id(1)


def test_area_views_carry_owner_and_applicability() -> None:
    neutral = cat.get_catalogue("neutral")
    rows = [
        _area(2, "scope", 2, applicable=False),
        _area(1, "integration", 1, owner_user_id=_id(7), name_override="Steering"),
    ]
    views = public.area_views(neutral, rows)
    assert [(v.code, v.order, v.status) for v in views] == [
        ("integration", 1, "applicable"),
        ("scope", 2, "not_applicable"),
    ]
    assert (views[0].owner_user_id, views[0].deputy_user_id, views[0].name_override) == (_id(7), None, "Steering")
    assert views[1].label["key"] == "governance.catalogue.neutral.area.scope"


def test_document_views_follow_area_order_and_drop_documents_of_retired_areas() -> None:
    neutral = cat.get_catalogue("neutral")
    areas = public.area_views(neutral, [_area(1, "integration", 1), _area(2, "scope", 2)])
    rows = [
        _doc(11, "scope_statement", 2, status="binding", required_at_gates=["design_to_approval"], read_only=True),
        _doc(12, "requirements_brief", 2),
        _doc(13, "project_handbook", 1),
        _doc(14, "risk_register", 99),
    ]
    views = public.document_views(neutral, rows, areas)
    assert [(v.code, v.area_code, v.order) for v in views] == [
        ("project_handbook", "integration", 1),
        ("requirements_brief", "scope", 2),
        ("scope_statement", "scope", 3),
    ]
    last = views[-1]
    assert (last.status, last.required_at_gates, last.read_only) == ("binding", ("design_to_approval",), True)
    assert last.label["key"] == "governance.catalogue.neutral.doc.scope_statement"


def test_a_code_the_catalogue_does_not_know_has_an_empty_label() -> None:
    views = public.area_views(cat.get_catalogue("neutral"), [_area(1, "left_over", 1)])
    assert views[0].label == {"key": None, "text": None}


@pytest.mark.parametrize("view", [public.GateView, public.AreaView, public.DocumentView, public.Host])
def test_read_models_are_frozen(view: type) -> None:
    assert dataclasses.is_dataclass(view) and view.__dataclass_params__.frozen


@pytest.mark.parametrize("view", [public.GateView, public.AreaView, public.DocumentView])
def test_every_listing_model_has_the_common_fields(view: type) -> None:
    names = {f.name for f in dataclasses.fields(view)}
    assert {"id", "code", "label", "order", "status"} <= names


def test_the_port_exports_its_listing_calls() -> None:
    assert {"project_gates", "project_areas", "project_documents"} <= set(public.__all__)


def test_gate_views_read_the_planned_day_from_the_schedule_when_given() -> None:
    from datetime import date

    neutral = cat.get_catalogue("neutral")
    own = _gate(1, "strategy_to_brief", 1)
    own.target_date = "2027-03-01"
    linked = _gate(2, "brief_to_concept", 2)
    linked.target_date = ""
    unplanned = _gate(3, "concept_to_design", 3)
    unplanned.target_date = ""
    views = public.gate_views(neutral, [own, linked, unplanned], {_id(2): "2027-06-15", _id(3): ""})
    assert [v.target_date for v in views] == [date(2027, 3, 1), date(2027, 6, 15), None]


def test_document_views_carry_the_pointers_a_module_files_against() -> None:
    neutral = cat.get_catalogue("neutral")
    areas = public.area_views(neutral, [_area(1, "scope", 1)])
    row = _doc(11, "scope_statement", 1, container_id=_id(50), bound_revision_id=_id(51), approved_gate_id=_id(52))
    (view,) = public.document_views(neutral, [row], areas)
    assert (view.container_id, view.bound_revision_id, view.approved_gate_id) == (_id(50), _id(51), _id(52))
    (bare,) = public.document_views(neutral, [_doc(12, "requirements_brief", 1)], areas)
    assert (bare.container_id, bare.bound_revision_id, bare.approved_gate_id) == (None, None, None)


def test_decision_views_are_oldest_first() -> None:
    from datetime import UTC, datetime

    def row(n: int, day: int, outcome: str, attempt: int) -> SimpleNamespace:
        return SimpleNamespace(
            id=_id(n),
            gate_id=_id(1),
            gate_code="strategy_to_brief",
            attempt_no=attempt,
            outcome=outcome,
            decided_by=_id(9),
            decided_at=datetime(2026, 10, day, tzinfo=UTC),
        )

    views = public.decision_views([row(2, 12, "go", 2), row(1, 5, "recycle", 1)])
    assert [(v.id, v.outcome, v.attempt_no) for v in views] == [(_id(1), "recycle", 1), (_id(2), "go", 2)]
    assert views[0].decided_by == _id(9) and views[0].gate_code == "strategy_to_brief"


def _condition(n: int, status: str, due: str, **kw) -> SimpleNamespace:
    base = {
        "decision_id": _id(100),
        "gate_id": _id(1),
        "gate_code": "strategy_to_brief",
        "text": f"condition {n}",
        "severity": "essential",
        "area_code": None,
        "document_type": None,
        "owner_user_id": _id(7),
        "cleared_at": None,
    }
    return SimpleNamespace(id=_id(n), status=status, due_date=due, **{**base, **kw})


def test_condition_views_read_overdue_from_the_day_given_not_from_the_stored_status() -> None:
    from datetime import date

    rows = [
        _condition(1, "open", "2026-10-01"),
        _condition(2, "open", "2026-12-01"),
        _condition(3, "cleared", "2026-09-01"),
        _condition(4, "open", ""),
        _condition(5, "waived", "2026-08-01"),
    ]
    views = public.condition_views(rows, date(2026, 10, 12))
    assert {v.id: v.status for v in views} == {
        _id(1): "overdue",
        _id(2): "open",
        _id(3): "cleared",
        _id(4): "open",
        _id(5): "waived",
    }
    # Earliest due date first, undated last.
    assert [v.id for v in views] == [_id(5), _id(3), _id(1), _id(2), _id(4)]
    assert views[2].due_date == date(2026, 10, 1) and views[-1].due_date is None
    # The same rows a day before the first one fell due.
    assert {v.status for v in public.condition_views(rows[:1], date(2026, 10, 1))} == {"open"}


def test_change_request_views_say_which_is_open() -> None:
    def row(n: int, status: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=_id(n),
            document_id=_id(11),
            status=status,
            reason="newer file",
            proposed_revision_id=_id(60 + n),
            requested_by=_id(7),
            decided_at=None,
            decided_by=None if status == "submitted" else _id(8),
        )

    views = public.change_request_views([row(1, "rejected"), row(2, "submitted"), row(3, "approved")])
    assert [(v.id, v.open) for v in views] == [(_id(1), False), (_id(2), True), (_id(3), False)]
    assert views[1].proposed_revision_id == _id(62)
    assert [(v.requested_by, v.decided_by) for v in views] == [(_id(7), _id(8)), (_id(7), None), (_id(7), _id(8))]


def test_the_port_exports_its_second_round() -> None:
    assert {"project_gate_decisions", "project_conditions", "project_change_requests"} <= set(public.__all__)
    for name in public.__all__:
        assert hasattr(public, name), name


def test_the_membership_read_is_the_rule_governance_itself_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.modules.project_governance.service import GovernanceService

    asked: list[tuple] = []

    async def _rule(self, project_id, user_id):
        asked.append((self.session, project_id, user_id))
        return "the answer of the service"

    monkeypatch.setattr(GovernanceService, "user_can_access_project", _rule)
    session, project_id, user_id = object(), uuid.uuid4(), uuid.uuid4()
    assert "user_can_access_project" in public.__all__
    answer = asyncio.run(public.user_can_access_project(session, project_id, user_id))
    assert answer == "the answer of the service"
    assert asked == [(session, project_id, user_id)]


# ── control settings and the bound content hash ──


def test_control_settings_of_a_project_with_a_model() -> None:
    row = SimpleNamespace(four_eyes=False, current_phase="design", stopped=True)
    assert public.control_settings(row) == public.ControlSettings(
        has_model=True, four_eyes=False, current_phase="design", stopped=True
    )


def test_a_project_without_a_model_is_under_four_eyes() -> None:
    """The control is on until somebody with the authority switches it off; no model is not that."""
    assert public.control_settings(None) == public.ControlSettings(
        has_model=False, four_eyes=True, current_phase=None, stopped=False
    )


def test_the_document_view_carries_the_hash_of_the_bound_revision() -> None:
    neutral = cat.get_catalogue("neutral")
    areas = public.area_views(neutral, [_area(2, "scope", 2)])
    bound = _doc(11, "scope_statement", 2, status="binding", bound_content_hash="ab" * 32)
    draft = _doc(12, "requirements_brief", 2)
    views = {v.code: v for v in public.document_views(neutral, [bound, draft], areas)}
    assert views["scope_statement"].bound_content_hash == "ab" * 32
    assert views["requirements_brief"].bound_content_hash is None


def test_the_control_read_is_exported() -> None:
    assert {"ControlSettings", "control_settings", "project_controls"} <= set(public.__all__)
