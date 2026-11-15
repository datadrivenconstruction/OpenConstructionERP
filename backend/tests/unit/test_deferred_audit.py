"""``deferred_audit``: the caller's work is flushed outside the audit savepoint, and dropped rows are logged."""

from __future__ import annotations

import logging

import pytest

from app.core.audit_log import deferred_audit, log_activity


class _Savepoint:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.calls.append("savepoint")

    async def __aexit__(self, exc_type, *_exc) -> bool:
        self.session.calls.append("rollback_savepoint" if exc_type else "release_savepoint")
        return False


class _Session:
    def __init__(self, fail_audit_insert: bool = False) -> None:
        self.info: dict = {}
        self.calls: list[str] = []
        self.fail_audit_insert = fail_audit_insert
        self.in_savepoint = False

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self)

    def add(self, _obj) -> None:
        self.calls.append("add")

    def add_all(self, objs) -> None:
        self.calls.append(f"add_all:{len(list(objs))}")

    async def flush(self) -> None:
        inside = self.calls.count("savepoint") > 0
        self.calls.append("flush_audit" if inside else "flush_caller")
        if inside and self.fail_audit_insert:
            raise RuntimeError("audit insert failed")


async def _two_rows(session: _Session) -> None:
    for action in ("create", "update"):
        await log_activity(session, actor_id=None, entity_type="thing", entity_id=None, action=action)  # type: ignore[arg-type]


async def test_caller_work_is_flushed_before_the_savepoint() -> None:
    session = _Session()
    async with deferred_audit(session):  # type: ignore[arg-type]
        await _two_rows(session)
    assert session.calls == ["flush_caller", "savepoint", "add_all:2", "flush_audit", "release_savepoint"]


async def test_a_failed_audit_insert_rolls_back_only_the_savepoint(caplog: pytest.LogCaptureFixture) -> None:
    session = _Session(fail_audit_insert=True)
    with caplog.at_level(logging.ERROR, logger="app.core.audit_log"):
        async with deferred_audit(session):  # type: ignore[arg-type]
            await _two_rows(session)
    assert session.calls[0] == "flush_caller"
    assert session.calls[-1] == "rollback_savepoint"
    assert "dropped 2 deferred audit rows" in caplog.text


async def test_a_failing_body_logs_the_dropped_rows(caplog: pytest.LogCaptureFixture) -> None:
    session = _Session()

    async def body() -> None:
        async with deferred_audit(session):  # type: ignore[arg-type]
            await _two_rows(session)
            raise ValueError("boom")

    with caplog.at_level(logging.WARNING, logger="app.core.audit_log"), pytest.raises(ValueError, match="boom"):
        await body()
    assert session.calls == []
    assert "dropped 2 deferred audit rows" in caplog.text
    assert session.info == {}
