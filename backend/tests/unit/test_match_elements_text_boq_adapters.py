# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the Text and BoQ source adapters.

Both adapters are session-scoped readers — they pull their input data
from ``MatchSession.metadata_`` rather than a project-level table.
These tests validate:

* The Text adapter handles plain-string and dict-shaped inputs.
* The BoQ adapter maps unit strings onto canonical quantity dimensions.
* Filters / excluded categories work the same as on BIM/DWG adapters.
* Both gracefully return empty results when no session is bound.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.modules.match_elements.sources.boq_adapter import (
    BoqAdapter,
    _quantities_for,
    _to_float,
)
from app.modules.match_elements.sources.text_adapter import (
    TextAdapter,
    _coerce_text_input,
)

# ── Helpers ─────────────────────────────────────────────────────────────


def _fake_session(metadata: dict | None) -> SimpleNamespace:
    """Build a duck-typed MatchSession stub for adapter unit tests.

    We only need ``metadata_`` and ``id`` — the SQLAlchemy parts of
    MatchSession are irrelevant since these adapters never touch the DB.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        metadata_=metadata,
    )


def _run(coro):
    """Synchronous wrapper for async adapter methods.

    Uses a fresh event loop per call so a closed loop from a sibling
    test (or a worker that already finished) doesn't cause
    ``RuntimeError: There is no current event loop``.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


PROJECT_ID = uuid.uuid4()


# ── _coerce_text_input ──────────────────────────────────────────────────


class TestCoerceTextInput:
    def test_plain_string(self):
        assert _coerce_text_input("hello") == {"raw_text": "hello"}

    def test_blank_string_is_dropped(self):
        assert _coerce_text_input("") is None
        assert _coerce_text_input("   ") is None

    def test_dict_with_raw_text(self):
        out = _coerce_text_input({"raw_text": "wall", "project_country": "DE"})
        assert out == {"raw_text": "wall", "project_country": "DE"}

    def test_dict_with_text_alias(self):
        # ``text`` is an accepted alias for ``raw_text``.
        out = _coerce_text_input({"text": "ленточный фундамент"})
        assert out == {"raw_text": "ленточный фундамент"}

    def test_dict_blank_raw_text_is_dropped(self):
        assert _coerce_text_input({"raw_text": ""}) is None
        assert _coerce_text_input({"raw_text": "   "}) is None

    def test_garbage_input_is_dropped(self):
        assert _coerce_text_input(123) is None
        assert _coerce_text_input(None) is None
        assert _coerce_text_input([]) is None


# ── TextAdapter ─────────────────────────────────────────────────────────


class TestTextAdapter:
    def test_no_session_returns_empty(self):
        adapter = TextAdapter(session=None, match_session=None)
        assert _run(adapter.list_attribute_keys(PROJECT_ID)) == ["category", "ifc_class", "raw_text"]
        assert _run(adapter.list_categories(PROJECT_ID)) == []
        assert _run(adapter.iter_elements(project_id=PROJECT_ID)) == []

    def test_iter_elements_plain_strings(self):
        sess = _fake_session(
            {
                "text_inputs": [
                    "Stahlbetonwand C30/37, d=240mm",
                    "ленточный фундамент 800x600",
                    "concrete slab 200mm",
                ]
            }
        )
        adapter = TextAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert len(elements) == 3
        assert all(e.category == "Text" for e in elements)
        assert all(e.attributes["ifc_class"] == "Text" for e in elements)
        assert elements[1].attributes["raw_text"] == "ленточный фундамент 800x600"
        # Each element gets count=1 — semantic search drives recall.
        assert all(e.quantities == {"count": 1.0} for e in elements)

    def test_iter_elements_with_dict_inputs(self):
        sess = _fake_session(
            {
                "text_inputs": [
                    {"raw_text": "wall", "project_country": "DE", "category": "Wall"},
                    {"text": "slab", "category": "Floor"},
                ]
            }
        )
        adapter = TextAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert len(elements) == 2
        assert elements[0].category == "Wall"
        assert elements[0].attributes["project_country"] == "DE"
        assert elements[1].category == "Floor"

    def test_blank_inputs_are_dropped(self):
        sess = _fake_session({"text_inputs": ["valid", "", "   ", None, 42]})
        adapter = TextAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert len(elements) == 1
        assert elements[0].attributes["raw_text"] == "valid"

    def test_excluded_categories_filter(self):
        sess = _fake_session(
            {
                "text_inputs": [
                    {"raw_text": "wall", "category": "Wall"},
                    {"raw_text": "floor", "category": "Floor"},
                ]
            }
        )
        adapter = TextAdapter(session=None, match_session=sess)
        elements = _run(
            adapter.iter_elements(
                project_id=PROJECT_ID,
                excluded_categories=["Floor"],
            )
        )
        assert len(elements) == 1
        assert elements[0].category == "Wall"

    def test_filters_attribute_match(self):
        sess = _fake_session(
            {
                "text_inputs": [
                    {"raw_text": "wall A", "category": "Wall", "project_country": "DE"},
                    {"raw_text": "wall B", "category": "Wall", "project_country": "BR"},
                ]
            }
        )
        adapter = TextAdapter(session=None, match_session=sess)
        elements = _run(
            adapter.iter_elements(
                project_id=PROJECT_ID,
                filters={"project_country": ["DE"]},
            )
        )
        assert len(elements) == 1
        assert elements[0].attributes["project_country"] == "DE"

    def test_list_categories_groups_correctly(self):
        sess = _fake_session(
            {
                "text_inputs": [
                    {"raw_text": "a", "category": "Wall"},
                    {"raw_text": "b", "category": "Wall"},
                    {"raw_text": "c", "category": "Floor"},
                    {"raw_text": "d"},  # defaults to "Text"
                ]
            }
        )
        adapter = TextAdapter(session=None, match_session=sess)
        cats = _run(adapter.list_categories(PROJECT_ID))
        assert dict(cats) == {"Wall": 2, "Floor": 1, "Text": 1}

    def test_malformed_metadata_returns_empty(self):
        # text_inputs as a non-list dict shouldn't crash.
        sess = _fake_session({"text_inputs": {"oops": "wrong shape"}})
        adapter = TextAdapter(session=None, match_session=sess)
        assert _run(adapter.iter_elements(project_id=PROJECT_ID)) == []

        # metadata_ entirely missing.
        sess2 = _fake_session(None)
        adapter2 = TextAdapter(session=None, match_session=sess2)
        assert _run(adapter2.iter_elements(project_id=PROJECT_ID)) == []


