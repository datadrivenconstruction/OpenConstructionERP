"""Unit tests for :class:`ChatMessageAdapter`.

Chat messages are unusual: ``to_text`` returns an empty string for
rows whose role isn't user/assistant.  Several tests cover that skip
behaviour explicitly so a future refactor can't silently start
indexing system/tool noise.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_CHAT
from app.modules.erp_chat.vector_adapter import (
    ChatMessageAdapter,
    chat_message_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "role": "user",
        "content": "How much does the basement waterproofing cost on this project?",
        "session_id": uuid.uuid4(),
        "session": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert chat_message_adapter.collection_name == COLLECTION_CHAT
    assert chat_message_adapter.module_name == "chat"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_returns_content() -> None:
    adapter = ChatMessageAdapter()
    text = adapter.to_text(_make_row())
    assert text == "How much does the basement waterproofing cost on this project?"


def test_to_text_strips_whitespace() -> None:
    adapter = ChatMessageAdapter()
    text = adapter.to_text(_make_row(content="   hello world   \n"))
    assert text == "hello world"


def test_to_text_skips_system_role() -> None:
    """System messages are infrastructure noise and must be skipped."""
    adapter = ChatMessageAdapter()
    assert adapter.to_text(_make_row(role="system")) == ""


def test_to_text_skips_tool_role() -> None:
    adapter = ChatMessageAdapter()
    assert adapter.to_text(_make_row(role="tool")) == ""


def test_to_text_assistant_role_indexed() -> None:
    adapter = ChatMessageAdapter()
    text = adapter.to_text(_make_row(role="assistant", content="Sure, here is the answer."))
    assert text == "Sure, here is the answer."


def test_to_text_role_case_insensitive() -> None:
    adapter = ChatMessageAdapter()
    assert adapter.to_text(_make_row(role="USER", content="hi")) == "hi"
    assert adapter.to_text(_make_row(role="Assistant", content="hi")) == "hi"


def test_to_text_tolerates_none_content() -> None:
    adapter = ChatMessageAdapter()
    assert adapter.to_text(_make_row(content=None)) == ""


def test_to_text_tolerates_none_role() -> None:
    adapter = ChatMessageAdapter()
    assert adapter.to_text(_make_row(role=None)) == ""


def test_to_text_empty_content_returns_empty() -> None:
    adapter = ChatMessageAdapter()
    assert adapter.to_text(_make_row(content="")) == ""


# -- to_payload ------------------------------------------------------------


def test_to_payload_title_from_content() -> None:
    adapter = ChatMessageAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"].startswith("How much does the basement waterproofing")
    assert payload["role"] == "user"


def test_to_payload_title_clipped_to_120() -> None:
    adapter = ChatMessageAdapter()
    payload = adapter.to_payload(_make_row(content="x" * 500))
    assert len(payload["title"]) == 120


def test_to_payload_title_falls_back_when_content_empty() -> None:
    adapter = ChatMessageAdapter()
    payload = adapter.to_payload(_make_row(content="", role="user"))
    assert payload["title"] == "user message"


def test_to_payload_title_fallback_sentinel_when_role_also_missing() -> None:
    adapter = ChatMessageAdapter()
    payload = adapter.to_payload(_make_row(content="", role=None))
    assert payload["title"] == "message message"


def test_to_payload_stringifies_session_id() -> None:
    adapter = ChatMessageAdapter()
    session_id = uuid.uuid4()
    payload = adapter.to_payload(_make_row(session_id=session_id))
    assert payload["session_id"] == str(session_id)


def test_to_payload_empty_session_id_becomes_empty_string() -> None:
    adapter = ChatMessageAdapter()
    payload = adapter.to_payload(_make_row(session_id=None))
    assert payload["session_id"] == ""


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_reads_parent_session() -> None:
    adapter = ChatMessageAdapter()
    project_id = uuid.uuid4()
    row = _make_row(session=SimpleNamespace(project_id=project_id))
    assert adapter.project_id_of(row) == str(project_id)


def test_project_id_of_returns_none_when_session_missing() -> None:
    adapter = ChatMessageAdapter()
    assert adapter.project_id_of(_make_row(session=None)) is None


def test_project_id_of_returns_none_when_session_has_no_project() -> None:
    """Tenant-wide chats without a project still get indexed with None."""
    adapter = ChatMessageAdapter()
    row = _make_row(session=SimpleNamespace(project_id=None))
    assert adapter.project_id_of(row) is None
