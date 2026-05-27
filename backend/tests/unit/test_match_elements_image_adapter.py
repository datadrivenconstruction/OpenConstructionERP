# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the Image source adapter.

The adapter delegates element extraction to the AI vision pipeline
(Claude / GPT-4V via :func:`app.modules.ai.ai_client.call_ai`). These
tests stub the AI call entirely so they run offline and don't require
an API key.

Coverage:

* Valid LLM response → ``SourceElement`` list with normalised
  attributes, quantities and ``ai_confidence="low"`` metadata.
* LLM returns ``[]`` (image is not a construction drawing) → empty
  list, no crash.
* LLM returns malformed JSON → empty list, no crash, no exception
  bubbled up.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.match_elements.sources.image_adapter import (
    ImageSourceAdapter,
    _coerce_ifc_class,
    _coerce_qty,
    _coerce_unit,
    _parse_ai_response,
    _quantities_for,
)

# ── Helpers ─────────────────────────────────────────────────────────────


# Minimal valid 1x1 PNG so ``base64.b64decode`` returns non-empty bytes
# and the resolver doesn't short-circuit. The byte content is irrelevant
# because the AI call is mocked out.
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


def _fake_session(metadata: dict[str, Any] | None) -> SimpleNamespace:
    """Build a duck-typed MatchSession stub.

    The image adapter only reads ``metadata_``, ``id`` and (optionally)
    ``created_by`` so a SimpleNamespace is enough — the SQLAlchemy
    attributes never get touched in adapter unit tests.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        metadata_=metadata,
        created_by=None,
    )


def _run(coro):
    """Synchronous wrapper for async adapter methods.

    A fresh event loop per call avoids ``RuntimeError: There is no
    current event loop`` when prior tests close their loop.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


PROJECT_ID = uuid.uuid4()


def _patch_extract(monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]):
    """Replace ``ImageSourceAdapter._extract_via_ai`` with an AsyncMock.

    Stubbing at the adapter layer (rather than at ``call_ai`` / settings
    repo) keeps the test independent of the AI module's internals — the
    contract under test is "given an image and an AI response, build
    SourceElements correctly", not "fully exercise the AI pipeline".
    """
    mock = AsyncMock(return_value=items)
    monkeypatch.setattr(
        ImageSourceAdapter,
        "_extract_via_ai",
        mock,
    )
    return mock


# ── Coercers ────────────────────────────────────────────────────────────


class TestCoercers:
    def test_ifc_class_passthrough(self):
        assert _coerce_ifc_class("IfcWall") == "IfcWall"
        assert _coerce_ifc_class("IfcSlab") == "IfcSlab"

    def test_ifc_class_case_recovery(self):
        assert _coerce_ifc_class("ifcwall") == "IfcWall"
        assert _coerce_ifc_class("IFCSLAB") == "IfcSlab"

    def test_ifc_class_drops_unknown(self):
        assert _coerce_ifc_class("IfcConcreteWall") is None
        assert _coerce_ifc_class("Wall") is None
        assert _coerce_ifc_class("null") is None
        assert _coerce_ifc_class("") is None
        assert _coerce_ifc_class(None) is None
        assert _coerce_ifc_class(42) is None

    def test_unit_normalisation(self):
        assert _coerce_unit("M3") == "m3"
        assert _coerce_unit("m²") == "m²"
        assert _coerce_unit("pcs") == "pcs"
        assert _coerce_unit("furlong") is None
        assert _coerce_unit("null") is None
        assert _coerce_unit("") is None
        assert _coerce_unit(None) is None

    def test_qty_coercion(self):
        assert _coerce_qty(12.5) == 12.5
        assert _coerce_qty(7) == 7.0
        assert _coerce_qty("12,5") == 12.5
        assert _coerce_qty("not a number") is None
        assert _coerce_qty(None) is None

    def test_quantities_for_units(self):
        assert _quantities_for("m3", 25.0) == {"count": 1.0, "volume_m3": 25.0}
        assert _quantities_for("m2", 100.0) == {"count": 1.0, "area_m2": 100.0}
        assert _quantities_for("m", 12.0) == {"count": 1.0, "length_m": 12.0}
        assert _quantities_for("pcs", 5) == {"count": 5.0}
        assert _quantities_for(None, 12.0) == {"count": 1.0}
        assert _quantities_for("m3", 0) == {"count": 1.0}


