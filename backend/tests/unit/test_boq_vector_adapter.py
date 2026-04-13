"""Unit tests for :class:`BOQPositionAdapter`.

Covers ``to_text``, ``to_payload`` and ``project_id_of`` using plain
duck-typed stubs — no database needed.  See
``test_requirements_vector_adapter.py`` for the canonical template.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_BOQ
from app.modules.boq.vector_adapter import (
    BOQPositionAdapter,
    boq_position_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    """Build a duck-typed Position row with the fields the adapter touches."""
    defaults = {
        "id": uuid.uuid4(),
        "description": "Reinforced concrete wall C30/37, 240mm",
        "ordinal": "01.02.003",
        "unit": "m2",
        "classification": {"din276": "330", "masterformat": "03 30 00"},
        "cost_code_id": None,
        "wbs_id": None,
        "boq_id": uuid.uuid4(),
        "validation_status": "passed",
        "source": "manual",
        "boq": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert boq_position_adapter.collection_name == COLLECTION_BOQ
    assert boq_position_adapter.module_name == "boq"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = BOQPositionAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "Reinforced concrete wall C30/37, 240mm",
        "[01.02.003]",
        "m2",
        "din276=330",
        "masterformat=03 30 00",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = BOQPositionAdapter()
    row = _make_row(ordinal="", unit="", classification={})
    text = adapter.to_text(row)
    assert "[]" not in text
    assert "din276=" not in text
    assert "Reinforced concrete wall C30/37, 240mm" in text


def test_to_text_tolerates_none_on_optional_fields() -> None:
    adapter = BOQPositionAdapter()
    row = _make_row(
        ordinal=None,
        unit=None,
        classification=None,
        cost_code_id=None,
        wbs_id=None,
    )
    text = adapter.to_text(row)
    assert "Reinforced concrete wall" in text


def test_to_text_skips_empty_classification_values() -> None:
    adapter = BOQPositionAdapter()
    row = _make_row(classification={"din276": "330", "nrm": "", "mf": None})
    text = adapter.to_text(row)
    assert "din276=330" in text
    assert "nrm=" not in text
    assert "mf=" not in text


def test_to_text_includes_cost_code_and_wbs_hints() -> None:
    adapter = BOQPositionAdapter()
    cost_code_id = uuid.uuid4()
    wbs_id = uuid.uuid4()
    text = adapter.to_text(_make_row(cost_code_id=cost_code_id, wbs_id=wbs_id))
    assert f"cost_code={cost_code_id}" in text
    assert f"wbs={wbs_id}" in text


def test_to_text_separator_uses_pipe() -> None:
    adapter = BOQPositionAdapter()
    assert " | " in adapter.to_text(_make_row())


def test_to_text_classification_not_dict_is_ignored() -> None:
    """If classification comes through as a non-dict it must not crash."""
    adapter = BOQPositionAdapter()
    text = adapter.to_text(_make_row(classification="not-a-dict"))
    assert "Reinforced concrete wall" in text


# -- to_payload ------------------------------------------------------------


def test_to_payload_builds_title_from_description() -> None:
    adapter = BOQPositionAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"].startswith("Reinforced concrete wall")
    assert payload["ordinal"] == "01.02.003"
    assert payload["unit"] == "m2"


def test_to_payload_clips_long_title() -> None:
    adapter = BOQPositionAdapter()
    payload = adapter.to_payload(_make_row(description="x" * 500))
    assert len(payload["title"]) <= 160


def test_to_payload_empty_description_yields_empty_title() -> None:
    adapter = BOQPositionAdapter()
    payload = adapter.to_payload(_make_row(description=None))
    assert payload["title"] == ""


def test_to_payload_stringifies_boq_id() -> None:
    adapter = BOQPositionAdapter()
    boq_id = uuid.uuid4()
    payload = adapter.to_payload(_make_row(boq_id=boq_id))
    assert payload["boq_id"] == str(boq_id)


def test_to_payload_empty_boq_id_becomes_empty_string() -> None:
    adapter = BOQPositionAdapter()
    payload = adapter.to_payload(_make_row(boq_id=None))
    assert payload["boq_id"] == ""


def test_to_payload_classification_is_copied_dict() -> None:
    adapter = BOQPositionAdapter()
    original = {"din276": "330"}
    payload = adapter.to_payload(_make_row(classification=original))
    assert payload["classification"] == {"din276": "330"}
    payload["classification"]["din276"] = "999"
    assert original["din276"] == "330"


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_reads_parent_boq() -> None:
    adapter = BOQPositionAdapter()
    project_id = uuid.uuid4()
    row = _make_row(boq=SimpleNamespace(project_id=project_id))
    assert adapter.project_id_of(row) == str(project_id)


def test_project_id_of_returns_none_when_boq_missing() -> None:
    adapter = BOQPositionAdapter()
    assert adapter.project_id_of(_make_row(boq=None)) is None


def test_project_id_of_returns_none_when_boq_has_no_project() -> None:
    adapter = BOQPositionAdapter()
    row = _make_row(boq=SimpleNamespace(project_id=None))
    assert adapter.project_id_of(row) is None