# ── _to_float ───────────────────────────────────────────────────────────


class TestToFloat:
    def test_numeric_passthrough(self):
        assert _to_float(12.3) == 12.3
        assert _to_float(7) == 7.0

    def test_string_decimal_point(self):
        assert _to_float("12.3") == 12.3

    def test_string_decimal_comma(self):
        assert _to_float("12,3") == 12.3

    def test_string_with_unit_tail(self):
        assert _to_float("12.3 m³") == 12.3
        assert _to_float("125,5 кг") == 125.5

    def test_blank_returns_none(self):
        assert _to_float("") is None
        assert _to_float("   ") is None
        assert _to_float(None) is None

    def test_negative(self):
        assert _to_float("-5.0") == -5.0


# ── _quantities_for (BoQ) ───────────────────────────────────────────────


class TestQuantitiesFor:
    def test_volume(self):
        qty = _quantities_for("m3", 25.5)
        assert qty["volume_m3"] == 25.5
        assert qty["count"] == 1.0

    def test_area(self):
        assert _quantities_for("m2", 100.0)["area_m2"] == 100.0
        assert _quantities_for("м²", 100.0)["area_m2"] == 100.0

    def test_length(self):
        assert _quantities_for("m", 12.5)["length_m"] == 12.5

    def test_mass_kg_passthrough(self):
        assert _quantities_for("kg", 250.0)["mass_kg"] == 250.0

    def test_mass_tonnes_to_kg(self):
        # 2.5 t → 2500 kg
        qty = _quantities_for("t", 2.5)
        assert qty["mass_kg"] == 2500.0

    def test_count(self):
        qty = _quantities_for("pcs", 7)
        assert qty["count"] == 7.0

    def test_unknown_unit_keeps_count(self):
        qty = _quantities_for("furlong", 12.0)
        assert qty == {"count": 1.0}

    def test_blank_unit(self):
        assert _quantities_for(None, 12.0) == {"count": 1.0}
        assert _quantities_for("", 12.0) == {"count": 1.0}

    def test_zero_qty_keeps_count(self):
        assert _quantities_for("m3", 0)["count"] == 1.0
        assert "volume_m3" not in _quantities_for("m3", 0)


# ── BoqAdapter ──────────────────────────────────────────────────────────


