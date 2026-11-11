"""ChangeOrderService guards that need no database: transitions, four-eyes, currency."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.changeorders.service import VALID_TRANSITIONS, ChangeOrderService


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Session:
    def __init__(self, project=None, boom=False):
        self.project = project
        self.boom = boom

    async def execute(self, stmt):
        if self.boom:
            raise RuntimeError("no db")
        return _Result(self.project)


def _svc(**kw) -> ChangeOrderService:
    return ChangeOrderService(_Session(**kw))  # type: ignore[arg-type]


def test_transition_table_is_closed_and_executed_is_terminal():
    known = set(VALID_TRANSITIONS)
    for targets in VALID_TRANSITIONS.values():
        assert set(targets) <= known
    assert VALID_TRANSITIONS["executed"] == []
    assert "executed" not in VALID_TRANSITIONS["draft"]


@pytest.mark.parametrize(
    ("current", "target"),
    [("draft", "approved"), ("draft", "executed"), ("approved", "draft"), ("executed", "draft"), ("ghost", "draft")],
)
def test_illegal_transition_is_400(current, target):
    with pytest.raises(HTTPException) as exc:
        _svc()._validate_transition(current, target)
    assert exc.value.status_code == 400
    assert current in exc.value.detail


def test_every_listed_transition_is_accepted():
    svc = _svc()
    for current, targets in VALID_TRANSITIONS.items():
        for target in targets:
            svc._validate_transition(current, target)


@pytest.mark.asyncio
async def test_submitter_is_blocked_from_deciding_but_others_pass():
    submitter = uuid.uuid4()
    order = SimpleNamespace(submitted_by=str(submitter))
    with pytest.raises(HTTPException) as exc:
        await _svc()._assert_not_self_approval(order, str(submitter), "approve")
    assert exc.value.status_code == 403
    assert "approve" in exc.value.detail
    await _svc()._assert_not_self_approval(order, str(uuid.uuid4()), "approve")
    await _svc()._assert_not_self_approval(SimpleNamespace(submitted_by=None), str(submitter), "reject")


@pytest.mark.asyncio
async def test_currency_prefers_explicit_then_project_never_eur():
    pid = uuid.uuid4()
    assert await _svc(project=SimpleNamespace(currency="CHF"))._resolve_currency(pid, " usd ") == "usd"
    assert await _svc(project=SimpleNamespace(currency="CHF"))._resolve_currency(pid, None) == "CHF"
    assert await _svc(project=SimpleNamespace(currency=""))._resolve_currency(pid, "") == ""
    assert await _svc(project=None)._resolve_currency(pid, None) == ""


@pytest.mark.asyncio
async def test_currency_lookup_failure_falls_back_to_blank():
    assert await _svc(boom=True)._resolve_currency(uuid.uuid4(), None) == ""