# ── _parse_ai_response ──────────────────────────────────────────────────


class TestParseAIResponse:
    def test_plain_array(self):
        items = _parse_ai_response('[{"name": "wall"}, {"name": "slab"}]')
        assert items == [{"name": "wall"}, {"name": "slab"}]

    def test_empty_array(self):
        assert _parse_ai_response("[]") == []

    def test_fenced_code_block(self):
        text = '```json\n[{"name": "door"}]\n```'
        assert _parse_ai_response(text) == [{"name": "door"}]

    def test_envelope_dict(self):
        # Some models wrap under {"elements": [...]}.
        text = '{"elements": [{"name": "beam"}]}'
        assert _parse_ai_response(text) == [{"name": "beam"}]

    def test_malformed_returns_empty(self):
        assert _parse_ai_response("not json at all") == []
        assert _parse_ai_response("") == []
        assert _parse_ai_response("[ malformed ") == []

    def test_drops_non_dict_items(self):
        items = _parse_ai_response('[{"name": "wall"}, "garbage", null, 42]')
        assert items == [{"name": "wall"}]


# ── ImageSourceAdapter ──────────────────────────────────────────────────


class TestImageSourceAdapterValidResponse:
    """End-to-end with a happy-path mocked LLM response."""

    def test_iter_elements_from_mocked_ai(self, monkeypatch: pytest.MonkeyPatch):
        sess = _fake_session(
            {
                "image": {
                    "data_b64": _TINY_PNG_B64,
                    "mime": "image/png",
                    "filename": "photo.png",
                }
            }
        )
        ai_items = [
            {
                "name": "Concrete wall",
                "ifc_class_guess": "IfcWall",
                "qty_estimate": 12.5,
                "unit_estimate": "m2",
                "material_guess": "concrete C30/37",
                "confidence": "medium",
            },
            {
                "name": "Door D1",
                "ifc_class_guess": "IfcDoor",
                "qty_estimate": 3,
                "unit_estimate": "pcs",
                "material_guess": None,
                "confidence": "high",
            },
        ]
        _patch_extract(monkeypatch, ai_items)

        adapter = ImageSourceAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))

        assert len(elements) == 2

        wall = elements[0]
        assert wall.category == "IfcWall"
        assert wall.name == "Concrete wall"
        assert wall.attributes["ifc_class"] == "IfcWall"
        assert wall.attributes["material"] == "concrete C30/37"
        # Always 'low' regardless of LLM-reported confidence — image is
        # an inherently noisy source.
        assert wall.attributes["ai_confidence"] == "low"
        assert wall.quantities["area_m2"] == 12.5
        assert wall.quantities["count"] == 1.0

        door = elements[1]
        assert door.category == "IfcDoor"
        assert door.attributes["ifc_class"] == "IfcDoor"
        assert door.quantities["count"] == 3.0
        # Material missing in input → no key polluting attrs.
        assert door.attributes["material"] is None

        # raw_ref should reference the session for back-linking.
        assert wall.raw_ref == str(sess.id)

    def test_list_categories(self, monkeypatch: pytest.MonkeyPatch):
        sess = _fake_session({"image": {"data_b64": _TINY_PNG_B64, "mime": "image/png"}})
        ai_items = [
            {"name": "w1", "ifc_class_guess": "IfcWall"},
            {"name": "w2", "ifc_class_guess": "IfcWall"},
            {"name": "d1", "ifc_class_guess": "IfcDoor"},
            {"name": "junk", "ifc_class_guess": "Garbage"},
        ]
        _patch_extract(monkeypatch, ai_items)

        adapter = ImageSourceAdapter(session=None, match_session=sess)
        cats = dict(_run(adapter.list_categories(PROJECT_ID)))
        # Unknown class falls back to "Image".
        assert cats == {"IfcWall": 2, "IfcDoor": 1, "Image": 1}

    def test_excluded_categories_filter(self, monkeypatch: pytest.MonkeyPatch):
        sess = _fake_session({"image": {"data_b64": _TINY_PNG_B64, "mime": "image/png"}})
        ai_items = [
            {"name": "wall", "ifc_class_guess": "IfcWall"},
            {"name": "furniture", "ifc_class_guess": "IfcFurniture"},
        ]
        _patch_extract(monkeypatch, ai_items)

        adapter = ImageSourceAdapter(session=None, match_session=sess)
        elements = _run(
            adapter.iter_elements(
                project_id=PROJECT_ID,
                excluded_categories=["IfcFurniture"],
            )
        )
        assert len(elements) == 1
        assert elements[0].category == "IfcWall"