class TestBoqAdapter:
    def test_no_session_returns_empty(self):
        adapter = BoqAdapter(session=None, match_session=None)
        assert _run(adapter.iter_elements(project_id=PROJECT_ID)) == []
        assert _run(adapter.list_categories(PROJECT_ID)) == []

    def test_iter_elements_basic(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "Concrete wall C30/37", "qty": 25.0, "unit": "m3"},
                    {"description": "Plaster work", "qty": 100, "unit": "m2"},
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert len(elements) == 2
        assert elements[0].quantities["volume_m3"] == 25.0
        assert elements[1].quantities["area_m2"] == 100.0
        assert elements[0].attributes["description"] == "Concrete wall C30/37"

    def test_exact_code_shortcut(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "Wall", "qty": 5, "unit": "m3", "code": "FER46-001-1"},
                    {"description": "Slab", "qty": 10, "unit": "m3", "rate_code": "FER46-002"},
                    {"description": "No code", "qty": 1, "unit": "m"},
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert elements[0].attributes["exact_code"] == "FER46-001-1"
        assert elements[1].attributes["exact_code"] == "FER46-002"
        assert "exact_code" not in elements[2].attributes

    def test_category_grouping(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "a", "qty": 1, "unit": "m", "category": "Walls"},
                    {"description": "b", "qty": 1, "unit": "m", "section": "Floors"},
                    {"description": "c", "qty": 1, "unit": "m"},  # default → "BoQ"
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        cats = dict(_run(adapter.list_categories(PROJECT_ID)))
        assert cats == {"Walls": 1, "Floors": 1, "BoQ": 1}

    def test_filters_apply(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "DE row", "qty": 1, "unit": "m", "source_lang": "de"},
                    {"description": "RU row", "qty": 1, "unit": "m", "source_lang": "ru"},
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(
            adapter.iter_elements(
                project_id=PROJECT_ID,
                filters={"source_lang": ["de"]},
            )
        )
        assert len(elements) == 1
        assert elements[0].attributes["source_lang"] == "de"

    def test_excluded_categories(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "Keep", "qty": 1, "unit": "m", "category": "Walls"},
                    {"description": "Drop", "qty": 1, "unit": "m", "category": "Site"},
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(
            adapter.iter_elements(
                project_id=PROJECT_ID,
                excluded_categories=["Site"],
            )
        )
        assert len(elements) == 1
        assert elements[0].attributes["description"] == "Keep"

    def test_string_qty_with_decimal_comma(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "Comma decimal", "qty": "12,5", "unit": "m3"},
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert elements[0].quantities["volume_m3"] == 12.5

    def test_list_attribute_keys_drops_qty(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "x", "qty": 1, "unit": "m3", "supplier": "Acme"},
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        keys = _run(adapter.list_attribute_keys(PROJECT_ID))
        # qty/quantity must not appear — they're quantities, not group-by.
        assert "qty" not in keys
        assert "quantity" not in keys
        # All non-qty keys surface.
        assert "supplier" in keys
        assert "description" in keys
        assert "unit" in keys

    def test_malformed_rows_are_skipped(self):
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "good", "qty": 1, "unit": "m3"},
                    "not-a-dict",
                    None,
                    42,
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert len(elements) == 1

    def test_ifc_class_not_promoted_from_synthetic_category(self):
        # ``category`` on a BoQ row is operator-facing free text — NOT
        # an IFC class name. Previously the adapter promoted it onto
        # ``ifc_class`` which then got forwarded as a hard Qdrant filter
        # and eliminated every CWICR candidate row (see
        # ``match_elements_three_filter_bugs`` memory). Verify the
        # synthetic label is no longer mirrored.
        sess = _fake_session(
            {
                "boq_rows": [
                    {"description": "x", "qty": 1, "unit": "m3", "category": "Wall"},
                    {"description": "y", "qty": 1, "unit": "m3"},  # default "BoQ" cat
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        # category still surfaces verbatim — it just doesn't masquerade
        # as an IFC class.
        assert elements[0].attributes["category"] == "Wall"
        assert "ifc_class" not in elements[0].attributes
        assert elements[1].attributes["category"] == "BoQ"
        assert "ifc_class" not in elements[1].attributes

    def test_ifc_class_forwarded_when_row_carries_one(self):
        # When the BoQ row explicitly carries a real IFC class (e.g. the
        # estimator exported a pre-classified BoQ from a BIM tool), the
        # adapter MUST forward it so the downstream Qdrant filter narrows
        # to the right element family.
        sess = _fake_session(
            {
                "boq_rows": [
                    {
                        "description": "Cast-in-place concrete wall",
                        "qty": 25,
                        "unit": "m3",
                        "ifc_class": "IfcWall",
                    },
                    {
                        "description": "Pre-cast slab",
                        "qty": 100,
                        "unit": "m2",
                        "ifc_class": "IfcSlab",
                        "category": "Floors",
                    },
                    {
                        "description": "garbage value should be rejected",
                        "qty": 1,
                        "unit": "m",
                        "ifc_class": "BoQ",  # not Ifc-prefixed → rejected
                    },
                ]
            }
        )
        adapter = BoqAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert elements[0].attributes["ifc_class"] == "IfcWall"
        assert elements[1].attributes["ifc_class"] == "IfcSlab"
        # The non-Ifc-prefixed value is filtered out — the downstream
        # envelope builder applies the same guard but the adapter
        # should not have written it in the first place.
        assert "ifc_class" not in elements[2].attributes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
