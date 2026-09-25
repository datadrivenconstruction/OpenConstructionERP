"""The onboarding job handlers must not report a failed load as a success.

``load_cwicr_handler`` and ``install_demo_handler`` used to catch a failed load,
return ``{"skipped": True}`` and let the job runner record ``success``. The
wizard then told the user the country was ready. Now a load that could not run
raises, so the job is recorded ``failed`` with the reason, and a load that ran
reports what it imported and what it had to leave out.

The load itself is replaced: the question here is what the handler does with
each answer, not how the import works (that is covered on PostgreSQL in
``tests/integration/costs/test_cwicr_load_survives_a_long_import.py``).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.costs import router as costs_router
from app.modules.onboarding import handlers


class _Session:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _Session:
    s = _Session()
    monkeypatch.setattr(handlers, "async_session_factory", lambda: s)

    async def _progress(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(handlers, "update_progress", _progress)
    return s


def _job() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _load_returns(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> None:
    async def _load(_db_id: str, _session: Any) -> Any:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(costs_router, "load_cwicr_region", _load)


async def test_a_base_that_cannot_be_found_fails_the_job(session: _Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _load_returns(monkeypatch, HTTPException(status_code=404, detail="CWICR database 'XX' not found."))
    with pytest.raises(handlers.ProvisioningError, match="not found"):
        await handlers.load_cwicr_handler(_job(), {"db_id": "XX"})
    assert session.rolled_back == 1


async def test_an_unexpected_database_error_fails_the_job(session: _Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _load_returns(monkeypatch, RuntimeError("Can't reconnect until invalid transaction is rolled back"))
    with pytest.raises(RuntimeError):
        await handlers.load_cwicr_handler(_job(), {"db_id": "XX"})
    assert session.rolled_back == 1


async def test_a_partial_load_reports_what_was_left_out(session: _Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _load_returns(
        monkeypatch,
        {"imported": 55717, "skipped": 40, "failed": 2, "failed_codes": ["A", "B"], "status": None},
    )

    async def _count(_db_id: str) -> int:
        return 55717

    monkeypatch.setattr(handlers, "_count_region_items", _count)
    result = await handlers.load_cwicr_handler(_job(), {"db_id": "ENG_TORONTO"})
    assert result["imported"] == 55717
    assert result["total_items"] == 55717
    assert result["failed"] == 2
    assert result["failed_codes"] == ["A", "B"]
    assert session.committed == 1


async def test_a_base_that_is_already_loaded_is_complete(session: _Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _load_returns(monkeypatch, {"imported": 0, "total_items": 55719, "status": "already_loaded"})
    result = await handlers.load_cwicr_handler(_job(), {"db_id": "ENG_TORONTO"})
    assert (result["total_items"], result["failed"], result["status"]) == (55719, 0, "already_loaded")


async def test_a_missing_region_is_a_failure_not_a_skip(session: _Session) -> None:
    with pytest.raises(handlers.ProvisioningError):
        await handlers.load_cwicr_handler(_job(), {})


async def test_an_unknown_sample_project_fails_the_job(session: _Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.demo_projects as demo_projects

    async def _install(_session: Any, _demo_id: str) -> dict:
        raise ValueError("Unknown demo 'nope'")

    monkeypatch.setattr(demo_projects, "install_demo_project", _install)
    with pytest.raises(handlers.ProvisioningError, match="Unknown demo"):
        await handlers.install_demo_handler(_job(), {"demo_id": "nope"})
    assert session.rolled_back == 1
