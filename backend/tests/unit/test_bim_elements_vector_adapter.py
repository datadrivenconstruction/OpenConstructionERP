"""Unit tests for :class:`BIMElementVectorAdapter`."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_BIM_ELEMENTS
from app.modules.bim_hub.vector_adapter import (
    BIMElementVectorAdapter,
    bim_element_vector_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "name": "Exterior wall W-240",
        "element_type": "Wall",
        "category": "Walls",
        "discipline": "architectural",
        "storey": "Level 02",
        "properties": {
            "material": "concrete_c30_37",
            "family": "Basic Wall",
            "type": "Ext 240 Concrete",
            "classification": {"din276": "330"},
        },
        "model_id": uuid.uuid4(),
        "model": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert bim_element_vector_adapter.collection_name == COLLECTION_BIM_ELEMENTS
    assert bim_element_vector_adapter.module_name == "bim_elements"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = BIMElementVectorAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "Exterior wall W-240",
        "Wall",
        "Walls",
        "architectural",
        "storey=Level 02",
        "material=concrete_c30_37",
        "family=Basic Wall",
        "type=Ext 240 Concrete",
        "din276=330",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = BIMElementVectorAdapter()
    row = _make_row(
        element_type="",
        category="",
        discipline="",
        storey="",
        properties={},
    )
    text = adapter.to_text(row)
    assert "Exterior wall W-240" in text
    assert "storey=" not in text
    assert "material=" not in text


def test_to_text_tolerates_none_on_optional_fields() -> None:
    adapter = BIMElementVectorAdapter()
    row = _make_row(
        element_type=None,
        category=None,
        discipline=None,
        storey=None,
        properties=None,
    )
    text = adapter.to_text(row)
    assert "Exterior wall W-240" in text


def test_to_text_separator_uses_pipe() -> None:
    adapter = BIMElementVectorAdapter()
    assert " | " in adapter.to_text(_make_row())


def test_to_text_picks_up_capitalised_property_keys() -> None:
    """Properties may come from Revit with PascalCase keys."""
    adapter = BIMElementVectorAdapter()
    row = _make_row(
        properties={
            "Material": "steel_s235",
            "Family": "Structural Framing",
            "Type": "W12x26",
        },
    )
    text = adapter.to_text(row)
    assert "material=steel_s235" in text
    assert "family=Structural Framing" in text
    assert "type=W12x26" in text


def test_to_text_classification_as_string_accepted() -> None:
    adapter = BIMElementVectorAdapter()
    row = _make_row(properties={"classification": "330"})
    text = adapter.to_text(row)
    assert "classification=330" in text


def test_to_text_skips_empty_classification_values() -> None:
    adapter = BIMElementVectorAdapter()
    row = _make_row(properties={"classification": {"din276": "330", "nrm": ""}})
    text = adapter.to_text(row)
    assert "din276=330" in text
    assert "nrm=" not in text


def test_to_text_non_dict_properties_ignored() -> None:
    adapter = BIMElementVectorAdapter()
    row = _make_row(properties="not-a-dict")
    text = adapter.to_text(row)
    assert "Exterior wall W-240" in text


# -- to_payload ------------------------------------------------------------


def test_to_payload_builds_title_from_name() -> None:
    adapter = BIMElementVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "Exterior wall W-240"
    assert payload["element_type"] == "Wall"
    assert payload["category"] == "Walls"
    assert payload["discipline"] == "architectural"
    assert payload["storey"] == "Level 02"


def test_to_payload_falls_back_to_element_type_when_name_missing() -> None:
    adapter = BIMElementVectorAdapter()
    payload = adapter.to_payload(_make_row(name=None))
    assert payload["title"] == "Wall"


def test_to_payload_falls_back_to_id_when_name_and_type_missing() -> None:
    adapter = BIMElementVectorAdapter()
    row_id = uuid.uuid4()
    payload = adapter.to_payload(_make_row(id=row_id, name=None, element_type=None))
    assert payload["title"] == str(row_id)


def test_to_payload_clips_long_title() -> None:
    adapter = BIMElementVectorAdapter()
    payload = adapter.to_payload(_make_row(name="x" * 500))
    assert len(payload["title"]) <= 160


def test_to_payload_stringifies_model_id() -> None:
    adapter = BIMElementVectorAdapter()
    model_id = uuid.uuid4()
    payload = adapter.to_payload(_make_row(model_id=model_id))
    assert payload["model_id"] == str(model_id)


def test_to_payload_empty_model_id_becomes_empty_string() -> None:
    adapter = BIMElementVectorAdapter()
    payload = adapter.to_payload(_make_row(model_id=None))
    assert payload["model_id"] == ""


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_reads_parent_model() -> None:
    adapter = BIMElementVectorAdapter()
    project_id = uuid.uuid4()
    row = _make_row(model=SimpleNamespace(project_id=project_id))
    assert adapter.project_id_of(row) == str(project_id)


def test_project_id_of_returns_none_when_model_missing() -> None:
    adapter = BIMElementVectorAdapter()
    assert adapter.project_id_of(_make_row(model=None)) is None


def test_project_id_of_returns_none_when_model_has_no_project() -> None:
    adapter = BIMElementVectorAdapter()
    row = _make_row(model=SimpleNamespace(project_id=None))
    assert adapter.project_id_of(row) is None
