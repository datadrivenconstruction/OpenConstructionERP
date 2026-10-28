"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Rules the second review asked for, each pinned without a database.

The same rules run against PostgreSQL in tests/pg/test_governance_idor.py
(settings and areas frozen while a gate is in review, explicit nulls) and in
tests/pg/test_governance_gate_lifecycle.py (reopen behind a prepared gate).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.project_governance import catalogue as cat
from app.modules.project_governance import evaluator as ev
from app.modules.project_governance import evidence as evd
from app.modules.project_governance import public, service
from app.modules.project_governance.errors import GovernanceError

PID = uuid.uuid4()

# ── C1, C2: nothing that decides who may decide changes while a gate is being decided ──


@pytest.mark.parametrize("status", ["in_review", "on_hold"])
def test_settings_are_frozen_while_a_gate_is_in_review_or_on_hold(status: str) -> None:
    assert ev.settings_freeze_violation(["decided", status, "not_started"]) == "settings_frozen_in_review"


def test_settings_are_free_while_no_gate_is_being_decided() -> None:
    assert ev.settings_freeze_violation(["decided", "in_preparation", "not_started"]) is None
    assert ev.settings_freeze_violation([]) is None


def test_the_new_codes_are_registered() -> None:
    assert {"settings_frozen_in_review", "null_not_allowed"} <= set(ev.ALL_CODES)


# ── C3: preparing the next gate does not lock the previous one ──


def test_a_later_gate_in_preparation_does_not_block_a_reopen() -> None:
    """Anyone who may edit can open the preparation of the next gate, and there is no way back."""
    assert ev.reopen_violation("decided", "Cost overrun", later_gate_statuses=["in_preparation", "not_started"]) is None


@pytest.mark.parametrize("later", ["in_review", "on_hold", "decided"])
def test_a_later_gate_under_decision_still_blocks_a_reopen(later: str) -> None:
    assert ev.reopen_violation("decided", "Cost overrun", later_gate_statuses=["in_preparation", later]) == (
        "later_gate_active"
    )


# ── C5: a provider registered for one area that says nothing about it ──


@pytest.fixture
def registry():
    saved = dict(evd._REGISTRY)
    evd._REGISTRY.clear()
    yield
    evd._REGISTRY.clear()
    evd._REGISTRY.update(saved)


async def _nothing(session: Any, project_id: Any, attempt: Any, area: Any) -> list:
    return []


def _collect(areas: list) -> list:
    attempt = evd.GateAttempt(gate_id=uuid.uuid4(), gate_code="g1", attempt_no=1)
    return asyncio.run(evd.collect_evidence(None, PID, attempt, areas))


def _area(code: str) -> SimpleNamespace:
    return SimpleNamespace(code=code, applicable=True, retired=False)


def test_a_blocking_provider_of_one_area_that_answers_nothing_shows_unknown(registry: None) -> None:
    evd.register_evidence_provider("site", _nothing, name="p_site", blocking=True)
    (item,) = _collect([_area("site"), _area("design")])
    assert (item.area_code, item.provider, item.blocking) == ("site", "p_site", True)
    assert (item.item.code, item.item.state) == ("p_site:no_answer", "unknown")


def test_silence_of_a_wildcard_or_informing_provider_stays_silence(registry: None) -> None:
    """A provider registered for every area answers only for its own; that is not a missing answer."""
    evd.register_evidence_provider("*", _nothing, name="p_all", blocking=True)
    evd.register_evidence_provider("site", _nothing, name="p_info", blocking=False)
    assert _collect([_area("site"), _area("design")]) == []


# ── C6: the read port answers None, it does not raise into ten modules ──


class _Repo:
    def __init__(self, session: Any) -> None:
        pass

    async def get_model(self, project_id: Any) -> Any:
        return SimpleNamespace(catalogue_source="pack", catalogue_id="gone", catalogue_version=1)


