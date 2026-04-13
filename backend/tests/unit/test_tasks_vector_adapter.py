"""Unit tests for :class:`TaskVectorAdapter`."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_TASKS
from app.modules.tasks.vector_adapter import (
    TaskVectorAdapter,
    task_vector_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "title": "Review structural drawings",
        "description": "Check rebar schedules and slab reinforcement",
        "task_type": "review",
        "status": "in_progress",
        "priority": "high",
        "checklist": [
            {"text": "Check rebar"},
            {"text": "Check slab edges"},
        ],
        "due_date": dt.date(2026, 5, 1),
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert task_vector_adapter.collection_name == COLLECTION_TASKS
    assert task_vector_adapter.module_name == "tasks"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = TaskVectorAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "Review structural drawings",
        "Check rebar schedules and slab reinforcement",
        "review",
        "in_progress",
        "high",
        "Check rebar",
        "Check slab edges",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = TaskVectorAdapter()
    row = _make_row(description="", task_type="", status="", priority="", checklist=[])
    text = adapter.to_text(row)
    assert "Review structural drawings" in text
    assert "review" not in text
    assert "high" not in text


def test_to_text_tolerates_none_on_optional_fields() -> None:
    adapter = TaskVectorAdapter()
    row = _make_row(
        description=None,
        task_type=None,
        status=None,
        priority=None,
        checklist=None,
    )
    text = adapter.to_text(row)
    assert "Review structural drawings" in text


def test_to_text_separator_uses_pipe() -> None:
    adapter = TaskVectorAdapter()
    assert " | " in adapter.to_text(_make_row())


def test_to_text_ignores_non_dict_checklist_items() -> None:
    adapter = TaskVectorAdapter()
    row = _make_row(checklist=["plain-string", {"text": "real item"}, 42])
    text = adapter.to_text(row)
    assert "real item" in text
    assert "plain-string" not in text


def test_to_text_ignores_checklist_items_without_text_key() -> None:
    adapter = TaskVectorAdapter()
    row = _make_row(checklist=[{"done": True}, {"text": "do the thing"}])
    text = adapter.to_text(row)
    assert "do the thing" in text


def test_to_text_checklist_non_list_ignored() -> None:
    adapter = TaskVectorAdapter()
    row = _make_row(checklist="not-a-list")
    text = adapter.to_text(row)
    assert "Review structural drawings" in text


# -- to_payload ------------------------------------------------------------


def test_to_payload_builds_title_from_task_title() -> None:
    adapter = TaskVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "Review structural drawings"
    assert payload["status"] == "in_progress"
    assert payload["task_type"] == "review"
    assert payload["priority"] == "high"


def test_to_payload_clips_long_title() -> None:
    adapter = TaskVectorAdapter()
    payload = adapter.to_payload(_make_row(title="x" * 500))
    assert len(payload["title"]) <= 160


def test_to_payload_empty_title_yields_empty() -> None:
    adapter = TaskVectorAdapter()
    payload = adapter.to_payload(_make_row(title=None))
    assert payload["title"] == ""


def test_to_payload_serialises_due_date_to_string() -> None:
    adapter = TaskVectorAdapter()
    payload = adapter.to_payload(_make_row(due_date=dt.date(2026, 12, 31)))
    assert payload["due_date"] == "2026-12-31"


def test_to_payload_empty_due_date_becomes_empty_string() -> None:
    adapter = TaskVectorAdapter()
    payload = adapter.to_payload(_make_row(due_date=None))
    assert payload["due_date"] == ""


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_returns_stringified_uuid() -> None:
    adapter = TaskVectorAdapter()
    project_id = uuid.uuid4()
    assert adapter.project_id_of(_make_row(project_id=project_id)) == str(project_id)


def test_project_id_of_returns_none_when_missing() -> None:
    adapter = TaskVectorAdapter()
    assert adapter.project_id_of(_make_row(project_id=None)) is None
