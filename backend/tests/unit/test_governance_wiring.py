"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Governance wiring other modules and repo-wide guards depend on.

Three seams, each of which failed silently before it was pinned here: the
names governance publishes its events under, the subscribers surviving an
emptied event bus, and the language its export says it was written in.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections import defaultdict
from typing import Any

import pytest

from app.core.events import event_bus
from app.modules.project_governance import events, export, service

ROUTE_EVENTS = ("approval_routes.instance.completed", "approval_routes.instance.rejected")


def _published_names() -> list[str]:
    """First argument of every ``self._publish(...)`` call in the service, as written."""
    names: list[str] = []
    for node in ast.walk(ast.parse(inspect.getsource(service))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_publish":
            first = node.args[0]
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), ast.dump(first)
            names.append(first.value)
    return names


def test_every_event_is_published_under_its_full_name() -> None:
    """A subscriber matches by exact string, and so does the guard that looks for a publisher.

    A name assembled at run time from a prefix is invisible to both a reader
    and the dead-subscription scan, which then reports every module listening
    to governance as listening to nothing.
    """
    names = _published_names()
    assert len(names) >= 10
    assert [n for n in names if not n.startswith("project_governance.")] == []
    assert "project_governance.frame_document.state_changed" in names
    assert "project_governance.gate.submitted" in names


def test_the_publisher_adds_no_prefix_of_its_own() -> None:
    sent: list[tuple[Any, ...]] = []
    svc = service.GovernanceService.__new__(service.GovernanceService)
    svc.session = object()
    original = service.publish_after_commit
    service.publish_after_commit = lambda session, name, data, **kw: sent.append((name, data, kw))
    try:
        svc._publish("project_governance.gate.submitted", {"a": 1})
    finally:
        service.publish_after_commit = original
    assert sent == [("project_governance.gate.submitted", {"a": 1}, {"source_module": "project_governance"})]


@pytest.fixture
def empty_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(event_bus, "_handlers", defaultdict(list))


def _bound() -> list[int]:
    return [len(event_bus._handlers.get(name, [])) for name in ROUTE_EVENTS]


def test_the_subscribers_come_back_after_the_bus_was_emptied(empty_bus: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """An app restarted in one process empties the bus; the module must hear its events again."""
    seen: list[tuple[str, Any]] = []

    async def record(data: dict, *, decision: str, session_factory: Any = None) -> None:
        seen.append((decision, data.get("target_id")))

    monkeypatch.setattr(events, "handle_route_event", record)
    events.register_governance_subscribers()
    assert _bound() == [1, 1]
    # Registering twice binds nothing twice.
    events.register_governance_subscribers()
    assert _bound() == [1, 1]

    monkeypatch.setattr(event_bus, "_handlers", defaultdict(list))
    assert _bound() == [0, 0]
    events.register_governance_subscribers()
    assert _bound() == [1, 1]

    asyncio.run(event_bus.publish(ROUTE_EVENTS[0], {"target_id": "t1"}))
    asyncio.run(event_bus.publish(ROUTE_EVENTS[1], {"target_id": "t2"}))
    assert seen == [("approved", "t1"), ("rejected", "t2")]


@pytest.mark.parametrize(
    ("asked", "written"),
    [("en", "en"), ("de", "de"), ("fr", "fr"), ("", "en"), (None, "en"), ("zz", "en")],
)
def test_the_export_names_the_language_it_can_write(asked: str | None, written: str) -> None:
    """The bundle answers a missing locale in English, so that is what the header must say."""
    assert export.written_locale(asked) == written


def test_the_export_route_declares_its_language() -> None:
    from app.modules.project_governance import router

    source = inspect.getsource(router.export_trail)
    assert "Content-Language" in source and "written_locale" in source
