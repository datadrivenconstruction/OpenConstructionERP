"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Access-control tests for the erp_chat semantic-search tools (item 16).

The per-module search tools (``search_rfis`` / ``search_submittals`` /
``search_correspondence`` and their siblings) and ``search_anything`` must
enforce the same project-access posture as the REST ``/search`` endpoint:

* a supplied ``project_id`` is verified via ``_require_project_access``
  before any data is touched (otherwise a chat user could enumerate any
  project by guessing its UUID — the unified service trusts a supplied
  project_id and skips its own fence);
* when no ``project_id`` is given, ``user_id`` is threaded through to the
  service so the cross-project search is fenced to the caller's accessible
  projects instead of running as an unrestricted admin.

These tests monkeypatch the search service and the access helper so they
exercise only the wiring in ``erp_chat/tools.py`` — no DB, no vector store.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.erp_chat import tools
from app.modules.erp_chat.tools import (
    ToolAuthError,
    handle_search_anything,
    handle_search_correspondence,
    handle_search_rfis,
    handle_search_submittals,
)


class _FakeResponse:
    """Minimal stand-in for ``UnifiedSearchResponse``."""

    def __init__(self) -> None:
        self.hits: list[Any] = []
        self.total = 0
        self.facets: dict[str, int] = {}


@pytest.fixture
def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the unified search service and capture its kwargs."""
    captured: dict[str, Any] = {}

    async def _fake_unified_search_service(**kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _FakeResponse()

    import app.modules.search.service as search_service

    monkeypatch.setattr(
        search_service,
        "unified_search_service",
        _fake_unified_search_service,
    )
    return captured


@pytest.fixture
def _allow_access(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(session: Any, project_id: Any, user_id: Any) -> None:
        return None

    monkeypatch.setattr(tools, "_require_project_access", _ok)


@pytest.fixture
def _deny_access(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _deny(session: Any, project_id: Any, user_id: Any) -> None:
        raise ToolAuthError(f"Project {project_id} not found")

    monkeypatch.setattr(tools, "_require_project_access", _deny)


_SESSION = object()
_USER = str(uuid.uuid4())


@pytest.mark.parametrize(
    ("handler", "short_type"),
    [
        (handle_search_rfis, "rfi"),
        (handle_search_submittals, "submittals"),
        (handle_search_correspondence, "correspondence"),
    ],
)
async def test_unscoped_search_threads_user_id(
    _capture: dict[str, Any],
    handler: Any,
    short_type: str,
) -> None:
    """A search with no project_id must pass user_id to the fence."""
    result = await handler(_SESSION, {"query": "waterproofing"}, _USER)
    assert _capture["user_id"] == _USER
    assert _capture["types"] == [short_type]
    assert _capture["project_id"] is None
    assert result["renderer"] == "semantic_search"


@pytest.mark.parametrize(
    "handler",
    [handle_search_rfis, handle_search_submittals, handle_search_correspondence],
)
async def test_scoped_search_verifies_access_then_forwards(
    _capture: dict[str, Any],
    _allow_access: None,
    handler: Any,
) -> None:
    """When access passes, the project filter is forwarded to the service."""
    pid = str(uuid.uuid4())
    await handler(_SESSION, {"query": "concrete", "project_id": pid}, _USER)
    assert _capture["project_id"] == pid
    assert _capture["user_id"] == _USER


@pytest.mark.parametrize(
    "handler",
    [handle_search_rfis, handle_search_submittals, handle_search_correspondence],
)
async def test_scoped_search_denied_returns_error_without_querying(
    _capture: dict[str, Any],
    _deny_access: None,
    handler: Any,
) -> None:
    """A project the caller cannot see yields an error result and never hits
    the search service (no leak of project existence)."""
    pid = str(uuid.uuid4())
    result = await handler(_SESSION, {"query": "anything", "project_id": pid}, _USER)
    assert result["renderer"] == "error"
    # The search service must not have been invoked.
    assert _capture == {}


async def test_search_anything_threads_user_id(_capture: dict[str, Any]) -> None:
    await handle_search_anything(_SESSION, {"query": "delay"}, _USER)
    assert _capture["user_id"] == _USER
    assert _capture["project_id"] is None


async def test_search_anything_denied_project(
    _capture: dict[str, Any],
    _deny_access: None,
) -> None:
    pid = str(uuid.uuid4())
    result = await handle_search_anything(_SESSION, {"query": "x", "project_id": pid}, _USER)
    assert result["renderer"] == "error"
    assert _capture == {}