@pytest.mark.parametrize(
    "failure",
    [
        GovernanceError("unknown_catalogue", 404),
        GovernanceError("pack_catalogue_invalid", 422),
        cat.InvalidCatalogueError("tenant:x@1", ["schema: broken"]),
    ],
)
def test_a_pin_that_no_longer_resolves_reads_as_no_catalogue(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    async def refuse(*_a: Any, **_k: Any) -> Any:
        raise failure

    monkeypatch.setattr(public, "GovernanceRepository", _Repo)
    monkeypatch.setattr(public, "resolve_catalogue", refuse)
    assert asyncio.run(public.project_catalogue(None, PID)) is None
    assert asyncio.run(public.host_for(None, PID, "permits")) is None
    assert asyncio.run(public.phases_enabling(None, PID, "handover")) == ()


# ── C8: the screen does not offer a go that the route cannot take yet ──


def _step(mode: str, quorum: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(id="final", mode=mode, required_approver_count=quorum)


def _state(user: str, decision: str = "approved", step: str = "final") -> SimpleNamespace:
    return SimpleNamespace(step_id=step, approver_user_id=user, decision=decision)


def test_one_approval_clears_a_step_that_names_its_approver() -> None:
    assert service.approval_would_clear(_step("any"), [], {"me"}, "me") is True
    assert service.approval_would_clear(_step("all"), [], {"me"}, "me") is True


def test_one_approval_clears_a_role_step_in_mode_any() -> None:
    assert service.approval_would_clear(_step("any"), [], None, "me") is True


@pytest.mark.parametrize("mode", ["all", "majority"])
def test_the_first_approval_does_not_clear_a_role_step_that_needs_several(mode: str) -> None:
    assert service.approval_would_clear(_step(mode), [], None, "me") is False
    assert service.approval_would_clear(_step(mode, quorum=5), [_state("a")], None, "me") is False


def test_the_last_missing_approval_clears_a_role_step() -> None:
    assert service.approval_would_clear(_step("all", quorum=2), [_state("a")], None, "me") is True
    # Approvals of an earlier step do not count for the final one.
    assert service.approval_would_clear(_step("all", quorum=2), [_state("a", step="first")], None, "me") is False
    # Approving twice is one approver.
    assert service.approval_would_clear(_step("all", quorum=2), [_state("me")], None, "me") is False


# ── C12, C13, C15: the port says what it exports and leaves a left model out ──


def test_the_pure_views_are_part_of_the_port() -> None:
    views = {"gate_views", "area_views", "document_views", "decision_views", "condition_views", "change_request_views"}
    assert views <= set(public.__all__)


def test_rows_of_a_gate_the_project_left_are_not_listed() -> None:
    live, historic = uuid.uuid4(), uuid.uuid4()
    rows = [
        SimpleNamespace(gate_id=live, n=1),
        SimpleNamespace(gate_id=historic, n=2),
        SimpleNamespace(gate_id=live, n=3),
    ]
    assert [r.n for r in public.rows_of_gates(rows, {live})] == [1, 3]
    # Asking for one gate by id is an explicit question and is answered as asked.
    assert [r.n for r in public.rows_of_gates(rows, {live}, asked=historic)] == [2]


def test_a_gate_linked_to_an_undated_activity_falls_back_to_its_own_date() -> None:
    gate_id = uuid.uuid4()
    catalogue = cat.get_catalogue("neutral")
    row = SimpleNamespace(
        id=gate_id,
        code=catalogue.gates[0].code,
        status="not_started",
        from_phase=catalogue.gates[0].from_phase,
        to_phase=catalogue.gates[0].to_phase,
        last_outcome=None,
        target_date="2026-11-30",
        historic=False,
        sort_order=1,
    )
    (view,) = public.gate_views(catalogue, [row], {gate_id: None})
    assert view.target_date == date(2026, 11, 30)
    (view,) = public.gate_views(catalogue, [row], {gate_id: "2026-12-05"})
    assert view.target_date == date(2026, 12, 5)
