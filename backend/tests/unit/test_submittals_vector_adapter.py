"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :class:`SubmittalVectorAdapter` (item 16)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_SUBMITTALS
from app.modules.submittals.vector_adapter import (
    SubmittalVectorAdapter,
    submittal_vector_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "submittal_number": "SUB-005",
        "title": "Concrete mix design C30/37",
        "spec_section": "03 30 00",
        "submittal_type": "product_data",
        "status": "under_review",
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert submittal_vector_adapter.collection_name == COLLECTION_SUBMITTALS
    assert submittal_vector_adapter.module_name == "submittals"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = SubmittalVectorAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "SUB-005",
        "Concrete mix design C30/37",
        "03 30 00",
        "product_data",
        "under_review",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = SubmittalVectorAdapter()
    row = _make_row(spec_section=None, status="")
    text = adapter.to_text(row)
    assert "Concrete mix design C30/37" in text
    assert "under_review" not in text


def test_to_text_separator_uses_pipe() -> None:
    adapter = SubmittalVectorAdapter()
    assert " | " in adapter.to_text(_make_row())


# -- to_payload ------------------------------------------------------------


def test_to_payload_prefers_title() -> None:
    adapter = SubmittalVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "Concrete mix design C30/37"
    assert payload["submittal_number"] == "SUB-005"
    assert payload["status"] == "under_review"
    assert payload["spec_section"] == "03 30 00"


def test_to_payload_falls_back_to_number() -> None:
    adapter = SubmittalVectorAdapter()
    payload = adapter.to_payload(_make_row(title=None))
    assert payload["title"] == "SUB-005"


def test_to_payload_clips_long_title() -> None:
    adapter = SubmittalVectorAdapter()
    payload = adapter.to_payload(_make_row(title="x" * 500))
    assert len(payload["title"]) <= 160


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_returns_stringified_uuid() -> None:
    adapter = SubmittalVectorAdapter()
    project_id = uuid.uuid4()
    assert adapter.project_id_of(_make_row(project_id=project_id)) == str(project_id)


def test_project_id_of_returns_none_when_missing() -> None:
    adapter = SubmittalVectorAdapter()
    assert adapter.project_id_of(_make_row(project_id=None)) is None
