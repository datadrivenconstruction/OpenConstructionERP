"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :class:`RFIVectorAdapter` (item 16)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_RFI
from app.modules.rfi.vector_adapter import (
    RFIVectorAdapter,
    rfi_vector_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "rfi_number": "RFI-007",
        "subject": "Rebar clash at grid C2",
        "question": "Beam reinforcement clashes with column starter bars",
        "official_response": "Use offset bend per detail S-204",
        "discipline": "structural",
        "status": "answered",
        "priority": "high",
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert rfi_vector_adapter.collection_name == COLLECTION_RFI
    assert rfi_vector_adapter.module_name == "rfi"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = RFIVectorAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "RFI-007",
        "Rebar clash at grid C2",
        "Beam reinforcement clashes with column starter bars",
        "Use offset bend per detail S-204",
        "structural",
        "answered",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = RFIVectorAdapter()
    row = _make_row(official_response=None, discipline="", status="")
    text = adapter.to_text(row)
    assert "Rebar clash at grid C2" in text
    assert "answered" not in text


def test_to_text_tolerates_none_on_optional_fields() -> None:
    adapter = RFIVectorAdapter()
    row = _make_row(question=None, official_response=None, discipline=None, status=None)
    text = adapter.to_text(row)
    assert "RFI-007" in text
    assert "Rebar clash at grid C2" in text


def test_to_text_separator_uses_pipe() -> None:
    adapter = RFIVectorAdapter()
    assert " | " in adapter.to_text(_make_row())


# -- to_payload ------------------------------------------------------------


def test_to_payload_prefers_subject_for_title() -> None:
    adapter = RFIVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "Rebar clash at grid C2"
    assert payload["rfi_number"] == "RFI-007"
    assert payload["status"] == "answered"
    assert payload["discipline"] == "structural"


def test_to_payload_falls_back_to_rfi_number() -> None:
    adapter = RFIVectorAdapter()
    payload = adapter.to_payload(_make_row(subject=None))
    assert payload["title"] == "RFI-007"


def test_to_payload_clips_long_title() -> None:
    adapter = RFIVectorAdapter()
    payload = adapter.to_payload(_make_row(subject="x" * 500))
    assert len(payload["title"]) <= 160


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_returns_stringified_uuid() -> None:
    adapter = RFIVectorAdapter()
    project_id = uuid.uuid4()
    assert adapter.project_id_of(_make_row(project_id=project_id)) == str(project_id)


def test_project_id_of_returns_none_when_missing() -> None:
    adapter = RFIVectorAdapter()
    assert adapter.project_id_of(_make_row(project_id=None)) is None
