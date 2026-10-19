"""Deleting a chat removes its messages from the search index too.

Every chat message is embedded into the ``oe_chat`` vector collection, which
global search reads. ``erp_chat/events.py`` subscribed a delete handler to
``erp_chat.message.deleted``, but deleting a session cascaded its messages away
in the database and published nothing, so a conversation the user deleted
could still be found from the search box.

The test deletes a session through the real service, captures what it
publishes, and hands that to the handlers the module registered on the bus at
import.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

import app.modules.erp_chat.events as chat_events
from app.core.events import Event, event_bus
from app.modules.erp_chat.service import ERPChatService

OWNER = str(uuid.uuid4())
MESSAGES = [uuid.uuid4(), uuid.uuid4()]


class _Result:
    def __init__(self, one: Any = None, many: list[Any] | None = None) -> None:
        self._one = one
        self._many = many or []

    def scalar_one_or_none(self) -> Any:
        return self._one

    def scalars(self) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: list(self._many))


class _StubSession:
    """Answers the session lookup, then the message id lookup, in that order."""

    def __init__(self, chat_session: Any) -> None:
        self._results = [_Result(one=chat_session), _Result(many=MESSAGES)]
        self.deleted: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        return self._results.pop(0) if self._results else _Result()

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        return None


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    def _capture(name: str, data: dict[str, Any] | None = None, source_module: str | None = None) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(event_bus, "publish_detached", _capture)
    return seen


@pytest.fixture
def removed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    gone: list[str] = []

    async def _delete_one(adapter: Any, row_id: str) -> None:
        gone.append(row_id)

    monkeypatch.setattr(chat_events, "vector_delete_one", _delete_one)
    return gone


@pytest.mark.asyncio
async def test_deleting_a_chat_session_drops_every_message_from_the_index(published, removed) -> None:
    chat_session = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4())
    service = ERPChatService.__new__(ERPChatService)
    service.session = _StubSession(chat_session)

    assert await service.delete_session(chat_session.id, OWNER) is True
    assert service.session.deleted == [chat_session]

    deleted = [(name, data) for name, data in published if name == "erp_chat.message.deleted"]
    assert sorted(data["message_id"] for _, data in deleted) == sorted(str(m) for m in MESSAGES)

    # The handlers the module registered at import, under the published name.
    handlers = event_bus._handlers.get("erp_chat.message.deleted", [])
    assert chat_events._on_message_deleted in handlers
    for name, data in deleted:
        for handler in handlers:
            await handler(Event(name=name, data=data, source_module="test"))

    assert sorted(removed) == sorted(str(m) for m in MESSAGES)


@pytest.mark.asyncio
async def test_a_session_that_is_not_yours_deletes_and_announces_nothing(published, removed) -> None:
    service = ERPChatService.__new__(ERPChatService)
    service.session = _StubSession(None)

    assert await service.delete_session(uuid.uuid4(), OWNER) is False
    assert published == []
