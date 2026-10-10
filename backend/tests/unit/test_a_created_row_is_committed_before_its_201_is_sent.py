"""A create is committed before the client is told it succeeded.

``SessionDep`` yields a session that commits after the path operation. With
FastAPI's default request scope (0.118 and later) that commit runs after the
response has been sent, so a client could receive its 201 and send the next
request (add a position to the BOQ it just created) before the BOQ row was
committed, and get "BOQ not found". The same ordering let a commit that failed
reach the client as a success.

The tests drive the raw ASGI app with a recording ``send`` and a stand-in
session factory, so the order of "commit" and "response start" is observed
directly instead of being raced against a real database.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, status

import app.dependencies as deps
from app.dependencies import SessionDep


class _FakeSession:
    def __init__(self, events: list[str], *, fail_commit: bool) -> None:
        self._events = events
        self._fail_commit = fail_commit

    async def commit(self) -> None:
        self._events.append("commit")
        if self._fail_commit:
            raise RuntimeError("commit refused")

    async def rollback(self) -> None:
        self._events.append("rollback")

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._events.append("close")


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/things", status_code=status.HTTP_201_CREATED)
    async def create_thing(session: SessionDep) -> dict[str, str]:
        return {"id": "1"}

    return app


async def _post(app: FastAPI, events: list[str]) -> None:
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/things",
        "raw_path": b"/things",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            events.append(f"response {message['status']}")

    await app(scope, receive, send)


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []
    monkeypatch.setattr(deps, "async_session_factory", lambda: _FakeSession(recorded, fail_commit=False))
    return recorded


async def test_the_session_is_committed_before_the_201_goes_out(events: list[str]) -> None:
    await _post(_app(), events)

    assert events == ["commit", "close", "response 201"]


async def test_a_failed_commit_is_not_answered_with_a_201(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(deps, "async_session_factory", lambda: _FakeSession(events, fail_commit=True))

    with pytest.raises(RuntimeError, match="commit refused"):
        await _post(_app(), events)

    assert "response 201" not in events
    assert events[:2] == ["commit", "rollback"]
    assert events[-1] == "response 500"


def test_every_session_dependency_is_declared_at_function_scope() -> None:
    """A bare ``Depends(get_session)`` would open a second, request-scoped session.

    FastAPI keys its per-request dependency cache on the scope, so the two would
    not be shared: two transactions in one request, one of them committed only
    after the response. Read from the source because module routers are mounted
    at startup, and importing all of them takes minutes.
    """
    import ast
    from pathlib import Path

    root = Path(deps.__file__).resolve().parent
    declared = []
    offenders = []
    for file in sorted(root.rglob("*.py")):
        text = file.read_text(encoding="utf-8")
        if "get_session" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Depends" and node.args):
                continue
            target = node.args[0]
            name = getattr(target, "id", None) or getattr(target, "attr", None)
            if name != "get_session":
                continue
            where = f"{file.relative_to(root)}:{node.lineno}"
            declared.append(where)
            scope = next((k.value for k in node.keywords if k.arg == "scope"), None)
            if not (isinstance(scope, ast.Constant) and scope.value == "function"):
                offenders.append(where)

    assert declared, "no Depends(get_session) found, the scan is not reading the source"
    assert offenders == []