class TestImageSourceAdapterEmptyResponse:
    """LLM returned ``[]`` because the image isn't a construction drawing."""

    def test_empty_list_from_ai_yields_no_elements(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        sess = _fake_session({"image": {"data_b64": _TINY_PNG_B64, "mime": "image/jpeg"}})
        _patch_extract(monkeypatch, [])

        adapter = ImageSourceAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        cats = _run(adapter.list_categories(PROJECT_ID))

        assert elements == []
        assert cats == []

    def test_no_session_returns_empty(self):
        # No mock needed — adapter short-circuits before touching AI.
        adapter = ImageSourceAdapter(session=None, match_session=None)
        assert _run(adapter.iter_elements(project_id=PROJECT_ID)) == []
        assert _run(adapter.list_categories(PROJECT_ID)) == []

    def test_no_image_metadata_returns_empty(self):
        sess = _fake_session({})  # metadata_ exists but no "image" key
        adapter = ImageSourceAdapter(session=None, match_session=sess)
        assert _run(adapter.iter_elements(project_id=PROJECT_ID)) == []

    def test_invalid_base64_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        # Image dict is shaped correctly but the bytes can't decode → []
        # without ever touching the AI service.
        sess = _fake_session({"image": {"data_b64": "", "mime": "image/png"}})
        # The AI mock should NOT be called because resolver returns None.
        mock = _patch_extract(monkeypatch, [{"name": "wall"}])

        adapter = ImageSourceAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))

        assert elements == []
        assert mock.call_count == 0


class TestImageSourceAdapterMalformedResponse:
    """LLM returned junk that's neither valid JSON nor a list."""

    def test_garbage_response_does_not_crash(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # Stub at the lower level — the LLM response is bad so the
        # parser must be exercised. We patch ``call_ai`` directly and
        # short-circuit the settings lookup so ``_extract_via_ai``
        # actually runs the parser.
        from app.modules.match_elements.sources import image_adapter

        sess = _fake_session({"image": {"data_b64": _TINY_PNG_B64, "mime": "image/png"}})

        # Bypass the settings-resolution branch by overriding
        # ``_extract_via_ai`` to return whatever the parser produces
        # for a malformed string. We re-implement the parser call so
        # the test still exercises real parsing logic.
        async def fake_extract(self, image_bytes, mime):  # noqa: ANN001
            return image_adapter._parse_ai_response("this is not json {not really at all")

        monkeypatch.setattr(
            ImageSourceAdapter,
            "_extract_via_ai",
            fake_extract,
        )

        adapter = ImageSourceAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        cats = _run(adapter.list_categories(PROJECT_ID))

        assert elements == []
        assert cats == []

    def test_partial_json_recoverable(self, monkeypatch: pytest.MonkeyPatch):
        # Markdown-wrapped JSON should still parse and produce elements.
        from app.modules.match_elements.sources import image_adapter

        sess = _fake_session({"image": {"data_b64": _TINY_PNG_B64, "mime": "image/png"}})

        async def fake_extract(self, image_bytes, mime):  # noqa: ANN001
            return image_adapter._parse_ai_response('```json\n[{"name": "wall", "ifc_class_guess": "IfcWall"}]\n```')

        monkeypatch.setattr(
            ImageSourceAdapter,
            "_extract_via_ai",
            fake_extract,
        )

        adapter = ImageSourceAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))

        assert len(elements) == 1
        assert elements[0].category == "IfcWall"


# ── Smoke: AI service unreachable (no key configured) ───────────────────


class TestImageSourceAdapterNoAIKey:
    def test_missing_ai_settings_returns_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """When :func:`resolve_provider_and_key` raises ``ValueError`` for
        every settings row (no API key), the adapter logs and returns
        ``[]`` — never raises and never bubbles a 5xx.
        """
        sess = _fake_session({"image": {"data_b64": _TINY_PNG_B64, "mime": "image/png"}})

        # Force the real ``_extract_via_ai`` path to execute by giving
        # it a session=None — the resolver returns an empty result and
        # the function returns [] cleanly.
        adapter = ImageSourceAdapter(session=None, match_session=sess)
        # Without a DB session, the adapter can't look up settings →
        # returns [] with a warning log.
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert elements == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
