# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - IDOR / tenant scoping for the vision plan-read endpoints (#194).

A stranger must not be able to poll a run, list its proposals, or accept them
on a project they cannot access. Every plan-read endpoint runs
``verify_project_access(run.project_id, user, session)`` first; these tests pin
that the gate is invoked with the run's project and that a denial (404) blocks
the call before any service work happens. Pure-Python: the router handlers are
imported and called directly with stub dependencies.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.takeoff import router as takeoff_router


def _run(project_id: uuid.UUID) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="review",
        project_id=project_id,
        document_id=str(uuid.uuid4()),
        page=1,
        mode="rooms",
        provider="anthropic",
        model_used="claude-sonnet-4-6",
        total_tokens=10,
        cost_usd_estimate=0.01,
        duration_ms=100,
        proposal_count=2,
        accepted_count=0,
        validation_report=None,
        failure_reason=None,
        created_at=None,
    )


class _ServiceStub:
    """Records calls; proves the access gate runs before any data work."""

    def __init__(self, run: Any) -> None:
        self._run = run
        self.list_called = False
        self.accept_called = False

    async def get_plan_read_run(self, _run_id: uuid.UUID) -> Any:
        return self._run

    async def list_plan_read_proposals(self, _run_id: uuid.UUID) -> list[Any]:
        self.list_called = True
        return []

    async def accept_plan_read(self, _run_id: uuid.UUID, **_kw: Any) -> dict:
        self.accept_called = True
        return {"confirmed": 0, "skipped": 0, "blocked": 0, "measurement_ids": []}


def _patch_access_denied(monkeypatch) -> None:
    async def _deny(_project_id, _user_id, _session):  # noqa: ANN001, ANN202
        raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(takeoff_router, "verify_project_access", _deny)


def _patch_access_allowed(monkeypatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def _allow(project_id, _user_id, _session):  # noqa: ANN001, ANN202
        seen["project_id"] = project_id

    monkeypatch.setattr(takeoff_router, "verify_project_access", _allow)
    return seen


@pytest.mark.asyncio
async def test_get_run_denied_for_foreign_project(monkeypatch) -> None:
    owner_project = uuid.uuid4()
    svc = _ServiceStub(_run(owner_project))
    _patch_access_denied(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await takeoff_router.plan_read_get_run(
            run_id=uuid.uuid4(),
            user_id=str(uuid.uuid4()),
            session=SimpleNamespace(),
            service=svc,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_proposals_denied_for_foreign_project_before_listing(monkeypatch) -> None:
    owner_project = uuid.uuid4()
    svc = _ServiceStub(_run(owner_project))
    _patch_access_denied(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await takeoff_router.plan_read_proposals(
            run_id=uuid.uuid4(),
            user_id=str(uuid.uuid4()),
            session=SimpleNamespace(),
            service=svc,
        )
    assert exc.value.status_code == 404
    # The gate fired BEFORE any proposal was listed - no data leaked.
    assert svc.list_called is False


@pytest.mark.asyncio
async def test_accept_denied_for_foreign_project_before_writing(monkeypatch) -> None:
    from app.modules.takeoff.schemas import PlanReadAcceptRequest

    owner_project = uuid.uuid4()
    svc = _ServiceStub(_run(owner_project))
    _patch_access_denied(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await takeoff_router.plan_read_accept(
            run_id=uuid.uuid4(),
            body=PlanReadAcceptRequest(measurement_ids=None, min_confidence=None),
            user_id=str(uuid.uuid4()),
            session=SimpleNamespace(),
            service=svc,
        )
    assert exc.value.status_code == 404
    assert svc.accept_called is False


@pytest.mark.asyncio
async def test_gate_is_called_with_the_runs_project(monkeypatch) -> None:
    """The access gate is checked against the RUN's project, not a client value."""
    owner_project = uuid.uuid4()
    svc = _ServiceStub(_run(owner_project))
    seen = _patch_access_allowed(monkeypatch)

    await takeoff_router.plan_read_get_run(
        run_id=uuid.uuid4(),
        user_id=str(uuid.uuid4()),
        session=SimpleNamespace(),
        service=svc,
    )
    assert seen["project_id"] == owner_project


@pytest.mark.asyncio
async def test_missing_run_is_404(monkeypatch) -> None:
    class _NoRun(_ServiceStub):
        async def get_plan_read_run(self, _run_id: uuid.UUID) -> Any:
            return None

    svc = _NoRun(_run(uuid.uuid4()))
    # The 404 must fire on the missing run before any access check.
    with pytest.raises(HTTPException) as exc:
        await takeoff_router.plan_read_get_run(
            run_id=uuid.uuid4(),
            user_id=str(uuid.uuid4()),
            session=SimpleNamespace(),
            service=svc,
        )
    assert exc.value.status_code == 404
