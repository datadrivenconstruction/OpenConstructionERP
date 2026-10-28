"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :class:`CorrespondenceVectorAdapter` (item 16)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_CORRESPONDENCE
from app.modules.correspondence.vector_adapter import (
    CorrespondenceVectorAdapter,
    correspondence_vector_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "reference_number": "COR-012",
        "subject": "Notice of delay - curtain wall delivery",
        "direction": "incoming",
        "correspondence_type": "notice",
        "notes": "Supplier confirms 3-week slip on facade panels",
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert correspondence_vector_adapter.collection_name == COLLECTION_CORRESPONDENCE
    assert correspondence_vector_adapter.module_name == "correspondence"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = CorrespondenceVectorAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "COR-012",
        "Notice of delay - curtain wall delivery",
        "incoming",
        "notice",
        "Supplier confirms 3-week slip on facade panels",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = CorrespondenceVectorAdapter()
    row = _make_row(notes=None, direction="")
    text = adapter.to_text(row)
    assert "Notice of delay - curtain wall delivery" in text
    assert "Supplier confirms" not in text


def test_to_text_separator_uses_pipe() -> None:
    adapter = CorrespondenceVectorAdapter()
    assert " | " in adapter.to_text(_make_row())


# -- to_payload ------------------------------------------------------------


def test_to_payload_prefers_subject() -> None:
    adapter = CorrespondenceVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "Notice of delay - curtain wall delivery"
    assert payload["reference_number"] == "COR-012"
    assert payload["direction"] == "incoming"
    assert payload["correspondence_type"] == "notice"


def test_to_payload_falls_back_to_reference_number() -> None:
    adapter = CorrespondenceVectorAdapter()
    payload = adapter.to_payload(_make_row(subject=None))
    assert payload["title"] == "COR-012"


def test_to_payload_clips_long_title() -> None:
    adapter = CorrespondenceVectorAdapter()
    payload = adapter.to_payload(_make_row(subject="x" * 500))
    assert len(payload["title"]) <= 160


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_returns_stringified_uuid() -> None:
    adapter = CorrespondenceVectorAdapter()
    project_id = uuid.uuid4()
    assert adapter.project_id_of(_make_row(project_id=project_id)) == str(project_id)


def test_project_id_of_returns_none_when_missing() -> None:
    adapter = CorrespondenceVectorAdapter()
    assert adapter.project_id_of(_make_row(project_id=None)) is None
