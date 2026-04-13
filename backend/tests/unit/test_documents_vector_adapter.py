"""Unit tests for :class:`DocumentVectorAdapter`.

Covers ``to_text``, ``to_payload`` and ``project_id_of`` using plain
duck-typed stubs — no database needed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_DOCUMENTS
from app.modules.documents.vector_adapter import (
    DocumentVectorAdapter,
    document_vector_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "name": "Structural rebar schedule L02",
        "description": "Schedule of reinforcement for level 02 slab",
        "category": "drawing",
        "tags": ["structural", "rebar", "L02"],
        "drawing_number": "S-201",
        "discipline": "structural",
        "file_name": "S-201-rebar.pdf",
        "file_path": "/uploads/drawings/S-201-rebar.pdf",
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert document_vector_adapter.collection_name == COLLECTION_DOCUMENTS
    assert document_vector_adapter.module_name == "documents"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = DocumentVectorAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "Structural rebar schedule L02",
        "Schedule of reinforcement for level 02 slab",
        "drawing",
        "structural rebar L02",
        "S-201",
        "S-201-rebar.pdf",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = DocumentVectorAdapter()
    row = _make_row(description="", category="", tags=[], drawing_number="")
    text = adapter.to_text(row)
    assert "Structural rebar schedule L02" in text
    assert "drawing" not in text
    assert "S-201 " not in text


def test_to_text_tolerates_none_on_optional_fields() -> None:
    adapter = DocumentVectorAdapter()
    row = _make_row(
        description=None,
        category=None,
        tags=None,
        drawing_number=None,
        discipline=None,
        file_name=None,
        file_path=None,
    )
    text = adapter.to_text(row)
    assert "Structural rebar schedule L02" in text


def test_to_text_separator_uses_pipe() -> None:
    adapter = DocumentVectorAdapter()
    assert " | " in adapter.to_text(_make_row())


def test_to_text_falls_back_to_basename_of_file_path() -> None:
    adapter = DocumentVectorAdapter()
    row = _make_row(file_name=None, file_path="/mnt/minio/docs/plan.dwg")
    text = adapter.to_text(row)
    assert "plan.dwg" in text


def test_to_text_ignores_tags_if_not_a_list() -> None:
    adapter = DocumentVectorAdapter()
    row = _make_row(tags="not-a-list")
    text = adapter.to_text(row)
    assert "not-a-list" not in text
    assert "Structural rebar schedule L02" in text


def test_to_text_joins_tags_space_separated() -> None:
    adapter = DocumentVectorAdapter()
    row = _make_row(tags=["a", "b", "c"])
    text = adapter.to_text(row)
    assert "a b c" in text


# -- to_payload ------------------------------------------------------------


def test_to_payload_builds_title_from_name() -> None:
    adapter = DocumentVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "Structural rebar schedule L02"
    assert payload["category"] == "drawing"
    assert payload["drawing_number"] == "S-201"
    assert payload["discipline"] == "structural"


def test_to_payload_clips_long_title() -> None:
    adapter = DocumentVectorAdapter()
    payload = adapter.to_payload(_make_row(name="x" * 500))
    assert len(payload["title"]) <= 160


def test_to_payload_empty_name_yields_empty_title() -> None:
    adapter = DocumentVectorAdapter()
    payload = adapter.to_payload(_make_row(name=None))
    assert payload["title"] == ""


def test_to_payload_file_name_falls_back_to_basename() -> None:
    adapter = DocumentVectorAdapter()
    payload = adapter.to_payload(
        _make_row(file_name=None, file_path="/var/docs/floorplan.pdf"),
    )
    assert payload["file_name"] == "floorplan.pdf"


def test_to_payload_file_name_empty_when_no_path() -> None:
    adapter = DocumentVectorAdapter()
    payload = adapter.to_payload(_make_row(file_name=None, file_path=None))
    assert payload["file_name"] == ""


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_returns_stringified_uuid() -> None:
    adapter = DocumentVectorAdapter()
    project_id = uuid.uuid4()
    assert adapter.project_id_of(_make_row(project_id=project_id)) == str(project_id)


def test_project_id_of_returns_none_when_missing() -> None:
    adapter = DocumentVectorAdapter()
    assert adapter.project_id_of(_make_row(project_id=None)) is None
